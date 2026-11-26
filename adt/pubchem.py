# -*- coding: utf-8 -*-
"""PubChem 取数与输入层硬化（R26 / A13 / C13 + R27）。

评审 C13 原话："名称→SMILES 输入入口已造成一次立体化学事故，入口未改为 InChIKey
强制锚定。" 评审 F10 补充："名称→结构检索只能作为交互辅助，不能进入已发布流水线。"

而且这不是假设性风险——**同一个坑已经踩过一次**：PubChem 新 API 把
`IsomericSMILES` 弃用，改为 `SMILES`（含立体）/ `ConnectivitySMILES`（非立体）。
旧代码按旧字段回退，静默拿到了非立体版本，Terfenadine/Digoxin 手性丢失。

本模块的三条硬规则：
  1. **字段优先级固定且可断言**：SMILES > IsomericSMILES > CanonicalSMILES，
     `ConnectivitySMILES` **永不**作为首选（它按定义丢立体）。
  2. **取数走快照层**（adt.snapshot）：默认离线重放，字段漂移可通过 mock 回归测试锁定。
  3. **输出 InChIKey 锚点 + 立体声明**；缺立体且分子本应有立体 → 标 `stereo_missing`。
"""

import json

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

FIELD_PRIORITY = ("SMILES", "IsomericSMILES", "CanonicalSMILES")
NEVER_PRIMARY = ("ConnectivitySMILES",)


def pick_smiles(props):
    """从 PubChem property 字典里按优先级取 SMILES；返回 (smiles, field, warning)。"""
    warned = []
    for f in FIELD_PRIORITY:
        v = props.get(f)
        if v:
            if f in NEVER_PRIMARY:
                warned.append("使用非立体字段 %s" % f)
            return v, f, "; ".join(warned)
    for f in NEVER_PRIMARY:
        v = props.get(f)
        if v:
            return v, f, "仅取到非立体字段 %s（立体信息已丢失）" % f
    return None, None, "无 SMILES 字段"


def has_stereo(smiles):
    return any(ch in (smiles or "") for ch in ("@", "/", "\\"))


def could_have_stereo(smiles):
    """分子是否**本应**有立体信息：存在未指定手性中心或双键立体。"""
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return False
    unassigned = Chem.FindMolChiralCenters(
        m, includeUnassigned=True, useLegacyImplementation=False
    )
    return any(c[1] == "?" for c in unassigned) or has_stereo(smiles)


def anchor(smiles):
    """InChIKey（结构锚点）。解析失败返回 None。"""
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return None
    try:
        return Chem.MolToInchiKey(m)
    except Exception:
        return None


def validate_entry(name, smiles, declared_stereo=False, declared_racemic=False):
    """输入准入判定：返回 dict(status, reasons, inchikey, stereo_state)。

    2026-11-19（面板实跑暴露）：旧实现只在报错信息里写"须声明是消旋体还是立体缺失"，
    但**没有任何声明为消旋体的入口**——`declared_stereo=True` 的语义是"我声明这是
    某个特定立体异构体"，于是 SMILES 无立体标记时反而被判失败。结果是所有消旋药
    （华法林、普萘洛尔、酮康唑、红霉素、环孢素…）**永远进不了流水线**，
    提示语承诺的门根本不存在。

    现在的三态语义（互斥，必须显式）：
      * `defined`             —— SMILES 自带立体标记（默认路径，最严）
      * `racemic_declared`    —— 明确声明"这是消旋体/立体未定混合物"，允许进入，
                                 但 `stereo_state` 会一路带下去，报告层必须加措辞上限
      * `undefined`           —— 既无立体标记也没声明 → **仍然拦截**（不猜）
    """
    reasons = []
    if not smiles:
        return {
            "name": name,
            "status": "fail",
            "reasons": ["无 SMILES"],
            "inchikey": None,
            "stereo_state": "missing",
        }
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return {
            "name": name,
            "status": "fail",
            "reasons": ["SMILES 不可解析"],
            "inchikey": None,
            "stereo_state": "unparsable",
        }
    if declared_stereo and declared_racemic:
        reasons.append("立体声明自相矛盾：不能同时声明为单一异构体与消旋体")
    has = has_stereo(smiles)
    if has:
        stereo_state = "defined"
    elif declared_racemic:
        stereo_state = "racemic_declared"
    elif not could_have_stereo(smiles):
        stereo_state = "not_applicable"  # 本来就没有立体中心，不是"未声明"
    else:
        stereo_state = "undefined"
    if not has and could_have_stereo(smiles) and not declared_racemic:
        reasons.append("分子含未指定手性中心/双键：须声明是消旋体还是立体缺失")
    if declared_stereo and not has:
        reasons.append("声明为立体异构体但 SMILES 无立体标记")
    status = (
        "fail"
        if any(k in r for r in reasons for k in ("须声明", "声明为", "矛盾"))
        else "ok"
    )
    return {
        "name": name,
        "status": status,
        "reasons": reasons,
        "inchikey": anchor(smiles),
        "stereo_state": stereo_state,
    }


def fetch_by_name(name, root=None, refresh=False, timeout=30):
    """名称→结构（**仅交互辅助**）：走快照层，重放模式下不联网。"""
    from adt import snapshot as SNAP

    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s/property/"
        "SMILES,IsomericSMILES,ConnectivitySMILES/JSON" % name
    )
    rec, body = SNAP.fetch(
        url,
        source="pubchem",
        key="name:%s" % name,
        schema_version="pug-rest/props-v2",
        root=root,
        timeout=timeout,
        refresh=refresh,
    )
    try:
        props = json.loads(body)["PropertyTable"]["Properties"][0]
    except Exception as exc:
        raise RuntimeError("PubChem 响应解析失败（%s）：%s" % (name, exc))
    smiles, field, warn = pick_smiles(props)
    return {
        "name": name,
        "smiles": smiles,
        "field": field,
        "warning": warn,
        "snapshot_id": rec["snapshot_id"],
        "sha256": rec["sha256"],
        "inchikey": anchor(smiles),
    }


def pipeline_guard(entries):
    """已发布流水线闸门：任何 entry 缺 InChIKey 或立体未声明 → 拒绝进入。"""
    bad = []
    for e in entries:
        v = validate_entry(
            e.get("name", ""),
            e.get("smiles", ""),
            e.get("declared_stereo", False),
            e.get("declared_racemic", False),
        )
        if v["status"] != "ok" or not v["inchikey"]:
            bad.append(v)
    return {
        "ok": not bad,
        "blocked": bad,
        "note": "名称→SMILES 只能作为交互辅助；流水线入口必须 InChIKey 锚定",
    }
