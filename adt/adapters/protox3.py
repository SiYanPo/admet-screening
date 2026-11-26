# -*- coding: utf-8 -*-
"""ProTox-III 适配器（tox.charite.de，网页表单 + JSON 端点，**逐分子**）。

v2.2 收编（评估报告 P1-7）：此前只有项目级脚本 w2_protox.py。

实测调用链（2026-10-27）：
  1) GET  index.php?site=compound_input             （取 PHPSESSID）
  2) POST index.php?site=compound_search_similarity  （**字段 smilesString 要填 molblock 文本**）
     -> 页面含 LD50 / 毒性类别 / 相似度 / 准确率 + var server_id='...'
  3) POST src/run_models.php  data={models, sdfile:"empty", mol:molblock, id:server_id}
     -> **直接返回 JSON**：{"dili":{"Prediction":"0.0","Probability":"0.973"}, ...}

三个必须记住的语义（registry 已登记，这里再写一遍防止误读）：
  * **Probability 是该预测类别的置信度，不是阳性概率**（反例：dili_pred=0 而 prob=0.975）
    —— 所以入长表的是 `Prediction`（类别 0/1），Probability 只写进 note。
  * **同会话连提 8 个分子后服务端不再返回 server_id/LD50**（会话级限流）
    —— 本适配器**每分子新建 Session** + 间隔 3 s。
  * 无实测近邻时 LD50 一律 5000 mg/kg / class 5（近邻也是 class 5 的默认值），
    不具备区分力 —— 用 neighbor_class_min / similarity 判定并写进 note。
"""

import re
import time

import requests

from .base import Adapter, AdapterResult
from .. import schema

BASE = "https://tox.charite.de/protox3"
RUN_MODELS = BASE + "/src/run_models.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"

# 与 ADMET 结论相关的 18 个端点（45 个里挑，含 6 个 CYP）
ENDPOINTS = [
    "dili",
    "neuro",
    "nephro",
    "respi",
    "cardio",
    "carcino",
    "immuno",
    "mutagen",
    "cyto",
    "bbb",
    "eco",
    "clinical",
    "CYP1A2",
    "CYP2C19",
    "CYP2C9",
    "CYP2D6",
    "CYP2E1",
    "CYP3A4",
]

LD50_RE = re.compile(r"Predicted LD50:\s*([\d.]+)\s*mg/kg", re.I)
CLASS_RE = re.compile(r"Predicted Toxicity Class:\s*(\d)", re.I)
SIM_RE = re.compile(r"Average similarity:\s*([\d.]+)\s*%", re.I)
ACC_RE = re.compile(r"Prediction accuracy:\s*([\d.]+)\s*%", re.I)
SID_RE = re.compile(r"server_id\s*=\s*['\"](\d+)['\"]")
NB_CLS_MIN_RE = re.compile(r"tox class,\s*min</td>\s*<td>(\d)</td>", re.I)


def molblock(smiles):
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError("invalid SMILES: %r" % smiles)
    AllChem.Compute2DCoords(m)
    return Chem.MolToMolBlock(m)


