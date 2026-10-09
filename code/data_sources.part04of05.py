def src_petabencana(city, cfg, t0, t1, opts, cache_dir, log):
    """PetaBencana crowdsourced flood reports (geolocated; Indonesia only)."""
    region = cfg.get("petabencana_region")
    if not region:
        raise RuntimeError("not an Indonesian city")
    rows, s = [], t0
    hdr = {"x-api-key": opts["petabencana_api_key"]} if opts.get("petabencana_api_key") else {}
    while s < t1:
        e = min(s + dt.timedelta(days=6, hours=23), t1)
        params = dict(admin=region, geoformat="geojson", disaster="flood",
                      start=s.strftime("%Y-%m-%dT%H:%M:%S+0000"), end=e.strftime("%Y-%m-%dT%H:%M:%S+0000"))
        url = "https://data.petabencana.id/reports/archive"
        js = cached_json(cache_dir, url + json.dumps(params, sort_keys=True),
                         lambda: http_get(url, params=params, headers=hdr).json())
        feats = (js.get("result") or {}).get("features", []) if isinstance(js, dict) else []
        for f in feats:
            p, g = f.get("properties", {}), f.get("geometry") or {}
            c = g.get("coordinates") or [np.nan, np.nan]
            rows.append(dict(doc_id=p.get("pkey"), url=p.get("url"), time_utc=p.get("created_at"),
                             text=(p.get("text") or "banjir laporan").strip() or "banjir laporan", lon=c[0], lat=c[1]))
        s = e + dt.timedelta(seconds=1)
    if not rows:
        raise RuntimeError("archive returned no reports (endpoint may require an API key)")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- geotagged photo sources (v6)
# Photos carry the photographer's own coordinates, so they localise without any geoparsing. Only photos TAKEN
# inside the social window whose title/tags/description use flood vocabulary are kept, and one author's photos
# from the same ~100 m spot on the same day count once (collect_documents), so a single photographer cannot
# dominate the layer. Flickr's location accuracy is recorded per photo; only accuracy >= FLICKR_MIN_ACCURACY
# (neighbourhood level or finer) is kept.
FLICKR_REST = "https://api.flickr.com/services/rest/"
FLICKR_MIN_ACCURACY = 12
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_DATE_RE = re.compile(r"(\d{4})[-:/.](\d{1,2})[-:/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?")


def flood_text_re(lang="en"):
    words = [re.escape(w.lower()) for w in QUERY_TERMS.get(lang, [])]
    return re.compile(FLOOD_RE.pattern + ("|" + "|".join(words) if words else ""), re.I)


def _flickr_rows(js, t0, t1, rx, min_accuracy=FLICKR_MIN_ACCURACY):
    """Parse one flickr.photos.search page (JSON, nojsoncallback=1) into document rows."""
    if not isinstance(js, dict) or js.get("stat") != "ok":
        raise RuntimeError(f"Flickr API error: {(js or {}).get('message', 'no response') if isinstance(js, dict) else js}")
    rows = []
    for ph_ in (js.get("photos") or {}).get("photo", []):
        try:
            lat, lon = float(ph_.get("latitude")), float(ph_.get("longitude"))
            acc = int(ph_.get("accuracy") or 0)
        except (TypeError, ValueError):
            continue
        if (lat == 0 and lon == 0) or acc < min_accuracy:
            continue
        desc = ph_.get("description")
        desc = desc.get("_content", "") if isinstance(desc, dict) else str(desc or "")
        text = " ".join(x for x in (ph_.get("title") or "", ph_.get("tags") or "", re.sub(r"<[^>]+>", " ", desc)) if x).strip()
        if not text or not rx.search(text):
            continue
        ts = pd.to_datetime(ph_.get("datetaken"), errors="coerce")
        if pd.isna(ts):
            continue
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if not (pd.Timestamp(t0, tz="UTC") <= ts <= pd.Timestamp(t1, tz="UTC")):
            continue
        rows.append(dict(doc_id=f"flickr_{ph_.get('id')}", url=f"https://www.flickr.com/photos/{ph_.get('owner')}/{ph_.get('id')}",
                         time_utc=ts, text=text, lat=lat, lon=lon, author=str(ph_.get("owner"))))
    pages = int((js.get("photos") or {}).get("pages") or 1)
    return rows, pages


