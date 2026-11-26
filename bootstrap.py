#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-shot, idempotent environment bootstrap for admet-screening (portable).

Design rules (each one exists because of a real failure):
  * Pure stdlib. It must run even when rdkit/numpy are broken.
  * Idempotence checks verify the PRODUCT WORKS (import + version + minimal call),
    never "directory exists" (gmx_MMPBSA incident, rule 8).
  * Every subprocess output goes to a log file on disk; on failure stop immediately,
    print the return code and the tail of the log. No in-guest `tee` anywhere.
  * Multiple PyPI mirrors with 429 fallback. pypi.org index answers 200 but wheel
    downloads stall on this network (measured 2026-11-05).
  * Zero hardcoded machine paths. External tools are resolved by env vars, a
    local mapping file, or generic probing; the mapping is regenerated each run.
  * Optional deps are installed with --no-deps where needed: plain `pip install pytdc`
    tries to downgrade numpy/pandas/rdkit and then fails to build numpy from source.

Usage:
    python bootstrap.py                      # core + optional + verify + pytest
    python bootstrap.py --core-only          # core deps only
    python bootstrap.py --verify-only        # audit only, install nothing
    python bootstrap.py --skip-tests         # skip the 4-minute pytest suite
    python bootstrap.py --mirror URL         # prepend a custom PyPI mirror
    python bootstrap.py --network           # also probe registered web sources
    python bootstrap.py --deep              # deep audit: ORCA single point + 1.2GB SI hash
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import importlib.metadata as _md
import io
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
LOCK = os.path.join(ROOT, "requirements.lock")
OPT = os.path.join(ROOT, "requirements-optional.txt")
PATH_MAP = os.path.join(ROOT, ".env_audit_paths.json")
LOG_DIR = os.path.join(ROOT, "logs")

MIRRORS = [
    "https://repo.huaweicloud.com/repository/pypi/simple/",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.tuna.tsinghua.edu.cn/simple/",
    "https://pypi.org/simple/",
]

# dist -> (import name, minimal functional probe returning str, or None)
CORE = [
    ("rdkit", "rdkit", "rdkit.Chem.MolFromSmiles('CCO').GetNumAtoms()"),
    ("pyyaml", "yaml", "yaml.safe_load('a: 1')"),
    ("requests", "requests", "requests.Session()"),
    ("numpy", "numpy", "numpy.array([1,2]).sum()"),
    ("scipy", "scipy", "scipy.stats.spearmanr([1,2,3],[1,2,3]).statistic"),
    ("scikit-learn", "sklearn", "sklearn.metrics.roc_auc_score([0,1],[.1,.9])"),
    ("pandas", "pandas", "pandas.DataFrame({'a':[1]}).shape"),
    ("beautifulsoup4", "bs4", "bs4.BeautifulSoup('<b>x</b>','html.parser').get_text()"),
    ("lxml", "lxml.etree", "lxml.etree.fromstring('<a/>').tag"),
    ("pytest", "pytest", None),
]

LOG_FH = None


def log(msg):
    line = "[%s] %s" % (_dt.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if LOG_FH:
        LOG_FH.write(line + "\n")
        LOG_FH.flush()


def die(msg, tail=""):
    log("FATAL: %s" % msg)
    if tail:
        log("---- last 40 lines of captured output ----")
        for l in tail.strip().splitlines()[-40:]:
            log("| " + l)
    log("Bootstrap aborted. Full log: %s" % (LOG_FH.name if LOG_FH else "(none)"))
    sys.exit(1)


def run(cmd, timeout=900, env=None):
    """Return (rc, combined_output). Never raises on missing exe / timeout."""
    e = os.environ.copy()
    if env:
        e.update({k: str(v) for k, v in env.items()})
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=e,
            cwd=ROOT,
        )
        return p.returncode, ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "FileNotFoundError: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "TimeoutExpired after %ss" % timeout
    except Exception as ex:
        return 126, "%s: %s" % (type(ex).__name__, ex)


