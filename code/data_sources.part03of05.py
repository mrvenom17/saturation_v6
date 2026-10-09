# ==================================================================================================
# Label assets: exact sources, one-time download into Drive, canonical form
# --------------------------------------------------------------------------------------------------
# Every entry is the AUTHORITATIVE entry point for that event's ground truth, with its licence.
# "api" entries are catalogue endpoints the connector walks (the individual product archive URLs are
# issued by the catalogue and are not stable); "file" entries are direct downloads; "page" entries are
# dataset pages whose download link is scraped. verify_label_sources() checks every URL before a run,
# and prefetch_label_assets() downloads each once into <Drive>/label_assets and freezes it as a
# canonical GeoPackage, so later runs read one local file instead of re-downloading anything.
# Verified 21 Sep 2026 by fetching each entry point (or its official landing page where the host blocks
# automated reads, noted in "verified"). "kind": api = catalogue endpoint walked at run time (product
# URLs are issued by the catalogue); file = direct download; feature = one OGC API feature.
EA_OGC = ("https://environment.data.gov.uk/spatialdata/recorded-flood-outlines/ogc/features/v1/collections/"
          "Recorded_Flood_Outlines/items/")
EMS_S3 = "https://cems-mapping-website.s3.eu-west-1.amazonaws.com/static/activations/"
OPENCITY_CHN15 = "https://data.opencity.in/dataset/866141ab-3a3f-4dc0-8092-421d97ba29a2/resource/"
LABEL_SOURCES_DOC = {
    "Valencia_2024": [dict(kind="api", source="copernicus_ems", ref="EMSR773 (DEL images 30 Oct - 8 Nov 2024)",
                           url="https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR773",
                           licence="Copernicus EMS — free, attribution required", verified="API fetched")],
    "EmiliaRomagna_2023a": [dict(kind="api", source="copernicus_ems", ref="EMSR659 (DEL images 4 May 2023)",
                                 url="https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR659",
                                 licence="Copernicus EMS — free, attribution required", verified="API fetched")],
    "Forli_2023b": [dict(kind="api", source="copernicus_ems", ref="EMSR664 AOI01 Forlì (DEL images 17-21 May 2023)",
                         url="https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR664",
                         licence="Copernicus EMS — free, attribution required", verified="API fetched")],
    "TaquariValley_2024": [dict(kind="api", source="copernicus_ems", ref="EMSR720 (AOIs Guaporé, Encantado, Roca Sales, Das Antas, Santa Tereza)",
                                url="https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR720",
                                licence="Copernicus EMS — free, attribution required", verified="API fetched")],
    "PortoAlegre_2024": [dict(kind="api", source="arcgis_featureserver", ref="EMSN194 Extent Temporal Evolution layers",
                              url="https://arcgis.jrc.ec.europa.eu/server/rest/services/Hosted/EMSN194_Vector_Layers/FeatureServer?f=json",
                              licence="Copernicus EMS Risk & Recovery — free, attribution required",
                              verified="service listing fetched; layer queries not yet exercised")],
    "Houston_SanJacinto_2017": [
        dict(kind="api", source="usgs_sciencebase", ref="USGS 10.5066/F7VH5N3N, San Jacinto child 5aa023ebe4b0b1c392e6881b",
             url="https://www.sciencebase.gov/catalog/item/5aa023ebe4b0b1c392e6881b?format=json",
             licence="USGS — public domain", verified="via data.usgs.gov (ScienceBase blocks automated reads)"),
        dict(kind="api", source="usgs_stn", ref="STN event 180 (2017 Harvey), Harris + Montgomery counties",
             url="https://stn.wim.usgs.gov/STNServices/HWMs/FilteredHWMs.json?Event=180&States=TX&County=Harris%20County",
             licence="USGS — public domain", verified="API fetched")],
    "NewYork_2021": [
        dict(kind="api", source="usgs_sciencebase", ref="USGS 10.5066/P9JF4OWB depth rasters (within 250 m of the 83 HWM sites)",
             url="https://www.sciencebase.gov/catalog/item/63badf22d34e92aad3cd279e?format=json",
             licence="USGS — CC0", verified="via DataCite/usgs.gov (ScienceBase blocks automated reads)"),
        dict(kind="api", source="usgs_stn", ref="STN event 312 (2021 Ida), NYC counties",
             url="https://stn.wim.usgs.gov/STNServices/HWMs/FilteredHWMs.json?Event=312&States=NY&County=Kings%20County",
             licence="USGS — public domain", verified="API fetched")],
    "Carlisle_2015": [
        dict(kind="feature", source="file_url", ref="EA Recorded Flood Outline rec_out_id 4078182 'Carlisle (including Crosby-on-Eden) 05_12_2015'",
             url=EA_OGC + "Recorded_Flood_Outlines.26355?f=json", licence="Open Government Licence v3.0", verified="fetched"),
        dict(kind="file", source="copernicus_ems", ref="EMSR147 AOI01 Carlisle delineation",
             url=EMS_S3 + "EMSR147/EMSR147_01CARLISLE_DELINEATION_OVERVIEW_v1_vector.zip",
             licence="Copernicus EMS — free, attribution required", verified="listed on the activation page")],
    "York_2015": [
        dict(kind="feature", source="file_url", ref="EA Recorded Flood Outline rec_out_id 4084890 'December 2015 Flood Event' (Ouse/Derwent; clipped to York)",
             url=EA_OGC + "Recorded_Flood_Outlines.27083?f=json", licence="Open Government Licence v3.0", verified="fetched"),
        dict(kind="file", source="copernicus_ems", ref="EMSR150 AOI01 York delineation",
             url=EMS_S3 + "EMSR150/EMSR150_01YORK_DELINEATION_OVERVIEW_v1_vector.zip",
             licence="Copernicus EMS — free, attribution required", verified="listed on the activation page")],
    "Jakarta_2020": [dict(kind="api", source="petabencana", ref="reports archive (crowdsourced)",
                          url="https://data.petabencana.id/reports/archive?start=2019-12-31T00:00:00%2B0000&end=2020-01-04T00:00:00%2B0000&geoformat=geojson",
                          licence="CC BY-NC 4.0", verified="endpoint fetched (no key)")],
    "Jakarta_2020b": [dict(kind="api", source="petabencana", ref="reports archive (crowdsourced)",
                           url="https://data.petabencana.id/reports/archive?start=2020-02-24T00:00:00%2B0000&end=2020-02-28T00:00:00%2B0000&geoformat=geojson",
                           licence="CC BY-NC 4.0", verified="endpoint fetched (no key)")],
    "Chennai_2015": [
        dict(kind="file", source="file_url", ref="NRSC 2015 flood inundation zone (via Chennai SDSS; image date/sensor not stated)",
             url=OPENCITY_CHN15 + "2056abd6-26d7-413b-9dfa-e63cbbf41ee7/download/7cb3cecf-a95a-4786-8032-9c7417655d24.kml",
             licence="OpenCity: Other (Public Domain)", verified="resource page fetched"),
        dict(kind="file", source="file_url", ref="GCC water-stagnation locations 2015 (points)",
             url=OPENCITY_CHN15 + "b5f39598-2e2d-40c5-82c3-806a1ad65c91/download/db3840ff-9f33-43a3-b826-2f9dae1bcb78.kml",
             licence="OpenCity: Other (Public Domain)", verified="resource page fetched"),
        dict(kind="file", source="file_url", ref="OSM-India crowdsourced flooded streets, 11:00 2 Dec 2015",
             url="https://raw.githubusercontent.com/osm-in/flood-map/gh-pages/data/chennai-flooded-streets-Dec2.geojson",
             licence="MIT (repo) / ODbL (OSM geometries)", verified="fetched"),
        dict(kind="api", source="gfd", ref="Global Flood Database DFO 4309 (MODIS 250 m)",
             url="https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_EVENTS_V1",
             licence="CC BY-NC 4.0", verified="catalog fetched")],
    "Chennai_2021": [dict(kind="file", source="ai4g_sar", ref="AI4G tile N12E078 (Sentinel-1 detections)",
                          url=AI4G_BASE + "/N12/N12E078/N12E078-post-processing.parquet",
                          licence="MIT (dataset card)", verified="tree listing fetched; resolve URL checked at run time")],
    "Chennai_2023": [dict(kind="file", source="ai4g_sar", ref="AI4G tile N12E078 (Sentinel-1 detections)",
                          url=AI4G_BASE + "/N12/N12E078/N12E078-post-processing.parquet",
                          licence="MIT (dataset card)", verified="tree listing fetched; resolve URL checked at run time")],
    "Bengaluru_2022": [dict(kind="file", source="ai4g_sar", ref="AI4G tile N12E075 (Sentinel-1 detections)",
                            url=AI4G_BASE + "/N12/N12E075/N12E075-post-processing.parquet",
                            licence="MIT (dataset card)", verified="tree listing fetched; resolve URL checked at run time")],
}

