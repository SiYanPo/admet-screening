# -*- coding: utf-8 -*-
"""Gate 0.5：分子状态标准化。

为什么必须有这一步（本项目实测）：真 M 与旧 M 只是连接方式不同，
ADMETlab 给出的 pKa 就从 6.93 变到 7.03、logD 从 0.83 到 0.57、logP 从 0.28 到 −0.01。
如果连互变异构体、质子化状态都不固定，这些量的漂移会比"换结构"更大，
而我们却会把它当成"模型误差"。

流程：去盐取最大片段 -> 电荷中和 -> 官能团标准化 -> 互变异构体规范化。
输出必须同时保留 input_smiles 与 calc_smiles，后者才是送进所有预测源的 SMILES。
"""

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, inchi, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_TAUT = rdMolStandardize.TautomerEnumerator()
_TAUT.SetMaxTautomers(1000)
# 关键：默认设置会**丢掉双键立体化学**。实测真 M 经默认规范化后
# InChIKey 从 MPZFXDIZHZVXBJ-SGKFEUNSSA-N 变成 ...-DMLMUOLJSA-N，
# /C=C/ 变成 C=C，E/Z 信息丢失——对肉桂酰类是不可接受的错误。
_TAUT.SetRemoveBondStereo(False)
_TAUT.SetRemoveSp3Stereo(False)
_TAUT.SetReassignStereo(True)
_UNCHARGER = rdMolStandardize.Uncharger()
_NORMALIZER = rdMolStandardize.Normalizer()
_LFC = rdMolStandardize.LargestFragmentChooser()


def _stereo_signature(m):
    """(骨架 InChIKey 前 14 位, 指定手性中心数, 指定双键数)。"""
    if m is None:
        return ("", 0, 0)
    ik = inchi.MolToInchiKey(m)
    tetra = sum(
        1
        for a in m.GetAtoms()
        if a.HasProp("_CIPCode") or a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
    )
    dbl = sum(1 for b in m.GetBonds() if b.GetStereo() != Chem.BondStereo.STEREONONE)
    return (ik.split("-")[0], tetra, dbl)


def _stereo_guard(before, after):
    """规范化不得改变骨架、也不得减少立体信息。返回 (ok, reason)。"""
    sb, sa = _stereo_signature(before), _stereo_signature(after)
    if sb[0] != sa[0]:
        return False, "骨架变了（%s -> %s）" % (sb[0], sa[0])
    if sa[1] < sb[1]:
        return False, "手性中心 %d -> %d" % (sb[1], sa[1])
    if sa[2] < sb[2]:
        return False, "双键立体 %d -> %d" % (sb[2], sa[2])
    return True, ""


def _smiles(m):
    return Chem.MolToSmiles(m) if m is not None else ""


def hard_gates(m):
    """B2 价键/奇电子硬门（外部线实测抓到过自由基阳离子与价键写错）。

    返回问题列表；非空 = 拦截分发：
      odd_electron  电子总数为奇（闭壳层中性分子应为偶）——
                    典型成因：质子化/去氢实现丢隐式 H 产生自由基
      valence_error SanitizeMol 不过（价键超限）
    """
    problems = []
    if m is None or m.GetNumAtoms() == 0:
        return ["empty_molecule"]
    try:
        copy = Chem.Mol(m)
        copy.UpdatePropertyCache(strict=False)
        Chem.SanitizeMol(copy)
    except Exception as exc:
        problems.append("valence_error(%s)" % type(exc).__name__)
        # 电子数 = Σ(原子序 + 氢计数) − 净电荷。氢计数必须加：[CH3] 的 3 个 H
    # 是 explicit-H 计数而非原子节点，漏加会把自由基判成闭壳层（实测踩过）
    n_elec = sum(
        a.GetAtomicNum() + a.GetTotalNumHs() for a in m.GetAtoms()
    ) - Chem.GetFormalCharge(m)
    if n_elec % 2 == 1:
        problems.append("odd_electron(%d e-)" % n_elec)
    # 显式 radical 标记：电子总数可能为偶（如 [NH2]c1ccccc1）但仍是自由基
    n_rad = sum(a.GetNumRadicalElectrons() for a in m.GetAtoms())
    if n_rad:
        problems.append("radical_spec(%d e-)" % n_rad)
    return problems