def usable(dist, modname, probe_expr, expected=None):
    """Product-level check: import + version + minimal functional call."""
    try:
        m = importlib.import_module(modname)
    except Exception as ex:
        return False, "import failed: %s" % ex
    try:
        v = _md.version(dist)
    except Exception:
        v = getattr(m, "__version__", "unknown")
    if expected and v != expected:
        return False, "version %s != pinned %s" % (v, expected)
    if probe_expr:
        try:
            g = {"numpy": None}
            exec("import " + modname.split(".")[0], g)
            # scipy.stats / sklearn.metrics are lazy submodules: import explicitly
            for sub in ("scipy.stats", "sklearn.metrics", "rdkit.Chem", "lxml.etree"):
                try:
                    importlib.import_module(sub)
                except Exception:
                    pass
            eval(probe_expr, g)
        except Exception as ex:
            return False, "probe failed: %s" % ex
    return True, "ok (%s)" % v


def parse_pins(path):
    pins = []
    for ln in io.open(path, encoding="utf-8").read().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "==" not in s:
            continue
        pkg, ver = s.split("==", 1)
        pkg, ver = pkg.strip(), ver.strip()
        if "#" in ver:
            ver = ver.split("#", 1)[0].strip()
        pins.append((pkg, ver))
    return pins


def pip_install(args, mirrors, label, timeout=900):
    """Try mirrors in order; 429 / source-missing / stalled -> next mirror."""
    for m in mirrors:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--timeout",
            "30",
            "--retries",
            "1",
            "-i",
            m,
        ] + args
        log("pip [%s] via %s" % (label, m.split("/")[2]))
        rc, out = run(cmd, timeout=timeout)
        if LOG_FH:
            LOG_FH.write("\n===== %s / %s rc=%s =====\n%s\n" % (label, m, rc, out))
            LOG_FH.flush()
        if rc == 0:
            log("pip [%s] OK via %s" % (label, m.split("/")[2]))
            return True
        log("pip [%s] rc=%s via %s (trying next mirror)" % (label, rc, m.split("/")[2]))
        if "429" in out:
            time.sleep(2)
    log("pip [%s] FAILED on all %d mirrors" % (label, len(mirrors)))
    return False


def step_core(mirrors):
    pins = parse_pins(LOCK)
    if not pins:
        die("requirements.lock has no pinned lines")
    expected = dict(pins)
    missing = []
    for dist, mod, probe in CORE:
        ok, why = usable(dist, mod, probe, expected.get(dist))
        log("core %-16s %s" % (dist, why if not ok else "OK " + why))
        if not ok:
            missing.append((dist, why))
    if not missing:
        log(
            "core layer complete: %d/%d packages verified usable; nothing to install"
            % (len(CORE), len(CORE))
        )
        return
    log(
        "core layer missing %d packages -> installing from requirements.lock"
        % len(missing)
    )
    if not pip_install(["-r", LOCK], mirrors, "core"):
        die("core pip install failed", "see log")
    # re-verify: installing is not the same as working
    bad = [
        (d, w)
        for d, m, p in CORE
        for ok, w in [usable(d, m, p, expected.get(d))]
        if not ok
    ]
    if bad:
        die("core packages still unusable after install: %s" % bad[:5], "see log")


