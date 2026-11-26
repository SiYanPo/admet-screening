# -*- coding: utf-8 -*-
"""同行评审 §3 疑点 5 / B16：生成 data manifest（SHA256 + 来源 URL + 许可）+ core 模式声明。

把 assets/ 下每个数据文件做 SHA256，合并各数据集已有的 PROVENANCE.json
（source_url / license / attribution），产出单一 `DATA_MANIFEST.json`。
core 模式列出"不含 1.2 GB 大数据也能跑"的最小文件集，供无资产机器复现核心流程。

用法：python tools/data_manifest.py [--out DATA_MANIFEST.json]
退出码恒 0；manifest 是审计产物，不是门禁。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
# 核心必需：无这些无法跑基础决策链；1.2 GB OneADMET 明确排除
CORE_FILES = {
    "controls/controls.csv",
    "herg_reference_ic50.csv",
    "truth_template.csv",
    "external/openadmet/expansion_data_train.csv",
    "external/openadmet/expansion_data_test.csv",
    "external/openadmet/PROVENANCE.json",
    "external/openadmet/LICENSE.md",
    "external/npass/npass_tox_ld50_rat.csv",
    "external/npass/npass_adme_subset.csv",
    "external/npass/npass_structures_subset.csv",
    "external/npass/PROVENANCE.json",
}
BIG_DATA = "external/oneadmet/oneADMET.csv"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _provenance_map():
    """读取各数据集 PROVENANCE.json，按相对目录索引。"""
    out = {}
    for base, _dirs, files in os.walk(ASSETS):
        if "PROVENANCE.json" in files:
            p = os.path.join(base, "PROVENANCE.json")
            try:
                d = json.load(io.open(p, encoding="utf-8"))
            except Exception:
                d = {}
            rel_dir = os.path.relpath(base, ASSETS).replace("\\", "/")
            out[rel_dir] = d
    return out


def build():
    prov = _provenance_map()
    files = []
    for base, _dirs, names in os.walk(ASSETS):
        for n in sorted(names):
            fp = os.path.join(base, n)
            rel = os.path.relpath(fp, ASSETS).replace("\\", "/")
            # 找最近的 PROVENANCE 目录
            pdir = os.path.dirname(rel)
            meta = prov.get(pdir, {}) or {}
            if meta.get("file", {}).get("name") == n and "sha256" in meta.get(
                "file", {}
            ):
                declared = meta["file"]["sha256"]
            else:
                declared = ""
            files.append(
                dict(
                    path="assets/" + rel,
                    bytes=os.path.getsize(fp),
                    sha256=_sha256(fp),
                    declared_sha256=declared or None,
                    sha256_matches=(declared == _sha256(fp)) if declared else None,
                    source_url=(
                        meta.get("source")
                        or meta.get("source_url")
                        or meta.get("doi")
                        or ""
                    ),
                    license=(meta.get("license") or meta.get("license_note") or ""),
                    core=("yes" if rel in CORE_FILES else "no"),
                )
            )
    core_ok = all(f["sha256_matches"] is not False for f in files if f["core"] == "yes")
    return dict(
        generated_by="tools/data_manifest.py",
        n_files=len(files),
        core_mode=dict(
            description="不含 1.2 GB OneADMET 的最小可复现文件集",
            required_files=sorted("assets/" + r for r in CORE_FILES),
            excluded_large_file="assets/" + BIG_DATA,
            all_core_hashes_match=core_ok,
        ),
        files=files,
        note=(
            "1.2 GB OneADMET SI 的许可/下载需人工过 Cloudflare 验证；"
            "本 manifest 校验本地文件 SHA256，不承诺公开镜像可获得性。"
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "DATA_MANIFEST.json"))
    a = ap.parse_args()
    m = build()
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    print(
        "manifest: %d files, core hashes match=%s"
        % (m["n_files"], m["core_mode"]["all_core_hashes_match"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