# Which kind of ground truth each source is. Only tier A enters the confirmatory analysis.
SOURCE_TIER = {"copernicus_ems": "A_authoritative", "usgs_sciencebase": "A_authoritative",
               "portal_download": "A_authoritative", "arcgis_featureserver": "A_authoritative",
               "file_url": "A_authoritative", "usgs_stn": "A_authoritative_points", "official": "unverified",
               "official_points": "unverified", "petabencana_area": "B_crowdsourced",
               "gfd": "C_satellite", "s1_change": "C_satellite", "s2_change": "C_satellite", "ai4g_sar": "C_satellite"}
SAR_LABEL_SOURCES = {"s1_change", "ai4g_sar"}

CANON_COLS = ["city", "event_date", "source", "gt_tier", "layer", "feat_date", "depth_m", "geometry"]


def to_canonical_labels(gdf, city, event_date, source, extra=None):
    """One schema for every label source: WGS84 polygons/points with provenance columns, so the
    frozen file is readable without knowing which portal it came from."""
    import geopandas as gpd
    if gdf is None or len(gdf) == 0:
        return gpd.GeoDataFrame({c: pd.Series(dtype="object") for c in CANON_COLS if c != "geometry"},
                                geometry=[], crs="EPSG:4326")
    g = gdf.copy()
    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    g = g.to_crs("EPSG:4326").reset_index(drop=True)
    date_col = ("feat_date" if "feat_date" in g.columns else
                next((c for c in g.columns if re.search(r"(?i)date|time|start|fecha|data", str(c))
                      and c != "geometry"), None))
    depth_col = ("depth_m" if "depth_m" in g.columns else
                 next((c for c in g.columns if re.search(r"(?i)depth|deep|prof|water_lev", str(c))), None))
    n = len(g)
    out = gpd.GeoDataFrame({
        "city": [city] * n, "event_date": [str(event_date)] * n, "source": [source] * n,
        "gt_tier": [str((extra or {}).get("gt_tier") or SOURCE_TIER.get(source.split(":")[0], ""))] * n,
        "layer": g["_src_layer"].astype(str).to_numpy() if "_src_layer" in g else
                 [str((extra or {}).get("layer", source))] * n,
        "feat_date": g[date_col].astype(str).to_numpy() if date_col else [None] * n,
        "depth_m": pd.to_numeric(g[depth_col], errors="coerce").to_numpy() if depth_col else np.full(n, np.nan),
    }, geometry=g.geometry.values, crs="EPSG:4326")
    return out[CANON_COLS]


