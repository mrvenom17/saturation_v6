def city_countries(city, cfg):
    cc = cfg.get("countries")
    if cc:
        return [cc] if isinstance(cc, str) else list(cc)
    stem = city.split("_")[0]
    if stem in COUNTRY_OF:
        return [COUNTRY_OF[stem]]
    raise KeyError(f"no country code for {city}: add countries=[...] to its registry entry")


def _geonames_chunks(cc, cache_dir, bbox, log=None, city=""):
    """Rows of the GeoNames country extract (feature class P) inside bbox, read in chunks."""
    import csv
    path = download_file(GEONAMES_URL.format(cc=cc), os.path.join(cache_dir, "geonames", f"{cc}.zip"), log, city)
    minx, miny, maxx, maxy = bbox
    with zipfile.ZipFile(path) as z, z.open(f"{cc}.txt") as fh:
        for ch in pd.read_csv(io.TextIOWrapper(fh, encoding="utf-8"), sep="\t", header=None, names=GEONAMES_COLS,
                              usecols=["name", "asciiname", "alternatenames", "latitude", "longitude",
                                       "feature_class", "feature_code", "population"],
                              dtype=str, quoting=csv.QUOTE_NONE, na_filter=False, chunksize=300000):
            ch = ch[ch["feature_class"] == "P"]
            lat = pd.to_numeric(ch["latitude"], errors="coerce")
            lon = pd.to_numeric(ch["longitude"], errors="coerce")
            m = lat.between(miny, maxy) & lon.between(minx, maxx)
            if m.any():
                out = ch[m].copy()
                out["lat"], out["lon"] = lat[m].to_numpy(float), lon[m].to_numpy(float)
                out["population"] = pd.to_numeric(out["population"], errors="coerce").fillna(0)
                yield out


def geonames_places(boundary_4326, cfg, city, cache_dir, log=None, buffer_km=80.0):
    """Gazetteer (named populated places and sections of places INSIDE the study area) and the set of names of
    towns OUTSIDE it within buffer_km (population >= 1000), both from the GeoNames country extract.
    Returns (gazetteer frame [key, name, lat, lon], outside-name set, meta)."""
    import shapely
    poly = boundary_4326.union_all() if hasattr(boundary_4326, "union_all") else boundary_4326.unary_union
    minx, miny, maxx, maxy = poly.bounds
    d = buffer_km / 111.0
    rows, outside, n_in, n_out, n_self = [], set(), 0, 0, 0
    ccs = city_countries(city, cfg)
    selfn = {_norm_place(n) for n in self_names(cfg)}
    for cc in ccs:
        for ch in _geonames_chunks(cc, cache_dir, (minx - d, miny - d, maxx + d, maxy + d), log, city):
            inside = shapely.contains_xy(poly, ch["lon"].to_numpy(), ch["lat"].to_numpy())
            ins = ch[inside & ch["feature_code"].isin(GEONAMES_CODES)]
            n_in += len(ins)
            for r in ins.itertuples():
                # the feature that IS the study city (or region): none of its names, in any language, is a
                # location inside the area ("Nueva York", "City of New York" are New York itself)
                if _norm_place(r.name) in selfn or _norm_place(r.asciiname) in selfn:
                    n_self += 1
                    continue
                names = {r.name, r.asciiname}
                names |= {a.strip() for a in str(r.alternatenames).split(",") if _LATIN.match(a.strip() or "")}
                for nm in names:
                    if nm and len(nm) >= 4:
                        rows.append(dict(name=nm, lat=r.lat, lon=r.lon))
            out = ch[~inside & (ch["population"] >= 1000) & (ch["feature_code"] != "PPLX")]
            n_out += len(out)
            for r in out.itertuples():
                outside |= {r.name.lower(), r.asciiname.lower()}
    gaz = _finalise_gazetteer(rows, log, city)
    meta = dict(source="geonames", version=GAZETTEER_VERSION, countries=ccs, places_inside=int(n_in),
                self_features_excluded=int(n_self), self_names=sorted(selfn),
                gazetteer_names=int(len(gaz)), outside_towns=int(n_out), outside_names=int(len(outside)),
                licence="GeoNames, CC BY 4.0")
    if log is not None:
        log(city, "social:gazetteer", "ok" if len(gaz) else "warn",
            f"GeoNames {','.join(ccs)}: {n_in} populated places inside the study area -> {len(gaz)} gazetteer names; "
            f"{len(outside)} names of {n_out} towns outside it (within {buffer_km:.0f} km) will not be placed inside it")
    return gaz, outside, meta