class ProtoxAdapter(Adapter):
    name = "protox3"
    version = "III"
    status = "ok"
    min_interval_s = 3.0  # 实测会话级限流：每分子新会话 + 3 s
    max_retries = 2

    def __init__(self, registry_entry=None, verbose=True, endpoints=None, raw_dir=""):
        Adapter.__init__(self, registry_entry, verbose)
        self.endpoints = endpoints or ENDPOINTS
        self.raw_dir = raw_dir

    def run_one(self, compound, chemical_class="", **kw):
        cid, smi = compound["compound_id"], compound["calc_smiles"]
        mb = molblock(smi)
        self.throttle()
        s = requests.Session()  # 每分子独立会话（会话级限流）
        s.headers["User-Agent"] = UA
        r0 = s.get(BASE + "/index.php?site=compound_input", timeout=60)
        if r0.status_code != 200:
            raise RuntimeError("输入页 HTTP %s" % r0.status_code)
        r1 = s.post(
            BASE + "/index.php?site=compound_search_similarity",
            data={"smilesString": mb, "defaultName": cid},
            headers={"Referer": BASE + "/index.php?site=compound_input"},
            timeout=600,
        )
        if r1.status_code != 200:
            raise RuntimeError("相似性提交 HTTP %s" % r1.status_code)

        ld50 = LD50_RE.search(r1.text)
        tclass = CLASS_RE.search(r1.text)
        sim = SIM_RE.search(r1.text)
        acc = ACC_RE.search(r1.text)
        nbmin = NB_CLS_MIN_RE.search(r1.text)
        sid = SID_RE.search(r1.text)

        rel = "MODERATE"
        if nbmin and nbmin.group(1) == "5" and tclass and tclass.group(1) == "5":
            rel = "LOW_neighbors_unclassified"
        elif sim and float(sim.group(1)) < 50:
            rel = "LOW_low_similarity"

        rows = []
        if ld50:
            rows.append(
                schema.measurement(
                    cid,
                    "protox_ld50",
                    float(ld50.group(1)),
                    "mg/kg",
                    self.name,
                    self.version,
                    "predicted",
                    "",
                    BASE + "/index.php",
                    "tox_class=%s; 近邻相似度=%s%%; 近邻最低类别=%s; 可信度=%s"
                    "（无实测近邻时 LD50 恒为 5000/class 5，无区分力）"
                    % (
                        tclass.group(1) if tclass else "?",
                        sim.group(1) if sim else "?",
                        nbmin.group(1) if nbmin else "?",
                        rel,
                    ),
                )
            )
        if not sid:
            rows.append(
                schema.measurement(
                    cid,
                    "protox_status",
                    "",
                    "status",
                    self.name,
                    self.version,
                    "error",
                    "",
                    BASE + "/index.php",
                    "未返回 server_id（可能是会话级限流；LD50 仍已解析）",
                )
            )
            return AdapterResult(rows, [])

        r2 = s.post(
            RUN_MODELS,
            data={
                "models": " ".join(self.endpoints),
                "sdfile": "empty",
                "mol": mb,
                "id": sid.group(1),
            },
            headers={
                "Referer": BASE + "/index.php?site=compound_input",
                "Origin": "https://tox.charite.de",
            },
            timeout=600,
        )
        if r2.status_code != 200:
            rows.append(
                schema.measurement(
                    cid,
                    "protox_status",
                    "",
                    "status",
                    self.name,
                    self.version,
                    "error",
                    "",
                    RUN_MODELS,
                    "run_models HTTP %s" % r2.status_code,
                )
            )
            return AdapterResult(rows, [])
        try:
            payload = r2.json()
        except Exception:
            rows.append(
                schema.measurement(
                    cid,
                    "protox_status",
                    "",
                    "status",
                    self.name,
                    self.version,
                    "error",
                    "",
                    RUN_MODELS,
                    "run_models 返回非 JSON",
                )
            )
            return AdapterResult(rows, [])

        from .. import endpoints as _ep

        cmap, _rmap = _ep.load_source_map(self.name)
        n_done = 0
        for key, item in payload.items():
            pred = (item or {}).get("Prediction", "")
            prob = (item or {}).get("Probability", "")
            if pred in ("", None):
                continue
            n_done += 1
            canon = cmap.get(key)
            if canon is None:
                continue  # 未登记语义的端点（cardio/cyto/...）不入长表
            try:
                v = int(float(pred))
            except (TypeError, ValueError):
                continue
            rows.append(
                schema.measurement(
                    cid,
                    canon,
                    v,
                    "class",
                    self.name,
                    self.version,
                    "predicted",
                    "",
                    RUN_MODELS,
                    "ProTox 端点 %s：Prediction=%s（类别标签）；Probability=%s 是"
                    "**该类别置信度**，不是阳性概率" % (key, pred, prob),
                )
            )
        return AdapterResult(
            rows, [], meta=dict(n_endpoints_done=n_done, ld50_reliability=rel)
        )
