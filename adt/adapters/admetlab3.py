# -*- coding: utf-8 -*-
"""ADMETlab 3.0 适配器（admetlab3.scbdd.com，**批量一次提交 + CSV 下载**）。

v2.2 收编（评估报告 P1-7）：此前只有项目级脚本 w1_admetlab_one.py / retry.py。

实测接口（2026-10-26 首轮，2026-10-27 复核）：
  GET  /server/screening                     取 csrfmiddlewaretoken
  POST /server/screeningCal                  method=2, is_example=0, smiles-list=换行分隔
       -> 结果页含 href="/server/result/<result_id>/download/csv"
  GET  /server/result/<id>/download/csv      -> 全端点 CSV（122 列）

限流（实测最痛的一条）：连续提交 429，需指数退避 —— 本适配器内置
[0, 90, 240, 420, 600, 900, 900, 1200] 秒的退避序列（合计约 1 小时上限）。
**新化学类首跑建议先 2 分子探窗口**，不要一上来全量。

行序不可假设：必须用 canonical SMILES 对齐（实测 A 与 L 的 raw_smiles 前缀相同）。
"""

import csv
import io
import re
import time

import requests

from .base import Adapter, AdapterResult
from .. import endpoints, schema

BASE = "https://admetlab3.scbdd.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BACKOFF = [0, 90, 240, 420, 600, 900, 900, 1200]
CSRF_RE = re.compile(r'csrfmiddlewaretoken" value="([^"]+)"')
RID_RE = re.compile(r"/server/result/([0-9a-f]{16,})/download/csv")


# 与 admet_ai 一致的物理量转换（v2.3.3）：单位只能来自规则表，值必须显式换算。
#   caco2 列是 log10(Papp, cm/s) → 原样（规则用 log 阈值）
#   PPB  列是 % bound → 规范端点 ppb_fu 是 fu(%)，方向相反
TRANSFORMS = {
    "caco2": (lambda v: v, "log10(Papp) 原样透传"),
    "PPB": (lambda v: round(100.0 - v, 4), "PPB 是 % bound，已换算为 fu% = 100 - PPB"),
}


