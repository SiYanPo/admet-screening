# -*- coding: utf-8 -*-
"""Zenodo 一条命令存证（restricted 文件 + 立即 DOI）。

为什么要有这个脚本
----------------
2026-11-23 实测：本机 `zenodo.org` **DNS 解析失败**，curl 直连生产返回
403 "unusual traffic from your network"（WAF 拦脚本）；浏览器加 host-resolver 规则能开页面，
但 ORCID 登录被"邮箱未确认"挡住（页面原文：A confirmation email has already been sent to 9…）。
因此把"存证"这件事做成**幂等、可一条命令重跑**的脚本：邮箱确认后（或换网络后）直接跑。

用法
----
  set ZENODO_TOKEN=xxxxx            # 在 https://zenodo.org/account/settings/applications/tokens/new/ 生成
  python tools/zenodo_deposit.py --dry-run      # 只建草稿+上传，不 publish（拿到预览 DOI）
  python tools/zenodo_deposit.py                # 正式 publish → 输出 DOI

  python tools/zenodo_deposit.py --base https://sandbox.zenodo.org   # 沙盒演练（DOI 是 10.5072，不可引用）

访问策略：`access_right=restricted` —— 元数据公开（可被引用/检索），**文件不公开**。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = [
    ("PREREG_STAGE1_PACKAGE.md", "text/markdown"),
    (os.path.join("references", "ENDPOINT_ESTIMAND_CARDS.yaml"), "text/yaml"),
    (os.path.join("references", "POSITIONING_EVIDENCE_2026-11-18.md"), "text/markdown"),
    # RFC3161 时间戳：与正文一起公开，第三方才能验"内容+时刻"两件事
    (
        os.path.join("anchors", "tsa", "PREREG_STAGE1_PACKAGE.md.tsr"),
        "application/timestamp-reply",
    ),
    (
        os.path.join("anchors", "tsa", "PREREG_STAGE1_PACKAGE.md.tsq"),
        "application/timestamp-query",
    ),
]

TITLE = (
    "PREREG-STAGE1-20261118-01 — When does evidence-source admission beat direct "
    "combination? A preregistered failure-boundary analysis of multi-source ADMET "
    "decision-making (Stage 1 protocol)"
)

DESC = """<p><strong>Stage 1 Registered Report protocol</strong> (package PREREG-STAGE1-20261118-01,
frozen 2026-11-18). This deposit contains the frozen hypotheses, statistical analysis plan (SAP) and
endpoint estimand cards of a preregistered study asking <em>when</em> an evidence-source-level
admission layer beats direct combination in multi-source ADMET prediction, and where it fails.</p>
<p><strong>Primary hypothesis (frozen).</strong> At c_ref=(c_false_PASS, c_false_FAIL, c_abstain)=(5,1,0.5),
AD threshold &tau;=0.35 and target_risk=0.15, the paired utility difference &Delta;u(S4&minus;S1) is
significantly positive (paired bootstrap 95% CI lower bound &gt; 0) on at least 2 of 3 endpoints
(hERG, DILI, BBB_Martins).</p>
<p><strong>Failure-as-conclusion clause.</strong> Whether or not the primary endpoint supports the
hypothesis, the preregistered protocol is reported in full; a negative result is published without
endpoint substitution, sample top-up or threshold re-tuning.</p>
<p><strong>Access.</strong> Metadata is public; files are restricted at this stage (the protocol is under
journal consideration). Access requests will be honoured after Stage 1 acceptance.</p>
<p><strong>Integrity.</strong> SHA256 of every deposited file is included in <code>SHA256SUMS.txt</code>;
the protocol text hash is also recorded in the project's preregistration hash-chain.</p>"""


