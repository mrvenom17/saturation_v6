# ---------------------------------------------------------------- toponym rule t3 (v5.5.3)
# The Houston acquisition (v5.5.2) showed what word-boundary gazetteer matching still lets through: GDELT's
# location strings name counties, creeks, states and countries, and a small same-named hamlet inside the study
# area catches them ("Montgomery County, Texas" -> Montgomery; "Egypt" -> Egypt, TX). The other cities add
# common words that are also place names ("fiume" = river, "quattro" = four, "dique" = dike) and same-named
# places in other states ("Sao Joao, Piauhy, Brazil"). Rule t3 keeps a gazetteer mention only if the text holds
# at least one occurrence of the name that is either
#   (a) a GDELT-structured location placed in the study area: "<name>, <home region>[, <home country>]" or
#       "<name>, <home country>" (GDELT's own geocoder has already resolved it), or
#   (b) a capitalised prose occurrence that is a complete name (no adjacent feature word or name particle,
#       no adjacent capitalised word outside title-case headlines), is not followed by a qualifier placing it
#       elsewhere, and is not a common word of the city's language or English (Zipf >= 4.5);
# and the name itself is not a country, a continent or a first-level division of the study country.
# Lower-case occurrences (URL words, lower-cased text) never count on their own: they carry no evidence of
# being a name. Applied to the stored mentions at analysis time (a subset filter: it never adds a mention), so
# inputs already acquired under g2 need no new network run. Documents whose candidates are all rejected are not
# re-sent to NER. (Rule t2, a draft of this rule, was replaced before it produced any result.)
TOPONYM_RULES_VERSION = "t3"
from toponym_data import COMMON_WORDS, COUNTRY_NAMES, HOME_ADMIN1   # noqa: E402  (frozen lists)
# v5.5.3 toponym lists, generated once from pycountry 24.6.1 (ISO 3166-1 country names; top-level ISO 3166-2
# subdivisions of the study countries), normalised with _norm_place. Frozen here so every run uses the same lists.

# common words (wordfreq 3.x, Zipf >= 4.5, length >= 4), frozen for toponym rule t3

CONTINENT_NAMES = frozenset({"africa", "asia", "europe", "america", "americas", "north america", "south america",
                             "latin america", "central america", "oceania", "antarctica", "middle east", "caribbean",
                             "scandinavia", "balkans", "eurasia", "australasia", "arctic"})
# the study area's own first-level qualifiers as GDELT (FIPS 10-4 names) and the press write them
HOME_REGIONS = {
    "Houston": {"texas", "tx"}, "Chennai": {"tamil nadu"}, "Bengaluru": {"karnataka"},
    "Valencia": {"valenciana", "valencia", "comunidad valenciana", "comunitat valenciana", "valencian community"},
    "EmiliaRomagna": {"emilia romagna"}, "Forli": {"emilia romagna"},
    "PortoAlegre": {"rio grande do sul"}, "TaquariValley": {"rio grande do sul"},
    "Carlisle": {"england", "cumbria"}, "York": {"england", "york", "north yorkshire", "yorkshire"},
    "Jakarta": {"jakarta raya", "jakarta", "dki jakarta", "banten", "jawa barat", "west java"},
    "NewYork": {"new york"}}
COUNTRY_FORMS = {"US": {"united states", "usa", "united states of america", "america"}, "IN": {"india"},
                 "ES": {"spain", "espana"}, "IT": {"italy", "italia"}, "BR": {"brazil", "brasil"},
                 "GB": {"united kingdom", "uk", "britain", "great britain", "england", "scotland", "wales"},
                 "ID": {"indonesia"}}