class AdmetlabAdapter(Adapter):
    name = "admetlab3"
    version = "3.0"
    status = "ok"
    min_interval_s = 2.0
    max_retries = 0  # 退避由 fetch 内部负责，避免双重重试

    def __init__(
        self,
        registry_entry=None,
        verbose=True,
        raw_dir="",
        backoff=None,
        max_wait_s=3600,
    ):
        Adapter.__init__(self, registry_entry, verbose)
        self.raw_dir = raw_dir
        self.backoff = list(backoff or BACKOFF)
        self.max_wait_s = max_wait_s

    # ---------------- 低层 ----------------
    def _attempt(self, smiles_list):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        r0 = s.get(BASE + "/server/screening", timeout=60)
        m = CSRF_RE.search(r0.text)
        if not m:
            return None, "no-csrf(%s)" % r0.status_code
        r = s.post(
            BASE + "/server/screeningCal",
            data={
                "csrfmiddlewaretoken": m.group(1),
                "method": "2",
                "is_example": "0",
                "smiles-list": "\n".join(smiles_list),
            },
            headers={"Referer": BASE + "/server/screening"},
            timeout=900,
        )
        if r.status_code != 200:
            return None, "post-%s" % r.status_code
        rid = RID_RE.search(r.text)
        if not rid:
            return None, "no-result-id"
        url = "%s/server/result/%s/download/csv" % (BASE, rid.group(1))
        d = s.get(url, timeout=300, headers={"Referer": BASE + "/server/screening"})
        if d.status_code != 200 or len(d.content) < 200:
            return None, "dl-%s" % d.status_code
        if self.raw_dir:
            p = "%s/admetlab3_raw.csv" % self.raw_dir.rstrip("/\\")
            open(p, "wb").write(d.content)
            self.log("原始宽表 -> %s（可直接喂 saturate）" % p)
        text = d.content.decode("utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(text))), "ok"

    def fetch(self, smiles_list):
        """带退避的批量提交。返回 (wide rows, provenance)。"""
        waited = 0
        last = "unknown"
        for i, w in enumerate(self.backoff, 1):
            if w:
                if waited + w > self.max_wait_s:
                    raise RuntimeError(
                        "退避累计将超 %.0f s，放弃（%s）" % (self.max_wait_s, last)
                    )
                self.log("限流退避 %d s（第 %d/%d 次）" % (w, i, len(self.backoff)))
                time.sleep(w)
                waited += w
            rows, st = self._attempt(smiles_list)
            self.log("尝试 %d/%d -> %s" % (i, len(self.backoff), st))
            if rows is not None:
                return rows, BASE + "/server/screening"
            last = st
        raise RuntimeError("ADMETlab 提交全部失败（最后状态 %s）" % last)

    # ---------------- 上层（批量，覆写 run） ----------------
    def to_measurements(self, rows, prov, can2id=None):
        """宽表 -> 长表（**与 fetch 解耦**：可直接复算已落盘的 CSV，不必重新提交）。

        返回 (measurements, meta)。单位来自规则表（endpoints.unit_for），
        非概率量必须经 TRANSFORMS 显式换算（C72）。
        """
        cmap, _rmap = endpoints.load_source_map(self.name)
        lower = {k.lower(): k for k in cmap}
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")

        def can(x):
            m = Chem.MolFromSmiles(str(x))
            return Chem.MolToSmiles(m) if m else None

        out, matched, unmatched = [], set(), []
        for r in rows:
            # 优先 smiles 列（canonical），退而 raw_smiles；行序不可信（A 与 L 前缀相同）
            cid = None
            for key in ("smiles", "raw_smiles"):
                v = r.get(key)
                if v and can2id:
                    cid = can2id.get(can(v))
                    if cid:
                        break
            if not cid:
                unmatched.append((r.get("smiles") or r.get("raw_smiles") or "")[:40])
                continue
            matched.add(cid)
            for raw_col, canon in cmap.items():
                col = raw_col if raw_col in r else lower.get(raw_col.lower())
                if col is None or r.get(col) in (None, ""):
                    continue
                try:
                    v = round(float(r[col]), 4)
                except (TypeError, ValueError):
                    continue
                note = "ADMETlab 列 %s（0-1 概率型输出）" % raw_col
                tf = TRANSFORMS.get(raw_col)
                if tf:
                    v = tf[0](v)
                    note = "ADMETlab 列 %s：%s" % (raw_col, tf[1])
                unit = endpoints.unit_for(canon) or "probability"
                out.append(
                    schema.measurement(
                        cid,
                        canon,
                        v,
                        unit,
                        self.name,
                        self.version,
                        "predicted",
                        "",
                        prov,
                        note,
                    )
                )
        return out, dict(matched=matched, unmatched=unmatched)

    def run(self, compounds, chemical_class="", **kw):
        res = AdapterResult()
        ok, why = self.is_allowed(chemical_class)
        if not ok:
            self.log("SKIP：化学类 %r 被登记为不可用（%s）" % (chemical_class, why))
            res.meta["skipped"] = why
            return res
        if not compounds:
            return res
        qa = self.pre_batch(compounds, chemical_class=chemical_class, **kw)
        if qa:
            res.meta["batch_qa"] = qa

        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")

        def can(s):
            m = Chem.MolFromSmiles(str(s))
            return Chem.MolToSmiles(m) if m else None

        can2id = {can(c["calc_smiles"]): c["compound_id"] for c in compounds}
        try:
            rows, prov = self.fetch([c["calc_smiles"] for c in compounds])
        except Exception as exc:
            self.log("批量提交失败：%s" % exc)
            res.meta["errors"] = [
                dict(compound_id=c["compound_id"], error=str(exc)) for c in compounds
            ]
            return res

        meas, meta = self.to_measurements(rows, prov, can2id=can2id)
        res.measurements.extend(meas)
        matched, unmatched = meta["matched"], meta["unmatched"]
        res.meta.update(
            n_rows=len(rows),
            n_matched=len(matched),
            unmatched=unmatched[:5],
            mapped_columns=sorted(endpoints.load_source_map(self.name)[0]),
        )
        if unmatched:
            self.log(
                "⚠ %d 行未能按 canonical SMILES 对齐（行序不可信）" % len(unmatched)
            )
        return res

    def run_one(self, compound, chemical_class="", **kw):
        r = self.run([compound], chemical_class=chemical_class, **kw)
        return AdapterResult(r.measurements, r.metabolites, r.meta)
