"""
saturation_core.py — analysis engine for the saturation-gradient paper.

Pure functions only: no Earth Engine, no network, no file-format assumptions.
The Colab notebook embeds this file verbatim, so the code that was unit-tested
is the code that produces paper numbers.

Design decisions (each one fixes a defect found in the audit):
  * Every reported score is OUT-OF-FOLD under buffered spatial block CV.
    Nothing is ever scored on cells the model was trained on.
  * Fusion operators that consume the physical score R are trained on
    *nested* out-of-fold R, so the stacker never sees in-sample R.
  * The entropy gate adjusts UNCERTAIN cells (H(R) > tau), and its strength
    alpha is selected on training tiles from a grid that includes alpha = 0.
  * Social marginal information is estimated as a held-out log-loss reduction
    between two identically-recalibrated stackers: g(R) vs g(R, S)  (nats).
  * Nulls use toroidal shifts of the real social raster (preserves its spatial
    autocorrelation, destroys alignment with floods). No synthetic data.
  * Uncertainty uses a spatial block bootstrap over tiles, paired across rungs
    and operators.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import rankdata, spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

EPS = 1e-6
HEADROOM_FLOOR = 0.05   # headroom 1-AP is floored so near-perfect physical models do not explode the ratio


# ---------------------------------------------------------------- metrics
def safe_ap(y, s):
    y = np.asarray(y)
    return float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def safe_auc(y, s):
    y = np.asarray(y)
    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def logloss_vec(y, p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def recall_at_k(y, s, k_pct):
    y = np.asarray(y)
    k = max(int(round(len(y) * k_pct / 100.0)), 1)
    top = np.argsort(-np.asarray(s), kind="mergesort")[:k]
    return float(y[top].sum() / max(y.sum(), 1))


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


def bernoulli_entropy_bits(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return -(p * np.log2(p) + (1 - p) * np.log2(1 - p))


# ---------------------------------------------------------- spatial folds
def tile_ids(x_m, y_m, tile_m):
    """Regular square tiles in a metric CRS."""
    tx = np.floor(np.asarray(x_m) / tile_m).astype(np.int64)
    ty = np.floor(np.asarray(y_m) / tile_m).astype(np.int64)
    return tx * 1_000_003 + ty


def assign_folds(tiles, y, k, seed):
    """Greedy balance: tiles sorted by positives go to the fold with fewest
    positives (ties -> fewest cells). Guarantees positives spread over folds
    whenever #positive tiles >= k."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"t": tiles, "y": y})
    agg = df.groupby("t")["y"].agg(["sum", "size"]).reset_index()
    agg["r"] = rng.random(len(agg))
    agg = agg.sort_values(["sum", "r"], ascending=[False, True])
    pos = np.zeros(k)
    size = np.zeros(k)
    fold_of = {}
    for t, s, n in zip(agg["t"], agg["sum"], agg["size"]):
        f = int(np.lexsort((size, pos))[0])
        fold_of[t] = f
        pos[f] += s
        size[f] += n
    return np.array([fold_of[t] for t in tiles])


def buffered_train_index(xy, train_idx, test_idx, buffer_m):
    """Drop training cells within buffer_m of any test cell."""
    if buffer_m <= 0 or len(test_idx) == 0:
        return train_idx
    d, _ = cKDTree(xy[test_idx]).query(xy[train_idx], k=1, distance_upper_bound=buffer_m + 1e-6)
    return train_idx[~np.isfinite(d)]


# ----------------------------------------------------------------- models
@dataclass
class ModelSpec:
    kind: str = "xgb"                   # "xgb" | "logistic"
    seed: int = 42
    xgb_params: dict = field(default_factory=lambda: dict(
        n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.8,
        colsample_bytree=0.8, min_child_weight=5, reg_lambda=1.0,
        tree_method="hist", n_jobs=-1))


class ConstantModel:
    """Physical model with no features: predicts training prevalence (rung 0)."""
    def fit(self, X, y):
        self.p = float(np.clip(np.mean(y), EPS, 1 - EPS)); return self

    def predict_proba(self, X):
        n = len(X)
        return np.c_[np.full(n, 1 - self.p), np.full(n, self.p)]


def make_model(spec: ModelSpec, n_features: int):
    if n_features == 0:
        return ConstantModel()
    if spec.kind == "logistic":
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0))
    import xgboost as xgb
    # Unweighted log-loss objective keeps probabilities approximately
    # calibrated, which the entropy gate and the log-loss CMI estimate need.
    return xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss",
                             random_state=spec.seed, **spec.xgb_params)


def fit_predict(spec, Xtr, ytr, Xte):
    if ytr.sum() == 0:
        return np.full(len(Xte), EPS)
    m = make_model(spec, Xtr.shape[1])
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


# ------------------------------------------------------ fusion operators
def _zfit(a):
    mu, sd = float(np.mean(a)), float(np.std(a))
    return mu, (sd if sd > 1e-12 else 1.0)


def stack_features(R, S_list, use_social):
    z = logit(R)[:, None]
    if not use_social:
        return z
    cols = [z]
    for S in S_list:
        cols += [S[:, None], (z[:, 0] * S)[:, None]]
    return np.hstack(cols)


def op_stacked(R_tr, S_tr, y_tr, R_te, S_te, use_social=True, C=1.0):
    """Late fusion by a logistic stacker on [logit R, S, logit R * S].
    With use_social=False this is a pure recalibration of R (the fair
    comparator for the log-loss information estimate)."""
    S_tr_z, S_te_z = [], []
    for a, b in zip(S_tr, S_te):
        mu, sd = _zfit(a)
        S_tr_z.append((a - mu) / sd)
        S_te_z.append((b - mu) / sd)
    Ftr = stack_features(R_tr, S_tr_z, use_social)
    Fte = stack_features(R_te, S_te_z, use_social)
    if y_tr.sum() == 0:
        return np.full(len(R_te), EPS)
    lr = LogisticRegression(C=C, max_iter=3000)
    lr.fit(Ftr, y_tr)
    return lr.predict_proba(Fte)[:, 1]


def gated_score(R, S_z, alpha, tau):
    g = (bernoulli_entropy_bits(R) > tau).astype(float)   # UNCERTAIN cells only
    return sigmoid(logit(R) + alpha * g * S_z)


def op_gated(R_tr, S_tr, y_tr, R_te, S_te, alphas=(0.0, 0.25, 0.5, 1.0, 2.0),
             taus=(0.3, 0.5, 0.7)):
    """Corrected entropy-gated reranking (ADR). (alpha, tau) chosen on training
    tiles by AP; alpha = 0 is always admissible, so on training data it can
    never underperform R. Returns scores and chosen parameters."""
    mu, sd = _zfit(S_tr)
    Str, Ste = (S_tr - mu) / sd, (S_te - mu) / sd
    best = (0.0, taus[0], safe_ap(y_tr, R_tr))
    for a in alphas:
        if a == 0:
            continue
        for t in taus:
            ap = safe_ap(y_tr, gated_score(R_tr, Str, a, t))
            if np.isfinite(ap) and ap > best[2] + 1e-9:
                best = (a, t, ap)
    return gated_score(R_te, Ste, best[0], best[1]), {"alpha": best[0], "tau": best[1]}


