"""
orchestrator.py — runs the whole study for a list of cities.

Each city goes through stages with on-disk checkpoints. A failing city is
recorded and skipped; the other cities still run. Every number written for the
paper comes from files produced here.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pickle
import re
import shutil
import time
import traceback

import numpy as np
import pandas as pd

import data_sources as ds
import pipeline_helpers as ph
import saturation_core as sc

PIPELINE_VERSION = "v6.1.1"
PROFILES = {
    "full":   dict(n_null=99, n_boot=500, n_estimators=400, n_null_early=25, sensitivity=True, emotion_lens=True,
                   label="FULL (paper numbers)"),
    "medium": dict(n_null=39, n_boot=200, n_estimators=300, n_null_early=15, sensitivity=False, emotion_lens=True,
                   label="MEDIUM (wider CIs; state the null/bootstrap counts if used in the paper)"),
    "quick":  dict(n_null=19, n_boot=100, n_estimators=150, n_null_early=9, sensitivity=False, emotion_lens=True,
                   label="QUICK (pipeline check, NOT for the paper)"),
}
CITY_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def city_code(name):
    """Short, unique LaTeX-safe prefix: first three letters plus any year in the key."""
    alpha = "".join(ch for ch in name if ch.isalpha())[:3]
    year = "".join(ch for ch in name if ch.isdigit())
    return alpha + year


# ---------------------------------------------------------------- prereg
def _note_reason(dev, reason):
    """Attach the stated reason to the open deviation entry (once)."""
    if not reason or not os.path.exists(dev):
        return
    txt = open(dev).read()
    if "State the reason here" in txt and reason.strip() not in txt:
        with open(dev, "a") as fh:
            fh.write(f"Reason (recorded {dt.datetime.utcnow().isoformat(timespec='seconds')}Z): {reason.strip()}\n")


def write_prereg(prereg, out_dir, reason=None):
    h = hashlib.sha256(json.dumps(prereg, sort_keys=True).encode()).hexdigest()
    path = os.path.join(out_dir, "preregistration.json")
    dev = os.path.join(out_dir, "deviations.md")
    try:
        return _write_prereg(prereg, out_dir, h, path, dev)
    finally:
        _note_reason(dev, reason)


def _write_prereg(prereg, out_dir, h, path, dev):
    if os.path.exists(path):
        old = json.load(open(path))
        if old.get("sha256") != h:
            with open(dev, "a") as fh:
                fh.write(f"\n## {dt.datetime.utcnow().isoformat()}Z\nPre-registration changed from {old.get('sha256')} "
                         f"to {h}. Previous version archived as preregistration_{old.get('sha256', 'old')[:8]}.json. "
                         f"State the reason here before using these results.\n")
            shutil.copy(path, os.path.join(out_dir, f"preregistration_{old.get('sha256', 'old')[:8]}.json"))
            print("NOTE: pre-registration changed; deviation recorded in deviations.md")
        else:
            return h
    json.dump(dict(prereg=prereg, sha256=h, written_utc=dt.datetime.utcnow().isoformat()), open(path, "w"), indent=2)
    return h


# ---------------------------------------------------------------- helpers
def make_geocoder(cfg, cache_dir):
    b = cfg["bounds"]
    path = os.path.join(cache_dir, "nominatim_cache.json")
    cache = json.load(open(path)) if os.path.exists(path) else {}
    state = dict(unsaved=0)

    def flush():
        if not state["unsaved"]:
            return
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, path)
        state["unsaved"] = 0

    def geocode(place):
        # v5.4.2: raw candidates are cached (up to 5, in the study box) and ds.resolve_mentions decides which, if
        # any, is the named settlement. The old key cached only a pre-filtered top hit, which rejected towns and
        # accepted same-named streets; the "raw2|" prefix keeps those entries from being reused.
        # v6 ("raw3"): the name alone, bounded to the study box. v5 appended the first retrieval alias, which for
        # multi-town areas was another town ("Humble, Kingwood") and made valid names unfindable.
        # v6.1 ("raw4"): v6.0 stored an EMPTY candidate list for any refused request (HTTP 403 and the like), which
        # cannot be told apart from "Nominatim knows no such place". Non-empty raw3 answers can only have come from a
        # real answer and are reused; empty ones are asked again once, under the new prefix.
        key = f"raw4|{place.lower()}|{ds._bounds_tag(b)}"
        if key in cache:
            return cache[key]
        old = cache.get(f"raw3|{place.lower()}|{ds._bounds_tag(b)}")
        if old:
            cache[key] = old
            state["unsaved"] += 1
            return old
        # v6.1: a failed lookup is RAISED. v6.0 returned [] here, and resolve_mentions then stored "no such place"
        # in its own cache, so one timeout removed a name from every later run. The 1 request/second policy is
        # kept by ds.http_get (HOST_PACE), which also honours Retry-After.
        try:
            r = ds.http_get("https://nominatim.openstreetmap.org/search",
                            params=dict(q=place, format="jsonv2", limit=5, bounded=1,
                                        viewbox=f"{b['min_lon']},{b['max_lat']},{b['max_lon']},{b['min_lat']}"),
                            timeout=30, retries=3)
        except Exception as e:  # noqa: BLE001
            raise ds.TransientLookupError(f"Nominatim: {str(e)[:120]}") from e
        if r.status_code != 200:
            raise ds.TransientLookupError(f"Nominatim: HTTP {r.status_code}")
        try:
            js = r.json()
        except Exception as e:  # noqa: BLE001
            raise ds.TransientLookupError(f"Nominatim: unreadable answer ({str(e)[:80]})") from e
        cache[key] = [dict(lat=c.get("lat"), lon=c.get("lon"), name=c.get("name"), addresstype=c.get("addresstype"),
                           type=c.get("type"), display_name=c.get("display_name")) for c in (js or [])]
        state["unsaved"] += 1
        if state["unsaved"] >= 25:       # v6.1: the whole cache was rewritten after every lookup (slow on Drive)
            flush()
        return cache[key]
    geocode.flush = flush                # resolve_mentions calls it when it is done, so nothing is left unsaved
    return geocode


def grid_bounds_lonlat(G):
    """Lon/lat envelope of the raster grid (edges densified), rounded to 5 decimals: the study box as a function of
    the grid alone, so it is the same in the session that built the grid and in every session that resumes it."""
    from pyproj import Transformer
    t = Transformer.from_crs(G.crs, "EPSG:4326", always_xy=True)
    x0, x1, y1, y0 = G.x0, G.x0 + G.nc * G.res, G.y1, G.y1 - G.nr * G.res
    xs = np.concatenate([np.linspace(x0, x1, 21), np.linspace(x0, x1, 21), np.full(21, x0), np.full(21, x1)])
    ys = np.concatenate([np.full(21, y0), np.full(21, y1), np.linspace(y0, y1, 21), np.linspace(y0, y1, 21)])
    lon, lat = t.transform(xs, ys)
    return dict(min_lon=round(float(np.min(lon)), 5), min_lat=round(float(np.min(lat)), 5),
                max_lon=round(float(np.max(lon)), 5), max_lat=round(float(np.max(lat)), 5))


OPTIONAL_KEY_SOURCES = ("flickr", "youtube")      # sources that appear when a key is added in Colab Secrets


def _mentions_from_v61(st, cfg, wide, sources, text_docs, common, city, log):
    """Reuse the text mentions of a COMPLETE v6.1 acquisition (v6.1.1). v6.1 kept one checkpoint for all mentions,
    keyed on the whole document set; its text part is still valid whenever the text documents are unchanged (the
    routing rule, the geocoder rule, the gazetteer and the study box are part of the key and are checked here).
    Rule t5's final filter is then applied, exactly as resolve_mentions applies it, so the result equals a fresh
    v6.1.1 run. Returns None if there is nothing to reuse: the caller then resolves the documents normally."""
    variants = [list(sources)]
    for drop in (("flickr",), ("youtube",), OPTIONAL_KEY_SOURCES):          # a key added since v6.1 changes the list
        v = [s_ for s_ in sources if s_ not in drop]
        if v not in variants:
            variants.append(v)
    fp_text = ds.documents_fingerprint(text_docs)
    for srcs in variants:
        k_docs61 = _h("6", cfg["event_date"], wide, srcs, cfg.get("aliases"), cfg.get("subreddits"),
                      cfg.get("news_locale"), cfg.get("petabencana_region"), cfg["bounds"])
        p_docs = st._path(f"docs_{k_docs61}")
        if not os.path.exists(p_docs):
            continue
        try:
            with open(p_docs, "rb") as fh:
                old_docs = pickle.load(fh)[0]
            if ds.documents_fingerprint(ds.split_documents(old_docs)[1]) != fp_text:
                continue                        # the text documents changed: nothing can be reused
            k_ment61 = _h("9", k_docs61, ds.documents_fingerprint(old_docs), common[0], common[1], cfg.get("lang"), common[3],
                          common[4], "t4", common[6], common[7], common[8], common[9])
            p_m = st._path(f"mentions_{k_ment61}")
            if common[5] != "t4" or not os.path.exists(p_m):
                continue
            with open(p_m, "rb") as fh:
                m, n_gaz, ginfo = pickle.load(fh)
            if not ginfo.get("complete", False):
                continue
            m_text = m[m["via"] != "native"].reset_index(drop=True)
            m_text, tstats = ds.refine_gazetteer_mentions(m_text, city, cfg)
            log(city, "social:places", "ok", f"{len(m_text)} text mentions reused from the complete v6.1 acquisition (same "
                                             f"text documents, gazetteer, study box and lookup rules); rule "
                                             f"{ds.TOPONYM_RULES_VERSION} dropped {tstats.get('dropped', 0)} of them "
                                             f"{tstats.get('top_dropped', [])[:4]}")
            return m_text, n_gaz, dict(ginfo, migrated_from="v6.1", tail_of_longer_name=int(tstats.get("dropped", 0)))
        except Exception as e:  # noqa: BLE001
            log(city, "social:places", "info", f"v6.1 mentions could not be reused ({str(e)[:120]}); resolving again")
    return None


def build_ladder(prereg, ordering, phys_cols, label_source, log, city):
    groups, seq = prereg["physical_groups"], list(prereg["orderings"][ordering])
    if str(label_source).split(":")[0] in ds.SAR_LABEL_SOURCES:
        # the label itself comes from Sentinel-1 backscatter: a Sentinel-1 predictor would rediscover it
        seq = [g for g in seq if g != "sar_event"]
    ladder, feats = [("R0_none", [])], []
    for i, g in enumerate(seq, 1):
        new = [f for f in groups[g] if f in phys_cols]
        if not new:
            log(city, "ladder", "info", f"group '{g}' unavailable -> rung skipped (pre-registered rule)")
            continue
        feats = feats + new
        ladder.append((f"R{len(ladder)}_+{g}", list(feats)))
    return ladder


class Stage:
    """On-disk checkpoints. Every stage and every ladder rung is written as soon as it
    finishes, so a disconnected run resumes instead of starting over. Writes go to a
    temporary file first, so an interrupted write cannot leave a half-written checkpoint."""

    def __init__(self, cache_dir, log=None, city=""):
        self.cache_dir, self.log, self.city = cache_dir, log, city
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, name):
        return os.path.join(self.cache_dir, f"{name}.pkl")

    def get(self, name, fn, quiet=False, final=None):
        """`final(value)` (v6.1): if given and False, the value is returned but NOT written, so an incomplete result
        (a capped geocoder, a source that failed) is recomputed by the next run instead of being frozen. v6.0 froze
        such results, and re-running a city silently reloaded the truncated stage."""
        p = self._path(name)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            try:
                with open(p, "rb") as fh:
                    val = pickle.load(fh)
                if self.log and not quiet:
                    self.log(self.city, f"resume:{name}", "info", "loaded from checkpoint (not recomputed)")
                return val
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log(self.city, f"resume:{name}", "warn", f"checkpoint unreadable ({e}); recomputing")
        val = fn()
        if final is not None and not final(val):
            if self.log and not quiet:
                self.log(self.city, f"stage:{name}", "info", "incomplete, so not checkpointed: the next run recomputes it")
            return val
        tmp = p + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(val, fh)
        os.replace(tmp, p)
        return val

    def rung_cache(self, tag=""):
        """Callable passed to run_ladder so each rung is checkpointed individually.
        A hit means the rung was already computed (earlier ordering, or before a disconnect)."""
        def cache(key, fn):
            name = f"rung_{key}"
            hit = os.path.exists(self._path(name)) and os.path.getsize(self._path(name)) > 0
            if hit and self.log:
                self.log(self.city, f"rung:{tag}" if tag else "rung", "info",
                         f"reused from checkpoint {key} (identical feature set; not recomputed)")
            return self.get(name, fn, quiet=True)
        return cache


def save_tables(out_dir, prefix, res):
    """Write one ordering's tables immediately, so a later failure cannot lose them."""
    tag = os.path.join(out_dir, prefix)
    res["summary"].to_csv(f"{tag}_summary.csv", index=False)
    res["point"].to_csv(f"{tag}_point_metrics.csv", index=False)
    res["gradient"].to_csv(f"{tag}_gradient.csv", index=False)
    res["gated_params"].to_csv(f"{tag}_gated_params.csv", index=False)
    res["boot"].to_csv(f"{tag}_bootstrap.csv.gz", index=False)
    if res.get("effects") is not None and len(res["effects"]):
        res["effects"].to_csv(f"{tag}_effects.csv", index=False)
    for r in res["results"]:
        if len(r.get("null", [])):
            r["null"].to_csv(f"{tag}_{r['rung']}_null.csv", index=False)


