def _block_covers_range(prov, prereg):
    """Does the spatial CV block (tile + buffer) reach the range of the label's autocorrelation? None if unknown.
    Where the correlogram never fell below 0.1 the range is unknown and larger than the maximum tile: False."""
    tile = prov.get("cv_tile_m")
    if tile is None:
        return None
    rng = prov.get("label_corr_range_m")
    buf = float((prereg.get("cv") or {}).get("buffer_m", 0.0))
    if rng is None or not np.isfinite(float(rng)):
        return False
    return bool(float(tile) + buf >= float(rng) - 1e-6)


ROBUSTNESS_NOTE = ("post hoc (v6.1.2, after the d55d6b06 results were seen); label-free; never a headline")


def _robustness_tables(states, info, sets, TOP, PC, T1, prereg, out_root, d):
    """v6.1.2 additions that need no refitting (all post hoc, reported as such):
    T12  pooled estimates (confirmatory set) with one estimate per disaster, leaving each disaster out, and
         without the events whose CV block is shorter than the label's autocorrelation range;
    T13  calibration of the out-of-fold scores at the top rung, per city and operator;
    T14  the null-centred top-rung effects next to those of an archived run that used the v6.1.1 null."""
    ap_ = prereg.get("analysis_plan") or {}
    clusters = dict(ap_.get("disaster_of") or {})
    conf = sets[CONFIRMATORY]
    lines, rows = [], []
    covers = {} if not len(T1) else dict(zip(T1["city"], T1.get("block_covers_label_range", pd.Series(dtype=object))))
    short = sorted(c for c in conf if covers.get(c) is False)
    quantities = []
    if len(TOP):
        for m in TOP_METRICS:
            quantities.append((f"top-rung {m}", TOP[(TOP["metric"] == m) & TOP["city"].isin(conf)], "estimate"))
    if len(PC):
        base = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary") & PC["city"].isin(conf)]
        for m in CO_PRIMARY:
            quantities.append((f"gradient slope {m}", base[base["metric"] == m], "slope"))
    for q, x, col in quantities:
        if not len(x):
            continue
        full = sc.meta_analysis(x[col], x["se"])
        rows.append(dict(quantity=q, variant="all confirmatory cities", cities=",".join(sorted(x["city"])), **full))
        if clusters:
            pc = sc.pool_by_cluster(x[col], x["se"], x["city"], clusters)
            rows.append(dict(quantity=q, variant="one estimate per disaster", cities=pc.pop("units"), **pc))
            lo = sc.leave_one_cluster_out(x[col], x["se"], x["city"], clusters)
            for r in lo.to_dict("records"):
                g = r.pop("left_out"); lc = r.pop("left_out_cities")
                if g in set(clusters.values()):
                    rows.append(dict(quantity=q, variant=f"without disaster {g} ({lc})", cities="", **r))
        if short:
            xs = x[~x["city"].isin(short)]
            rows.append(dict(quantity=q, variant="without events whose CV block is shorter than the label range",
                             cities=",".join(sorted(xs["city"])), **sc.meta_analysis(xs[col], xs["se"])))
    ROB = pd.DataFrame(rows)
    if len(ROB):
        ROB.insert(2, "note", ROBUSTNESS_NOTE)
    ROB.to_csv(os.path.join(d, "T12_robustness_pooling.csv"), index=False)
    for q in ("top-rung dAP_stacked_fm", "top-rung dAP_adr_legacy_fm", "gradient slope info_nats_fm_adj"):
        x = ROB[ROB["quantity"] == q] if len(ROB) else ROB
        if len(x):
            parts = [f"{r.variant}: {r.estimate:+.4f} [{r.ci_low:+.4f}, {r.ci_high:+.4f}] k={r.k}" for r in x.itertuples()
                     if np.isfinite(r.estimate)]
            lines.append(f"Robustness (post hoc) {q}: " + "; ".join(parts))
    if short:
        lines.append(f"CV block shorter than the label's autocorrelation range: {', '.join(short)}")
    # T13 calibration
    cal = []
    for c, st_ in sorted(states.items()):
        cb = st_.get("calibration")
        if cb is not None and len(cb) and info.get(c, {}).get("current"):
            cal.append(pd.DataFrame(cb).assign(city=c))
    CAL = pd.concat(cal, ignore_index=True) if cal else pd.DataFrame()
    if len(CAL):
        CAL = CAL[["city"] + [k for k in CAL.columns if k != "city"]]
    CAL.to_csv(os.path.join(d, "T13_calibration_top_rung.csv"), index=False)
    if len(CAL):
        fm = CAL[CAL["scope"] == "fold_mean"]
        for op in ("physical", "recal_R", "stacked_RS"):
            x = fm[fm["operator"] == op]
            if len(x):
                lines.append(f"Calibration (post hoc, fold mean, top rung) {op}: median ECE {x['ece'].median():.3f}, "
                             f"median calibration slope {x['cal_slope'].median():.2f} over {len(x)} cities")
    # T14 old vs corrected null
    ref = ap_.get("compare_null_with_archive")
    CMP = pd.DataFrame()
    if ref and len(TOP):
        old_p = os.path.join(out_root, f"archive_{str(ref)[:8]}", SYN_DIR, "T4_top_rung_effects.csv")
        if os.path.exists(old_p):
            old = pd.read_csv(old_p)
            keep_cols = ["city", "metric", "estimate", "ci95_low", "ci95_high", "p_null", "verdict"]
            CMP = TOP[keep_cols].merge(old[keep_cols], on=["city", "metric"], how="outer", suffixes=("", f"_{str(ref)[:8]}"))
            CMP["verdict_changed"] = CMP["verdict"] != CMP[f"verdict_{str(ref)[:8]}"]
            n_ch = int(CMP["verdict_changed"].sum())
            lines.append(f"Null correction: {n_ch} of {len(CMP)} top-rung verdicts differ from the archived run "
                         f"{str(ref)[:8]} (v6.1.1 null, masked cells set to 0); see T14")
        else:
            lines.append(f"Null correction: no archived run {str(ref)[:8]} found in {out_root}, so T14 is empty")
    CMP.to_csv(os.path.join(d, "T14_null_correction_vs_archive.csv"), index=False)
    return ROB, CAL, CMP, lines


