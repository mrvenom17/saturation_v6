"""
pipeline_helpers.py — network-free building blocks used by the notebook.
Grid geometry, label rasterisation, ground-truth audit, social-mention KDE,
GDELT title parsing and place-name filtering. Unit-tested offline.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter


# ------------------------------------------------------------------ grid
@dataclass
class RasterGrid:
    crs: str        # metric CRS, e.g. "EPSG:32643"
    res: float      # metres
    x0: float       # left edge
    y1: float       # top edge
    nr: int
    nc: int

    def to_json(self):
        return asdict(self)

    def cell_centres(self):
        rows, cols = np.indices((self.nr, self.nc))
        x = self.x0 + (cols + 0.5) * self.res
        y = self.y1 - (rows + 0.5) * self.res
        return rows.ravel(), cols.ravel(), x.ravel(), y.ravel()

    def rowcol(self, x, y):
        c = np.floor((np.asarray(x) - self.x0) / self.res).astype(int)
        r = np.floor((self.y1 - np.asarray(y)) / self.res).astype(int)
        ok = (r >= 0) & (r < self.nr) & (c >= 0) & (c < self.nc)
        return r, c, ok

    def ee_grid(self):
        """Grid spec for ee.data.computePixels (pixel-aligned with this grid)."""
        return {"dimensions": {"width": int(self.nc), "height": int(self.nr)},
                "affineTransform": {"scaleX": float(self.res), "shearX": 0.0, "translateX": float(self.x0),
                                    "shearY": 0.0, "scaleY": -float(self.res), "translateY": float(self.y1)},
                "crsCode": self.crs}

    def split(self, n_parts=2):
        """Split into row bands (for EE requests that exceed memory)."""
        edges = np.linspace(0, self.nr, n_parts + 1).astype(int)
        out = []
        for a, b in zip(edges[:-1], edges[1:]):
            out.append((a, RasterGrid(self.crs, self.res, self.x0, self.y1 - a * self.res, b - a, self.nc)))
        return out


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def make_raster_grid(bounds_lonlat, res, crs):
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = t.transform([bounds_lonlat["min_lon"], bounds_lonlat["max_lon"], bounds_lonlat["min_lon"], bounds_lonlat["max_lon"]],
                         [bounds_lonlat["min_lat"], bounds_lonlat["min_lat"], bounds_lonlat["max_lat"], bounds_lonlat["max_lat"]])
    x0 = np.floor(min(xs) / res) * res
    y1 = np.ceil(max(ys) / res) * res
    nc = int(np.ceil((max(xs) - x0) / res))
    nr = int(np.ceil((y1 - min(ys)) / res))
    return RasterGrid(crs, float(res), float(x0), float(y1), nr, nc)


def grid_frame(G: RasterGrid, boundary_gdf_metric=None):
    """Cell table. If a boundary (in G.crs) is given, keep cells whose centre is inside."""
    import geopandas as gpd
    rows, cols, x, y = G.cell_centres()
    df = pd.DataFrame(dict(row=rows, col=cols, x_m=x, y_m=y))
    if boundary_gdf_metric is not None:
        pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(x, y), crs=G.crs)
        inside = gpd.sjoin(pts, boundary_gdf_metric[["geometry"]], predicate="within", how="inner").index.unique()
        df = df.loc[np.sort(inside)].reset_index(drop=True)
    lon, lat = _to_lonlat(G.crs, df.x_m.to_numpy(), df.y_m.to_numpy())
    df["lon"], df["lat"] = lon, lat
    return df


def _to_lonlat(crs, x, y):
    from pyproj import Transformer
    t = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return t.transform(x, y)


def raster_to_cells(arr2d, df):
    return np.asarray(arr2d)[df["row"].to_numpy(), df["col"].to_numpy()]


# ------------------------------------------------------ ground truth
def audit_ground_truth(gdf, date_hint=None):
    """Human-readable audit of a label file. Returns dict + prints nothing."""
    geom_types = gdf.geometry.geom_type.value_counts().to_dict()
    cols = [c for c in gdf.columns if c != "geometry"]
    date_cols = {}
    for c in cols:
        s = gdf[c].astype(str)
        hits = s.str.extract(r"((?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2})")[0].dropna()
        if len(hits) > 0:
            date_cols[c] = dict(n_with_date=int(len(hits)), examples=hits.unique()[:5].tolist())
    text_examples = {c: gdf[c].astype(str).head(3).tolist() for c in cols[:6]}
    return dict(n_features=int(len(gdf)), geometry_types=geom_types, columns=cols,
                date_like_columns=date_cols, text_examples=text_examples,
                date_hint=date_hint, bounds=[float(b) for b in gdf.total_bounds])


def label_cells_from_geometries(df, G: RasterGrid, gdf_metric, point_buffer_m=0.0):
    """Points -> the cell containing each point (optionally buffered).
    Polygons/lines -> cells whose centre falls inside (lines are buffered by half a cell)."""
    import geopandas as gpd
    lab = np.zeros((G.nr, G.nc), dtype=np.uint8)
    pts = gdf_metric[gdf_metric.geometry.geom_type.isin(["Point", "MultiPoint"])]
    oth = gdf_metric[~gdf_metric.geometry.geom_type.isin(["Point", "MultiPoint"])]
    n_pts_in = 0
    if len(pts):
        ex = pts.explode(index_parts=False)
        if point_buffer_m > 0:
            oth = pd.concat([oth, gpd.GeoDataFrame(geometry=ex.buffer(point_buffer_m), crs=G.crs)])
        else:
            r, c, ok = G.rowcol(ex.geometry.x.to_numpy(), ex.geometry.y.to_numpy())
            lab[r[ok], c[ok]] = 1
            n_pts_in = int(ok.sum())
    if len(oth):
        geo = oth.copy()
        is_line = geo.geometry.geom_type.isin(["LineString", "MultiLineString"])
        geo.loc[is_line, "geometry"] = geo.loc[is_line].buffer(G.res / 2)
        cells = gpd.GeoDataFrame(df[["row", "col"]].copy(),
                                 geometry=gpd.points_from_xy(df.x_m, df.y_m), crs=G.crs)
        hit = gpd.sjoin(cells, geo[["geometry"]], predicate="within", how="inner")
        lab[hit["row"].to_numpy(), hit["col"].to_numpy()] = 1
    y = raster_to_cells(lab, df).astype(int)
    return y, dict(points_inside_grid=n_pts_in, positive_cells=int(y.sum()),
                   prevalence=float(y.mean()))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------ social
_TITLE_RE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)


def extract_title(extras):
    if not isinstance(extras, str):
        return None
    m = _TITLE_RE.search(extras)
    return html.unescape(m.group(1)).strip() if m else None


CITY_LEVEL_TYPES = {"city", "town", "state", "state_district", "county", "country",
                    "region", "province", "administrative", "municipality", "district"}


def clean_place(s):
    s = re.sub(r"^##", "", str(s)).strip(" .,:;'\"()[]")
    return re.sub(r"\s+", " ", s)


def is_useful_place(place, city_aliases, extra_stop=()):
    p = clean_place(place).lower()
    if len(p) < 3 or p.isdigit():
        return False
    stop = {a.lower() for a in city_aliases} | {"india", "indonesia", "karnataka", "tamil nadu",
                                                "south india", "bay of bengal"} | {e.lower() for e in extra_stop}
    return p not in stop


def accept_geocode(result, bounds, city_level_types=CITY_LEVEL_TYPES):
    """result: dict with lat, lon, addresstype/type. Reject city-level or out-of-bbox."""
    if not result:
        return False
    at = (result.get("addresstype") or result.get("type") or "").lower()
    if at in city_level_types:
        return False
    la, lo = float(result["lat"]), float(result["lon"])
    return (bounds["min_lat"] <= la <= bounds["max_lat"]) and (bounds["min_lon"] <= lo <= bounds["max_lon"])


def mention_kde(G: RasterGrid, x_m, y_m, weights, bandwidth_m):
    """Gaussian kernel density of geocoded mentions on the raster (mentions/km^2)."""
    ras = np.zeros((G.nr, G.nc))
    r, c, ok = G.rowcol(x_m, y_m)
    np.add.at(ras, (r[ok], c[ok]), np.asarray(weights, float)[ok])
    sig = bandwidth_m / G.res
    dens = gaussian_filter(ras, sigma=sig, mode="constant", truncate=3.0)
    return dens * (1e6 / (G.res ** 2)), int(ok.sum())


def prereg_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def cells_to_raster(values, df, G, fill=np.nan):
    ras = np.full((G.nr, G.nc), fill, dtype=float)
    ras[df["row"].to_numpy(), df["col"].to_numpy()] = np.asarray(values, float)
    return ras
