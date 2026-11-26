# -*- coding: utf-8 -*-
"""ChEMBL 适配器 —— 给所有预测一个"真值参照"（不是预测源）。

它回答的问题不是"这个分子活性多少"，而是：
  1. 我的分子在 ChEMBL 里有没有邻居（**最大 Tanimoto**）——这本身就是适用域指标；
  2. 邻居们的实测 ADMET 值分布（p10/p50/p90）——把预测值放进去就知道分位。

**v2.2 修复（C52，评估报告 P1-3）**：v2.1 及更早版本的参照层有三处科学错误，
会让"真值参照"本身失真（虽因 role=reference 不污染裁决，但污染了校准依据）：
  a) hERG 桶把 nM 与 uM **不换算直接合并**算分位（差 1000 倍）；
  b) ppb 桶把 "% bound"（越大结合越强）与 "fu/Fraction unbound"（越大越游离）
     **方向相反**的物理量合并取分位——同桶内数值互为补数，分位数无意义；
  c) clearance 桶混入 "Half Life"——半衰期不是清除率，量纲不同。
修复策略：**先归一（单位换算 + 方向统一），再按 (物理量, 规范单位) 分组，
每组单独算分位**；组内样本 < min_neighbors_for_ref 判 out_of_domain。
参照端点全部是 role=reference（只报告、不裁决）。

实测到的接口（2026-10-27）：
  * 相似性：`GET /chembl/api/data/similarity/{smiles}/{threshold}.json?limit=N`
    —— 返回 {molecules:[...], page_meta:{total_count}}。
    **注意**：老的 `molecule.json?molecule_structures__canonical_smiles__similarity=...`
    会 500，不要用。
  * 活性：`GET /activity.json?molecule_chembl_id__in=A,B,C&limit=N` 可用（逗号分隔）。
  * hERG 单独一次：`target_chembl_id=CHEMBL240`（hERG 靶点）。
"""

import re
import time

import requests

from .base import Adapter, AdapterResult
from .. import schema

BASE = "https://www.ebi.ac.uk/chembl/api/data"
H = {"Accept": "application/json"}
HERG_TARGET = "CHEMBL240"

# standard_type -> 物理量（C52：clearance 与 half_life 必须分开）
QUANTITY_TYPES = {
    "solubility": {"Solubility", "Solubility (ug/mL)"},
    "logd": {"LogD"},
    "clearance": {"Clearance", "Intrinsic Clearance"},
    "half_life": {"Half Life"},
    "ppb_fu": {"Protein binding", "% bound", "fu", "Fraction unbound"},
    "caco2": {"Permeability"},
}

# 结合类活性的 standard_type（只在 hERG 靶点命中时进入 herg 桶）
HERG_TYPES = {"IC50", "Ki", "Kd"}

# 到 µM 的换算因子
_TO_UM = {"pm": 1e-6, "nm": 1e-3, "um": 1.0, "µm": 1.0, "μm": 1.0, "mm": 1e3, "m": 1e6}
# 半衰期到小时
_TO_H = {
    "s": 1.0 / 3600,
    "sec": 1.0 / 3600,
    "min": 1.0 / 60,
    "h": 1.0,
    "hr": 1.0,
    "hour": 1.0,
    "d": 24.0,
    "day": 24.0,
}
# 溶解度到 µg/mL（mg/L == µg/mL）
_TO_UG_ML = {
    "ug/ml": 1.0,
    "µg/ml": 1.0,
    "μg/ml": 1.0,
    "mg/l": 1.0,
    "mg/ml": 1e3,
    "g/l": 1e3,
    "ng/ml": 1e-3,
}


def _u(unit):
    return (unit or "").strip().lower().replace(" ", "")


def _slug(unit):
    return re.sub(r"[^a-z0-9]+", "", _u(unit)) or "na"