def osm_outside_places(study_4326, buffer_km=80.0, log=None, city=""):
    """Names of OSM cities/towns within buffer_km of the study area but OUTSIDE it. A mention of one of
    these is about a neighbouring municipality, so it must not be placed inside the study area."""
    import osmnx as ox
    from shapely.geometry import box
    poly = study_4326.union_all() if hasattr(study_4326, "union_all") else study_4326.unary_union
    minx, miny, maxx, maxy = poly.bounds
    d = buffer_km / 111.0
    feats = overpass_features(box(minx - d, miny - d, maxx + d, maxy + d), {"place": ["city", "town"]},
                              log, city, "social:outside_places")
    names = set()
    for _, r in feats.iterrows():
        if r.geometry is None or r.geometry.is_empty:
            continue
        if poly.contains(r.geometry.representative_point()):
            continue
        for col in ("name", "name:en", "official_name", "alt_name"):
            v = r.get(col) if hasattr(r, "get") else None
            if isinstance(v, str):
                names |= {n.strip().lower() for n in v.split(";") if len(n.strip()) >= 3}
    if log:
        log(city, "social:outside_places", "info", f"{len(names)} neighbouring town/city names outside the study "
                                                   f"area (within {buffer_km:.0f} km) will not be placed inside it")
    return names


def self_names(cfg):
    """Names that denote the WHOLE study area (the city itself, its region, the storm, the main river). They are
    retrieval keywords but never a location inside the area. v6: until v5.5 the retrieval aliases were used here,
    which silently removed every within-area town listed as an alias (Paiporta, Kingwood, Canoas, ...) from the
    social layer."""
    names = cfg.get("self_names")
    if names is None:
        names = cfg.get("aliases", [])[:1]
    return [str(n) for n in names]


def match_gazetteer(texts, gaz, stop_names):
    if gaz is None or gaz.empty:
        return [[] for _ in texts]
    stop = {a.lower() for a in stop_names} | {_norm_place(a) for a in stop_names}
    keys = sorted([k for k in gaz["key"] if k not in stop], key=len, reverse=True)
    if not keys:
        return [[] for _ in texts]
    rx = re.compile(r"(?<![\w])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w])", re.I)
    return [sorted({m.group(1).lower() for m in rx.finditer(t or "")}) for t in texts]


