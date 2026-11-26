# -*- coding: utf-8 -*-
"""BBB 双层机制：被动渗透 × P-gp 外排（深水区建议 2.2）。

报告 2.2 的核心方法学立场（呼应 BBB-Nuke 2026 的 transport-aware 立场）：
BBB 穿透 = 被动跨细胞渗透 × 外排转运体（主要是 P-gp）净效应的乘积。两个过程是
**独立的**，需要两条独立的证据通道，它们的组合才产生"有效脑暴露"的裁决。

当前框架把 BBB 当作一个端点（vnn_bbb，role=reference），依赖外部源二元预测。
问题：当 BBB 为 UNDETERMINED 时，框架只给出泛泛的"补实验"，没有把 P-gp 外排作为
解释 UNDETERMINED 的具体机制。本模块在 BBB 语境下**激活 transporter_priors.yaml**
的 P-gp 先验与 assay 处方，把 UNDETERMINED 的 action **强制**指向"P-gp 底物概率评估"。

设计纪律：
  - 仅当 BBB 端点 verdict == UNDETERMINED 时触发（与报告建议一致；PASS/FAIL 不动）。
  - 不改写 verdict / confidence，只改写 action 并打标记 bbb_mechanism=dual_layer_activated，
    使 BBB 从"一个端点"重新框定为"双层机制问题"。
  - 这是对"准入逻辑应用于双层转运问题"的具体落地，与 BBB-Nuke（更好的预测模型）
    互补而非竞争。

⚠️ 机制落点限制（2026-11-03 B2 量化，见 references/B2_transporter_coverage.md；2026-11-03 补 P-gp/BCRP 外排启发式）：
  本模块"三通道决议"中：
  - 被动层：SAR 预筛，独立通道，OK；
  - **外排 P-gp/BCRP：已有启发式 moiety 骨架**（见 adt/efflux_heuristic.py + transporter_priors.yaml
    的 efflux_heuristics 块：P-gp 共识药效团，SMARTS 近似、**非实测**、须经 Caco-2 ± verapamil/elacridar
    验证）。SMILES 提供时自动评估底物 plausibility，但所有命中都**不得进 reliab 计票、不得改写原裁决**；
  - **摄取 OATP1A2/LAT1/GLUT1：已有启发式 moiety 骨架**（见 adt/uptake_heuristic.py +
     transporter_priors.yaml 的 uptake_heuristics 块：OATP1A2 大体积有机阴离子、
     LAT1 大中性 L-氨基酸、GLUT1 仅游离单糖；均**非实测**、须经过表达细胞摄取 ± 竞争抑制剂验证）；
  - **SGLT1：仍仅有 action 叙事文案，无结构判定规则**（且按生物学保真，SGLT1 在 BBB 内皮
     无功能性表达，属肠侧 Fa 通道，不纳入 BBB 侧摄取结构规则）；
  - OATP2B1：有 moiety 规则但黄酮专属，对 BBB_Martins 406 个 CNS 分子几乎不触发（2 例含糖），属肠侧 Fa 通道。
  故本机制仍是"框架级"而非"量化级"：外排（P-gp/BCRP）与摄取（OATP1A2/LAT1/GLUT1）均已升级为
  "有结构依据的待验证假设"，但**任何通道都不得给人"已被本 skill 量化"的印象**——
  所有命中必须经指定实验验证、且不得进 reliab 计票。要升级为量化级，须对 P-gp/BCRP/OATP1A2/LAT1
  做实验回填端点（role=reference）。
"""

import os

# BBB 类端点（含 vNN 命名与外部源命名）
BBB_ENDPOINTS = {"vnn_bbb", "bbb", "bbb_permeability", "bbb_penetration"}

# 外排通道（三通道之二）：P-gp / BCRP 主导负项
P_GP_ACTION = (
    "外排通道（三通道决议之二）：强制 P-gp / BCRP 底物概率评估——"
    "脑有效暴露 = 被动渗透 × 外排净效应，二者需独立取证。已启用 "
    "adt.efflux_heuristic（P-gp 共识药效团启发式；SMILES 提供时自动评估底物 plausibility，"
    "但**所有命中均须经 Caco-2 ± verapamil/elacridar 验证方可下结论，且不得进 reliab 计票**）。"
    "Caco-2 双向 + verapamil 100 µM（ER 比前后差）判定 P-gp 底物；"
    "+ elacridar 2 µM 分离 BCRP 贡献；"
    "若确为底物，即便被动渗透性好，有效脑暴露仍可能很低，需显式计入获益-风险"
)

