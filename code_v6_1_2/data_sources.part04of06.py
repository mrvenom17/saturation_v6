def src_gdelt_bigquery(city, cfg, t0, t1, opts, cache_dir, log):
    client = opts.get("bq_client")
    if client is None:
        raise SourceNotApplicable("BigQuery client not available")
    from google.cloud import bigquery
    alias_re = "|".join(re.escape(a.lower()) for a in cfg["aliases"])
    sql = """
      SELECT DATE, SourceCommonName, DocumentIdentifier, V2Themes, V2Locations, V2Tone,
             REGEXP_EXTRACT(Extras, r'<PAGE_TITLE>(.*?)</PAGE_TITLE>') AS title
      FROM `gdelt-bq.gdeltv2.gkg_partitioned`
      WHERE _PARTITIONTIME >= TIMESTAMP(@p0) AND _PARTITIONTIME < TIMESTAMP(@p1)
        AND DATE BETWEEN @t0 AND @t1
        AND REGEXP_CONTAINS(LOWER(V2Themes), r'flood')
        AND (REGEXP_CONTAINS(LOWER(V2Locations), @city) OR REGEXP_CONTAINS(LOWER(Extras), @city))"""
    params = [bigquery.ScalarQueryParameter("p0", "STRING", (t0 - dt.timedelta(days=1)).strftime("%Y-%m-%d")),
              bigquery.ScalarQueryParameter("p1", "STRING", (t1 + dt.timedelta(days=2)).strftime("%Y-%m-%d")),
              bigquery.ScalarQueryParameter("t0", "INT64", int(t0.strftime("%Y%m%d%H%M%S"))),
              bigquery.ScalarQueryParameter("t1", "INT64", int(t1.strftime("%Y%m%d%H%M%S"))),
              bigquery.ScalarQueryParameter("city", "STRING", alias_re)]
    path = os.path.join(cache_dir, f"{city}_gdelt_bq_{t0:%Y%m%d}_{t1:%Y%m%d}.pkl")
    if os.path.exists(path):
        raw = pd.read_pickle(path)
    else:
        dry = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params, dry_run=True, use_query_cache=False))
        gb = dry.total_bytes_processed / 1e9
        if gb > opts.get("max_bq_gb", 60):
            raise RuntimeError(f"dry run {gb:.1f} GB exceeds cap {opts.get('max_bq_gb', 60)} GB")
        raw = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result().to_dataframe()
        raw.to_pickle(path)
        log(city, "social:gdelt_bigquery", "info", f"scanned {gb:.1f} GB")
    raw = raw.rename(columns={"title": "title"})
    return _gkg_to_docs(raw, cfg["aliases"], log, city)


def _gkg_file(url, aliases_low):
    import requests
    try:
        r = requests.get(url, timeout=120, headers=UA)
        if r.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(z.namelist()[0]) as fh:
                raw = pd.read_csv(fh, sep="\t", header=None, usecols=list(GKG_COLS), names=None, dtype=str,
                                  quoting=3, encoding="latin-1", on_bad_lines="skip", engine="c")
        raw.columns = [GKG_COLS[c] for c in raw.columns]
        low = (raw["V2Themes"].fillna("") + raw["V2Locations"].fillna("") + raw["Extras"].fillna("")).str.lower()
        m = low.str.contains("flood") & low.str.contains("|".join(re.escape(a) for a in aliases_low))
        return raw[m]
    except Exception:  # noqa: BLE001
        return None


def src_gdelt_rawfiles(city, cfg, t0, t1, opts, cache_dir, log):
    """Public GDELT 2.x GKG 15-minute files over plain HTTP (no account)."""
    path = os.path.join(cache_dir, f"{city}_gdelt_raw_{t0:%Y%m%d}_{t1:%Y%m%d}.pkl")
    if os.path.exists(path):
        raw = pd.read_pickle(path)
    else:
        stamps = pd.date_range(pd.Timestamp(t0).floor("15min"), pd.Timestamp(t1), freq="15min")
        urls = [f"http://data.gdeltproject.org/gdeltv2/{s:%Y%m%d%H%M%S}.gkg.csv.zip" for s in stamps]
        aliases_low = [a.lower() for a in cfg["aliases"]]
        with ThreadPoolExecutor(max_workers=opts.get("gdelt_threads", 8)) as ex:
            parts = list(ex.map(lambda u: _gkg_file(u, aliases_low), urls))
        got = [p for p in parts if p is not None]
        log(city, "social:gdelt_rawfiles", "info", f"{len(got)}/{len(urls)} 15-min GKG files read")
        if not got:
            raise RuntimeError("no GKG files could be downloaded")
        raw = pd.concat(got, ignore_index=True)
        raw.to_pickle(path)
    return _gkg_to_docs(raw, cfg["aliases"], log, city)


