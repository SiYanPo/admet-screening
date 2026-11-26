# -*- coding: utf-8 -*-
"""v4.4 外部评审材料包 —— 生成器（单一入口，可重复执行，**全程零删除**）

设计要点
--------
1. **source of truth 唯一**：包内每个文件都从 skill 目录现取，不在包里手改。
2. **零删除**：不 rmtree、不删旧包。staging 只覆盖写同名文件；tar 用 "wb" 截断重写。
   历史产物一律留着，避免误删。
3. **tar 只按白名单构造**（不从 staging 目录 add）→ staging 里的任何残留都不会进包。
4. **可重复构建**：同一批源 → **逐位相同**的 .tar.gz（顺序/时间戳/uid/gzip 头全部归一）。
5. **双层清单**：顶层 MANIFEST.sha256（5 件） + 包内 MANIFEST.internal.sha256（全部）。
6. **自校验不解压**：直接读 tar 成员流算哈希，不落临时目录。

用法
----
    python build_review_package.py            # 生成 + 自校验
    python build_review_package.py --check    # 只校验已有包
"""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import sys
import tarfile

SK = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
ROOT = r"D:\WorkBuddy\本地文件\2026-11-01-09-12-03"
BASE = os.path.join(ROOT, "_staging_v44")
STG = os.path.join(BASE, "admet-screening-review")
OUT = os.path.join(ROOT, "外部评审材料产物_v4.4")
TARN = "admet-screening-review-data_v4.4.tar.gz"
ARC = "admet-screening-review"
INNER_MANIFEST = "MANIFEST.internal.sha256"

# ---------------------------------------------------------------- 白名单
CODE = [
    # 构建器本身必须进包：否则「可重复构建」只是一个无法效验的声明
    "build_review_package.py",
    "run_keystone.py", "run_blacklist_analysis.py", "run_blacklist_report.py",
    "run_evidence_export.py", "run_ad_multicriteria.py", "run_p8_mmp_regression.py",
    "run_leakage_attribution.py", "run_external_holdout.py",
    "run_tail_risk_stratified.py", "run_external_cuts_summary.py",
    "run_indifference.py", "run_spec_multiverse.py",
    "run_independence_gradient.py", "run_leakage_confound_check.py",
]
ADT = ["claims_audit.py", "defaults.py", "threshold_audit.py", "guards.py",
       "release_gate.py", "independence.py", "mmp.py", "stats_ci.py", "phrasing.py"]
TESTS = ["test_v44_guards.py", "test_v44_gates.py"]

