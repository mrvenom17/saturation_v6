def run_all(cities, registry, prereg, profile, clients, out_root, cache_root, log, deviation_reason=None, mode="full"):
    """mode: 'full' (acquire + analyse), 'acquire' (network stages only; writes <city>/_analysis_inputs.pkl.gz)
    or 'analyse' (reads those inputs; no network, so it can run on any machine)."""
    if mode not in ("full", "acquire", "analyse"):
        raise ValueError(f"mode must be full, acquire or analyse, not {mode!r}")
    os.makedirs(out_root, exist_ok=True)
    os.makedirs(cache_root, exist_ok=True)
    h = write_prereg(prereg, out_root, reason=deviation_reason)
    try:
        capture_environment(out_root, mode)
    except Exception as e:  # noqa: BLE001
        log("(all)", "environment", "warn", f"could not record the software environment: {e}")
    with open(os.path.join(out_root, "RUN_PROFILE.txt"), "w") as fh:
        fh.write(PROFILES[profile]["label"] + "\n")
    city_results, prov = [], dict(prereg_sha256=h, profile=profile, started_utc=dt.datetime.utcnow().isoformat(), cities={})
    for city in cities:
        if city not in registry:
            log(city, "config", "fail", "not in CITY_REGISTRY")
            continue
        t = time.time()
        if mode == "acquire":
            try:
                ctx = acquire_city(city, registry[city], prereg, profile, clients, out_root, cache_root, log)
                path = save_inputs(ctx, out_root)
                log(city, "acquire", "ok", f"analysis inputs saved ({os.path.getsize(path) / 1e6:.1f} MB) in "
                                           f"{(time.time() - t) / 60:.1f} min -> {os.path.relpath(path, out_root)}")
                city_results.append(dict(city=city, acquired=True, inputs=path,
                                         localisation=(ctx["prov"].get("localisation") or {}).get("eligible")))
            except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001
                tb = traceback.format_exc()
                open(os.path.join(out_root, f"{city}_ERROR.txt"), "w").write(tb)
                short = (str(e).split("\n")[0] or type(e).__name__)[:400]
                log(city, "acquire", "fail", f"{type(e).__name__}: {short} (traceback in {city}_ERROR.txt)")
                city_results.append(dict(city=city, error=f"{type(e).__name__}: {short}"))
            continue
        try:
            if mode == "analyse":
                r = analyse_city(load_inputs(city, out_root), prereg, profile, out_root, cache_root, log)
            else:
                r = run_city(city, registry[city], prereg, profile, clients, out_root, cache_root, log)
            prov["cities"][city] = r["prov"]
            city_results.append(r)
            _save_report_state(r, out_root, h)
            log(city, "city", "ok", f"finished in {(time.time() - t) / 60:.1f} min")
            _synthesise(out_root, prereg, h, log)          # the pooled results are current after every city
        except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001
            tb = traceback.format_exc()
            open(os.path.join(out_root, f"{city}_ERROR.txt"), "w").write(tb)
            short = (str(e).split("\n")[0] or type(e).__name__)[:400]
            log(city, "city", "fail", f"{type(e).__name__}: {short} (traceback in {city}_ERROR.txt)")
            city_results.append(dict(city=city, error=f"{type(e).__name__}: {short}"))
    if mode == "acquire":
        ov = pd.DataFrame([dict(city=r["city"], acquired=bool(r.get("acquired")), localisable=r.get("localisation"),
                                error=r.get("error", "")) for r in city_results])
        ov.to_csv(os.path.join(out_root, "acquisition_overview.csv"), index=False)
        log("(all)", "acquire", "ok", f"{int(ov['acquired'].sum())} of {len(ov)} cities acquired; run the analysis "
                                      f"with RUN_MODE='analyse' (any machine) on {out_root}")
        return city_results, ov, None
    # the report covers every city finished so far (this session's results replace older ones)
    states = _load_report_states(out_root, log)
    here = {r["city"] for r in city_results}
    earlier = [dict(v, from_earlier_session=True) for c, v in states.items() if c not in here]
    for e in earlier:
        if e.get("prereg_sha256") != h:
            log(e["city"], "report", "warn", f"included from an earlier session run under a different "
                                             f"pre-registration ({str(e.get('prereg_sha256'))[:8]} vs {h[:8]}); "
                                             f"re-run it before using it in the paper")
    for r in city_results:
        r.setdefault("prereg_sha256", h)
    report_results = earlier + city_results
    try:
        overview = write_report(report_results, prereg, profile, out_root, log)
    except Exception as e:  # noqa: BLE001
        log("(all)", "report", "warn", f"report generation failed ({e}); per-city CSVs are already on disk")
        overview = pd.DataFrame([dict(city=r.get("city"), status="ok" if r.get("results") else "failed",
                                      error=r.get("error", "")) for r in city_results])
        overview.to_csv(os.path.join(out_root, "cities_overview.csv"), index=False)
    _synthesise(out_root, prereg, h, log)
    prov["finished_utc"] = dt.datetime.utcnow().isoformat()
    pp = os.path.join(out_root, "provenance.json")
    if os.path.exists(pp):          # keep earlier cities' provenance; this session's entries replace theirs
        try:
            old = json.load(open(pp))
            prov["cities"] = {**(old.get("cities") or {}), **prov["cities"]}
            prov["earlier_sessions"] = (old.get("earlier_sessions") or []) + [
                {k: old.get(k) for k in ("prereg_sha256", "profile", "started_utc", "finished_utc")}]
        except Exception:  # noqa: BLE001
            pass
    json.dump(prov, open(pp, "w"), indent=2, default=str)
    zip_path = shutil.make_archive(out_root.rstrip("/") + "_bundle", "zip", out_root)
    return city_results, overview, zip_path
