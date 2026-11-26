# -*- coding: utf-8 -*-
"""A2 evidence ledger：结论必须可溯源（借自外部 skill 治理层的"契约校验"）。

规则：**结论里声明的证据必须有对应记录；没做的必须显式声明"未执行"；
静默跳级被视为最严重的污染。**

输入 reliability.csv + axis_scores.csv + measurements 长表，输出 ledger.csv：
  level         conclusion / axis_conclusion
  compound_id
  claim         结论原文（verdict/值/置信）
  evidence      支撑它的记录（source|flag|endpoint|value）
  n_records     支撑记录数
  status        supported / unsupported / no_evidence

status != supported 的行就是"说了但拿不出证据"的地方——必须先修证据或改结论。
"""

import csv
import io
import os


def build(reliability_rows, axis_rows, measurement_rows):
    # 索引： (cid, ep) -> measurements
    meas = {}
    for r in measurement_rows:
        meas.setdefault((r["compound_id"], r["endpoint"]), []).append(r)

    out = []
    for r in reliability_rows:
        # C64（v2.2 集成验证发现）：PASSTHRU 是"适用域/真值参照数据"，不是结论。
        # 把它们当 claim 入账会被判 unsupported，制造大量假警报、稀释真正的欠账。
        if r.get("verdict") == "PASSTHRU":
            continue
        cid, ep = r["compound_id"], r["endpoint"]
        ev = meas.get((cid, ep), [])
        evid = (
            "|".join(
                "%s:%s=%s" % (m.get("source"), m.get("domain_flag"), m.get("value"))
                for m in ev
            )
            or "none"
        )
        n_dom = int(r.get("n_in_domain") or 0) + int(r.get("n_measured") or 0)
        status = (
            "supported"
            if (ev and n_dom > 0)
            else ("unsupported" if r["verdict"] != "UNDETERMINED" else "no_evidence")
        )
        claim = "%s = %s%s (conf=%s, indep_groups=%s)" % (
            ep,
            r["verdict"],
            (
                ("=" + str(r["value_used"]))
                if r.get("value_used") not in ("", None)
                else ""
            ),
            r.get("confidence"),
            r.get("n_indep_groups", "?"),
        )
        out.append(
            dict(
                level="conclusion",
                compound_id=cid,
                claim=claim,
                evidence=evid,
                n_records=len(ev),
                status=status,
            )
        )

    for r in axis_rows:
        audited = r.get("endpoints_audited") or ""
        claim = "axis %s geo_mean=%s (cov=%s, flag=%s)" % (
            r["axis"],
            r.get("geo_mean") or "NA",
            r.get("coverage"),
            r.get("flag"),
        )
        evid = (
            ";".join(
                "%s|%s" % (cid, ep)
                for ep in audited.split(";")
                if ep
                for cid in [r["compound_id"]]
            )
            or "none"
        )
        status = "supported" if int(r.get("n_audited") or 0) > 0 else "no_evidence"
        out.append(
            dict(
                level="axis_conclusion",
                compound_id=r["compound_id"],
                claim=claim,
                evidence=evid,
                n_records=int(r.get("n_audited") or 0),
                status=status,
            )
        )
    return out


def write(path, rows):
    cols = ["level", "compound_id", "claim", "evidence", "n_records", "status"]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if r["status"] == "unsupported"]
    return len(rows), len(bad)
