def _walk_urls(obj, want=".zip"):
    """Collect every string in a nested JSON structure that looks like a product URL."""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += _walk_urls(v, want)
    elif isinstance(obj, list):
        for v in obj:
            out += _walk_urls(v, want)
    elif isinstance(obj, str) and obj.lower().endswith(want):
        out.append(obj)
    return out


class WrongEventError(RuntimeError):
    """The product exists but depicts a different flood (image date outside the event window)."""


def _ems_products(js):
    """Structured product list from the Rapid Mapping dashboard API: one dict per product with its
    AOI, type (DEL/GRA/...), download URL and every image acquisition time found inside it."""
    out = []
    results = js.get("results") if isinstance(js, dict) else None
    acts = results if isinstance(results, list) else ([js] if isinstance(js, dict) else [])
    for act in acts:
        for aoi in (act.get("aois") or []):
            for p in (aoi.get("products") or []):
                url = p.get("downloadPath") or next(iter(_walk_urls(p)), None)
                if not url:
                    continue
                times = []

                def _walk(o):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if "acquisition" in str(k).lower() and isinstance(v, str):
                                times.append(v)
                            else:
                                _walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            _walk(v)
                _walk(p)
                out.append(dict(url=url, aoi=str(aoi.get("number", "")), aoi_name=aoi.get("name", ""),
                                type=str(p.get("type", "")), times=sorted(times)))
    return out


def fetch_copernicus_ems(city, cfg, prereg, cache_dir, log, code=None, product_regex=r"(?i)(del|vector)",
                         layer_regex=r"(?i)(observed.?event|maximum.?flood.?extent|flooded.?area|flood.?extent|flood.?trace)",
                         aoi_regex=None, product_urls=(), max_products=60, date_filter=False,
                         product_types=("DEL",), image_window_days=None):
    """Copernicus EMS Rapid Mapping delineation/grading vectors for one activation (e.g. EMSR773).
    Product URLs are read from the public activation API; they are not hard-coded."""
    if not code and not product_urls:
        raise RuntimeError("no EMS activation code configured")
    urls = list(product_urls)
    api_err = []
    for host in EMS_API_HOSTS if not urls else []:
        api = f"{host}/backend/dashboard-api/public-activations/?code={code}"
        try:
            r = http_get(api, timeout=120, retries=2)
            if r.status_code != 200:
                api_err.append(f"{host}: HTTP {r.status_code}")
                continue
            js = r.json()
            prods = _ems_products(js)
            if prods:
                # EVENT-SPECIFICITY GUARD: keep only products whose satellite image was acquired inside the
                # event window. An activation can span several flood waves (EMSR659 is early May 2023 only).
                win = image_window_days or prereg["label"]["event_window_days"]
                t0, t1 = window_bounds(cfg["event_date"], win)
                kept, dropped = [], []
                for pr in prods:
                    if product_types and pr["type"] and pr["type"].upper() not in {t.upper() for t in product_types}:
                        continue
                    ts = [pd.to_datetime(t, utc=True, errors="coerce") for t in pr["times"]]
                    ts = [t.tz_localize(None) for t in ts if not pd.isna(t)]
                    if ts and not any(t0 <= t <= t1 for t in ts):
                        dropped.append(f"AOI{pr['aoi']} {pr['type']} ({min(ts).date()}..{max(ts).date()})")
                        continue
                    kept.append(pr)
                if dropped:
                    log(city, "label:copernicus_ems", "info", f"{len(dropped)} product(s) imaged outside the event "
                                                              f"window {t0.date()}..{t1.date()} dropped: {dropped[:6]}")
                if prods and not kept:
                    raise WrongEventError(f"activation {code}: every product was imaged outside the event window "
                                       f"{t0.date()}..{t1.date()} — this activation maps a different flood wave")
                found = [p["url"] for p in kept]
                img_times = sorted({t[:10] for p in kept for t in p["times"]})
                log(city, "label:copernicus_ems", "ok", f"{len(found)} product(s) of type {list(product_types)} "
                                                        f"imaged {img_times[:1]}..{img_times[-1:]} listed by {host}")
            else:
                found = _walk_urls(js)
            urls = [u if u.startswith("http") else urllib.parse.urljoin(host + "/", u.lstrip("/")) for u in found]
            if urls:
                if not prods:
                    log(city, "label:copernicus_ems", "ok", f"{len(urls)} product archives listed by {host}")
                break
        except WrongEventError:
            raise
        except Exception as e:  # noqa: BLE001
            api_err.append(f"{host}: {str(e)[:160]}")
    if not urls:
        raise RuntimeError(f"activation {code}: no product archives found ({'; '.join(api_err) or 'empty API response'}). "
                           "Put verified zip URLs in label_params['copernicus_ems']['product_urls'] to bypass the API.")
    if aoi_regex:
        urls = [u for u in urls if re.search(aoi_regex, u, re.I)] or urls
    keep = ([u for u in urls if re.search(product_regex, os.path.basename(u), re.I)] or urls) if product_regex else urls
    # group by area of interest; within an AOI read the delineation product first, then monitoring steps
    groups = {}
    for u in keep:
        m = re.search(r"AOI(\d+)", os.path.basename(u), re.I)
        groups.setdefault(m.group(1) if m else "?", []).append(u)

    def _order(u):
        b = os.path.basename(u).upper()
        v = re.search(r"_V(\d+)", b)
        return (0 if "PRODUCT" in b else 1, b, -(int(v.group(1)) if v else 0))
    frames, aoi_frames, used, skipped_aoi = [], [], [], []
    n_dl = 0
    for aoi, members in sorted(groups.items()):
        members = sorted(members, key=_order)
        for i, u in enumerate(members):
            if n_dl >= max_products:
                break
            try:
                p = download_file(u, os.path.join(cache_dir, "ems", code or city, os.path.basename(u)), log, city)
                n_dl += 1
                g = read_vector_archive(p, _bbox_tuple(cfg), layer_regex, log, city, strict=True)
                try:
                    a = read_vector_archive(p, _bbox_tuple(cfg), r"(?i)area.?of.?interest", None, city, strict=True)
                except RuntimeError:          # no AOI layer in this archive: no mask from it (never guess one)
                    a = g.iloc[0:0]
                a = a[a.geometry.geom_type.isin(["Polygon", "MultiPolygon"])] if len(a) else a
            except Exception as e:  # noqa: BLE001
                log(city, "label:copernicus_ems", "info", f"skipped {os.path.basename(u)}: {str(e)[:120]}")
                continue
            if i == 0 and len(g) == 0 and len(a) == 0:
                skipped_aoi.append(aoi)     # this area of interest does not reach the city: skip its other archives
                break
            used.append(os.path.basename(u))
            if len(g):
                frames.append(g)
            if len(a):
                aoi_frames.append(a)
    if skipped_aoi:
        log(city, "label:copernicus_ems", "info", f"areas of interest outside the study area, not downloaded further: "
                                                  f"{', '.join('AOI' + x for x in skipped_aoi)}")
    frames = [f for f in frames if len(f)]
    if not frames:
        raise RuntimeError(f"activation {code}: {len(used)} archive(s) read, none with flood polygons inside the study "
                           "area. If the activation maps a different part of the region, set bounds_from_label=True "
                           "in the registry so the grid is placed on the label instead.")
    import geopandas as gpd
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if len(gdf) == 0:
        raise RuntimeError(f"activation {code}: archives held features but no polygons inside the study area")
    extra = dict(activation=code, archives=used, n_archives_listed=len(urls),
                 layers=sorted(set(gdf["_src_layer"]))[:12])
    if aoi_frames:
        extra["_aoi_gdf"] = gpd.GeoDataFrame(pd.concat(aoi_frames, ignore_index=True), geometry="geometry",
                                             crs="EPSG:4326")
    if date_filter:
        gdf, dinfo = filter_by_event_date(gdf, cfg["event_date"], prereg["label"]["event_window_days"], log, city)
        extra["date_filter"] = dinfo
    return gdf, extra


