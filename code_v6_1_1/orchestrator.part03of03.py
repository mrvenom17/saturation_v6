def _synthesise(out_root, prereg, h, log):
    try:
        write_synthesis(_load_report_states(out_root, log), prereg, h, out_root, log)
    except Exception as e:  # noqa: BLE001
        log("(all)", "synthesis", "warn", f"synthesis failed ({type(e).__name__}: {e}); per-city outputs are on disk")


REPORT_STATE = "_report_state.pkl"


def _save_report_state(r, out_root, prereg_sha):
    """What the cross-city report needs from one city, kept on disk so the tables, macros and figures
    always cover every finished city, not only the ones run in the current session."""
    slim = {k: r.get(k) for k in ("city", "prov", "positives", "prevalence", "label_source", "effective_label_source",
                                  "gt_tier", "social", "cells_analysed", "lens", "sens")}
    slim["results"] = {o: {"summary": v["summary"], "gradient": v["gradient"], "effects": v.get("effects")}
                       for o, v in r["results"].items()}
    slim["placebo"] = r.get("placebo")
    slim.update(prereg_sha256=prereg_sha, pipeline_version=PIPELINE_VERSION,
                saved_utc=dt.datetime.utcnow().isoformat(timespec="seconds"))
    d = os.path.join(out_root, r["city"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, REPORT_STATE + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(slim, fh)
    os.replace(tmp, os.path.join(d, REPORT_STATE))


def _load_report_states(out_root, log):
    states = {}
    for name in sorted(os.listdir(out_root)):
        p = os.path.join(out_root, name, REPORT_STATE)
        if os.path.exists(p):
            try:
                with open(p, "rb") as fh:
                    st_ = pickle.load(fh)
                states[st_["city"]] = st_
            except Exception as e:  # noqa: BLE001
                log(name, "report", "warn", f"could not read the saved report state ({e})")
    return states


INPUTS_FILE = "_analysis_inputs.pkl.gz"
PART_BYTES = 4_500_000       # v6: the Drive transfer tool refuses files of ~7 MB and more


def save_inputs(ctx, out_root):
    import gzip
    d = os.path.join(out_root, ctx["city"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, INPUTS_FILE + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        pickle.dump(ctx, fh, protocol=4)
    path = os.path.join(d, INPUTS_FILE)
    os.replace(tmp, path)
    # also as <= 4.5 MB parts (with a SHA-256 manifest), so the inputs can be moved through tools that cap file size
    for old in [f for f in os.listdir(d) if f.startswith(INPUTS_FILE + ".part")]:
        os.remove(os.path.join(d, old))
    raw = open(path, "rb").read()
    parts = [raw[i:i + PART_BYTES] for i in range(0, len(raw), PART_BYTES)] or [b""]
    for i, chunk in enumerate(parts):
        open(os.path.join(d, f"{INPUTS_FILE}.part{i:02d}of{len(parts):02d}"), "wb").write(chunk)
    json.dump(dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), parts=len(parts)),
              open(os.path.join(d, INPUTS_FILE + ".manifest.json"), "w"))
    return path


def load_inputs(city, out_root):
    """Reads the inputs file, or reassembles it from its parts (checked against the SHA-256 manifest)."""
    import gzip
    d = os.path.join(out_root, city)
    path = os.path.join(d, INPUTS_FILE)
    if not os.path.exists(path):
        parts = sorted((f for f in os.listdir(d) if f.startswith(INPUTS_FILE + ".part")),
                       key=lambda f: int(re.search(r"\.part(\d+)of", f).group(1)))      # numeric, not text order
        if not parts:
            raise FileNotFoundError(f"no {INPUTS_FILE} (or parts) for {city} in {d}: run RUN_MODE='acquire' first")
        raw = b"".join(open(os.path.join(d, f), "rb").read() for f in parts)
        man = json.load(open(os.path.join(d, INPUTS_FILE + ".manifest.json")))
        if hashlib.sha256(raw).hexdigest() != man["sha256"] or len(parts) != man["parts"]:
            raise RuntimeError(f"{city}: reassembled inputs do not match their manifest (missing or damaged part)")
        open(path, "wb").write(raw)
    with gzip.open(path, "rb") as fh:
        return pickle.load(fh)


ENV_PACKAGES = ["numpy", "pandas", "scipy", "scikit-learn", "xgboost", "geopandas", "shapely", "pyproj", "pyogrio",
                "rasterio", "earthengine-api", "google-cloud-bigquery", "transformers", "torch", "osmnx", "matplotlib"]


def capture_environment(out_root, mode):
    """Software versions and code hashes for the methods section and for exact reruns (appended per session)."""
    import importlib.metadata as im
    import platform
    import sys
    env = dict(utc=dt.datetime.utcnow().isoformat(timespec="seconds"), mode=mode, pipeline=PIPELINE_VERSION,
               python=sys.version.split()[0], platform=platform.platform(), packages={})
    for p_ in ENV_PACKAGES:
        try:
            env["packages"][p_] = im.version(p_)
        except Exception:  # noqa: BLE001
            env["packages"][p_] = None
    here = os.path.dirname(os.path.abspath(__file__))
    env["code_sha256"] = {m: ds.file_sha256(os.path.join(here, f"{m}.py")) for m in
                          ("orchestrator", "data_sources", "saturation_core", "pipeline_helpers")
                          if os.path.exists(os.path.join(here, f"{m}.py"))}
    with open(os.path.join(out_root, "environment.jsonl"), "a") as fh:
        fh.write(json.dumps(env) + "\n")
    return env


ARCHIVE_FILES = ("all_cities_summary.csv", "cities_overview.csv", "provenance.json", "results_macros.tex",
                 "acquisition_overview.csv", "preflight_checks.csv", "run_log.csv")


def archive_previous_results(out_root, log):
    """Before a changed pre-registration replaces them (v6.1): the cross-city tables, macros, provenance, run log
    and the results bundle produced under the previous pre-registration are copied to archive_<sha8>/, so the
    record of what was run before the change is not overwritten. Per-city folders are left in place."""
    path = os.path.join(out_root, "preregistration.json")
    if not os.path.exists(path):
        return None
    try:
        old = json.load(open(path)).get("sha256") or "old"
    except Exception:  # noqa: BLE001
        return None
    dst = os.path.join(out_root, f"archive_{old[:8]}")
    if os.path.isdir(dst):
        return dst
    os.makedirs(dst, exist_ok=True)
    n = 0
    if os.path.isdir(os.path.join(out_root, SYN_DIR)):
        shutil.copytree(os.path.join(out_root, SYN_DIR), os.path.join(dst, SYN_DIR)); n += 1
    for f in ARCHIVE_FILES:
        if os.path.exists(os.path.join(out_root, f)):
            shutil.copy(os.path.join(out_root, f), os.path.join(dst, f)); n += 1
    bundle = out_root.rstrip("/") + "_bundle.zip"
    if os.path.exists(bundle):
        shutil.copy(bundle, out_root.rstrip("/") + f"_bundle_{old[:8]}.zip"); n += 1
    log("(all)", "archive", "ok", f"results under pre-registration {old[:8]} archived to {os.path.basename(dst)}/ ({n} items)")
    return dst


def run_all(cities, registry, prereg, profile, clients, out_root, cache_root, log, deviation_reason=None, mode="full",
            allow_stale_inputs=False):
    """mode: 'full' (acquire + analyse), 'acquire' (network stages only; writes <city>/_analysis_inputs.pkl.gz)
    or 'analyse' (reads those inputs; no network, so it can run on any machine).
    v6.1: in analyse mode, inputs acquired under older acquisition rules or left incomplete are refused unless
    allow_stale_inputs=True (they are then analysed and flagged as provisional everywhere)."""
    if mode not in ("full", "acquire", "analyse"):
        raise ValueError(f"mode must be full, acquire or analyse, not {mode!r}")
    os.makedirs(out_root, exist_ok=True)
    os.makedirs(cache_root, exist_ok=True)
    try:
        prev = os.path.join(out_root, "preregistration.json")
        if os.path.exists(prev) and json.load(open(prev)).get("sha256") != hashlib.sha256(
                json.dumps(prereg, sort_keys=True).encode()).hexdigest():
            archive_previous_results(out_root, log)
    except Exception as e:  # noqa: BLE001
        log("(all)", "archive", "warn", f"could not archive the previous results: {e}")
    h = write_prereg(prereg, out_root, reason=deviation_reason)
    study = set((prereg.get("analysis_plan") or {}).get("study_set") or [])
    extra = [c for c in cities if study and c not in study]
    if extra:
        log("(all)", "config", "warn", f"not in the pre-registered study set, so analysed but never pooled: {extra}")
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
                acq = ctx["prov"].get("acquisition") or {}
                log(city, "acquire", "ok" if acq.get("complete", True) else "warn",
                    f"analysis inputs saved ({os.path.getsize(path) / 1e6:.1f} MB) in "
                    f"{(time.time() - t) / 60:.1f} min -> {os.path.relpath(path, out_root)}"
                    + ("" if acq.get("complete", True) else "  [INCOMPLETE: run the acquisition again]"))
                city_results.append(dict(city=city, acquired=True, inputs=path,
                                         complete=bool(acq.get("complete", True)), pending=" | ".join(acq.get("pending", [])),
                                         mentions_primary=(ctx["prov"].get("localisation") or {}).get("n_mentions"),
                                         signal_type=(ctx["prov"].get("signal_primary") or {}).get("signal_type"),
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
                ctx = load_inputs(city, out_root)
                stale = ctx.get("acquisition_rules") != ACQUISITION_RULES
                incomplete = not (ctx.get("prov", {}).get("acquisition") or {}).get("complete", True)
                if (stale or incomplete) and not allow_stale_inputs:
                    raise RuntimeError(
                        f"{city}: the saved inputs "
                        + (f"were acquired under older rules ({ctx.get('acquisition_rules') or 'v6.0'}, current {ACQUISITION_RULES})"
                           if stale else "are INCOMPLETE (" + " | ".join((ctx['prov'].get('acquisition') or {}).get('pending', []))[:300] + ")")
                        + ". Run RUN_MODE='acquire' for this city first (cached downloads make it quick), or set "
                          "ALLOW_STALE_INPUTS=True to analyse them anyway as provisional")
                r = analyse_city(ctx, prereg, profile, out_root, cache_root, log)
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
        ov = pd.DataFrame([dict(city=r["city"], acquired=bool(r.get("acquired")), complete=bool(r.get("complete", False)),
                                mentions_primary=r.get("mentions_primary"), signal_type=r.get("signal_type"),
                                localisable=r.get("localisation"), pending=r.get("pending", ""),
                                error=r.get("error", "")) for r in city_results],
                          columns=["city", "acquired", "complete", "mentions_primary", "signal_type", "localisable",
                                   "pending", "error"])
        ov.to_csv(os.path.join(out_root, "acquisition_overview.csv"), index=False)
        n_ok = int((ov["acquired"] & ov["complete"]).sum())
        log("(all)", "acquire", "ok" if n_ok == len(ov) else "warn",
            f"{int(ov['acquired'].sum())} of {len(ov)} cities acquired, {n_ok} complete"
            + ("; run the analysis with RUN_MODE='analyse' (any machine) on " + out_root if n_ok == len(ov) else
               "; RUN THE ACQUISITION AGAIN until every city is complete (finished work is reused), then analyse"))
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