def src_google_news_rss(city, cfg, t0, t1, opts, cache_dir, log):
    """Google News RSS with date operators. Items are re-filtered by pubDate, so if
    Google ignores the operators, out-of-window items are still dropped."""
    rows, failed = [], []
    for alias in cfg["aliases"][:3]:
        for kw in query_terms(cfg.get("lang", "en")):
            q = f'"{alias}" {kw} after:{(t0 - dt.timedelta(days=1)):%Y-%m-%d} before:{(t1 + dt.timedelta(days=1)):%Y-%m-%d}'
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(dict(q=q, **cfg.get("news_locale", {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"})))
            def fetch(url=url):
                r = http_get(url, timeout=60)
                if r.status_code != 200:
                    raise TransientLookupError(f"Google News RSS: HTTP {r.status_code}")
                return r.text
            # v6.1: only a feed is cached (v6.0 cached error pages too and then skipped them silently, for good)
            try:
                body = cached_json(cache_dir, url, fetch, ok=lambda v: isinstance(v, str) and "<rss" in v[:3000].lower())
                if "<rss" not in str(body)[:3000].lower():
                    raise TransientLookupError("the answer is not a feed (consent or error page)")
                root = ET.fromstring(body)
            except Exception as e:  # noqa: BLE001
                failed.append(f'"{alias}" {kw}: {str(e)[:100]}')
                time.sleep(1.0)
                continue
            for it in root.iter("item"):
                pub = it.findtext("pubDate")
                try:
                    ts = email.utils.parsedate_to_datetime(pub)
                except Exception:  # noqa: BLE001
                    continue
                title = it.findtext("title") or ""
                rows.append(dict(doc_id=it.findtext("link") or title, url=it.findtext("link"), time_utc=ts,
                                 text=f"{title}. {it.findtext('description') or ''}"))
            time.sleep(1.0)
    df = pd.DataFrame(rows)
    df.attrs["incomplete"] = f"{len(failed)} of the feed queries failed ({failed[0]})" if failed else ""
    return df


def _arctic_page(endpoint, params, cache_dir):
    url = f"https://arctic-shift.photon-reddit.com/api/{endpoint}"
    key = url + "?" + urllib.parse.urlencode(sorted(params.items()))

    def fetch():
        r = http_get(url, params=params, timeout=90)
        if r.status_code != 200:
            raise RequestRefused(f"HTTP {r.status_code} from {endpoint}")
        return r.json()
    js = cached_json(cache_dir, key, fetch, ok=lambda v: not (isinstance(v, dict) and v.get("error")))
    if isinstance(js, dict) and js.get("error"):
        raise TransientLookupError(f"{endpoint}: {str(js['error'])[:160]}")
    return js.get("data", js) if isinstance(js, dict) else js


def src_reddit_arcticshift(city, cfg, t0, t1, opts, cache_dir, log):
    """Historical Reddit posts and comments (Arctic Shift archive, keyless)."""
    rows, failed = [], []
    a0, a1 = int(t0.replace(tzinfo=dt.timezone.utc).timestamp()), int(t1.replace(tzinfo=dt.timezone.utc).timestamp())
    for sub in cfg.get("subreddits", []):
        for endpoint, text_fields in [("posts/search", ("title", "selftext")), ("comments/search", ("body",))]:
            after, n = a0, 0
            while n < opts.get("reddit_max_items", 3000):
                params = dict(subreddit=sub, after=after, before=a1, limit=100, sort="asc")
                if endpoint == "comments/search":
                    params["body"] = " OR ".join(["flood", "rain", "water"] + QUERY_TERMS.get(cfg.get("lang", "en"), [])[:3])
                try:
                    data = _arctic_page(endpoint, params, cache_dir)
                except RequestRefused as e:
                    # the archive does not accept this query for this subreddit: the same on every run, so it is
                    # reported and the source is NOT left waiting for a retry
                    log(city, "social:reddit", "warn", f"r/{sub} {endpoint} refused by the archive ({e}); nothing from there")
                    break
                except Exception as e:  # noqa: BLE001
                    log(city, "social:reddit", "warn", f"r/{sub} {endpoint}: {e}")
                    failed.append(f"r/{sub} {endpoint}: {str(e)[:120]}")
                    break
                if not isinstance(data, list) or not data:
                    break
                for p in data:
                    txt = " ".join(str(p.get(f) or "") for f in text_fields)
                    rows.append(dict(doc_id=f"{endpoint[:4]}_{p.get('id')}", url=f"https://reddit.com/r/{sub}/comments/{p.get('link_id', p.get('id'))}",
                                     time_utc=pd.to_datetime(p.get("created_utc"), unit="s", utc=True), text=txt))
                n += len(data)
                last = max(int(p.get("created_utc", after)) for p in data)
                if len(data) < 100 or last <= after:
                    break
                after = last + 1
                time.sleep(0.5)
    df = pd.DataFrame(rows)
    df = df[df["text"].str.contains(FLOOD_RE)] if len(df) else df
    # v6.1: pages that failed are reported to collect_documents, which keeps what was fetched but marks the source
    # incomplete, so the documents stage is not frozen and the missing pages are fetched on the next run
    df.attrs["incomplete"] = "; ".join(failed[:3]) if failed else ""
    return df


def src_youtube(city, cfg, t0, t1, opts, cache_dir, log):
    key = opts.get("youtube_api_key")
    if not key:
        raise SourceNotApplicable("YOUTUBE_API_KEY not set (optional source)")
    rows = []
    terms = query_terms(cfg.get("lang", "en"), n_local=1, n_en=1)
    for alias, kw in [(a, t) for a in cfg["aliases"][:2] for t in terms]:
        token = None
        for _ in range(3):
            params = dict(part="snippet", q=f"{alias} {kw}", type="video", maxResults=50, key=key,
                          publishedAfter=t0.strftime("%Y-%m-%dT%H:%M:%SZ"), publishedBefore=t1.strftime("%Y-%m-%dT%H:%M:%SZ"))
            if token:
                params["pageToken"] = token
            ck = "yt|" + json.dumps({k: v for k, v in params.items() if k != "key"}, sort_keys=True)
            js = cached_json(cache_dir, ck, lambda: http_get("https://www.googleapis.com/youtube/v3/search", params=params).json(),
                             ok=lambda v: isinstance(v, dict) and "error" not in v)
            if "error" in js:
                raise RuntimeError(js["error"].get("message", "YouTube API error"))
            for it in js.get("items", []):
                sn = it.get("snippet", {})
                rows.append(dict(doc_id=it.get("id", {}).get("videoId"), url=f"https://youtu.be/{it.get('id', {}).get('videoId')}",
                                 time_utc=sn.get("publishedAt"), text=f"{sn.get('title', '')}. {sn.get('description', '')}"))
            token = js.get("nextPageToken")
            if not token:
                break
    return pd.DataFrame(rows)


def src_petabencana(city, cfg, t0, t1, opts, cache_dir, log):
    """PetaBencana crowdsourced flood reports (geolocated; Indonesia only)."""
    region = cfg.get("petabencana_region")
    if not region:
        raise SourceNotApplicable("not an Indonesian city")
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
        raise SourceNotApplicable("FLICKR_API_KEY not set (optional source)")
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
        js = cached_json(cache_dir, ck, lambda: http_get(FLICKR_REST, params=params, timeout=60).json(),
                         ok=lambda v: isinstance(v, dict) and v.get("stat") == "ok")
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


COMMONS_RETRYABLE = ("too busy", "maxlag", "ratelimited", "readonly", "try again")


def _commons_get(params, opts, cache_dir, tries=5):
    """One Commons API call (v6.1). Paced per host (see HOST_PACE), sent with maxlag as the API etiquette asks,
    with an optional personal access token, and retried when the server answers with a retryable error BODY
    (HTTP 200, e.g. "Search is currently too busy"). Only good answers are cached."""
    params = dict(params, maxlag=5)
    hdr = {"Authorization": f"Bearer {opts['wikimedia_access_token']}"} if (opts or {}).get("wikimedia_access_token") else {}
    key = "commons2|" + json.dumps(params, sort_keys=True)
    good = lambda v: isinstance(v, dict) and not v.get("error")
    js = None
    for k in range(tries):
        js = cached_json(cache_dir, key, lambda: http_get(COMMONS_API, params=params, headers=hdr, timeout=60,
                                                          retries=5).json(), ok=good)
        if good(js):
            return js
        info = str((js or {}).get("error", {}).get("info", js))[:200] if isinstance(js, dict) else str(js)[:200]
        code = str((js or {}).get("error", {}).get("code", "")) if isinstance(js, dict) else ""
        if not any(w in (info + " " + code).lower() for w in COMMONS_RETRYABLE):
            raise RuntimeError(f"Commons API error: {info}")
        if k < tries - 1:
            time.sleep(min(10.0 * (k + 1), 60.0))
    raise TransientLookupError(f"Commons API still failing after {tries} tries: {info}")


COMMONS_TILE_LIMIT = 500           # the API returns at most this many files per geosearch request, with no continuation
COMMONS_MIN_TILE_DEG = 0.00125     # ~140 m: a full tile is not subdivided below this


def _commons_scan(tile, opts, cache_dir, stats):
    """All geotagged Commons files in one box (v6.1.1). list=geosearch returns at most COMMONS_TILE_LIMIT files and
    cannot be continued, so a tile that comes back full is split into four and each quarter is asked again, down to
    COMMONS_MIN_TILE_DEG. v6.1 read each ~9 km tile once: in the first real acquisition two of York's four tiles
    came back with exactly 500 files (the other two held 481 and 328), so any further photos in those two tiles
    were never examined."""
    top, left, bottom, right = tile
    params = dict(action="query", list="geosearch", gsbbox=f"{top}|{left}|{bottom}|{right}", gsnamespace=6,
                  gslimit=COMMONS_TILE_LIMIT, format="json")
    js = _commons_get(params, opts, cache_dir)
    stats["requests"] += 1
    ids = [g["pageid"] for g in ((js or {}).get("query") or {}).get("geosearch", [])]
    if len(ids) < COMMONS_TILE_LIMIT:
        return ids
    if min(float(top) - float(bottom), float(right) - float(left)) <= COMMONS_MIN_TILE_DEG:
        stats["truncated"] += 1
        return ids
    stats["split"] += 1
    mid_lat, mid_lon = (float(top) + float(bottom)) / 2.0, (float(left) + float(right)) / 2.0
    out = []
    for sub in ((top, left, mid_lat, mid_lon), (top, mid_lon, mid_lat, right),
                (mid_lat, left, bottom, mid_lon), (mid_lat, mid_lon, bottom, right)):
        out += _commons_scan(sub, opts, cache_dir, stats)
    return out


def src_wikimedia_commons(city, cfg, t0, t1, opts, cache_dir, log):
    """Wikimedia Commons photos with camera/photographer coordinates, taken in the window (keyless)."""
    b = cfg["bounds"]
    rx = flood_text_re(cfg.get("lang", "en"))
    ids, stats = [], dict(requests=0, split=0, truncated=0)
    for tile in _commons_tiles(b):
        ids += _commons_scan(tile, opts, cache_dir, stats)
    ids = list(dict.fromkeys(ids))
    rows = []
    for i in range(0, len(ids), 50):
        params = dict(action="query", pageids="|".join(map(str, ids[i:i + 50])), prop="coordinates|imageinfo|categories",
                      iiprop="extmetadata|user", iiextmetadatafilter="DateTimeOriginal|ImageDescription",
                      cllimit="max", clshow="!hidden", format="json")
        js = _commons_get(params, opts, cache_dir)
        rows += _commons_rows(((js or {}).get("query") or {}).get("pages"), t0, t1, rx)
        if i and i % 5000 == 0:
            log(city, "social:wikimedia_commons", "info", f"{i} of {len(ids)} files examined ...")
    log(city, "social:wikimedia_commons", "info",
        f"{len(ids)} geotagged files in the box ({stats['requests']} tile requests, {stats['split']} dense tiles "
        f"subdivided); {len(rows)} flood photos taken in the window")
    if stats["truncated"]:
        log(city, "social:wikimedia_commons", "warn",
            f"{stats['truncated']} spots of about {COMMONS_MIN_TILE_DEG * 111000:.0f} m still hold {COMMONS_TILE_LIMIT} or more "
            f"files (a heavily photographed landmark); only {COMMONS_TILE_LIMIT} of each were read. Report this")
    return pd.DataFrame(rows)


SOCIAL_SOURCES = {"gdelt_bigquery": src_gdelt_bigquery, "gdelt_rawfiles": src_gdelt_rawfiles,
                  "google_news_rss": src_google_news_rss, "reddit_arcticshift": src_reddit_arcticshift,
                  "youtube": src_youtube, "petabencana": src_petabencana, "flickr": src_flickr,
                  "wikimedia_commons": src_wikimedia_commons}
PHOTO_SOURCES = {"flickr", "wikimedia_commons"}
# v6.1: what kind of signal each source is. The v6.0 layer was 87-98% news articles in eight of ten cities, so it
# has to be reported as a news-media signal wherever that is what it is (see signal_composition).
SOURCE_KIND = {"gdelt_bigquery": "news", "gdelt_rawfiles": "news", "google_news_rss": "news",
               "reddit_arcticshift": "social_media", "youtube": "social_media",
               "flickr": "geotagged_photo", "wikimedia_commons": "geotagged_photo", "petabencana": "crowdsourced_report"}
SIGNAL_LABELS = {"news": "news-media signal", "social_media": "social-media signal",
                 "geotagged_photo": "geotagged-photo signal", "crowdsourced_report": "crowdsourced-report signal"}


def signal_composition(frame):
    """Shares of documents or mentions by kind of source, and the honest name of the layer: the dominant kind if it
    carries at least 80%, else 'mixed'. Label-free."""
    if frame is None or len(frame) == 0 or "source" not in frame:
        return dict(n=0, shares={}, signal_type="no signal")
    kinds = frame["source"].map(lambda x: SOURCE_KIND.get(str(x), "other"))
    sh = kinds.value_counts(normalize=True)
    top, share = str(sh.index[0]), float(sh.iloc[0])
    name = SIGNAL_LABELS.get(top, top) if share >= 0.8 else "mixed signal (" + ", ".join(f"{k} {v:.0%}" for k, v in sh.items()) + ")"
    return dict(n=int(len(frame)), shares={str(k): round(float(v), 3) for k, v in sh.items()}, signal_type=name)


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
            partial = str(getattr(raw_df, "attrs", {}).get("incomplete") or "")
            df = finalize_docs(raw_df, name, t0, t1)
            if n_raw and len(df) < n_raw:
                log(city, f"social:{name}", "info", f"{n_raw} fetched -> {len(df)} kept "
                                                     f"({n_raw - len(df)} outside the window, empty or duplicate)")
            frames.append(df)
            status.append(dict(source=name, status="incomplete" if partial else "ok", n=len(df),
                               detail=partial or f"{time.time() - t:.0f}s", retry=bool(partial)))
            log(city, f"social:{name}", "ok" if len(df) else "warn", f"{len(df)} documents in window")
            if partial:
                log(city, f"social:{name}", "warn", f"INCOMPLETE ({partial}): the documents stage is not frozen; "
                                                     f"re-run the acquisition to fetch the rest")
            if name == "gdelt_bigquery" and len(df) > 0:
                gdelt_done = True
        except SourceNotApplicable as e:
            status.append(dict(source=name, status="not_applicable", n=0, detail=str(e)[:300], retry=False))
            log(city, f"social:{name}", "skip", str(e)[:200])
        except Exception as e:  # noqa: BLE001
            # v6.1: a source that FAILED (rate limit, timeout, server error) is not the same as a source that does
            # not apply. v6.0 froze the documents stage either way, so Wikimedia Commons (HTTP 429 in every city) was
            # never asked again by any later run. A failed source is now retried on the next run.
            status.append(dict(source=name, status="failed", n=0, detail=str(e)[:300], retry=True))
            log(city, f"social:{name}", "warn", f"FAILED, will be retried on the next run: {str(e)[:200]}")
    docs = pd.concat(frames, ignore_index=True) if frames else empty_docs()
    if len(docs):
        docs = dedupe_documents(docs, log, city)
    return docs, pd.DataFrame(status, columns=["source", "status", "n", "detail", "retry"])


def documents_complete(status):
    """True if no source of this city is waiting to be retried (label-free; decides whether the stage is frozen)."""
    if status is None or len(status) == 0 or "retry" not in status:
        return True
    return not bool(pd.Series(status["retry"]).fillna(False).astype(bool).any())


def documents_fingerprint(docs):
    """Identity of a document set (v6.1). The mentions stage is keyed on it: until v6.0 it was keyed on the
    documents stage's CONFIGURATION only, so documents that changed under the same configuration (a source that
    came back, a cap that was lifted) would have been paired with stale mentions."""
    if docs is None or len(docs) == 0:
        return "empty"
    ids = sorted((docs["source"].astype(str) + "|" + docs["doc_id"].astype(str)).tolist())
    h = hashlib.sha1("\n".join(ids).encode())
    h.update(str(int(docs["text"].astype(str).str.len().sum())).encode())
    return h.hexdigest()[:12]


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