def op_adr_legacy(R, S, alpha=1.5, tau=0.5):
    """Verbatim re-implementation of the draft-paper lens (gai notebook,
    Block 15, default rank_multiplicative). Kept ONLY to document the
    correction; applied to out-of-fold R. Note the two defects preserved:
    rank(-S) gives the largest multiplier to cells with the LEAST social
    signal, and scores are min-max rescaled afterwards."""
    def _norm(x):
        x = np.nan_to_num(np.asarray(x, float)); lo, hi = x.min(), x.max()
        return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)
    risk = _norm(sigmoid(4.0 * (R - 0.5)))
    if np.ptp(S) < 0.05 or np.ptp(risk) < 0.05:
        return risk
    mask = (bernoulli_entropy_bits(risk) > tau).astype(float)
    e_rank = rankdata(-S, method="average") / len(S)
    return _norm(risk * np.clip(1.0 + alpha * e_rank * mask, 0.7, 2.0))


# -------------------------------------------------- toroidal spatial null
def toroidal_shift(values, rows, cols, n_rows, n_cols, dr, dc, fill=0.0):
    """Shift a cell attribute on its raster by (dr, dc) with wrap-around.
    Cells outside the study mask receive `fill` (no signal)."""
    ras = np.full((n_rows, n_cols), np.nan)
    ras[rows, cols] = values
    sh = np.roll(np.roll(ras, dr, axis=0), dc, axis=1)
    out = sh[rows, cols]
    return np.where(np.isfinite(out), out, fill)


def sample_shifts(n, n_rows, n_cols, min_shift_cells, seed):
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < n:
        dr, dc = int(rng.integers(0, n_rows)), int(rng.integers(0, n_cols))
        ddr, ddc = min(dr, n_rows - dr), min(dc, n_cols - dc)
        if math.hypot(ddr, ddc) >= min_shift_cells:
            out.append((dr, dc))
    return out


# ----------------------------------------------------------- the ladder
@dataclass
class LadderConfig:
    k_folds: int = 5
    tile_m: float = 2000.0
    buffer_m: float = 500.0
    inner_k: int = 3
    seed: int = 42
    n_boot: int = 500
    n_null: int = 99
    n_null_early: int = 25          # early fusion needs XGBoost refits per null, so fewer shifts
    null_min_shift_m: float = 5000.0
    grid_m: float = 100.0
    top_k_pct: tuple = (1, 5, 10, 20)
    run_early_fusion: bool = True
    run_legacy_adr: bool = True
    # pre-registered gate search grid; a different grid is a separate, labelled robustness analysis
    gated_alphas: tuple = (0.0, 0.25, 0.5, 1.0, 2.0)
    gated_taus: tuple = (0.3, 0.5, 0.7)


GATED_GRID_DEFAULT = ((0.0, 0.25, 0.5, 1.0, 2.0), (0.3, 0.5, 0.7))
GATED_GRID_WIDE = ((0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0), (0.0, 0.1, 0.2, 0.3, 0.5, 0.7))


def _outer_inner(df, feats, S_cols, y, xy, folds, spec, cfg):
    """One physical rung. Returns OOF physical score and, per outer fold,
    what the social operators need (nested OOF R on training cells)."""
    n = len(df)
    X = df[feats].to_numpy(float) if feats else np.zeros((n, 0))
    R = np.full(n, np.nan)
    parts = []
    for f in range(cfg.k_folds):
        te = np.where(folds == f)[0]
        tr = buffered_train_index(xy, np.where(folds != f)[0], te, cfg.buffer_m)
        R[te] = fit_predict(spec, X[tr], y[tr], X[te])
        # nested OOF R on the (buffered) training set, for the stackers
        inner = assign_folds(df["_tile"].to_numpy()[tr], y[tr], cfg.inner_k, cfg.seed + 7 + f)
        R_tr = np.full(len(tr), np.nan)
        for g in range(cfg.inner_k):
            ite = np.where(inner == g)[0]
            itr = buffered_train_index(xy[tr], np.where(inner != g)[0], ite, cfg.buffer_m)
            R_tr[ite] = fit_predict(spec, X[tr][itr], y[tr][itr], X[tr][ite])
        parts.append((tr, te, R_tr))
    return R, parts


def _apply_social_ops(parts, R, S_mat, y, n, cfg, with_gated=True):
    """Stacked(R), Stacked(R,S), Gated for one social layer realisation."""
    P0, P1, PG = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    chosen = []
    for tr, te, R_tr in parts:
        S_tr = [S_mat[tr, j] for j in range(S_mat.shape[1])]
        S_te = [S_mat[te, j] for j in range(S_mat.shape[1])]
        P0[te] = op_stacked(R_tr, S_tr, y[tr], R[te], S_te, use_social=False)
        P1[te] = op_stacked(R_tr, S_tr, y[tr], R[te], S_te, use_social=True)
        if with_gated:
            PG[te], prm = op_gated(R_tr, S_tr[0], y[tr], R[te], S_te[0],
                                   alphas=tuple(getattr(cfg, "gated_alphas", GATED_GRID_DEFAULT[0])),
                                   taus=tuple(getattr(cfg, "gated_taus", GATED_GRID_DEFAULT[1])))
            chosen.append(prm)
    return P0, P1, PG, chosen