def label_copernicus_ems(city, cfg, G, df, prereg, cache_dir, log, **kw):
    gdf, extra = fetch_copernicus_ems(city, cfg, prereg, cache_dir, log, **kw)
    aoi = extra.pop("_aoi_gdf", None)
    y, ys, info = _rasterise(city, G, df, gdf, prereg, log, source="copernicus_ems", extra=extra)
    if aoi is not None and len(aoi):
        inside, _ = ph.label_cells_from_geometries(df, G, aoi.to_crs(G.crs))
        valid = inside.astype(bool)
        info.update(_valid=valid, valid_cells=int(valid.sum()))
        log(city, "label:copernicus_ems", "info", f"{valid.mean():.1%} of cells lie inside a mapped area of interest; "
                                                  f"{(~valid).sum():,} outside are excluded as unmapped, not dry")
    else:
        log(city, "label:copernicus_ems", "warn", "no area-of-interest layer found: every cell treated as mapped")
    return y, ys, info


RASTER_EXT = (".tif", ".tiff", ".img", ".vrt", ".asc")


def _sb_get(url, params):
    r = http_get(url, params=params, timeout=120, retries=3)
    return r.json() if r.status_code == 200 else {}


def _sb_files(doc):
    out = [f for f in (doc.get("files") or []) if isinstance(f, dict) and f.get("url")]
    for fac in doc.get("facets") or []:
        out += [f for f in (fac.get("files") or []) if isinstance(f, dict) and f.get("url")]
    return out


def _sb_walk(item_id, depth=0, max_depth=3):
    js = _sb_get("https://www.sciencebase.gov/catalog/items",
                 dict(parentId=item_id, format="json", fields="title,spatial,files,hasChildren", max=250))
    out = []
    for it in js.get("items", []) or []:
        out.append(it)
        if it.get("hasChildren") and depth < max_depth:
            out += _sb_walk(it.get("id"), depth + 1, max_depth)
    return out


