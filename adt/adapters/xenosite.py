# -*- coding: utf-8 -*-
"""XenoSite 适配器 —— 网页手动模式（**没有**可用的免费 API）。

2026-10-27 实测与站点原文：
  * 六个模型页均可访问：`/reactivity`（反应性 SOR）、`/quinone`（成醌）、
    `/ndealk`（N-脱烷基）、`/epoxidation`（环氧化）、`/phase1`（Phase I 五位分类）、
    `/ugt`（UGT 结合）。首页 200，/reactivity 200。
  * 站点 Terms 原文：*"Licenses are available for secure commercial access and
    **access to the programatic API**."* → **程序化接口是收费许可项**，
    网页界面才对学术/非商业免费。
  * 因此本适配器**不模拟网页提交**（那等于绕过许可），只提供两个可核对的动作：
      1) prepare()  生成待提交清单 + 对应网址，人工在网页上跑；
      2) ingest()   把人工读回的数值按固定契约并入长表（domain_flag=manual）。
  * 前端是 Qwik + RDKit-WASM，没有可复用的公开 REST 端点（已试 /api、/apiv2 均为 404）。

为什么仍要做这个适配器：本项目 5 个分子含邻苯二酚、全部含 Michael 受体，
"会不会成醌、哪个原子被 GSH 攻击"是最关键的缺口（G1），而 XenoSite 的
quinone 模型正是唯一直接回答这个问题的公开工具。宁可保留手动通道，也不要缺口。
"""

import csv
import io
import os

from .base import Adapter, AdapterResult
from .. import schema

MODELS = {
    "reactivity": "https://xenosite.org/reactivity",
    "quinone": "https://xenosite.org/quinone",
    "ndealk": "https://xenosite.org/ndealk",
    "epoxidation": "https://xenosite.org/epoxidation",
    "phase1": "https://xenosite.org/phase1",
    "ugt": "https://xenosite.org/ugt",
}

# 人工回填契约（列名固定，缺列直接报错）
INGEST_COLS = [
    "compound_id",
    "model",
    "endpoint",
    "value",
    "unit",
    "atom_index",
    "note",
]
TASK_COLS = ["compound_id", "calc_smiles", "formula", "urls"]


class XenoSiteAdapter(Adapter):
    name = "xenosite"
    version = "web-2026-10"
    status = "license_required"  # API 需许可；网页手动可用
    min_interval_s = 0.0

    def prepare(self, compounds, outdir, models=None):
        models = models or list(MODELS)
        os.makedirs(outdir, exist_ok=True)
        p = os.path.join(outdir, "xenosite_tasks.csv")
        with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=TASK_COLS)
            w.writeheader()
            for c in compounds:
                w.writerow(
                    dict(
                        compound_id=c["compound_id"],
                        calc_smiles=c["calc_smiles"],
                        formula=c.get("formula", ""),
                        urls=" ".join(MODELS[m] for m in models),
                    )
                )
        self.log(
            "待提交清单 -> %s（%d 个分子 × %d 个模型）"
            % (p, len(compounds), len(models))
        )
        # v4.22 修复：此前 prepare 只出任务清单不出回填模板，ingest 永远缺输入
        # （生产者-消费者断链，与 pbpk/cmax 同类）。模板预填 compound_id/model/endpoint，
        # 人工在网页跑完只填 value/unit/atom_index/note；留空 value 即按 out_of_domain 并表。
        ENDPOINT_BY_MODEL = {
            "reactivity": "sor",
            "quinone": "quinone",
            "ndealk": "ndealk",
            "epoxidation": "epoxidation",
            "phase1": "som",
            "ugt": "ugt",
        }
        tp = os.path.join(outdir, "xenosite_readback_template.csv")
        with io.open(tp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=INGEST_COLS)
            w.writeheader()
            for c in compounds:
                for m in models:
                    w.writerow(
                        dict(
                            compound_id=c["compound_id"],
                            model=m,
                            endpoint=ENDPOINT_BY_MODEL.get(m, m),
                            value="",
                            unit="",
                            atom_index="",
                            note="",
                        )
                    )
        self.log(
            "回填模板 -> %s（网页跑完后只填 value；整行留空值将并表为 out_of_domain）"
            % tp
        )
        self.log("网页地址：")
        for m in models:
            self.log("  %-12s %s" % (m, MODELS[m]))
        self.log("读回后在 CS 端的契约：%s" % ",".join(INGEST_COLS))
        return p

    def ingest(self, path):
        """把人工读回的结果并入长表。out_of_domain 行必须 value 留空。"""
        with io.open(path, encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError("空文件: %s" % path)
        missing = [c for c in INGEST_COLS if c not in rows[0]]
        if missing:
            raise ValueError("缺列: %s（契约列=%s）" % (missing, INGEST_COLS))
        out = []
        for r in rows:
            val = (r.get("value") or "").strip()
            flag = "manual" if val else "out_of_domain"
            note = r.get("note", "")
            if r.get("atom_index"):
                note = ("atom_idx=%s; " % r["atom_index"]) + note
            out.append(
                schema.measurement(
                    r["compound_id"],
                    "%s:%s" % (r["model"], r["endpoint"]),
                    val,
                    r.get("unit", ""),
                    self.name,
                    self.version,
                    flag,
                    "",
                    MODELS.get(r["model"], ""),
                    note,
                )
            )
        self.log("ingest %d 行 -> 长表" % len(out))
        return AdapterResult(out, [])

    def run_one(self, compound, chemical_class="", **kw):
        raise NotImplementedError(
            "XenoSite 无免费 API（程序化访问需商业许可）。请用 prepare() 生成清单、"
            "在网页上人工跑，再用 ingest() 回填。见 references/02_source_registry.yaml。"
        )