def canonical_label_path(assets_root, city):
    return os.path.join(assets_root, f"{city}_labels.gpkg")


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def write_canonical_labels(gdf, assets_root, city, log=None, meta=None, coverage=None):
    """Freeze one city's ground truth as a single GeoPackage plus a manifest row (sha256, counts,
    bbox). Layer 'labels' holds the flooded features; layer 'coverage' (when the product has one)
    the mapped-area footprint, so a frozen run keeps the same valid-cell mask as a live run."""
    import geopandas as gpd
    os.makedirs(assets_root, exist_ok=True)
    path = canonical_label_path(assets_root, city)
    tmp = path + ".tmp.gpkg"
    if os.path.exists(tmp):
        os.remove(tmp)
    gdf.to_file(tmp, driver="GPKG", layer="labels")
    n_cov = 0
    if coverage is not None and len(coverage):
        cov = gpd.GeoDataFrame(geometry=coverage.to_crs("EPSG:4326").geometry.values, crs="EPSG:4326")
        cov.to_file(tmp, driver="GPKG", layer="coverage")
        n_cov = len(cov)
    os.replace(tmp, path)
    b = gdf.total_bounds
    row = dict(city=city, path=path, bytes=os.path.getsize(path), sha256=file_sha256(path),
               features=int(len(gdf)), geom_types=",".join(sorted(set(gdf.geometry.geom_type.astype(str)))),
               min_lon=round(float(b[0]), 5), min_lat=round(float(b[1]), 5),
               max_lon=round(float(b[2]), 5), max_lat=round(float(b[3]), 5),
               source=",".join(sorted(set(gdf["source"].astype(str)))) if len(gdf) else "",
               gt_tier=",".join(sorted(set(gdf["gt_tier"].astype(str)))) if len(gdf) and "gt_tier" in gdf else "",
               coverage_polygons=n_cov, written_utc=dt.datetime.utcnow().isoformat() + "Z", **(meta or {}))
    if log is not None:
        log(city, "label:assets", "ok", f"froze {len(gdf)} features -> {os.path.basename(path)} "
                                        f"({row['bytes']/1e6:.2f} MB, sha256 {row['sha256'][:12]})")
    return path, row


