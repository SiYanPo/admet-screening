# -*- coding: utf-8 -*-
"""问题②-b + 盲区3：L0 对抗性输入强制校验（含真实世界大分子支持）。

相对 v0.1 原型的增强（实测驱动）：
- 实测发现 TautomerEnumerator 对 peptide(124原子) 互变体触顶 1000、
  paclitaxel 96 个互变体、耗时 0.44s → 这是 OOM/挂死的真实来源。
- 新增 size guard：按原子数/环数/可旋转键/MW 分复杂度等级；
  大分子**跳过**互变枚举（标 skipped_oversize），并设枚举上限防爆。
- 复杂度分级：small / medium / large / macro（PROTAC、大环、多肽、ADC payload）。

任何标准化异常 → fail-closed 到最高级 UNDETERMINED，绝不静默通过。
依赖 rdkit（实测 2026.09.1）。
"""

from __future__ import annotations

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    from rdkit import RDLogger

    RDLogger.DisableLog("rdApp.*")
    _HAS_RDKIT = True
except Exception:  # pragma: no cover
    _HAS_RDKIT = False

# 并发改造（生产级）：单例枚举器 → 有界对象池。
# 单例在单线程快，但并发下 RDKit C++ 对象共享会串扰；用大锁串行化又等于挂死。
# concurrent_runtime 的池：锁只保护实例创建，Enumerate 在独占实例上跑，
# 队列带超时 → 池耗尽时 fail-closed 跳过而非死锁。见 tests/test_production.py。
from .concurrent_runtime import get_taut_pool
from .compute_directive import directive_for

SMALL_MAX_ATOMS = 40
MEDIUM_MAX_ATOMS = 120
MACRO_MIN_ATOMS = 200
MAX_RINGS_FOR_TAUT = 12
MAX_ROTATABLE_FOR_TAUT = 30
TAUT_MAX_ENUM_SMALL = 300  # small 分子完整枚举上限
TAUT_MAX_ENUM_MEDIUM = 50  # medium 受限枚举（实测 cap=50 仅 0.1s，且足以判 >1）
MAX_HETERO_FOR_TAUT = (
    16  # 杂原子太多（多酯/多羟基）→ 枚举成本高；16 已实测 paclitaxel(15) cap=50 仅 0.1s
)


def _base(ok, **kw):
    d = {
        "pass_guard": ok,
        "verdict": "UNDETERMINED" if not ok else None,
        "certainty_modifier": "low_unresolvable" if not ok else None,
        "reason": None,
        "detail": "",
        "inchikey": None,
        "calc_smiles": None,
        "state_sensitive": False,
        "declared_stereo": "undefined",
        "net_charge": None,
        "is_radical": None,
        "complexity": None,
        "n_atoms": None,
        "mol_wt": None,
        "n_rings": None,
        "n_rotatable": None,
        "n_stereo": None,
        "taut_skipped": False,
    }
    d.update(kw)
    if not ok:
        d["compute_directive"] = {
            "directive": "STOP_ALL",
            "reason": d.get("reason") or "L0_FAIL_CLOSED",
            "l2": "disabled",
            "l3": "disabled",
            "return_properties_only": True,
            "tier_ceiling": "T0",
        }
    return d


def _complexity_tier(n_atoms, n_rings, mol_wt):
    if n_atoms and n_atoms >= MACRO_MIN_ATOMS:
        return "macro"
    if n_atoms and n_atoms > MEDIUM_MAX_ATOMS:
        return "large"
    if n_atoms and n_atoms > SMALL_MAX_ATOMS:
        return "medium"
    return "small"