def _bbox_hit(bb, b):
    try:
        return not (bb["maxX"] < b["min_lon"] or bb["minX"] > b["max_lon"] or
                    bb["maxY"] < b["min_lat"] or bb["minY"] > b["max_lat"])
    except Exception:  # noqa: BLE001
        return False


def _zip_rasters(path):
    if path.lower().endswith(RASTER_EXT):
        return [path]
    if not path.lower().endswith(".zip"):
        return []
    with zipfile.ZipFile(path) as z:
        return [f"/vsizip/{path}/{n}" for n in z.namelist() if n.lower().endswith(RASTER_EXT) and "__MACOSX" not in n]


def raster_bounds_4326(path):
    import rasterio
    from rasterio.warp import transform_bounds
    with rasterio.open(path) as src:
        return transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)


SHP_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".shp.xml")


def _layer_role(name, flood_regex, coverage_regex, ignore_regex):
    """Classify a layer/file name: 'coverage' (the mapped-area boundary), 'ignore' (e.g. HWM points in
    a polygon release) or 'flood'. A boundary polygon must never be rasterised as flooded."""
    n = os.path.basename(str(name))
    if coverage_regex and re.search(coverage_regex, n):
        return "coverage"
    if ignore_regex and re.search(ignore_regex, n):
        return "ignore"
    if flood_regex and not re.search(flood_regex, n):
        return "ignore"
    return "flood"