def fetch_canonical_gpkg(city, cfg, prereg, cache_dir, log, assets_root=None, point_buffer_m=0.0,
                         date_filter=False, **_):
    """Read the frozen GeoPackage for this city (offline, no network). Raises if it is absent, so the
    label chain falls through to the live source."""
    import geopandas as gpd
    root = assets_root or cfg.get("assets_root") or os.path.join(cache_dir, "label_assets")
    path = canonical_label_path(root, city)
    if not os.path.exists(path):
        raise RuntimeError(f"no frozen label file at {path}; run the prefetch cell once, or let the "
                           f"live source run")
    gdf = gpd.read_file(path, layer="labels", bbox=_bbox_tuple(cfg))
    if len(gdf) == 0:
        raise RuntimeError(f"frozen label file holds no features inside the study area ({os.path.basename(path)})")
    extra = dict(frozen_file=os.path.basename(path), sha256=file_sha256(path)[:16],
                 frozen_source=",".join(sorted(set(gdf["source"].astype(str)))), features_in_bbox=int(len(gdf)),
                 gt_tier=",".join(sorted(set(gdf["gt_tier"].astype(str)))) if "gt_tier" in gdf else "")
    try:
        import pyogrio
        if "coverage" in [l[0] for l in pyogrio.list_layers(path)]:
            cov = gpd.read_file(path, layer="coverage")
            if len(cov):
                extra["_aoi_gdf"] = cov
    except Exception:  # noqa: BLE001
        pass
    if date_filter and "feat_date" in gdf:
        # only the per-feature date may drive filtering; "event_date" is provenance metadata and is
        # constant, so it must not be mistaken for an observation date
        probe = gdf[["feat_date", "geometry"]].rename(columns={"feat_date": "date"})
        probe, dinfo = filter_by_event_date(probe, cfg["event_date"], prereg["label"]["event_window_days"], log, city)
        gdf = gdf.loc[probe.index] if len(probe) else gdf.iloc[0:0]
        extra["date_filter"] = dinfo
    extra["point_buffer_m"] = point_buffer_m
    log(city, "label:canonical_gpkg", "ok", f"{len(gdf)} features from the frozen file "
                                            f"(sha256 {extra['sha256'][:12]}, no download)")
    return gdf, extra


def label_canonical_gpkg(city, cfg, G, df, prereg, cache_dir, log, **kw):
    gdf, extra = fetch_canonical_gpkg(city, cfg, prereg, cache_dir, log, **kw)
    aoi = extra.pop("_aoi_gdf", None)
    y, ys, info = _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=extra.get("point_buffer_m", 0.0),
                             source="canonical_gpkg", extra=extra)
    if aoi is not None and len(aoi):
        _apply_coverage(info, df, G, aoi, log, city, "canonical_gpkg", "inside the frozen mapped-area footprint")
    else:
        info.update(coverage_polygons=0, coverage_fraction=1.0)
        log(city, "label:canonical_gpkg", "info", "no mapped-area footprint stored with this label: every grid cell "
                                                  "is treated as mapped (report this for the city)")
    return y, ys, info


