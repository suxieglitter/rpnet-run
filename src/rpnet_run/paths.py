"""Guarded path helpers for rpnet-run.

Path policy for this tool (enforced on every access):

1. Normalize: every user-supplied path is converted to an absolute path
   before use.
2. No parent references: paths containing '..' are rejected outright.
3. Allowlist: every input, output directory and directory listing must
   stay inside the allowed root, RPNET_RUN_ALLOWED_ROOT (defaults to
   the user's home directory). Set it to a wider root when the tool
   must read data elsewhere (e.g. an external data mount).
4. This module never opens files for writing; data files are written
   through pandas/obspy writers, and raw writes do not exist here.
"""

import os


class PathError(SystemExit):
    pass


def fail(msg):
    raise PathError("[rpnet-run] " + msg)


def allowed_root():
    """The directory tree this tool may read from and write to."""
    return os.path.realpath(os.environ.get(
        "RPNET_RUN_ALLOWED_ROOT", os.path.expanduser("~")))


def _inside(root, path):
    return path == root or path.startswith(root + os.sep)


def check_input(label, raw, kind="file"):
    """Normalize a user-supplied input path, verify existence and root."""
    raw = str(raw)
    if os.pardir in raw:
        fail("%s: path must not contain '%s': %s" % (label, os.pardir, raw))
    path = os.path.abspath(raw)
    root = allowed_root()
    if not _inside(root, path):
        fail("%s: path is outside the allowed root %s: %s "
             "(set RPNET_RUN_ALLOWED_ROOT to widen it)" % (label, root, path))
    if kind == "dir":
        if not os.path.isdir(path):
            fail("%s: no such directory: %s" % (label, path))
    else:
        if not os.path.isfile(path):
            fail("%s: no such file: %s" % (label, path))
    return path


def check_out_dir(raw):
    """Normalize the output directory and verify allowlist containment."""
    raw = str(raw)
    if os.pardir in raw:
        fail("--out-dir: path must not contain '%s': %s" % (os.pardur, raw))
    path = os.path.abspath(raw)
    root = allowed_root()
    if not _inside(root, path):
        fail("--out-dir: outside the allowed root %s: %s "
             "(set RPNET_RUN_ALLOWED_ROOT to widen it)" % (root, path))
    return path


def join_out(out_dir, filename):
    """Path of <out_dir>/<basename(filename)>; always inside out_dir."""
    return os.path.join(os.path.realpath(out_dir),
                        os.path.basename(str(filename)))


def listdir_checked(root_dir, label):
    """List (name, full_path) of root_dir's children via os.scandir.

    Child paths are taken from the OS-provided entry objects, and each
    one is re-checked to resolve inside root_dir.
    """
    base = os.path.realpath(root_dir)
    entries = []
    with os.scandir(base) as scan:
        for entry in sorted(scan, key=lambda e: e.name):
            full = os.path.realpath(entry.path)
            if not _inside(base, full):
                fail("%s: entry resolves outside the directory: %s"
                     % (label, entry.name))
            entries.append((entry.name, full))
    return entries