def adversarial_guard(smiles, *, max_abs_charge=3, do_tautomer=True):
    """L0 最终守卫。失败 → verdict=UNDETERMINED（最高级）。"""
    if not _HAS_RDKIT:
        return _base(
            False,
            reason="RDKIT_UNAVAILABLE",
            detail="rdkit 不可用，fail-closed",
            action="安装 rdkit 后重试",
        )

    if not isinstance(smiles, str) or not smiles.strip():
        return _base(
            False, reason="EMPTY_INPUT", detail="空输入", action="提供有效 SMILES"
        )

    # 预检：超长字符串直接拒绝（防解析前 OOM；5000 字符 ≈ 数千原子）
    if len(smiles) > 5000:
        return _base(
            False,
            reason="INPUT_TOO_LONG",
            detail="SMILES 长度=%d 超 5000" % len(smiles),
            action="结构过大，fail-closed；如确需评估请拆分或专用流程",
        )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return _base(
            False,
            reason="PARSE_FAILED",
            detail="RDKit 无法解析该 SMILES",
            action="结构标准化失败，禁止进入下游；需人工核定结构",
        )

    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        return _base(
            False,
            reason="SANITIZE_FAILED",
            detail=str(e)[:200],
            action="价键/芳香性异常，fail-closed",
        )

    try:
        inchikey = Chem.MolToInchiKey(mol)
    except Exception as e:
        return _base(
            False,
            reason="INCHIKEY_FAILED",
            detail=str(e)[:200],
            action="InChIKey 生成失败",
        )
    if not inchikey or len(inchikey) != 27:
        return _base(
            False,
            reason="INCHIKEY_INVALID",
            detail="InChIKey 长度=%r" % (len(inchikey) if inchikey else 0),
            action="InChIKey 锚定失败，fail-closed",
        )

    net_charge = Chem.GetFormalCharge(mol)
    is_radical = any(a.GetNumRadicalElectrons() > 0 for a in mol.GetAtoms())
    if is_radical:
        return _base(
            False,
            reason="RADICAL_SPECIES",
            detail="含自由基电子",
            action="自由基结构禁止进入下游预测",
        )
    if abs(net_charge) > max_abs_charge:
        return _base(
            False,
            reason="CHARGE_OUT_OF_RANGE",
            detail="净电荷=%d 超 ±%d" % (net_charge, max_abs_charge),
            action="净电荷异常，fail-closed",
        )

    # ---- 结构与复杂度画像 ----
    n_atoms = mol.GetNumAtoms()
    mol_wt = round(Descriptors.MolWt(mol), 2)
    n_rings = mol.GetRingInfo().NumRings()
    n_rotatable = Descriptors.NumRotatableBonds(mol)
    tier = _complexity_tier(n_atoms, n_rings, mol_wt)

    has_stereo = any(
        a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms()
    )
    n_possible_stereo = len(
        Chem.FindMolChiralCenters(
            mol, includeUnassigned=True, useLegacyImplementation=False
        )
    )
    if n_possible_stereo == 0:
        declared = "not_applicable"
    elif has_stereo:
        declared = "defined"
    else:
        declared = "undefined"

    # ---- 互变枚举：带 size guard + 分级 cap（防 OOM / 挂死）----
    # state_sensitive 必须是**显式**值，绝不能留 None 让下游误当"不敏感"：
    #   True/False     = 已枚举判定
    #   "skipped_oversize" = 分子太大跳过（性能保护）
    #   "not_evaluated"    = 未启用（do_tautomer=False）或枚举失败
    state_sensitive = "not_evaluated"
    taut_skipped = False
    if do_tautomer:
        n_hetero = sum(1 for a in mol.GetAtoms() if a.GetSymbol() in ("O", "N", "S"))
        too_big = (
            n_atoms > MEDIUM_MAX_ATOMS
            or n_rings > MAX_RINGS_FOR_TAUT
            or n_rotatable > MAX_ROTATABLE_FOR_TAUT
            or n_hetero > MAX_HETERO_FOR_TAUT
        )
        if too_big:
            taut_skipped = True
            state_sensitive = "skipped_oversize"
        else:
            try:
                cap = (
                    TAUT_MAX_ENUM_SMALL
                    if n_atoms <= SMALL_MAX_ATOMS
                    else TAUT_MAX_ENUM_MEDIUM
                )
                state_sensitive, taut_meta = get_taut_pool(cap).enumerate_states(mol)
                if state_sensitive == "not_evaluated":
                    taut_skipped = True  # 池耗尽/异常 → 显式跳过，绝不留 None
            except Exception:
                state_sensitive, taut_skipped = "not_evaluated", True
    else:
        taut_skipped = True
        state_sensitive = "not_evaluated"

    out = _base(
        True,
        inchikey=inchikey,
        calc_smiles=Chem.MolToSmiles(mol),
        net_charge=net_charge,
        is_radical=is_radical,
        state_sensitive=state_sensitive,
        declared_stereo=declared,
        n_possible_stereo=n_possible_stereo,
        complexity=tier,
        n_atoms=n_atoms,
        mol_wt=mol_wt,
        n_rings=n_rings,
        n_rotatable=n_rotatable,
        n_stereo=n_possible_stereo,
        taut_skipped=taut_skipped,
        action=None,
    )
    # L0 不只是打标签：把复杂度画像翻译成下游可执行预算指令（盲区3）
    out["compute_directive"] = directive_for(out)
    return out
