def toponym_context(city, cfg=None):
    """Everything rule t3 needs about a city: home regions, countries, common words, banned names."""
    cfg = cfg or {}
    try:
        ccs = city_countries(city, cfg)
    except KeyError:
        ccs = []
    home = home_regions(city, cfg)
    lang = cfg.get("lang", "en")
    common = COMMON_WORDS.get(lang, frozenset()) | COMMON_WORDS["en"] | (COMMON_WORDS["ca"] if lang == "es" else frozenset())
    own = {_norm_place(c) for c in _country_forms(ccs)}
    banned = (COUNTRY_NAMES | CONTINENT_NAMES | set().union(*[HOME_ADMIN1.get(c, frozenset()) for c in ccs])) - home
    return dict(ccs=ccs, home=home, common=common, own=own, banned=banned, rx={})


def toponym_verdict(place, text, tc, strict=False):
    """None if the name is kept, else the reason ('name' or 'occurrence'). strict=True adds the t5 test (see
    _occurrence_ok): a structured location counts only if the name is the whole first component."""
    key = _norm_place(place)
    if key in tc["banned"] or key in tc["own"] or key in FLOOD_NAME_WORDS:
        return "name"
    k = str(place).lower().strip()
    rx = tc["rx"].get(k) or tc["rx"].setdefault(k, re.compile(r"(?<![\w])" + re.escape(k) + r"(?![\w])", re.I))
    t = str(text or "")
    if not any(_occurrence_ok(t, mm.start(), mm.end(), tc["home"], tc["ccs"], tc["common"], strict=strict)
               for mm in rx.finditer(t)):
        return "occurrence"
    return None


TEXT_RESOLVED = ("gazetteer", "ner+nominatim", "ner+gazetteer")      # paths that place a NAME found in text


def mention_verdict(place, text, tc, via="gazetteer", strict=True):
    """toponym_verdict for a stored mention. A 'ner+gazetteer' mention carries the gazetteer's spelling of a name
    that NER found in another spelling ("Sao Joao" in the text, "São João" in the gazetteer), so the name is also
    looked for accent-insensitively and the rule is applied to the spelling the text actually uses."""
    v = toponym_verdict(place, text, tc, strict=strict)
    if not v or via != "ner+gazetteer":
        return v
    key, t = _norm_place(place), str(text or "")
    n = len(key.split())
    words = list(_WORD.finditer(t))
    seen = set()
    for i in range(len(words) - n + 1):
        surface = t[words[i].start():words[i + n - 1].end()]
        if surface in seen or _norm_place(surface) != key:
            continue
        seen.add(surface)
        if toponym_verdict(surface, t, tc, strict=strict) is None:
            return None
    return v


def refine_gazetteer_mentions(mentions, city, cfg=None, log=None):
    """The toponym rule (see above) on every mention that was placed from a NAME in the text: gazetteer names and,
    since t4, NER names. Geotagged mentions pass unchanged. Returns (kept, stats). A subset filter: it never adds
    a mention, so inputs acquired under an older rule can be corrected without the network. Idempotent on inputs
    resolved under the current rule. The stored text is entity-decoded first, as it is at acquisition."""
    if mentions is None or len(mentions) == 0 or "via" not in mentions:
        return mentions, dict(rules=TOPONYM_RULES_VERSION, checked=0, dropped=0)
    tc = toponym_context(city, cfg)
    keep = np.ones(len(mentions), bool)
    why = []
    for i, (via, place, text) in enumerate(zip(mentions["via"], mentions["place"], mentions["text"])):
        if via not in TEXT_RESOLVED:
            continue
        text = clean_text(text)
        v = mention_verdict(place, text, tc, via=via, strict=True)
        if v:
            keep[i] = False; why.append((v, place, via))
    out = mentions[keep].reset_index(drop=True)
    w = pd.DataFrame(why, columns=["rule", "place", "via"])
    stats = dict(rules=TOPONYM_RULES_VERSION, checked=int(mentions["via"].isin(TEXT_RESOLVED).sum()),
                 dropped=int((~keep).sum()), kept=int(len(out)),
                 dropped_by_rule=w["rule"].value_counts().to_dict() if len(w) else {},
                 dropped_by_path=w["via"].value_counts().to_dict() if len(w) else {},
                 top_dropped=[(str(a), int(b)) for a, b in w["place"].value_counts().head(8).items()] if len(w) else [])
    if log is not None:
        log(city, "social:toponyms", "info" if stats["dropped"] < 0.2 * max(len(mentions), 1) else "warn",
            f"rule {TOPONYM_RULES_VERSION}: {stats['dropped']} of {len(mentions)} mentions dropped (not a complete place "
            f"name placed in the study area; {stats['dropped_by_rule']}); most dropped: {stats['top_dropped']}")
    return out, stats