def write_outputs_index(states, info, prereg, h, out_root):
    """v6.1.2: outputs/INDEX.md says what every folder and *_ERROR.txt in the outputs folder is, so a reader of the
    repository can tell the analysed study set from folders left by acquisitions of events that are not in it."""
    ap_ = prereg.get("analysis_plan") or {}
    study = list(ap_.get("study_set") or [])
    L = [f"# Contents of this folder (pipeline {PIPELINE_VERSION}, pre-registration {h[:8]})", "",
         "Written automatically by the pipeline after every analysed city.", "",
         "| Folder | In the pre-registered study set | Analysed under this pre-registration | Note |", "|---|---|---|---|"]
    names = sorted(n for n in os.listdir(out_root) if os.path.isdir(os.path.join(out_root, n))
                   and n not in (SYN_DIR,) and not n.startswith("archive_"))
    for n in names:
        st_ = states.get(n)
        cur = bool(info.get(n, {}).get("current")) if st_ is not None else False
        note = ""
        if n not in study:
            att = os.path.join(out_root, n, "label_attempts.json")
            if st_ is None and os.path.exists(att):
                try:
                    a = json.load(open(att))
                    a = a if isinstance(a, list) else a.get("attempts", [])
                    note = ("no usable label: " + "; ".join(f"{x.get('source')}: {str(x.get('error') or 'rejected')[:60]}"
                                                            for x in a[:4]))
                except Exception:  # noqa: BLE001
                    note = "label attempts recorded (unreadable)"
            else:
                note = "acquired for an earlier design; not part of this study and never pooled"
        elif not cur:
            note = "results on disk come from an older pre-registration; re-run before use"
        L.append(f"| {n} | {'yes' if n in study else 'no'} | {'yes' if cur else 'no'} | {note} |")
    errs = sorted(f for f in os.listdir(out_root) if f.endswith("_ERROR.txt"))
    if errs:
        L += ["", "## Error files", "", "A traceback from a failed attempt. If the city was later analysed successfully the "
              "file is kept only as a record.", "", "| File | Written (UTC) | Superseded by a later successful run |", "|---|---|---|"]
        for f in errs:
            c = f[:-len("_ERROR.txt")]
            t_err = dt.datetime.utcfromtimestamp(os.path.getmtime(os.path.join(out_root, f)))
            saved = (states.get(c) or {}).get("saved_utc")
            later = bool(saved and dt.datetime.fromisoformat(str(saved)) > t_err)
            L.append(f"| {f} | {t_err.isoformat(timespec='minutes')} | {'yes' if later else 'no'} |")
    L += ["", "Cross-city tables: `paper_synthesis/` (see RESULTS_SUMMARY.md there). Earlier pre-registrations: "
          "`archive_<sha8>/` and `preregistration_<sha8>.json`; why each changed: `deviations.md`."]
    open(os.path.join(out_root, "INDEX.md"), "w").write("\n".join(L) + "\n")