def run_rung(df, rung_name, feats, S_cols, spec, cfg, raster_meta=None, log=print):
    """Full evaluation of one physical rung x all fusion operators."""
    y = df["flooded"].to_numpy(int)
    xy = df[["x_m", "y_m"]].to_numpy(float)
    folds = df["_fold"].to_numpy()
    n = len(df)
    R, parts = _outer_inner(df, feats, S_cols, y, xy, folds, spec, cfg)
    S_mat = df[S_cols].to_numpy(float)
    P0, P1, PG, chosen = _apply_social_ops(parts, R, S_mat, y, n, cfg)

    scores = {"physical": R, "recal_R": P0, "stacked_RS": P1, "gated_RS": PG}
    if cfg.run_early_fusion:
        XS = df[feats + S_cols].to_numpy(float)
        PE = np.full(n, np.nan)
        for tr, te, _ in parts:
            PE[te] = fit_predict(spec, XS[tr], y[tr], XS[te])
        scores["early_RS"] = PE
    if cfg.run_legacy_adr:
        scores["adr_legacy"] = op_adr_legacy(R, S_mat[:, 0])

    # ---- toroidal null: same real social layer, shifted so it no longer aligns with the floods
    null = []
    if raster_meta is not None and cfg.n_null > 0:
        rows, cols, nr, nc = raster_meta
        shifts = sample_shifts(cfg.n_null, nr, nc, cfg.null_min_shift_m / cfg.grid_m, cfg.seed + 99)
        ap_phys = safe_ap(y, R)
        ap_phys_fm = fold_ap(y, R, folds)[0]
        for i, (dr, dc) in enumerate(shifts):
            S_sh = np.column_stack([toroidal_shift(S_mat[:, j], rows, cols, nr, nc, dr, dc)
                                    for j in range(S_mat.shape[1])])
            n0, n1, ng, _ = _apply_social_ops(parts, R, S_sh, y, n, cfg)
            rec = dict(info_nats=float(np.mean(logloss_vec(y, n0) - logloss_vec(y, n1))),
                       dAP_stacked=safe_ap(y, n1) - safe_ap(y, n0),
                       dAP_gated=safe_ap(y, ng) - ap_phys, dAP_early=np.nan,
                       info_nats_fm=fold_info(y, n0, n1, folds),
                       dAP_stacked_fm=fold_ap(y, n1, folds)[0] - fold_ap(y, n0, folds)[0],
                       dAP_gated_fm=fold_ap(y, ng, folds)[0] - ap_phys_fm, dAP_early_fm=np.nan)
            if cfg.run_early_fusion and i < cfg.n_null_early:
                XS_n = np.column_stack([df[feats].to_numpy(float) if feats else np.zeros((n, 0)), S_sh])
                PE_n = np.full(n, np.nan)
                for tr, te, _ in parts:
                    PE_n[te] = fit_predict(spec, XS_n[tr], y[tr], XS_n[te])
                rec["dAP_early"] = safe_ap(y, PE_n) - ap_phys
                rec["dAP_early_fm"] = fold_ap(y, PE_n, folds)[0] - ap_phys_fm
            null.append(rec)
    log(f"  [{rung_name}] AP_phys={safe_ap(y, R):.4f} "
        f"AP_stacked={safe_ap(y, P1):.4f} AP_gated={safe_ap(y, PG):.4f}")
    return dict(rung=rung_name, features=list(feats), scores=scores,
                gated_params=chosen, null=pd.DataFrame(null))


# ------------------------------------------------------- summarisation
def point_metrics(y, scores, top_k_pct):
    rows = []
    for name, s in scores.items():
        r = dict(operator=name, AP=safe_ap(y, s), AUC=safe_auc(y, s),
                 logloss=float(np.mean(logloss_vec(y, s))) if name != "adr_legacy" else float("nan"),
                 brier=float(np.mean((s - y) ** 2)) if name != "adr_legacy" else float("nan"))
        for k in top_k_pct:
            r[f"R@{k}%"] = recall_at_k(y, s, k)
        rows.append(r)
    return pd.DataFrame(rows)


def fold_ap(y, s, folds):
    """Mean and sd of AP computed separately inside each spatial fold. Pooled out-of-fold AP mixes
    five per-fold calibrations, which can rank cells by fold base rate instead of by risk; the
    per-fold mean cannot."""
    aps = [safe_ap(y[folds == f], s[folds == f]) for f in np.unique(folds)]
    aps = [a for a in aps if np.isfinite(a)]
    return (float(np.mean(aps)) if aps else float("nan"),
            float(np.std(aps)) if aps else float("nan"), len(aps))


def fold_info(y, p0, p1, folds):
    """Mean over folds of the within-fold log-loss reduction (nats per cell)."""
    vals = []
    for f in np.unique(folds):
        m = folds == f
        if m.sum() and np.isfinite(p0[m]).all() and np.isfinite(p1[m]).all():
            vals.append(float(np.mean(logloss_vec(y[m], p0[m]) - logloss_vec(y[m], p1[m]))))
    return float(np.mean(vals)) if vals else float("nan")


def fold_entropy(y, p, folds):
    """Mean over folds of the within-fold mean log-loss of p (nats per cell): the held-out conditional
    entropy H(Y | R) left by the recalibrated physical model, i.e. the headroom any extra layer can use."""
    vals = []
    for f in np.unique(folds):
        m = folds == f
        if m.sum() and np.isfinite(p[m]).all():
            vals.append(float(np.mean(logloss_vec(y[m], p[m]))))
    return float(np.mean(vals)) if vals else float("nan")


def per_fold_metrics(y, scores, folds):
    """Pooled out-of-fold ranking mixes per-fold calibrations; the per-fold mean avoids that."""
    rows = []
    for name, s in scores.items():
        aps = [safe_ap(y[folds == f], s[folds == f]) for f in np.unique(folds)]
        aps = [a for a in aps if np.isfinite(a)]
        rows.append(dict(operator=name, AP_fold_mean=float(np.mean(aps)) if aps else float("nan"),
                         AP_fold_sd=float(np.std(aps)) if aps else float("nan"), n_folds=len(aps)))
    return pd.DataFrame(rows)


NULL_METRICS = ["info_nats", "dAP_stacked", "dAP_gated", "dAP_early"]
# Reported primary: per-fold metrics, centred on the spatial null. Secondary: pooled and
# headroom-normalised versions (kept for continuity; the headroom denominator amplifies late rungs).
PRIMARY_GRADIENT = ["info_nats_fm_adj", "dAP_stacked_fm_adj", "dAP_early_fm_adj", "dAP_gated_fm_adj"]
SECONDARY_GRADIENT = ["info_nats", "dAP_stacked", "dAP_early", "dAP_gated", "dAPh_stacked"]