def fetch_usgs_sciencebase(city, cfg, prereg, cache_dir, log, item_id=None, file_regex=r"(?i)\.zip$",
                           layer_regex=None, point_buffer_m=0.0, date_filter=False, max_files=40,
                           depth_min_m=0.0, file_exclude_regex=None, flood_regex=None,
                           coverage_regex=r"(?i)(^|[_\W])(bnd|bound|boundary|study.?area|mapped.?area)",
                           ignore_regex=r"(?i)(hwm|high.?water)", raster_coverage=False, coverage_hwm=None):
    """USGS data release on ScienceBase. Child items are chosen by their own bounding boxes, so a
    basin-scale release contributes only the products that actually reach the study area. Reads
    vector products (inundation polygons, high-water marks) and depth rasters."""
    if not item_id:
        raise RuntimeError("no ScienceBase item configured")
    b = cfg["bounds"]
    root = _sb_get(f"https://www.sciencebase.gov/catalog/item/{item_id}",
                   dict(format="json", fields="files,title,spatial,hasChildren"))
    if not root:
        raise RuntimeError(f"ScienceBase item {item_id} unavailable")
    items = [root] + _sb_walk(item_id)
    with_bb = [it for it in items if (it.get("spatial") or {}).get("boundingBox")]
    hit = [it for it in with_bb if _bbox_hit(it["spatial"]["boundingBox"], b)]
    no_bb = [it for it in items if not (it.get("spatial") or {}).get("boundingBox")]
    # items without a bounding box (often the parent) cannot be ruled out, so they are kept; every file
    # is still read with the study-area filter, and items that do intersect are read first
    chosen = hit + no_bb
    log(city, "label:usgs_sciencebase", "info",
        f"{len(items)} items in the release; {len(with_bb)} carry a bounding box, {len(hit)} intersect the study "
        f"area; {len(no_bb)} without a bounding box are also searched")
    files, seen = [], set()
    for it in chosen:
        item_files = _sb_files(it)
        # a shapefile listed as separate parts is useless unless every part comes along
        stems = {os.path.splitext(f.get("name", ""))[0].lower().replace(".shp", "")
                 for f in item_files if re.search(file_regex, f.get("name", ""))}
        for f in item_files:
            nm = f.get("name", "")
            stem = os.path.splitext(nm)[0].lower().replace(".shp", "")
            part = nm.lower().endswith(SHP_PARTS) and stem in stems
            if not (re.search(file_regex, nm) or part) or f["url"] in seen:
                continue
            if file_exclude_regex and re.search(file_exclude_regex, nm):
                continue
            seen.add(f["url"])
            files.append(dict(f, _item=it.get("title", ""), _item_id=it.get("id", item_id)))
    # polygons and boundaries first, depth rasters after
    files.sort(key=lambda f: (0 if re.search(r"(?i)(bound|extent|inund|poly|shp)", f["name"]) else 1, f["name"]))
    if not files:
        raise RuntimeError(f"release {item_id}: no file matching {file_regex} in the {len(chosen)} item(s) that "
                           f"reach the study area")
    if len(files) > max_files:
        log(city, "label:usgs_sciencebase", "warn", f"{len(files)} matching files; reading the first {max_files}")
        files = files[:max_files]
    import geopandas as gpd
    frames, cover, rasters, read, roles = [], [], [], [], {}
    paths = []
    for f in files:          # download everything first so shapefile parts sit together
        try:
            p = download_file(f["url"], os.path.join(cache_dir, "usgs", f.get("_item_id") or item_id, f["name"]),
                              log, city)
            paths.append((f, p))
        except Exception as e:  # noqa: BLE001
            log(city, "label:usgs_sciencebase", "info", f"skipped {f['name']}: {str(e)[:120]}")
    for f, p in paths:
        if p.lower().endswith(SHP_PARTS) and not p.lower().endswith(".shp"):
            continue          # read through its .shp
        g = None
        try:
            g = read_vector_archive(p, _bbox_tuple(cfg), layer_regex, log, city)
        except RuntimeError:
            g = None
        if g is not None and len(g):
            g["_role"] = [_layer_role(f"{f['name']}:{lyr}", flood_regex, coverage_regex, ignore_regex)
                          for lyr in g["_src_layer"]]
            for role, part in g.groupby("_role"):
                roles[role] = roles.get(role, 0) + len(part)
                if role == "flood":
                    frames.append(part.drop(columns="_role"))
                elif role == "coverage":
                    cover.append(part.drop(columns="_role"))
            read.append(f["name"])
            continue
        for rp in _zip_rasters(p):
            try:
                rb = raster_bounds_4326(rp)
            except Exception as e:  # noqa: BLE001
                log(city, "label:usgs_sciencebase", "info", f"raster {os.path.basename(rp)} unreadable: {str(e)[:100]}")
                continue
            if _bbox_hit(dict(minX=rb[0], minY=rb[1], maxX=rb[2], maxY=rb[3]), b):
                rasters.append(dict(path=rp, bounds=rb))
                read.append(f["name"])
    gdf = (gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
           if frames else gpd.GeoDataFrame({"_src_layer": pd.Series(dtype="object")}, geometry=[], crs="EPSG:4326"))
    if roles:
        log(city, "label:usgs_sciencebase", "info", "features by role: " + ", ".join(f"{k}={v}" for k, v in sorted(roles.items()))
            + " (coverage = mapped-area boundary, used as the valid mask; ignore = e.g. HWM points)")
    if len(gdf) == 0 and not rasters:
        raise RuntimeError(f"release {item_id}: {len(files)} file(s) read, none with features or depth rasters "
                           f"inside the study area (examples: {[f['name'] for f in files[:5]]})")
    extra = dict(item=item_id, title=root.get("title"), files_used=read[:20], n_rasters=len(rasters),
                 depth_min_m=depth_min_m, _rasters=rasters, raster_coverage=bool(raster_coverage))
    if cover:
        cg = gpd.GeoDataFrame(pd.concat(cover, ignore_index=True), geometry="geometry", crs="EPSG:4326")
        cg = cg[cg.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
        if len(cg):
            extra["_aoi_gdf"] = cg
    if coverage_hwm and "_aoi_gdf" not in extra:
        # products documented as mapped only near surveyed high-water marks (e.g. USGS Ida NYC depth grids:
        # "within 250 m of the HWM locations"): the valid area is that buffer, NOT the raster's data footprint,
        # because depth grids store dry cells as NoData
        try:
            hw, _ = fetch_usgs_stn(city, cfg, prereg, cache_dir, log, point_buffer_m=0.0,
                                   **{k: v for k, v in coverage_hwm.items() if k != "buffer_m"})
            buf = float(coverage_hwm.get("buffer_m", 250.0))
            metric = ph.utm_epsg((b["min_lon"] + b["max_lon"]) / 2, (b["min_lat"] + b["max_lat"]) / 2)
            ring = gpd.GeoDataFrame(geometry=hw.to_crs(metric).buffer(buf), crs=metric).to_crs("EPSG:4326")
            extra["_aoi_gdf"] = ring
            extra["coverage"] = f"{buf:.0f} m around {len(hw)} surveyed HWM sites (STN event {coverage_hwm.get('event_id')})"
            log(city, "label:usgs_sciencebase", "info", f"valid area = {extra['coverage']}")
        except Exception as e:  # noqa: BLE001
            log(city, "label:usgs_sciencebase", "warn", f"HWM coverage unavailable ({str(e)[:120]}); the depth "
                                                        f"rasters alone cannot say where it was dry")
    if date_filter and len(gdf):
        gdf, dinfo = filter_by_event_date(gdf, cfg["event_date"], prereg["label"]["event_window_days"], log, city)
        extra["date_filter"] = dinfo
    if len(gdf) and gdf.geometry.geom_type.isin(["Point", "MultiPoint"]).all() and point_buffer_m <= 0:
        log(city, "label:usgs_sciencebase", "warn",
            "this release is point data (e.g. high-water marks): set point_buffer_m to turn it into an extent, "
            "and report it as a sparse label")
    extra["point_buffer_m"] = point_buffer_m
    log(city, "label:usgs_sciencebase", "ok", f"{len(gdf)} vector features and {len(rasters)} depth raster(s) "
                                              f"inside the study area")
    return gdf, extra


def raster_on_grid(path, G):
    """Sample a raster at every grid-cell centre (nearest neighbour), matching the polygon rule
    'cell centre inside the flooded area'. Only the part overlapping the grid is read."""
    import rasterio
    from affine import Affine
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    with rasterio.open(path) as src:
        with WarpedVRT(src, crs=G.crs, transform=Affine(G.res, 0, G.x0, 0, -G.res, G.y1), width=G.nc, height=G.nr,
                       resampling=Resampling.nearest) as vrt:
            arr = vrt.read(1, masked=True)
    return np.asarray(arr.filled(np.nan), dtype=float)


def label_usgs_sciencebase(city, cfg, G, df, prereg, cache_dir, log, **kw):
    gdf, extra = fetch_usgs_sciencebase(city, cfg, prereg, cache_dir, log, **kw)
    rasters = extra.pop("_rasters", [])
    aoi = extra.pop("_aoi_gdf", None)
    covered = np.zeros(len(df), bool)
    if len(gdf):
        y, ys, info = _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=extra.get("point_buffer_m", 0.0),
                                 source="usgs_sciencebase", extra=extra)
    else:
        y, ys = np.zeros(len(df), dtype=int), None
        info = dict(source="usgs_sciencebase", features=0, **{k: v for k, v in extra.items() if not k.startswith("_")})
    n_r = 0
    for r in rasters:
        try:
            vals = ph.raster_to_cells(raster_on_grid(r["path"], G), df)
        except Exception as e:  # noqa: BLE001
            log(city, "label:usgs_sciencebase", "warn", f"depth raster {os.path.basename(r['path'])}: {str(e)[:120]}")
            continue
        wet = np.nan_to_num(vals, nan=-1.0) > extra.get("depth_min_m", 0.0)
        y = np.maximum(y, wet.astype(int))
        covered |= np.isfinite(vals)
        n_r += 1
    if rasters:
        log(city, "label:usgs_sciencebase", "info", f"{n_r}/{len(rasters)} depth raster(s) sampled at cell centres "
                                                    f"(depth > {extra.get('depth_min_m', 0.0)} m = flooded)")
    info.update(positive_cells=int(y.sum()), prevalence=float(y.mean()), rasters_used=n_r)
    if aoi is not None and len(aoi):
        _apply_coverage(info, df, G, aoi, log, city, "usgs_sciencebase", "inside the USGS mapped-area boundary")
    elif extra.get("raster_coverage") and n_r:
        info.update(_valid=covered, valid_cells=int(covered.sum()))
        log(city, "label:usgs_sciencebase", "info", f"{covered.mean():.1%} of cells lie inside the depth-raster "
                                                    f"footprint; {(~covered).sum():,} outside are unmapped, not dry")
        if covered.sum() and y[covered].mean() > 0.95:
            log(city, "label:usgs_sciencebase", "warn", "the raster footprint is (almost) all wet: this raster stores "
                                                        "dry cells as NoData, so its footprint is not a coverage mask")
    return y, ys, info


