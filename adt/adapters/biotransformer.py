# -*- coding: utf-8 -*-
"""BioTransformer 3.0 适配器（REST API，2026-10-27 实测可用）。

实测到的真实流程（官方 help?page=programmatic_access 有文档，但两处与文档不符）：
  1) POST https://biotransformer.ca/queries.json
     头必须同时带 Content-Type / Accept = application/json；
     **用 requests 的 json= 参数会返回 406 Not Acceptable**，必须用 data=json.dumps(...)
     并且 allow_redirects=False，否则跟随 302 会丢掉 query id。
  2) 成功判据不是 200，而是 **302 + Location: /queries/{id}/status**
  3) GET https://biotransformer.ca/queries/{id}.json  -> status=="Done" 时才可取结果
     返回结构：predictions[0].biotransformations[] 每项含
     biosystem / reaction_type / metabolic_enzymes[] / substrates[] / products[]
  4) 限流：**2 次 POST/分钟**（官方文档明示），所以 min_interval_s 设 31 s

本化学类的实测覆盖情况（重要，不是"0 就是没代谢"）：
  对乙酰氨基酚 6 个产物、苯酚 2 个、甲苯 3 个  ← 规则正常
  咖啡酸（邻苯二酚）**0 个**、真 M（糖苷）**0 个**、对香豆酸 2 个但产物化学不合理
  （"2-O-Acylation of 1-monoacylglycerol" 产出咖啡酸）
  => 该源的 CYP450 规则对本化学类 **没有覆盖**，0 必须记为 out_of_domain 而不是 0 代谢。
"""

import io
import json
import os
import time

import requests

from .base import Adapter, AdapterResult
from .. import schema

BASE = "https://biotransformer.ca"
OPTIONS = [
    "CYP450",
    "EC-BASED",
    "PHASEII",
    "HGUT",
    "ENVMICRO",
    "ALLHUMAN",
    "SUPERBIO",
    "MULTIBIO",
    "ABIOTICBIO",
]

HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


