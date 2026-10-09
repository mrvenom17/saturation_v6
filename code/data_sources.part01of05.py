"""
data_sources.py — every external data source used by the pipeline.

Rules followed by every connector:
  * never raises for an *optional* source: it returns an empty frame plus a
    status record, and the reason is written to the run log;
  * returns a standard table so sources can be merged;
  * caches raw responses to disk so a Colab disconnect does not repeat calls;
  * only real, dated data inside the event window are kept.

Standard document table (social):
  source, doc_id, time_utc (pandas Timestamp, UTC), text, url, lat, lon, tone
  (lat/lon only when the source itself is geolocated; tone only for GDELT).
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import io
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import pipeline_helpers as ph

DOC_COLS = ["source", "doc_id", "time_utc", "text", "url", "lat", "lon", "tone", "synd_key", "author"]
UA = {"User-Agent": "saturation-gradient-research/1.1 (academic, non-commercial)"}
FLOOD_RE = re.compile(r"flood|inundat|waterlog|water-log|submerg|deluge|cyclone|heavy rain|downpour|"
                      r"rain|drain|overflow|stranded|marooned|knee-deep|waist-deep|"
                      r"banjir|genang|hujan|"                      # id
                      r"inundaci|riada|dana\b|lluvia|desbord|"      # es
                      r"alluvion|allagament|esondaz|pioggia|"      # it
                      r"enchente|alagament|inunda|chuva", re.I)    # pt

# search terms per language (v6): queries to keyword APIs (news RSS, Reddit comments, YouTube) use the
# language of the event as well as English; until v5.5 only English terms were sent everywhere
QUERY_TERMS = {"en": ["flood", "flooding", "waterlogging"],
               "es": ["inundación", "DANA", "riada"],
               "it": ["alluvione", "allagamento", "esondazione"],
               "pt": ["enchente", "inundação", "alagamento"],
               "id": ["banjir", "genangan"]}


def query_terms(lang, n_local=3, n_en=2):
    loc = QUERY_TERMS.get(lang, []) if lang != "en" else []
    return list(dict.fromkeys(loc[:n_local] + QUERY_TERMS["en"][:n_en if loc else 3]))


# distress vocabulary per language; used for the transparent S_distress channel
DISTRESS_WORDS = {
    "en": r"stranded|trapped|rescue|evacuat|marooned|submerged|drown|sos\b|help\b|knee[- ]deep|waist[- ]deep|"
          r"neck[- ]deep|boats?\b|power cut|no electricity|collapsed|washed away|dead|died|missing|injured|"
          r"relief camp|shelter|inundated|waterlogged|water-logged|flooded",
    "es": r"atrapad|rescat|evacua|desaparecid|fallecid|muert|herid|socorro|auxilio|sin luz|sin electricidad|"
          r"derrumb|arrastr|anegad|inundad|barro|lodo|refugio|hasta la cintura|hasta las rodillas",
    "it": r"intrappolat|soccors|evacua|dispers|mort|ferit|senza corrente|senza elettricit|crollat|travolt|"
          r"allagat|sommers|fango|sfollat|salvataggio",
    "pt": r"ilhad|resgat|evacua|desaparecid|mort|ferid|sem luz|sem energia|desabou|arrastad|alagad|"
          r"submers|lama|abrigo|socorro",
    "id": r"terjebak|evakuasi|penyelamatan|hilang|meninggal|korban|mati lampu|listrik padam|roboh|hanyut|"
          r"terendam|tergenang|setinggi|lutut|pinggang|dada|pengungsi|bantuan",
}
DISTRESS_RE = re.compile(DISTRESS_WORDS["en"], re.I)


def distress_regex(lang="en"):
    """English terms are always included: coverage of these events is partly English-language."""
    pat = DISTRESS_WORDS["en"] if lang == "en" else DISTRESS_WORDS["en"] + "|" + DISTRESS_WORDS.get(lang, "")
    return re.compile(pat, re.I)


# ======================================================================
# logging
# ======================================================================
class RunLog:
    def __init__(self, path=None, echo=True):
        # the log APPENDS across sessions: a resumed or later run must not erase an earlier city's record
        self.rows, self.path, self.echo = [], path, echo
        self.session = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        self._old = pd.DataFrame()
        if path and os.path.exists(path):
            try:
                self._old = pd.read_csv(path)
            except Exception:  # noqa: BLE001
                self._old = pd.DataFrame()

    def __call__(self, city, stage, status, detail=""):
        rec = dict(time=dt.datetime.utcnow().isoformat(timespec="seconds"), session=self.session, city=city,
                   stage=stage, status=status, detail=str(detail)[:2000])
        self.rows.append(rec)
        if self.echo:
            tag = {"ok": "  ok ", "warn": "WARN ", "fail": "FAIL ", "skip": "skip ", "info": "     "}.get(status, status)
            print(f"[{tag}] {city:<10} {stage:<26} {str(detail)[:220]}")
        if self.path:
            pd.concat([self._old, pd.DataFrame(self.rows)], ignore_index=True).to_csv(self.path, index=False)

    def frame(self):
        """This session's records only (the file on disk holds every session)."""
        return pd.DataFrame(self.rows)


