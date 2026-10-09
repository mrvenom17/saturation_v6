def _arcgis_query(layer_url, bbox, cache_dir):
    feats, off = [], 0
    while True:
        params = dict(where="1=1", outFields="*", outSR=4326, f="json", returnGeometry="true",
                      resultOffset=off, resultRecordCount=1000, geometry=",".join(str(v) for v in bbox),
                      geometryType="esriGeometryEnvelope", inSR=4326, spatialRel="esriSpatialRelIntersects")
        js = cached_json(cache_dir, f"arcgis_{layer_url}_{bbox}_{off}",
                         lambda: http_get(layer_url + "/query", params=params, timeout=240, retries=3).json())
        if isinstance(js, dict) and js.get("error"):
            raise RuntimeError(f"{layer_url}: {js['error']}")
        fs = js.get("features", []) if isinstance(js, dict) else []
        feats += fs
        if not fs or not js.get("exceededTransferLimit"):
            return feats
        off += len(fs)


def _date_in_name(name, year):
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", name)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})[/.\-_](\d{1,2})(?:[/.\-_](\d{2,4}))?", name)
    if m:
        yy = int(m.group(3)) if m.group(3) else year
        yy = yy + 2000 if yy < 100 else yy
        try:
            return dt.date(yy, int(m.group(2)), int(m.group(1)))       # dd/mm[/yyyy]
        except ValueError:
            return None
    return None


def fetch_arcgis_featureserver(city, cfg, prereg, cache_dir, log, service_url=None, layer_regex=r"(?i)extent",
                               aoi_layer_regex=r"(?i)area.?of.?interest", window_days=None, **_):
    """Flood extents from an ArcGIS FeatureServer (e.g. CEMS Risk & Recovery EMSN194 for Porto Alegre,
    whose downloads are not published but whose vector layers are served here). Every layer whose name
    matches layer_regex and carries a date inside the event window is unioned (maximum extent)."""
    import geopandas as gpd
    if not service_url:
        raise RuntimeError("no FeatureServer URL configured")
    meta = cached_json(cache_dir, f"arcgis_meta_{service_url}",
                       lambda: http_get(service_url, params=dict(f="json"), timeout=120, retries=3).json())
    layers = (meta.get("layers") or []) if isinstance(meta, dict) else []
    if not layers:
        raise RuntimeError(f"{service_url}: no layers listed ({str(meta)[:160]})")
    t0, t1 = window_bounds(cfg["event_date"], window_days or prereg["label"]["event_window_days"])
    year = dt.date.fromisoformat(cfg["event_date"]).year
    bbox = _bbox_tuple(cfg)
    chosen, skipped = [], []
    for L in layers:
        nm = str(L.get("name", ""))
        if not re.search(layer_regex, nm):
            continue
        d = _date_in_name(nm, year)
        if d is None or not (t0.date() <= d <= t1.date()):
            skipped.append(f"{L.get('id')}:{nm}")
            continue
        chosen.append((L["id"], nm, d))
    log(city, "label:arcgis", "info", f"{len(chosen)} extent layer(s) dated inside {t0.date()}..{t1.date()}: "
                                      f"{[c[1] for c in chosen]}; outside/undated: {skipped[:6]}")
    rows = []
    for lid, nm, d in chosen:
        for f in _arcgis_query(f"{service_url}/{lid}", bbox, cache_dir):
            g = esri_to_shapely(f.get("geometry"))
            if g is not None and not g.is_empty:
                rows.append(dict(geometry=g, _src_layer=nm, feat_date=d.isoformat()))
    if not rows:
        raise RuntimeError("no flood-extent features inside the study area in the dated layers")
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    extra = dict(service=service_url, layers=[c[1] for c in chosen], gt_tier="A_authoritative")
    aoi_ids = [L["id"] for L in layers if re.search(aoi_layer_regex, str(L.get("name", "")))]
    if aoi_ids:
        arows = [esri_to_shapely(f.get("geometry")) for f in _arcgis_query(f"{service_url}/{aoi_ids[0]}", bbox, cache_dir)]
        arows = [a for a in arows if a is not None and not a.is_empty]
        if arows:
            extra["_aoi_gdf"] = gpd.GeoDataFrame(geometry=arows, crs="EPSG:4326")
    log(city, "label:arcgis", "ok", f"{len(gdf)} extent features from {len(chosen)} dated layer(s)")
    return gdf, extra


# ---------------------------------------------------------------- Microsoft AI4G flood dataset (satellite)
AI4G_BASE = "https://huggingface.co/datasets/ai-for-good-lab/ai4g-flood-dataset/resolve/main"
AI4G_REPO = "ai-for-good-lab/ai4g-flood-dataset"
AI4G_CARD_FILTERS = [("dem_metric_2", "<", 10), ("soil_moisture_sca", ">", 1), ("soil_moisture_zscore", ">", 1),
                     ("soil_moisture", ">", 20), ("temp", ">", 0), ("land_cover", "!=", 60),
                     ("edge_false_positives", "==", 0)]


def ai4g_tiles(bounds):
    """3-degree tiles named by their lower-left corner, e.g. Chennai (80.27E, 13.08N) -> N12/N12E078."""
    out = set()
    for lon in (bounds["min_lon"], bounds["max_lon"]):
        for lat in (bounds["min_lat"], bounds["max_lat"]):
            la, lo = int(np.floor(lat / 3.0) * 3), int(np.floor(lon / 3.0) * 3)
            ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
            ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
            out.add((ns, f"{ns}{ew}"))
    return sorted(out)