# 摄取通道（三通道之三）：GLUT1 / SGLT1 / OATP2B1 作为脑暴露正项的评估
# ⚠️ 生物学保真（与报告 2.2 的"激活摄取先验"一致，但**不夸大** BBB 侧权重）：
#   - GLUT1 是 BBB 内皮的主要葡萄糖转运体，但只转运单糖、不转运完整糖苷；
#   - SGLT1 在 BBB 内皮**无功能性表达**（Yu et al. 实证：大鼠 BBB 无 SGLT 摄取），
#     其真实作用位点在肠上皮（决定 Fa 而非脑暴露）；
#   - 故完整糖苷在 BBB 侧的摄取正项权重低，真正杠杆在肠侧 SGLT1/OATP2B1 口服吸收。
UPTAKE_ACTION = (
    "摄取通道（三通道决议之三，作为脑暴露正项候选）：评估 GLUT1 / SGLT1 / OATP2B1 被本类糖苷"
    "识别的可能性。**生物学保真声明**：GLUT1 只转运单糖、不转运完整糖苷（糖基接到苷元/"
    "甘油后分子过大且失去单糖 C1–C6 空间排布）；SGLT1 在 BBB 内皮无功能性表达（Yu et al. 实证），"
    "其真实作用位点是肠上皮——决定 Fa 而非脑暴露。因此本类完整糖苷在 BBB 侧的摄取正项权重低；"
    "真正可解释口服吸收的摄取正项杠杆是肠侧 SGLT1 / OATP2B1 介导吸收（解释 Fa 缺口），"
    "以及苷元经肠菌/肠黏膜糖苷酶水解后的转运。框架据此把 BBB 决议重述为**三通道定位信息缺口**，"
    "而非笼统的 BBB+/-：被动层（已由 SAR 预筛判定关闭）→ 外排（P-gp/BCRP，主导负项）→ "
    "摄取（GLUT1/SGLT1/OATP2B1，权重需实验定位）。"
)


def is_bbb_endpoint(ep):
    if not ep:
        return False
    ep = str(ep).lower()
    if ep in BBB_ENDPOINTS:
        return True
    return ep.endswith("bbb") or "bbb" in ep


def apply_dual_layer(rec, smiles=None):
    """对单条裁决记录：若 BBB 端点且未给确定裁决（UNDETERMINED / 参照透传 PASSTHRU），
    强制改写 action 并打标。

    注意（架构要点）：vnn_bbb 在规则表里 role=reference，本化学类 14/14 域外 →
    框架走"参照透传 PASSTHRU"而非 UNDETERMINED。报告深水区 2.2 的原话是
    "当 BBB/vnn_bbb 为 UNDETERMINED 时强制 P-gp 评估"；在真实管线里 BBB 端点往往以
    PASSTHRU（reference 角色、域外）形式出现。两种情形都代表"BBB 方向证据不足"，
    都应触发双层机制激活——故这里对 UNDETERMINED 与 PASSTHRU 同样处理，PASS/FAIL 不动。

    smiles：可选，提供则同时运行 adt.efflux_heuristic（外排 P-gp/BCRP）与
    adt.uptake_heuristic（摄取 OATP1A2/LAT1/GLUT1），把两通道从纯叙事升级为
    "有结构依据的待验证假设"（启发式，非实测，强制指定实验验证）。
    不提供时两通道退化为纯叙事（与历史行为一致），不影响任何既有不变量。

    返回改写后的 rec（原地修改）。非 BBB / 已给确定裁决 原样返回。
    """
    ep = rec.get("endpoint", "")
    if not is_bbb_endpoint(ep):
        return rec
    if rec.get("verdict") not in ("UNDETERMINED", "PASSTHRU"):
        return rec

    rec["action"] = P_GP_ACTION + "\n\n" + UPTAKE_ACTION

    eff = None
    upt = None
    if smiles:
        try:
            from adt import efflux_heuristic as _eh

            eff = _eh.pgp_bcrp_efflux_heuristic(smiles)
            if eff.get("available"):
                rec[
                    "action"
                ] += (
                    "\n\n【外排启发式命中 · P-gp 共识药效团 · 非实测须验证】\n"
                    + _eh.summarize(eff)
                )
        except Exception:
            eff = None  # 结构解析失败/缺 rdkit：静默降级为纯叙事，不破坏裁决
        try:
            from adt import uptake_heuristic as _uh

            upt = _uh.oatp1a2_lat1_glut1_uptake_heuristic(smiles)
            if upt.get("available"):
                rec["action"] += (
                    "\n\n【摄取启发式命中 · OATP1A2/LAT1/GLUT1 共识药效团 · 非实测须验证】\n"
                    + _uh.summarize(upt)
                )
        except Exception:
            upt = None  # 结构解析失败/缺 rdkit：静默降级为纯叙事，不破坏裁决

    rec["efflux_heuristic"] = eff
    rec["uptake_heuristic"] = upt
    rec["bbb_mechanism"] = "three_channel_resolution"
    rec["bbb_channels"] = (
        "passive(closed_by_SAR)[可执行] × "
        "efflux(P-gp/BCRP)[启发式moiety骨架,非实测,需Caco-2±verapamil/elacridar验证] × "
        "uptake(OATP1A2/LAT1/GLUT1)[启发式moiety骨架,非实测,需过表达细胞±竞争抑制剂验证; "
        "SGLT1/OATP2B1为肠侧Fa通道不纳入; GLUT1仅游离单糖] "
        "-- 见 B2_transporter_coverage.md"
    )
    return rec


def postprocess(records):
    """对整批裁决记录做 BBB 双层激活（在 adjudicate 末尾调用）。

    若某条 rec 自带 smiles 字段，则自动透传给 apply_dual_layer 同时跑外排与摄取启发式；
    无 smiles 时退化为纯叙事（向后兼容 reliability 管线现行为）。
    """
    return [apply_dual_layer(r, r.get("smiles")) for r in records]