def empty_docs():
    return pd.DataFrame({c: pd.Series(dtype="object") for c in DOC_COLS})


def finalize_docs(df, source, t0, t1):
    if df is None or len(df) == 0:
        return empty_docs()
    df = df.copy()
    for c in DOC_COLS:
        if c not in df:
            df[c] = np.nan
    df["source"] = source
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="coerce")
    df = df[df["time_utc"].between(pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC"))]
    df["text"] = df["text"].fillna("").astype(str).map(lambda s: re.sub(r"<[^>]+>", " ", s)).str.strip()
    df = df[df["text"].str.len() > 0]
    df["doc_id"] = df["doc_id"].astype(str)
    return df[DOC_COLS].drop_duplicates(["source", "doc_id"]).reset_index(drop=True)


# ======================================================================
# HTTP
# ======================================================================
def http_get(url, params=None, headers=None, timeout=60, retries=4, backoff=2.0, allow_status=(200,)):
    import requests
    h = dict(UA, **(headers or {}))
    last = None
    for k in range(retries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code in allow_status:
                return r
            if r.status_code in (404, 400, 401, 403):
                return r
            last = f"HTTP {r.status_code}"
            wait = float(r.headers.get("X-RateLimit-Reset", backoff ** (k + 1))) if r.status_code == 429 else backoff ** (k + 1)
        except Exception as e:  # noqa: BLE001
            last, wait = repr(e)[:200], backoff ** (k + 1)
        time.sleep(min(wait, 60))
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


def download_file(url, path, log=None, city="", timeout=600):
    """Stream a file to disk once; returns the path. Raises with the status if it fails."""
    import requests
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp, last = path + ".part", None
    for attempt in range(5):
        try:
            with requests.get(url, headers=UA, timeout=timeout, stream=True) as r:
                if r.status_code != 200:
                    last = f"HTTP {r.status_code}"
                    if r.status_code in (400, 401, 403, 404):     # not transient
                        break
                else:
                    n = 0
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(1 << 20):
                            fh.write(chunk)
                            n += len(chunk)
                    if n == 0:
                        last = "empty response"
                    else:
                        os.replace(tmp, path)
                        if log:
                            log(city, "download", "ok", f"{n/1e6:.1f} MB from {url[:110]}"
                                                        + (f" (attempt {attempt+1})" if attempt else ""))
                        return path
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:150]
        if attempt < 4:
            wait = 5 * (attempt + 1)
            if log:
                log(city, "download", "info", f"{last}; retrying in {wait}s ({attempt+1}/4): {os.path.basename(url)}")
            time.sleep(wait)
    if os.path.exists(tmp):
        os.remove(tmp)
    raise RuntimeError(f"{last} after 5 attempts for {url}")


VECTOR_EXT = (".gpkg", ".shp", ".geojson", ".json", ".kml", ".kmz", ".gml", ".gdb")


def _bbox_in_layer_crs(member, layer, bbox4326):
    """The WGS84 study box expressed in the layer's own CRS (densified, so a curved projected edge is
    covered). Layers without a CRS or already geographic WGS84 keep the degree box."""
    try:
        import pyogrio
        from pyproj import CRS, Transformer
        info = pyogrio.read_info(member, layer=layer) if layer is not None else pyogrio.read_info(member)
        crs = info.get("crs")
        if not crs:
            return tuple(bbox4326)
        c = CRS.from_user_input(crs)
        if c.equals(CRS.from_epsg(4326)) or (c.is_geographic and c.to_epsg() in (4326, 4269, 4258, 4674)):
            return tuple(bbox4326)       # WGS84, NAD83, ETRS89, SIRGAS: degrees within metres of each other
        tr = Transformer.from_crs("EPSG:4326", c, always_xy=True)
        return tuple(tr.transform_bounds(*bbox4326, densify_pts=21))
    except Exception:  # noqa: BLE001
        return tuple(bbox4326)


def read_vector_archive(path, bbox4326=None, name_regex=None, log=None, city="", strict=False):
    """Read vector layers from a file or zip archive, optionally bbox-filtered.

    Returns an empty GeoDataFrame (not an error) when the layers open cleanly but
    hold nothing inside the study area: Copernicus EMS activations cover several
    areas of interest, and most of them legitimately fall outside one city.
    Raises only when no layer could be opened at all.

    strict=True: with name_regex, ONLY matching files/layers are read (no fall-back to every layer).
    Used for flood and area-of-interest layers, where reading roads or buildings instead would
    silently corrupt the label.
    """
    import geopandas as gpd
    frames, tried, opened, empty, failed = [], [], 0, 0, []
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(VECTOR_EXT) and "__MACOSX" not in n]
        if name_regex:
            hit = [n for n in names if re.search(name_regex, os.path.basename(n), re.I)]
            names = hit if (hit or strict) else names
        # EMS ships each layer as BOTH .json and .shp; reading both double-counts every
        # feature. Keep one copy per layer, preferring the shapefile.
        by_stem = {}
        pref = {".shp": 0, ".gpkg": 1, ".geojson": 2, ".json": 3, ".kml": 4, ".kmz": 5, ".gml": 6, ".gdb": 7}
        for n in names:
            stem = os.path.splitext(os.path.basename(n))[0].lower()
            ext = os.path.splitext(n)[1].lower()
            if stem not in by_stem or pref.get(ext, 9) < pref.get(os.path.splitext(by_stem[stem])[1].lower(), 9):
                by_stem[stem] = n
        dropped = len(names) - len(by_stem)
        if dropped and log:
            log(city, "label:vector", "info",
                f"{os.path.basename(path)}: {dropped} duplicate layer copy(ies) ignored (same layer as .json and .shp)")
        members = [f"/vsizip/{path}/{n}" for n in sorted(by_stem.values())]
    else:
        members = [path]

    for m in members:
        tried.append(os.path.basename(m))
        try:
            try:
                import pyogrio
                layers = [l[0] for l in pyogrio.list_layers(m)]
            except Exception:  # noqa: BLE001
                layers = [None]
            for lyr in layers:
                if name_regex and lyr and (len(layers) > 1 or strict) and not (
                        re.search(name_regex, str(lyr), re.I) or re.search(name_regex, os.path.basename(m), re.I)):
                    continue
                kw = dict(layer=lyr) if lyr is not None else {}
                try:
                    # a bbox tuple is interpreted in the LAYER's CRS, not WGS84: a projected layer (USGS
                    # shapefiles in UTM / State Plane feet) filtered with degrees returned nothing (v5.5.0 bug)
                    g = (gpd.read_file(m, bbox=_bbox_in_layer_crs(m, lyr, bbox4326), **kw) if bbox4326
                         else gpd.read_file(m, **kw))
                except Exception:      # driver without bbox pushdown: read then clip
                    g = gpd.read_file(m, **kw)
                    if bbox4326 is not None and len(g):
                        from shapely.geometry import box as _box
                        g = g.to_crs("EPSG:4326") if g.crs else g.set_crs("EPSG:4326")
                        g = g[g.intersects(_box(*bbox4326))]
                opened += 1
                if len(g):
                    g = g.to_crs("EPSG:4326") if g.crs else g.set_crs("EPSG:4326")
                    g["_src_layer"] = f"{os.path.basename(m)}:{lyr}"
                    frames.append(g)
                else:
                    empty += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{os.path.basename(m)}: {str(e)[:100]}")

    if not frames:
        if opened > 0:      # layers read fine, they just do not reach this city
            if log:
                log(city, "label:vector", "info", f"{os.path.basename(path)}: {opened} layer(s) read, "
                                                  f"none intersecting the study area")
            return gpd.GeoDataFrame({"_src_layer": pd.Series(dtype="object")}, geometry=[], crs="EPSG:4326")
        raise RuntimeError(f"no vector layer could be opened in {os.path.basename(path)} "
                           f"(tried {tried[:6]}; errors: {failed[:3]})")
    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    return out[out.geometry.notna() & ~out.geometry.is_empty]


DATE_COL_RE = re.compile(r"(date|time|start|end|begin|fecha|data|tanggal|event)", re.I)


def filter_by_event_date(gdf, event_date, window_days, log=None, city=""):
    """Keep features whose date attributes fall within the event window.
    Returns (filtered_gdf, info). Raises if the file carries no usable date column,
    because a file without dates cannot be shown to be event-specific."""
    ev = pd.Timestamp(event_date)
    lo, hi = ev + pd.Timedelta(days=window_days[0]), ev + pd.Timedelta(days=window_days[1])
    cand = [c for c in gdf.columns if c != "geometry" and DATE_COL_RE.search(str(c))]
    parsed = {}
    for c in cand:
        try:
            v = pd.to_datetime(gdf[c], errors="coerce", format="mixed", utc=True).dt.tz_localize(None)
        except Exception:  # noqa: BLE001
            continue
        if v.notna().mean() > 0.3:
            parsed[c] = v
    if not parsed:
        raise RuntimeError(f"no usable date column (candidates checked: {cand[:8]}); cannot confirm the file is "
                           "event-specific, so it is rejected")
    hit = pd.Series(False, index=gdf.index)
    for c, v in parsed.items():
        hit |= v.between(lo, hi)
    out = gdf[hit]
    info = dict(date_columns=list(parsed), window=[str(lo.date()), str(hi.date())],
                features_total=int(len(gdf)), features_in_window=int(len(out)))
    if log:
        log(city, "label:date_filter", "ok" if len(out) else "warn",
            f"{len(out)}/{len(gdf)} features dated inside {lo.date()}..{hi.date()} using {list(parsed)[:3]}")
    if len(out) == 0:
        raise RuntimeError(f"no features dated within the event window ({info})")
    return out, info


def window_bounds(event_date, days):
    ev = dt.date.fromisoformat(event_date)
    t0 = dt.datetime.combine(ev + dt.timedelta(days=days[0]), dt.time.min)
    t1 = dt.datetime.combine(ev + dt.timedelta(days=days[1]), dt.time.max)
    return t0, t1


def cached_json(cache_dir, key, fn):
    path = os.path.join(cache_dir, "http", hashlib.sha1(key.encode()).hexdigest() + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return json.load(open(path))
    val = fn()
    json.dump(val, open(path, "w"))
    return val


# ======================================================================
# Earth Engine
# ======================================================================
def ee_pixels(img, G, depth=0, max_depth=5):
    """Pixel-aligned export of a multiband ee.Image onto RasterGrid G."""
    import ee
    try:
        arr = ee.data.computePixels({"expression": img.toFloat(), "fileFormat": "NUMPY_NDARRAY",
                                     "grid": G.ee_grid()})
        return {n: np.asarray(arr[n], dtype=float) for n in arr.dtype.names}
    except Exception as e:  # noqa: BLE001
        if depth >= max_depth or G.nr < 2:
            raise RuntimeError(f"computePixels failed: {str(e)[:300]}")
        out = None
        for r0, sub in G.split(2):
            part = ee_pixels(img, sub, depth + 1, max_depth)
            if out is None:
                out = {k: np.full((G.nr, G.nc), np.nan) for k in part}
            for k, v in part.items():
                out[k][r0:r0 + sub.nr, :] = v
        return out


def cell_mean(img, crs, native_m):
    import ee
    return img.setDefaultProjection(crs=crs, scale=native_m).reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096)


def _roi(bounds):
    import ee
    return ee.Geometry.Rectangle([bounds["min_lon"], bounds["min_lat"], bounds["max_lon"], bounds["max_lat"]])


DEM_ASSETS = ("COPERNICUS/DEM/GLO30_2024_1", "COPERNICUS/DEM/GLO30")


def _dem(roi, log=None, city=""):
    """Copernicus GLO-30. The 2024 edition supersedes the original asset."""
    import ee
    errs = []
    for asset in DEM_ASSETS:
        try:
            col = ee.ImageCollection(asset).filterBounds(roi).select("DEM")
            if int(col.size().getInfo()) > 0:
                if log and asset != DEM_ASSETS[0]:
                    log(city, "physical:dem", "info", f"using {asset} (current edition unavailable here)")
                return col.mosaic().setDefaultProjection(col.first().projection())
            errs.append(f"{asset}: no tiles")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{asset}: {str(e)[:80]}")
    raise RuntimeError(f"no Copernicus DEM available for this area ({'; '.join(errs)})")


def s1_collections(bounds, event_date, s):
    import ee
    roi = _roi(bounds)
    d = ee.Date(event_date)
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(roi)
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")).select("VV"))
    ev = s1.filterDate(d.advance(s["event_days"][0], "day"), d.advance(s["event_days"][1], "day"))
    n_ev = int(ev.size().getInfo())
    if n_ev == 0:
        return None, None, 0
    pas = ev.first().get("orbitProperties_pass").getInfo()
    ev = ev.filter(ee.Filter.eq("orbitProperties_pass", pas))
    bl = s1.filterDate(d.advance(s["baseline_days"][0], "day"), d.advance(s["baseline_days"][1], "day")).filter(
        ee.Filter.eq("orbitProperties_pass", pas))
    if int(bl.size().getInfo()) == 0:
        return None, None, n_ev
    return ev, bl, n_ev


def s1_nearest_dates(bounds, event_date, days=45):
    """Dates of Sentinel-1 IW acquisitions within +/- days of the event (diagnostic only)."""
    import ee
    try:
        d = ee.Date(event_date)
        col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(_roi(bounds)).filter(ee.Filter.eq("instrumentMode", "IW"))
               .filterDate(d.advance(-days, "day"), d.advance(days, "day")))
        ts = col.aggregate_array("system:time_start").getInfo()
        if not isinstance(ts, list):
            return "unavailable"
        dates = sorted({dt.datetime.utcfromtimestamp(t / 1000).date().isoformat() for t in ts})
        return dates if dates else f"none within +/-{days} days"
    except Exception as e:  # noqa: BLE001
        return f"query failed: {str(e)[:80]}"