def canon(quantity, value, unit):
    """把一条活性记录归一为 (规范值, 规范单位)。无法安全归一 → None。

    **无法归一就丢弃**，绝不做"凑一个数"的换算——参照层的错误比缺失更危险。
    """
    u = _u(unit)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if quantity == "herg":
        if u in _TO_UM:
            return v * _TO_UM[u], "uM"
        return None
    if quantity == "ppb_fu":
        # 方向统一：一律换成"游离分数 fu ∈ [0,1]"
        if ("%" in u) or u in ("percent", "pct"):
            if not (0.0 <= v <= 100.0):
                return None
            return 1.0 - v / 100.0, "fraction"
        if u in ("", "none", "fraction", "ratio"):
            if 0.0 <= v <= 1.0:
                return v, "fraction"
            if 1.0 < v <= 100.0:  # 以百分数形式给出的 fu
                return v / 100.0, "fraction"
        return None
    if quantity == "clearance":
        # 清除率单位族不可互算（需体重/蛋白含量假设）→ 按单位分组，不跨单位比较
        if u in ("ml/min/kg", "ml/min", "ul/min/mg", "l/h/kg", "ml/h/kg"):
            return v, u
        return None
    if quantity == "half_life":
        if u in _TO_H:
            return v * _TO_H[u], "h"
        return None
    if quantity == "solubility":
        if u in _TO_UG_ML:
            return v * _TO_UG_ML[u], "ug/mL"
        if u in _TO_UM:  # 摩尔浓度：统一到 uM（无 MW 不跨族换算成 µg/mL）
            return v * _TO_UM[u], "uM"
        return None
    if quantity == "logd":
        if u in ("", "none", "log"):
            return v, "log"
        return None
    if quantity == "caco2":
        if "log" in u:
            return v, "log_cm_s"
        if "cm/s" in u:
            return v, "cm/s"
        return None
    return None


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def build_reference_rows(cid, acts, herg_acts, source, version, prov, min_n=3):
    """纯函数：活性记录 -> 参照分位长表行（可离线测试，不触网）。

    C52 的核心：先 canon() 归一，再按 (量, 单位) 分组；只有同组内才取分位。
    """
    groups = {}  # (quantity, unit) -> {"vals": [...], "raw_units": {...}}
    for a in acts:
        st = a.get("standard_type")
        v = a.get("standard_value")
        if not st or v in (None, ""):
            continue
        q = next((k for k, ts in QUANTITY_TYPES.items() if st in ts), None)
        if q is None:
            continue
        c = canon(q, v, a.get("standard_units") or "")
        if c is None:
            continue
        g = groups.setdefault((q, c[1]), dict(vals=[], raw_units={}))
        g["vals"].append(c[0])
        ru = (a.get("standard_units") or "none").strip()
        g["raw_units"][ru] = g["raw_units"].get(ru, 0) + 1

    for a in herg_acts:
        v = a.get("standard_value")
        st = a.get("standard_type")
        if st not in HERG_TYPES or v in (None, ""):
            continue
        c = canon("herg", v, a.get("standard_units") or "")
        if c is None:
            continue
        g = groups.setdefault(("herg", "uM"), dict(vals=[], raw_units={}))
        g["vals"].append(c[0])
        ru = (a.get("standard_units") or "none").strip()
        g["raw_units"][ru] = g["raw_units"].get(ru, 0) + 1

    # 同一物理量有多个单位组时：最大组用基础名，其余组加单位后缀（避免静默覆盖）
    by_q = {}
    for (q, u), g in groups.items():
        by_q.setdefault(q, []).append((u, g))
    dominant = {
        q: max(gs, key=lambda x: len(x[1]["vals"]))[0] for q, gs in by_q.items()
    }

    rows = []
    for (q, u), g in sorted(groups.items()):
        vals = g["vals"]
        base = "chembl_%s" % q
        name = base if (u == dominant[q]) else "%s_%s" % (base, _slug(u))
        raw = ",".join("%s×%d" % (k, n) for k, n in sorted(g["raw_units"].items()))
        ok = len(vals) >= min_n
        note = "%d 条邻居实测；规范单位 %s（原始：%s%s）" % (
            len(vals),
            u,
            raw,
            "；已做单位换算" if len(g["raw_units"]) > 1 else "",
        )
        if not ok:
            note += "；样本 < %d，不足作参照" % min_n
        if u != dominant[q]:
            note += "；该量另有主单位组 %s，本组单列" % dominant[q]
        flag = "predicted" if ok else "out_of_domain"
        for stat, qq in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
            rows.append(
                schema.measurement(
                    cid,
                    "%s_%s" % (name, stat),
                    (round(_pct(vals, qq), 4) if ok else ""),
                    u,
                    source,
                    version,
                    flag,
                    "",
                    prov,
                    note,
                )
            )
    return rows