def src_flickr(city, cfg, t0, t1, opts, cache_dir, log):
    """Flickr photos taken in the window inside the study box (needs a free non-commercial API key)."""
    key = opts.get("flickr_api_key")
    if not key:
        raise RuntimeError("FLICKR_API_KEY not set (optional source)")
    b = cfg["bounds"]
    rx = flood_text_re(cfg.get("lang", "en"))
    rows, page, pages = [], 1, 1
    # local camera time is stored without a zone: the query is widened by a day on each side and the exact
    # window is applied to the parsed time (which is treated as UTC; the error is at most the zone offset)
    q0, q1 = t0 - dt.timedelta(days=1), t1 + dt.timedelta(days=1)
    while page <= min(pages, int(opts.get("flickr_max_pages", 40))):
        params = dict(method="flickr.photos.search", api_key=key, format="json", nojsoncallback=1,
                      bbox=f"{b['min_lon']},{b['min_lat']},{b['max_lon']},{b['max_lat']}",
                      min_taken_date=q0.strftime("%Y-%m-%d %H:%M:%S"), max_taken_date=q1.strftime("%Y-%m-%d %H:%M:%S"),
                      has_geo=1, extras="geo,date_taken,tags,description,owner_name", per_page=250, page=page,
                      sort="date-taken-asc", content_type=1)
        ck = "flickr|" + json.dumps({k: v for k, v in params.items() if k != "api_key"}, sort_keys=True)
        js = cached_json(cache_dir, ck, lambda: http_get(FLICKR_REST, params=params, timeout=60).json())
        got, pages = _flickr_rows(js, t0, t1, rx)
        rows += got
        page += 1
        time.sleep(0.3)
    log(city, "social:flickr", "info", f"{pages} result page(s) scanned; {len(rows)} geotagged flood photos in the window")
    return pd.DataFrame(rows)


def _commons_tiles(b, step_deg=0.08):
    """The Commons geosearch bounding box is size-limited: the study box is scanned in <= ~9 km tiles."""
    lats = np.arange(b["min_lat"], b["max_lat"], step_deg)
    lons = np.arange(b["min_lon"], b["max_lon"], step_deg)
    for la in lats:
        for lo in lons:
            yield (min(la + step_deg, b["max_lat"]), lo, la, min(lo + step_deg, b["max_lon"]))   # top, left, bottom, right


def _commons_date(meta):
    raw = re.sub(r"<[^>]+>", " ", str(((meta or {}).get("DateTimeOriginal") or {}).get("value") or ""))
    m = _DATE_RE.search(raw)
    if not m:
        return pd.NaT
    y, mo, d, hh, mm = m.groups()
    try:
        return pd.Timestamp(int(y), int(mo), int(d), int(hh or 12), int(mm or 0), tz="UTC")
    except ValueError:
        return pd.NaT


