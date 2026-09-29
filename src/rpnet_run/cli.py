"""Command-line interface for rpnet-run."""

import argparse

from rpnet_run import __version__
from rpnet_run.pipeline import run


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="rpnet-run",
        description="RPNet P-wave polarity prediction with SKHASH input "
                    "generation (wrapper of Han et al., 2025, SRL; "
                    "upstream v0.1.0).",
        epilog="Example: rpnet-run --waveform-dir waveform "
               "--catalog Kumamoto_catalog.csv --phase Kumamoto_phase.csv "
               "--stations hinet_station.csv --model model/RPNet_v1.h5 "
               "--vmodel vz.iasp91 --out output01")
    req = parser.add_argument_group("required inputs")
    req.add_argument("--waveform-dir", required=True,
                     help="waveform directory, layout <event_id>/<station>.* "
                          "(vertical channel *Z preferred, *U fallback)")
    req.add_argument("--catalog", required=True,
                     help="event catalog CSV: origin time, id, lat, lon, dep "
                          "(mag optional)")
    req.add_argument("--phase", required=True,
                     help="phase CSV: event id, station, P and S times")
    req.add_argument("--stations", required=True,
                     help="station CSV: sta, lat, lon, elv (net, chan optional)")
    req.add_argument("--out", required=True, dest="out_dir",
                     help="output directory (created; must not exist unless "
                          "--overwrite)")

    io = parser.add_argument_group("inputs / outputs")
    io.add_argument("--model", required=True,
                    help="pretrained RPNet model, e.g. RPNet_v1.h5")
    io.add_argument("--vmodel", default=None,
                    help="SKHASH 1-D velocity model (depth_km,Vp text file); "
                         "omit to skip SKHASH input generation")
    io.add_argument("--time-col", default="jst",
                    help="origin-time column in catalog (default: jst)")
    io.add_argument("--id-col", default="data_id",
                    help="event id column shared by catalog/phase "
                         "(default: data_id)")
    io.add_argument("--ptime-col", default="ptime")
    io.add_argument("--stime-col", default="stime")
    io.add_argument("--overwrite", action="store_true",
                    help="replace an existing output directory")

    pred = parser.add_argument_group("prediction")
    pred.add_argument("--cores", type=int, default=5,
                      help="parallel workers for preprocessing (default: 5)")
    pred.add_argument("--batch-size", type=int, default=8192)
    pred.add_argument("--iteration", type=int, default=100,
                      help="MC iterations for prob/std (0 = single pass)")
    pred.add_argument("--gpu", default="",
                      help='GPU id, e.g. "0"; empty means CPU (default)')
    pred.add_argument("--std-threshold", type=float, default=0.2,
                      help="std above this is marked unknown (default: 0.2)")
    pred.add_argument("--mean-threshold", type=float, default=0.0,
                      help="prob below this is marked unknown "
                           "(0 = off, default)")
    pred.add_argument("--keep-unknown", action="store_true",
                      help="keep K (unknown) rows for SKHASH too")

    taup = parser.add_argument_group("TauP arrival times")
    taup.add_argument("--no-taup", dest="change2taup", action="store_false",
                      help="keep catalog picks instead of TauP times")
    taup.add_argument("--add-sta", action="store_true",
                      help="use stations with waveforms but no picks "
                           "(requires TauP times)")
    taup.add_argument("--keep-initial-phase", action="store_true",
                      help="keep existing picks, estimate only missing ones")
    taup.add_argument("--taup-model", default="iasp91",
                      help="iasp91, ak135, or path to a custom .npz")

    sk = parser.add_argument_group("SKHASH")
    sk.add_argument("--dang", type=float, default=5,
                    help="grid spacing in degrees (default: 5; 1 needs the "
                         "compiled Fortran routine with a larger ncoor)")
    sk.add_argument("--npolmin", type=int, default=8)
    sk.add_argument("--delmax", type=float, default=120,
                    help="max source-receiver distance in km (default: 120)")
    sk.add_argument("--num-cpus", type=int, default=2)
    sk.add_argument("--use-fortran", action="store_true",
                    help="use the compiled SKHASH Fortran routine "
                         "(only if you built gridsearch.so)")
    sk.add_argument("--loc-uncert", type=float, default=0.0, metavar="KM",
                    help="uniform source location uncertainty (km) written "
                         "into the SKHASH phase file, so the Monte Carlo "
                         "trials actually perturb locations and "
                         "fault_plane_uncertainty includes location error "
                         "(0 = off, default)")

    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)

    args = parser.parse_args(argv)
    run(**vars(args))


if __name__ == "__main__":
    main()