def _apply_coverage(info, df, G, cover_gdf, log, city, source, what="inside the mapped area"):
    """Cells outside the product's mapped area are UNKNOWN, not dry: mark them invalid."""
    inside, _ = ph.label_cells_from_geometries(df, G, cover_gdf.to_crs(G.crs))
    valid = inside.astype(bool)
    info.update(_valid=valid, valid_cells=int(valid.sum()), coverage_fraction=round(float(valid.mean()), 4),
                coverage_polygons=int(len(cover_gdf)))
    log(city, f"label:{source}", "info", f"{valid.mean():.1%} of cells lie {what}; "
                                         f"{(~valid).sum():,} outside are excluded as unmapped, not dry")
    return valid


def fetch_portal_download(city, cfg, prereg, cache_dir, log, page_url=None, href_regex=r"(?i)\.(gpkg|geojson|shp)\.zip$",
                          prefer=("gpkg", "geojson", "shp"), layer_regex=None, date_filter=True, point_buffer_m=0.0,
                          direct_url=None):
    """Generic open-data portal source: find the download link on the dataset page (no hard-coded file path),
    read it with a bbox filter, then keep only features dated inside the event window."""
    url = direct_url
    if not url:
        if not page_url:
            raise RuntimeError("neither direct_url nor page_url configured")
        r = http_get(page_url, timeout=120, retries=3)
        if r.status_code != 200:
            raise RuntimeError(f"dataset page HTTP {r.status_code}")
        hrefs = re.findall(r'href=[\'"]([^\'"]+)[\'"]', r.text)
        hrefs = [urllib.parse.urljoin(page_url, h) for h in hrefs if re.search(href_regex, h)]
        if not hrefs:
            raise RuntimeError(f"no link matching {href_regex} on {page_url}")
        for ext in prefer:
            pick = [h for h in hrefs if f".{ext}." in h.lower()]
            if pick:
                url = pick[0]
                break
        url = url or hrefs[0]
    p = download_file(url, os.path.join(cache_dir, "portal", city + "_" + os.path.basename(urllib.parse.urlparse(url).path)), log, city)
    gdf = read_vector_archive(p, _bbox_tuple(cfg), layer_regex, log, city)
    extra = dict(download_url=url, features_in_bbox=int(len(gdf)))
    if date_filter:
        gdf, dinfo = filter_by_event_date(gdf, cfg["event_date"], prereg["label"]["event_window_days"], log, city)
        extra["date_filter"] = dinfo
    extra["point_buffer_m"] = point_buffer_m
    return gdf, extra