def write_synthesis(states, prereg, h, out_root, log):
    import matplotlib.pyplot as plt
    ap_ = prereg.get("analysis_plan") or {}
    d = os.path.join(out_root, SYN_DIR)
    os.makedirs(d, exist_ok=True)
    info, sets = _city_sets(states, h, prereg)
    stale = sorted(c for c, v in info.items() if not v["current"])
    outside = sorted(c for c, v in info.items() if not v["in_study"])
    sesoi_ap = float(((ap_.get("sesoi") or {}).get("dAP_stacked_fm")) or sc.SESOI["dAP_stacked_fm"])
    # ---- T1: city characteristics ----------------------------------------------------------------------
    t1 = []
    for c, st_ in sorted(states.items()):
        prov = st_.get("prov") or {}
        loc = prov.get("localisation") or {}
        sA = ((st_.get("results") or {}).get("A_terrain_first") or {}).get("summary")
        top = sA.iloc[-1] if sA is not None and len(sA) else None
        t1.append(dict(city=c, current_prereg=info[c]["current"], gt_tier=st_.get("gt_tier"),
                       label_source=st_.get("effective_label_source") or st_.get("label_source"),
                       grid_m=prov.get("grid_m"), cells_analysed=st_.get("cells_analysed"), positives=st_.get("positives"),
                       prevalence=st_.get("prevalence"), top_rung=None if top is None else top["rung"],
                       AP_top_fm=None if top is None else top.get("AP_recal_fm"),
                       lift_top=None if top is None or not st_.get("prevalence") else top.get("AP_recal_fm") / st_["prevalence"],
                       mentions_primary=loc.get("n_mentions"), effective_locations=loc.get("effective_locations"),
                       top_place=loc.get("top_place"), top_place_share=loc.get("top_share"), localisable=loc.get("eligible"),
                       label_corr_range_m=prov.get("label_corr_range_m"),
                       gazetteer_source=(prov.get("gazetteer") or {}).get("source"),
                       gazetteer_names=(prov.get("gazetteer") or {}).get("names"),
                       social_population_spearman=prov.get("social_population_spearman"),
                       saturation_rung_A=prov.get("saturation_rung_A_terrain_first"),
                       in_study_set=info[c]["in_study"], evaluable_social_layer=info[c]["evaluable"],
                       signal_type=(prov.get("signal_primary") or {}).get("signal_type"),
                       share_news=((prov.get("signal_primary") or {}).get("shares") or {}).get("news"),
                       acquisition_complete=info[c]["acquisition_complete"],
                       label_caveat=prov.get("label_caveat"),
                       cv_tile_m=prov.get("cv_tile_m"),
                       block_covers_label_range=_block_covers_range(prov, prereg),
                       # v6.1.2: which grid the toroidal null shifts (the complete rectangle) and how much of it the
                       # study area and the analysed cells are; "excluded" shares relative to the study area alone
                       # understate how much of the shifted raster lies outside the analysed cells
                       raster_cells=(prov.get("null_raster") or {}).get("raster_cells"),
                       study_area_share_of_raster=(prov.get("null_raster") or {}).get("study_area_share_of_raster"),
                       analysed_share_of_raster=(prov.get("null_raster") or {}).get("analysed_share_of_raster"),
                       null_mode=(prov.get("null_raster") or {}).get("mode", "masked_zero_fill")))
    T1 = pd.DataFrame(t1)
    T1.to_csv(os.path.join(d, "T1_city_characteristics.csv"), index=False)
    # ---- RQ2: per-city gradients + Holm; RQ3: random-effects meta-analysis ------------------------------------
    per_city, meta_rows = [], []
    for ordering in ("A_terrain_first", "B_surface_first"):
        for role, mets in (("primary", CO_PRIMARY), ("robust_excl_R0", CO_PRIMARY),
                           ("headroom_normalised", NORMALISED), ("headroom_normalised_excl_R0", NORMALISED)):
            sr = _slope_rows(states, ordering, role, mets)
            if sr.empty:
                continue
            per_city.append(sr)
            for set_name, members in sets.items():
                for m in mets:
                    x = sr[(sr["metric"] == m) & sr["city"].isin(members)]
                    ma = sc.meta_analysis(x["slope"], x["se"])
                    meta_rows.append(dict(set=set_name, ordering=ordering, role=role, metric=m,
                                          cities=",".join(sorted(x["city"])), **ma))
    PC = pd.concat(per_city, ignore_index=True) if per_city else pd.DataFrame()
    if len(PC):
        prim = sets[CONFIRMATORY]
        fam = (PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary") & PC["city"].isin(prim) & PC["metric"].isin(CO_PRIMARY)
        PC["holm_p_primary_family"] = np.nan
        PC.loc[fam, "holm_p_primary_family"] = sc.holm(PC.loc[fam, "p_one_sided"].to_numpy())
        PC["in_confirmatory_set"] = PC["city"].isin(prim)
        PC["localisable"] = PC["city"].isin(sets[LOCALISABLE])
    PC.to_csv(os.path.join(d, "T2_per_city_gradients.csv"), index=False)
    META = pd.DataFrame(meta_rows)
    META.to_csv(os.path.join(d, "T3_meta_gradients.csv"), index=False)
    # ---- RQ1: operators at the most complete rung ----------------------------------------------------------
    top_rows, top_meta = [], []
    for c, st_ in states.items():
        e = ((st_.get("results") or {}).get("A_terrain_first") or {}).get("effects")
        if e is None or not len(e):
            continue
        last = e[e["rung"] == e["rung"].iloc[-1]]
        for r in last.itertuples():
            d_ = r.sesoi if np.isfinite(r.sesoi) else None
            within = getattr(r, "within_sesoi", None)
            if within is None:          # report states written before v6.1
                within = bool(d_ is not None and np.isfinite(r.ci90_low) and -d_ < r.ci90_low and r.ci90_high < d_)
            reading = getattr(r, "reading", None) or (
                "negligible (non-zero but within SESOI)" if within and r.verdict in ("informative", "harmful")
                else "equivalent to zero (within SESOI)" if within else r.verdict)
            top_rows.append(dict(city=c, rung=r.rung, metric=r.metric, estimate=r.estimate, ci90_low=r.ci90_low,
                                 ci90_high=r.ci90_high, ci95_low=r.ci95_low, ci95_high=r.ci95_high, p_null=r.p_null,
                                 sesoi=r.sesoi, verdict=r.verdict, within_sesoi=bool(within), reading=reading,
                                 evaluable_social_layer=info[c]["evaluable"], se=(r.ci95_high - r.ci95_low) / 3.92))
    TOP = pd.DataFrame(top_rows)
    TOP.to_csv(os.path.join(d, "T4_top_rung_effects.csv"), index=False)
    for set_name, members in sets.items():
        for m in TOP_METRICS:
            x = TOP[(TOP["metric"] == m) & TOP["city"].isin(members)] if len(TOP) else TOP
            if len(x):
                top_meta.append(dict(set=set_name, metric=m, cities=",".join(sorted(x["city"])),
                                     **sc.meta_analysis(x["estimate"], x["se"])))
    TM = pd.DataFrame(top_meta)
    TM.to_csv(os.path.join(d, "T5_meta_top_rung.csv"), index=False)
    # ---- negative control: population-density placebo ----------------------------------------------------------
    pl_rows = []
    for c, st_ in states.items():
        pl = st_.get("placebo")
        if not pl:
            continue
        real = _slope_rows({c: st_}, "A_terrain_first", "primary", CO_PRIMARY)
        fake = _slope_rows({c: st_}, "A_terrain_first", "primary", CO_PRIMARY, tag="placebo")
        ce = pl.get("control_effects")
        for m in CO_PRIMARY:
            a = real[real["metric"] == m]
            b = fake[fake["metric"] == m]
            if a.empty or b.empty:
                continue
            row = dict(city=c, metric=m, real_slope=a["slope"].iloc[0], real_se=a["se"].iloc[0],
                       placebo_slope=b["slope"].iloc[0], placebo_se=b["se"].iloc[0],
                       spearman_social_population=pl.get("spearman_social_pop"))
            row["difference"] = row["real_slope"] - row["placebo_slope"]
            row["difference_se_approx"] = float(np.hypot(row["real_se"], row["placebo_se"]))
            if ce is not None and len(ce):
                cm = ce[ce["metric"] == ("info_frac_fm" if m.startswith("info") else "dAP_stacked_fm")]
                if len(cm):
                    row.update(control_top_estimate=cm["estimate"].iloc[0], control_top_ci95_low=cm["ci95_low"].iloc[0],
                               control_top_ci95_high=cm["ci95_high"].iloc[0], control_top_verdict=cm["verdict"].iloc[0])
            pl_rows.append(row)
    PL = pd.DataFrame(pl_rows)
    PL.to_csv(os.path.join(d, "T6_density_placebo.csv"), index=False)
    pl_meta = []
    for set_name, members in sets.items():
        for m in CO_PRIMARY:
            x = PL[(PL["metric"] == m) & PL["city"].isin(members)] if len(PL) else PL
            if len(x):
                pl_meta.append(dict(set=set_name, metric=m, quantity="placebo slope", **sc.meta_analysis(x["placebo_slope"], x["placebo_se"])))
                pl_meta.append(dict(set=set_name, metric=m, quantity="real minus placebo slope",
                                    **sc.meta_analysis(x["difference"], x["difference_se_approx"])))
    pd.DataFrame(pl_meta).to_csv(os.path.join(d, "T7_meta_density_placebo.csv"), index=False)
    # ---- RQ3 moderator (confirmatory, v6): localisation of the social layer ---------------------------------------
    # label-free moderator = log effective number of mention locations in the primary window; outcomes = the per-city
    # gradient slopes (co-primary) and the top-rung effects (RQ1 metrics); confirmatory set only
    mod_rows = []
    conf = sets[CONFIRMATORY]
    if len(T1):
        loc = T1.set_index("city")
        logeff = lambda cities: np.log(pd.to_numeric(loc.reindex(cities)["effective_locations"], errors="coerce").clip(lower=1.0))

        def _mod(analysis, outcome, x, ycol, modname="log_effective_locations", vals=None, influence=False):
            xv = logeff(x["city"]).to_numpy() if vals is None else np.asarray(vals, float)
            row = dict(analysis=analysis, outcome=outcome, moderator=modname, cities=",".join(sorted(x["city"])),
                       **sc.meta_regression(x[ycol], x["se"], xv))
            if influence:
                row.update(sc.metareg_influence(x[ycol], x["se"], xv, x["city"]))
            mod_rows.append(row)
        # the evaluable set repeats the confirmatory tests without the cities that have no usable social layer
        # (v6.1, added after the v6.0 results were seen: a sensitivity analysis, never the headline)
        for analysis, members, infl in (("confirmatory", conf, True),
                                        ("sensitivity: evaluable social layer", sets[EVALUABLE], False)):
            if analysis != "confirmatory" and members == conf:
                continue
            if len(PC):
                base = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary") & PC["city"].isin(members)]
                for m in CO_PRIMARY:
                    _mod(analysis, f"gradient slope {m}", base[base["metric"] == m], "slope", influence=infl)
            if len(TOP):
                for m in TOP_METRICS:
                    _mod(analysis, f"top-rung {m}", TOP[(TOP["metric"] == m) & TOP["city"].isin(members)], "estimate",
                         influence=infl)
        if len(PC):
            base = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary")].merge(T1, on="city", how="left")
            for m in CO_PRIMARY:
                x = base[(base["metric"] == m) & base["city"].isin(conf)]
                for mod, vals in [("physical_lift_top_rung", pd.to_numeric(x["lift_top"], errors="coerce")),
                                  ("log_mentions", np.log(pd.to_numeric(x["mentions_primary"], errors="coerce").clip(lower=1)))]:
                    _mod("exploratory", f"gradient slope {m}", x, "slope", modname=mod, vals=vals.to_numpy())
    MOD = pd.DataFrame(mod_rows)
    if len(MOD):
        # v6.1: the confirmatory moderator is tested on several outcomes (2 slopes + 5 top-rung effects); v6.0
        # reported each permutation p on its own. Holm across that family, on the p-value that is reported
        # (permutation p for k < 10, as pre-registered).
        MOD["p_holm_family"] = np.nan
        fam = MOD["analysis"] == "confirmatory"
        MOD.loc[fam, "p_holm_family"] = sc.holm(MOD.loc[fam, "p_perm"].where(MOD.loc[fam, "p_perm"].notna(), MOD.loc[fam, "p"]).to_numpy())
        MOD["family_size"] = np.where(fam, int(fam.sum()), np.nan)
    MOD.to_csv(os.path.join(d, "T8_meta_regression_localisation.csv"), index=False)
    # ---- T11 (v6.1): who carries each pooled estimate (confirmatory set; weights and leave-one-out) -----------------
    infl = []
    if len(TOP):
        for m in TOP_METRICS:
            x = TOP[(TOP["metric"] == m) & TOP["city"].isin(conf)]
            if len(x) >= 3:
                infl.append(sc.meta_influence(x["estimate"], x["se"], x["city"]).assign(quantity=f"top-rung {m}"))
    if len(PC):
        base = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary") & PC["city"].isin(conf)]
        for m in CO_PRIMARY:
            x = base[base["metric"] == m]
            if len(x) >= 3:
                infl.append(sc.meta_influence(x["slope"], x["se"], x["city"]).assign(quantity=f"gradient slope {m}"))
    INFL = pd.concat(infl, ignore_index=True) if infl else pd.DataFrame()
    if len(INFL):
        INFL = INFL[["quantity"] + [c_ for c_ in INFL.columns if c_ != "quantity"]]
    INFL.to_csv(os.path.join(d, "T11_influence_leave_one_out.csv"), index=False)
    ROB, CAL, CMP, rob_lines = _robustness_tables(states, info, sets, TOP, PC, T1, prereg, out_root, d)
    # ---- T9: localisation audit (label-free; every city) ---------------------------------------------------------------
    t9 = []
    for c, st_ in sorted(states.items()):
        prov = st_.get("prov") or {}
        loc_ = prov.get("localisation") or {}
        docs_ = prov.get("documents") or {}
        top_ = prov.get("toponyms") or {}
        t9.append(dict(city=c, gt_tier=st_.get("gt_tier"), documents_kept=docs_.get("kept_total"),
                       documents_by_source=json.dumps(docs_.get("kept_by_source", {}), sort_keys=True),
                       mentions_primary=loc_.get("n_mentions"), by_resolution=json.dumps(loc_.get("via", {}), sort_keys=True),
                       distinct_locations=loc_.get("distinct_locations"), effective_locations=loc_.get("effective_locations"),
                       top_place=loc_.get("top_place"), top_share=loc_.get("top_share"), top5=json.dumps(loc_.get("top5", [])),
                       localisable=loc_.get("eligible"), gazetteer_names=(prov.get("gazetteer") or {}).get("names"),
                       toponym_candidates_dropped=top_.get("dropped"),
                       signal_type=(prov.get("signal_primary") or {}).get("signal_type"),
                       mention_shares_by_kind=json.dumps((prov.get("signal_primary") or {}).get("shares", {}), sort_keys=True),
                       sources_switched_off=",".join(docs_.get("sources_switched_off", []) or []),
                       evaluable_social_layer=info[c]["evaluable"],
                       acquisition_rules=(prov.get("acquisition_status") or {}).get("rules"),
                       acquisition_complete=info[c]["acquisition_complete"],
                       acquisition_pending=" | ".join((prov.get("acquisition_status") or {}).get("pending", []) or []),
                       geocoder_calls=(prov.get("geocoding") or {}).get("geocoder_calls"),
                       lookups_not_done=(prov.get("geocoding") or {}).get("lookups_capped"),
                       ner_candidates_rejected=(prov.get("geocoding") or {}).get("ner_candidates_rejected")))
    pd.DataFrame(t9).to_csv(os.path.join(d, "T9_localisation_audit.csv"), index=False)
    # ---- T10: sensitivity roll-up (top rung, every variant incl. learner family) --------------------------------------
    t10 = []
    keep_cols = ["rung", "AP_recal_fm", "info_nats_fm_adj", "info_frac_fm_adj", "dAP_stacked_fm_adj", "dAP_gated_fm",
                 "dAP_early_fm_adj", "dAP_adr_legacy_fm", "variant", "gate_alpha_median", "gate_off_share"]
    for c, st_ in sorted(states.items()):
        for sdf in st_.get("sens") or []:
            if sdf is None or not len(sdf):
                continue
            x = sdf[[k_ for k_ in keep_cols if k_ in sdf.columns]].copy()
            x.insert(0, "city", c)
            # v6.1: how far each variant moves the co-primary top-rung effect, and whether it flips its sign by more
            # than the SESOI (Emilia-Romagna's -0.136 AP became +0.004 at the 1,000 m bandwidth in the v6.0 run)
            sA_ = ((st_.get("results") or {}).get("A_terrain_first") or {}).get("summary")
            if sA_ is not None and len(sA_) and "dAP_stacked_fm_adj" in sA_.columns and "dAP_stacked_fm_adj" in x.columns:
                prim_ = float(sA_["dAP_stacked_fm_adj"].iloc[-1])
                v_ = pd.to_numeric(x["dAP_stacked_fm_adj"], errors="coerce")
                x["primary_dAP_stacked_fm_adj"] = prim_
                x["delta_vs_primary"] = v_ - prim_
                x["unstable"] = ((np.sign(v_) != np.sign(prim_)) & ((v_ - prim_).abs() > sesoi_ap)) | ((v_ - prim_).abs() > 5 * sesoi_ap)
            t10.append(x)
    pd.concat(t10, ignore_index=True).to_csv(os.path.join(d, "T10_sensitivity_top_rung.csv"), index=False) if t10 else None
    # ---- forest plot (primary ordering, co-primary metrics) ------------------------------------------------------
    try:
        if len(PC):
            fig, axes = plt.subplots(1, 2, figsize=(9.0, 0.45 * max(4, PC["city"].nunique()) + 1.6), squeeze=False)
            prim = sets[CONFIRMATORY]
            for ax, m, lab in zip(axes[0], CO_PRIMARY, ["information gain (nats) per unit physical AP",
                                                        "ΔAP (stacked) per unit physical AP"]):
                x = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary") & (PC["metric"] == m)
                       & PC["city"].map(lambda c_: info.get(c_, {}).get("current", False))].sort_values("city")
                ys = np.arange(len(x))[::-1] + 1
                for yy, r in zip(ys, x.itertuples()):
                    filled = r.city in sets[LOCALISABLE]
                    ax.errorbar(r.slope, yy, xerr=[[max(0.0, r.slope - r.ci_low)], [max(0.0, r.ci_high - r.slope)]], fmt="o" if filled else "o",
                                mfc="k" if filled else "white", mec="k", ecolor="k", capsize=2, ms=4)
                mm = META[(META["set"] == CONFIRMATORY) & (META["ordering"] == "A_terrain_first")
                          & (META["role"] == "primary") & (META["metric"] == m)]
                if len(mm) and np.isfinite(mm["estimate"].iloc[0]):
                    e, lo_, hi_ = mm["estimate"].iloc[0], mm["ci_low"].iloc[0], mm["ci_high"].iloc[0]
                    if np.isfinite(lo_):
                        ax.fill([lo_, e, hi_, e], [0, 0.25, 0, -0.25], color="0.3")
                    else:
                        ax.plot([e], [0], "D", color="0.3")
                ax.axvline(0, color="k", lw=0.6, ls=":")
                ax.set_yticks(list(ys) + [0]); ax.set_yticklabels(list(x["city"]) + [f"pooled (k={int(mm['k'].iloc[0]) if len(mm) else 0})"], fontsize=7)
                ax.set_xlabel(f"gradient slope: {lab}", fontsize=8)
            fig.suptitle("Saturation gradient per city (ordering A; filled = localisable social layer; pooled = tier A, all; 95% CIs)", fontsize=9)
            fig.tight_layout()
            fig.savefig(os.path.join(d, "fig_forest_gradients.png"), dpi=300); fig.savefig(os.path.join(d, "fig_forest_gradients.pdf"))
            plt.close(fig)
    except Exception as e:  # noqa: BLE001
        log("(all)", "synthesis:figure", "warn", f"forest plot failed: {e}")
    # ---- LaTeX tables + macros ------------------------------------------------------------------------------------
    def tex(df, name, cols):
        cols = [c for c in cols if c in df.columns]
        if not len(df) or not cols:
            return
        t = df[cols].copy()
        for c in t.columns:
            if t[c].dtype == object:
                t[c] = t[c].astype(str).str.replace("_", r"\_", regex=False)
        with open(os.path.join(d, name), "w") as fh:
            fh.write(t.to_latex(index=False, escape=False, float_format=lambda v: sc.fmt_num(v, 3)))
    tex(T1, "T1_city_characteristics.tex", ["city", "gt_tier", "grid_m", "cells_analysed", "prevalence", "AP_top_fm",
                                            "lift_top", "mentions_primary", "effective_locations", "localisable"])
    tex(META[(META["ordering"] == "A_terrain_first")] if len(META) else META, "T3_meta_gradients.tex",
        ["set", "role", "metric", "k", "estimate", "ci_low", "ci_high", "p_one_sided_lt0", "tau2", "I2"])
    tex(TM, "T5_meta_top_rung.tex", ["set", "metric", "k", "estimate", "ci_low", "ci_high", "p_two_sided", "I2"])
    tex(MOD, "T8_meta_regression_localisation.tex", ["analysis", "outcome", "moderator", "k", "slope", "slope_se", "p", "p_perm",
                                                     "p_holm_family", "loo_slope_min", "loo_slope_max", "most_influential_city"])
    tex(INFL, "T11_influence_leave_one_out.tex", ["quantity", "city", "weight", "estimate", "loo_estimate", "loo_ci_low", "loo_ci_high"])
    macros = [f"% {PIPELINE_VERSION} synthesis, prereg {h[:8]}, generated {dt.datetime.utcnow().isoformat()}Z"]
    for r in (MOD[MOD["analysis"] == "confirmatory"].itertuples() if len(MOD) else []):
        mk = {"gradient slope info_nats_fm_adj": "GradInfo", "gradient slope dAP_stacked_fm_adj": "GradStacked",
              "top-rung info_frac_fm": "TopInfoFrac", "top-rung dAP_stacked_fm": "TopStacked", "top-rung dAP_gated_fm": "TopGated",
              "top-rung dAP_early_fm": "TopEarly", "top-rung dAP_adr_legacy_fm": "TopLegacy"}.get(r.outcome)
        if mk and np.isfinite(r.slope):
            macros.append(sc.latex_macros(f"ModLoc{mk}", {"K": int(r.k), "Slope": r.slope, "Se": r.slope_se, "P": r.p,
                                                          "Pperm": r.p_perm, "Pholm": getattr(r, "p_holm_family", np.nan)}))
    for set_key, sk in [(CONFIRMATORY, "Conf"), (LOCALISABLE, "Loc"), (EVALUABLE, "Eval")]:
        for role, rk in [("primary", ""), ("headroom_normalised", "Norm"), ("robust_excl_R0", "ExclRzero")]:
            for m, mk in [("info_nats_fm_adj", "Info"), ("dAP_stacked_fm_adj", "Stacked"),
                          ("info_frac_fm_adj", "Info"), ("dAPh_fm_adj", "Stacked")]:
                x = META[(META["set"] == set_key) & (META["ordering"] == "A_terrain_first") & (META["role"] == role)
                         & (META["metric"] == m)] if len(META) else META
                if len(x):
                    r = x.iloc[0]
                    macros.append(sc.latex_macros(f"Meta{sk}{rk}{mk}", {"K": int(r["k"]), "Est": r["estimate"], "Lo": r["ci_low"],
                                                                     "Hi": r["ci_high"], "P": r["p_one_sided_lt0"],
                                                                     "Isq": r["I2"], "Tau": r["tau2"]}))
    for m, mk in [("dAP_adr_legacy_fm", "Legacy"), ("dAP_gated_fm", "Gated"), ("dAP_stacked_fm", "Stacked"),
                  ("dAP_early_fm", "Early"), ("info_frac_fm", "InfoFrac")]:
        x = TM[(TM["set"] == CONFIRMATORY) & (TM["metric"] == m)] if len(TM) else TM
        if len(x):
            r = x.iloc[0]
            macros.append(sc.latex_macros(f"TopTierA{mk}", {"K": int(r["k"]), "Est": r["estimate"], "Lo": r["ci_low"],
                                                             "Hi": r["ci_high"], "P": r["p_two_sided"]}))
    for m, mk in [("dAP_adr_legacy_fm", "Legacy"), ("dAP_gated_fm", "Gated"), ("dAP_stacked_fm", "Stacked"),
                  ("dAP_early_fm", "Early"), ("info_frac_fm", "InfoFrac")]:
        x = TM[(TM["set"] == EVALUABLE) & (TM["metric"] == m)] if len(TM) else TM
        if len(x):
            r = x.iloc[0]
            macros.append(sc.latex_macros(f"TopEval{mk}", {"K": int(r["k"]), "Est": r["estimate"], "Lo": r["ci_low"],
                                                           "Hi": r["ci_high"], "P": r["p_two_sided"]}))
    macros.append(sc.latex_macros("Cities", {"Total": len(states), "Current": sum(v["current"] for v in info.values()),
                                              "Confirmatory": len(sets[CONFIRMATORY]),
                                              "Evaluable": len(sets[EVALUABLE]),
                                              "Localisable": len(sets[LOCALISABLE])}))
    open(os.path.join(d, "synthesis_macros.tex"), "w").write("\n".join(macros) + "\n")
    # ---- plain-language summary for the manuscript update --------------------------------------------------------
    L = [f"# Synthesis (pipeline {PIPELINE_VERSION}, pre-registration {h[:8]})", ""]
    if ap_.get("study_set"):
        L.append(f"Study set (pre-registration): {len(ap_['study_set'])} cities: {', '.join(ap_['study_set'])}")
        missing = [c for c in ap_["study_set"] if c not in states or not info.get(c, {}).get("current")]
        if missing:
            L.append(f"**NOT YET ANALYSED under this pre-registration: {', '.join(missing)}. Every pooled number below "
                     f"is provisional until they are.**")
    if stale:
        L.append(f"Not in any pooled set (computed under an older pre-registration, re-run them): {', '.join(stale)}")
    if outside:
        L.append(f"Not in any pooled set (outside the study set): {', '.join(outside)}")
    for k_, v_ in sets.items():
        L.append(f"- set '{k_}': {len(v_)} cities: {', '.join(sorted(v_)) or '-'}")
    L.append("")
    # v6.1: what the layer is, and which cities' numbers must not be read as findings
    if len(T1):
        L.append("## Read this first")
        for r in T1.itertuples():
            notes = []
            if getattr(r, "signal_type", None):
                notes.append(f"layer = {r.signal_type}")
            if not r.evaluable_social_layer:
                notes.append(f"NO EVALUABLE SOCIAL LAYER ({0 if pd.isna(r.mentions_primary) else int(r.mentions_primary)} located mentions): "
                             f"its social effects are noise")
            if not r.current_prereg:
                notes.append("NOT YET ANALYSED under this pre-registration: the numbers shown for it come from an "
                             "older run (its acquisition may be fine)")
            elif not r.acquisition_complete:
                notes.append("ACQUISITION INCOMPLETE OR UNDER OLDER RULES: re-acquire before use")
            if isinstance(r.label_caveat, str) and r.label_caveat:
                notes.append(f"label caveat: {r.label_caveat}")
            if notes:
                L.append(f"- {r.city}: " + "; ".join(notes))
        L.append("- Verdicts are the pre-registered ones. 'reading' adds whether the whole 90% interval lies inside the "
                 "SESOI: an effect can be non-zero and still negligible.")
        L.append("- A pooled interval inside the SESOI is not evidence from every city: see the weights and "
                 "leave-one-out estimates in T11 before describing any pooled result.")
        L.append("")
    if len(META):
        for role in ("primary", "headroom_normalised", "robust_excl_R0"):
            x = META[(META["set"] == CONFIRMATORY) & (META["ordering"] == "A_terrain_first") & (META["role"] == role)]
            for r in x.itertuples():
                L.append(f"RQ3 pooled slope [{role}] {r.metric}: {r.estimate:+.4f} (95% CI {r.ci_low:+.4f} to {r.ci_high:+.4f}; "
                         f"one-sided p (H1: slope < 0)={r.p_one_sided_lt0:.4f}; k={r.k}; I2={r.I2:.2f}; tau2={r.tau2:.4g}; "
                         f"PI {r.pi_low:+.3f} to {r.pi_high:+.3f})")
    if len(MOD):
        L.append("")
        for r in MOD.itertuples():
            line = (f"RQ3 moderator [{r.analysis}] {r.outcome} ~ {r.moderator}: slope {r.slope:+.4f} (SE {r.slope_se:.4f}; "
                    f"KH p={r.p:.4f}; permutation p={r.p_perm:.4f}; k={r.k})")
            if r.analysis == "confirmatory":
                line += f"; Holm p across the {int(r.family_size)} confirmatory moderator tests={r.p_holm_family:.4f}"
                if isinstance(getattr(r, "most_influential_city", ""), str) and r.most_influential_city:
                    line += (f"; leave-one-out slope {r.loo_slope_min:+.4f} to {r.loo_slope_max:+.4f} "
                             f"(sign {'stable' if r.loo_sign_stable else 'NOT stable'}; most influential {r.most_influential_city}, "
                             f"slope without it {r.slope_without_it:+.4f})")
            L.append(line)
    if len(INFL):
        L.append("")
        for q, x in INFL.groupby("quantity", sort=False):
            x = x.sort_values("weight", ascending=False)
            top2 = x.head(2)
            L.append(f"Influence {q}: {', '.join(f'{c_} {w_:.0%}' for c_, w_ in zip(top2['city'], top2['weight']))} of the pooled weight; "
                     f"leave-one-out estimate from {x['loo_estimate'].min():+.4f} to {x['loo_estimate'].max():+.4f} "
                     f"(all cities {x['full_estimate'].iloc[0]:+.4f} [{x['full_ci_low'].iloc[0]:+.4f}, {x['full_ci_high'].iloc[0]:+.4f}])")
    if len(TM):
        L.append("")
        for r in TM[TM["set"].isin([CONFIRMATORY, EVALUABLE])].itertuples():
            L.append(f"RQ1 pooled top rung [{r.set}] {r.metric}: {r.estimate:+.4f} (95% CI {r.ci_low:+.4f} to {r.ci_high:+.4f}; k={r.k}; I2={r.I2:.2f})")
    if len(PC):
        L.append("")
        x = PC[(PC["ordering"] == "A_terrain_first") & (PC["role"] == "primary")]
        for r in x.itertuples():
            L.append(f"RQ2 {r.city} {r.metric}: slope {r.slope:+.4f} [{r.ci_low:+.4f}, {r.ci_high:+.4f}], one-sided p={r.p_one_sided:.4f}"
                     + (f", Holm p={r.holm_p_primary_family:.4f}" if np.isfinite(r.holm_p_primary_family) else " (not in the confirmatory family)"))
    if len(TOP):
        L.append("")
        for r in TOP.itertuples():
            L.append(f"RQ1 {r.city} {r.rung} {r.metric}: {r.estimate:+.4f} [{r.ci95_low:+.4f}, {r.ci95_high:+.4f}] -> {r.verdict}"
                     + (f" | reading: {r.reading}" if r.reading != r.verdict else "")
                     + ("" if r.evaluable_social_layer else " | no evaluable social layer"))
    if len(PL):
        L.append("")
        for r in PL.itertuples():
            L.append(f"Placebo {r.city} {r.metric}: real slope {r.real_slope:+.4f} vs population-density slope {r.placebo_slope:+.4f}; "
                     f"Spearman(social, population) {r.spearman_social_population:.2f}"
                     + (f"; social gain with population controlled at top rung {r.control_top_estimate:+.4f} "
                        f"[{r.control_top_ci95_low:+.4f}, {r.control_top_ci95_high:+.4f}] {r.control_top_verdict}"
                        if "control_top_estimate" in PL.columns and pd.notna(getattr(r, "control_top_estimate", np.nan)) else ""))
    if rob_lines:
        L += ["", "## Post-hoc robustness and diagnostics (v6.1.2; not pre-registered, never a headline)"] + rob_lines
    open(os.path.join(d, "RESULTS_SUMMARY.md"), "w").write("\n".join(L) + "\n")
    try:
        write_outputs_index(states, info, prereg, h, out_root)
    except Exception as e:  # noqa: BLE001
        log("(all)", "synthesis", "warn", f"INDEX.md not written: {e}")
    log("(all)", "synthesis", "ok", f"{len(states)} cities ({sum(v['current'] for v in info.values())} under the current "
                                    f"pre-registration); confirmatory k={len(sets[CONFIRMATORY])}, evaluable k={len(sets[EVALUABLE])}, "
                                    f"localisable k={len(sets[LOCALISABLE])} -> {SYN_DIR}/")
    return META
