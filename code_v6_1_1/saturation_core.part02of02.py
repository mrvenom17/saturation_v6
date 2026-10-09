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
    is the one to report. n_perm=0 skips the permutations (p_perm is NaN): used for leave-one-out influence."""
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
    if not n_perm:
        return dict(base, intercept=float(b[0]), slope=float(b[1]), slope_se=se_b,
                    p=float(2 * tdist.sf(abs(t_obs), k - 2)), p_perm=np.nan, tau2=float(t2),
                    R2_tau=float(max(0.0, 1 - t2 / tau2_0)) if tau2_0 and tau2_0 > 0 else np.nan, note="no permutations")
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
