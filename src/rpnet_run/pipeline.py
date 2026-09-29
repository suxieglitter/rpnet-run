"""Pipeline for rpnet-run.

Faithful port of the upstream example/run_RPNet.py workflow (RPNet v0.1.0),
with four deliberate differences:

1. Parameters come from the caller instead of hyperparams.py.
2. mean_threshold filtering uses the corrected logic from example2
   (upstream example1 has a mean_thresuld NameError typo).
3. The SKHASH control template is generated here (vmodel path, dang,
   use_fortran ...), so no hand-edited control_file0.txt is needed.
4. loc_uncert (km) turns on source-location perturbation in the SKHASH
   Monte Carlo trials with one uniform uncertainty. Upstream hardcodes
   0.00 km location uncertainties into the phase file, which makes the
   nmc trials geometrically identical; the value is written back into
   the phase file header because SKHASH's default_uncert fill only
   covers missing/negative columns, not the explicit zeros that
   hash2-format files carry.

Path handling goes through rpnet_run.paths (normalize, reject parent
references, allowlist containment); this module never opens files for
writing itself -- data files are written through pandas, and the MSEED
archive plus SKHASH input files are written by the upstream rpnet
functions inside --out-dir.

Stations whose names are longer than 4 characters are renamed S001...N
before writing SKHASH input, because the HASH phase format allocates a
4-character station field (SKHASH reads it with fixed column widths).
The mapping is saved to <out_dir>/sta_map.csv.
"""

import os
import shutil
import time

import numpy as np
import pandas as pd
import parmap
from obspy import UTCDateTime

from rpnet import est_taup, pred_rpnet, prep_skhash, wf2matrix

from .paths import check_input, check_out_dir, join_out, listdir_checked

CONTROL_TEMPLATE = """$vmodel_paths  # whitespace/newline delimited list of paths to the velocity models
{vmodel}

$npolmin       # mininum number of polarity data (e.g., 8)
{npolmin}

$max_agap      # maximum azimuthal gap
360

$max_pgap      # maximum "plungal" gap
90

$dang          # minimum grid spacing (degrees)
{dang}

$nmc           # number of trials (e.g., 30)
30

$maxout        # max num of acceptable focal mech. outputs (e.g. 500)
500

$ratmin        # minimum allowed signal to noise ratio
1

$badfrac       # fraction polarities assumed bad
0.05

$qbadfrac      # assumed noise in amplitude ratios, log10 (e.g. 0.3 for a factor of 2)
0.3

$delmax        # maximum allowed source-receiver distance in km.
{delmax}

$cangle        # angle for computing mechanisms probability
45

$prob_max      # probability threshold for multiples (e.g. 0.1)
0.25

$num_cpus      # number of cores in parallel (0: use all cpu / 1: sigle core)
{num_cpus}

$use_fortran   # Fortran subroutine for fast grid search
{use_fortran}

$perturb_epicentral_location  # randomly perturb the horizontal earthquake location
{perturb_epicentral}
"""