def physical_layers(city, cfg, G, df, prereg, log):
    """Pre-event physical groups + optional Sentinel-1 event layer, one row per cell."""
    import ee
    crs, b = G.crs, cfg["bounds"]
    roi, d = _roi(b), ee.Date(cfg["event_date"])
    L = {}
    dem = _dem(roi, log, city)
    L["terrain"] = ee.Image.cat([
        cell_mean(dem, crs, 30).rename("elev_m"),
        cell_mean(ee.Terrain.slope(dem), crs, 30).rename("slope_deg"),
        cell_mean(dem.subtract(dem.focalMean(1000, "circle", "meters")), crs, 30).rename("tpi_1km")])
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(roi)
          .filterDate(d.advance(-365, "day"), d.advance(-2, "day")).select("built").mean())
    L["surface"] = ee.Image.cat([cell_mean(wc.eq(50), crs, 10).rename("built_frac"),
                                cell_mean(wc.eq(10), crs, 10).rename("tree_frac"),
                                cell_mean(dw, crs, 10).rename("dw_built")])
    merit = ee.Image("MERIT/Hydro/v1_0_1")
    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    perm = jrc.gte(75).setDefaultProjection(crs=crs, scale=30)
    dist = perm.fastDistanceTransform(1000, "pixels", "squared_euclidean").sqrt().multiply(30)
    L["hydrography"] = ee.Image.cat([merit.select("hnd").resample("bilinear").rename("hand_m"),
                                    merit.select("upa").add(1e-3).log().resample("bilinear").rename("log_upa"),
                                    cell_mean(dist, crs, 30).rename("dist_water_m"),
                                    cell_mean(jrc, crs, 30).rename("jrc_occ")])
    era = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
    im = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07").filterDate(d.advance(-2, "day"), d.advance(1, "day"))
          .select("precipitation").sum().multiply(0.5))
    L["forcing"] = ee.Image.cat([
        era.filterDate(d.advance(-2, "day"), d.advance(1, "day")).select("total_precipitation_sum").sum().multiply(1000).rename("era5_rain_72h"),
        era.filterDate(d.advance(-9, "day"), d.advance(-2, "day")).select("total_precipitation_sum").sum().multiply(1000).rename("era5_rain_ante7d"),
        era.filterDate(d.advance(-3, "day"), d).select("volumetric_soil_water_layer_1").mean().rename("era5_sm_l1"),
        im.rename("imerg_rain_72h")])   # nearest: keep honest ~9-11 km blocks, no interpolated gradients
    meta = {}
    try:
        ev, bl, n_ev = s1_collections(b, cfg["event_date"], prereg["label"]["s1_change"])
        meta["s1_event_scenes"] = n_ev
        if ev is not None:
            L["sar_event"] = cell_mean(bl.median().subtract(ev.min()), crs, 10).rename("s1_vv_drop_db")
        else:
            log(city, "physical:sar_event", "warn", f"no usable Sentinel-1 pair (event scenes={n_ev}); rung dropped")
    except Exception as e:  # noqa: BLE001
        log(city, "physical:sar_event", "warn", f"Sentinel-1 query failed: {e}")
    out = {}
    for grp, img in L.items():
        t = time.time()
        try:
            pix = ee_pixels(img, G)
        except Exception as e:  # noqa: BLE001
            if grp == "terrain":
                raise
            log(city, f"physical:{grp}", "warn", f"group unavailable, rung will be skipped: {e}")
            continue
        for k, v in pix.items():
            out[k] = ph.raster_to_cells(v, df)
        log(city, f"physical:{grp}", "ok", f"{list(pix)} in {time.time() - t:.0f}s")
    phys = pd.DataFrame(out).replace([np.inf, -np.inf], np.nan)
    # Coarse reanalysis leaves holes over water and at tile edges. A city median would
    # invent a flat plateau over a fifth of the grid; the nearest valid cell preserves the field.
    xy = df[["x_m", "y_m"]].to_numpy(float)
    for k in list(phys.columns):
        miss = phys[k].isna().to_numpy()
        if 0 < miss.sum() < len(phys) and miss.mean() <= 0.6:
            from scipy.spatial import cKDTree
            dist, idx = cKDTree(xy[~miss]).query(xy[miss], k=1)
            vals = np.asarray(phys[k], dtype=float).copy()
            vals[miss] = vals[~miss][idx]
            phys[k] = vals
            log(city, "physical:fill", "info", f"{k}: {int(miss.sum())} cells ({miss.mean():.1%}) filled from the "
                                               f"nearest valid cell (max distance {dist.max()/1000:.1f} km)")
    for k in ["era5_rain_72h", "era5_rain_ante7d", "era5_sm_l1", "imerg_rain_72h"]:
        if k in phys:
            nu = int(pd.Series(np.round(phys[k], 3)).nunique())
            log(city, "physical:coarse", "info", f"{k}: {nu} distinct values within the city (native ~9-11 km)")
    for k, v in phys.isna().mean().items():
        if v > 0:
            log(city, "physical:missing", "warn", f"{k}: {v:.1%} still missing after nearest-cell fill -> city median")
    return phys.fillna(phys.median(numeric_only=True)), meta