def rung_summary(y, res, prevalence, folds=None):
    s = res["scores"]
    ap_phys, ap_rec, ap_st = safe_ap(y, s["physical"]), safe_ap(y, s["recal_R"]), safe_ap(y, s["stacked_RS"])
    head = max(1.0 - ap_rec, HEADROOM_FLOOR)
    out = dict(
        rung=res["rung"], n_features=len(res["features"]), prevalence=prevalence,
        AP_phys=ap_phys, AP_recal=ap_rec, AP_stacked=ap_st, AP_gated=safe_ap(y, s["gated_RS"]),
        info_nats=float(np.mean(logloss_vec(y, s["recal_R"]) - logloss_vec(y, s["stacked_RS"]))),
        dAP_stacked=ap_st - ap_rec, dAPh_stacked=(ap_st - ap_rec) / head,
        dAP_gated=safe_ap(y, s["gated_RS"]) - ap_phys)
    if "early_RS" in s:
        out["dAP_early"] = safe_ap(y, s["early_RS"]) - ap_phys
    if "adr_legacy" in s:
        out["dAP_adr_legacy"] = safe_ap(y, s["adr_legacy"]) - ap_phys
    # ---- per-fold metrics (primary in the paper) -----------------------------------
    if folds is not None:
        folds = np.asarray(folds)
        fm = {}
        for op, nm in [("physical", "AP_phys_fm"), ("recal_R", "AP_recal_fm"), ("stacked_RS", "AP_stacked_fm"),
                       ("gated_RS", "AP_gated_fm"), ("early_RS", "AP_early_fm"), ("adr_legacy", "AP_legacy_fm")]:
            if op in s:
                m, sd, nf = fold_ap(y, s[op], folds)
                fm[nm], fm[nm + "_sd"], fm["n_folds"] = m, sd, nf
        out.update(fm)
        out["info_nats_fm"] = fold_info(y, s["recal_R"], s["stacked_RS"], folds)
        out["cond_entropy_fm"] = fold_entropy(y, s["recal_R"], folds)
        out["dAP_stacked_fm"] = fm.get("AP_stacked_fm", np.nan) - fm.get("AP_recal_fm", np.nan)
        out["dAP_gated_fm"] = fm.get("AP_gated_fm", np.nan) - fm.get("AP_phys_fm", np.nan)
        if "AP_early_fm" in fm:
            out["dAP_early_fm"] = fm["AP_early_fm"] - fm.get("AP_phys_fm", np.nan)
        if "AP_legacy_fm" in fm:
            out["dAP_adr_legacy_fm"] = fm["AP_legacy_fm"] - fm.get("AP_phys_fm", np.nan)
    # ---- spatial null: p-values, null means, and null-centred effects ---------------
    nl = res["null"]
    out["null_basis_fm"] = "none"
    for key in NULL_METRICS:
        for suf in ["", "_fm"]:
            k, col = key + suf, key + suf
            if k not in out or not len(nl):
                continue
            src = col if (col in nl and nl[col].notna().any()) else None
            if src is None and suf == "_fm" and key in nl and nl[key].notna().any():
                src = key                      # checkpoint from an older run: pooled null, flagged below
                out["null_basis_fm"] = "pooled_null"
            if src is None:
                continue
            v = nl[src].dropna().to_numpy()
            out[f"p_null_{k}"] = float((1 + np.sum(v >= out[k])) / (len(v) + 1))
            out[f"null_mean_{k}"] = float(np.mean(v))
            out[f"null_q95_{k}"] = float(np.nanquantile(v, 0.95))
            out[f"n_null_{k}"] = int(len(v))
            # the null is not centred on zero (any smooth extra channel helps the learner a little),
            # so the reported effect subtracts the mean of the shifted-layer runs
            out[f"{k}_adj"] = out[k] - float(np.mean(v))
    if out.get("null_basis_fm") == "none" and any(f"null_mean_{m}_fm" in out for m in NULL_METRICS):
        out["null_basis_fm"] = "fold_mean_null"
    # headroom-normalised effects (v5.5): a falling absolute gain can be mechanical, because the room left by
    # the physical model shrinks as it improves. These divide the null-centred gain by that room.
    if "info_nats_fm_adj" in out and out.get("cond_entropy_fm", 0) > 0:
        out["info_frac_fm_adj"] = out["info_nats_fm_adj"] / out["cond_entropy_fm"]
    if "dAP_stacked_fm_adj" in out and np.isfinite(out.get("AP_recal_fm", np.nan)):
        out["dAPh_fm_adj"] = out["dAP_stacked_fm_adj"] / max(1.0 - out["AP_recal_fm"], HEADROOM_FLOOR)
    return out


def block_bootstrap(y, tiles, rung_results, n_boot, seed, folds=None):
    """Paired tile bootstrap across rungs and operators. Returns long frame."""
    rng = np.random.default_rng(seed)
    ut, inv = np.unique(tiles, return_inverse=True)
    members = [np.where(inv == i)[0] for i in range(len(ut))]
    recs = []
    for b in range(n_boot):
        pick = rng.integers(0, len(ut), len(ut))
        idx = np.concatenate([members[i] for i in pick])
        yb = y[idx]
        if yb.sum() == 0:
            continue
        fb = None if folds is None else np.asarray(folds)[idx]
        for res in rung_results:
            s = res["scores"]
            ap_phys = safe_ap(yb, s["physical"][idx])
            ap_rec = safe_ap(yb, s["recal_R"][idx])
            ap_st = safe_ap(yb, s["stacked_RS"][idx])
            rec_extra = {}
            if "early_RS" in s:
                rec_extra["dAP_early"] = safe_ap(yb, s["early_RS"][idx]) - ap_phys
            if fb is not None:
                ph_fm = fold_ap(yb, s["physical"][idx], fb)[0]
                pr_fm = fold_ap(yb, s["recal_R"][idx], fb)[0]
                st_fm = fold_ap(yb, s["stacked_RS"][idx], fb)[0]
                rec_extra.update(AP_phys_fm=ph_fm, AP_recal_fm=pr_fm, AP_stacked_fm=st_fm,
                                 dAP_stacked_fm=st_fm - pr_fm,
                                 dAP_gated_fm=fold_ap(yb, s["gated_RS"][idx], fb)[0] - ph_fm,
                                 info_nats_fm=fold_info(yb, s["recal_R"][idx], s["stacked_RS"][idx], fb),
                                 cond_entropy_fm=fold_entropy(yb, s["recal_R"][idx], fb))
                if "early_RS" in s:
                    rec_extra["dAP_early_fm"] = fold_ap(yb, s["early_RS"][idx], fb)[0] - ph_fm
                if "adr_legacy" in s:
                    rec_extra["dAP_adr_legacy_fm"] = fold_ap(yb, s["adr_legacy"][idx], fb)[0] - ph_fm
            recs.append(dict(
                b=b, rung=res["rung"], AP_phys=ap_phys, AP_recal=ap_rec, **rec_extra,
                info_nats=float(np.mean(logloss_vec(yb, s["recal_R"][idx])
                                        - logloss_vec(yb, s["stacked_RS"][idx]))),
                dAP_stacked=ap_st - ap_rec,
                dAPh_stacked=(ap_st - ap_rec) / max(1 - ap_rec, HEADROOM_FLOOR),
                dAP_gated=safe_ap(yb, s["gated_RS"][idx]) - ap_phys))
    return pd.DataFrame(recs)


