# -*- coding: utf-8 -*-
"""面板结构锚定：名称 → ChEMBL 结构（canonical/isomeric SMILES + InChIKey）。

为什么不用手写 SMILES：本仓库自己的红线是"名称→SMILES 只能作交互辅助，须由
InChIKey 锚定"。手写 30 个结构的立体与盐型极易出错（badcase 5：Terfenadine/Digoxin
在标准化时丢手性就是实例）。所以统一从 ChEMBL（免 key、可访问）取权威结构，
并把 `molecule_chembl_id` + `standard_inchi_key` 一起落盘，便于复核。

用法：
    python tools/panel_fetch.py --spec panel_spec.json --out panel_resolved.csv
    python tools/panel_fetch.py --spec panel_spec.json --verify   # 只复核已有 csv

spec 每条形如：
    {"id": "aspirin", "name": "aspirin", "chembl": "ASPIRIN",
     "class": "NSAID/酸性", "stereo": "defined", "triggers": ["pka", "glycoside-hyd"]}
`chembl` 字段是 ChEMBL pref_name（精确匹配，大小写不敏感）；留空则按 name 搜。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)  # 直接 `python tools/xxx.py` 时也能 import adt

API = "https://www.ebi.ac.uk/chembl/api/data/molecule/search"
FIELDS = [
    "id",
    "name",
    "chembl_id",
    "inchi_key",
    "smiles",
    "stereo",
    "chemical_class",
    "triggers",
    "source_note",
]


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def search(name):
    url = "%s?q=%s&format=json&limit=10" % (API, urllib.parse.quote(name))
    d = _get(url)
    return d.get("molecules") or []


def pick(mols, want):
    """优先 pref_name 精确匹配；否则退到第一个有结构的记录并标记。"""
    for m in mols:
        if (m.get("pref_name") or "").strip().upper() == (want or "").strip().upper():
            return m, "pref_name_exact"
    for m in mols:
        if m.get("molecule_structures"):
            return m, "first_with_structure"
    return None, "none"


def has_stereo(smiles):
    return ("@" in smiles) or ("/" in smiles) or ("\\" in smiles)


def relabel(smiles, current):
    """把 stereo 标签修正成三态：defined / racemic / undefined。

    2026-11-19 实测：ChEMBL 对**无手性**分子也给 canonical SMILES（无 @），
    初版一律降级成 `racemic_or_unspecified` 是错的——甲硝唑/对乙酰氨基酚这类
    根本没有立体问题，标成"立体未定"会污染下游的立体上限提示。
    判据用 RDKit 的 `could_have_stereo`（含未指定手性中心或有立体信息）。
    """
    if has_stereo(smiles):
        return "defined"
    try:
        from adt import pubchem as PB

        return "racemic" if PB.could_have_stereo(smiles) else "defined"
    except Exception:
        return current


def _relabel_csv(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    n = 0
    for r in rows:
        new = relabel(r["smiles"], r["stereo"])
        if new != r["stereo"]:
            r["source_note"] = (r.get("source_note") or "") + "/relabel:%s->%s" % (
                r["stereo"],
                new,
            )
            r["stereo"] = new
            n += 1
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("[panel] relabel %d 条 -> %s" % (n, path))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default="panel_resolved.csv")
    ap.add_argument("--verify", action="store_true", help="只复核已有 csv，不联网")
    ap.add_argument(
        "--relabel",
        action="store_true",
        help="用 RDKit 重判已有 csv 的 stereo 三态（不联网）",
    )
    a = ap.parse_args(argv)

    if a.relabel:
        _relabel_csv(a.out)
        return 0

    spec = json.load(io.open(a.spec, encoding="utf-8"))
    rows = []
    if a.verify:
        with io.open(a.out, encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        bad = [r for r in rows if not r["inchi_key"] or not r["smiles"]]
        print("[panel] %d 条，缺结构 %d 条" % (len(rows), len(bad)))
        return 0 if not bad else 4

    for it in spec["compounds"]:
        want = it.get("chembl") or it["name"]
        try:
            mols = search(want)
        except Exception as exc:
            print("[panel] %-14s 检索失败：%s" % (it["id"], exc), file=sys.stderr)
            mols = []
        m, how = pick(mols, want)
        if not m:
            print(
                "[panel] %-14s ✗ 未找到结构（%s）" % (it["id"], want), file=sys.stderr
            )
            continue
        st = m.get("molecule_structures") or {}
        smi = (st.get("canonical_smiles") or "").strip()
        ik = (st.get("standard_inchi_key") or "").strip()
        declared = it.get("stereo", "defined")
        declared = relabel(smi, declared)
        rows.append(
            dict(
                id=it["id"],
                name=it["name"],
                chembl_id=m.get("molecule_chembl_id") or "",
                inchi_key=ik,
                smiles=smi,
                stereo=declared,
                chemical_class=it.get("class", ""),
                triggers=";".join(it.get("triggers") or []),
                source_note="chembl:%s/%s" % (how, m.get("molecule_chembl_id")),
            )
        )
        print(
            "[panel] %-14s ✓ %-12s %s %s"
            % (
                it["id"],
                m.get("molecule_chembl_id"),
                ik,
                "(stereo)" if has_stereo(smi) else "(no stereo)",
            )
        )

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("[panel] %d/%d 条 -> %s" % (len(rows), len(spec["compounds"]), a.out))
    return 0 if len(rows) == len(spec["compounds"]) else 4


if __name__ == "__main__":
    sys.exit(main())