# ======================================================================
# labels
# ======================================================================
def read_vector_any(path):
    """Read every layer of a KML/GeoJSON/GPKG using pyogrio or fiona, whichever works."""
    import geopandas as gpd
    layers = None
    try:
        import pyogrio
        layers = [l[0] for l in pyogrio.list_layers(path)]
    except Exception:  # noqa: BLE001
        try:
            import fiona
            fiona.drvsupport.supported_drivers["KML"] = "rw"
            fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
            layers = fiona.listlayers(path)
        except Exception:  # noqa: BLE001
            layers = [None]
    parts = []
    for l in layers:
        try:
            g = gpd.read_file(path, layer=l) if l is not None else gpd.read_file(path)
            if len(g):
                parts.append(g)
        except Exception:  # noqa: BLE001
            continue
    if not parts:
        raise RuntimeError(f"no readable layers in {path}")
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=parts[0].crs or "EPSG:4326")
    return g[g.geometry.notna() & ~g.geometry.is_empty]


def label_official(city, cfg, G, df, prereg, cache_dir, log, geom="all"):
    url = cfg.get("gt_url")
    if not url:
        raise RuntimeError("no official label URL configured")
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".kml"
    path = os.path.join(cache_dir, f"{city}_official{ext}")
    if not os.path.exists(path):
        r = http_get(url, timeout=180)
        if r.status_code != 200:
            raise RuntimeError(f"download failed HTTP {r.status_code}")
        open(path, "wb").write(r.content)
    gdf = read_vector_any(path).to_crs(G.crs)
    audit = ph.audit_ground_truth(gdf.to_crs("EPSG:4326"), date_hint=cfg["event_date"])
    if geom == "points":
        gdf = gdf[gdf.geometry.geom_type.isin(["Point", "MultiPoint"])]
        if len(gdf) == 0:
            raise RuntimeError("official file has no point geometries")
        log(city, "label:official_points", "warn", f"using {len(gdf)} point features only; confirm they describe THIS event "
                                                     f"(see label_attempts.json audit) before using results in the paper")
    audit["sha256"] = ph.sha256_file(path)
    y, info = ph.label_cells_from_geometries(df, G, gdf)
    y_s, info_s = ph.label_cells_from_geometries(df, G, gdf, prereg["label"]["sensitivity_point_buffer_m"])
    info.update(audit=audit, sensitivity_positive_cells=int(y_s.sum()))
    return y, y_s, info


