# -*- coding: utf-8 -*-
"""工作包 J：把案例库升级为"带精确率/召回率的失效模式检测系统"。

外部评审意见（2026-10-29）：
  "badcase 在论文中不是产品修复日志，而是方法学发现的证据。每一条应被提炼为
   一个一般性的失效模式，并说明框架的哪个设计选择是对该失效模式的结构性预防。"
  更进一步，每个失效模式需要**在基准数据上的发生频率估计**，以及检测的
  precision / recall——这样案例库才是"可靠性工程"产出，而不是"我们踩过坑"。

本模块把 C50/C74/C78/C80/C82/U6/C16 提炼成 7 个可自动检测的不变量违例：
  unit_isomerism        同一端点混用 class 0/1 与 probability（C78）
  domain_block_unwired  registry 登记了域外端点，但数据仍是 predicted（C82）
  version_drift         同一 (cid, ep, source) 出现多个 source_version（C74）
  phys_range_violation  数值越出端点物理边界（C80）
  pseudo_consensus      整数独立组 >=2 但加权有效票 <1.5（C16/C35）
  single_group_verdict  PASS/FAIL 的独立组数 < 规则要求（U6 门控绕过）
  silent_empty_source   预期源在本批 0 行（C50 静默空转）

诚实的度量边界：precision/recall 需要**独立的标签**（哪些行确实是失效）。
没有标签时只报计数，不伪造指标。
"""

import os

IN_DOMAIN = {"predicted", "measured", "saturated"}
UNIT_PROB = {"probability", "fraction"}
UNIT_CLASS = {"class", "class_0_1", "binary"}


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _unit_kind(u):
    u = (u or "").strip().lower()
    if u in UNIT_PROB:
        return "prob"
    if u in UNIT_CLASS:
        return "class"
    return "other"


def _blocked_set(registry, chemical_class):
    """registry -> {(source, canonical_endpoint): evidence}"""
    if not registry or not chemical_class:
        return {}
    try:
        from .endpoints import canonical_name
    except Exception:  # pragma: no cover

        def canonical_name(x):
            return (x or "").strip().lower()

    out = {}
    for src in registry.get("sources") or []:
        name = src.get("name", "")
        for item in (src.get("blocked_endpoints_in_class") or {}).get(
            chemical_class
        ) or []:
            ep = (
                canonical_name(item.get("endpoint", ""))
                or str(item.get("endpoint", "")).lower()
            )
            out[(name, ep)] = item.get("evidence", "")
    classes = (registry.get("chemical_classes") or {}).get(chemical_class) or {}
    for item in classes.get("blocked_endpoints") or []:
        raw = str(item)
        if ":" in raw:
            s, e = raw.split(":", 1)
        elif "." in raw:
            s, e = raw.split(".", 1)
        else:
            continue
        out[(s.strip(), canonical_name(e) or e.strip().lower())] = (
            "chemical_classes 登记"
        )
    return out