def gradient_test(summary, boot, x="AP_recal", ycol="dAPh_stacked", role="secondary"):
    """RQ2: slope of marginal social value on held-out physical skill.
    Point slope from rung summaries; CI and one-sided p (slope >= 0) from the
    paired block bootstrap. Also Spearman on the point estimates (few rungs:
    descriptive only)."""
    def slope(xv, yv):
        xv, yv = np.asarray(xv, float), np.asarray(yv, float)
        ok = np.isfinite(xv) & np.isfinite(yv)
        if ok.sum() < 3 or np.ptp(xv[ok]) < 1e-12:
            return float("nan")
        return float(np.polyfit(xv[ok], yv[ok], 1)[0])
    base, centred = (ycol[:-4], True) if ycol.endswith("_adj") else (ycol, False)
    if base not in boot.columns or x not in boot.columns or base not in summary.columns:
        return dict(metric=ycol, role=role, x=x, centred=centred, slope=float("nan"), slope_se=float("nan"),
                    slope_ci_low=float("nan"), slope_ci_high=float("nan"),
                    p_one_sided_slope_ge_0=float("nan"), spearman_rho_descriptive=float("nan"),
                    n_rungs=int(len(summary)), n_boot=0)
    off = summary.set_index("rung")[f"null_mean_{base}"] if centred and f"null_mean_{base}" in summary else None
    yv = summary[base].to_numpy(float) - (summary["rung"].map(off).to_numpy(float) if off is not None else 0.0)
    bo = boot.copy()
    bo["_y"] = bo[base].to_numpy(float) - (bo["rung"].map(off).to_numpy(float) if off is not None else 0.0)
    pt = slope(summary[x], yv)
    bs = bo.groupby("b").apply(lambda d: slope(d[x], d["_y"]), include_groups=False).dropna().to_numpy()
    rho = (spearmanr(summary[x], yv).correlation
           if len(summary) >= 3 and np.ptp(np.asarray(yv, float)) > 0 and np.ptp(summary[x].to_numpy(float)) > 0
           else float("nan"))          # a constant metric (e.g. a gate that never opens) has no rank correlation
    return dict(metric=ycol, role=role, x=x, centred=centred, slope=pt,
                slope_se=float(np.std(bs, ddof=1)) if len(bs) > 1 else float("nan"),
                slope_ci_low=float(np.quantile(bs, 0.025)) if len(bs) else float("nan"),
                slope_ci_high=float(np.quantile(bs, 0.975)) if len(bs) else float("nan"),
                p_one_sided_slope_ge_0=float((1 + np.sum(bs >= 0)) / (len(bs) + 1)) if len(bs) else float("nan"),
                spearman_rho_descriptive=float(rho), n_rungs=int(len(summary)), n_boot=int(len(bs)))


def gradient_robustness(res, drop_first=True):
    """Primary gradients recomputed without the empty-model rung (R0). R0 has no physical features, so any
    informative smooth layer helps most there; a decline that survives without R0 is not an artefact of it."""
    summary, boot = res["summary"], res["boot"]
    if len(summary) < 4 or "rung" not in summary:
        return pd.DataFrame()
    first = summary["rung"].iloc[0]
    s2 = summary[summary["rung"] != first].reset_index(drop=True)
    b2 = boot[boot["rung"] != first]
    xp = "AP_recal_fm" if "AP_recal_fm" in boot.columns else "AP_recal"
    g = pd.DataFrame([gradient_test(s2, b2, x=xp, ycol=c, role="robust_excl_R0") for c in PRIMARY_GRADIENT])
    return g[g["n_boot"] > 0].reset_index(drop=True)


def fold_diagnostics(res, y):
    """Per-fold cell counts and prevalence. Strongly unequal fold prevalence inflates the spread of
    per-fold AP (AP of a constant model equals the fold base rate), so it is reported per city."""
    f = np.asarray(res["fold"])
    y = np.asarray(y)
    rows = [dict(fold=int(k), cells=int((f == k).sum()), positives=int(y[f == k].sum()),
                 prevalence=float(y[f == k].mean())) for k in np.unique(f)]
    return pd.DataFrame(rows)


# ======================================================================= v5.5 inference layer
# Pre-registered smallest effect sizes of interest (SESOI) for the equivalence ("saturation") verdicts.
SESOI = {"dAP_stacked_fm": 0.01, "dAP_gated_fm": 0.01, "dAP_early_fm": 0.01, "dAP_adr_legacy_fm": 0.01,
         "info_frac_fm": 0.02, "info_nats_fm": None}
EFFECT_METRICS = ["info_nats_fm", "info_frac_fm", "dAP_stacked_fm", "dAP_gated_fm", "dAP_early_fm", "dAP_adr_legacy_fm"]


def _null_offset(summary, base):
    col = f"null_mean_{base}"
    return summary.set_index("rung")[col] if col in summary.columns else None


def _normalised_boot(summary, boot):
    """Adds the headroom-normalised, null-centred effects to the bootstrap replicates. The null mean is a
    fixed per-rung offset; the headroom (conditional entropy, 1 - AP) is re-estimated in each replicate."""
    b = boot.copy()
    off_i = _null_offset(summary, "info_nats_fm")
    if {"info_nats_fm", "cond_entropy_fm"}.issubset(b.columns) and off_i is not None:
        ce = b["cond_entropy_fm"].to_numpy(float)
        b["info_frac_fm"] = np.where(ce > 0, (b["info_nats_fm"].to_numpy(float) - b["rung"].map(off_i).to_numpy(float)) / np.where(ce > 0, ce, 1), np.nan)
    off_s = _null_offset(summary, "dAP_stacked_fm")
    if {"dAP_stacked_fm", "AP_recal_fm"}.issubset(b.columns) and off_s is not None:
        head = np.maximum(1.0 - b["AP_recal_fm"].to_numpy(float), HEADROOM_FLOOR)
        b["dAPh_fm"] = (b["dAP_stacked_fm"].to_numpy(float) - b["rung"].map(off_s).to_numpy(float)) / head
    return b


def normalised_gradients(res, drop_first=False):
    """Gradients of the headroom-normalised, null-centred gains (information: share of the physical model's
    remaining held-out uncertainty removed by the social layer; AP: share of the remaining AP headroom).
    A decline here is not the mechanical consequence of a shrinking ceiling."""
    summary, boot = res["summary"], res["boot"]
    if "info_frac_fm_adj" not in summary.columns and "dAPh_fm_adj" not in summary.columns:
        return pd.DataFrame()
    s2, b2 = summary.copy(), _normalised_boot(summary, boot)
    if drop_first and len(s2) >= 4:
        first = s2["rung"].iloc[0]
        s2, b2 = s2[s2["rung"] != first].reset_index(drop=True), b2[b2["rung"] != first]
    elif drop_first:
        return pd.DataFrame()
    xp = "AP_recal_fm" if "AP_recal_fm" in b2.columns else "AP_recal"
    rows = []
    for adj, bcol in [("info_frac_fm_adj", "info_frac_fm"), ("dAPh_fm_adj", "dAPh_fm")]:
        if adj in s2.columns and bcol in b2.columns:
            s3 = s2.assign(**{bcol: s2[adj]})
            g = gradient_test(s3, b2, x=xp, ycol=bcol, role="headroom_normalised" + ("_excl_R0" if drop_first else ""))
            g.update(metric=adj, centred=True)
            rows.append(g)
    g = pd.DataFrame(rows)
    return g[g["n_boot"] > 0].reset_index(drop=True) if len(g) else g


