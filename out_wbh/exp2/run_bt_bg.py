# -*- coding: utf-8 -*-
"""后台跑 BioTransformer：ABIOTICBIO（非生物水解，近似 SIF/SCF）+ HGUT（菌群）。

目的：把"下一步实验"里两条湿实验的**可计算前置**先做掉——
  · SIF/SCF 水解稳定性  -> ABIOTICBIO（化学水解通道）
  · 肠道菌群脱糖苷      -> HGUT（微生物通道）
poll_timeout 提到 1800 s（站点排队实测 >240 s，见 query 363690 "In Queue"）。
"""
import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from adt import schema
from adt.cli import load_released_compounds
from adt.adapters.biotransformer import BioTransformerAdapter


def main():
    comps = load_released_compounds(
        os.path.join(ROOT, "out_wbh", "compounds.csv"), tag="bt")
    log = []
    for opt in ("ABIOTICBIO", "HGUT"):
        print("=" * 70, flush=True)
        print("OPTION", opt, flush=True)
        ad = BioTransformerAdapter(verbose=True, options=[opt], steps=1,
                                   poll_timeout=1800)
        try:
            res = ad.run(comps, chemical_class="cinnamoyl_glycoside")
        except Exception:
            print("[FATAL]", opt, traceback.format_exc(), flush=True)
            continue
        mp = os.path.join(HERE, "measurements_biotransformer_%s.csv" % opt)
        n = schema.write_measurements_checked(mp, res.measurements)
        print("[bt] %s: %d 行长表" % (opt, n), flush=True)
        if res.metabolites:
            schema.write_metabolites_checked(
                os.path.join(HERE, "metabolites_biotransformer_%s.csv" % opt),
                res.metabolites)
            print("[bt] %s: %d 个代谢产物" % (opt, len(res.metabolites)), flush=True)
        else:
            print("[bt] %s: 0 个代谢产物（0 != 无代谢）" % opt, flush=True)
        log.append({"option": opt,
                    "n_measurements": n,
                    "n_metabolites": len(res.metabolites),
                    "batch_qa": res.meta.get("batch_qa"),
                    "errors": res.meta.get("errors")})
        with io.open(os.path.join(HERE, "bt_run_meta.json"), "w",
                     encoding="utf-8") as fh:
            json.dump(log, fh, ensure_ascii=False, indent=2)
    print("DONE_ALL", flush=True)


if __name__ == "__main__":
    main()