def label_gfd(city, cfg, G, df, prereg, cache_dir, log, dfo_id=None):
    """Global Flood Database (Tellman et al. 2021; MODIS 250 m; CC BY-NC 4.0). With dfo_id the exact
    Dartmouth Flood Observatory event is used (filterMetadata('id', 'equals', dfo_id))."""
    import ee
    if dt.date.fromisoformat(cfg["event_date"]) > dt.date(2018, 12, 10):
        raise RuntimeError("Global Flood Database ends 2018-12-10; not applicable")
    d = ee.Date(cfg["event_date"])
    col = ee.ImageCollection("GLOBAL_FLOOD_DB/MODIS_EVENTS/V1")
    if dfo_id is not None:
        col = col.filterMetadata("id", "equals", int(dfo_id))
    else:
        col = col.filterBounds(_roi(cfg["bounds"])).filterDate(d.advance(-30, "day"), d.advance(15, "day"))
    n = int(col.size().getInfo())
    if n == 0:
        raise RuntimeError("no GFD event intersecting the city within [-30, +15] days")
    img = col.select("flooded").max().subtract(col.select("jrc_perm_water").max()).gt(0).unmask(0)
    f = ph.raster_to_cells(ee_pixels(img.rename("f"), G)["f"], df)
    y = (f > 0.5).astype(int)
    log(city, "label:gfd", "info", f"{n} GFD event image(s)" + (f" (DFO {dfo_id})" if dfo_id else "")
        + "; MODIS 250 m resampled to the grid — coarse, reported as a satellite-derived reference")
    return y, None, dict(source="GFD", dfo_id=dfo_id, n_events=n, positive_cells=int(y.sum()),
                         prevalence=float(y.mean()), gt_tier="C_satellite")