def _commons_rows(pages, t0, t1, rx):
    """Parse Commons query pages (prop=coordinates|imageinfo|categories) into document rows."""
    rows = []
    for pg in (pages or {}).values():
        coords = pg.get("coordinates") or []
        info = (pg.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        if not coords:
            continue
        ts = _commons_date(meta)
        if pd.isna(ts) or not (pd.Timestamp(t0, tz="UTC") <= ts <= pd.Timestamp(t1, tz="UTC")):
            continue
        cats = " ".join(c.get("title", "").replace("Category:", "") for c in (pg.get("categories") or []))
        desc = re.sub(r"<[^>]+>", " ", str((meta.get("ImageDescription") or {}).get("value") or ""))
        text = re.sub(r"\s+", " ", f"{pg.get('title', '').replace('File:', '')} {desc} {cats}").strip()
        if not rx.search(text):
            continue
        rows.append(dict(doc_id=f"commons_{pg.get('pageid')}", url=f"https://commons.wikimedia.org/?curid={pg.get('pageid')}",
                         time_utc=ts, text=text, lat=float(coords[0]["lat"]), lon=float(coords[0]["lon"]),
                         author=str(info.get("user") or "")))
    return rows


def src_wikimedia_commons(city, cfg, t0, t1, opts, cache_dir, log):
    """Wikimedia Commons photos with camera/photographer coordinates, taken in the window (keyless)."""
    b = cfg["bounds"]
    rx = flood_text_re(cfg.get("lang", "en"))
    ids = []
    for top, left, bottom, right in _commons_tiles(b):
        params = dict(action="query", list="geosearch", gsbbox=f"{top}|{left}|{bottom}|{right}", gsnamespace=6,
                      gslimit=500, format="json")
        js = cached_json(cache_dir, "commons|" + json.dumps(params, sort_keys=True),
                         lambda: http_get(COMMONS_API, params=params, headers=UA, timeout=60).json())
        if isinstance(js, dict) and js.get("error"):
            raise RuntimeError(f"Commons geosearch error: {js['error'].get('info', js['error'])}")
        ids += [g["pageid"] for g in ((js or {}).get("query") or {}).get("geosearch", [])]
        time.sleep(0.2)
    ids = list(dict.fromkeys(ids))
    rows = []
    for i in range(0, len(ids), 50):
        params = dict(action="query", pageids="|".join(map(str, ids[i:i + 50])), prop="coordinates|imageinfo|categories",
                      iiprop="extmetadata|user", iiextmetadatafilter="DateTimeOriginal|ImageDescription",
                      cllimit="max", clshow="!hidden", format="json")
        js = cached_json(cache_dir, "commons|" + json.dumps(params, sort_keys=True),
                         lambda: http_get(COMMONS_API, params=params, headers=UA, timeout=60).json())
        rows += _commons_rows(((js or {}).get("query") or {}).get("pages"), t0, t1, rx)
        time.sleep(0.2)
    log(city, "social:wikimedia_commons", "info", f"{len(ids)} geotagged files in the box; {len(rows)} flood photos taken in the window")
    return pd.DataFrame(rows)


SOCIAL_SOURCES = {"gdelt_bigquery": src_gdelt_bigquery, "gdelt_rawfiles": src_gdelt_rawfiles,
                  "google_news_rss": src_google_news_rss, "reddit_arcticshift": src_reddit_arcticshift,
                  "youtube": src_youtube, "petabencana": src_petabencana, "flickr": src_flickr,
                  "wikimedia_commons": src_wikimedia_commons}
PHOTO_SOURCES = {"flickr", "wikimedia_commons"}


def collect_documents(city, cfg, window_days, sources, opts, cache_dir, log):
    t0, t1 = window_bounds(cfg["event_date"], window_days)
    frames, status = [], []
    gdelt_done = False
    for name in sources:
        if name == "gdelt_rawfiles" and gdelt_done:
            status.append(dict(source=name, status="skip", n=0, detail="GDELT already obtained via BigQuery"))
            continue
        try:
            t = time.time()
            raw_df = SOCIAL_SOURCES[name](city, cfg, t0, t1, opts, cache_dir, log)
            n_raw = 0 if raw_df is None else len(raw_df)
            df = finalize_docs(raw_df, name, t0, t1)
            if n_raw and len(df) < n_raw:
                log(city, f"social:{name}", "info", f"{n_raw} fetched -> {len(df)} kept "
                                                     f"({n_raw - len(df)} outside the window, empty or duplicate)")
            frames.append(df)
            status.append(dict(source=name, status="ok", n=len(df), detail=f"{time.time() - t:.0f}s"))
            log(city, f"social:{name}", "ok" if len(df) else "warn", f"{len(df)} documents in window")
            if name == "gdelt_bigquery" and len(df) > 0:
                gdelt_done = True
        except Exception as e:  # noqa: BLE001
            status.append(dict(source=name, status="unavailable", n=0, detail=str(e)[:300]))
            log(city, f"social:{name}", "skip", str(e)[:200])
    docs = pd.concat(frames, ignore_index=True) if frames else empty_docs()
    if len(docs):
        docs = dedupe_documents(docs, log, city)
    return docs, pd.DataFrame(status)


def dedupe_documents(docs, log=None, city=""):
    """Pre-registered de-duplication (v6), in this order:
    1. syndicated wire copies (same GDELT location list, tone vector and title) count once, earliest kept;
    2. identical text (first 160 normalised characters) counts once for documents without coordinates;
    3. geotagged photos: one per author, ~100 m spot and day.
    Other geotagged reports (e.g. PetaBencana) are distinct observations and are all kept."""
    docs = docs.sort_values("time_utc").reset_index(drop=True)
    n0 = len(docs)
    synd = docs["synd_key"].notna() if "synd_key" in docs else pd.Series(False, index=docs.index)
    docs = pd.concat([docs[~synd], docs[synd].drop_duplicates("synd_key")]).sort_values("time_utc")
    n1 = len(docs)
    docs["text_key"] = docs["text"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip().str[:160]
    geotag = docs["lat"].notna() & docs["lon"].notna()
    photo = docs["source"].isin(PHOTO_SOURCES)
    ph_ = docs[photo].copy()
    if len(ph_):
        ph_["spot"] = (ph_["author"].astype(str) + "|" + (ph_["lat"].astype(float) / 0.001).round().astype(int).astype(str) + "|"
                       + (ph_["lon"].astype(float) / 0.0013).round().astype(int).astype(str) + "|"
                       + pd.to_datetime(ph_["time_utc"], utc=True).dt.strftime("%Y%m%d"))
        ph_ = ph_.drop_duplicates("spot").drop(columns="spot")
    docs = pd.concat([docs[geotag & ~photo], ph_, docs[~geotag].drop_duplicates("text_key")]).drop(columns="text_key")
    docs = docs.sort_values("time_utc").reset_index(drop=True)
    if log is not None and len(docs) < n0:
        log(city, "social:dedupe", "info", f"{n0} documents -> {len(docs)} after de-duplication "
                                           f"({n0 - n1} syndicated wire copies, {n1 - len(docs)} repeated texts or photos)")
    return docs


# ======================================================================
# exposure layer (v5.5): residential population, for the density placebo and control
GHSL_POP_EPOCHS = (2000, 2005, 2010, 2015, 2020, 2025)


def population_layer(city, cfg, G, df, log):
    """Residents per grid cell from GHSL GHS-POP (JRC/GHSL/P2023A/GHS_POP, 100 m; the epoch nearest the event
    year, never a projection past it), else WorldPop GP 100 m (WorldPop/GP/100m/pop, nearest year <= 2021).
    Returns (values per cell, meta). Raises if neither is available: the caller skips the density analyses."""
    import ee
    year = int(str(cfg["event_date"])[:4])
    roi = _roi(cfg["bounds"])
    errs, attempts = [], []
    epoch = min((e for e in GHSL_POP_EPOCHS if e <= max(year, GHSL_POP_EPOCHS[0])), key=lambda e: abs(e - year))
    attempts.append(("ghsl", f"JRC/GHSL/P2023A/GHS_POP/{epoch}",
                     lambda: ee.Image(f"JRC/GHSL/P2023A/GHS_POP/{epoch}").select("population_count"), 100))
    wp_year = min(max(year, 2000), 2021)
    attempts.append(("worldpop", f"WorldPop/GP/100m/pop year={wp_year}",
                     lambda: ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(roi)
                     .filter(ee.Filter.eq("year", wp_year)).select("population").mosaic(), 93))
    for name, ref, make, native in attempts:
        try:
            img = cell_mean(make().unmask(0), G.crs, native).rename("pop")
            pix = ee_pixels(img, G)["pop"]
            vals = ph.raster_to_cells(pix, df)
            # counts cannot be negative; resampling edges and nodata are treated as nobody living there
            vals = np.clip(np.where(np.isfinite(vals), vals, 0.0), 0.0, None)
            if vals.sum() <= 0:
                raise RuntimeError("no population inside the study area")
            # residents per 100 m pixel, averaged over the cell -> residents per km^2
            dens = vals * (1e6 / (native ** 2))
            log(city, "exposure:population", "ok", f"{ref}: median {np.median(dens):.0f} residents/km², "
                                                   f"max {dens.max():.0f}")
            return dens, dict(source=name, asset=ref, native_m=native)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {str(e)[:120]}")
    raise RuntimeError("population layer unavailable -> " + " | ".join(errs))


# ======================================================================
# place resolution + emotion scoring
# ======================================================================
GENERIC_NAMES = {"market", "station", "colony", "nagar", "road", "layout", "city", "central", "new", "old", "east",
                 "west", "north", "south", "main", "cross", "stage", "phase", "sector", "block", "village", "town",
                 "bus stand", "junction", "circle", "park", "lake", "temple", "church", "mosque", "school", "hospital",
                 "airport", "port", "beach", "river", "bridge", "highway", "downtown", "midtown", "uptown", "centre", "center",
                 # v5.4.2: ordinary Italian/Spanish/Portuguese words that are also OSM locality names
                 "centro", "centre-ville", "pianta", "ponte", "borgo", "villa", "piazza", "chiesa", "stazione", "porto",
                 "plaza", "barrio", "calle", "puerto", "playa", "rio", "bairro", "vila", "jardim", "parque", "praia",
                 "nova", "novo", "alto", "baixo", "santa", "santo", "san", "sao", "zona", "industrial"}


OVERPASS_MIRRORS = ["https://overpass-api.de/api",
                    "https://overpass.kumi.systems/api",
                    "https://overpass.osm.ch/api",
                    "https://overpass.private.coffee/api",
                    "https://overpass-api.openstreetmap.fr/api"]
OVERPASS_STATE = dict(endpoint=None, tried=[])


def overpass_features(poly, tags, log=None, city="", stage="social:osm"):
    """ox.features_from_polygon with mirror fallback: one Overpass instance being down must not
    silently drop the gazetteer or the neighbouring-town filter. Records the endpoint used."""
    import osmnx as ox
    order = ([OVERPASS_STATE["endpoint"]] if OVERPASS_STATE["endpoint"] else []) + \
            [m for m in OVERPASS_MIRRORS if m != OVERPASS_STATE["endpoint"]]
    errs, switched = [], False
    # osmnx >= 2.0 reads settings.overpass_url; osmnx 1.x read settings.overpass_endpoint. Setting a name
    # the installed build does not read creates a dead attribute and every "mirror" silently stays on the
    # default host (the v5.4.1 bug), so only a name that already exists counts, and it is read back.
    settings = getattr(ox, "settings", None)
    attr = next((a for a in ("overpass_url", "overpass_endpoint") if hasattr(settings, a)), None)
    for ep in order:
        try:
            switched = False
            if attr is not None:
                try:
                    setattr(settings, attr, ep)
                    switched = getattr(settings, attr) == ep
                except Exception:  # noqa: BLE001
                    switched = False
            feats = ox.features_from_polygon(poly, tags)
            if OVERPASS_STATE["endpoint"] != ep and log is not None:
                log(city, stage, "info", f"Overpass endpoint {ep.split('//')[1].split('/')[0]}")
            OVERPASS_STATE["endpoint"] = ep if switched else None
            OVERPASS_STATE["tried"] = errs
            return feats
        except Exception as e:  # noqa: BLE001
            errs.append(f"{ep.split('//')[1].split('/')[0]}: {str(e)[:70]}")
            if log is not None:
                log(city, stage, "info", f"Overpass mirror unavailable ({errs[-1]}); trying the next one")
            if not switched:
                break      # the endpoint could not be changed, so the other mirrors are unreachable anyway
    raise RuntimeError(("every Overpass mirror failed -> " if switched else
                        "Overpass query failed and this osmnx build does not expose the endpoint setting -> ")
                       + " | ".join(errs))


def osm_gazetteer(boundary_4326, log=None, city=""):
    """Named places inside the boundary from OpenStreetMap (suburbs, neighbourhoods, localities)."""
    import osmnx as ox
    poly = boundary_4326.union_all() if hasattr(boundary_4326, "union_all") else boundary_4326.unary_union
    # "town" since v5.4.2: in the multi-municipality study areas (Valencia's Horta Sud, Romagna, Taquari) the
    # flooded places ARE towns (Paiporta, Catarroja, Faenza, Lugo); the study city's own name is removed below
    tags = {"place": ["suburb", "neighbourhood", "quarter", "locality", "village", "hamlet", "borough", "city_block",
                      "town"]}
    feats = overpass_features(poly, tags, log, city, "social:gazetteer")
    rows = []
    for _, r in feats.iterrows():
        pt = r.geometry.representative_point()
        for col in ["name", "name:en", "alt_name", "old_name"]:
            v = r.get(col)
            if isinstance(v, str):
                for nm in v.split(";"):
                    rows.append(dict(name=nm.strip(), lat=pt.y, lon=pt.x))
    return _finalise_gazetteer(rows, log, city)


def _finalise_gazetteer(rows, log=None, city=""):
    """Shared clean-up for any gazetteer: generic words, major places and pure numbers out; one entry per name;
    a name used for places more than 2 km apart is ambiguous and dropped."""
    g = pd.DataFrame(rows)
    if g.empty:
        return pd.DataFrame(columns=["key", "name", "lat", "lon"])
    g["key"] = g["name"].str.lower().str.strip()
    all_generic = g["key"].map(lambda k: all(w in GENERIC_NAMES for w in re.split(r"[\s\-]+", k) if w))
    g = g[(g["key"].str.len() >= 4) & ~g["key"].isin(GENERIC_NAMES) & ~g["key"].isin(MAJOR_PLACES) & ~all_generic & ~g["key"].str.fullmatch(r"[\d\s\-]+")]
    if g.empty:
        return pd.DataFrame(columns=["key", "name", "lat", "lon"])
    agg = g.groupby("key").agg(name=("name", "first"), lat=("lat", "mean"), lon=("lon", "mean"),
                               lat_sd=("lat", "std"), lon_sd=("lon", "std"), n=("lat", "size")).reset_index()
    spread_km = np.hypot(agg["lat_sd"].fillna(0) * 111, agg["lon_sd"].fillna(0) * 111)
    amb = agg[spread_km > 2.0]
    if log is not None and len(amb):
        log(city, "social:gazetteer", "info", f"{len(amb)} ambiguous names (same name >2 km apart) dropped")
    return agg[spread_km <= 2.0][["key", "name", "lat", "lon"]].reset_index(drop=True)


# ---------------------------------------------------------------- GeoNames gazetteer (v5.5.1)
# The OSM gazetteer depends on live Overpass servers; in the v5.5.0 run every mirror timed out for 7 of 9
# cities, so the social layer of most cities was built without any gazetteer. GeoNames country extracts are
# static files (CC BY 4.0), identical for every run and every city: the gazetteer is now reproducible.
GAZETTEER_VERSION = "geonames2"
GEONAMES_URL = "https://download.geonames.org/export/dump/{cc}.zip"
GEONAMES_COLS = ["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude", "feature_class",
                 "feature_code", "country_code", "cc2", "admin1", "admin2", "admin3", "admin4", "population",
                 "elevation", "dem", "timezone", "modification_date"]
# populated places and their sections; not capitals/first-order seats (the study city itself), not historical,
# abandoned or destroyed places
GEONAMES_CODES = {"PPL", "PPLX", "PPLL", "PPLF", "PPLS", "PPLA2", "PPLA3", "PPLA4", "PPLA5"}
COUNTRY_OF = {"Chennai": "IN", "Bengaluru": "IN", "Valencia": "ES", "EmiliaRomagna": "IT", "Forli": "IT",
              "PortoAlegre": "BR", "TaquariValley": "BR", "Houston": "US", "NewYork": "US", "Carlisle": "GB",
              "York": "GB", "Jakarta": "ID"}
_LATIN = re.compile(r"^[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\.\- ]{2,38}[A-Za-zÀ-ɏ\.]$")   # Latin + Latin-1/Extended (U+00C0-U+024F)


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
GEOCODE_RULES_VERSION = "g3"   # v6: new geocoder query (name only) -> earlier cached picks are not reused
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


def resolve_mentions(docs, gaz, cfg, bounds, ner=None, geocoder=None, max_geocode=150, log=None, city="",
                     exclude=None, cache_path=None):
    """One row per (document, place). Geolocated sources keep their own coordinates;
    others use the OSM gazetteer, then (optionally) NER + bounded geocoding."""
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
    unresolved = []
    tc = toponym_context(city, cfg)
    n_t3 = {"name": 0, "occurrence": 0}
    for i, r in rest.iterrows():
        kept = []
        for k in hits[i]:
            g = gidx.loc[k]
            v = toponym_verdict(g["name"], r.text, tc)      # rule t3, applied at acquisition (v6)
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
    n_geo_calls, n_cache_hits, n_capped = 0, 0, 0
    if ner is not None and geocoder is not None and unresolved:
        # the cache persists in cache/: a repeated or resumed run pays no geocoder calls for names
        # already looked up, so the per-run cap stops truncating coverage across runs
        cache = _geocode_cache_load(cache_path) if cache_path else {}
        n_cached_start = len(cache)
        for i in unresolved:
            r = rest.loc[i]
            try:
                ents = ner(r.text[:512])
            except Exception:  # noqa: BLE001
                continue
            places = {ph.clean_place(e["word"]) for e in ents
                      if e.get("entity_group") == "LOC" and float(e.get("score", 1.0)) >= 0.80 and "##" not in str(e.get("word", ""))}
            for p in places:
                if (not ph.is_useful_place(p, self_names(cfg)) or len(p) < 4 or _norm_place(p) in MAJOR_PLACES
                        or _norm_place(p) in NON_PLACE_WORDS or p.lower() in exclude):
                    continue
                # the key carries the rules version and the study box: a name resolved for another city (or
                # under older rules) is never reused here
                key = f"{GEOCODE_RULES_VERSION}|{p.lower()}|{_bounds_tag(bounds)}"
                if key in cache:
                    n_cache_hits += 1
                if key not in cache:
                    if n_geo_calls >= max_geocode:
                        n_capped += 1
                        continue
                    cache[key] = _pick_geocode(p, geocoder(p), bounds)
                    n_geo_calls += 1
                g = cache[key]
                if g and _in_bounds(g, bounds):
                    rows.append(dict(source=r.source, doc_id=r.doc_id, place=p, lat=float(g["lat"]), lon=float(g["lon"]),
                                     tone=r.tone, text=r.text, via="ner+nominatim", time_utc=r.time_utc))
        if cache_path and len(cache) > n_cached_start:
            _geocode_cache_save(cache_path, cache)
    # an empty result keeps its columns, so social_mentions.csv.gz stays a readable (header-only) table
    m = pd.DataFrame(rows, columns=["source", "doc_id", "place", "lat", "lon", "tone", "text", "via", "time_utc"])
    if len(m):
        m = m.drop_duplicates(["source", "doc_id", "place"]).reset_index(drop=True)
    if log is not None:
        log(city, "social:places", "ok", f"{len(m)} mentions from {m['doc_id'].nunique() if len(m) else 0} documents "
                                         f"(gazetteer names={0 if gaz is None else len(gaz)}, geocoder calls={n_geo_calls}, "
                                         f"cache hits={n_cache_hits})")
        if n_capped:
            log(city, "social:places", "warn", f"the geocoder cap ({max_geocode}) stopped {n_capped} name lookups; "
                                               f"cached names are free on the next run, so re-running widens coverage "
                                               f"— raise MAX_GEOCODE_CALLS to finish in one pass")
        cc = mention_concentration(m)
        if cc["n_mentions"]:
            msg = (f"{cc['distinct_locations']} distinct locations, effective {cc['effective_locations']}; top place "
                   f"'{cc['top_place']}' = {cc['top_share']:.0%} of mentions; top 5: {cc['top5']}")
            bad = cc["top_share"] > 0.4 or cc["effective_locations"] < 5
            log(city, "social:concentration", "warn" if bad else "info",
                msg + ("  <- the social layer is carried by very few points; it cannot localise flooding. Check "
                       "the top places are real places inside the study area" if bad else ""))
    return m