def label_portal_download(city, cfg, G, df, prereg, cache_dir, log, **kw):
    gdf, extra = fetch_portal_download(city, cfg, prereg, cache_dir, log, **kw)
    return _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=extra.get("point_buffer_m", 0.0),
                      source="portal_download", extra=extra)


def probe_label_bounds(city, cfg, prereg, cache_dir, log, source=None, pad_km=3.0):
    """Download the first vector label source WITHOUT a bbox filter and return its extent.
    Used by bounds_from_label so the grid is placed where the ground truth actually is."""
    import geopandas as gpd
    cands = [source] if source else [s for s in cfg["label_chain"] if s.split(":")[0] in VECTOR_LABEL_SOURCES]
    if not cands:
        raise RuntimeError("no vector label source in the chain to probe")
    region = cfg.get("label_search_bounds") or dict(min_lon=-180, min_lat=-90, max_lon=180, max_lat=90)
    open_cfg = dict(cfg, bounds=region)
    errs, gdf, extra, src = [], None, None, None
    for src in cands:           # the frozen file first (offline), then the live sources in chain order
        try:
            params = dict((cfg.get("label_params") or {}).get(src, {}))
            gdf, extra = VECTOR_LABEL_SOURCES[src.split(":")[0]](city, open_cfg, prereg, cache_dir, log, **params)
            if len(gdf) or extra.get("_rasters"):
                break
        except Exception as e:  # noqa: BLE001
            errs.append(f"{src}: {str(e)[:120]}")
    if gdf is None:
        raise RuntimeError("; ".join(errs) or "no source could be probed")
    boxes = [tuple(gdf.total_bounds)] if len(gdf) else []
    boxes += [tuple(r["bounds"]) for r in extra.get("_rasters", [])]
    if not boxes:
        raise RuntimeError(f"{src} returned no features or rasters inside the search region to probe")
    minx, miny = min(b[0] for b in boxes), min(b[1] for b in boxes)
    maxx, maxy = max(b[2] for b in boxes), max(b[3] for b in boxes)
    minx, miny = max(minx, region["min_lon"]), max(miny, region["min_lat"])
    maxx, maxy = min(maxx, region["max_lon"]), min(maxy, region["max_lat"])
    dlat = pad_km / 111.0
    dlon = pad_km / (111.0 * max(np.cos(np.radians((miny + maxy) / 2)), 0.1))
    b = dict(min_lon=float(minx - dlon), min_lat=float(miny - dlat),
             max_lon=float(maxx + dlon), max_lat=float(maxy + dlat))
    log(city, "label:probe", "ok", f"{src}: {len(gdf)} features spanning "
                                   f"{(maxx-minx)*111*np.cos(np.radians((miny+maxy)/2)):.0f} x {(maxy-miny)*111:.0f} km "
                                   f"-> bounds {json.dumps({k: round(v, 3) for k, v in b.items()})}")
    return b, dict(source=src, features=int(len(gdf)),
                   **{k: v for k, v in (extra or {}).items() if k != "layers" and not k.startswith("_")})