def verify_label_sources(cities, log=None):
    """Check every documented ground-truth URL before a run. Network-only, no downloads."""
    rows = []
    for city in cities:
        for e in LABEL_SOURCES_DOC.get(city, []):
            status, detail = "missing", ""
            try:
                r = http_get(e["url"], timeout=90, retries=2, allow_status=(200, 301, 302, 403, 404, 405))
                status = "ok" if r.status_code == 200 else f"http {r.status_code}"
                detail = f"{len(getattr(r, 'text', '') or '')/1000:.0f} kB"
            except Exception as ex:  # noqa: BLE001
                status, detail = "unreachable", str(ex)[:120]
            rows.append(dict(city=city, source=e["source"], kind=e["kind"], ref=e.get("ref", ""),
                             url=e["url"], licence=e["licence"], verified_when_written=e.get("verified", ""),
                             status=status, detail=detail))
            if log is not None:
                log(city, "label:verify", "ok" if status == "ok" else "warn",
                    f"{e['source']} {e.get('ref', '')}: {status} {detail}")
    return pd.DataFrame(rows)


def _cached_manifest_row(city, path, assets_root, log):
    """Manifest row for an already-frozen file: keep the row written when it was frozen (source, tier,
    live source) and re-measure the file, so a cached run never blanks the provenance."""
    import geopandas as gpd
    old = {}
    mp = os.path.join(assets_root, "label_assets_manifest.csv")
    if os.path.exists(mp):
        try:
            m = pd.read_csv(mp)
            m = m[(m["city"] == city) & m["status"].astype(str).eq("frozen")]
            if len(m):
                old = m.iloc[-1].dropna().to_dict()
        except Exception:  # noqa: BLE001
            old = {}
    row = dict(old, city=city, path=path, status="cached", bytes=os.path.getsize(path), sha256=file_sha256(path))
    try:
        g = gpd.read_file(path, layer="labels")
        b = g.total_bounds
        row.update(features=int(len(g)), geom_types=",".join(sorted(set(g.geometry.geom_type.astype(str)))),
                   min_lon=round(float(b[0]), 5), min_lat=round(float(b[1]), 5),
                   max_lon=round(float(b[2]), 5), max_lat=round(float(b[3]), 5))
        if "source" in g and "source" not in old:
            row["source"] = ",".join(sorted(set(g["source"].astype(str))))
        if "gt_tier" in g and "gt_tier" not in old:
            row["gt_tier"] = ",".join(sorted(set(g["gt_tier"].astype(str))))
        import pyogrio
        layers = [l[0] for l in pyogrio.list_layers(path)]
        row["coverage_polygons"] = int(len(gpd.read_file(path, layer="coverage"))) if "coverage" in layers else 0
    except Exception as e:  # noqa: BLE001
        log(city, "label:assets", "warn", f"frozen file could not be re-read: {str(e)[:120]}")
    if old.get("sha256") and old["sha256"] != row["sha256"]:
        log(city, "label:assets", "warn", "frozen file changed since it was written (sha256 differs from the manifest)")
    log(city, "label:assets", "info", f"already frozen ({os.path.basename(path)}, {row.get('features', '?')} features, "
                                      f"coverage polygons {row.get('coverage_polygons', '?')}, sha256 "
                                      f"{row['sha256'][:12]}); set REFREEZE_LABEL_FILES=True to rebuild")
    return row


