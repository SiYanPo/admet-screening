# -*- coding: utf-8 -*-
"""ADMET-AI 适配器（admet.ai.greenstonebio.com，免登录，**批量一次提交**）。

v2.2 收编（评估报告 P1-7）：此前只有项目级脚本 w3_admetai_submit.py，
skill 本体跑不通全流程。现按 Adapter 基类内置。

实测接口（2026-10-27）：
  1) POST /  multipart：input-type=text、text-smiles=换行分隔 SMILES
  2) GET  /download_predictions（**同一 Session**）-> CSV（41 端点 + DrugBank 百分位）
  3) 结果 CSV 只有 smiles 列、没有分子 ID —— 必须用 canonical SMILES 对齐，
     **绝不能按行序**（实测 ADMETlab 侧 A/L 的 raw_smiles 前缀相同，行序对齐必错）

列 -> 规范端点的映射在 references/endpoint_aliases.yaml 显式登记；
未登记的列**不自动入长表**（单位族不同：AqSolDB 是 log mol/L、Clearance 是
mL/min/kg、Half_Life 是 h），只计入 meta["unmapped_columns"] 并落列审计文件。
"""

import csv
import io
import os
import sys

import requests

from .base import Adapter, AdapterResult
from .. import endpoints, schema

BASE = "https://admet.ai.greenstonebio.com"