def state_sensitivity(m):
    """C2 状态假设的区间化（括号思想的轻量版）。

    比较"当前状态"与"中和态"两个微状态的描述符极差：
    TPSA 差 > 10 或 cLogP 差 > 0.5 -> 该分子的这些描述符带状态不确定度，
    下游引用时必须声明。返回 dict(state_sensitive=bool, dtpsa, dclogp)。
    """
    m2 = _UNCHARGER.uncharge(Chem.Mol(m))
    dtpsa = abs(Descriptors.TPSA(m) - Descriptors.TPSA(m2))
    dclogp = abs(Crippen.MolLogP(m) - Crippen.MolLogP(m2))
    # 阈值实测校准：单电荷基团（醋酸根）dTPSA≈2.8、dClogP≈0.1 —— 这类差异
    # 通常低于源的报告精度；显著影响预测的是 dTPSA>3 或 dClogP>0.2
    return dict(
        state_sensitive=bool(dtpsa > 3 or dclogp > 0.2),
        dtpsa=round(dtpsa, 2),
        dclogp=round(dclogp, 2),
    )


def standardize(smiles):
    """返回 dict(input_smiles, calc_smiles, steps, formula, inchikey, mw,
    clogp, hard_gate_problems, state_sensitive)。"""
    steps = []
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError("SMILES 解析失败: %r" % smiles)
    m_orig = Chem.Mol(m)  # 保留原始态：状态敏感性必须对"用户输入的微状态"算，
    # 而不是标准化后的态（实测踩过：对标准化后的 m 算恒为 0，
    # 两性离子的状态敏感标记从未触发——v2.0.1 实例排查抓出）
    s0 = _smiles(m)

    # 1) 去盐 / 取最大有机片段（保留电荷中和）
    m2 = _LFC.choose(m)
    if _smiles(m2) != s0:
        steps.append("desalt")
    m = m2

    # 2) 电荷中和（季铵除外；Uncharger 会自行判断）
    m2 = _UNCHARGER.uncharge(m)
    if _smiles(m2) != _smiles(m):
        steps.append("uncharge")
    m = m2

    # 3) 官能团标准化（硝基、亚砜等表示法统一）
    m2 = _NORMALIZER.normalize(m)
    if _smiles(m2) != _smiles(m):
        steps.append("normalize")
    m = m2

    # 4) 互变异构体规范化（带立体保护）
    before = _smiles(m)
    m2 = _TAUT.Canonicalize(m)
    ok, why = _stereo_guard(m, m2)
    if _smiles(m2) != before:
        if ok:
            steps.append("tautomer")
            m = m2
        else:
            steps.append("tautomer_REVERTED(%s)" % why)
            # 保留互变异构前的结构，宁可不动也不能破坏立体
    m = m2 if ok else m

    calc = _smiles(m)
    gates = hard_gates(m)
    sens = state_sensitivity(m_orig)
    if gates:
        steps.append("HARD_GATE:" + "+".join(gates))
    return dict(
        input_smiles=smiles,
        calc_smiles=calc,
        state_flag=("+".join(steps) if steps else "unchanged"),
        formula=rdMolDescriptors.CalcMolFormula(m),
        inchikey=inchi.MolToInchiKey(m) if m.GetNumAtoms() else "",
        mw=round(Descriptors.MolWt(m), 2),
        clogp=round(Crippen.MolLogP(m), 2),
        hard_gate_problems=";".join(gates),
        state_sensitive=(
            ""
            if not sens["state_sensitive"]
            else "dTPSA=%.1f,dClogP=%.2f" % (sens["dtpsa"], sens["dclogp"])
        ),
    )


def charges_and_ph(smiles, ph=7.4):
    """给出酸性/碱性中心个数与 pH 7.4 下的粗略净电荷提示。

    不做真实 pKa 计算（本机没有可靠 pKa 源），只用于标记"这个分子的质子化
    状态在不同源之间可能不一致"，提示使用者核对。
    """
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return {}
    acids = m.GetSubstructMatches(Chem.MolFromSmarts("[OX2H1]"))
    # F4（全流程覆盖测试发现）：旧 SMARTS 末尾的 `!$(N-*)` 本意排除阴离子氮，
    # 实际匹配"任何单键相连的 N"，把**全部胺**排除——propranolol（仲胺）reported 0 个碱性氮。
    # 修正：用 !$([N-]) 只排阴离子，另排酰胺/磺酰胺/腈（非碱性）。
    bases = m.GetSubstructMatches(
        Chem.MolFromSmarts(
            "[NX3;H2,H1,H0;!$(N=*);!$([N-]);!$(N-C(=O));!$(N-S(=O)(=O));!$(N#*)]"
        )
    )
    return dict(
        n_acid_sites=len(acids),
        n_base_sites=len(bases),
        note=(
            "含 %d 个酸性羟基、%d 个碱性氮：pH 7.4 下离子化比例需逐源核对"
            % (len(acids), len(bases))
        ),
    )