def prefetch_label_assets(cities, registry, prereg, cache_dir, assets_root, log, overwrite=False):
    """Download each city's ground truth ONCE and freeze it as a canonical GeoPackage in Drive.
    Vector sources only (rasters stay in the download cache and are read from there)."""
    os.makedirs(assets_root, exist_ok=True)
    man = []
    for city in cities:
        cfg = dict(registry[city])
        path = canonical_label_path(assets_root, city)
        if os.path.exists(path) and not overwrite:
            man.append(_cached_manifest_row(city, path, assets_root, log))
            continue
        src = next((s for s in cfg["label_chain"]
                    if s.split(":")[0] in VECTOR_LABEL_SOURCES and s != "canonical_gpkg"), None)
        if src is None:
            log(city, "label:assets", "info", "no vector label source in this chain (satellite labels are "
                                              "computed in Earth Engine, nothing to freeze)")
            man.append(dict(city=city, path="", status="no_vector_source", features=0))
            continue
        # search the widest sensible box so the frozen file is not clipped to the current grid
        region = cfg.get("label_search_bounds") or cfg.get("bounds")
        open_cfg = dict(cfg, bounds=region)
        params = dict((cfg.get("label_params") or {}).get(src, {}))
        try:
            gdf, extra = VECTOR_LABEL_SOURCES[src.split(":")[0]](city, open_cfg, prereg, cache_dir, log, **params)
            canon = to_canonical_labels(gdf, city, cfg["event_date"], src, extra)
            if len(canon) == 0:
                raise RuntimeError("source returned no vector features (raster-only products stay in the "
                                   "download cache and are read from there)")
            p, row = write_canonical_labels(canon, assets_root, city, log, coverage=extra.get("_aoi_gdf"),
                                            meta=dict(status="frozen", live_source=src,
                                                      rasters=int(extra.get("n_rasters", 0) or 0)))
            man.append(row)
        except Exception as e:  # noqa: BLE001
            log(city, "label:assets", "warn", f"could not freeze {src}: {str(e)[:160]}")
            man.append(dict(city=city, path="", status="failed", features=0, error=str(e)[:200], live_source=src))
    mf = pd.DataFrame(man)
    mp = os.path.join(assets_root, "label_assets_manifest.csv")
    # merge with the manifest of earlier sessions: freezing city B must not erase city A's row
    if os.path.exists(mp):
        try:
            old = pd.read_csv(mp)
            old = old[~old["city"].isin(mf["city"])]
            mf = pd.concat([old, mf], ignore_index=True)
        except Exception:  # noqa: BLE001
            pass
    mf.to_csv(mp, index=False)
    mf = mf[mf["city"].isin(list(cities))].reset_index(drop=True)
    log("", "label:assets", "ok", f"manifest written: {mp}")
    return mf

VECTOR_LABEL_SOURCES = {"copernicus_ems": fetch_copernicus_ems, "usgs_sciencebase": fetch_usgs_sciencebase,
                        "portal_download": fetch_portal_download, "file_url": fetch_file_url,
                        "usgs_stn": fetch_usgs_stn, "arcgis_featureserver": fetch_arcgis_featureserver,
                        "petabencana_area": fetch_petabencana_reports}

VECTOR_LABEL_SOURCES["canonical_gpkg"] = fetch_canonical_gpkg

LABEL_FUNCS = {"official": label_official,
               "canonical_gpkg": label_canonical_gpkg,
               "copernicus_ems": label_copernicus_ems,
               "usgs_sciencebase": label_usgs_sciencebase,
               "portal_download": label_portal_download,
               "petabencana_area": label_petabencana_area,
               "official_points": lambda *a, **k: label_official(*a, **k, geom="points"),
               "gfd": label_gfd, "s1_change": label_s1_change, "s2_change": label_s2_change,
               "file_url": _label_with_coverage("file_url", fetch_file_url),
               "usgs_stn": _label_with_coverage("usgs_stn", fetch_usgs_stn),
               "arcgis_featureserver": _label_with_coverage("arcgis_featureserver", fetch_arcgis_featureserver),
               "ai4g_sar": label_ai4g_sar,
               }