DATA = [
    ("out_keystone/results.json", "data/out_keystone/results.json"),
    ("out_keystone_v43/results.json", "data/out_keystone_v43/results.json"),
    ("out_blacklist/results.json", "data/out_blacklist/results.json"),
    ("out_blacklist/tables.md", "data/out_blacklist/tables.md"),
    ("out_blacklist/export_meta.json", "data/out_blacklist/export_meta.json"),
    ("out_ext/tdc/ad_multicriteria.json", "data/out_ext/tdc/ad_multicriteria.json"),
    ("out_ext/tdc/ames_alerts.json", "data/out_ext/tdc/ames_alerts.json"),
    ("out_ext/tdc/gate_audit.json", "data/out_ext/tdc/gate_audit.json"),
    ("out_ext/tdc/gate_audit_DILI.json", "data/out_ext/tdc/gate_audit_DILI.json"),
    ("out_ext/tdc/gate_audit_BBB_Martins.json", "data/out_ext/tdc/gate_audit_BBB_Martins.json"),
    ("out_ext/tdc/independence_gradient.json", "data/out_ext/tdc/independence_gradient.json"),
    ("out_ext/tdc/leakage_attribution.json", "data/out_ext/tdc/leakage_attribution.json"),
    ("out_ext/tdc/leakage_confound_check.json", "data/out_ext/tdc/leakage_confound_check.json"),
    ("out_ext/tdc/p8_mmp_results.json", "data/out_ext/tdc/p8_mmp_results.json"),
    ("out_ext/tdc/p8_mmp_results_hERG.json", "data/out_ext/tdc/p8_mmp_results_hERG.json"),
    ("out_ext/tdc/p8_mmp_results_DILI.json", "data/out_ext/tdc/p8_mmp_results_DILI.json"),
    ("out_ext/tdc/p8_mmp_results_BBB_Martins.json", "data/out_ext/tdc/p8_mmp_results_BBB_Martins.json"),
    ("out_ext/external/herg_holdout.json", "data/out_ext/external/herg_holdout.json"),
    ("out_ext/external/herg_holdout_stratified.json", "data/out_ext/external/herg_holdout_stratified.json"),
    ("out_ext/external/herg_holdout_rows.csv", "data/out_ext/external/herg_holdout_rows.csv"),
    ("out_ext/external/herg_holdout_y2021_stratified.json", "data/out_ext/external/herg_holdout_y2021_stratified.json"),
    ("out_ext/external/herg_holdout_y2021_rows.csv", "data/out_ext/external/herg_holdout_y2021_rows.csv"),
    ("out_ext/external/_legacy_stratified.json", "data/out_ext/external/legacy_mixed_stratified.json"),
    ("out_ext/external/_legacy_rows.csv", "data/out_ext/external/legacy_mixed_rows.csv"),
    ("out_ext/external/external_cuts_summary.json", "data/out_ext/external/external_cuts_summary.json"),
    ("out_ext/keystone_indifference.json", "data/out_ext/keystone_indifference.json"),
    ("out_ext/keystone_indifference.md", "data/out_ext/keystone_indifference.md"),
    ("out_ext/keystone_spec_multiverse.json", "data/out_ext/keystone_spec_multiverse.json"),
    ("out_ext/keystone_spec_multiverse.md", "data/out_ext/keystone_spec_multiverse.md"),
    ("out_ext/threshold_freeze_audit.json", "data/out_ext/threshold_freeze_audit.json"),
    ("out_ext/claims_registry_check.json", "data/out_ext/claims_registry_check.json"),
]

DOCS = [
    ("SKILL.md", "docs/SKILL_v4.4.md"),
    ("references/REVIEW_v4.1_LEDGER.md", "docs/01_评审台账_REVIEW_v4.1_LEDGER.md"),
    ("references/TASK_SCORECARD_v4.2.md", "docs/02_任务计分卡_v4.2.md"),
    ("references/REVIEW_ROUND3_CHECKLIST_v4.4.md", "docs/03_第三轮核对清单_v4.4.md"),
    ("references/REVIEW_ROUND3_CLOSEOUT_v4.4.md", "docs/04_第三轮执行记录_v4.4.md"),
    ("references/TASK_SCORECARD_v4.4.md", "docs/05_任务计分卡_v4.4.md"),
    ("references/TAIL_RISK_THESIS.md", "docs/TAIL_RISK_THESIS.md"),
    ("references/PAPER_SKELETON_v4.4.md", "docs/PAPER_SKELETON_v4.4.md"),
    ("references/METASCIENCE_NOTE_OUTLINE.md", "docs/METASCIENCE_NOTE_OUTLINE.md"),
    ("references/CLAIMS_REGISTRY.yaml", "docs/CLAIMS_REGISTRY.yaml"),
    ("references/NEGATIVE_RESULT_DEFAULTS.yaml", "docs/NEGATIVE_RESULT_DEFAULTS.yaml"),
    ("references/THRESHOLD_REGISTRY.yaml", "docs/THRESHOLD_REGISTRY.yaml"),
    ("references/STATISTICAL_POLICY.md", "docs/STATISTICAL_POLICY.md"),
    ("references/INDEPENDENCE_DECISIONS.md", "docs/INDEPENDENCE_DECISIONS.md"),
    ("references/POSITIONING.md", "docs/POSITIONING.md"),
    ("references/GATE_AND_P8_MMP_v4.2.md", "docs/GATE_AND_P8_MMP_v4.2.md"),
    ("references/ENDPOINT_TIER_EVIDENCE.md", "docs/ENDPOINT_TIER_EVIDENCE.md"),
    ("references/UNRESOLVED_CLOSEOUT_v4.3.md", "docs/UNRESOLVED_CLOSEOUT_v4.3.md"),
    ("references/PEER_REVIEW_2026-10-31.md", "docs/PEER_REVIEW_2026-10-31.md"),
    ("references/REPRODUCIBILITY.md", "docs/REPRODUCIBILITY.md"),
    ("SETUP_REPRODUCE.md", "docs/SETUP_REPRODUCE.md"),
    ("references/TDC_ALIGNMENT.md", "docs/TDC_ALIGNMENT.md"),
]

