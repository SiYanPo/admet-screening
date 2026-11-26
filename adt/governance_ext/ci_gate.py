# -*- coding: utf-8 -*-
"""CI 门禁编排：pytest → 断言账本 → 变异分数 → 放行判定。

用法：
  python -m adt_proto.ci_gate --run-mutation      # 首次/定期跑变异
  python -m adt_proto.ci_gate                     # 日常：复用已有变异报告
  python -m adt_proto.ci_gate --skip-tests        # 只看账本/变异门禁

退出码非 0 表示 CI 失败。报告落 evidence/ci_gate_report.json。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from . import assertion_ledger, mutation_engine

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE = os.path.join(ROOT, "evidence")
KEY = os.path.join(EVIDENCE, ".ledger_hmac_key")
LEDGER = os.path.join(EVIDENCE, "assertion_ledger.json")
MUT_REPORT = os.path.join(EVIDENCE, "mutation_report.json")
MUT_BASE = os.path.join(EVIDENCE, "mutation_baseline.json")
SPLIT_REPORT = os.path.join(EVIDENCE, "split_audit_report.json")
OOD_REPORT = os.path.join(EVIDENCE, "ood_monotonicity_report.json")
TRUST_DOMAIN = os.path.join(EVIDENCE, "trust_domain.json")

# 这些函数若被变异后测试没抓住，视为门禁失败（与总分无关）
CRITICAL_FUNCTIONS = (
    "enforce_publish_gate",
    "assert_no_value_when_undetermined",
    "assert_out_of_domain_no_number",
    "semantic_interceptor",
)


def run_tests():
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--disable-warnings"]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return {
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "tail": (p.stdout + p.stderr)[-800:],
    }


def gate(*, run_mut=False, skip_tests=False, min_score=0.95):
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    if not skip_tests:
        out["checks"]["pytest"] = run_tests()
    else:
        out["checks"]["pytest"] = {"ok": True, "skipped": True}

    # 生产：CI 从 KMS/Secret 注入密钥，绝不把可重签密钥放进代码仓
    key_path = KEY
    env_key = os.environ.get("ADMET_LEDGER_KEY")
    if env_key:
        fd, key_path = tempfile.mkstemp(prefix="admet_ci_key_")
        with os.fdopen(fd, "wb") as fh:
            fh.write(env_key.encode("utf-8"))
    if not os.path.exists(key_path) and not env_key:
        assertion_ledger.generate_key(key_path)
    if not os.path.exists(LEDGER):
        assertion_ledger.build_ledger(os.path.join(ROOT, "tests"), key_path, LEDGER)
    led = assertion_ledger.verify_ledger(LEDGER, os.path.join(ROOT, "tests"), key_path)
    if env_key:
        os.remove(key_path)
    out["checks"]["assertion_ledger"] = led

    if run_mut or not os.path.exists(MUT_REPORT):
        rep = mutation_engine.run_mutation_tests(ROOT, out_path=MUT_REPORT)
    else:
        with open(MUT_REPORT, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
    out["mutation"] = {k: v for k, v in rep.items() if k != "mutants"}

    reasons = []
    if not out["checks"]["pytest"]["ok"]:
        reasons.append("pytest 失败")
    if not led["ok"]:
        reasons.append("断言账本签名/内容不一致: %s" % led["summary"])
    score = float(rep.get("score", 0))
    if score < min_score:
        reasons.append("变异分数 %.4f < 门禁 %.4f" % (score, min_score))
    crit_surv = [
        m
        for m in rep.get("mutants", [])
        if m["status"] == "survived" and m.get("function") in CRITICAL_FUNCTIONS
    ]
    if crit_surv:
        reasons.append(
            "核心函数存在存活变异: %s"
            % ["%s:%s" % (m["file"], m["line"]) for m in crit_surv[:5]]
        )
    if os.path.exists(MUT_BASE):
        with open(MUT_BASE, "r", encoding="utf-8") as fh:
            base = json.load(fh)
        g = assertion_ledger.check_mutation_non_regression(rep, MUT_BASE)
        out["checks"]["mutation_non_regression"] = g
        if not g["ok"]:
            reasons.extend(g["reasons"])
    else:
        out["checks"]["mutation_non_regression"] = {
            "skipped": True,
            "note": "缺基线，首次运行后请保存",
        }

    # 方向一：分割敏感性元断言必须存在且通过
    if not os.path.exists(SPLIT_REPORT):
        reasons.append("缺少分割敏感性审计报告（random/scaffold/cluster/time）")
        out["checks"]["split_sensitivity"] = {"ok": False, "missing": True}
    else:
        with open(SPLIT_REPORT, "r", encoding="utf-8") as fh:
            sp = json.load(fh)
        out["checks"]["split_sensitivity"] = sp.get("gate", sp)
        if not sp.get("gate", {}).get("ok"):
            reasons.append("分割敏感性门禁失败: %s" % sp.get("gate", {}).get("reasons"))

    # 贯穿性元断言：OOD 偏移单调性
    if not os.path.exists(OOD_REPORT):
        reasons.append("缺少 OOD 单调性元断言报告")
        out["checks"]["ood_monotonicity"] = {"ok": False, "missing": True}
    else:
        with open(OOD_REPORT, "r", encoding="utf-8") as fh:
            ood = json.load(fh)
        out["checks"]["ood_monotonicity"] = {
            "ok": ood.get("ok"),
            "reasons": ood.get("reasons"),
        }
        if not ood.get("ok"):
            reasons.append("OOD 单调性元断言失败: %s" % ood.get("reasons"))

    # 方向三：信任域分离证明
    if not os.path.exists(TRUST_DOMAIN):
        reasons.append("缺少信任域分离证明（KMS/不可变记录/独立测量）")
        out["checks"]["trust_domain"] = {"ok": False, "missing": True}
    else:
        with open(TRUST_DOMAIN, "r", encoding="utf-8") as fh:
            td = json.load(fh)
        from .regulatory_seal import TrustDomainConfig, trust_domain_gate

        cfg = TrustDomainConfig(
            td.get("key_store_domain", "same"),
            td.get("record_store_domain", "same"),
            td.get("measurement_domain", "same"),
        )
        g = trust_domain_gate(cfg)
        out["checks"]["trust_domain"] = g
        if not g["ok"]:
            reasons.append("信任域未分离: %s" % g["reasons"])

    out["ok"] = not reasons
    out["reasons"] = reasons
    os.makedirs(EVIDENCE, exist_ok=True)
    with open(
        os.path.join(EVIDENCE, "ci_gate_report.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-mutation", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--min-score", type=float, default=0.95)
    a = ap.parse_args()
    r = gate(run_mut=a.run_mutation, skip_tests=a.skip_tests, min_score=a.min_score)
    print(
        json.dumps(
            {"ok": r["ok"], "reasons": r["reasons"], "mutation": r["mutation"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if r["ok"] else 1)