def effect_table(res, sesoi=None, alpha=0.05):
    """Per rung and metric: null-centred estimate, tile-bootstrap 90% and 95% intervals, spatial-null p and a
    pre-registered verdict. 'saturated' requires the 90% interval to lie inside +/- SESOI (two one-sided tests
    at 5%): absence of evidence is never reported as evidence of absence."""
    sesoi = dict(SESOI, **(sesoi or {}))
    summary = res["summary"]
    boot = _normalised_boot(summary, res["boot"])
    rows = []
    for _, r in summary.iterrows():
        rung = r["rung"]
        br = boot[boot["rung"] == rung]
        for m in EFFECT_METRICS:
            if m == "info_frac_fm":
                est, bv = r.get("info_frac_fm_adj", np.nan), br[m].to_numpy(float) if m in br else np.array([])
                pn = r.get("p_null_info_nats_fm", np.nan)
            else:
                if m not in summary.columns:
                    continue
                off = r.get(f"null_mean_{m}", np.nan)
                off = 0.0 if not np.isfinite(off) else off
                est = r[m] - off
                bv = br[m].to_numpy(float) - off if m in br else np.array([])
                pn = r.get(f"p_null_{m}", np.nan)
            bv = bv[np.isfinite(bv)]
            if not np.isfinite(est):
                continue
            q = (lambda a: float(np.quantile(bv, a)) if len(bv) >= 20 else float("nan"))
            lo95, hi95, lo90, hi90 = q(0.025), q(0.975), q(0.05), q(0.95)
            d = sesoi.get(m)
            has_null = np.isfinite(pn) if isinstance(pn, (float, int, np.floating)) else False
            if np.isfinite(lo95) and lo95 > 0 and (not has_null or pn <= alpha):
                verdict = "informative"
            elif np.isfinite(hi95) and hi95 < 0:
                verdict = "harmful"
            elif d is not None and np.isfinite(lo90) and -d < lo90 and hi90 < d:
                verdict = "saturated"
            else:
                verdict = "inconclusive"
            rows.append(dict(rung=rung, metric=m, estimate=float(est), ci90_low=lo90, ci90_high=hi90,
                             ci95_low=lo95, ci95_high=hi95, p_null=float(pn) if has_null else float("nan"),
                             sesoi=d if d is not None else float("nan"), verdict=verdict, null_centred=m not in ("dAP_adr_legacy_fm",),
                             n_boot=int(len(bv))))
    return pd.DataFrame(rows)


def saturation_rung(effects, metric="info_frac_fm"):
    """First rung from which the social gain is 'saturated' (equivalent to zero) at that rung and every
    later one; None if it never saturates. Descriptive, read with the per-rung table."""
    e = effects[effects["metric"] == metric].reset_index(drop=True)
    if e.empty:
        return None
    sat = (e["verdict"] == "saturated").to_numpy()
    for i in range(len(e)):
        if sat[i:].all():
            return str(e.loc[i, "rung"])
    return None


def holm(pvals):
    """Holm-Bonferroni adjusted p-values (family-wise error), order preserved; NaN passes through."""
    p = np.asarray(pvals, float)
    out = np.full(len(p), np.nan)
    ok = np.where(np.isfinite(p))[0]
    if not len(ok):
        return out
    order = ok[np.argsort(p[ok])]
    m, run = len(order), 0.0
    for i, j in enumerate(order):
        run = max(run, min(1.0, (m - i) * p[j]))
        out[j] = run
    return out


def meta_analysis(est, se, level=0.95, max_iter=200):
    """Random-effects meta-analysis for a handful of cities: REML between-city variance (fixed-point
    iteration), Hartung-Knapp-Sidik-Jonkman interval with the conservative max(1, q) truncation (recommended
    for k < 10), I^2 and a prediction interval for a new city (k >= 3)."""
    from scipy.stats import t as tdist
    y, s = np.asarray(est, float), np.asarray(se, float)
    # an SE at numerical zero means the estimate is degenerate (e.g. a city whose social layer is constant, so its
    # slope is exactly 0 in every bootstrap replicate); with inverse-variance weights it would swamp every other
    # city, so it is excluded as undefined rather than treated as infinitely precise (v5.5.1)
    ok = np.isfinite(y) & np.isfinite(s) & (s > 1e-9)
    y, v = y[ok], s[ok] ** 2
    k = int(len(y))
    out = dict(k=k, estimate=np.nan, se=np.nan, ci_low=np.nan, ci_high=np.nan, p_two_sided=np.nan,
               p_one_sided_lt0=np.nan, tau2=np.nan, I2=np.nan, Q=np.nan, pi_low=np.nan, pi_high=np.nan,
               method="REML + HKSJ (max(1,q))")
    if k == 0:
        return out
    if k == 1:
        out.update(estimate=float(y[0]), se=float(np.sqrt(v[0])), tau2=0.0, method="single city (no pooling)")
        z = 1.959963984540054
        out.update(ci_low=float(y[0] - z * np.sqrt(v[0])), ci_high=float(y[0] + z * np.sqrt(v[0])))
        return out
    wf = 1 / v
    mu_f = np.sum(wf * y) / np.sum(wf)
    Q = float(np.sum(wf * (y - mu_f) ** 2))
    tau2 = max(0.0, (Q - (k - 1)) / (np.sum(wf) - np.sum(wf ** 2) / np.sum(wf)))       # DL start
    for _ in range(max_iter):
        w = 1 / (v + tau2)
        mu = np.sum(w * y) / np.sum(w)
        new = max(0.0, float(np.sum(w ** 2 * ((y - mu) ** 2 - v)) / np.sum(w ** 2) + 1 / np.sum(w)))
        if abs(new - tau2) < 1e-12:
            tau2 = new
            break
        tau2 = new
    w = 1 / (v + tau2)
    mu = float(np.sum(w * y) / np.sum(w))
    q = float(np.sum(w * (y - mu) ** 2) / (k - 1))
    se_hk = float(np.sqrt(max(1.0, q) / np.sum(w)))
    tc = tdist.ppf(0.5 + level / 2, k - 1)
    tstat = mu / se_hk if se_hk > 0 else np.nan
    I2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0
    out.update(estimate=mu, se=se_hk, ci_low=mu - tc * se_hk, ci_high=mu + tc * se_hk,
               p_two_sided=float(2 * tdist.sf(abs(tstat), k - 1)), p_one_sided_lt0=float(tdist.cdf(tstat, k - 1)),
               tau2=float(tau2), I2=float(I2), Q=Q)
    if k >= 3:
        tp = tdist.ppf(0.5 + level / 2, k - 2)
        half = tp * np.sqrt(tau2 + se_hk ** 2)
        out.update(pi_low=mu - half, pi_high=mu + half)
    return {kk: (float(vv) if isinstance(vv, (np.floating, np.integer)) and kk != "k" else vv) for kk, vv in out.items()}