def _observable_label(city, G, df, prereg, obs, wat, source, log, extra):
    """Shared rule for satellite labels. 'obs' = pixels the sensor can judge; 'wat' = new water among them.
    A cell is VALID when most of it is observable; it is FLOODED when new water covers at least
    cell_fraction of its observable part. Invalid cells are excluded from training and evaluation."""
    lab = prereg["label"]
    img = ee_image_cat([cell_mean(obs.unmask(0), G.crs, 10).rename("o"), cell_mean(wat.unmask(0), G.crs, 10).rename("w")])
    pix = ee_pixels(img, G)
    o = np.nan_to_num(ph.raster_to_cells(pix["o"], df))
    w = np.nan_to_num(ph.raster_to_cells(pix["w"], df))
    share = np.divide(w, o, out=np.zeros_like(w), where=o > 0)
    valid = o >= lab["valid_cell_fraction"]
    y = ((share >= lab[source]["cell_fraction"]) & valid).astype(int)
    log(city, f"label:{source}", "info",
        f"{valid.mean():.1%} of cells observable ({(~valid).sum():,} excluded as unknown, not dry); "
        f"{int(y.sum())} flooded cells among the observable ones")
    return y, None, dict(source=source, positive_cells=int(y.sum()), valid_cells=int(valid.sum()),
                         prevalence_valid=float(y[valid].mean()) if valid.any() else float("nan"),
                         _valid=valid, **extra)