def label_chain(city, cfg, G, df, prereg, cache_dir, log, out_dir=None):
    """Try label sources in the configured order; accept the first that passes
    the pre-registered checks. Every attempt is logged."""
    lo, hi = prereg["label"]["prevalence_bounds"]
    mn = prereg["label"]["min_positive_cells"]
    attempts = []
    for src in cfg["label_chain"]:
        try:
            params = (cfg.get("label_params") or {}).get(src, {})
            y, y_sens, info = LABEL_FUNCS[src.split(":")[0]](city, cfg, G, df, prereg, cache_dir, log, **params)
            info.setdefault("gt_tier", SOURCE_TIER.get(src.split(":")[0], "unknown"))
            if src == "canonical_gpkg" and not info.get("gt_tier"):
                info["gt_tier"] = "frozen"
            valid = info.get("_valid")
            valid = np.ones(len(y), bool) if valid is None else np.asarray(valid, bool)
            info["_valid"] = valid
            yv = y[valid]
            prev = float(yv.mean()) if len(yv) else 0.0
            ok = (yv.sum() >= mn) and (lo <= prev <= hi)
            attempts.append(dict(source=src, gt_tier=info.get("gt_tier"), positives=int(yv.sum()), prevalence=prev,
                                 valid_cells=int(valid.sum()), accepted=bool(ok),
                                 details={k: v for k, v in info.items() if k != "attempts" and not k.startswith("_")}))
            _write_attempts(out_dir, attempts)
            if ok:
                log(city, f"label:{src}", "ok", f"accepted: {int(yv.sum())} positive cells, prevalence {prev:.4%} "
                                                f"of {int(valid.sum()):,} observable cells [ground truth tier "
                                                f"{info.get('gt_tier')}]")
                return y, y_sens, src, dict(info, attempts=attempts)
            log(city, f"label:{src}", "warn", f"rejected by pre-registered checks ({int(yv.sum())} positives, "
                                               f"prevalence {prev:.4%}; need >= {mn} and in [{lo}, {hi}])")
        except Exception as e:  # noqa: BLE001
            attempts.append(dict(source=src, error=str(e)[:300], accepted=False))
            _write_attempts(out_dir, attempts)
            log(city, f"label:{src}", "warn", f"unavailable: {e}")
    brief = "; ".join(f"{a['source']}: " + (a.get("error") or f"{a.get('positives')} positives, prevalence {a.get('prevalence', 0):.2%}")
                      for a in attempts)
    raise RuntimeError(f"no label source passed ({brief}). Details in label_attempts.json")


def _write_attempts(out_dir, attempts):
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        clean = [{k: v for k, v in a.items() if not str(k).startswith("_")} for a in attempts]
        json.dump(clean, open(os.path.join(out_dir, "label_attempts.json"), "w"), indent=2, default=str)


# ======================================================================
# social / emotion sources
# ======================================================================
GKG_COLS = {1: "DATE", 3: "SourceCommonName", 4: "DocumentIdentifier", 8: "V2Themes",
            10: "V2Locations", 15: "V2Tone", 26: "Extras"}


GDELT_TITLE_START = "2019-09-22"      # GKG 2.0 Extras carries <PAGE_TITLE> only from this date (GDELT blog)
_SLUG_JUNK = re.compile(r"^(?:\d+|[0-9a-f]{8,}|index|article|story|news|html?|php|aspx?|amp|www|com|org|net)$", re.I)


def url_slug_text(url):
    """Words from the last two path segments of an article URL ('meyerland-residents-flee' -> text)."""
    try:
        path = urllib.parse.urlparse(str(url)).path
    except Exception:  # noqa: BLE001
        return ""
    segs = [p for p in path.split("/") if p][-2:]
    words = []
    for seg in segs:
        seg = re.sub(r"\.[a-z0-9]{2,5}$", "", seg, flags=re.I)
        words += [w for w in re.split(r"[-_+.,]", seg) if w and not _SLUG_JUNK.match(w)]
    return " ".join(words)


def gkg_location_names(v2loc):
    """Full names from a GDELT V2Locations field ('4#Meyerland, Texas, United States#US#...;...')."""
    if not isinstance(v2loc, str) or not v2loc:
        return ""
    names = []
    for block in v2loc.split(";"):
        parts = block.split("#")
        if len(parts) > 1 and parts[1] and parts[1] not in names:
            names.append(parts[1])
    return ". ".join(names[:25])


