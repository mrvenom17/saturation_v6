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

    # v6.1.2: the complete rasters of every social channel, which the toroidal null shifts. They are rebuilt from the
    # stored mentions (no network); null_rasters_for checks that they reproduce the channels at the analysed cells.
    _ch2, _, soc_rasters = ds.social_channels(G, df, m_primary, sp["kde_bandwidth_m"], sp["min_source_mentions"],
                                              return_rasters=True)
    for k_ in channels:
        if k_ not in soc_rasters or not np.allclose(np.asarray(_ch2[k_], float), np.asarray(channels[k_], float),
                                                   rtol=1e-9, atol=1e-9):
            raise RuntimeError(f"{city}: the social channel {k_} cannot be rebuilt from the stored mentions, so its "
                               f"null cannot be built; re-acquire this city")

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
    null_mode = (prereg.get("inference") or {}).get("null_mode", "masked_zero_fill")
    rc_ = (data["row"].to_numpy(), data["col"].to_numpy(), G.nr, G.nc)

    def _meta(rasters):
        return rc_ + (dict(rasters),) if null_mode == "full_raster" else rc_
    meta = _meta(soc_rasters)
    prov["null_raster"] = dict(null_raster_coverage(G, df_full, data), mode=null_mode)
    log(city, "null", "info", f"toroidal null ({null_mode}): shifts the complete {G.nr} x {G.nc} rectangle; study area "
                              f"{prov['null_raster']['study_area_share_of_raster']:.0%} and analysed cells "
                              f"{prov['null_raster']['analysed_share_of_raster']:.0%} of it")
    cfgL = sc.LadderConfig(k_folds=prereg["cv"]["k_folds"], tile_m=tile_m, buffer_m=prereg["cv"]["buffer_m"],
                           inner_k=prereg["cv"]["inner_k"], seed=prereg["cv"]["seed"], n_boot=P["n_boot"], n_null=P["n_null"],
                           null_min_shift_m=prereg["inference"]["null_min_shift_m"],
                           grid_m=int(cfg.get("grid_m", prereg["grid_m"])), null_mode=null_mode)
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
    # v6.1.2 (post hoc, from the saved out-of-fold scores; nothing is refitted): calibration at the top rung
    calibration = None
    try:
        resA = results["A_terrain_first"]
        topA = resA["results"][-1]
        calibration = sc.calibration_table(y, topA["scores"], resA["fold"]).assign(rung=topA["rung"])
        calibration.to_csv(os.path.join(out, "calibration_top_rung.csv"), index=False)
    except Exception as e:  # noqa: BLE001
        log(city, "calibration", "warn", f"calibration diagnostics failed: {e}")
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
        variants, vmeta = [], {}
        ch_bw, _, r_bw = ds.social_channels(G, df_full, m_primary, sp["sensitivity_bandwidth_m"], 10**9, return_rasters=True)
        variants.append(("bandwidth_1000m", data.assign(S_mentions=np.asarray(ch_bw["S_mentions"])[keep])))
        vmeta["bandwidth_1000m"] = _meta({"S_mentions": r_bw["S_mentions"]})
        ch_w, _, r_w = ds.social_channels(G, df_full, mentions, sp["kde_bandwidth_m"], 10**9, return_rasters=True)
        variants.append(("window_minus3_plus3", data.assign(S_mentions=np.asarray(ch_w["S_mentions"])[keep])))
        vmeta["window_minus3_plus3"] = _meta({"S_mentions": r_w["S_mentions"]})
        if len(m_primary) and m_primary["source"].isin(ds.PHOTO_SOURCES).any():
            # timeliness check (v6): photos are often uploaded after the event, so the layer is rebuilt without them
            ch_np, _, r_np = ds.social_channels(G, df_full, m_primary[~m_primary["source"].isin(ds.PHOTO_SOURCES)],
                                                sp["kde_bandwidth_m"], 10**9, return_rasters=True)
            variants.append(("without_photos", data.assign(S_mentions=np.asarray(ch_np["S_mentions"])[keep])))
            vmeta["without_photos"] = _meta({"S_mentions": r_np["S_mentions"]})
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
            metaV = vmeta.get(name, meta)
            r = st.get(f"sens_{name}_{profile}_{fpd}_{STAGE_CODE['analysis']}_{kcv}_{specV.kind}",
                        lambda: sc.run_ladder(d, [full_rung], ["S_mentions"], specV, cfgV, metaV, log=lambda s: None,
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
            smooth_ras = _smooth_density_raster(dens, df_full, G, sp["kde_bandwidth_m"])
            smooth = smooth_ras[df_full["row"].to_numpy(), df_full["col"].to_numpy()]
            data_p = data.assign(pop_log=np.log1p(dens[keep]), S_placebo_pop=smooth[keep])
            meta_p = _meta({"S_placebo_pop": smooth_ras, "S_mentions": soc_rasters["S_mentions"]})
            rho = float(pd.Series(data_p["S_placebo_pop"]).corr(data["S_mentions"], method="spearman"))
            prov["social_population_spearman"] = rho
            log(city, "placebo", "info", f"social layer vs population-density layer: Spearman {rho:.2f}")
            cfgP = dataclasses.replace(cfgL, run_early_fusion=False, run_legacy_adr=False)
            ladA = build_ladder(prereg, "A_terrain_first", set(phys.columns), eff_source, log, city)
            fpp = sc.data_fingerprint(data_p, list(phys.columns) + ["S_placebo_pop"])
            rp = st.get(f"placebo_pop_{profile}_{fpp}_{STAGE_CODE['analysis']}_{kcv}",
                        lambda: sc.run_ladder(data_p, ladA, ["S_placebo_pop"], spec, cfgP, meta_p,
                                              log=lambda s_: log(city, "rung:placebo", "info", s_.strip()),
                                              rung_cache=st.rung_cache("placebo")))
            rp = _augment(dict(rp), prereg, log, city, "placebo_population_A")
            save_tables(out, "placebo_population_A", rp)
            # control: the real social layer's gain when population density is part of the physical model
            ctrl = [(full_rung[0] + "+population", list(full_rung[1]) + ["pop_log"])]
            fpc = sc.data_fingerprint(data_p, ctrl[0][1] + ["S_mentions"])
            rc = st.get(f"control_pop_{profile}_{fpc}_{STAGE_CODE['analysis']}_{kcv}",
                        lambda: sc.run_ladder(data_p, ctrl, ["S_mentions"], spec, cfgP, meta_p, log=lambda s_: None,
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
                placebo=placebo, calibration=calibration,
                positives=int(y.sum()), prevalence=float(y.mean()), label_source=label_source, social=cstats,
                cells_analysed=int(len(data)), gt_tier=gt_tier, effective_label_source=eff_source)


# ---------------------------------------------------------------- figures / tables
def make_city_maps(city, G, data, res, out):
    import matplotlib.pyplot as plt
    last = res["results"][-1]
    panels = [("Labels (flooded cells)", data["flooded"].to_numpy(), "Blues"),
              (f"Physical OOF risk ({last['rung']})", last["scores"]["physical"], "viridis"),
              ("Social layer: log1p mentions/km²", data["S_mentions"].to_numpy(), "magma")]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
    for ax, (title, vals, cmap) in zip(axes, panels):
        ras = ph.cells_to_raster(vals, data, G)
        im = ax.imshow(ras, cmap=cmap, interpolation="nearest")
        ax.set_title(title, fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    fig.suptitle(f"{city} — 100 m grid ({G.crs})", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_maps.png"), dpi=250)
    fig.savefig(os.path.join(out, "fig_maps.pdf"))
    plt.close(fig)


def write_report(city_results, prereg, profile, out_root, log):
    import matplotlib.pyplot as plt
    P = PROFILES[profile]
    ok = [r for r in city_results if r.get("results")]
    macros = [f"% Auto-generated by saturation pipeline {PIPELINE_VERSION}. Do not edit by hand.",
              f"% profile: {P['label']}", f"% generated {dt.datetime.utcnow().isoformat()}Z"]
    rows = []
    if ok:
        fig, axes = plt.subplots(len(ok), 2, figsize=(7.4, 3.0 * len(ok)), squeeze=False)
    for i, r in enumerate(ok):
        cc = city_code(r["city"])
        macros.append(sc.latex_macros(cc, {"Cells": r["prov"]["n_cells"], "Positives": r["positives"], "Prevalence": r["prevalence"],
                                           "LabelSource": r["label_source"], "Mentions": r["social"].get("mentions", 0),
                                           "SignalCells": r["social"].get("cells_with_signal", 0)}, nd=4))
        for j, (ordering, res) in enumerate(r["results"].items()):
            oc = ordering[0]
            s, g_all = res["summary"], res["gradient"]
            # primary/secondary rows are unique per metric; robustness rows repeat metric names, so keep them apart
            g = g_all[g_all["role"] != "robust_excl_R0"].set_index("metric")
            g_rob = g_all[g_all["role"] == "robust_excl_R0"].set_index("metric")
            ax = axes[i, j]
            # primary axes: per-fold physical skill vs per-fold, null-centred social gain
            xk = "AP_recal_fm" if "AP_recal_fm" in s else "AP_recal"
            yk = "dAP_stacked_fm_adj" if "dAP_stacked_fm_adj" in s else "dAPh_stacked"
            bk = yk[:-4] if yk.endswith("_adj") else yk
            x, yv = s[xk], s[yk]
            ylo = s.get(f"{bk}_lo"); yhi = s.get(f"{bk}_hi"); xlo = s.get(f"{xk}_lo"); xhi = s.get(f"{xk}_hi")
            shift = (s[bk] - s[yk]) if yk.endswith("_adj") else 0.0
            kw = {}
            if ylo is not None and yhi is not None:
                kw["yerr"] = [(yv - (ylo - shift)).clip(lower=0), ((yhi - shift) - yv).clip(lower=0)]
            if xlo is not None and xhi is not None:
                kw["xerr"] = [(x - xlo).clip(lower=0), (xhi - x).clip(lower=0)]
            ax.errorbar(x, yv, fmt="o-", ms=3, lw=1, capsize=2, label="stacked (R,S), null-centred", **kw)
            if "dAP_early_fm_adj" in s:
                ax.plot(x, s["dAP_early_fm_adj"], "^:", ms=3, lw=1, label="early fusion, null-centred")
            ax.plot(x, s.get("dAP_gated_fm", s["dAP_gated"]), "s--", ms=3, lw=1, label="gated, corrected")
            ax.axhline(0, color="k", lw=0.6)
            for xx, yy, rn in zip(x, yv, s["rung"]):
                ax.annotate(rn.split("_")[0], (xx, yy), fontsize=6, xytext=(2, 2), textcoords="offset points")
            ax.set_title(f"{r['city']} — ordering {oc}", fontsize=9)
            ax.set_xlabel("held-out physical AP (per-fold mean)")
            ax.set_ylabel("ΔAP from the social layer\n(per-fold, minus spatial-null mean)")
            if i == 0 and j == 0:
                ax.legend(fontsize=7)
            def gval(metric, field, default=np.nan):
                return g.loc[metric, field] if metric in g.index else default
            macros.append(sc.latex_macros(f"{cc}{oc}Slope", {
                # primary (per-fold, null-centred)
                "Stacked": gval("dAP_stacked_fm_adj", "slope"), "StackedLo": gval("dAP_stacked_fm_adj", "slope_ci_low"),
                "StackedHi": gval("dAP_stacked_fm_adj", "slope_ci_high"),
                "StackedP": gval("dAP_stacked_fm_adj", "p_one_sided_slope_ge_0"),
                "Info": gval("info_nats_fm_adj", "slope"), "InfoLo": gval("info_nats_fm_adj", "slope_ci_low"),
                "InfoHi": gval("info_nats_fm_adj", "slope_ci_high"),
                "InfoP": gval("info_nats_fm_adj", "p_one_sided_slope_ge_0"),
                "Early": gval("dAP_early_fm_adj", "slope"), "EarlyP": gval("dAP_early_fm_adj", "p_one_sided_slope_ge_0"),
                # secondary (pooled; the headroom denominator amplifies late rungs)
                "PooledInfo": gval("info_nats", "slope"), "PooledInfoP": gval("info_nats", "p_one_sided_slope_ge_0"),
                "Headroom": gval("dAPh_stacked", "slope"), "HeadroomP": gval("dAPh_stacked", "p_one_sided_slope_ge_0"),
                # robustness: primary gradients without the empty-model rung R0
                "StackedExclRzero": g_rob.loc["dAP_stacked_fm_adj", "slope"] if "dAP_stacked_fm_adj" in g_rob.index else np.nan,
                "StackedExclRzeroHi": g_rob.loc["dAP_stacked_fm_adj", "slope_ci_high"] if "dAP_stacked_fm_adj" in g_rob.index else np.nan,
                "InfoExclRzero": g_rob.loc["info_nats_fm_adj", "slope"] if "info_nats_fm_adj" in g_rob.index else np.nan,
                "InfoExclRzeroHi": g_rob.loc["info_nats_fm_adj", "slope_ci_high"] if "info_nats_fm_adj" in g_rob.index else np.nan}))
            for _, row in s.iterrows():
                rid = row["rung"].split("_")[0]
                macros.append(sc.latex_macros(f"{cc}{oc}{rid}", {
                    # primary: per-fold, null-centred
                    "APphys": row.get("AP_recal_fm", row["AP_recal"]), "APphysSd": row.get("AP_recal_fm_sd", np.nan),
                    "APstacked": row.get("AP_stacked_fm", row["AP_stacked"]),
                    "Info": row.get("info_nats_fm_adj", np.nan), "InfoRaw": row.get("info_nats_fm", np.nan),
                    "InfoNullMean": row.get("null_mean_info_nats_fm", np.nan),
                    "InfoP": row.get("p_null_info_nats_fm", row.get("p_null_info_nats", np.nan)),
                    "dAPstacked": row.get("dAP_stacked_fm_adj", np.nan),
                    "dAPearly": row.get("dAP_early_fm_adj", np.nan),
                    "dAPearlyNullMean": row.get("null_mean_dAP_early_fm", np.nan),
                    "dAPearlyP": row.get("p_null_dAP_early_fm", row.get("p_null_dAP_early", np.nan)),
                    "dAPgated": row.get("dAP_gated_fm", row["dAP_gated"]),
                    "dAPlegacy": row.get("dAP_adr_legacy_fm", row.get("dAP_adr_legacy", np.nan)),
                    # secondary: pooled
                    "APphysPooled": row["AP_recal"], "APphysPooledLo": row["AP_recal_lo"],
                    "APphysPooledHi": row["AP_recal_hi"], "InfoPooled": row["info_nats"],
                    "dAPh": row["dAPh_stacked"], "dAPhLo": row["dAPh_stacked_lo"], "dAPhHi": row["dAPh_stacked_hi"]}))
                rows.append(dict(city=r["city"], gt_tier=r.get("gt_tier"), ordering=ordering, **row.to_dict()))
            pick = [("rung", "Rung"), ("n_features", "$k$"),
                    ("AP_recal_fm", "AP$_R$ (fold)"), ("AP_recal_fm_sd", "sd"),
                    ("info_nats_fm_adj", r"$\hat I^{\mathrm{adj}}$ (nats)"),
                    ("p_null_info_nats_fm", r"$p_{\mathrm{null}}$"),
                    ("dAP_stacked_fm_adj", r"$\Delta$AP stacked$^{\mathrm{adj}}$"),
                    ("dAP_early_fm_adj", r"$\Delta$AP early$^{\mathrm{adj}}$"),
                    ("p_null_dAP_early_fm", r"$p_{\mathrm{early}}$"),
                    ("dAP_gated_fm", r"$\Delta$AP gated"), ("dAP_adr_legacy_fm", r"$\Delta$AP legacy"),
                    ("dAPh_stacked", r"$\Delta$AP$_h$ (pooled)")]
            pick = [(c, n) for c, n in pick if c in s.columns]
            tab = s[[c for c, _ in pick]].copy()
            tab.columns = [n for _, n in pick]
            tab["Rung"] = tab["Rung"].str.replace("_", r"\_", regex=False)
            with open(os.path.join(out_root, f"table_{cc}{oc}.tex"), "w") as fh:
                fh.write(tab.to_latex(index=False, escape=False, float_format=lambda v: sc.fmt_num(v, 3)))
        if r["lens"]:
            lens = pd.concat(r["lens"])
            fig2, ax2 = plt.subplots(figsize=(6.5, 0.35 * len(lens) + 1.2))
            ik = "info_nats_fm_adj" if "info_nats_fm_adj" in lens.columns else "info_nats"
            bk = ik[:-4] if ik.endswith("_adj") else ik
            shift = (lens[bk] - lens[ik]) if ik.endswith("_adj") else 0.0
            xe = None
            if f"{bk}_lo" in lens.columns and f"{bk}_hi" in lens.columns:
                xe = [(lens[ik] - (lens[f"{bk}_lo"] - shift)).clip(lower=0),
                      ((lens[f"{bk}_hi"] - shift) - lens[ik]).clip(lower=0)]
            ax2.barh(lens["channel"], lens[ik], xerr=xe, capsize=2)
            ax2.axvline(0, color="k", lw=0.6)
            ax2.set_xlabel("information gain Î (nats), per-fold and null-centred  [most complete rung]")
            ax2.set_title(f"{r['city']} — emotion/social channels", fontsize=9)
            fig2.tight_layout(); fig2.savefig(os.path.join(out_root, f"fig_emotion_lens_{cc}.png"), dpi=250)
            fig2.savefig(os.path.join(out_root, f"fig_emotion_lens_{cc}.pdf")); plt.close(fig2)
    if ok:
        fig.tight_layout(); fig.savefig(os.path.join(out_root, "fig_saturation_curves.png"), dpi=300)
        fig.savefig(os.path.join(out_root, "fig_saturation_curves.pdf")); plt.close(fig)
    open(os.path.join(out_root, "results_macros.tex"), "w").write("\n".join(macros) + "\n")
    pd.DataFrame(rows).to_csv(os.path.join(out_root, "all_cities_summary.csv"), index=False)
    overview = pd.DataFrame([dict(city=r["city"], status="ok" if r.get("results") else "failed",
                                  label_source=r.get("effective_label_source") or r.get("label_source"),
                                  gt_tier=r.get("gt_tier"),
                                  confirmatory=r.get("gt_tier") == "A_authoritative",
                                  positives=r.get("positives"), cells_analysed=r.get("cells_analysed"),
                                  prevalence=r.get("prevalence"), mentions=(r.get("social") or {}).get("mentions"),
                                  prereg_sha256=str(r.get("prereg_sha256") or "")[:8],
                                  pipeline_version=r.get("pipeline_version") or PIPELINE_VERSION,
                                  from_earlier_session=bool(r.get("from_earlier_session", False)),
                                  error=r.get("error", "")) for r in city_results])
    overview.to_csv(os.path.join(out_root, "cities_overview.csv"), index=False)
    return overview


# ---------------------------------------------------------------- v5.5 cross-city synthesis (RQ1-RQ3)
SYN_DIR = "paper_synthesis"
# v6 design: every tier-A city is confirmatory; localisation (label-free) is the pre-registered moderator, and
# the localisable subset is a conditional secondary set (reported whatever its size)
CONFIRMATORY = "tier A, all (confirmatory)"
LOCALISABLE = "tier A, localisable (conditional)"
EVALUABLE = "tier A, evaluable social layer (sensitivity, added in v6.1)"
MIN_EVALUABLE_MENTIONS = 10       # = social.min_source_mentions and the "sparse social layer" warning since v5
CO_PRIMARY = ["info_nats_fm_adj", "dAP_stacked_fm_adj"]
NORMALISED = ["info_frac_fm_adj", "dAPh_fm_adj"]
TOP_METRICS = ["info_frac_fm", "dAP_stacked_fm", "dAP_gated_fm", "dAP_early_fm", "dAP_adr_legacy_fm"]


def _slope_rows(states, ordering, role, metrics, tag="results"):
    rows = []
    for c, st_ in states.items():
        src = (st_.get("placebo") or {}) if tag == "placebo" else (st_.get("results") or {}).get(ordering)
        if not src or src.get("gradient") is None:
            continue
        g = src["gradient"]
        for m in metrics:
            gg = g[(g["role"] == role) & (g["metric"] == m)]
            if gg.empty:
                continue
            r = gg.iloc[0]
            se = r.get("slope_se", np.nan)
            if not np.isfinite(se):
                se = (r["slope_ci_high"] - r["slope_ci_low"]) / 3.92
            rows.append(dict(city=c, ordering=ordering, role=role, metric=m, slope=r["slope"], se=se,
                             ci_low=r["slope_ci_low"], ci_high=r["slope_ci_high"],
                             p_one_sided=r["p_one_sided_slope_ge_0"], n_rungs=r["n_rungs"]))
    return pd.DataFrame(rows)


def _city_sets(states, h, prereg=None):
    """Pooled sets. v6.1: (1) only cities of the pre-registered study set are pooled (if one is declared), so a
    report state left in the output folder by another run cannot enter a pooled estimate unnoticed; (2) the
    'evaluable' sensitivity set drops tier-A cities whose social layer has too few located mentions to evaluate."""
    ap_ = (prereg or {}).get("analysis_plan") or {}
    study = set(ap_.get("study_set") or [])
    info = {}
    for c, st_ in states.items():
        prov = st_.get("prov") or {}
        loc = prov.get("localisation") or {}
        ev = prov.get("evaluable_social_layer")
        if ev is None:
            ev = int(loc.get("n_mentions") or 0) >= int(ap_.get("min_evaluable_mentions", MIN_EVALUABLE_MENTIONS))
        info[c] = dict(current=st_.get("prereg_sha256") == h, tier=st_.get("gt_tier"),
                       eligible=bool(loc.get("eligible", False)), evaluable=bool(ev),
                       in_study=(c in study) if study else True,
                       acquisition_complete=bool((prov.get("acquisition_status") or {}).get("complete", False)))
    cur = {c for c, v in info.items() if v["current"] and v["in_study"]}
    sets = {
        CONFIRMATORY: {c for c in cur if info[c]["tier"] == "A_authoritative"},
        EVALUABLE: {c for c in cur if info[c]["tier"] == "A_authoritative" and info[c]["evaluable"]},
        LOCALISABLE: {c for c in cur if info[c]["tier"] == "A_authoritative" and info[c]["eligible"]},
        "tier A + A-points": {c for c in cur if str(info[c]["tier"]).startswith("A_")},
        "tier A + A-points, localisable": {c for c in cur if str(info[c]["tier"]).startswith("A_") and info[c]["eligible"]},
        "all localisable (any tier)": {c for c in cur if info[c]["eligible"]},
    }
    return info, sets