def step_optional(mirrors):
    """Pharmpy and pytdc need DIFFERENT pip strategies. Never merge into one -r."""
    # A. Pharmpy: distribution is pharmpy-core, not pharmpy
    ok, why = usable("pharmpy-core", "pharmpy", None)
    if not ok:
        log("optional pharmpy-core: %s -> installing" % why)
        if not pip_install(
            ["pharmpy-core==2.3.0"], mirrors, "pharmpy-core", timeout=1200
        ):
            die("pharmpy-core install failed", "see log")
    else:
        log("optional pharmpy-core OK (skipped)")
    ok2, why2 = usable("pharmpy-core", "pharmpy", None)
    if not ok2:
        die("pharmpy-core unusable after install: %s" % why2)

    # B. pytdc + minimal runtime, all --no-deps (see requirements-optional.txt)
    no_deps = [
        ("pytdc", "tdc"),
        ("tqdm", "tqdm"),
        ("fuzzywuzzy", "fuzzywuzzy"),
        ("openpyxl", "openpyxl"),
        ("setuptools", "pkg_resources"),
    ]
    todo = []
    for dist, mod in no_deps:
        ok, _ = usable(dist, mod, None)
        if not ok:
            todo.append(dist)
    if todo:
        pin = dict(parse_pins(OPT))
        specs = ["%s==%s" % (d, pin[d]) for d in todo if d in pin]
        log("optional pytdc helpers missing: %s -> installing with --no-deps" % todo)
        if not pip_install(["--no-deps"] + specs, mirrors, "pytdc-no-deps"):
            die("pytdc --no-deps install failed", "see log")
    # huggingface_hub needs its own transitive deps -> normal resolution is safe
    # (it does not touch numpy/pandas/rdkit; measured 2026-11-05)
    ok, why = usable("huggingface_hub", "huggingface_hub", None)
    if not ok:
        log("optional huggingface_hub missing -> installing")
        if not pip_install(["huggingface_hub==2.4.0"], mirrors, "hf-hub"):
            die("huggingface_hub install failed", "see log")
    # final product check on the real entry point
    rc, out = run(
        [sys.executable, "-c", "from tdc import BenchmarkGroup; print('TDC_OK')"],
        timeout=180,
    )
    if rc != 0 or "TDC_OK" not in out:
        die("from tdc import BenchmarkGroup still fails", out)
    log("optional layer verified: pharmpy + pytdc BenchmarkGroup import OK")


def _first_file(cands):
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return ""


def _env_has_rscript(env_dir):
    if not env_dir or not os.path.isdir(env_dir):
        return False
    return any(
        os.path.isfile(os.path.join(env_dir, r))
        for r in ("Scripts/Rscript.exe", "bin/Rscript", "lib/R/bin/x64/Rscript.exe")
    )


def _candidate_paths():
    from shutil import which

    osp_env = os.environ.get("ADT_OSP_DIR", "")
    osp = osp_env or ""
    if not osp:
        for c in (
            os.path.join(HOME, ".workbuddy", "binaries", "osp"),
            os.path.join(ROOT, "_vendor", "osp"),
            "/opt/osp",
        ):
            if os.path.isdir(c):
                osp = c
                break
    pksim = _first_file(
        [
            os.path.join(osp, "PKSim", "PKSim.CLI.exe") if osp else "",
            os.path.join(osp, "PKSim", "PKSim.CLI") if osp else "",
            which("PKSim.CLI") or "",
        ]
    )
    mobi = _first_file(
        [
            os.path.join(osp, "MoBi", "MoBi.exe") if osp else "",
            os.path.join(osp, "MoBi", "MoBi") if osp else "",
        ]
    )
    mamba_env = os.environ.get("ADT_MAMBA_EXE", "")
    mamba = mamba_env or _first_file(
        [
            os.path.join(
                HOME,
                ".workbuddy",
                "binaries",
                "micromamba",
                "Library",
                "bin",
                "micromamba.exe",
            ),
            os.path.join(
                HOME, ".workbuddy", "binaries", "micromamba", "bin", "micromamba"
            ),
            os.path.join(ROOT, "_vendor", "bin", "micromamba.exe"),
            which("micromamba") or "",
        ]
    )
    root = os.environ.get("ADT_MAMBA_ROOT") or os.environ.get("MAMBA_ROOT_PREFIX", "")
    pkpd_env = os.environ.get("ADT_PKPD_ENV", "")
    pkpd = pkpd_env or ""
    if not pkpd:
        for c in (
            os.path.join(root, "envs", "pkpd") if root else "",
            os.path.join(HOME, ".workbuddy", "binaries", "mamba", "pkpd"),
            os.path.join(ROOT, "_vendor", "envs", "pkpd"),
        ):
            if _env_has_rscript(c):
                pkpd = c
                break
    # ORCA / OneADMET: reuse env_audit's discovery so the two implementations
    # cannot drift apart. env_audit is pure stdlib, so this works even when the
    # scientific stack is broken.
    try:
        from adt.env_audit import discover_orca as _discover_orca
    except Exception:
        _discover_orca = None
    orca_dir = os.environ.get("ADT_ORCA_DIR", "")
    if not orca_dir and _discover_orca:
        try:
            orca_dir = _discover_orca()
        except Exception:
            orca_dir = ""
    if orca_dir:
        orca_dir = os.path.normpath(orca_dir)
        if not _first_file(
            [os.path.join(orca_dir, "orca.exe"), os.path.join(orca_dir, "orca")]
        ):
            orca_dir = ""
    oneadmet_csv = os.environ.get("ADT_ONEADMET_CSV", "") or _first_file(
        [
            os.path.join(ROOT, "assets", "external", "oneadmet", "oneADMET.csv"),
            os.path.join(
                ROOT, "assets", "external", "oneadmet", "extracted", "oneADMET.csv"
            ),
        ]
    )
    if not pkpd and mamba:
        # Machine-readable discovery: on a new machine there is no path map yet.
        # micromamba env list --json lists every environment; pick one that actually
        # contains Rscript (product-level check, not "directory exists").
        rc, out = run([mamba, "env", "list", "--json"], timeout=90)
        if rc == 0:
            try:
                envs = json.loads(out).get("envs", [])
            except Exception:
                envs = []
            for e in envs:
                if _env_has_rscript(e):
                    pkpd = e
                    log("auto-discovered R/PK-PD env via micromamba env list: %s" % e)
                    break
    return {
        "osp_dir": osp,
        "mamba": mamba,
        "mamba_root": root,
        "pkpd": pkpd,
        "pyscf_env": os.environ.get("ADT_PYSCF_ENV", ""),
        "openmm_env": os.environ.get("ADT_OPENMM_ENV", ""),
        "orca_dir": orca_dir,
        "oneadmet_csv": oneadmet_csv,
        "_pksim_found": bool(pksim),
        "_mobi_found": bool(mobi),
    }