def sha256(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://zenodo.org")
    ap.add_argument("--token", default=os.environ.get("ZENODO_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true", help="建草稿+上传但不 publish")
    a = ap.parse_args(argv)

    if not a.token:
        print(
            "[fail] 缺 token：先到 %s/account/settings/applications/tokens/new/ 生成，"
            "勾 deposit:write + deposit:actions，然后 set ZENODO_TOKEN=..." % a.base
        )
        return 2

    try:
        import requests
    except ImportError:
        print("[fail] 需要 requests：pip install requests")
        return 2

    api = a.base.rstrip("/") + "/api"
    H = {"Authorization": "Bearer %s" % a.token}

    meta = {
        "metadata": {
            "title": TITLE,
            "upload_type": "publication",
            "publication_type": "other",
            "publication_date": "2026-11-18",
            "description": DESC,
            "creators": [{"name": "SiYanpo", "orcid": "0009-0004-6564-4760"}],
            "access_right": "restricted",
            "access_conditions": "Access requests will be honoured after Stage 1 acceptance.",
            "license": "cc-by-4.0",
            "keywords": [
                "preregistration",
                "registered report",
                "ADMET",
                "applicability domain",
                "multi-source evidence",
                "decision theory",
                "failure boundary",
                "negative result",
            ],
            "notes": "Package PREREG-STAGE1-20261118-01. Frozen 2026-11-18; do not edit after anchoring.",
            "prereserve_doi": True,
        }
    }

    r = requests.post(api + "/deposit/depositions", json=meta, headers=H, timeout=120)
    print("[create] %d" % r.status_code)
    if r.status_code >= 400:
        print(r.text[:500])
        if r.status_code == 403:
            print(
                "  -> 403 多半是本机网络被 Zenodo WAF 拦（见脚本头注释），换网络或用浏览器手动建。"
            )
        return 1
    dep = r.json()
    dep_id = dep["id"]
    doi = (dep.get("metadata") or {}).get("prereserve_doi", {}).get("doi") or (
        dep.get("doi") or ""
    )
    bucket = (dep.get("links") or {}).get("bucket", "")
    print("[draft] id=%s doi(reserved)=%s" % (dep_id, doi))

    # SHA256SUMS
    lines = []
    for rel, mime in FILES:
        p = os.path.join(ROOT, rel)
        lines.append("%s  %s" % (sha256(p), os.path.basename(p)))
    sums = "\n".join(lines) + "\n"
    tmp = os.path.join(ROOT, "out_sensitivity", "SHA256SUMS.txt")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(sums)

    targets = [(os.path.join(ROOT, rel), mime) for rel, mime in FILES]
    targets.append((tmp, "text/plain"))

    for path, mime in targets:
        name = os.path.basename(path)
        with io.open(path, "rb") as fh:
            r = requests.put(
                "%s/%s" % (bucket, name),
                data=fh.read(),
                headers={**H, "Content-Type": mime},
                timeout=300,
            )
        print("[upload] %-42s %d" % (name, r.status_code))
        if r.status_code >= 400:
            print(r.text[:300])
            return 1

    if a.dry_run:
        print(
            "\n[dry-run] 草稿已就绪：%s/deposit/%s  （未 publish，无正式 DOI）"
            % (a.base, dep_id)
        )
        print("[dry-run] DOI 仅在 publish 后生效")
        return 0

    r = requests.post(
        "%s/deposit/depositions/%s/actions/publish" % (api, dep_id),
        headers=H,
        timeout=180,
    )
    print("[publish] %d" % r.status_code)
    if r.status_code >= 400:
        print(r.text[:400])
        return 1
    out = r.json()
    doi = out.get("doi") or doi
    url = (out.get("links") or {}).get("html") or ("%s/record/%s" % (a.base, dep_id))
    print("\n[DOI] %s\n[URL] %s\ndeposition_id=%s" % (doi, url, dep_id))
    io.open(
        os.path.join(ROOT, "out_sensitivity", "zenodo_deposit.json"),
        "w",
        encoding="utf-8",
        newline="\n",
    ).write(
        json.dumps(
            {
                "doi": doi,
                "url": url,
                "deposition_id": dep_id,
                "access_right": "restricted",
                "files_sha256": lines,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    print(
        "[next] python tools/prereg_anchor_stage1.py --registry Zenodo "
        "--url %s --doi %s --deposited-at <ISO8601>" % (url, doi)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