def run(
    waveform_dir,
    catalog,
    phase,
    stations,
    out_dir,
    model,
    vmodel=None,
    time_col="jst",
    id_col="data_id",
    ptime_col="ptime",
    stime_col="stime",
    cores=5,
    batch_size=2 ** 13,
    iteration=100,
    gpu="",
    std_threshold=0.2,
    mean_threshold=0.0,
    keep_unknown=False,
    change2taup=True,
    add_sta=False,
    keep_initial_phase=False,
    taup_model="iasp91",
    hash_version="hash2",
    dang=5,
    npolmin=8,
    delmax=120,
    num_cpus=2,
    use_fortran=False,
    loc_uncert=0.0,
    overwrite=False,
):
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu
    stime = time.time()

    # ---- normalize and validate all input paths ---------------------------
    waveform_dir = check_input("--waveform-dir", waveform_dir, kind="dir")
    catalog = check_input("--catalog", catalog)
    phase = check_input("--phase", phase)
    stations = check_input("--stations", stations)
    model = check_input("--model", model)
    out_dir = check_out_dir(out_dir)
    if vmodel is not None:
        vmodel = check_input("--vmodel", vmodel)
        print("[rpnet-run] SKHASH velocity model: %s" % vmodel)
    else:
        print("[rpnet-run] no --vmodel given: polarity CSV only, "
              "SKHASH input files will NOT be generated")
    if add_sta and not change2taup:
        raise SystemExit("[rpnet-run] --add-sta needs TauP times "
                         "(--no-taup must not be set)")
    if loc_uncert < 0:
        raise SystemExit("[rpnet-run] --loc-uncert must be >= 0 km")
    if loc_uncert >= 100:
        raise SystemExit("[rpnet-run] --loc-uncert must be < 100 km "
                         "(fixed-width phase file columns)")

    if os.path.exists(out_dir):
        if not overwrite:
            raise SystemExit("[rpnet-run] output dir exists: %s "
                             "(use --overwrite to replace it)" % out_dir)
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    # ---- load tables -----------------------------------------------------
    cat_df = pd.read_csv(catalog)
    pha_df = pd.read_csv(phase)
    sta_df = pd.read_csv(stations).sort_values(["sta"]).reset_index(drop=True)
    sta_df["sta0"] = sta_df["sta"]
    pha_df["source"] = "original"

    need_cat = [time_col, id_col, "lat", "lon", "dep"]
    missing = [c for c in need_cat if c not in cat_df.columns]
    if missing:
        raise SystemExit("[rpnet-run] catalog %s lacks column(s): %s"
                         % (catalog, ", ".join(missing)))
    if "mag" not in cat_df.columns:
        print("[rpnet-run] catalog has no mag column, using 0.0 for SKHASH headers")
        cat_df["mag"] = 0.0
    for c in [id_col, "sta", ptime_col]:
        if c not in pha_df.columns:
            raise SystemExit("[rpnet-run] phase %s lacks column: %s" % (phase, c))
    if stime_col not in pha_df.columns:
        print("[rpnet-run] phase table has no %s column (P-only catalog); "
              "S times, when needed, will come from TauP" % stime_col)
        pha_df[stime_col] = np.nan
    for c in ["sta", "lat", "lon", "elv"]:
        if c not in sta_df.columns:
            raise SystemExit("[rpnet-run] station table %s lacks column: %s"
                             % (stations, c))
    def _code(value, fallback):
        text = "" if pd.isna(value) else str(value).strip()
        return text if text else fallback

    if "net" not in sta_df.columns:
        sta_df["net"] = ""
    if "chan" not in sta_df.columns:
        sta_df["chan"] = "HHZ"
    sta_df["net"] = [_code(n, "XX") for n in sta_df["net"]]

    # ---- add stations that have waveforms but no picks -------------------
    if add_sta:
        print("# adding waveform-only stations (TauP times)")
        add_rows = []
        seen = set()
        for event_id, ev_dir in listdir_checked(waveform_dir, "--waveform-dir"):
            for wf_name, _ in listdir_checked(ev_dir, "--waveform-dir/" + event_id):
                sta = wf_name.split(".")[0]
                if (event_id, sta) in seen:
                    continue  # one row per station even with 3-component files
                if len(pha_df[(pha_df[id_col] == event_id) &
                              (pha_df["sta"] == sta)]) != 0:
                    continue
                if event_id not in cat_df[id_col].tolist():
                    continue
                seen.add((event_id, sta))
                add_rows.append({id_col: event_id, "sta": sta,
                                 ptime_col: np.nan, stime_col: np.nan})
        if add_rows:
            pha_df0 = pd.DataFrame(add_rows)
            pha_df0["source"] = "add"
            pha_df = pd.concat([pha_df, pha_df0]).reset_index(drop=True)
        print("- %d extra station-event pairs added" % len(add_rows))

    sta_df = sta_df[sta_df["sta"].isin(pha_df["sta"].tolist())].reset_index(drop=True)
    pha_df = pha_df[pha_df["sta"].isin(sta_df["sta"].tolist())].reset_index(drop=True)
    for col in ["lat", "lon", "elv", "net", "chan"]:
        pha_df[col] = [sta_df[sta_df.sta == i][col].iloc[0]
                       for i in pha_df["sta"].tolist()]

    cat_df[time_col] = [UTCDateTime(i) for i in cat_df[time_col].tolist()]

    if not change2taup:
        n_missing = int(pd.isna(pha_df[ptime_col]).sum())
        if n_missing:
            print("[rpnet-run] warning: %d rows have no %s; with --no-taup "
                  "these stations cannot be cut and will be skipped"
                  % (n_missing, ptime_col))

    # ---- TauP theoretical arrivals ---------------------------------------
    if change2taup:
        print("# replacing picks with TauP arrivals (%s)" % taup_model)
        pha_df["ptime0"] = pha_df[ptime_col]
        results = parmap.map(
            est_taup,
            [[idx, val, cat_df[cat_df[id_col] == val[id_col]].iloc[0],
              time_col, "P", taup_model, keep_initial_phase]
             for idx, val in pha_df.iterrows()],
            pm_pbar=True, pm_processes=cores, pm_chunksize=1)
        pha_df[ptime_col] = results
        print("- TauP (P) done")
        pha_df["stime0"] = pha_df[stime_col]
        results = parmap.map(
            est_taup,
            [[idx, val, cat_df[cat_df[id_col] == val[id_col]].iloc[0],
              time_col, "S", taup_model, keep_initial_phase]
             for idx, val in pha_df.iterrows()],
            pm_pbar=True, pm_processes=cores, pm_chunksize=1)
        pha_df[stime_col] = results
        print("- TauP (S) done")

    pha_df = pha_df.sort_values([id_col, "sta"]).reset_index(drop=True)

    # ---- cut windows and predict ------------------------------------------
    print("# making input matrix from waveforms")
    results = parmap.map(
        wf2matrix,
        [[idx, val, id_col, ptime_col, waveform_dir, out_dir]
         for idx, val in pha_df.iterrows()],
        pm_pbar=True, pm_processes=cores, pm_chunksize=1)
    results = [i for i in results if i is not None]
    if not results:
        raise SystemExit("[rpnet-run] no waveform could be read; check wf "
                         "layout <id>/<sta>.* and channel codes")
    a, b = zip(*results)
    pha_df = pha_df.iloc[list(a)].reset_index(drop=True)
    in_mat = np.vstack(b)
    print("- %d windows, %.1f min" % (in_mat.shape[0], (time.time() - stime) / 60))

    print("# predicting polarity (iteration=%d)" % iteration)
    r_df = pred_rpnet(model, in_mat, pha_df, batch_size=batch_size,
                      iteration=iteration, gpu_num=gpu,
                      time_shift=0.0, mid_point=250)
    r_df.to_csv(join_out(out_dir, "pol_result.csv"), index=False)
    n0 = len(r_df)
    print("- %d rows -> pol_result.csv" % n0)

    # ---- thresholds --------------------------------------------------------
    if iteration != 0:
        r_df.loc[r_df["std"] > std_threshold, "predict"] = "K"
        if mean_threshold > 0:
            r_df.loc[r_df["prob"] < mean_threshold, "predict"] = "K"
    n_k = int((r_df["predict"] == "K").sum())
    if not keep_unknown:
        r_df = r_df[r_df["predict"] != "K"].reset_index(drop=True)
    print("- %d of %d marked unknown (std>%.2g%s), %d kept"
          % (n_k, n0, std_threshold,
             ", prob<%.2g" % mean_threshold if mean_threshold > 0 else "",
             len(r_df)))

    if vmodel is None:
        print("@ DONE (polarity only): %s/pol_result.csv" % out_dir)
        return r_df

    # ---- rename stations too long for the HASH 4-char field ---------------
    order = sorted(sta_df["sta0"].unique(), key=str)
    rename_map = {s: "S%03d" % (i + 1) for i, s in enumerate(order)}
    long_names = [s for s in order if len(str(s)) > 4]
    if long_names:
        sta_df["sta"] = sta_df["sta0"].map(rename_map)
        pd.DataFrame({"original": list(rename_map.keys()),
                      "skhash": list(rename_map.values())}).to_csv(
            join_out(out_dir, "sta_map.csv"), index=False)
        print("- %d station names longer than 4 chars renamed (sta_map.csv)"
              % len(long_names))
    sta_df["chan"] = ["HHZ" if _code(c, "").upper() == "U" else _code(c, "HHZ")[:3]
                      for c in sta_df["chan"]]

    # ---- SKHASH input ------------------------------------------------------
    print("# writing SKHASH %s input files" % hash_version)
    ctrl_text = CONTROL_TEMPLATE.format(
        vmodel=vmodel, npolmin=npolmin, dang=dang,
        delmax=delmax, num_cpus=num_cpus,
        use_fortran=str(bool(use_fortran)),
        perturb_epicentral=str(bool(loc_uncert > 0)))
    if loc_uncert > 0:
        print("- location perturbation ON: uniform %.2f km for all events "
              "(SKHASH Monte Carlo trials)" % loc_uncert)
    np.savetxt(join_out(out_dir, "control_file0.txt"),
               np.array(ctrl_text.splitlines()), fmt="%s")
    r_df = r_df.drop_duplicates(["sta", id_col]).reset_index(drop=True)
    cat_df = cat_df[cat_df[id_col].isin(r_df[id_col].tolist())].reset_index(drop=True)
    prep_skhash(cat_df=cat_df, pol_df=r_df, amp=[], sta_df=sta_df,
                ftime=time_col, fwfid=id_col,
                ctrl0=join_out(out_dir, "control_file0.txt"),
                out_dir=out_dir, hash_version=hash_version)

    # ---- write location uncertainty into the phase file headers ---------
    # prep_skhash hardcodes ' 0.00 0.00' (horz/vert km) at columns 88-99 of
    # each event header; SKHASH perturbs locations by exactly those values.
    if loc_uncert > 0:
        phase_path = os.path.join(out_dir, hash_version, "IN", "phase.txt")
        pair = "%5.2f %5.2f" % (loc_uncert, loc_uncert)
        with open(phase_path) as f:
            lines = f.read().splitlines()
        n_hdr = 0
        for i, line in enumerate(lines):
            if len(line) > 100:  # event headers; pick/footer lines are short
                lines[i] = line[:88] + pair + line[99:]
                n_hdr += 1
        np.savetxt(phase_path, np.array(lines), fmt="%s")
        print("- %d event headers: location uncertainty %.2f km written "
              "into phase.txt" % (n_hdr, loc_uncert))

    print("@ DONE in %.1f min: %s/pol_result.csv, %s/%s/ "
          "(run: SKHASH %s/%s/control_file.txt)"
          % ((time.time() - stime) / 60, out_dir, out_dir, hash_version,
             out_dir, hash_version))
    return r_df
