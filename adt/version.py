# -*- coding: utf-8 -*-
"""C2-c / §7「版本单轨」：把四轨版本分歧变成机器可读、可审计的事实。

外审 C V8 判「-dev 是零成本通行券、版本四轨是沟通问题」；报告 §7 要求
「单一 version 由 commit SHA + OCI digest 派生」。本模块**不假装已实现单轨**——
当前仓库既无钉版容器 digest，也无第三方签名与固定 commit 锚，任何「由
commit+digest 派生版本」的写法都是编造。它只做两件诚实的事：
  1) 实测四轨版本并列出全部分歧；
  2) 与 references/VERSION_POLICY.yaml 的登记台账比对，未登记的新分歧即报错。

用法：python -m adt.version --json [--strict]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
POLICY = os.path.join(ROOT, "references", "VERSION_POLICY.yaml")


def read_sources(root=None):
    """返回 {来源: 观测到的版本字符串}；读不到记 None（不猜、不填空）。"""
    root = root or ROOT
    out = {}
    p = os.path.join(root, "SKILL.md")
    m = None
    if os.path.isfile(p):
        m = re.search(
            r"^version:\s*(\S+)\s*$", io.open(p, encoding="utf-8").read(), re.M
        )
    out["SKILL.md::version"] = m.group(1) if m else None

    p = os.path.join(root, "pyproject.toml")
    out["pyproject.toml::project.version"] = None
    if os.path.isfile(p):
        try:
            import tomllib

            with open(p, "rb") as f:
                d = tomllib.load(f)
            out["pyproject.toml::project.version"] = (d.get("project") or {}).get(
                "version"
            )
        except Exception:
            m = re.search(
                r'^version\s*=\s*"([^"]+)"', io.open(p, encoding="utf-8").read(), re.M
            )
            out["pyproject.toml::project.version"] = m.group(1) if m else None

    p = os.path.join(root, "CHANGELOG.md")
    m = (
        re.search(
            r"^##\s*v?([0-9][0-9A-Za-z.\-]*)", io.open(p, encoding="utf-8").read(), re.M
        )
        if os.path.isfile(p)
        else None
    )
    out["CHANGELOG.md::latest"] = m.group(1) if m else None

    # 文档轨：MODULE_MAP 文件名里带的版本号（历史双轨并行最直接的证据）
    docs = (
        [
            f
            for f in os.listdir(os.path.join(root, "references"))
            if f.startswith("MODULE_MAP_v")
        ]
        if os.path.isdir(os.path.join(root, "references"))
        else []
    )
    out["references/MODULE_MAP"] = (
        docs[0].split("_v")[-1].replace(".md", "") if docs else None
    )
    return out


def audit_version_sources(root=None):
    """返回四轨观测、分歧清单、以及「分歧是否全部登记在台账」。"""
    root = root or ROOT
    observed = read_sources(root)
    keys = sorted(observed)
    divergences = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if observed[a] != observed[b]:
                divergences.append("%s=%r vs %s=%r" % (a, observed[a], b, observed[b]))
    declared = []
    policy = {}
    if os.path.isfile(POLICY):
        import yaml

        policy = yaml.safe_load(io.open(POLICY, encoding="utf-8")) or {}
        declared = list(policy.get("known_divergences") or [])
    # 台账按「含关键版本串」匹配，避免要求逐字符复制整句
    undeclared = [d for d in divergences if not any(str(x) in d for x in declared)]
    return dict(
        schema_version="1.0",
        single_source_declared=(
            policy.get("single_source") or "SKILL.md::version（目标态，尚未生效）"
        ),
        observed=observed,
        n_sources=len(observed),
        divergences=divergences,
        n_divergences=len(divergences),
        n_declared=len(declared),
        undeclared=undeclared,
        status=(
            "known_divergence_pending_external_anchor"
            if not undeclared
            else "unregistered_divergence"
        ),
        target_state=(
            policy.get("target_state") or "单一 version 由 commit SHA + OCI digest 派生"
        ),
        blocking_items=(
            policy.get("blocking_items")
            or ["无钉版容器 digest", "无第三方签名", "无 commit 固定锚"]
        ),
        honesty_note=(
            "本机 CI 的 passed 仍是 self-attestation；版本号统一不等于"
            "信任根外置，见 references/TRUST_MODEL.md。"
        ),
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--strict", action="store_true", help="存在未登记的版本分歧时 exit 3"
    )
    ap.add_argument("--root", default=None)
    a = ap.parse_args(argv)
    r = audit_version_sources(a.root)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        for k, v in r["observed"].items():
            print("  %-40s %s" % (k, v))
        print(
            "分歧 %d 条 / 未登记 %d 条 / 状态 %s"
            % (r["n_divergences"], len(r["undeclared"]), r["status"])
        )
    if a.strict and r["undeclared"]:
        print(
            "[version] 存在未登记的版本分歧：%s" % r["undeclared"][:3], file=sys.stderr
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