def _metareg_fit(y, v, X, max_iter=200):
    """Mixed-effects meta-regression: REML residual tau^2 (Fisher scoring, Viechtbauer 2005) and weighted LS."""
    tau2 = 0.0
    for _ in range(max_iter):
        w = 1 / (v + tau2)
        W = np.diag(w)
        A = np.linalg.inv(X.T @ W @ X)
        P = W - W @ X @ A @ X.T @ W
        Py = P @ y
        tr_PP = float(np.trace(P @ P))
        if tr_PP <= 0:
            break
        new = max(0.0, tau2 + float(Py @ Py - np.trace(P)) / tr_PP)
        if abs(new - tau2) < 1e-12:
            tau2 = new
            break
        tau2 = new
    w = 1 / (v + tau2)
    W = np.diag(w)
    A = np.linalg.inv(X.T @ W @ X)
    b = A @ X.T @ W @ y
    return b, A, w, tau2


def meta_regression(est, se, x, n_perm=20000, seed=0):
    """Mixed-effects meta-regression y ~ 1 + x (v6): REML residual between-city variance, Knapp-Hartung
    standard errors with the conservative max(1, q) scaling, two-sided t test on k-2 df, and a permutation
    p-value for the moderator (Higgins & Thompson 2004), exact when k! <= n_perm. Small k: the permutation p
    is the one to report."""
    import itertools
    import math
    from scipy.stats import t as tdist
    y, s, x = (np.asarray(a, float) for a in (est, se, x))
    ok = np.isfinite(y) & np.isfinite(s) & (s > 1e-9) & np.isfinite(x)
    y, s, x = y[ok], s[ok], x[ok]
    k = int(len(y))
    base = dict(k=k, intercept=np.nan, slope=np.nan, slope_se=np.nan, p=np.nan, p_perm=np.nan, tau2=np.nan,
                R2_tau=np.nan, method="REML + Knapp-Hartung (max(1,q)) + permutation")
    if k < 4 or np.ptp(x) == 0:
        return dict(base, note="needs >= 4 cities with varying moderator")
    v = s ** 2

    def tstat(xx):
        X = np.column_stack([np.ones(k), xx])
        b, A, w, t2 = _metareg_fit(y, v, X)
        q = float(np.sum(w * (y - X @ b) ** 2) / (k - 2))
        se_b = float(np.sqrt(A[1, 1] * max(1.0, q)))
        return b, se_b, t2, (b[1] / se_b if se_b > 0 else np.nan)
    b, se_b, t2, t_obs = tstat(x)
    tau2_0 = meta_analysis(y, s)["tau2"]
    if math.factorial(k) <= n_perm:
        perms = (np.array(pp) for pp in itertools.permutations(range(k)))
    else:
        rng = np.random.default_rng(seed)
        perms = (rng.permutation(k) for _ in range(n_perm))
    t_perm = np.array([tstat(x[pp])[3] for pp in perms])
    t_perm = t_perm[np.isfinite(t_perm)]
    p_perm = float(np.mean(np.abs(t_perm) >= abs(t_obs) - 1e-12)) if len(t_perm) and np.isfinite(t_obs) else np.nan
    return dict(base, intercept=float(b[0]), slope=float(b[1]), slope_se=se_b,
                p=float(2 * tdist.sf(abs(t_obs), k - 2)), p_perm=p_perm, tau2=float(t2),
                R2_tau=float(max(0.0, 1 - t2 / tau2_0)) if tau2_0 and tau2_0 > 0 else np.nan, note="")


