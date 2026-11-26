# -*- coding: utf-8 -*-
"""把 Stage 1 冻结标准与第三方锚定**一次登记**进预注册链（PREREG §6 步骤 4 的代码化）。

为什么必须同一事件：`adt.prereg.Prereg.attach_anchor()` 是"事后补锚"，会被标
post_hoc_anchor=True 且 claim_allowed=False（见 references/PREREG_ANCHORING_CHECKLIST.md §2.3）。
只有 `register_criteria(..., external_anchor=...)` 这种"登记即锚定"才授予 claim 资格。

用法：
  python tools/prereg_anchor_stage1.py \
      --registry OSF --url https://osf.io/xxxxx --deposited-at 2026-11-23T10:30:00+08:00 \
      [--doi 10.17605/OSF.IO/XXXXX] [--log prereg/prereg.jsonl]

退出码：0=已锚定且 claim_allowed；3=未锚定；1=参数错误
"""

import argparse
import hashlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.prereg import Prereg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "PREREG_STAGE1_PACKAGE.md")

# 冻结标准（与 PREREG_STAGE1_PACKAGE.md §3/§5 逐条对应；改动即等于换实验，须重新锚定）
CRITERIA = {
    "primary_hypothesis": "H1: dU(S4-S1) > 0 (paired bootstrap 95%CI lower bound > 0) on >= 2 of 3 endpoints",
    "null_hypothesis": "H0: dU <= 0 or CI crosses 0 on >= 2 endpoints",
    "endpoints": ["herg", "dili", "bbb_martins"],
    "cost_ref": {"c_false_PASS": 5, "c_false_FAIL": 1, "c_abstain": 0.5},
    "ad_threshold": 0.35,
    "target_risk": 0.15,
    "seeds_per_costpoint": 20,
    "bootstrap": {"seed": 20261103, "B": 10000, "method": "percentile"},
    "multiplicity": "holm-bonferroni within 3-endpoint family (m=3)",
    "secondary": [
        "H2: cost-grid scan c_abstain in {0.05,0.1,0.2,0.5,1.0} x c_false_PASS in {2,5,10}; report all points",
        "H3: dU(S4-S3) not positive at c_ref",
    ],
    "sample": {
        "n_min_per_endpoint": 30,
        "stopping": "fixed n, single unblinding, no post-hoc top-up",
    },
    "failure_rule": "if >=2/3 endpoints have CI lower bound <= 0 -> H1 not supported; publish negative result",
    "estimand_rule": "if any endpoint estimand NOT_BOUND -> withdraw inferential claim for that endpoint",
    "forbidden": "compare AUC (ranking, chance 0.5) with always-positive accuracy (prevalence) in the same sentence",
}


def sha256_of(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="OSF")
    ap.add_argument("--url", required=True)
    ap.add_argument("--doi", default=None)
    ap.add_argument("--deposited-at", default=None)
    ap.add_argument("--log", default=os.path.join(ROOT, "prereg", "prereg.jsonl"))
    ap.add_argument("--note", default="Stage 1 RR 冻结标准 + 第三方锚定（同事件登记）")
    args = ap.parse_args(argv)

    anchor = {"registry": args.registry, "url": args.url}
    if args.doi:
        anchor["doi"] = args.doi
    if args.deposited_at:
        anchor["deposited_at"] = args.deposited_at
    if os.path.isfile(DOC):
        anchor["doc_sha256"] = sha256_of(DOC)

    p = Prereg(args.log)
    pid = p.register_criteria(
        name="evidence_source_admission_stage1",
        criteria=CRITERIA,
        note=args.note,
        external_anchor=anchor,
        prospective_data_window={
            "rule": "min(data_ts) > anchor_date",
            "data_ts_source": "Stage 2 labels table: collected_at",
            "checker": "Prereg.temporal_validity / "
            "adt.cli prereg-status --data-timestamps",
            "on_violation": "违规记录不得进入主分析集（exit 4）",
        },
    )
    st = p.anchor_status()
    print("[prereg] id=%s" % pid)
    print("[prereg] log=%s" % args.log)
    print(
        "[prereg] anchored=%s claim_allowed=%s post_hoc=%s"
        % (st.get("anchored"), st.get("claim_allowed"), st.get("post_hoc_anchor"))
    )
    for a in st.get("anchors", []):
        print(
            "[prereg] anchor=%s via=%s" % (a.get("url") or a.get("doi"), a.get("via"))
        )
    return 0 if st.get("claim_allowed") else 3


if __name__ == "__main__":
    sys.exit(main())