def _gkg_to_docs(raw, aliases, log=None, city=""):
    """GDELT GKG rows -> documents. Every document gets URL-slug words + GDELT location names; the page
    title is added when GDELT has one (only from 2019-09-22), so pre-2019 events are not left empty.
    Every filtering step is counted, so an empty result can never be silent."""
    if raw is None or len(raw) == 0:
        if log:
            log(city, "social:gdelt_parse", "warn", "0 raw GKG rows returned by the query")
        return empty_docs()
    alias_re = re.compile("|".join(re.escape(a.lower()) for a in aliases))
    raw = raw.copy()
    if "title" not in raw or raw["title"].isna().all():
        raw["title"] = raw["Extras"].map(ph.extract_title) if "Extras" in raw else None
    n0 = len(raw)
    keep = raw["V2Themes"].fillna("").str.lower().str.contains("flood")
    locs = raw["V2Locations"].fillna("")
    hay = (locs + " " + raw["title"].fillna("") + " " + raw["DocumentIdentifier"].fillna("")).str.lower()
    raw = raw[keep & hay.str.contains(alias_re)]
    n_theme, n_city = int(keep.sum()), len(raw)
    if n_city == 0:
        if log:
            log(city, "social:gdelt_parse", "warn", f"{n0} raw rows, {n_theme} with a flood theme, 0 mentioning "
                                                    f"the city aliases {aliases[:3]}")
        return empty_docs()
    slug = raw["DocumentIdentifier"].map(url_slug_text)
    locn = raw["V2Locations"].map(gkg_location_names)
    title = raw["title"].fillna("").astype(str).str.strip()
    text = [". ".join(p for p in (t, sl, ln) if p) for t, sl, ln in zip(title, slug, locn)]
    tone = pd.to_numeric(raw["V2Tone"].fillna("").str.split(",").str[0], errors="coerce")
    n_title = int((title.str.len() > 0).sum())
    if log:
        log(city, "social:gdelt_parse", "ok",
            f"{n0} raw rows -> {n_theme} flood-themed -> {n_city} mention the city; {n_title} have a page title "
            f"({n_city - n_title} use URL words + GDELT location names; titles exist only from {GDELT_TITLE_START})")
    # v6 syndication key: a wire story republished by many outlets keeps GDELT's location list and tone vector
    # (both computed from the same text), while URL and outlet differ. Copies count once (see collect_documents).
    tone_sig = raw["V2Tone"].fillna("")          # all 7 fields, word count included
    synd = [hashlib.sha1(f"{l}|{t}|{ti.lower()}".encode()).hexdigest()[:16] if l else None
            for l, t, ti in zip(raw["V2Locations"].fillna(""), tone_sig, title)]
    return pd.DataFrame(dict(doc_id=raw["DocumentIdentifier"].to_numpy(), url=raw["DocumentIdentifier"].to_numpy(),
                             time_utc=pd.to_datetime(raw["DATE"].astype("int64").astype(str), format="%Y%m%d%H%M%S",
                                                     utc=True, errors="coerce").to_numpy(),
                             text=text, tone=tone.to_numpy(), synd_key=synd))


def src_gdelt_bigquery(city, cfg, t0, t1, opts, cache_dir, log):
    client = opts.get("bq_client")
    if client is None:
        raise RuntimeError("BigQuery client not available")
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
    rows = []
    for alias in cfg["aliases"][:3]:
        for kw in query_terms(cfg.get("lang", "en")):
            q = f'"{alias}" {kw} after:{(t0 - dt.timedelta(days=1)):%Y-%m-%d} before:{(t1 + dt.timedelta(days=1)):%Y-%m-%d}'
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(dict(q=q, **cfg.get("news_locale", {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"})))
            body = cached_json(cache_dir, url, lambda: http_get(url, timeout=60).text)
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
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
    return pd.DataFrame(rows)


def _arctic_page(endpoint, params, cache_dir):
    url = f"https://arctic-shift.photon-reddit.com/api/{endpoint}"
    key = url + "?" + urllib.parse.urlencode(sorted(params.items()))

    def fetch():
        r = http_get(url, params=params, timeout=90)
        if r.status_code != 200:
            return {"data": [], "error": f"HTTP {r.status_code}"}
        return r.json()
    js = cached_json(cache_dir, key, fetch)
    return js.get("data", js) if isinstance(js, dict) else js


def src_reddit_arcticshift(city, cfg, t0, t1, opts, cache_dir, log):
    """Historical Reddit posts and comments (Arctic Shift archive, keyless)."""
    rows = []
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
                except Exception as e:  # noqa: BLE001
                    log(city, "social:reddit", "warn", f"r/{sub} {endpoint}: {e}")
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
    return df[df["text"].str.contains(FLOOD_RE)] if len(df) else df


def src_youtube(city, cfg, t0, t1, opts, cache_dir, log):
    key = opts.get("youtube_api_key")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY not set (optional source)")
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
            js = cached_json(cache_dir, ck, lambda: http_get("https://www.googleapis.com/youtube/v3/search", params=params).json())
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