def ee_image_cat(imgs):
    import ee
    return ee.Image.cat(imgs)


def _observability_masks(roi, s, log, city):
    import ee
    slope = ee.Terrain.slope(_dem(roi, log, city))
    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    hand = ee.Image("MERIT/Hydro/v1_0_1").select("hnd")
    return jrc.lt(s["jrc_occurrence_max"]).And(slope.lt(s["slope_max_deg"])).And(hand.lt(s["hand_max_m"]))


def label_s1_change(city, cfg, G, df, prereg, cache_dir, log):
    """Sentinel-1 VV change. Terrain/drainage/permanent-water masks mark cells UNOBSERVABLE (excluded),
    never 'not flooded', so predictors cannot score by rediscovering the masks."""
    import ee
    s = prereg["label"]["s1_change"]
    ev, bl, n_ev = s1_collections(cfg["bounds"], cfg["event_date"], s)
    if ev is None:
        raise RuntimeError(f"no usable Sentinel-1 event/baseline pair (event scenes={n_ev}); "
                           f"nearest acquisitions: {s1_nearest_dates(cfg['bounds'], cfg['event_date'])}")
    roi = _roi(cfg["bounds"])
    evm, blm = ev.min(), bl.median()
    seen = evm.mask().And(blm.mask())
    obs = seen.And(_observability_masks(roi, s, log, city))
    wat = obs.And(evm.subtract(blm).lt(s["diff_db"])).And(evm.lt(s["event_db"]))
    log(city, "label:s1_change", "info", "Sentinel-1 change detection; under-detects in dense built-up areas")
    return _observable_label(city, G, df, prereg, obs, wat, "s1_change", log, dict(event_scenes=n_ev))


