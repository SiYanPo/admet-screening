# -*- coding: utf-8 -*-
"""CLI for the local, no-API ADMET toolkit.

Usage:
    python -m local_admet --list-tools
    python -m local_admet --tool "Molecular Descriptors" --smiles "CC(=O)O"
    python -m local_admet --tool all --smiles "Cn1cnc2c1c(=O)n(C)c(=O)n2C"
    python -m local_admet --tool "ADMET Predictor" --smiles-file lib.smi \
        --features T --format long --out out/local_admet.csv
    python -m local_admet --selftest

Exit codes: 0 ok, 2 bad args / parse error.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import io
import json
import os
import sys

from .tools import TOOL_NAMES, TOOL_ALIASES, normalize_tool, run_tool

SOURCE = "local_admet"
SOURCE_VERSION = "1.0.0"

# endpoint -> unit for the long-table writer (scalar endpoints only)
_DESC_UNITS = {
    "MW": "Da",
    "exact_MW": "Da",
    "heavy_atoms": "count",
    "logP_crippen": "logP",
    "TPSA": "Angstrom^2",
    "HBD": "count",
    "HBA": "count",
    "rotatable_bonds": "count",
    "rings": "count",
    "aromatic_rings": "count",
    "fraction_csp3": "fraction",
    "molar_refractivity": "cm^3/mol",
    "QED": "unitless",
    "lipinski_violations": "count",
}


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _iter_inputs(args):
    """Yield (compound_id, smiles)."""
    if args.smiles:
        cid = args.id or "mol_1"
        yield cid, args.smiles
        return
    if not args.smiles_file:
        raise SystemExit("need --smiles or --smiles-file")
    with io.open(args.smiles_file, encoding="utf-8") as fh:
        i = 0
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            smi = parts[0]
            cid = parts[1] if len(parts) > 1 else ("mol_%d" % (i + 1))
            i += 1
            yield cid, smi


def _scalars(tool, res):
    """Return list of (endpoint, value, unit) for the long-table writer."""
    out = []
    if tool == "Molecular Descriptors":
        for k, unit in _DESC_UNITS.items():
            if k in res:
                out.append((k, res[k], unit))
    elif tool == "DeepEsol":
        out.append(("esol_logS_mol_per_L", res["esol_logS_mol_per_L"], "log10(mol/L)"))
        out.append(("esol_solubility_mg_per_L", res["esol_solubility_mg_per_L"], "mg/L"))
        out.append(("dG_solv_proxy_kcal_per_mol",
                    res["dG_solv_proxy_kcal_per_mol"], "kcal/mol"))
    elif tool == "OBA":
        out.append(("bioavailability_score_martin",
                    res["bioavailability_score_martin"], "unitless"))
    elif tool == "ADMET Predictor":
        for ep, v in res["endpoints"].items():
            if isinstance(v, dict) and "prob_proxy" in v:
                out.append((ep, v["prob_proxy"], "prob_proxy_unitless"))
    # Graph-pKa / AOMP are multi-valued -> JSON only
    return out


def _run_one(tool, cid, smiles, args):
    kw = {}
    if args.features:
        kw["features"] = args.features
    if args.dose_mg is not None:
        kw["dose_mg"] = args.dose_mg
    if args.ph is not None:
        kw["ph"] = args.ph
    res = run_tool(tool, smiles, **kw)
    if isinstance(res, dict):
        res.setdefault("compound_id", cid)
    return res


def _selftest():
    cases = {
        "ethanol": "CCO",
        "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
        "caffeine": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
        "imidazole": "c1cnc[nH]1",
        "aniline": "Nc1ccccc1",
        "nitrobenzene": "[O-][N+](=O)c1ccccc1",
    }
    fails = 0
    for cid, smi in cases.items():
        for tool in TOOL_NAMES:
            try:
                r = run_tool(tool, smi)
                assert r.get("tool") == tool
                assert r.get("method") == "rule-based-local-proxy"
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print("[FAIL] %s / %s: %r" % (cid, tool, exc))
    print("[selftest] %d molecules x %d tools, failures=%d"
          % (len(cases), len(TOOL_NAMES), fails))
    return 0 if fails == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="local_admet",
        description="Offline RDKit-based approximations of the six SciMiner admet-pkpd tools "
                    "(ADMET Predictor / AOMP / OBA / Graph-pKa / DeepEsol / Molecular Descriptors). "
                    "No API, no credits, no network.")
    ap.add_argument("--tool", help="one of the 6 tool names (or alias), or 'all'")
    ap.add_argument("--smiles", help="single SMILES")
    ap.add_argument("--smiles-file", help="file: '<SMILES> [id]' per line")
    ap.add_argument("--id", help="compound_id for single --smiles")
    ap.add_argument("--features", help="ADMET Predictor feature filter, e.g. 'T' or 'A,D,T' or endpoint names")
    ap.add_argument("--dose-mg", type=float, dest="dose_mg", help="OBA dose in mg")
    ap.add_argument("--ph", type=float, help="Graph-pKa target pH (default 7.4)")
    ap.add_argument("--format", choices=["json", "long"], default="json",
                    help="json = full result; long = measurements.csv-compatible long table")
    ap.add_argument("--out", help="output path (default stdout for json; local_admet_<tool>.csv for long)")
    ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--deterministic", action="store_true",
                    help="long 表的 retrieved_at 写固定占位而非运行时间戳，"
                         "使两次运行逐字节一致（与 skill 的确定性纪律对齐）")
    args = ap.parse_args(argv)

    if args.list_tools:
        print(json.dumps({"tools": TOOL_NAMES,
                          "aliases": sorted(set(TOOL_ALIASES))},
                         ensure_ascii=False, indent=2))
        return 0
    if args.selftest:
        return _selftest()
    if not args.tool:
        ap.error("--tool is required (use --list-tools to see options)")

    tools = TOOL_NAMES if str(args.tool).strip().lower() == "all" else [normalize_tool(args.tool)]
    results = []
    long_rows = []
    # 确定性档：固定占位，两次运行逐字节一致；默认档保留真实时间戳（向后兼容）。
    stamp = "DETERMINISTIC" if args.deterministic else _now()
    for cid, smi in _iter_inputs(args):
        for tool in tools:
            res = _run_one(tool, cid, smi, args)
            results.append(res)
            if args.format == "long":
                for ep, val, unit in _scalars(tool, res):
                    long_rows.append({
                        "compound_id": cid,
                        "endpoint": ep,
                        "value": val,
                        "unit": unit,
                        "source": SOURCE,
                        "source_version": SOURCE_VERSION,
                        "retrieved_at": stamp,
                        "domain_flag": "predicted",
                        "uncertainty": "",
                        "provenance_url": "",
                        "note": "rule-based local proxy (rule-based-local-proxy); NOT SciMiner model",
                    })

    if args.format == "long":
        out = args.out or "local_admet_%s.csv" % (
            "all" if len(tools) > 1 else tools[0].replace(" ", "_").replace("-", ""))
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        fields = ["compound_id", "endpoint", "value", "unit", "source", "source_version",
                  "retrieved_at", "domain_flag", "uncertainty", "provenance_url", "note"]
        with io.open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for row in long_rows:
                w.writerow(row)
        print("[local_admet] wrote %d rows -> %s" % (len(long_rows), out), file=sys.stderr)
        return 0

    payload = results[0] if (len(results) == 1 and str(args.tool).strip().lower() != "all") else results
    txt = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        d = os.path.dirname(args.out)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with io.open(args.out, "w", encoding="utf-8") as fh:
            fh.write(txt + "\n")
        print("[local_admet] wrote %s" % args.out, file=sys.stderr)
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