# 非概率端点的**显式转换**（v2.3.3）：源给的物理量与规范端点不同量时必须在此换算，
# 不允许"值直接塞进去 + 单位随手写"（C72 的根因）。
#   列名 -> (规范端点, 值变换, 说明)
TRANSFORMS = {
    # Caco2_Wang 是 log10(Papp, cm/s)；规则阈值已改为 log 单位，值原样透传
    "Caco2_Wang": (
        lambda v: v,
        "log10(Papp) 原样透传；规则 caco2_papp_ab 用 log10(cm/s) 阈值",
    ),
    # PPBR_AZ 是 % bound；规范端点 ppb_fu 是 fu(%)，方向相反 → 必须换算
    "PPBR_AZ": (
        lambda v: round(100.0 - v, 4),
        "PPBR_AZ 是 % bound，已换算为 fu% = 100 - PPBR（方向相反，不能直接并表）",
    ),
}
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AdmetAIAdapter(Adapter):
    name = "admet_ai"
    version = "2.0"
    status = "ok"
    min_interval_s = 1.0
    max_retries = 1

    def __init__(
        self,
        registry_entry=None,
        verbose=True,
        raw_dir="",
        local=False,
        local_python="",
    ):
        Adapter.__init__(self, registry_entry, verbose)
        self.raw_dir = raw_dir
        # v2.3.4：本地离线模式（admet-ai PyPI 包 + Chemprop 权重）。
        # **本地版与网页服务不是同一套权重**：分类端点（DILI/hERG/SR-MMP）几乎一致，
        # 但回归端点系统性偏移（实测 14 分子：Caco2_Wang 本地 **+0.53 log**、
        # PPBR_AZ 本地 **−3.5%**、CLint 中位 +3.8 但范围 ±6.6）。
        # 因此两种模式的 source_version 必须不同，禁止在同一张表里混用（C74）。
        self.local = local
        self.local_python = local_python
        if local:
            self.version = "2.0.1-local"

    # ---------------- 低层 ----------------
    def fetch(self, smiles_list):
        """一次提交整批，返回 (wide rows, provenance url)。"""
        s = requests.Session()
        s.headers["User-Agent"] = UA
        r0 = s.get(BASE + "/", timeout=60)
        if r0.status_code != 200:
            raise RuntimeError("首页 HTTP %s" % r0.status_code)
        r = s.post(
            BASE + "/",
            data={"input-type": "text", "text-smiles": "\n".join(smiles_list)},
            headers={"Referer": BASE + "/", "Origin": BASE},
            timeout=300,
        )
        if r.status_code != 200:
            raise RuntimeError("提交 HTTP %s：%s" % (r.status_code, r.text[:160]))
        d = s.get(BASE + "/download_predictions", timeout=300)
        if d.status_code != 200 or b"," not in d.content[:2000]:
            raise RuntimeError(
                "下载失败 HTTP %s（%d B）" % (d.status_code, len(d.content))
            )
        if self.raw_dir:
            p = "%s/admet_ai_raw.csv" % self.raw_dir.rstrip("/\\")
            open(p, "wb").write(d.content)
            self.log("原始宽表 -> %s（可直接喂 saturate）" % p)
        text = d.content.decode("utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(text))), BASE + "/download_predictions"

    def fetch_local(self, smiles_list):
        """本地离线推理（无网络）。返回 (wide rows, provenance)。

        需要独立环境装有 admet-ai + chemprop（本项目：pharma-tools/envs/admetai_local）。
        首次运行会下载模型权重（约 100 MB，之后完全离线）。
        """
        import subprocess
        import json as _json
        import tempfile

        py = self.local_python or sys.executable
        script = (
            "import sys, json, pandas as pd\n"
            "from admet_ai import ADMETModel\n"
            "smis=json.load(open(sys.argv[1],encoding='utf-8'))\n"
            "df=ADMETModel().predict(smiles=smis)\n"
            "df.insert(0,'smiles',smis)\n"
            "df.to_json(sys.argv[2],orient='records',force_ascii=False)\n"
        )
        d = tempfile.mkdtemp(prefix="admetlocal_")
        inp = os.path.join(d, "smiles.json")
        outp = os.path.join(d, "pred.json")
        with io.open(inp, "w", encoding="utf-8") as fh:
            _json.dump(list(smiles_list), fh, ensure_ascii=False)
        self.log("本地推理（%s，离线）…" % py)
        r = subprocess.run(
            [py, "-c", script, inp, outp], capture_output=True, text=True, timeout=1800
        )
        if r.returncode != 0 or not os.path.exists(outp):
            raise RuntimeError("本地 admet-ai 失败：%s" % (r.stderr or "")[-400:])
        import pandas as pd  # noqa: F401  （只用于读 json，随默认环境可用）

        with io.open(outp, encoding="utf-8") as fh:
            rows = _json.load(fh)
        if not rows:
            raise RuntimeError("本地推理返回空结果")
        # 记录一次，便于复现
        self.log(
            "本地推理完成：%d 分子 × %d 列（source_version=%s）"
            % (len(rows), len(rows[0]) - 1, self.version)
        )
        return rows, "admet-ai %s (local, offline)" % self.version

    # ---------------- 上层（批量，覆写 run） ----------------
    def run(self, compounds, chemical_class="", **kw):
        res = AdapterResult()
        ok, why = self.is_allowed(chemical_class)
        if not ok:
            self.log("SKIP：化学类 %r 被登记为不可用（%s）" % (chemical_class, why))
            res.meta["skipped"] = why
            return res
        if not compounds:
            return res

        per_batch_qa = self.pre_batch(compounds, chemical_class=chemical_class, **kw)
        if per_batch_qa:
            res.meta["batch_qa"] = per_batch_qa

        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")

        def can(s):
            m = Chem.MolFromSmiles(str(s))
            return Chem.MolToSmiles(m) if m else None

        can2id = {}
        for c in compounds:
            can2id[can(c["calc_smiles"])] = c["compound_id"]

        try:
            fetcher = self.fetch_local if self.local else self.fetch
            rows, prov = fetcher([c["calc_smiles"] for c in compounds])
        except Exception as exc:
            self.log("批量提交失败：%s" % exc)
            res.meta["errors"] = [
                dict(compound_id=c["compound_id"], error=str(exc)) for c in compounds
            ]
            return res

        cmap, rmap = endpoints.load_source_map(self.name)
        # 列名大小写不敏感匹配（源侧表头可能变）
        lower = {k.lower(): k for k in cmap}
        lower_ref = {k.lower(): k for k in rmap}

        unmapped, mapped_cols, unmatched = [], [], []
        for r in rows:
            cid = can2id.get(can(r.get("smiles")))
            if not cid:
                unmatched.append(r.get("smiles"))
                continue
            for raw_col, canon in cmap.items():
                col = raw_col if raw_col in r else lower.get(raw_col.lower())
                if col is None or r.get(col) in (None, ""):
                    continue
                try:
                    v = round(float(r[col]), 4)
                except (TypeError, ValueError):
                    continue
                note = (
                    "列 %s（ADMET-AI 原始预测值；百分位列是该预测在 DrugBank "
                    "参考分布中的位置，不是概率）" % raw_col
                )
                tf = TRANSFORMS.get(raw_col)
                if tf:
                    v = tf[0](v)
                    note = "列 %s：%s" % (raw_col, tf[1])
                unit = endpoints.unit_for(canon) or "probability"
                res.measurements.append(
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
                mapped_cols.append(raw_col)
            for raw_col, canon in rmap.items():
                col = raw_col if raw_col in r else lower_ref.get(raw_col.lower())
                if col is None or r.get(col) in (None, ""):
                    continue
                res.measurements.append(
                    schema.measurement(
                        cid,
                        canon,
                        r[col],
                        "",
                        self.name,
                        self.version,
                        "predicted",
                        "",
                        prov,
                        "参照列 %s" % raw_col,
                    )
                )

        # 列审计：哪些列被丢弃必须在日志和 meta 里可见（静默丢列=静默失效）
        if rows:
            all_cols = [c for c in rows[0] if c.lower() != "smiles"]
            known = set(mapped_cols) | set(rmap)
            unmapped = [
                c
                for c in all_cols
                if c not in known and c.replace("_percentile", "") not in known
            ]
        res.meta.update(
            n_rows=len(rows),
            n_matched=len({m["compound_id"] for m in res.measurements}),
            mapped_columns=sorted(set(mapped_cols)),
            n_unmapped_columns=len(unmapped),
            unmapped_columns=unmapped[:40],
            unmatched_smiles=unmatched[:5],
        )
        self.log(
            "映射列 %s；未映射列 %d 个（见 meta.unmapped_columns）"
            % (sorted(set(mapped_cols)), len(unmapped))
        )
        return res

    def run_one(self, compound, chemical_class="", **kw):
        r = self.run([compound], chemical_class=chemical_class, **kw)
        return AdapterResult(r.measurements, r.metabolites, r.meta)