# ---------------------------------------------------------------- per city
# v6.1: identifies the acquisition rules (text cleaning, toponym rule on both paths, completeness accounting,
# source pacing). Inputs saved under other rules carry the v6.0 defects and are refused by run_all in analyse mode.
ACQUISITION_RULES = "a3"      # a3 (v6.1.1): Commons tiles subdivided, toponym rule t5
# Bump a version when that stage's code changes, so only that stage and what depends on it recompute.
STAGE_CODE = dict(grid="5", physical="2", labels="6", docs="7", mentions="9", analysis="5", gazetteer="2")


def _h(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _smooth_density(dens, df, G, bandwidth_m):
    """Population density smoothed with the social layer's own kernel and transform (log1p per km^2), so the
    placebo differs from the social layer only in what it measures, not in how smooth it is."""
    from scipy.ndimage import gaussian_filter
    ras = ph.cells_to_raster(dens, df, G, fill=0.0)
    sm = gaussian_filter(ras, sigma=bandwidth_m / G.res, mode="constant", truncate=3.0)
    return np.log1p(np.clip(sm[df["row"].to_numpy(), df["col"].to_numpy()], 0, None))


def _augment(res, prereg, log, city, tag):
    """v5.5 additions to one ladder result: robustness (without R0) and headroom-normalised gradients, and the
    per-rung effect table with equivalence verdicts. Failures are logged, never fatal."""
    keep_roles = ("robust_excl_R0", "headroom_normalised", "headroom_normalised_excl_R0")
    g = res["gradient"]
    parts = [g[~g["role"].isin(keep_roles)]]
    for fn in (lambda: sc.gradient_robustness(res), lambda: sc.normalised_gradients(res),
               lambda: sc.normalised_gradients(res, drop_first=True)):
        try:
            parts.append(fn())
        except Exception as e:  # noqa: BLE001
            log(city, f"gradient:{tag}", "warn", f"a robustness gradient failed: {e}")
    res["gradient"] = pd.concat([p_ for p_ in parts if p_ is not None and len(p_)], ignore_index=True)
    try:
        res["effects"] = sc.effect_table(res, sesoi=(prereg.get("analysis_plan") or {}).get("sesoi"))
    except Exception as e:  # noqa: BLE001
        log(city, f"effects:{tag}", "warn", f"effect table failed: {e}")
        res["effects"] = pd.DataFrame()
    return res


def run_city(city, cfg, prereg, profile, clients, out_root, cache_root, log):
    """Full per-city run = data acquisition (network) followed by analysis (no network). The two halves can
    also run on different machines: RUN_MODE 'acquire' saves the inputs, 'analyse' reads them (v5.5.2)."""
    return analyse_city(acquire_city(city, cfg, prereg, profile, clients, out_root, cache_root, log),
                        prereg, profile, out_root, cache_root, log)


def acquire_city(city, cfg, prereg, profile, clients, out_root, cache_root, log):
    """Stages 1-4 and the population layer: everything that needs the network. Returns the analysis inputs."""
    P = PROFILES[profile]
    cfg = copy.deepcopy(cfg)            # never mutate the registry the notebook holds
    out = os.path.join(out_root, city)
    os.makedirs(out, exist_ok=True)
    # One folder per city-event; every stage name hashes exactly the inputs it depends on, so a change
    # recomputes that stage and its dependants and nothing else. Earlier cache folders are left untouched.
    st = Stage(os.path.join(cache_root, f"{city}_{cfg['event_date']}"), log, city)
    lab = cfg.get("label_params") or {}
    k_grid = _h(STAGE_CODE["grid"], cfg.get("bounds"), cfg.get("bounds_from_label"), cfg.get("bounds_pad_km"),
                cfg.get("label_search_bounds"), cfg.get("use_bbox_only"), cfg.get("boundary_query"),
                cfg.get("grid_m"), prereg["grid_m"], prereg.get("max_cells"), prereg.get("grid_m_escalation"),
                cfg["label_chain"][:1], lab if cfg.get("bounds_from_label") else None)
    k_phys = _h(STAGE_CODE["physical"], k_grid, cfg["event_date"], prereg["physical_groups"],
                prereg["label"]["s1_change"])
    k_lab = _h(STAGE_CODE["labels"], k_grid, cfg["event_date"], prereg["label"], cfg["label_chain"], lab,
               cfg.get("gt_url"), cfg.get("petabencana_region"))
    prov = dict(city=city, event_date=cfg["event_date"], profile=profile,
                stage_keys=dict(grid=k_grid, physical=k_phys, labels=k_lab))

    # 1. grid ---------------------------------------------------------
    def _grid():
        import geopandas as gpd
        from shapely.geometry import box
        b = cfg["bounds"]
        if cfg.get("bounds_from_label") or b is None:
            try:
                b, pinfo = ds.probe_label_bounds(city, cfg, prereg, cache_root, log,
                                                 pad_km=cfg.get("bounds_pad_km", 3.0))
                prov["bounds_from_label"] = pinfo
            except Exception as e:  # noqa: BLE001
                if b is None:
                    raise
                log(city, "grid:probe", "warn", f"could not place the grid on the label ({str(e)[:160]}); "
                                                "using the registry bounds")
        crs = ph.utm_epsg((b["min_lon"] + b["max_lon"]) / 2, (b["min_lat"] + b["max_lat"]) / 2)
        # Deterministic, pre-registered rule: coarsen only if the bounding box exceeds max_cells.
        gm = int(cfg.get("grid_m", prereg["grid_m"]))
        steps = [s for s in prereg.get("grid_m_escalation", [gm]) if s >= gm] or [gm]
        cap = prereg.get("max_cells", 260000)
        for gm in steps:
            G = ph.make_raster_grid(b, gm, crs)
            # the bounding box is an upper bound on cells inside the study area, so satisfying the cap
            # here guarantees the hard check below cannot fail (v5.3 compared against 1.6x the cap)
            if G.nr * G.nc <= cap:
                break
        cfg["bounds"], cfg["grid_m"] = b, gm
        bbox = gpd.GeoDataFrame(geometry=[box(b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])], crs="EPSG:4326")
        if cfg.get("use_bbox_only") or not cfg.get("boundary_query"):
            log(city, "grid:boundary", "info", "study area = bounding box by configuration (the flooding crosses "
                                               "administrative boundaries, so no single city polygon fits)")
            boundary = bbox
        else:
            try:
                import osmnx as ox
                q = cfg["boundary_query"]
                if not isinstance(q, (str, dict)):
                    raise TypeError(f"boundary_query must be a string or dict, got {type(q).__name__}")
                try:
                    geo = ox.geocode_to_gdf(q)
                except AttributeError:                      # osmnx >= 2 moved the helper
                    geo = ox.geocoder.geocode_to_gdf(q)
                boundary = geo[["geometry"]].to_crs("EPSG:4326")
                boundary = gpd.overlay(boundary, bbox, how="intersection")
                if boundary.empty:
                    raise RuntimeError("boundary does not intersect bbox")
            except Exception as e:  # noqa: BLE001
                log(city, "grid:boundary", "warn", f"OSM boundary unavailable ({e}); using the bounding box")
                boundary = bbox
        df = ph.grid_frame(G, boundary.to_crs(crs))
        return G, df, boundary
    probed = bool(cfg.get("bounds_from_label") or cfg.get("bounds") is None)
    G, df, boundary = st.get(f"grid_{k_grid}", _grid)
    gm = int(round(G.res))
    cfg["grid_m"] = gm
    if probed:
        # v6.1: for a grid placed on the label's extent, the study box used by the social sources and the geoparser
        # is derived from the grid itself. v6.0 set it only in the session that BUILT the grid; a resumed session
        # loaded the grid from its checkpoint and silently used the registry's (different) box instead.
        cfg["bounds"] = grid_bounds_lonlat(G)
        pinfo = st.get(f"gridinfo_{k_grid}", lambda: prov.get("bounds_from_label") or {}, quiet=True, final=bool)
        if pinfo:
            prov["bounds_from_label"] = pinfo
    prov["study_box"] = dict(cfg["bounds"], from_label=probed)
    log(city, "grid", "ok", f"{G.nr}x{G.nc} raster at {gm} m, {len(df):,} cells in study area, {G.crs}")
    if gm != prereg["grid_m"]:
        log(city, "grid", "warn", f"cell size {gm} m differs from the study default {prereg['grid_m']} m "
                                  "(large study area); report this per-city resolution in the paper")
    prov["grid_m"] = gm
    cap = prereg.get("max_cells", 260000)
    if len(df) > cap:
        raise RuntimeError(f"{len(df):,} cells exceeds max_cells={cap:,}. Either tighten the registry bounds / "
                           f"bounds_pad_km, set a larger per-city grid_m (e.g. grid_m=150), or raise "
                           f"PREREG['max_cells'] knowing the run will be slow.")
    prov.update(grid=G.to_json(), n_cells=len(df))

    # 2. physical layers ------------------------------------------------
    phys, pmeta = st.get(f"physical_{k_phys}", lambda: ds.physical_layers(city, cfg, G, df, prereg, log))
    prov["physical_meta"] = pmeta
    prov["physical_columns"] = list(phys.columns)

    # 3. labels ------------------------------------------------------------
    y, y_sens, label_source, linfo = st.get(f"labels_{k_lab}",
                                            lambda: ds.label_chain(city, cfg, G, df, prereg, cache_root, log, out_dir=out))
    label_valid = np.asarray(linfo.get("_valid", np.ones(len(y), bool)), bool)
    # the source that actually produced the label (a frozen file records which live source it froze)
    eff_source = (linfo.get("frozen_source") or label_source) if label_source == "canonical_gpkg" else label_source
    gt_tier = linfo.get("gt_tier") or ds.SOURCE_TIER.get(str(eff_source).split(":")[0], "unknown")
    prov.update(gt_tier=gt_tier, effective_label_source=eff_source)
    if str(eff_source).split(":")[0] in ds.SAR_LABEL_SOURCES:
        log(city, "ladder", "info", f"label is Sentinel-1-derived ({eff_source}): the SAR rung is removed from every "
                                    f"ladder so the model cannot rediscover the label")
    prov.update(label_source=label_source, label_info={k: v for k, v in linfo.items() if not str(k).startswith("_")})
    log(city, "labels", "ok", f"source={label_source}, positives={int(y[label_valid].sum())}, "
                              f"prevalence={y[label_valid].mean():.4%} of {int(label_valid.sum()):,} observable cells")
    if y[label_valid].mean() > prereg["label"]["flag_prevalence_above"]:
        log(city, "labels", "warn", f"prevalence {y[label_valid].mean():.1%} is high: Recall@K and AP are near their random "
                                     f"baselines by construction, so read info_nats and AUC for this city")

    # 4. social documents (widest window once, then filtered) -------------------
    sp = prereg["social"]
    wide = [min(sp["window_days"][0], sp["sensitivity_window_days"][0]), max(sp["window_days"][1], sp["sensitivity_window_days"][1])]
    sources = [s for s in cfg.get("social_sources", sp["sources"]) if clients.get("enabled_sources", {}).get(s, True)]
    if str(eff_source).startswith("petabencana"):
        # the label IS crowdsourced PetaBencana reports: the same reports cannot also be a predictor
        sources = [s for s in sources if s != "petabencana"]
        log(city, "social", "info", "PetaBencana is the label source here, so it is excluded from the social layer "
                                    "(and this city is a crowdsourced-label case, not confirmatory evidence)")
    k_docs = _h(STAGE_CODE["docs"], cfg["event_date"], wide, sources, cfg.get("aliases"), cfg.get("subreddits"),
                cfg.get("news_locale"), cfg.get("petabencana_region"), cfg["bounds"])
    docs, sstatus = st.get(f"docs_{k_docs}", lambda: ds.collect_documents(city, cfg, wide, sources, clients, cache_root, log),
                           final=lambda v: ds.documents_complete(v[1]))
    sstatus.to_csv(os.path.join(out, "social_source_status.csv"), index=False)
    docs_ok = ds.documents_complete(sstatus)
    pending = [f"source {r_['source']}: {str(r_.get('detail'))[:120]}" for r_ in sstatus.to_dict("records")
               if bool(r_.get("retry")) and r_.get("retry") == r_.get("retry")]
    off = sorted(s for s in cfg.get("social_sources", sp["sources"]) if s not in sources)
    prov["documents"] = dict(fetched_by_source={r_["source"]: int(r_["n"]) for r_ in sstatus.to_dict("records")},
                             kept_by_source=docs["source"].value_counts().to_dict() if len(docs) else {},
                             kept_total=int(len(docs)), complete=bool(docs_ok), sources_switched_off=off,
                             composition=ds.signal_composition(docs))

    # Gazetteer and neighbouring-town list (v5.5.1): GeoNames country extract, a static file, so every city and
    # every run uses the same place names. OSM/Overpass is only a logged fallback if GeoNames cannot be read.
    bkm = prereg["social"].get("outside_places_buffer_km", 80)
    k_gaz = _h(STAGE_CODE["gazetteer"], k_grid, ds.GAZETTEER_VERSION, cfg.get("countries"), bkm)
    try:
        gaz, outside, gmeta = st.get(f"gazetteer_{k_gaz}",
                                     lambda: ds.geonames_places(boundary, cfg, city, cache_root, log, buffer_km=bkm))
        outside_ok = True
    except Exception as e:  # noqa: BLE001
        log(city, "social:gazetteer", "warn", f"GeoNames gazetteer unavailable ({str(e)[:200]}); falling back to OSM "
                                              f"(the gazetteer source then differs from the pre-registration: report it)")
        gaz, outside, outside_ok, gmeta = pd.DataFrame(columns=["key", "name", "lat", "lon"]), set(), False, dict(source="osm_fallback")
        try:
            gaz = ds.osm_gazetteer(boundary, log, city)
        except Exception as e2:  # noqa: BLE001
            log(city, "social:gazetteer", "warn", f"OSM gazetteer unavailable too: {str(e2)[:200]}")
        try:
            outside, outside_ok = ds.osm_outside_places(boundary, bkm, log, city), True
        except Exception as e2:  # noqa: BLE001
            log(city, "social:outside_places", "warn", f"could not list neighbouring towns: {str(e2)[:200]}")
    if len(gaz) == 0:
        log(city, "social:gazetteer", "warn", "EMPTY gazetteer: mentions can only be placed by NER + geocoding, "
                                              "which locates far fewer; this city's social layer is degraded")
    prov["gazetteer"] = dict(gmeta, names=int(len(gaz)))
    prov["outside_places"] = dict(available=bool(outside_ok), n_names=len(outside), source=gmeta.get("source"))
    gaz_fp = hashlib.sha1("|".join(sorted(gaz["key"])).encode()).hexdigest()[:12] if len(gaz) else "empty"

    # ---- mentions (v6.1.1): text documents and geotagged documents are resolved and checkpointed separately --------
    # Text documents need the gazetteer, NER and the geocoder (hours for a large city); geotagged ones carry their
    # own coordinates. Keyed on the documents themselves, and frozen only when every name lookup was done, so the
    # per-run geocoder cap limits one session, never the result. A new photo no longer repeats the NER of a city.
    geo_docs, text_docs = ds.split_documents(docs)
    lang = cfg.get("lang", "en")
    _sent = lambda: (clients["sentiment_for"](lang) if callable(clients.get("sentiment_for")) else clients.get("sentiment"))
    common = [k_grid, cfg["bounds"], lang, prereg["social"].get("outside_places_buffer_km"), ds.self_names(cfg),
              ds.RESOLVE_RULES_VERSION, ds.LOCATION_LATTICE_DEG, ds.GEOCODE_RULES_VERSION,
              sorted(outside) if outside_ok else "outside-unavailable", gaz_fp]

    def _text_mentions():
        old = _mentions_from_v61(st, cfg, wide, sources, text_docs, common, city, log)
        if old is not None:
            return old
        geocoder = make_geocoder(cfg, cache_root) if clients.get("use_nominatim", True) else None
        ner = clients["ner_for"](lang) if callable(clients.get("ner_for")) else clients.get("ner")
        ginfo = {}
        m = ds.resolve_mentions(text_docs, gaz, cfg, cfg["bounds"], ner=ner, geocoder=geocoder,
                                max_geocode=clients.get("max_geocode", 150), log=log, city=city, exclude=outside,
                                cache_path=os.path.join(cache_root, "geocode_cache.json"), info=ginfo,
                                report_concentration=False)
        ginfo["ner_geocoding"] = bool(ner is not None and geocoder is not None)
        return ds.score_emotion(m, _sent(), lang=lang), len(gaz), ginfo
    k_text = _h("text1", ds.documents_fingerprint(text_docs), *common)
    m_text, n_gaz, ginfo = st.get(f"textmentions_{k_text}", _text_mentions, final=lambda v: bool(v[2].get("complete", True)))
    k_nat = _h("native1", ds.documents_fingerprint(geo_docs), cfg["bounds"], lang)
    m_native = st.get(f"nativementions_{k_nat}",
                      lambda: ds.score_emotion(ds.resolve_mentions(geo_docs, None, cfg, cfg["bounds"]), _sent(), lang=lang),
                      quiet=True)
    parts = [f_ for f_ in (m_native, m_text) if f_ is not None and len(f_)]
    mentions = (pd.concat(parts, ignore_index=True).drop_duplicates(["source", "doc_id", "place"]).reset_index(drop=True)
                if parts else m_text)
    log(city, "social:mentions", "ok", f"{len(mentions)} mentions: {len(m_native)} from geotagged documents, "
                                       f"{len(m_text)} from place names in text"
                                       + (" (name lookups reused from the v6.1 acquisition)" if ginfo.get("migrated_from") else ""))
    _msg, _bad = ds.concentration_message(mentions)
    if len(mentions):
        log(city, "social:concentration", "warn" if _bad else "info", _msg)
    prov["geocoding"] = ginfo
    if not ginfo.get("complete", True):
        pending.append(f"place names: {ginfo.get('lookups_capped', 0)} lookups of {ginfo.get('names_capped', 0)} names "
                       f"not done, {ginfo.get('lookups_failed', 0)} failed")
    want_ner = clients.get("want_ner_geocoding", clients.get("use_nominatim", True))
    if want_ner and not ginfo.get("ner_geocoding", True):
        log(city, "social:places", "warn", "NER + geocoding is off (no NER model or Nominatim unreachable): only "
                                           "gazetteer names are placed. Re-run the acquisition when both are available")
        pending.append("NER + geocoding was not available")
    ginfo["ner_geocoding_wanted"] = bool(want_ner)
    prov["acquisition"] = dict(complete=not pending, pending=pending, rules=ACQUISITION_RULES)
    log(city, "acquire:complete", "ok" if not pending else "warn",
        "every source answered and every place name was looked up" if not pending else
        "INCOMPLETE, re-run the acquisition for this city before analysing it: " + " | ".join(pending))
    prov["mention_concentration"] = ds.mention_concentration(mentions)
    prov["signal"] = ds.signal_composition(mentions)
    t0, t1 = ds.window_bounds(cfg["event_date"], sp["window_days"])
    in_primary = (lambda m: m[pd.to_datetime(m["time_utc"], utc=True).between(pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC"))]
                  if len(m) else m)
    m_primary = in_primary(mentions)
    docs.to_csv(os.path.join(out, "social_documents.csv.gz"), index=False)
    mentions.to_csv(os.path.join(out, "social_mentions.csv.gz"), index=False)
    channels, cstats = ds.social_channels(G, df, m_primary, sp["kde_bandwidth_m"], sp["min_source_mentions"])
    prov["social"] = dict(documents_wide_window=len(docs), gazetteer_names=n_gaz, primary=cstats,
                          sources=sstatus.to_dict("records"))
    if cstats.get("mentions", 0) < 10:
        log(city, "social", "warn", f"sparse social layer: {cstats.get('mentions', 0)} located mentions in the primary window")
    # Pre-registered, label-free localisation rule (v5.5): decided from the mentions alone, before any label
    # is looked at, so selecting cities on it cannot bias the gradient (selecting on R0 gain would).
    ap_ = prereg.get("analysis_plan") or {}
    el = ap_.get("localisation_eligibility") or dict(min_mentions=100, min_effective_locations=10, max_top_place_share=0.4)
    ccp = ds.mention_concentration(m_primary)
    eligible = bool(ccp["n_mentions"] >= el["min_mentions"] and ccp["effective_locations"] >= el["min_effective_locations"]
                    and (ccp["top_share"] if ccp["top_share"] is not None else 1.0) <= el["max_top_place_share"])
    prov["localisation"] = dict(ccp, eligible=eligible, rule=el)
    prov["signal_primary"] = ds.signal_composition(m_primary)
    log(city, "social:localisation", "ok" if eligible else "warn",
        f"{'eligible' if eligible else 'NOT eligible'} for the pooled gradient analysis: {ccp['n_mentions']} mentions "
        f"in the primary window, {ccp['effective_locations']} effective locations, top place {ccp['top_place']} "
        f"= {ccp['top_share']} (rule: >= {el['min_mentions']}, >= {el['min_effective_locations']}, <= {el['max_top_place_share']})")
    log(city, "social:signal", "info", f"primary-window layer is a {prov['signal_primary']['signal_type']} "
                                       f"{prov['signal_primary']['shares']}; report it under that name")

    # population (exposure) layer for the density placebo/control: fetched here, with the other network data
    dens, pop_meta, pop_err = None, None, None
    if P.get("placebo", True) and (prereg.get("analysis_plan") or {}).get("density_placebo", True):
        try:
            k_pop = _h("pop1", k_grid, str(cfg["event_date"])[:4])
            dens, pop_meta = st.get(f"population_{k_pop}", lambda: ds.population_layer(city, cfg, G, df, log))
            dens = np.asarray(dens, float)
        except Exception as e:  # noqa: BLE001
            pop_err = f"population layer unavailable: {str(e)[:250]}"
            log(city, "exposure:population", "warn", pop_err)
    return dict(city=city, cfg=cfg, prov=prov, G=G, df=df, phys=phys, y=y, y_sens=y_sens, label_valid=label_valid,
                label_source=label_source, eff_source=eff_source, gt_tier=gt_tier, channels=channels, cstats=cstats,
                m_primary=m_primary, mentions=mentions, k_grid=k_grid, dens=dens, pop_meta=pop_meta, pop_err=pop_err,
                prereg_sha256=ph.prereg_hash(prereg), pipeline_version=PIPELINE_VERSION,
                toponym_rules=ds.TOPONYM_RULES_VERSION,          # the toponym rule was applied while resolving mentions
                acquisition_rules=ACQUISITION_RULES, acquisition_complete=not pending,
                acquired_utc=dt.datetime.utcnow().isoformat(timespec="seconds"))


def choose_cv_tile(cvp, corr_range_m, xy, y):
    """Pre-registered spatial-block size (v6): the block should be at least as large as the range of the label's
    spatial autocorrelation (Roberts et al. 2017), so the tile is the correlogram range minus the buffer, rounded
    up to 500 m, within [tile_m, tile_max_m]. If that leaves fewer than min_positive_tiles_per_fold x k tiles
    containing flooded cells, the tile is stepped down by 500 m (never below tile_m)."""
    base = float(cvp["tile_m"])
    if cvp.get("tile_rule") != "correlogram":
        return base, "fixed tile (pre-registered)"
    tmax = float(cvp.get("tile_max_m", 4000))
    need = int(cvp.get("min_positive_tiles_per_fold", 3)) * int(cvp["k_folds"])
    if np.isfinite(corr_range_m):
        target = min(max(base, corr_range_m - float(cvp["buffer_m"])), tmax)
        why = f"correlogram range {corr_range_m:.0f} m"
    else:
        target, why = tmax, "autocorrelation never fell below 0.1 within the correlogram's range: maximum tile"
    target = float(np.ceil(target / 500.0) * 500.0)
    cand = target
    while cand >= base:
        n_pos = len(np.unique(sc.tile_ids(xy[:, 0], xy[:, 1], cand)[np.asarray(y) > 0]))
        if n_pos >= need:
            return cand, why + (f"; stepped down from {target:.0f} m to keep >= {need} flooded tiles" if cand < target else "")
        cand -= 500.0
    return base, why + f"; fewer than {need} flooded tiles even at larger sizes: default tile"


def analyse_city(ctx, prereg, profile, out_root, cache_root, log):
    """Stage 5 onwards: analysis table, ladders, lens, sensitivity, density placebo, maps. No network."""
    P = PROFILES[profile]
    city, cfg, prov = ctx["city"], copy.deepcopy(ctx["cfg"]), dict(ctx["prov"])
    out = os.path.join(out_root, city)
    os.makedirs(out, exist_ok=True)
    st = Stage(os.path.join(cache_root, f"{city}_{cfg['event_date']}"), log, city)
    G, df, phys, y, y_sens = ctx["G"], ctx["df"], ctx["phys"], ctx["y"], ctx["y_sens"]
    label_valid, label_source, eff_source, gt_tier = ctx["label_valid"], ctx["label_source"], ctx["eff_source"], ctx["gt_tier"]
    channels, cstats, m_primary, mentions = ctx["channels"], ctx["cstats"], ctx["m_primary"], ctx["mentions"]
    sp = prereg["social"]
    # Toponym rule (ds.refine_gazetteer_mentions): a subset filter on the stored mentions that were placed from a
    # name in the text (gazetteer and, since t4, NER), applied before anything else, so the social layer, the
    # localisation rule and every downstream result use only complete place names. Label-free; no network. It
    # corrects the NER defect of v6.0 inputs, but NOT their truncated geocoding or missing sources: those need a
    # new acquisition, which is why run_all refuses inputs acquired under older rules unless told otherwise.
    acq = prov.get("acquisition") or {}
    if ctx.get("acquisition_rules") != ACQUISITION_RULES:
        log(city, "analyse", "warn", f"inputs were acquired under older acquisition rules ({ctx.get('acquisition_rules') or 'v6.0'}; "
                                     f"current {ACQUISITION_RULES}): geocoding may be truncated and failed sources were "
                                     f"never retried. Re-acquire this city before using its results")
    elif not acq.get("complete", True):
        log(city, "analyse", "warn", "the acquisition of this city is INCOMPLETE (" + " | ".join(acq.get("pending", []))[:300]
                                     + "); its results are provisional")
    prov["acquisition_status"] = dict(rules=ctx.get("acquisition_rules") or "v6.0", current_rules=ACQUISITION_RULES,
                                      complete=bool(ctx.get("acquisition_rules") == ACQUISITION_RULES and acq.get("complete", True)),
                                      pending=acq.get("pending", []))
    if ctx.get("toponym_rules") != ds.TOPONYM_RULES_VERSION:
        n_raw = len(mentions)
        prov["mention_concentration_g2"] = prov.get("mention_concentration")
        prov["localisation_g2"] = prov.get("localisation")
        mentions, tstats = ds.refine_gazetteer_mentions(mentions, city, cfg, log)
        prov["toponyms"] = tstats
        t0, t1 = ds.window_bounds(cfg["event_date"], sp["window_days"])
        m_primary = (mentions[pd.to_datetime(mentions["time_utc"], utc=True).between(pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC"))]
                     if len(mentions) else mentions)
        channels, cstats = ds.social_channels(G, ctx["df"], m_primary, sp["kde_bandwidth_m"], sp["min_source_mentions"])
        prov["mention_concentration"] = ds.mention_concentration(mentions)
        prov["social"] = dict(prov.get("social") or {}, primary=cstats, toponym_rules=ds.TOPONYM_RULES_VERSION)
        ap_ = prereg.get("analysis_plan") or {}
        el = ap_.get("localisation_eligibility") or dict(min_mentions=100, min_effective_locations=10, max_top_place_share=0.4)
        ccp = ds.mention_concentration(m_primary)
        eligible = bool(ccp["n_mentions"] >= el["min_mentions"] and ccp["effective_locations"] >= el["min_effective_locations"]
                        and (ccp["top_share"] if ccp["top_share"] is not None else 1.0) <= el["max_top_place_share"])
        prov["localisation"] = dict(ccp, eligible=eligible, rule=el, toponym_rules=ds.TOPONYM_RULES_VERSION)
        prov["signal_primary"] = ds.signal_composition(m_primary)
        log(city, "social:localisation", "ok" if eligible else "warn",
            f"[rule {ds.TOPONYM_RULES_VERSION}] {'eligible' if eligible else 'NOT eligible'} for the pooled gradient analysis: "
            f"{ccp['n_mentions']} mentions in the primary window ({n_raw} before refinement, all windows), "
            f"{ccp['effective_locations']} effective locations, top place {ccp['top_place']} = {ccp['top_share']} "
            f"(rule: >= {el['min_mentions']}, >= {el['min_effective_locations']}, <= {el['max_top_place_share']})")
        mentions.to_csv(os.path.join(out, "social_mentions.csv.gz"), index=False)
    if ctx.get("prereg_sha256") and ctx["prereg_sha256"] != ph.prereg_hash(prereg):
        log(city, "analyse", "warn", f"inputs were acquired under pre-registration {ctx['prereg_sha256'][:8]}, analysed "
                                     f"under {ph.prereg_hash(prereg)[:8]}; re-acquire if the social or label rules changed")
    prov["analysed_utc"] = dt.datetime.utcnow().isoformat(timespec="seconds")
    prov["acquired_utc"] = ctx.get("acquired_utc")
    if "signal_primary" not in prov:
        prov["signal_primary"] = ds.signal_composition(m_primary)
    prov["label_caveat"] = cfg.get("label_caveat")
    # v6.1, label-free: a layer with fewer located mentions than this cannot be evaluated at all (Carlisle had 2 and
    # York 5 in the v6.0 run; their null-centred estimates were noise). The city stays in the pre-registered
    # confirmatory set; the flag defines a sensitivity set and is shown next to every result of that city.
    n_prim = int((prov.get("localisation") or {}).get("n_mentions") or 0)
    min_ev = int((prereg.get("analysis_plan") or {}).get("min_evaluable_mentions", MIN_EVALUABLE_MENTIONS))
    prov["evaluable_social_layer"] = bool(n_prim >= min_ev)
    if not prov["evaluable_social_layer"]:
        log(city, "social", "warn", f"NO EVALUABLE SOCIAL LAYER: {n_prim} located mentions in the primary window "
                                    f"(< {min_ev}). Every social effect of this city is noise around zero; it is "
                                    f"excluded from the 'evaluable' sensitivity set and flagged in T1/T4")

    # 5. analysis table ------------------------------------------------------
    data = pd.concat([df.reset_index(drop=True), phys.reset_index(drop=True)], axis=1)
    data["flooded"] = y
    for k, v in channels.items():
        data[k] = v
    # sanitise: inf -> NaN -> city median (label-free, so no leakage); constant columns are kept but logged
    for col in list(phys.columns) + list(channels):
        v = pd.to_numeric(data[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
        n_bad = int(v.isna().sum())
        if n_bad:
            med = v.median()
            v = v.fillna(0.0 if not np.isfinite(med) else med)
            log(city, "sanitise", "warn" if n_bad > 0.05 * len(v) else "info", f"{col}: {n_bad} non-finite values replaced by median")
        if v.nunique() <= 1:
            log(city, "sanitise", "info", f"{col}: constant within the city")
        data[col] = v.astype(float)
    prov["sanitised_columns"] = [c for c in list(phys.columns) + list(channels)]
    # Cells the label cannot judge (unmapped, unobservable) and permanent water are excluded, not scored
    # as dry: otherwise terrain/water predictors win points for rediscovering the label's masks.
    keep = label_valid.copy()
    thr = prereg["label"].get("exclude_permanent_water_occ")
    if thr is not None and "jrc_occ" in data:
        perm = data["jrc_occ"].to_numpy(float) >= thr
        keep &= ~perm
        log(city, "exclude", "info", f"{int(perm.sum()):,} permanent-water cells (JRC occurrence >= {thr}%) excluded")
    log(city, "exclude", "ok" if keep.mean() > 0.5 else "warn",
        f"{int((~keep).sum()):,} of {len(keep):,} cells excluded ({(~keep).mean():.1%}); "
        f"{int(y[keep].sum())} flooded among {int(keep.sum()):,} analysed")
    prov.update(cells_analysed=int(keep.sum()), cells_excluded=int((~keep).sum()))
    data_full, df_full = data, df
    data = data_full[keep].reset_index(drop=True)
    y = y[keep]
    y_sens = y_sens[keep] if y_sens is not None else None
    fp = sc.data_fingerprint(data, list(phys.columns) + list(channels))
    prov["data_fingerprint"] = fp
    crange = np.nan
    try:
        cg, crange = sc.label_correlogram(data[["x_m", "y_m"]].to_numpy(float), y, seed=prereg["cv"]["seed"])
        cg.to_csv(os.path.join(out, "label_correlogram.csv"), index=False)
        prov["label_corr_range_m"] = crange
    except Exception as e:  # noqa: BLE001
        log(city, "cv:correlogram", "warn", f"correlogram failed: {e}; the default tile is used")
    tile_m, tile_note = choose_cv_tile(prereg["cv"], crange, data[["x_m", "y_m"]].to_numpy(float), y)
    prov.update(cv_tile_m=tile_m, cv_tile_rule=tile_note)
    log(city, "cv:blocks", "ok", f"label autocorrelation < 0.1 by {crange:.0f} m -> CV tile {tile_m:.0f} m + buffer "
                                 f"{prereg['cv']['buffer_m']:.0f} m ({tile_note})")
    meta = (data["row"].to_numpy(), data["col"].to_numpy(), G.nr, G.nc)
    cfgL = sc.LadderConfig(k_folds=prereg["cv"]["k_folds"], tile_m=tile_m, buffer_m=prereg["cv"]["buffer_m"],
                           inner_k=prereg["cv"]["inner_k"], seed=prereg["cv"]["seed"], n_boot=P["n_boot"], n_null=P["n_null"],
                           null_min_shift_m=prereg["inference"]["null_min_shift_m"],
                           grid_m=int(cfg.get("grid_m", prereg["grid_m"])))
    gg = (prereg.get("inference") or {}).get("gated_grid") or {}
    if gg:
        cfgL = dataclasses.replace(cfgL, gated_alphas=tuple(gg.get("alphas", sc.GATED_GRID_DEFAULT[0])),
                                   gated_taus=tuple(gg.get("taus", sc.GATED_GRID_DEFAULT[1])))
    spec = sc.ModelSpec(kind=prereg["model"]["kind"], seed=prereg["cv"]["seed"],
                        xgb_params={**prereg["model"]["params"], "n_estimators": P["n_estimators"], "tree_method": "hist", "n_jobs": -1})
    kcv = _h(dataclasses.asdict(cfgL), dataclasses.asdict(spec))       # every cached result is tied to its CV design
    results = {}
    for ordering in prereg["orderings"]:
        ladder = build_ladder(prereg, ordering, set(phys.columns), eff_source, log, city)
        t = time.time()
        res = st.get(f"ladder_{ordering}_{profile}_{fp}_{STAGE_CODE['analysis']}_{kcv}",
                     lambda: sc.run_ladder(data, ladder, ["S_mentions"], spec, cfgL, meta,
                                           log=lambda s: log(city, f"rung:{ordering}", "info", s.strip()),
                                           rung_cache=st.rung_cache(ordering)))
        res = dict(res)
        res = _augment(res, prereg, log, city, ordering)
        rob = res["gradient"][res["gradient"]["role"] == "robust_excl_R0"]
        if len(rob):
            bad = rob[rob["slope_ci_high"] < 0]["metric"].tolist()
            log(city, f"gradient:{ordering}", "info", f"without R0: {len(bad)} of {len(rob)} primary slopes have a "
                                                        f"95% CI entirely below 0 {bad}")
        gp = res.get("gated_params")
        if gp is not None and len(gp):
            amax, tmin = max(cfgL.gated_alphas), min(cfgL.gated_taus)
            edge = float(((gp["alpha"] == amax) | ((gp["tau"] == tmin) & (gp["alpha"] > 0))).mean())
            if edge > 0.3:
                log(city, f"gated:{ordering}", "warn", f"{edge:.0%} of fold fits chose the edge of the gate grid "
                                                         f"(alpha={amax} or tau={tmin}); see the gated_wide_grid "
                                                         f"sensitivity variant")
        results[ordering] = res
        save_tables(out, ordering, res)
        eff = res.get("effects")
        if eff is not None and len(eff):
            top = eff[eff["rung"] == eff["rung"].iloc[-1]]
            prov[f"top_rung_{ordering}"] = {r_.metric: dict(estimate=r_.estimate, ci95=[r_.ci95_low, r_.ci95_high],
                                                         verdict=r_.verdict) for r_ in top.itertuples()}
            prov[f"saturation_rung_{ordering}"] = sc.saturation_rung(eff)
            log(city, f"effects:{ordering}", "ok", "top rung: " + "; ".join(
                f"{r_.metric} {r_.estimate:+.4f} [{r_.ci95_low:+.4f}, {r_.ci95_high:+.4f}] {r_.verdict}" for r_ in top.itertuples())
                + f" | social gain saturated from: {prov[f'saturation_rung_{ordering}']}")
        log(city, f"ladder:{ordering}", "ok", f"{len(ladder)} rungs in {(time.time() - t) / 60:.1f} min")

    full_rung = build_ladder(prereg, "A_terrain_first", set(phys.columns), eff_source, log, city)[-1]
    fd = sc.fold_diagnostics(results["A_terrain_first"], y)
    fd.to_csv(os.path.join(out, "fold_diagnostics.csv"), index=False)
    prov["fold_prevalence_range"] = [round(float(fd["prevalence"].min()), 4), round(float(fd["prevalence"].max()), 4)]
    if fd["prevalence"].max() - fd["prevalence"].min() > 0.25:
        log(city, "folds", "warn", f"fold prevalence ranges {fd['prevalence'].min():.1%}-{fd['prevalence'].max():.1%}: "
                                   f"per-fold AP partly reflects fold base rates; report fold_diagnostics.csv")

    # 6. emotion lens: every social channel at the most complete rung ---------------
    lens_rows = []
    if P["emotion_lens"]:
        chans = [c for c in data.columns if c.startswith("S_")]
        combos = [[c] for c in chans]
        core = [c for c in ["S_mentions", "S_negative", "S_distress"] if c in chans]
        if len(core) > 1:
            combos.append(core)
        for combo in combos:
            name = "+".join(combo)
            r = st.get(f"lens_{name}_{profile}_{fp}_{STAGE_CODE['analysis']}_{kcv}",
                        lambda: sc.run_ladder(data, [full_rung], combo, spec, cfgL, meta, log=lambda s: None,
                                              rung_cache=st.rung_cache("lens")))
            # the gated operator reranks with ONE channel: for a combination that is the first one listed
            lens_rows.append(r["summary"].assign(channel=name, gated_uses=combo[0]))
            pd.concat(lens_rows).to_csv(os.path.join(out, "emotion_lens.csv"), index=False)   # flush after each channel
        log(city, "emotion_lens", "ok", f"{len(combos)} channel sets at rung {full_rung[0]}")

    # 7. sensitivity ----------------------------------------------------------------
    sens_rows = []
    if P["sensitivity"]:
        variants = []
        ch_bw, _ = ds.social_channels(G, df_full, m_primary, sp["sensitivity_bandwidth_m"], 10**9)
        variants.append(("bandwidth_1000m", data.assign(S_mentions=np.asarray(ch_bw["S_mentions"])[keep])))
        ch_w, _ = ds.social_channels(G, df_full, mentions, sp["kde_bandwidth_m"], 10**9)
        variants.append(("window_minus3_plus3", data.assign(S_mentions=np.asarray(ch_w["S_mentions"])[keep])))
        if len(m_primary) and m_primary["source"].isin(ds.PHOTO_SOURCES).any():
            # timeliness check (v6): photos are often uploaded after the event, so the layer is rebuilt without them
            ch_np, _ = ds.social_channels(G, df_full, m_primary[~m_primary["source"].isin(ds.PHOTO_SOURCES)],
                                          sp["kde_bandwidth_m"], 10**9)
            variants.append(("without_photos", data.assign(S_mentions=np.asarray(ch_np["S_mentions"])[keep])))
        if y_sens is not None and y_sens.sum() >= prereg["label"]["min_positive_cells"]:
            variants.append(("label_point_buffer_100m", data.assign(flooded=y_sens)))
        # the gate is the only thing this variant changes, so early fusion and legacy ADR are not refitted
        cfgW = dataclasses.replace(cfgL, gated_alphas=sc.GATED_GRID_WIDE[0], gated_taus=sc.GATED_GRID_WIDE[1],
                                   run_early_fusion=False, run_legacy_adr=False)
        variants.append(("gated_wide_grid", data, cfgW))
        # learner family (v6): the whole top-rung comparison refitted with a penalised logistic regression, so the
        # verdicts are not an artefact of gradient boosting
        variants.append(("learner_logistic", data, cfgL, dataclasses.replace(spec, kind="logistic")))
        for v in variants:
            name, d = v[0], v[1]
            cfgV = v[2] if len(v) > 2 else cfgL
            specV = v[3] if len(v) > 3 else spec
            fpd = sc.data_fingerprint(d, list(full_rung[1]) + ["S_mentions"])
            r = st.get(f"sens_{name}_{profile}_{fpd}_{STAGE_CODE['analysis']}_{kcv}_{specV.kind}",
                        lambda: sc.run_ladder(d, [full_rung], ["S_mentions"], specV, cfgV, meta, log=lambda s: None,
                                              rung_cache=st.rung_cache("sensitivity")))
            row = r["summary"].assign(variant=name)
            gpv = r.get("gated_params")
            if gpv is not None and len(gpv):
                row = row.assign(gate_alpha_median=float(gpv["alpha"].median()),
                                 gate_tau0_share=float((gpv["tau"] == 0).mean()),
                                 gate_off_share=float((gpv["alpha"] == 0).mean()))
            sens_rows.append(row)
            pd.concat(sens_rows).to_csv(os.path.join(out, "sensitivity.csv"), index=False)    # flush after each variant
        log(city, "sensitivity", "ok", f"{len(variants)} variants")

    # 7b. exposure placebo and control (v5.5) -----------------------------------------
    placebo = None
    if P.get("placebo", True) and (prereg.get("analysis_plan") or {}).get("density_placebo", True):
        try:
            if ctx.get("dens") is None:
                raise RuntimeError(ctx.get("pop_err") or "population layer was not acquired")
            dens, pop_meta = ctx["dens"], ctx["pop_meta"]
            prov["population"] = pop_meta
            dens = np.asarray(dens, float)
            smooth = _smooth_density(dens, df_full, G, sp["kde_bandwidth_m"])
            data_p = data.assign(pop_log=np.log1p(dens[keep]), S_placebo_pop=smooth[keep])
            rho = float(pd.Series(data_p["S_placebo_pop"]).corr(data["S_mentions"], method="spearman"))
            prov["social_population_spearman"] = rho
            log(city, "placebo", "info", f"social layer vs population-density layer: Spearman {rho:.2f}")
            cfgP = dataclasses.replace(cfgL, run_early_fusion=False, run_legacy_adr=False)
            ladA = build_ladder(prereg, "A_terrain_first", set(phys.columns), eff_source, log, city)
            fpp = sc.data_fingerprint(data_p, list(phys.columns) + ["S_placebo_pop"])
            rp = st.get(f"placebo_pop_{profile}_{fpp}_{STAGE_CODE['analysis']}_{kcv}",
                        lambda: sc.run_ladder(data_p, ladA, ["S_placebo_pop"], spec, cfgP, meta,
                                              log=lambda s_: log(city, "rung:placebo", "info", s_.strip()),
                                              rung_cache=st.rung_cache("placebo")))
            rp = _augment(dict(rp), prereg, log, city, "placebo_population_A")
            save_tables(out, "placebo_population_A", rp)
            # control: the real social layer's gain when population density is part of the physical model
            ctrl = [(full_rung[0] + "+population", list(full_rung[1]) + ["pop_log"])]
            fpc = sc.data_fingerprint(data_p, ctrl[0][1] + ["S_mentions"])
            rc = st.get(f"control_pop_{profile}_{fpc}_{STAGE_CODE['analysis']}_{kcv}",
                        lambda: sc.run_ladder(data_p, ctrl, ["S_mentions"], spec, cfgP, meta, log=lambda s_: None,
                                              rung_cache=st.rung_cache("placebo")))
            rc = dict(rc)
            rc["effects"] = sc.effect_table(rc, sesoi=(prereg.get("analysis_plan") or {}).get("sesoi"))
            rc["effects"].to_csv(os.path.join(out, "control_population_effects.csv"), index=False)
            sens_rows.append(rc["summary"].assign(variant="control_population"))
            pd.concat(sens_rows).to_csv(os.path.join(out, "sensitivity.csv"), index=False)
            placebo = dict(summary=rp["summary"], gradient=rp["gradient"], effects=rp["effects"],
                           control_summary=rc["summary"], control_effects=rc["effects"], spearman_social_pop=rho)
            log(city, "placebo", "ok", "population-density placebo ladder and population control done")
        except Exception as e:  # noqa: BLE001
            log(city, "placebo", "warn", f"density placebo/control skipped: {str(e)[:300]}")

    # 8. maps ---------------------------------------------------------------------------
    try:
        make_city_maps(city, G, data, results["A_terrain_first"], out)
    except Exception as e:  # noqa: BLE001
        log(city, "figures:maps", "warn", str(e))
    prov["pipeline_version"] = PIPELINE_VERSION
    return dict(city=city, cfg=cfg, results=results, lens=lens_rows, sens=sens_rows, prov=prov, data_cols=list(data.columns),
                placebo=placebo,
                positives=int(y.sum()), prevalence=float(y.mean()), label_source=label_source, social=cstats,
                cells_analysed=int(len(data)), gt_tier=gt_tier, effective_label_source=eff_source)