ENV = [("requirements.lock", "env/requirements.lock"),
       ("requirements.txt", "env/requirements.txt"),
       ("env_fingerprint.json", "env/env_fingerprint.json")]

TOP_FILES = ["CLAIMS.md", "README.md", "README_INDEX.md", "VERIFICATION.md", TARN]


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def collect() -> tuple:
    """返回 ( [(abs_src, rel)], [missing], [dirs] )"""
    pairs, missing, dirs = [], [], set()

    def add(src_rel, dst_rel):
        s = os.path.join(SK, src_rel)
        if not os.path.exists(s):
            missing.append(src_rel)
            return
        pairs.append((s, dst_rel))
        parts = dst_rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))

    for f in CODE:
        add(f, "code/" + f)
    for f in ADT:
        add("adt/" + f, "code/adt/" + f)
    for f in TESTS:
        add("tests/" + f, "code/tests/" + f)
    for s, d in DATA:
        add(s, d)
    for s, d in DOCS:
        add(s, d)
    for s, d in ENV:
        add(s, d)

    rep_dir = os.path.join(SK, "replication")
    if os.path.isdir(rep_dir):
        for dp, _, fs in os.walk(rep_dir):
            for fn in sorted(fs):
                rp = os.path.join(dp, fn)
                rel = os.path.relpath(rp, rep_dir).replace(os.sep, "/")
                add("replication/" + rel, "replication/" + rel)
    return pairs, missing, sorted(dirs)


def mirror(pairs) -> None:
    """写一份人可读的展开副本到 staging（只覆盖写，不删除任何东西）"""
    for s, d in pairs:
        dd = os.path.join(STG, d)
        os.makedirs(os.path.dirname(dd), exist_ok=True)
        shutil.copy2(s, dd)


def inner_manifest(pairs) -> tuple:
    """包内清单：**按 pairs 生成**（不含 staging 残留）"""
    lines = []
    for s, d in pairs:
        lines.append("%s  %s" % (sha(s), d))
    lines.sort(key=lambda x: x.split("  ", 1)[1])
    body = "\n".join(lines) + "\n"
    p = os.path.join(STG, INNER_MANIFEST)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("# admet-screening-review v4.4 internal manifest\n")
        f.write("# %d files\n" % len(lines))
        f.write(body)
    return len(lines), body


def build_tar(pairs, dirs, manifest_body: str) -> int:
    """按 pairs 构造 tar（可重复：顺序/时间戳/uid/gzip 头全归一）"""
    os.makedirs(OUT, exist_ok=True)
    tar = os.path.join(OUT, TARN)

    def _ti(name, size=0, mode=0o644, isdir=False):
        ti = tarfile.TarInfo(name)
        ti.size = size
        ti.mode = mode
        ti.mtime = 0
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        if isdir:
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
        return ti

    with io.open(tar, "wb") as raw:                       # wb 截断重写，不是删除
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                           mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w",
                              format=tarfile.PAX_FORMAT) as tf:
                tf.addfile(_ti(ARC, isdir=True))
                for d in dirs:
                    tf.addfile(_ti(ARC + "/" + d, isdir=True))

                # 包内清单本身也进 tar
                mb = manifest_body.encode("utf-8")
                tf.addfile(_ti(ARC + "/" + INNER_MANIFEST, size=len(mb)),
                           io.BytesIO(mb))

                for s, d in sorted(pairs, key=lambda x: x[1]):
                    with open(s, "rb") as f:
                        data = f.read()
                    tf.addfile(_ti(ARC + "/" + d, size=len(data)),
                               io.BytesIO(data))
    return os.path.getsize(tar)