def step_external_maps():
    """Probe external tools, write the local mapping, and print official URLs if absent.

    Download policy: OSP portable ZIPs and the R/conda-forge environment are large
    and GitHub/conda-forge are slow or blocked on this network. bootstrap does NOT
    guess asset names; it prints exact official URLs and target directories instead.
    """
    c = _candidate_paths()
    # Re-entry rule: a fresh probe must not erase a previously verified path.
    # If the new value is empty but the old one still points at a real product,
    # keep the old one (otherwise re-running bootstrap would silently degrade).
    old = {}
    if os.path.isfile(PATH_MAP):
        try:
            old = json.loads(io.open(PATH_MAP, encoding="utf-8").read())
        except Exception:
            old = {}
    keys = (
        "osp_dir",
        "mamba",
        "mamba_root",
        "pkpd",
        "pyscf_env",
        "openmm_env",
        "orca_dir",
        "oneadmet_csv",
    )
    merged = {}
    for k in keys:
        v = c.get(k, "")
        if not v and old.get(k):
            ov = old[k]
            if k == "pkpd":
                still_ok = _env_has_rscript(ov)
            elif k == "orca_dir":
                still_ok = bool(
                    _first_file(
                        [os.path.join(ov, "orca.exe"), os.path.join(ov, "orca")]
                    )
                )
            elif k == "oneadmet_csv":
                still_ok = os.path.isfile(ov)
            else:
                still_ok = os.path.exists(ov)
            if still_ok:
                v = ov
                log("path map: keep previously verified %s" % k)
        merged[k] = v
    payload = {
        "_comment": "Generated by bootstrap.py. Re-run bootstrap on a new machine; do not copy this file across machines.",
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    payload.update(merged)
    with io.open(PATH_MAP, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    log("local path map -> %s" % PATH_MAP)
    if not c["orca_dir"]:
        log(
            "MISSING ORCA       -> official: https://www.faccts.de/customer/ (academic registration)"
        )
        log(
            "                      set ADT_ORCA_DIR to the directory containing orca.exe"
        )
    if not c["oneadmet_csv"]:
        log(
            "MISSING OneADMET SI -> official: https://pubs.acs.org/doi/10.1021/acs.jmedchem.6c00049"
        )
        log(
            "                      jm6c00049_si_002.zip -> assets/external/oneadmet/oneADMET.csv"
        )
        log(
            "                      or set ADT_ONEADMET_CSV; module L cannot reproduce without it"
        )
    if not c["_pksim_found"]:
        log(
            "MISSING PKSim.CLI  -> official: https://github.com/Open-Systems-Pharmacology/PK-Sim/releases"
        )
        log(
            "                     portable ZIP -> <skill>/_vendor/osp/PKSim ; set ADT_OSP_DIR"
        )
    if not c["mamba"]:
        log(
            "MISSING micromamba -> official: https://micro.mamba.pm/api/micromamba/win-64/latest"
        )
        log(
            "                     (Linux/macOS: https://micro.mamba.pm/api/micromamba/<platform>/latest)"
        )
    if not c["pkpd"]:
        log(
            "MISSING R/PK-PD env -> conda-forge via micromamba; see SETUP_REPRODUCE.md section 5b"
        )
        log(
            "                     official index: https://conda.anaconda.org/conda-forge/"
        )
    return c


def step_fingerprint():
    rc, out = run(
        [sys.executable, "-m", "adt", "env-fp", "--out", "env_fingerprint.json"],
        timeout=180,
    )
    if rc != 0:
        die("env-fp failed", out)
    log(
        "env_fingerprint.json regenerated (a new machine legitimately drifts; G4 will warn)"
    )


def step_verify(network, skip_tests, deep=False):
    args = [
        sys.executable,
        "-m",
        "adt",
        "env-audit",
        "--json-out",
        "env_audit_report.json",
    ]
    if network:
        args.append("--network")
    if deep:
        args.append("--deep")
    rc, out = run(args, timeout=600)
    log(out[-2500:])
    if rc == 1:
        die("env-audit reports REQUIRED layer missing (exit 1)", out)
    if rc not in (0, 2):
        die("env-audit crashed (exit %s)" % rc, out)
    log("env-audit exit=%s (0=all green, 2=optional/external warnings only)" % rc)
    if not skip_tests:
        # 2026-11-22：默认 smoke 现有 103 例（含 13 个原生测试），
        # 旧 900s 会在较慢机器上误杀；全量实测约 15–25 分钟。
        rc, out = run([sys.executable, "-m", "pytest", "-q"], timeout=3600)
        log("pytest tail:\n" + "\n".join(out.strip().splitlines()[-15:]))
        if rc != 0:
            die("pytest failed (exit %s)" % rc, out)
        log("pytest OK")
    return rc


def main():
    global LOG_FH
    ap = argparse.ArgumentParser(
        description="Idempotent portable bootstrap for admet-screening"
    )
    ap.add_argument("--core-only", action="store_true", help="core dependencies only")
    ap.add_argument(
        "--verify-only", action="store_true", help="audit only, install nothing"
    )
    ap.add_argument("--skip-tests", action="store_true", help="skip pytest")
    ap.add_argument("--network", action="store_true", help="also probe web sources")
    ap.add_argument(
        "--deep",
        action="store_true",
        help="deep env-audit: ORCA H2O single point + OneADMET SI SHA256",
    )
    ap.add_argument("--mirror", default="", help="prepend a custom PyPI mirror")
    a = ap.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, "bootstrap_%s.log" % ts)
    LOG_FH = io.open(log_path, "w", encoding="utf-8")
    log("bootstrap start | python=%s | root=%s" % (sys.version.split()[0], ROOT))
    log("log: %s" % log_path)

    mirrors = ([a.mirror] if a.mirror else []) + MIRRORS
    if sys.version_info < (3, 11):
        die("Python >= 3.11 required (got %s)" % sys.version.split()[0])

    if a.verify_only:
        log("--verify-only: no installation")
        step_verify(a.network, a.skip_tests, a.deep)
    else:
        step_core(mirrors)
        if not a.core_only:
            step_optional(mirrors)
        step_external_maps()
        step_fingerprint()
        step_verify(a.network, a.skip_tests, a.deep)

    log("bootstrap DONE (exit 0). Next: python -m adt env-audit --quiet")
    if LOG_FH:
        LOG_FH.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