FEATURE_AFTER = frozenset({
    "county", "counties", "parish", "borough", "township", "district", "province", "region", "state", "city", "village",
    "villages", "town", "creek", "river", "bayou", "branch", "brook", "lake", "lakes", "reservoir", "dam", "canal",
    "channel", "bay", "beach", "island", "islands", "valley", "hills", "hill", "heights", "park", "gardens", "garden",
    "estates", "road", "rd", "street", "st", "avenue", "ave", "drive", "dr", "lane", "ln", "boulevard", "blvd",
    "highway", "hwy", "freeway", "fwy", "parkway", "pkwy", "bridge", "school", "schools", "isd", "college", "university",
    "academy", "airport", "hospital", "church", "mall", "center", "centre", "plaza", "station", "stadium", "plant",
    "refinery", "forest", "springs", "falls", "point", "harbor", "harbour", "fire", "police", "sheriff", "high",
    "middle", "elementary", "fc", "united", "wanderers", "rovers", "do", "da", "dos", "das", "de", "del", "della",
    "di", "du", "des"})
FEATURE_BEFORE = frozenset({
    "north", "south", "east", "west", "northern", "southern", "eastern", "western", "northeast", "northwest",
    "southeast", "southwest", "new", "old", "little", "upper", "lower", "great", "greater", "lake", "mount", "mt",
    "fort", "ft", "port", "saint", "st", "san", "santa", "santo", "sao", "rio", "fiume", "torrente", "barranco",
    "arroyo", "rambla", "via", "viale", "piazza", "corso", "calle", "carrer", "avenida", "av", "rua", "praca", "lago",
    "monte", "valle", "val", "ponte", "jalan", "jl", "kali", "sungai", "gunung", "university", "county", "cape", "isle",
    "de", "del", "della", "delle", "dei", "di", "da", "do", "dos", "das", "du", "des", "la", "le", "el", "los", "las",
    "lo", "van", "von", "bairro", "vila", "villa", "jardim", "parque", "barrio", "frazione", "localita"})
_LEFT_OK = frozenset({"in", "at", "near", "of", "from", "to", "the", "and", "across", "around", "into", "over", "for",
                      "on", "by", "outside", "hits", "hit", "floods", "flooding", "flood", "rain", "storm", "a", "em",
                      "no", "na", "en", "ad", "per", "tra", "fra", "con", "su", "entre", "para", "por", "desde", "hacia"})
_SEG_SPLIT = re.compile(r"[.;:!?|\n()\[\]\"“”«»,]")
_WORD = re.compile(r"[^\W\d_][\w'’\-]*", re.U)


def home_regions(city, cfg=None):
    h = set((cfg or {}).get("home_regions") or [])
    h |= HOME_REGIONS.get(str(city).split("_")[0], set())
    return {_norm_place(x) for x in h}


def _country_forms(ccs):
    out = set()
    for c in ccs:
        out |= COUNTRY_FORMS.get(c, set())
    return out


def _is_cap(w):
    return bool(w) and w[0].isupper()


def _titlecase_segment(seg):
    ws = [w for w in _WORD.findall(seg) if w.lower() not in _LEFT_OK]
    return len(ws) >= 3 and sum(_is_cap(w) for w in ws) >= 0.75 * len(ws)


def _neighbours(text, s, e, k=3):
    """Words joined to the span [s, e) by whitespace or hyphens only (one phrase), up to k on each side."""
    left, right = [], []
    i = s
    while len(left) < k:
        m = re.search(r"([^\W\d_][\w'’]*)[ \t\-]+$", text[:i], re.U)
        if not m:
            break
        left.append(m.group(1)); i = m.start(1)
    j = e
    while len(right) < k:
        m = re.match(r"[ \t\-]+([^\W\d_][\w'’]*)", text[j:], re.U)
        if not m:
            break
        right.append(m.group(1)); j += m.end(1)
    return left, right


def _qualifiers(text, e):
    """The next (up to two) comma-separated items after the span, normalised; [] if none."""
    m = re.match(r"\s*,([^.;:!?|\n()]*)", text[e:])
    return [_norm_place(x) for x in m.group(1).split(",")[:2]] if m else []