def detect(
    measurements,
    reliability=None,
    rules=None,
    registry=None,
    chemical_class="",
    groups=None,
    expect_sources=None,
):
    """返回命中列表；每条 dict(mode, compound_id, endpoint, source, detail)。"""
    rules = rules or {}
    hits = []
    rows = measurements or []

    # 1) unit_isomerism
    by_key = {}
    for r in rows:
        if r.get("domain_flag") not in IN_DOMAIN:
            continue
        by_key.setdefault((r.get("compound_id", ""), r.get("endpoint", "")), []).append(
            r
        )
    for (cid, ep), rs in by_key.items():
        kinds = {_unit_kind(r.get("unit")) for r in rs} - {"other"}
        if "prob" in kinds and "class" in kinds:
            hits.append(
                dict(
                    mode="unit_isomerism",
                    compound_id=cid,
                    endpoint=ep,
                    source=";".join(sorted({r.get("source", "") for r in rs})),
                    detail="同一端点混用 class 0/1 与 probability；直接取中位数=假 PASS",
                )
            )

    # 2) domain_block_unwired
    blocked = _blocked_set(registry, chemical_class)
    for r in rows:
        key = (r.get("source", ""), (r.get("endpoint", "") or "").strip().lower())
        if key in blocked and r.get("domain_flag") in IN_DOMAIN:
            hits.append(
                dict(
                    mode="domain_block_unwired",
                    compound_id=r.get("compound_id", ""),
                    endpoint=r.get("endpoint", ""),
                    source=r.get("source", ""),
                    detail="registry 已登记域外（%s），但数据仍为 %s"
                    % (blocked[key][:40], r.get("domain_flag")),
                )
            )

    # 3) version_drift
    vers = {}
    for r in rows:
        if not r.get("source_version"):
            continue
        key = (r.get("compound_id", ""), r.get("endpoint", ""), r.get("source", ""))
        vers.setdefault(key, set()).add(r["source_version"])
    for (cid, ep, src), vs in vers.items():
        if len(vs) > 1:
            hits.append(
                dict(
                    mode="version_drift",
                    compound_id=cid,
                    endpoint=ep,
                    source=src,
                    detail="多版本共存：%s" % sorted(vs),
                )
            )

    # 4) phys_range_violation
    for r in rows:
        v = _f(r.get("value"))
        if v is None or r.get("domain_flag") not in IN_DOMAIN:
            continue
        try:
            from .reliability import _match_rule

            rule = _match_rule(r.get("endpoint", ""), rules) or {}
        except Exception:  # pragma: no cover
            rule = rules.get(r.get("endpoint", "")) or {}
        rng = rule.get("phys_range")
        if rng and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
            if not (lo <= v <= hi):
                hits.append(
                    dict(
                        mode="phys_range_violation",
                        compound_id=r.get("compound_id", ""),
                        endpoint=r.get("endpoint", ""),
                        source=r.get("source", ""),
                        detail="%.4g 越出 [%g, %g]" % (v, lo, hi),
                    )
                )

    # 5) pseudo_consensus（需要 groups；用加权有效票）
    if groups:
        from .independence import effective_votes

        ev = effective_votes(rows, groups)
        for r in ev:
            if r.get("pseudo_consensus") == "Y":
                hits.append(
                    dict(
                        mode="pseudo_consensus",
                        compound_id=r["compound_id"],
                        endpoint=r["endpoint"],
                        source="",
                        detail="整数 %d 组但有效票 %.2f < 1.5"
                        % (r["n_indep_groups"], r["effective_votes"]),
                    )
                )

    # 6) single_group_verdict（门控绕过）
    for rec in reliability or []:
        if rec.get("verdict") not in ("PASS", "FAIL"):
            continue
        ep = rec.get("endpoint", "")
        try:
            from .reliability import _match_rule

            need = int((_match_rule(ep, rules) or {}).get("require_sources", 2))
        except Exception:  # pragma: no cover
            need = int((rules.get(ep) or {}).get("require_sources", 2))
        n_indep = int(rec.get("n_indep_groups") or 0)
        if n_indep < max(1, need):
            hits.append(
                dict(
                    mode="single_group_verdict",
                    compound_id=rec.get("compound_id", ""),
                    endpoint=ep,
                    source="",
                    detail="verdict=%s 但独立组 %d < 要求 %d（U6 同类）"
                    % (rec["verdict"], n_indep, max(1, need)),
                )
            )

    # 7) silent_empty_source
    if expect_sources:
        present = {r.get("source", "") for r in rows}
        for s in expect_sources:
            if s not in present:
                hits.append(
                    dict(
                        mode="silent_empty_source",
                        compound_id="*",
                        endpoint="*",
                        source=s,
                        detail="预期源在本批 0 行（静默空转风险）",
                    )
                )
    return hits


def evaluate_detectors(hits, labels=None):
    """有标签时算每模式 precision/recall；无标签返回 counts only。

    labels: list[dict(mode, compound_id, endpoint, is_failure)]。
    """
    counts = {}
    for h in hits:
        counts[h["mode"]] = counts.get(h["mode"], 0) + 1
    if not labels:
        return dict(
            per_mode={
                m: dict(n_hits=n, precision=None, recall=None)
                for m, n in counts.items()
            },
            label_source="none",
        )
    truth = {
        (l["mode"], l["compound_id"], l["endpoint"])
        for l in labels
        if int(l.get("is_failure", 0)) == 1
    }
    pred = {(h["mode"], h["compound_id"], h["endpoint"]) for h in hits}
    modes = sorted(set(m for m, _, _ in truth) | set(m for m, _, _ in pred))
    per = {}
    for m in modes:
        tp = len({p for p in pred if p[0] == m} & {t for t in truth if t[0] == m})
        fp = len({p for p in pred if p[0] == m} - {t for t in truth if t[0] == m})
        fn = len({t for t in truth if t[0] == m} - {p for p in pred if p[0] == m})
        per[m] = dict(
            n_hits=counts.get(m, 0),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=round(tp / (tp + fp), 4) if (tp + fp) else None,
            recall=round(tp / (tp + fn), 4) if (tp + fn) else None,
        )
    return dict(per_mode=per, label_source="labels")


def write(outdir, hits, metrics):
    import csv
    import io

    p1 = os.path.join(outdir, "failure_modes.csv")
    cols = ["mode", "compound_id", "endpoint", "source", "detail"]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(hits)
    p2 = os.path.join(outdir, "failure_modes_metrics.csv")
    cols2 = ["mode", "n_hits", "tp", "fp", "fn", "precision", "recall", "label_source"]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        for m, v in sorted(metrics.get("per_mode", {}).items()):
            row = dict(mode=m, label_source=metrics.get("label_source", ""))
            row.update(v)
            w.writerow(row)
    return p1, p2
