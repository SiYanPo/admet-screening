# -*- coding: utf-8 -*-
"""数据源健康探针（可复跑、带时间戳）——只做 GET，**不提交预测作业**。

## 为什么需要

`references/02_source_registry.yaml` 里的 `verified_at: 2026-10-27` 是**静态结论**。
站点会迁移、会复活、会再死：pkCSM 2026-11-04 从 unimelb 迁到 UQ 后
「首页 200、表单完整、示例页 200」，但预测后端 8/8 返回 500 —— 登记表里
专门写了「首页 200 是引诱」。若半年后有人只读旧结论，就会把死源当活源引用。

本模块把「当时实测过」变成「现在随时可复跑」，并强制区分两件事：

  frontend_reachable   GET 首页/表单页是否 200
  prediction_available **永远不由 GET 判定**，默认 null/unknown

## 三条纪律

1. **不自动改写注册表**。健康检查的产物是报告，不是 `status: ok` 的授权。
   状态升级必须由人看过预测端点真出结果后手工改 02_source_registry.yaml。
2. **不提交预测作业**。POST 可能触发排队/限流/封禁，且 BioTransformer 的
   worker 死锁只有提交后才知道 —— 本探针明确把该项记为 `not_probed`，
   不制造「端口通 = 服务可用」的假象。
3. **失败落盘、不静默**。每个源的异常类型/消息/最终 URL 都写进 JSON，
   便于按第一手证据定位，而不是只打印「失败」。

## 用法

    python -m adt.cli source-health --outdir out_source_health
    python -m adt.cli source-health --sources pkcsm admetasar3 swissadme \
        --outdir out_source_health --timeout 6
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from collections import OrderedDict

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_REGISTRY = os.path.join(ROOT, "references", "02_source_registry.yaml")

_TITLE_PAT = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# 只探这些：本地/无需 key/论文级/明确 dead 的源不探（探了也没有判别力）
DEFAULT_PROBE = ("pkcsm", "admetasar3", "swissadme", "biotransformer")


def load_registry(path=None):
    p = path or DEFAULT_REGISTRY
    d = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    return {s.get("name"): s for s in (d.get("sources") or []) if s.get("name")}


def _get(url, timeout):
    """单次 GET。返回 (ok, code, final_url, nbytes, title, error)。"""
    try:
        import requests
    except Exception as e:  # pragma: no cover
        return False, None, url, 0, "", "requests_import_failed: %s" % e
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "adt-source-health/1.0"},
        )
        m = _TITLE_PAT.search(r.text or "")
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""
        return (
            r.status_code == 200,
            r.status_code,
            r.url,
            len(r.content or b""),
            title,
            "",
        )
    except Exception as e:
        return False, None, url, 0, "", "%s: %s" % (type(e).__name__, str(e)[:200])


def probe(names=None, timeout=8, registry_path=None, outdir=None):
    """探测并可选落盘。返回完整报告 dict。

    报告是**状态快照**，含 generated_at（与 interference.py 的确定性产物
    刻意不同：这里时间是证据的一部分）。
    """
    reg = load_registry(registry_path)
    # 空列表是「显式不探任何源」，不是「用缺省」——否则单测会意外联网（语义走查）
    targets = list(names) if names is not None else list(DEFAULT_PROBE)
    unknown = [n for n in targets if n not in reg]
    if unknown:
        raise ValueError("源不在 02_source_registry.yaml：%s" % unknown)

    entries = []
    for name in targets:
        s = reg[name]
        url = s.get("url") or ""
        rec = OrderedDict(
            [
                ("name", name),
                ("label", s.get("label", "")),
                ("url", url),
                ("registry_status", s.get("status", "unknown")),
                ("registry_verified_at", "2026-10-27"),
                ("registry_note", (s.get("note") or "").strip()[:300]),
            ]
        )
        if not url:
            rec["frontend_reachable"] = False
            rec["error"] = "no_url_in_registry"
            rec["prediction_available"] = None
            rec["status_verdict"] = "registry_status_unchanged"
            entries.append(rec)
            continue
        ok, code, final, nbytes, title, err = _get(url, timeout)
        rec.update(
            OrderedDict(
                [
                    ("http_status", code),
                    ("final_url", final),
                    ("nbytes", nbytes),
                    ("title", title),
                    ("error", err),
                    ("frontend_reachable", bool(ok)),
                    ("prediction_available", None),  # 绝不由 GET 推断
                    ("prediction_probe", "not_probed (本探针不提交预测作业)"),
                    ("status_verdict", "registry_status_unchanged"),
                    (
                        "caveat",
                        (
                            "首页/表单 200 不代表预测后端可用：pkCSM 2026-11-04 "
                            "实测前端全 200 而 POST 预测 8/8 返回 500"
                        ),
                    ),
                ]
            )
        )
        entries.append(rec)

    report = OrderedDict(
        [
            ("generated_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ("generator", "adt/source_health.py"),
            ("method", "HTTP GET only; no prediction job submitted"),
            ("timeout_seconds", timeout),
            (
                "registry",
                (
                    os.path.relpath(registry_path or DEFAULT_REGISTRY, ROOT)
                    if (registry_path or DEFAULT_REGISTRY).startswith(ROOT)
                    else (registry_path or DEFAULT_REGISTRY)
                ),
            ),
            ("n_probed", len(entries)),
            ("n_frontend_ok", sum(1 for e in entries if e.get("frontend_reachable"))),
            ("n_prediction_confirmed", 0),
            (
                "policy",
                OrderedDict(
                    [
                        ("auto_update_registry", False),
                        ("prediction_available_from_get", False),
                        ("submits_jobs", False),
                        (
                            "next_step",
                            (
                                "要升级某源状态，须人工在浏览器/API 跑通一次真实预测、"
                                "记录结果页第一手证据，再手改 02_source_registry.yaml"
                            ),
                        ),
                    ]
                ),
            ),
            ("sources", entries),
        ]
    )
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        p = os.path.join(outdir, "source_health_latest.json")
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False, indent=2))
        report["_report_path"] = p
    return report