def _occurrence_ok(text, s, e, home, country_cc, common=frozenset()):
    left, right = _neighbours(text, s, e)
    l1 = _norm_place(left[0]) if left else None
    r1 = _norm_place(right[0]) if right else None
    # part of a longer name: adjacent feature word or name particle ("Montgomery County", "Alhaurin De La Torre")
    if (r1 and r1 in FEATURE_AFTER) or (l1 and l1 in FEATURE_BEFORE):
        return False
    cap_run = []
    for w in right:
        if not _is_cap(w):
            break
        cap_run.append(_norm_place(w))
    if any(w in FEATURE_AFTER for w in cap_run):
        return False
    own = _country_forms(country_cc)
    admin_home_country = set().union(*[HOME_ADMIN1.get(c, frozenset()) for c in country_cc]) if country_cc else set()
    q = _qualifiers(text, e) if not right else []
    # (a) a structured location: "<name>, <country>" or "<name>, <region>, <country>"
    if q:
        if q[0] in COUNTRY_NAMES or q[0] in own or q[0] in CONTINENT_NAMES:
            return q[0] in own
        if len(q) > 1 and (q[1] in COUNTRY_NAMES or q[1] in own):
            return q[1] in own and q[0] in home
        if q[0] in admin_home_country or q[0] in home:
            return q[0] in home
    # (b) prose: must be written as a name
    frag = text[s:e]
    if not _is_cap(frag):
        return False
    if _norm_place(frag) in common:
        return False
    seg_start = max([m.end() for m in _SEG_SPLIT.finditer(text[:s])] or [0])
    m_end = _SEG_SPLIT.search(text, e)
    seg = text[seg_start:(m_end.start() if m_end else len(text))]
    if not _titlecase_segment(seg):
        quals = home | COUNTRY_NAMES | CONTINENT_NAMES | admin_home_country | own
        if left and _is_cap(left[0]) and l1 not in _LEFT_OK and l1 not in quals:
            return False
        if right and _is_cap(right[0]) and r1 not in quals:
            return False
    return True


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


def toponym_verdict(place, text, tc):
    """None if the gazetteer name is kept, else the reason ('name' or 'occurrence')."""
    key = _norm_place(place)
    if key in tc["banned"] or key in tc["own"]:
        return "name"
    k = str(place).lower().strip()
    rx = tc["rx"].get(k) or tc["rx"].setdefault(k, re.compile(r"(?<![\w])" + re.escape(k) + r"(?![\w])", re.I))
    t = str(text or "")
    if not any(_occurrence_ok(t, mm.start(), mm.end(), tc["home"], tc["ccs"], tc["common"]) for mm in rx.finditer(t)):
        return "occurrence"
    return None


def refine_gazetteer_mentions(mentions, city, cfg=None, log=None):
    """Rule t3 (see above) on gazetteer mentions; NER/geotagged mentions pass unchanged. Returns (kept, stats).
    Idempotent: v6 already applies the rule while resolving mentions, so on v6 inputs this drops nothing."""
    if mentions is None or len(mentions) == 0 or "via" not in mentions:
        return mentions, dict(rules=TOPONYM_RULES_VERSION, checked=0, dropped=0)
    tc = toponym_context(city, cfg)
    keep = np.ones(len(mentions), bool)
    why = []
    for i, (via, place, text) in enumerate(zip(mentions["via"], mentions["place"], mentions["text"])):
        if via != "gazetteer":
            continue
        v = toponym_verdict(place, text, tc)
        if v:
            keep[i] = False; why.append((v, place))
    out = mentions[keep].reset_index(drop=True)
    w = pd.DataFrame(why, columns=["rule", "place"])
    stats = dict(rules=TOPONYM_RULES_VERSION, checked=int((mentions["via"] == "gazetteer").sum()),
                 dropped=int((~keep).sum()), kept=int(len(out)),
                 dropped_by_rule=w["rule"].value_counts().to_dict() if len(w) else {},
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