def fetch_petabencana_reports(city, cfg, prereg, cache_dir, log, admin=None, min_state=2, point_buffer_m=150.0,
                              window_days=None, **_):
    """PetaBencana crowdsourced flood reports (points, CC BY-NC 4.0) from the documented reports archive
    https://data.petabencana.id/reports/archive (GeoJSON, no key). The flooded-AREA archive returns only
    area ids and states without geometry, so it cannot be rasterised on its own. Requested in <= 7-day
    slices. Depth in cm comes from report_data.flood_depth when present."""
    import geopandas as gpd
    from shapely.geometry import shape
    win = window_days or prereg["label"].get("report_window_days", [-1, 3])
    t0, t1 = window_bounds(cfg["event_date"], win)
    feats, s0 = [], t0
    while s0 < t1:
        e = min(s0 + dt.timedelta(days=6, hours=23), t1)
        params = dict(start=s0.strftime("%Y-%m-%dT%H:%M:%S+0000"), end=e.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                      geoformat="geojson")
        key = f"petabencana_reports_{params['start']}_{params['end']}"
        try:
            js = cached_json(cache_dir, key, lambda: http_get("https://data.petabencana.id/reports/archive",
                                                              params=params, timeout=180, retries=3).json())
        except Exception as ex:  # noqa: BLE001
            log(city, "label:petabencana", "warn", f"reports archive {params['start'][:10]}: {str(ex)[:120]}")
            js = {}
        res = js.get("result") if isinstance(js, dict) else None
        feats += (res or {}).get("features", []) if isinstance(res, dict) else []
        s0 = e + dt.timedelta(seconds=1)
    rows = []
    for f in feats:
        p = f.get("properties") or {}
        if p.get("disaster_type") not in (None, "flood"):
            continue
        rd = p.get("report_data") or {}
        depth = rd.get("flood_depth") if isinstance(rd, dict) else None
        if f.get("geometry"):
            rows.append(dict(geometry=shape(f["geometry"]), pkey=p.get("pkey"), created_at=p.get("created_at"),
                             source_app=p.get("source"), depth_cm=depth))
    if not rows:
        raise RuntimeError(f"PetaBencana reports archive returned no flood reports for {t0.date()}..{t1.date()}")
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    b = cfg["bounds"]
    gdf = gdf.cx[b["min_lon"]:b["max_lon"], b["min_lat"]:b["max_lat"]]
    gdf["depth_m"] = pd.to_numeric(gdf["depth_cm"], errors="coerce") / 100.0
    log(city, "label:petabencana", "ok", f"{len(feats)} reports in {t0.date()}..{t1.date()}, {len(gdf)} flood reports "
                                         f"inside the study area (buffered {point_buffer_m:.0f} m)")
    return gdf, dict(endpoint="reports/archive", window=[str(t0), str(t1)], point_buffer_m=point_buffer_m,
                     gt_tier="B_crowdsourced")


def label_petabencana_area(city, cfg, G, df, prereg, cache_dir, log, **kw):
    gdf, extra = fetch_petabencana_reports(city, cfg, prereg, cache_dir, log, **kw)
    return _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=extra["point_buffer_m"],
                      source="petabencana_reports", extra=extra)


# ---------------------------------------------------------------- exact-URL vector files (verified)
def _safe_name(url):
    p = urllib.parse.urlparse(url)
    base = os.path.basename(p.path) or "download"
    q = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{q}_{base}"


def _apply_where(g, where):
    """Attribute filter: {column: value or [values]}; values compared as strings, case-insensitive."""
    keep = np.ones(len(g), bool)
    for col, val in (where or {}).items():
        if col not in g:
            raise RuntimeError(f"filter column '{col}' not in file (columns: {list(g.columns)[:12]})")
        vals = {str(v).lower() for v in (val if isinstance(val, (list, tuple, set)) else [val])}
        keep &= g[col].astype(str).str.lower().isin(vals).to_numpy()
    return g[keep]


def fetch_file_url(city, cfg, prereg, cache_dir, log, files=(), coverage_files=(), point_buffer_m=0.0,
                   date_filter=False, gt_tier="A_authoritative", **_):
    """Ground truth from exact, verified file URLs. Each entry of `files` is
    dict(url=..., name=<local file name incl. extension>, where={col: values}, layer_regex=None).
    Handles GeoJSON (incl. OGC API single-feature responses), KML, zipped shapefiles/GeoPackages.
    `coverage_files` (same form) give the mapped-area footprint used as the valid mask."""
    import geopandas as gpd

    def _read(entries, role):
        out, used = [], []
        for f in entries:
            name = f.get("name") or _safe_name(f["url"])
            p = download_file(f["url"], os.path.join(cache_dir, "gt_files", city, name), log, city)
            g = read_vector_archive(p, _bbox_tuple(cfg), f.get("layer_regex"), log, city)
            n0 = len(g)
            if len(g) and f.get("where"):
                g = _apply_where(g, f["where"])
            log(city, "label:file_url", "info", f"{role} {name}: {n0} feature(s) in the study area"
                + (f", {len(g)} after filter {f['where']}" if f.get("where") else "") + f" (sha256 {file_sha256(p)[:12]})")
            if len(g):
                g = g.copy()
                g["_src_layer"] = name
                out.append(g)
                used.append(dict(name=name, url=f["url"], sha256=file_sha256(p), features=int(len(g))))
        return out, used

    frames, used = _read(files, "label")
    if not frames:
        raise RuntimeError(f"none of {len(files)} verified file(s) has features inside the study area")
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    extra = dict(files=used, point_buffer_m=point_buffer_m, gt_tier=gt_tier,
                 geom_types=sorted(set(gdf.geometry.geom_type.astype(str))))
    if coverage_files:
        cov, cused = _read(coverage_files, "coverage")
        if cov:
            cg = gpd.GeoDataFrame(pd.concat(cov, ignore_index=True), geometry="geometry", crs="EPSG:4326")
            extra["_aoi_gdf"] = cg[cg.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
            extra["coverage_files"] = cused
    if date_filter:
        gdf, dinfo = filter_by_event_date(gdf, cfg["event_date"], prereg["label"]["event_window_days"], log, city)
        extra["date_filter"] = dinfo
    return gdf, extra


def _label_with_coverage(source, fetch):
    def _fn(city, cfg, G, df, prereg, cache_dir, log, **kw):
        gdf, extra = fetch(city, cfg, prereg, cache_dir, log, **kw)
        aoi = extra.pop("_aoi_gdf", None)
        y, ys, info = _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=extra.get("point_buffer_m", 0.0),
                                 source=source, extra=extra)
        if aoi is not None and len(aoi):
            _apply_coverage(info, df, G, aoi, log, city, source)
        return y, ys, info
    return _fn