def top_manifest() -> list:
    head = [
        "# admet-screening 外部评审材料包 v4.4 —— 完整性校验清单 (MANIFEST.sha256)",
        "# 本包共 6 份材料：4 份文档 + 本清单 + 1 个数据包",
        "#",
        "# 用法（在包所在目录执行）：",
        "#   顶层 5 件：  sha256sum -c MANIFEST.sha256",
        "#   包内全部：   tar -xzf " + TARN,
        "#                cd " + ARC,
        "#                sha256sum -c " + INNER_MANIFEST,
        "#",
        "# Windows PowerShell 等价：",
        "#   Get-FileHash -Algorithm SHA256 CLAIMS.md,README.md,README_INDEX.md,"
        "VERIFICATION.md," + TARN,
        "#",
        "# 编码 UTF-8(LF)；格式与 coreutils sha256sum 兼容（两空格分隔）。",
        "#",
    ]
    body = ["%s  %s" % (sha(os.path.join(OUT, f)), f) for f in TOP_FILES]
    with io.open(os.path.join(OUT, "MANIFEST.sha256"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head + body) + "\n")
    return body


def verify() -> tuple:
    """自校验：顶层 5 件 + 包内全部（**不解压**，直接读 tar 成员流）"""
    bad_top = []
    for line in io.open(os.path.join(OUT, "MANIFEST.sha256"), encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        want, name = line.split("  ", 1)
        if sha(os.path.join(OUT, name)) != want:
            bad_top.append(name)

    bad_in, n, n_members = [], 0, 0
    with tarfile.open(os.path.join(OUT, TARN)) as tf:
        members = {}
        for m in tf.getmembers():
            n_members += 1
            if m.isfile():
                members[m.name] = m
        key = ARC + "/" + INNER_MANIFEST
        if key not in members:
            return bad_top, ["<包内清单缺失>"], 0
        txt = tf.extractfile(members[key]).read().decode("utf-8")
        for line in txt.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            want, rel = line.split("  ", 1)
            m = members.get(ARC + "/" + rel)
            if m is None:
                bad_in.append(rel + " (缺失)")
                n += 1
                continue
            got = hashlib.sha256(tf.extractfile(m).read()).hexdigest()
            n += 1
            if got != want:
                bad_in.append(rel)
    return bad_top, bad_in, n


def main(argv):
    if "--check" in argv:
        bt, bi, n = verify()
        print("顶层坏项 %d ；包内坏项 %d ；包内条目 %d" % (len(bt), len(bi), n))
        if bt or bi:
            print("坏项：", bt + bi)
            return 1
        print("CHECK PASSED")
        return 0

    pairs, missing, dirs = collect()
    if missing:
        print("!! 缺源文件 %d 个：" % len(missing))
        for m in missing:
            print("   ", m)

    os.makedirs(BASE, exist_ok=True)
    mirror(pairs)
    n_inner, body = inner_manifest(pairs)
    size = build_tar(pairs, dirs, body)
    top = top_manifest()

    bt, bi, n = verify()
    print("包内文件 %d 项 / 目录 %d 个；tar %.1f KB"
          % (n_inner, len(dirs) + 1, size / 1024.0))
    print("顶层校验：%d/%d OK" % (len(TOP_FILES) - len(bt), len(TOP_FILES)))
    print("包内校验：%d/%d OK" % (n - len(bi), n))
    for line in top:
        print("   ", line)
    if bt or bi:
        print("!! 坏项：", bt + bi)
        return 1
    print("SELF-CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
