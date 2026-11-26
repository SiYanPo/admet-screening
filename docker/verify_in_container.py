# -*- coding: utf-8 -*-
"""容器内自检：证明这个 digest 对应的镜像**真的能算**，而不是只能 import。

判定标准（任一失败即 exit 1）：
  1. RDKit 能解析真实药物结构并算出可复算的描述符（数值与 2026-11-23 宿主一致）；
  2. 指纹 Tanimoto 可算且落在 (0,1) 内；
  3. `adt` 包可导入且版本号可读；
  4. `python -m adt.cli --help` 返回 0（CLI 入口在容器内可用）。
"""
import json
import os
import subprocess
import sys

# 直接以脚本方式运行时 sys.path[0] 是脚本目录，加回工作目录以便找到源码树
sys.path.insert(0, os.getcwd())

FAIL = []


def check(name, ok, detail):
    print(("PASS  " if ok else "FAIL  ") + name + " :: " + str(detail))
    if not ok:
        FAIL.append(name)


try:
    import rdkit
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    from rdkit.Chem import AllChem
    from rdkit import DataStructs

    check("rdkit_import", True, rdkit.__version__)

    asp = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")   # aspirin
    sal = Chem.MolFromSmiles("OC(=O)c1ccccc1O")         # salicylic acid
    check("parse_aspirin", asp is not None, "atoms=%d" % (asp.GetNumAtoms() if asp else -1))

    mw = round(Descriptors.MolWt(asp), 2)
    formula = rdMolDescriptors.CalcMolFormula(asp)
    # 阿司匹林 C9H8O4，MW 180.16 —— 硬编码期望值，算错就报错
    check("aspirin_mw", abs(mw - 180.16) < 0.05, "MW=%.2f (expect 180.16)" % mw)
    check("aspirin_formula", formula == "C9H8O4", formula)

    fa = AllChem.GetMorganFingerprintAsBitVect(asp, 2, nBits=2048)
    fs = AllChem.GetMorganFingerprintAsBitVect(sal, 2, nBits=2048)
    tan = DataStructs.TanimotoSimilarity(fa, fs)
    check("tanimoto_in_range", 0.0 < tan < 1.0, "T(aspirin, salicylic)=%.4f" % tan)

except Exception as exc:  # noqa: BLE001
    check("rdkit_block", False, repr(exc))

try:
    import adt
    from adt._version import __version__ as adt_version
    check("adt_import", True, "adt %s" % adt_version)
except Exception as exc:  # noqa: BLE001
    adt_version = None
    check("adt_import", False, repr(exc))

try:
    rc = subprocess.run([sys.executable, "-m", "adt.cli", "--help"],
                        capture_output=True, timeout=180).returncode
    check("cli_help_rc", rc == 0, "rc=%d" % rc)
except Exception as exc:  # noqa: BLE001
    check("cli_help_rc", False, repr(exc))

print("\nCONTAINER_SELFTEST " + json.dumps(
    {"ok": not FAIL, "failures": FAIL, "adt_version": adt_version},
    ensure_ascii=False))
sys.exit(0 if not FAIL else 1)