MAJOR_PLACES = {
    # countries and seas/regions
    "india", "indonesia", "pakistan", "bangladesh", "sri lanka", "nepal", "china", "bhutan", "myanmar", "usa", "us", "america",
    "united states", "uk", "britain", "england", "uae", "united arab emirates", "saudi arabia", "qatar", "oman", "singapore",
    "malaysia", "japan", "australia", "texas", "gulf", "bay of bengal", "arabian sea", "indian ocean", "south asia", "asia",
    "western ghats", "eastern ghats", "deccan", "bengal", "north india", "south india",
    # Indian states and union territories
    "andhra", "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu", "tamilnadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal", "jammu", "kashmir", "ladakh", "puducherry", "pondicherry", "lakshadweep",
    "andaman", "chandigarh",
    # major cities (a mention of another city is not a location inside this one)
    "mumbai", "bombay", "delhi", "new delhi", "kolkata", "calcutta", "chennai", "madras", "bengaluru", "bangalore", "hyderabad",
    "secunderabad", "pune", "ahmedabad", "surat", "jaipur", "lucknow", "kanpur", "nagpur", "indore", "bhopal", "patna", "vadodara",
    "coimbatore", "madurai", "mysuru", "mysore", "mangaluru", "mangalore", "hubli", "belagavi", "kochi", "cochin", "thiruvananthapuram",
    "trivandrum", "visakhapatnam", "vijayawada", "guwahati", "bhubaneswar", "noida", "gurugram", "gurgaon", "ghaziabad", "faridabad",
    "tirupati", "vellore", "salem", "tiruchirappalli", "trichy", "nellore", "hosur", "jakarta", "bekasi", "bogor", "tangerang",
    "depok", "surabaya", "bandung", "dubai", "abu dhabi", "sharjah", "houston", "dallas", "austin", "new york", "london",
    # organisations and nicknames that geocode to a single office or nowhere meaningful
    "silicon valley", "bescom", "bbmp", "bwssb", "bda", "kseb", "tneb", "tangedco", "cmwssb", "gcc", "ghmc", "bmc", "mcgm",
    "imd", "ndrf", "sdrf", "ksndmc", "namma metro", "metro", "airport", "railway station", "city railway station", "majestic",
    "whatsapp", "twitter", "reddit", "youtube", "instagram",
    # Spain
    "madrid", "barcelona", "sevilla", "seville", "zaragoza", "malaga", "murcia", "palma", "bilbao", "alicante",
    "cordoba", "valladolid", "vigo", "gijon", "granada", "albacete", "castellon", "castello", "utiel", "requena",
    "cuenca", "toledo", "teruel", "tarragona", "girona", "lleida", "catalunya", "cataluna", "catalonia", "andalucia",
    "andalusia", "castilla", "castilla-la mancha", "comunitat valenciana", "comunidad valenciana", "aragon",
    "galicia", "asturias", "cantabria", "navarra", "euskadi", "baleares", "canarias", "espana", "spain",
    # Italy
    "roma", "rome", "milano", "milan", "napoli", "naples", "torino", "turin", "palermo", "genova", "bologna",
    "firenze", "florence", "bari", "catania", "venezia", "venice", "verona", "modena", "parma", "rimini", "ferrara",
    "imola", "italia", "lombardia", "toscana", "veneto", "piemonte", "marche", "umbria", "lazio", "campania",
    # Portugal / Brazil
    "lisboa", "lisbon", "porto", "sao paulo", "rio de janeiro", "brasilia", "salvador", "curitiba", "florianopolis",
    "canoas", "caxias do sul", "santa maria", "pelotas", "brasil", "brazil", "rio grande", "santa catarina", "parana",
    # Indonesia
    "bandung", "semarang", "medan", "makassar", "palembang", "yogyakarta", "banten", "jawa", "java", "sumatra",
    "sulawesi", "kalimantan", "bali", "indonesia",
    # UK / US extras
    "manchester", "birmingham", "leeds", "liverpool", "glasgow", "edinburgh", "cardiff", "belfast", "bristol",
    "newcastle", "sheffield", "nottingham", "cumbria", "yorkshire", "lancashire", "scotland", "wales", "ireland",
    "chicago", "los angeles", "san francisco", "boston", "philadelphia", "miami", "atlanta", "seattle", "denver",
    "new jersey", "florida", "louisiana", "california"}