def _ai4g_file(folder, tile, suffix, cache_dir, log, city):
    rel = f"{folder}/{tile}/{tile}-{suffix}"
    path = os.path.join(cache_dir, "ai4g", rel)
    try:
        return download_file(f"{AI4G_BASE}/{rel}", path, log, city, timeout=1800)
    except Exception as e:  # noqa: BLE001
        try:
            from huggingface_hub import hf_hub_download
            return hf_hub_download(AI4G_REPO, rel, repo_type="dataset", local_dir=os.path.join(cache_dir, "ai4g"))
        except Exception as e2:  # noqa: BLE001
            raise RuntimeError(f"AI4G {rel}: {str(e)[:100]} / huggingface_hub: {str(e2)[:100]}")


def label_ai4g_sar(city, cfg, G, df, prereg, cache_dir, log, cell_fraction=None, pixel_m=None, card_filters=None,
                   use_exclusion=True, **_):
    """Microsoft AI for Good global flood dataset (Misra et al. 2025, Nat Commun; Sentinel-1, Oct 2014 -
    Sep 2024; MIT per the dataset card). Detections inside the event window are counted per cell; a
    cell is flooded when detections cover >= cell_fraction of it. SAR-derived: tier C, and the SAR
    rung is removed from the ladder to avoid circularity."""
    import pyarrow.parquet as pq
    p = prereg.get("label_ai4g") or prereg["label"].get("ai4g", {})
    cell_fraction = cell_fraction or p.get("cell_fraction", 0.25)
    pixel_m = pixel_m or p.get("pixel_m", 20.0)
    card_filters = p.get("card_filters", True) if card_filters is None else card_filters
    ev = dt.date.fromisoformat(cfg["event_date"])
    if ev > dt.date(2024, 9, 30) or ev < dt.date(2014, 10, 1):
        raise RuntimeError("AI4G covers Oct 2014 - Sep 2024 only")
    t0, t1 = window_bounds(cfg["event_date"], prereg["label"]["event_window_days"])
    b = cfg["bounds"]
    parts = []
    for folder, tile in ai4g_tiles(b):
        path = _ai4g_file(folder, tile, "post-processing.parquet", cache_dir, log, city)
        years = sorted({t0.year, t1.year})
        tab = pq.read_table(path, filters=[("lat", ">=", b["min_lat"]), ("lat", "<=", b["max_lat"]),
                                           ("lon", ">=", b["min_lon"]), ("lon", "<=", b["max_lon"]),
                                           ("year", "in", years)])
        parts.append(tab.to_pandas())
    d = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(d) == 0:
        raise RuntimeError("AI4G has no detections inside the study area in the event years")
    when = pd.to_datetime(dict(year=d["year"], month=d["month"], day=d["day"]), errors="coerce")
    d = d[(when >= t0) & (when <= t1)]
    n_win = len(d)
    if card_filters:
        for col, op, v in AI4G_CARD_FILTERS:
            if col in d:
                x = pd.to_numeric(d[col], errors="coerce")
                d = d[{"<": x < v, ">": x > v, "!=": x != v, "==": x == v}[op]]
    if len(d) == 0:
        raise RuntimeError(f"AI4G: {n_win} detections in {t0.date()}..{t1.date()}, none after the dataset-card filters")
    d = d.assign(_k=d["lat"].round(5).astype(str) + "_" + d["lon"].round(5).astype(str)).drop_duplicates("_k")
    from pyproj import Transformer
    x, y_ = Transformer.from_crs("EPSG:4326", G.crs, always_xy=True).transform(d["lon"].to_numpy(), d["lat"].to_numpy())
    r, c, ok = G.rowcol(x, y_)
    counts = np.zeros((G.nr, G.nc), dtype=np.int32)
    np.add.at(counts, (r[ok], c[ok]), 1)
    cnt = ph.raster_to_cells(counts, df)
    need = int(np.ceil(cell_fraction * (G.res / pixel_m) ** 2))
    y = (cnt >= need).astype(int)
    info = dict(source="ai4g_sar", detections_in_window=int(n_win), detections_used=int(len(d)),
                min_detections_per_cell=need, pixel_m=pixel_m, cell_fraction=cell_fraction,
                tiles=[t for _, t in ai4g_tiles(b)], positive_cells=int(y.sum()), gt_tier="C_satellite")
    if use_exclusion:
        try:
            ex = np.zeros(len(df), bool)
            for folder, tile in ai4g_tiles(b):
                tif = _ai4g_file(folder, tile, "80m-buffer.tif", cache_dir, log, city)
                v = ph.raster_to_cells(raster_on_grid(tif, G), df)
                ex |= np.nan_to_num(v, nan=0) == 1
            valid = ~ex
            info.update(_valid=valid, valid_cells=int(valid.sum()))
            log(city, "label:ai4g_sar", "info", f"{ex.mean():.1%} of cells in the AI4G exclusion layer -> unknown, not dry")
        except Exception as e:  # noqa: BLE001
            log(city, "label:ai4g_sar", "warn", f"exclusion layer unavailable ({str(e)[:100]}); all cells treated as observable")
    log(city, "label:ai4g_sar", "info", f"{n_win} detections in {t0.date()}..{t1.date()}, {len(d)} after the card "
                                        f"filters; >= {need} per {G.res:.0f} m cell = flooded -> {int(y.sum())} cells")
    return y, None, info


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