def label_correlogram(xy, y, bins_m=(250, 500, 1000, 1500, 2000, 3000, 4000, 6000, 8000),
                      n_pairs=300000, seed=0):
    """Spatial autocorrelation of the flood label by distance (random pairs). The distance at which it
    falls below 0.1 is compared with the CV tile size to justify the spatial blocking."""
    rng = np.random.default_rng(seed)
    xy, y = np.asarray(xy, float), np.asarray(y, float)
    n = len(y)
    if n < 50 or y.std() == 0:
        return pd.DataFrame(), float("nan")
    z = (y - y.mean()) / y.std()
    tree = cKDTree(xy)
    edges = np.array([0.0] + list(bins_m), float)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        i = rng.integers(0, n, n_pairs // len(bins_m))
        # random partner within the annulus: jitter a point, snap to its nearest cell
        ang = rng.uniform(0, 2 * np.pi, len(i))
        rad = np.sqrt(rng.uniform(lo ** 2, hi ** 2, len(i)))
        tgt = xy[i] + np.column_stack([rad * np.cos(ang), rad * np.sin(ang)])
        _, j = tree.query(tgt, k=1)
        d = np.hypot(*(xy[i] - xy[j]).T)
        keep = (d > lo) & (d <= hi) & (i != j)     # partner snapped outside the study area or annulus: dropped
        if keep.sum() < 100:
            continue
        rows.append(dict(bin_low_m=lo, bin_high_m=hi, n_pairs=int(keep.sum()), corr=float(np.mean(z[i[keep]] * z[j[keep]]))))
    cg = pd.DataFrame(rows)
    below = cg[cg["corr"] < 0.1] if len(cg) else cg
    rng_m = float(below["bin_high_m"].iloc[0]) if len(below) else float("nan")
    return cg, rng_m


def data_fingerprint(df, cols):
    """Hash of the exact values a computation consumes. Two rungs are only 'identical' if their
    labels, coordinates, features and social columns are identical, not merely their column names."""
    h = hashlib.sha1()
    for col in ["flooded", "x_m", "y_m"] + sorted(cols):
        a = np.ascontiguousarray(np.asarray(df[col], dtype=np.float64))
        h.update(col.encode())
        h.update(a.tobytes())
    return h.hexdigest()[:16]


def rung_key(feats, S_cols, cfg, spec, df=None):
    """Identity of a rung's computation. Includes a fingerprint of the data itself, so a sensitivity
    variant with a different social layer or label can never be served another run's cached result."""
    fp = data_fingerprint(df, list(feats) + list(S_cols)) if df is not None else "nodata"
    payload = json.dumps(dict(d=fp, f=sorted(feats), s=sorted(S_cols), k=cfg.k_folds, t=cfg.tile_m, b=cfg.buffer_m,
                              i=cfg.inner_k, seed=cfg.seed, nn=cfg.n_null, ne=cfg.n_null_early,
                              ef=cfg.run_early_fusion, la=cfg.run_legacy_adr, m=spec.kind,
                              p=spec.xgb_params if spec.kind == "xgb" else {}), sort_keys=True)
    grid = (tuple(getattr(cfg, "gated_alphas", GATED_GRID_DEFAULT[0])), tuple(getattr(cfg, "gated_taus", GATED_GRID_DEFAULT[1])))
    if grid != GATED_GRID_DEFAULT:
        # only a non-default grid changes the key, so every cached pre-registered result stays valid
        payload += "|gated=" + json.dumps([list(grid[0]), list(grid[1])])
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def run_ladder(df, ladder, S_cols, spec, cfg, raster_meta=None, log=print, rung_cache=None):
    """df needs: flooded, x_m, y_m, feature columns, S_cols.
    ladder: ordered list of (rung_name, cumulative_feature_list)."""
    df = df.copy()
    used = sorted({f for _, feats in ladder for f in feats} | set(S_cols))
    missing = [c for c in used if c not in df]
    if missing:
        raise ValueError(f"columns missing from analysis table: {missing}")
    bad = [c for c in used if not np.isfinite(df[c].to_numpy(float)).all()]
    if bad:
        raise ValueError(f"non-finite values (NaN/inf) in columns {bad}; sanitise before run_ladder")
    y = df["flooded"].to_numpy(int)
    if y.sum() < cfg.k_folds * 2:
        raise ValueError(f"Too few positives ({y.sum()}) for {cfg.k_folds}-fold spatial CV.")
    df["_tile"] = tile_ids(df["x_m"], df["y_m"], cfg.tile_m)
    df["_fold"] = assign_folds(df["_tile"].to_numpy(), y, cfg.k_folds, cfg.seed)
    pos_per_fold = df.groupby("_fold")["flooded"].sum().to_dict()
    log(f"positives per fold: {pos_per_fold}")
    results, seen = [], {}
    for name, feats in ladder:
        key = rung_key(feats, S_cols, cfg, spec, df)
        if key in seen:        # same feature set as an earlier rung (R0, and the full rung across orderings)
            res = dict(seen[key], rung=name)
            log(f"  [{name}] reused from '{seen[key]['rung']}' (identical feature set)")
        elif rung_cache is not None:
            res = dict(rung_cache(key, lambda: run_rung(df, name, feats, S_cols, spec, cfg, raster_meta, log)),
                       rung=name)
        else:
            res = run_rung(df, name, feats, S_cols, spec, cfg, raster_meta, log)
        seen[key] = res
        results.append(res)
    prev = float(y.mean())
    foldv = df["_fold"].to_numpy()
    summary = pd.DataFrame([rung_summary(y, r, prev, folds=foldv) for r in results])
    boot = block_bootstrap(y, df["_tile"].to_numpy(), results, cfg.n_boot, cfg.seed + 1, folds=foldv)
    ci = boot.groupby("rung").quantile([0.025, 0.975]).unstack()
    ci.columns = [f"{a}_{'lo' if q == 0.025 else 'hi'}" for a, q in ci.columns]
    summary = summary.merge(ci.drop(columns=["b_lo", "b_hi"], errors="ignore"),
                            left_on="rung", right_index=True, how="left")
    point = pd.concat([point_metrics(y, r["scores"], cfg.top_k_pct)
                       .merge(per_fold_metrics(y, r["scores"], df["_fold"].to_numpy()), on="operator", how="left")
                       .assign(rung=r["rung"]) for r in results], ignore_index=True)
    for a, b in [("AP_phys_fm", "AP_phys_foldmean"), ("AP_recal_fm", "AP_recal_foldmean"),
                 ("AP_stacked_fm", "AP_stacked_foldmean"), ("AP_early_fm", "AP_early_foldmean"),
                 ("AP_gated_fm", "AP_gated_foldmean"), ("dAP_early_fm", "dAP_early_foldmean")]:
        if a in summary.columns:
            summary[b] = summary[a]
    fm = point.pivot_table(index="rung", columns="operator", values="AP_fold_mean", aggfunc="first")
    for op, col in [("physical", "AP_phys_foldmean"), ("recal_R", "AP_recal_foldmean"),
                    ("stacked_RS", "AP_stacked_foldmean"), ("early_RS", "AP_early_foldmean"),
                    ("gated_RS", "AP_gated_foldmean")]:
        if op in fm.columns:
            summary[col] = summary["rung"].map(fm[op])
    if {"AP_early_foldmean", "AP_phys_foldmean"}.issubset(summary.columns):
        summary["dAP_early_foldmean"] = summary["AP_early_foldmean"] - summary["AP_phys_foldmean"]
    # primary gradients: per-fold metrics, null-centred, against per-fold physical skill
    xp = "AP_recal_fm" if "AP_recal_fm" in boot.columns else "AP_recal"
    grad = pd.DataFrame([gradient_test(summary, boot, x=xp, ycol=c, role="primary") for c in PRIMARY_GRADIENT]
                        + [gradient_test(summary, boot, x="AP_recal", ycol=c, role="secondary")
                           for c in SECONDARY_GRADIENT])
    grad = grad[grad["n_boot"] > 0].reset_index(drop=True)
    gated = pd.DataFrame([dict(rung=r["rung"], fold=i, **p)
                          for r in results for i, p in enumerate(r["gated_params"])])
    return dict(summary=summary, point=point, boot=boot, gradient=grad, gated_params=gated,
                results=results, pos_per_fold=pos_per_fold, fold=df["_fold"].to_numpy(),
                tile=df["_tile"].to_numpy())


# ------------------------------------------------------- LaTeX macros
_DIG = dict(zip("0123456789", ["Zero", "One", "Two", "Three", "Four", "Five",
                               "Six", "Seven", "Eight", "Nine"]))


def macro_name(*parts):
    s = "".join(str(p) for p in parts)
    s = "".join(_DIG.get(ch, ch) for ch in s)
    s = "".join(ch for ch in s if ch.isalpha())
    return s


def fmt_num(v, nd=3):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "n/a"
    if isinstance(v, (int, np.integer)):
        return f"{int(v)}"
    av = abs(v)
    if av != 0 and av < 10 ** (-nd):
        return f"{v:.1e}"
    return f"{v:.{nd}f}"


def latex_macros(prefix, mapping, nd=3):
    lines = []
    for k, v in mapping.items():
        name = macro_name(prefix, k)
        val = v if isinstance(v, str) else fmt_num(v, nd)
        val = val.replace("_", r"\_").replace("%", r"\%")
        lines.append(f"\\newcommand{{\\{name}}}{{{val}}}")
    return "\n".join(lines) + "\n"