class BioTransformerAdapter(Adapter):
    name = "biotransformer"
    version = "3.0"
    status = "ok"
    min_interval_s = 31.0
    max_retries = 2

    def __init__(
        self, registry_entry=None, verbose=True, options=None, steps=1, poll_timeout=240
    ):
        Adapter.__init__(self, registry_entry, verbose)
        self.options = options or ["CYP450"]
        self.steps = steps
        self.poll_timeout = poll_timeout
        self._cache = {}
        self.controls_csv = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "assets",
            "controls",
            "controls.csv",
        )

    # ---------------- 低层 ----------------
    def preflight(self, timeout=8):
        """源可达性预检（2026-11-19 面板实跑补）。

        实测：biotransformer.ca 在部分网络下**直接不可达**（curl 返回 000）。
        旧行为没有预检，于是每个分子都要走 `timeout=90` 的 POST + 2 次重试 +
        31s 限流，2 个分子就超过 180s，用户看到的是"卡死"而不是"源不通"。
        预检只发一次短超时 GET：不通就立刻返回 False，由调用方给明确报错。
        """
        try:
            r = requests.get(BASE, timeout=timeout, allow_redirects=False)
            return r.status_code < 500
        except Exception as exc:
            self.log("预检失败（%s）：%s" % (BASE, type(exc).__name__))
            return False

    def submit(self, compound_id, smiles, option, steps=None):
        self.throttle()  # 限流放在真正发请求的地方（control 也走 submit）
        payload = {
            "biotransformer_option": option,
            "number_of_steps": steps or self.steps,
            "query_input": "%s\t%s" % (compound_id, smiles),
            "task_type": "PREDICTION",
        }
        r = requests.post(
            BASE + "/queries.json",
            data=json.dumps(payload),
            headers=HEADERS,
            timeout=90,
            allow_redirects=False,
        )
        loc = r.headers.get("Location", "")
        if r.status_code != 302 or "/queries/" not in loc:
            raise RuntimeError(
                "submit 失败: HTTP %s / %s" % (r.status_code, r.text[:160])
            )
        return loc.split("/queries/")[1].split("/")[0]

    def poll(self, qid):
        t0 = time.time()
        while time.time() - t0 < self.poll_timeout:
            time.sleep(6)
            try:
                d = requests.get(
                    "%s/queries/%s.json" % (BASE, qid),
                    headers={"Accept": "application/json"},
                    timeout=60,
                ).json()
            except Exception:
                continue
            if d.get("status") == "Done":
                return d
        raise RuntimeError("轮询超时（query %s 未进入 Done）" % qid)

    def control(self, option="CYP450", controls=("acetaminophen", "phenol")):
        """阳性对照：确认该 option 的规则引擎是活的。结果在进程内缓存。

        B1 跨批锚点（借自外部 skill 的"内标偏移量"）：实测值必须落在
        controls.csv 的 expected 区间内，否则记 batch_drift ——
        同源不同批次的结果不可直接跨批比较。
        """
        key = ("control", option)
        if key in self._cache:
            return self._cache[key]
        smis = {"acetaminophen": "CC(=O)NC1=CC=C(O)C=C1", "phenol": "Oc1ccccc1"}
        out = {}
        drift = []
        for c in controls:
            qid = self.submit("CTRL_" + c, smis[c], option)
            d = self.poll(qid)
            v = d["number_of_unique_metabolites"]
            out[c] = v
            lo, hi = self._expected(c, option)
            if lo is not None and not (lo <= v <= hi):
                drift.append("%s=%s 不在期望区间 [%s, %s]" % (c, v, lo, hi))
        self._cache[key] = out
        self._cache[("control_drift", option)] = drift
        self.log(
            "阳性对照 %s: %s%s"
            % (option, out, ("  << BATCH_DRIFT: " + "; ".join(drift)) if drift else "")
        )
        return out

    def pre_batch(self, compounds, chemical_class="", **kw):
        """B1 协议落实（C56）：**每批开跑前**对每个 option 强制跑对照并比对区间。

        与 v2.1 的区别：不再等"某分子 0 产物"才惰性触发。对照结果在进程内缓存，
        同一 option 只多消耗 2 次 POST（限流 31 s/次），换来"每批都有锚点"。
        """
        qa = []
        for opt in self.options:
            ctrl = self.control(opt)
            for name, observed in ctrl.items():
                lo, hi = self._expected(name, opt)
                in_range = lo is None or (lo <= observed <= hi)
                qa.append(
                    dict(
                        source=self.name,
                        option=opt,
                        control=name,
                        observed=observed,
                        expected_min=lo,
                        expected_max=hi,
                        drift=(
                            ""
                            if in_range
                            else "%s=%s 不在 [%s,%s]" % (name, observed, lo, hi)
                        ),
                    )
                )
        return qa

    def _expected(self, compound_id, option):
        """从 controls.csv 读期望区间；无记录返回 (None, None)。"""
        if not os.path.exists(self.controls_csv):
            return None, None
        import csv as _csv

        with io.open(self.controls_csv, encoding="utf-8-sig") as fh:
            for r in _csv.DictReader(fh):
                if (
                    r.get("compound_id") == compound_id
                    and r.get("source") == self.name
                    and r.get("option") == option
                ):
                    try:
                        return float(r["expected_min"]), float(r["expected_max"])
                    except (KeyError, ValueError):
                        return None, None
        return None, None

    # ---------------- 上层 ----------------
    def run_one(self, compound, chemical_class="", **kw):
        cid, smi = compound["compound_id"], compound["calc_smiles"]
        rows, mets = [], []
        zero_with_coverage = False
        for opt in self.options:
            qid = self.submit(cid, smi, opt)
            d = self.poll(qid)
            pr = d["predictions"][0]
            n = int(pr.get("nr_of_biotransformations") or 0)
            uniq = int(d.get("number_of_unique_metabolites") or 0)
            prov = "%s/queries/%s" % (BASE, qid)

            if uniq == 0:
                ctrl = self.control(opt)
                alive = any(v > 0 for v in ctrl.values())
                flag = "out_of_domain" if alive else "error"
                note = (
                    (
                        "规则引擎活着（对照 %s）但本分子 0 产物 -> 判为规则未覆盖，"
                        "不可读作'无代谢'；observed_count=0" % ctrl
                    )
                    if alive
                    else "对照也为 0，规则引擎不可用；observed_count=0"
                )
                val = ""  # 契约：domain_flag=out_of_domain 不得带数值
            else:
                flag, note = "predicted", "%d 个唯一代谢产物" % uniq
                val = uniq

            rows.append(
                schema.measurement(
                    cid,
                    "metabolite_count_%s" % opt,
                    val,
                    "count",
                    self.name,
                    self.version,
                    flag,
                    "",
                    prov,
                    note,
                )
            )
            rows.append(
                schema.measurement(
                    cid,
                    "biotransformation_count_%s" % opt,
                    (n if flag == "predicted" else ""),
                    "count",
                    self.name,
                    self.version,
                    flag,
                    "",
                    prov,
                    note if flag != "predicted" else "%d 条生化转化" % n,
                )
            )

            for b in pr.get("biotransformations") or []:
                enz = ",".join(b.get("metabolic_enzymes") or [])
                for p in b.get("products") or []:
                    mets.append(
                        dict(
                            compound_id=cid,
                            metabolite_smiles=p.get("smiles", ""),
                            metabolite_inchikey=p.get("inchikey", ""),
                            name=p.get("title") or "",
                            reaction_type=b.get("reaction_type", ""),
                            enzymes=enz,
                            biosystem=b.get("biosystem", ""),
                            source=self.name,
                            provenance_url=prov,
                        )
                    )
        return AdapterResult(
            rows, mets, meta=dict(options=self.options, steps=self.steps)
        )