# v5.4.2 geoparsing rules (version tag enters every geocoder cache key, so results accepted under older,
# looser rules are never reused). The v5.4.1 rule accepted any road/amenity/POI whose name CONTAINED the
# query, inside a bounded viewbox; that pinned country and region names onto same-named streets
# ("Romania" -> "Carrer de Romania", "Italy" -> an "Italia" street), which dominated the social layer of
# every non-Indian city. A place mention now has to resolve to a named settlement unit, exactly.
# g3 (v6): new geocoder query (name only) -> earlier cached picks are not reused.
# g4 (v6.1): the acceptance rule is unchanged; the namespace is new because v6.0 could store a FAILED lookup as
# "no such place" under g3, and such entries must never be read again.
GEOCODE_RULES_VERSION = "g4"
SETTLEMENT_TYPES = {"suburb", "neighbourhood", "quarter", "city_block", "city_district", "borough", "village",
                    "hamlet", "locality", "isolated_dwelling", "town"}
ALLOWED_GEOCODE_TYPES = SETTLEMENT_TYPES          # kept under the old name for callers and tests
NON_PLACE_WORDS = {
    # months and weekdays that NER tags as locations (en, es, it, pt)
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november",
    "december", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre", "gennaio", "febbraio", "aprile", "maggio", "giugno", "luglio",
    "settembre", "ottobre", "dicembre", "janeiro", "fevereiro", "marco", "maio", "junho", "julho",
    "setembro", "outubro", "novembro", "dezembro", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday"}


def _norm_place(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def geocode_matches(place, result):
    """A Nominatim result counts only if it is a named settlement unit (suburb ... town) whose name IS the
    queried name (accents and punctuation ignored). Streets, POIs, rivers and admin areas never count."""
    if not result:
        return False
    at = (result.get("addresstype") or result.get("type") or "").lower()
    if at not in SETTLEMENT_TYPES:
        return False
    q = _norm_place(place)
    name = _norm_place(result.get("name") or str(result.get("display_name", "")).split(",")[0])
    return len(q) >= 4 and name == q


def _in_bounds(g, bounds):
    try:
        la, lo = float(g["lat"]), float(g["lon"])
    except (TypeError, KeyError, ValueError):
        return False
    return bounds["min_lat"] <= la <= bounds["max_lat"] and bounds["min_lon"] <= lo <= bounds["max_lon"]


def _pick_geocode(place, res, bounds):
    """First candidate (Nominatim may return several) that is the named settlement and lies in the study box."""
    cands = res if isinstance(res, list) else ([res] if res else [])
    for c in cands:
        if geocode_matches(place, c) and _in_bounds(c, bounds):
            return dict(lat=float(c["lat"]), lon=float(c["lon"]), name=c.get("name"),
                        addresstype=(c.get("addresstype") or c.get("type")))
    return None


def _bounds_tag(bounds):
    return ",".join(f"{bounds[k]:.2f}" for k in ("min_lon", "min_lat", "max_lon", "max_lat"))


LOCATION_LATTICE_DEG = 0.0025      # ~250 m: mentions closer than this are one location (v6)


def concentration_message(m):
    """(text, is_concentrated) for the run log: how many places carry the layer."""
    cc = mention_concentration(m)
    if not cc["n_mentions"]:
        return "no located mentions", True
    bad = cc["top_share"] > 0.4 or cc["effective_locations"] < 5
    return (f"{cc['distinct_locations']} distinct locations, effective {cc['effective_locations']}; top place "
            f"'{cc['top_place']}' = {cc['top_share']:.0%} of mentions; top 5: {cc['top5']}"
            + ("  <- the layer is carried by very few points; it cannot localise flooding. Check the top places are "
               "real places inside the study area" if bad else "")), bad


def mention_concentration(m):
    """How many distinct places actually carry the social layer. A layer dominated by one point cannot say
    anything about WHERE flooding happened, whatever its size. v6: locations are cells of a ~250 m lattice for
    every resolution path (gazetteer places, geocoded names and geotagged posts alike); until v5.5 all geotagged
    posts shared the label '(geotagged)', so a geotagged source could never pass the top-place rule."""
    if m is None or len(m) == 0:
        return dict(n_mentions=0, distinct_locations=0, effective_locations=0.0, top_place=None, top_share=None)
    loc = ((m["lat"].astype(float) / LOCATION_LATTICE_DEG).round().astype(int).astype(str) + ","
           + (m["lon"].astype(float) / LOCATION_LATTICE_DEG).round().astype(int).astype(str))
    p = loc.value_counts(normalize=True)
    name = m["place"].astype(str).where(m["place"].astype(str) != "(geotagged)",
                                        "geotagged@" + m["lat"].round(3).astype(str) + "," + m["lon"].round(3).astype(str))
    label = name.groupby(loc).agg(lambda x: x.value_counts().index[0])
    top5 = [(str(label[k]), round(float(v), 3)) for k, v in p.head(5).items()]
    return dict(n_mentions=int(len(m)), distinct_locations=int(len(p)),
                effective_locations=round(float(1.0 / np.sum(p.to_numpy() ** 2)), 2),
                top_place=top5[0][0], top_share=top5[0][1], top5=top5,
                via=m["via"].value_counts().to_dict() if "via" in m else {})


def _geocode_cache_load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def _geocode_cache_save(path, cache):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


GEOCODER_BREAKER = 5      # consecutive failed lookups after which the geocoder is left alone for this run
MENTION_COLS = ["source", "doc_id", "place", "lat", "lon", "tone", "text", "via", "time_utc"]


def split_documents(docs):
    """(geotagged documents, text documents). Geotagged ones keep their own coordinates and cost nothing to place;
    text ones need the gazetteer, NER and the geocoder. v6.1.1 resolves and checkpoints the two parts separately,
    so a new photo does not make a city repeat hours of NER."""
    if docs is None or len(docs) == 0:
        return docs, docs
    geo = docs["lat"].notna() & docs["lon"].notna()
    return docs[geo].reset_index(drop=True), docs[~geo].reset_index(drop=True)


def resolve_mentions(docs, gaz, cfg, bounds, ner=None, geocoder=None, max_geocode=150, log=None, city="",
                     exclude=None, cache_path=None, info=None, report_concentration=True):
    """One row per (document, place). Geolocated sources keep their own coordinates;
    others use the gazetteer, then (optionally) NER + bounded geocoding.

    v6.1 (rule t4): a name found by NER has to pass the same toponym rule as a gazetteer name BEFORE it is
    geocoded. In v6.0 a document whose gazetteer candidates were all rejected went to NER, and NER handed the very
    same names to the geocoder with no check: GDELT's "Sao Sebastiao, Estado Do Rio, Brazil", "Sarandi, Parana,
    Brazil" and "Sao Joao, Piauhy, Brazil" were placed on same-named neighbourhoods of Porto Alegre and made up
    48% of that city's located mentions.

    `info` (a dict, filled in place) reports whether the result is COMPLETE: lookups stopped by the cap or lost to
    a geocoder failure are counted, never cached as 'not found', and the caller must not freeze such a result."""
    stats = dict(geocoder_calls=0, cache_hits=0, lookups_capped=0, lookups_failed=0, ner_failed=0,
                 ner_candidates_rejected=0, names_capped=0, complete=True)
    if info is not None:
        info.update(stats)
    if docs is None or len(docs) == 0:
        return pd.DataFrame(columns=["source", "doc_id", "place", "lat", "lon", "tone", "text", "via", "time_utc"])
    rows = []
    geo = docs[docs["lat"].notna() & docs["lon"].notna()]
    for r in geo.itertuples():
        if bounds["min_lat"] <= float(r.lat) <= bounds["max_lat"] and bounds["min_lon"] <= float(r.lon) <= bounds["max_lon"]:
            rows.append(dict(source=r.source, doc_id=r.doc_id, place="(geotagged)", lat=float(r.lat), lon=float(r.lon),
                             tone=r.tone, text=r.text, via="native", time_utc=r.time_utc))
    rest = docs[~(docs["lat"].notna() & docs["lon"].notna())].reset_index(drop=True)
    exclude = {e.lower() for e in (exclude or set())}
    if exclude and gaz is not None and not gaz.empty:
        n_before = len(gaz)
        gaz = gaz[~gaz["key"].isin(exclude)].reset_index(drop=True)
        if log is not None and len(gaz) < n_before:
            log(city, "social:gazetteer", "info", f"{n_before - len(gaz)} gazetteer names shared with neighbouring "
                                                  f"towns outside the study area removed")
    hits = match_gazetteer(rest["text"].tolist(), gaz, self_names(cfg))
    gidx = gaz.set_index("key") if gaz is not None and not gaz.empty else None
    gnorm = {}
    if gidx is not None:
        for k_, g_ in gidx.iterrows():
            gnorm.setdefault(_norm_place(k_), g_)
    unresolved = []
    tc = toponym_context(city, cfg)
    n_t3 = {"name": 0, "occurrence": 0}
    for i, r in rest.iterrows():
        kept = []
        for k in hits[i]:
            g = gidx.loc[k]
            v = toponym_verdict(g["name"], r.text, tc)      # toponym rule, applied at acquisition (v6)
            if v:
                n_t3[v] += 1
            else:
                kept.append(g)
        for g in kept:
            rows.append(dict(source=r.source, doc_id=r.doc_id, place=g["name"], lat=float(g["lat"]), lon=float(g["lon"]),
                             tone=r.tone, text=r.text, via="gazetteer", time_utc=r.time_utc))
        if not kept:
            unresolved.append(i)          # no accepted gazetteer place: the document goes to NER + geocoding
    if log is not None and sum(n_t3.values()):
        log(city, "social:toponyms", "info", f"rule {TOPONYM_RULES_VERSION}: {sum(n_t3.values())} gazetteer candidates "
                                             f"rejected at acquisition {n_t3}")
    n_geo_calls, n_cache_hits, n_capped, n_failed, n_ner_fail, streak = 0, 0, 0, 0, 0, 0
    n_ner_rej = {"name": 0, "occurrence": 0}
    capped_names, last_err = set(), ""
    if ner is not None and geocoder is not None and unresolved:
        # the cache persists in cache/: a repeated or resumed run pays no geocoder calls for names
        # already looked up, so the per-run cap stops truncating coverage across runs
        cache = _geocode_cache_load(cache_path) if cache_path else {}
        n_cached_start = len(cache)
        self_n = self_names(cfg)
        for i in unresolved:
            r = rest.loc[i]
            try:
                ents = ner(r.text[:512])
            except Exception:  # noqa: BLE001
                n_ner_fail += 1
                continue
            places = {ph.clean_place(e["word"]) for e in ents
                      if e.get("entity_group") == "LOC" and float(e.get("score", 1.0)) >= 0.80 and "##" not in str(e.get("word", ""))}
            for p in sorted(places):
                if (not ph.is_useful_place(p, self_n) or len(p) < 4 or _norm_place(p) in MAJOR_PLACES
                        or _norm_place(p) in NON_PLACE_WORDS or p.lower() in exclude):
                    continue
                v = toponym_verdict(p, r.text, tc)          # rule t4: the same test as for gazetteer names
                if v:
                    n_ner_rej[v] += 1
                    continue
                gz = gnorm.get(_norm_place(p))
                if gz is not None:
                    # a name the gazetteer knows keeps the gazetteer's coordinates, so one name is one location
                    # whichever path found it (v6.0 could list a town twice, e.g. "Roca Sales")
                    rows.append(dict(source=r.source, doc_id=r.doc_id, place=gz["name"], lat=float(gz["lat"]),
                                     lon=float(gz["lon"]), tone=r.tone, text=r.text, via="ner+gazetteer", time_utc=r.time_utc))
                    continue
                # the key carries the rules version and the study box: a name resolved for another city (or
                # under older rules) is never reused here
                key = f"{GEOCODE_RULES_VERSION}|{p.lower()}|{_bounds_tag(bounds)}"
                if key in cache:
                    n_cache_hits += 1
                else:
                    if n_geo_calls >= max_geocode or streak >= GEOCODER_BREAKER:
                        n_capped += 1
                        capped_names.add(p.lower())
                        continue
                    try:
                        res = geocoder(p)
                    except Exception as e:  # noqa: BLE001  (TransientLookupError from the geocoder, or any other failure)
                        n_failed += 1; streak += 1; last_err = str(e)[:160]
                        n_geo_calls += 1
                        continue            # NOT cached: a failed lookup is not a place that does not exist
                    streak = 0
                    cache[key] = _pick_geocode(p, res, bounds)
                    n_geo_calls += 1
                    if cache_path and n_geo_calls % 200 == 0:
                        _geocode_cache_save(cache_path, cache)      # a disconnect loses at most 200 lookups
                g = cache.get(key)
                if g and _in_bounds(g, bounds):
                    rows.append(dict(source=r.source, doc_id=r.doc_id, place=p, lat=float(g["lat"]), lon=float(g["lon"]),
                                     tone=r.tone, text=r.text, via="ner+nominatim", time_utc=r.time_utc))
        if cache_path and len(cache) > n_cached_start:
            _geocode_cache_save(cache_path, cache)
        if callable(getattr(geocoder, "flush", None)):
            geocoder.flush()
    # t5: the final filter (see RESOLVE_RULES_VERSION). Routing above used t4, so a document is not re-sent to NER
    # because of it; the filter only removes mentions.
    n_tail = 0
    if rows:
        kept_rows = []
        for r_ in rows:
            if r_["via"] in TEXT_RESOLVED and mention_verdict(r_["place"], r_["text"], tc, via=r_["via"], strict=True):
                n_tail += 1
                continue
            kept_rows.append(r_)
        rows = kept_rows
    # an empty result keeps its columns, so social_mentions.csv.gz stays a readable (header-only) table
    m = pd.DataFrame(rows, columns=["source", "doc_id", "place", "lat", "lon", "tone", "text", "via", "time_utc"])
    if len(m):
        m = m.drop_duplicates(["source", "doc_id", "place"]).reset_index(drop=True)
    stats.update(tail_of_longer_name=n_tail)
    if log is not None and n_tail:
        log(city, "social:toponyms", "info", f"rule {TOPONYM_RULES_VERSION}: {n_tail} mentions dropped (the name is only the "
                                             f"end of a longer place name in a structured location)")
    stats.update(geocoder_calls=n_geo_calls, cache_hits=n_cache_hits, lookups_capped=n_capped, lookups_failed=n_failed,
                 ner_failed=n_ner_fail, ner_candidates_rejected=int(sum(n_ner_rej.values())),
                 names_capped=len(capped_names), complete=not (n_capped or n_failed))
    if info is not None:
        info.update(stats)
    if log is not None:
        if sum(n_ner_rej.values()):
            log(city, "social:toponyms", "info", f"rule {TOPONYM_RULES_VERSION}: {sum(n_ner_rej.values())} NER candidates "
                                                 f"rejected before geocoding {n_ner_rej}")
        log(city, "social:places", "ok", f"{len(m)} mentions from {m['doc_id'].nunique() if len(m) else 0} documents "
                                         f"(gazetteer names={0 if gaz is None else len(gaz)}, geocoder calls={n_geo_calls}, "
                                         f"cache hits={n_cache_hits})")
        if n_ner_fail:
            log(city, "social:places", "warn", f"NER failed on {n_ner_fail} documents (they carry no NER mention)")
        if n_capped or n_failed:
            why = []
            if n_capped and streak >= GEOCODER_BREAKER:
                why.append(f"the geocoder failed {GEOCODER_BREAKER} times in a row and was left alone ({last_err})")
            elif n_capped:
                why.append(f"the per-run geocoder cap ({max_geocode}) was reached")
            if n_failed:
                why.append(f"{n_failed} lookups failed ({last_err})")
            log(city, "social:places", "warn",
                f"INCOMPLETE: {n_capped} lookups of {len(capped_names)} names not done; " + "; ".join(why)
                + ". This result is NOT frozen: re-run the acquisition (names already looked up are free) until "
                  "this message disappears, or raise MAX_GEOCODE_CALLS")
        cc = mention_concentration(m) if report_concentration else dict(n_mentions=0)
        if cc["n_mentions"]:
            msg = (f"{cc['distinct_locations']} distinct locations, effective {cc['effective_locations']}; top place "
                   f"'{cc['top_place']}' = {cc['top_share']:.0%} of mentions; top 5: {cc['top5']}")
            bad = cc["top_share"] > 0.4 or cc["effective_locations"] < 5
            log(city, "social:concentration", "warn" if bad else "info",
                msg + ("  <- the social layer is carried by very few points; it cannot localise flooding. Check "
                       "the top places are real places inside the study area" if bad else ""))
    return m



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
TOPONYM_RULES_VERSION = "t5"
# The rule under which names are ROUTED while mentions are resolved (which gazetteer names are kept, which documents
# go on to NER). t5 does not change the routing: it is t4 followed by one more filter on the result (below), applied
# identically whether the mentions were just resolved or come from a checkpoint. So the name lookups of a v6.1
# acquisition stay valid, and a fresh run and a resumed run give the same mentions.
RESOLVE_RULES_VERSION = "t4"
# t5 (v6.1.1) = t4 + a final filter: a mention is dropped unless its text holds an occurrence that passes the rule
# with the name as the WHOLE first component of a structured location ("Vargas, ..." yes; "Getulio Vargas, ..." no).
# t4 (v6.1) = t3 with three changes, all label-free:
#   1. the rule is applied to names found by NER as well, before they are geocoded (t3 covered gazetteer names
#      only; the NER path re-admitted exactly the names t3 had rejected);
#   2. flood and weather words are never place names ("Kebanjiran" = "flooded" was 3.9% of Jakarta's mentions);
#   3. text is entity-decoded before matching (clean_text), so accented names in titles can be found.
# Flood/weather vocabulary of the study languages, normalised with _norm_place (accents removed):
FLOOD_NAME_WORDS = frozenset({
    "flood", "floods", "flooding", "flooded", "waterlogging", "waterlogged", "rain", "rains", "rainfall", "storm",
    "cyclone", "deluge", "monsoon",
    "banjir", "kebanjiran", "genangan", "tergenang", "terendam", "hujan", "longsor", "luapan",
    "inundacion", "inundaciones", "riada", "riadas", "dana", "lluvia", "lluvias", "tormenta", "temporal",
    "alluvione", "alluvioni", "allagamento", "allagamenti", "esondazione", "esondazioni", "maltempo", "pioggia", "piogge",
    "enchente", "enchentes", "inundacao", "inundacoes", "alagamento", "alagamentos", "chuva", "chuvas", "temporais"})
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


def _occurrence_ok(text, s, e, home, country_cc, common=frozenset(), strict=False):
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
        placed = None
        if q[0] in COUNTRY_NAMES or q[0] in own or q[0] in CONTINENT_NAMES:
            placed = q[0] in own
        elif len(q) > 1 and (q[1] in COUNTRY_NAMES or q[1] in own):
            placed = q[1] in own and q[0] in home
        elif q[0] in admin_home_country or q[0] in home:
            placed = q[0] in home
        if placed is not None:
            # t5 (strict): the structured location must BE the name, not end with it. "Getulio Vargas, Rio Grande Do
            # Sul, Brazil" (a town 300 km away) was read as "Vargas", a neighbourhood of Porto Alegre, in the v6.1
            # acquisition: 8 of that city's 80 primary mentions.
            if placed and strict and left and _is_cap(left[0]) and l1 not in _LEFT_OK:
                return False
            return placed
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