ADMET_ASSAY_KEYS = (
    "caco",
    "permeab",
    "pampa",
    "mdck",  # 渗透性（三类独立方法）
    "ppb",
    "protein binding",
    "plasma protein",
    "unbound",
    "fraction unbound",  # 蛋白结合
    "microsom",
    "intrinsic clearance",
    "clearance",
    "clint",
    "hepatocyte",
    "half life",
    "half-life",
)  # 代谢稳定


def _count_admet_assays(acts):
    """邻居活性记录里属于 ADMET 实测（渗透/结合/代谢稳定）的条数（C79）。"""
    n = 0
    for a in acts or []:
        st = str(a.get("standard_type") or "").lower()
        if any(k in st for k in ADMET_ASSAY_KEYS):
            n += 1
    return n


class ChEMBLAdapter(Adapter):
    name = "chembl"
    version = "api-2026-10"
    status = "ok"
    min_interval_s = 1.0

    def __init__(
        self,
        registry_entry=None,
        verbose=True,
        threshold=40,
        max_neighbors=40,
        min_neighbors_for_ref=3,
    ):
        Adapter.__init__(self, registry_entry, verbose)
        self.threshold = threshold
        self.max_neighbors = max_neighbors
        self.min_neighbors_for_ref = min_neighbors_for_ref
        self._cache = {}

    # ---------------- 低层 ----------------
    def similar(self, smiles, threshold=None):
        th = threshold or self.threshold
        url = "%s/similarity/%s/%d.json?limit=%d" % (
            BASE,
            requests.utils.quote(smiles, safe=""),
            th,
            self.max_neighbors,
        )
        r = requests.get(url, headers=H, timeout=120)
        if r.status_code != 200:
            raise RuntimeError("similarity HTTP %s: %s" % (r.status_code, r.text[:160]))
        d = r.json()
        return d.get("molecules") or [], int(
            (d.get("page_meta") or {}).get("total_count") or 0
        )

    def activities(self, ids, extra=""):
        if not ids:
            return []
        out = []
        chunk = 25
        for i in range(0, len(ids), chunk):
            part = ",".join(ids[i : i + chunk])
            url = "%s/activity.json?molecule_chembl_id__in=%s&limit=1000%s" % (
                BASE,
                part,
                extra,
            )
            r = requests.get(url, headers=H, timeout=120)
            if r.status_code != 200:
                raise RuntimeError(
                    "activity HTTP %s: %s" % (r.status_code, r.text[:160])
                )
            out.extend(r.json().get("activities") or [])
            time.sleep(0.4)
        return out

    def herg_activities(self, ids):
        return self.activities(ids, "&target_chembl_id=%s" % HERG_TARGET)

    # ---------------- 上层 ----------------
    def run_one(self, compound, chemical_class="", **kw):
        from rdkit import Chem, RDLogger
        from rdkit.Chem import AllChem, DataStructs

        RDLogger.DisableLog("rdApp.*")

        cid, smi = compound["compound_id"], compound["calc_smiles"]
        # ChEMBL 的相似性阈值下限是 40（实测 30 会 400）
        th = max(40, int(self.threshold))
        mols, total = self.similar(smi, th)
        ids = [m["molecule_chembl_id"] for m in mols]
        prov = "%s/similarity/%s/%d.json" % (BASE, smi, th)

        # 本地算最大 Tanimoto（API 不返回分数）：Morgan r=2/2048，与官方 ECFP4 略有差异
        q = Chem.MolFromSmiles(smi)
        qfp = AllChem.GetMorganFingerprintAsBitVect(q, 2, nBits=2048) if q else None
        best, best_id = None, ""
        for m in mols:
            cs = (m.get("molecule_structures") or {}).get("canonical_smiles")
            if not cs or qfp is None:
                continue
            mm = Chem.MolFromSmiles(cs)
            if mm is None:
                continue
            fp = AllChem.GetMorganFingerprintAsBitVect(mm, 2, nBits=2048)
            t = DataStructs.TanimotoSimilarity(qfp, fp)
            if best is None or t > best:
                best, best_id = t, m["molecule_chembl_id"]

        rows = [
            schema.measurement(
                cid,
                "chembl_neighbors_t%d" % th,
                total,
                "count",
                self.name,
                self.version,
                "predicted",
                "",
                prov,
                "ChEMBL 中 Tanimoto>=%d 的邻居总数 %d；仅取前 %d 个做活性统计"
                % (th, total, len(ids)),
            ),
            schema.measurement(
                cid,
                "chembl_max_tanimoto",
                (round(best, 3) if best is not None else ""),
                "similarity",
                self.name,
                self.version,
                ("predicted" if best is not None else "out_of_domain"),
                "",
                prov,
                (
                    ("最近邻 %s，本地 Morgan r2 计算" % best_id)
                    if best is not None
                    else "无邻居；该分子在此阈值下没有同系物真值可参照"
                ),
            ),
        ]
        # 顺带记录严格阈值 70% 下的邻居数（本项目实测真 M 为 0，是适用域的强证据）
        try:
            _, total70 = self.similar(smi, 70)
            rows.append(
                schema.measurement(
                    cid,
                    "chembl_neighbors_t70",
                    total70,
                    "count",
                    self.name,
                    self.version,
                    "predicted",
                    "",
                    prov,
                    "Tanimoto>=70 的邻居数（严格阈值）",
                )
            )
        except Exception as exc:
            self.log("70%% 查询失败（不影响主结果）: %s" % exc)

        if not ids:
            return AdapterResult(rows, [], meta=dict(n_neighbors=0, total=total))

        # C53（实测 2026-10-28）：ChEMBL activity 接口偶发 500（APAP 复现）。
        # **适用域信息（邻居数/最大 Tanimoto）是主产物，参照分位是次产物**——
        # 活性查询失败只能降级，不能把整个分子判失败。
        try:
            acts = self.activities(ids)
            herg = self.herg_activities(ids)
        except Exception as exc:
            self.log("%s 活性查询失败（保留适用域信息，参照分位降级）: %s" % (cid, exc))
            rows.append(
                schema.measurement(
                    cid,
                    "chembl_reference_status",
                    "",
                    "status",
                    self.name,
                    self.version,
                    "error",
                    "",
                    prov,
                    "活性查询失败（%s）；参照分位未取得，适用域指标仍有效"
                    % str(exc)[:120],
                )
            )
            return AdapterResult(
                rows,
                [],
                meta=dict(n_neighbors=len(ids), total=total, reference_status="error"),
            )
        ref = build_reference_rows(
            cid, acts, herg, self.name, self.version, prov, self.min_neighbors_for_ref
        )
        rows.extend(ref)

        # C79（2026-10-29 实测）：**邻居多 ≠ 有 ADMET 实测**。肉桂酰糖苷类 14 个分子
        # 各有 180–340 条邻居活性记录，但 ADMET 相关（Caco-2/蛋白结合/微粒体清除）
        # **合计 0 条**——全是 GI50/IC50/细胞毒。若不显式统计，很容易误以为
        # "ChEMBL 能给三项湿实验替代补第二组"。
        n_admet = _count_admet_assays(acts)
        rows.append(
            schema.measurement(
                cid,
                "chembl_admet_assay_count",
                n_admet,
                "count",
                self.name,
                self.version,
                "predicted",
                "",
                prov,
                "邻居中 ADMET 类实测记录数（Caco-2/蛋白结合/微粒体清除）；"
                "0 表示本类无法提供实验第二组",
            )
        )
        if n_admet == 0:
            self.log(
                "%s：邻居 %d 个、活性 %d 条，但 **ADMET 实测 0 条**"
                "（无法作为 Caco-2/PPB/CLint 的实验第二组）"
                % (cid, len(ids), len(acts))
            )
        return AdapterResult(
            rows,
            [],
            meta=dict(
                n_neighbors=len(ids),
                total=total,
                n_admet_assays=n_admet,
                reference_endpoints=len({r["endpoint"] for r in ref}),
            ),
        )