def label_s2_change(city, cfg, G, df, prereg, cache_dir, log):
    """Sentinel-2 MNDWI change (cloud-masked with S2 cloud probability). Optical: blind under cloud,
    so it requires a minimum share of the city observed clear after the event."""
    import ee
    s = prereg["label"]["s2_change"]
    roi, d = _roi(cfg["bounds"]), ee.Date(cfg["event_date"])

    def mndwi_col(a, b):
        sr = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(roi).filterDate(d.advance(a, "day"), d.advance(b, "day"))
        cp = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filterBounds(roi).filterDate(d.advance(a, "day"), d.advance(b, "day"))
        joined = ee.Join.saveFirst("cp").apply(primary=sr, secondary=cp,
                                               condition=ee.Filter.equals(leftField="system:index", rightField="system:index"))

        def mask(img):
            img = ee.Image(img)
            prob = ee.Image(img.get("cp")).select("probability")
            return img.normalizedDifference(["B3", "B11"]).rename("mndwi").updateMask(prob.lt(s["cloud_prob_max"]))
        return ee.ImageCollection(joined).map(mask), int(sr.size().getInfo())
    ev, n_ev = mndwi_col(*s["event_days"])
    bl, n_bl = mndwi_col(*s["baseline_days"])
    if n_ev == 0 or n_bl == 0:
        raise RuntimeError(f"no Sentinel-2 scenes (event={n_ev}, baseline={n_bl})")
    evm, blm = ev.max(), bl.median()
    obs = evm.mask().And(blm.mask()).And(_observability_masks(roi, s, log, city))   # clear sky both dates
    wat = obs.And(evm.gt(s["mndwi_threshold"])).And(blm.lt(s["mndwi_threshold"]))
    clear = ph.raster_to_cells(ee_pixels(cell_mean(evm.mask().unmask(0), G.crs, 10).rename("v"), G)["v"], df)
    cover = float(np.nanmean(np.nan_to_num(clear) > 0.5))
    if cover < s["min_clear_fraction"]:
        raise RuntimeError(f"only {cover:.0%} of cells observed cloud-free after the event (< {s['min_clear_fraction']:.0%})")
    log(city, "label:s2_change", "info", f"Sentinel-2 MNDWI change; {n_ev} event scenes, {cover:.0%} of cells clear; "
                                         "cloudy cells are excluded as unknown, not labelled dry")
    return _observable_label(city, G, df, prereg, obs, wat, "s2_change", log,
                             dict(event_scenes=n_ev, clear_fraction=cover))


# ---------------------------------------------------------------- new label sources
def _bbox_tuple(cfg):
    b = cfg["bounds"]
    return (b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])


def _rasterise(city, G, df, gdf, prereg, log, point_buffer_m=0.0, source="", extra=None):
    y, info = ph.label_cells_from_geometries(df, G, gdf.to_crs(G.crs), point_buffer_m=point_buffer_m)
    extra = {k: v for k, v in (extra or {}).items()
             if k not in ("source", "features", "point_buffer_m") and not k.startswith("_")}
    info.update(source=source, features=int(len(gdf)), point_buffer_m=point_buffer_m, **extra)
    log(city, f"label:{source}", "info", f"{len(gdf)} features -> {int(y.sum())} cells "
                                         f"({y.mean():.3%} of the study area)")
    return y, None, info


EMS_API_HOSTS = ["https://rapidmapping.emergency.copernicus.eu", "https://mapping.emergency.copernicus.eu"]


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