# ---------------------------------------------------------------- USGS Short-Term Network high-water marks
STN_HWM_URL = "https://stn.wim.usgs.gov/STNServices/HWMs/FilteredHWMs.json"


def fetch_usgs_stn(city, cfg, prereg, cache_dir, log, event_id=None, states="", counties=("",), point_buffer_m=250.0,
                   min_height_above_gnd_ft=None, **_):
    """USGS STN high-water marks for one event (public domain), e.g. Event=180 (2017 Harvey),
    Event=312 (2021 Ida). Points; duplicates at one site are merged. A SPARSE label."""
    import geopandas as gpd
    if not event_id:
        raise RuntimeError("no STN event id configured")
    recs = []
    for county in (counties or ("",)):
        params = dict(Event=event_id, States=states, County=county)
        key = f"stn_hwm_{event_id}_{states}_{county}"
        def _get(params=params):
            r = http_get(STN_HWM_URL, params=params, timeout=240, retries=3)
            if r.status_code != 200:
                raise RuntimeError(f"STN HTTP {r.status_code}")
            try:
                return r.json()
            except ValueError:
                raise RuntimeError(f"STN returned non-JSON ({(getattr(r, 'text', '') or '')[:80]!r})")
        js = cached_json(cache_dir, key, _get)
        recs += js if isinstance(js, list) else []
    if not recs:
        raise RuntimeError(f"STN returned no high-water marks for event {event_id} ({states} {list(counties)})")
    d = pd.DataFrame(recs)
    lat = pd.to_numeric(d.get("latitude_dd", d.get("latitude")), errors="coerce")
    lon = pd.to_numeric(d.get("longitude_dd", d.get("longitude")), errors="coerce")
    d = d.assign(lat=lat, lon=lon).dropna(subset=["lat", "lon"])
    d["height_above_gnd"] = pd.to_numeric(d.get("height_above_gnd"), errors="coerce")
    if min_height_above_gnd_ft is not None:
        d = d[d["height_above_gnd"].fillna(0) >= min_height_above_gnd_ft]
    key = d["site_no"].astype(str) if "site_no" in d else (d["lat"].round(5).astype(str) + d["lon"].round(5).astype(str))
    d = d.assign(_k=key).sort_values("height_above_gnd", ascending=False).drop_duplicates("_k")
    b = cfg["bounds"]
    d = d[d.lon.between(b["min_lon"], b["max_lon"]) & d.lat.between(b["min_lat"], b["max_lat"])]
    keep = [c for c in ("hwm_id", "site_no", "flag_date", "survey_date", "height_above_gnd", "elev_ft",
                        "hwmQualityName", "hwm_environment", "countyName") if c in d]
    gdf = gpd.GeoDataFrame(d[keep].reset_index(drop=True), geometry=gpd.points_from_xy(d.lon, d.lat), crs="EPSG:4326")
    if "height_above_gnd" in gdf:
        gdf["depth_m"] = gdf["height_above_gnd"] * 0.3048
    log(city, "label:usgs_stn", "ok", f"{len(recs)} HWMs for event {event_id}; {len(gdf)} distinct sites inside the "
                                      f"study area (buffered {point_buffer_m:.0f} m) — sparse label")
    return gdf, dict(event_id=event_id, states=states, counties=list(counties), n_records=len(recs),
                     point_buffer_m=point_buffer_m, gt_tier="A_authoritative_points")


# ---------------------------------------------------------------- ArcGIS FeatureServer (e.g. CEMS EMSN194)
def esri_to_shapely(geom):
    """Esri JSON geometry -> shapely. Rings: clockwise = exterior, counter-clockwise = hole."""
    from shapely.geometry import Point, MultiLineString, Polygon, LinearRing
    from shapely.ops import unary_union
    if not geom:
        return None
    if "x" in geom and "y" in geom:
        return Point(geom["x"], geom["y"])
    if "paths" in geom:
        return MultiLineString([p for p in geom["paths"] if len(p) >= 2])
    if "rings" in geom:
        ext, holes = [], []
        for ring in geom["rings"]:
            if len(ring) < 4:
                continue
            (holes if LinearRing(ring).is_ccw else ext).append(ring)
        if not ext:               # orientation not honoured by the server: treat every ring as exterior
            ext, holes = holes, []
        polys = []
        for e in ext:
            pe = Polygon(e)
            hs = [h for h in holes if pe.contains(Polygon(h).representative_point())]
            polys.append(Polygon(e, hs).buffer(0))
        return unary_union(polys) if len(polys) > 1 else (polys[0] if polys else None)
    return None