def score_emotion(mentions, sentiment=None, batch=32, lang="en"):
    """negativity in [0,1]: GDELT tone if present, else transformer negative probability.
    distress in {0,1}: transparent lexicon. Both are per document."""
    if mentions is None or len(mentions) == 0:
        return mentions
    m = mentions.copy()
    neg = np.clip(-pd.to_numeric(m["tone"], errors="coerce") / 10.0, 0, 1)
    need = neg.isna()
    if need.any() and sentiment is not None:
        texts = m.loc[need, "text"].str.slice(0, 512).tolist()
        uniq = list(dict.fromkeys(texts))
        scores = {}
        for k in range(0, len(uniq), batch):
            chunk = uniq[k:k + batch]
            try:
                out = sentiment(chunk, truncation=True, top_k=None)
            except TypeError:
                out = sentiment(chunk, truncation=True, return_all_scores=True)
            for t, o in zip(chunk, out):
                d = {x["label"].lower(): x["score"] for x in o}
                scores[t] = d.get("negative", d.get("label_0", np.nan))
        neg.loc[need] = [scores.get(t, np.nan) for t in texts]
    m["negativity"] = neg.astype(float)
    m["distress"] = m["text"].fillna("").str.contains(distress_regex(lang)).astype(float)
    return m


def social_channels(G, df, mentions, bandwidth_m, min_source_mentions=10):
    """Density surfaces (log1p mentions/km^2): all mentions, negativity-weighted,
    distress-weighted, and one per source with enough mentions."""
    from pyproj import Transformer
    ch, stats = {}, {}
    if mentions is None or len(mentions) == 0:
        ch["S_mentions"] = np.zeros(len(df))
        return ch, dict(mentions=0)
    tx, ty = Transformer.from_crs("EPSG:4326", G.crs, always_xy=True).transform(mentions["lon"].to_numpy(), mentions["lat"].to_numpy())

    def surf(w):
        dens, n_in = ph.mention_kde(G, tx, ty, np.nan_to_num(np.asarray(w, float)), bandwidth_m)
        return np.log1p(ph.raster_to_cells(dens, df)), n_in
    ch["S_mentions"], n_in = surf(np.ones(len(mentions)))
    stats.update(mentions=len(mentions), mentions_in_grid=n_in, cells_with_signal=int((ch["S_mentions"] > 1e-9).sum()))
    if "negativity" in mentions and mentions["negativity"].notna().mean() > 0.5:
        ch["S_negative"], _ = surf(mentions["negativity"].fillna(mentions["negativity"].median()))
    if "distress" in mentions and mentions["distress"].sum() >= 5:
        ch["S_distress"], _ = surf(mentions["distress"])
    for src, n in mentions["source"].value_counts().items():
        if n >= min_source_mentions:
            ch[f"S_src_{src}"], _ = surf((mentions["source"] == src).astype(float))
    stats["by_source"] = mentions["source"].value_counts().to_dict()
    stats["by_resolution"] = mentions["via"].value_counts().to_dict() if "via" in mentions else {}
    return ch, stats
