# -*- coding: utf-8 -*-
"""红线守卫（R34–R42 / 评审 §7.1 + 第三轮评审 §G）——**红线必须能在代码层被断言**。

文档里写"禁止"没有约束力：只要能用一条命令绕过，它就不是红线而是建议。
本模块把每条红线各落成一个**可调用、可测试**的守卫，并由 `red_lines_status()`
统一自检（发布门禁会读它，任一未落地即拒绝发布）。

| # | 红线 | 守卫 | 违反时的行为 |
|---|---|---|---|
| 1 | 禁止名称→SMILES 直连；InChIKey 锚定；立体缺失即 fail | `admission_line()` → `adt/pubchem.pipeline_guard` | `NormalizeInputError` |
| 2 | n<30 打横幅；n<10 只出定性结论 | `sample_size_guard(n)` | 返回 level=banner/qualitative（调用方必须打印） |
| 3 | 论文/决策数字必须来自快照重放模式 | `require_replay()` | `ReplayRequired` |
| 4 | DILI/Ames 需 `--i-accept-low-validity` 且留痕 | `low_validity_line()` | `LowValidityError` |
| 5 | 商用必须 `--profile commercial` 且调用日志归档 | `commercial_line(profile)` → `adt/compliance.enforce` | `ComplianceError` |
| 6 | 禁无区间措辞；护栏不可关闭 | `interval_line(text)` → `adt/phrasing` | 返回需改写短语（发布门禁拦截） |
| 7 | gate 判别力数字**必须带评测分布标注**；域内 AUC 不得用来评价门 | `gate_distribution_line(...)` | `RedLineError` |
| 8 | post-cutoff 类外源数字**必须同句标注「非预注册前瞻」** | `provenance_line(text)` | `RedLineError` |
| 9 | 端点依赖类结论**必须三端点并列**，禁单端点外推 | `endpoint_plurality_line(...)` | `RedLineError` |

**红线 7–9 的来历（第三轮评审 §G）**：这三条都不是"做事更仔细"式的要求，而是
**本包自己踩出来的坑**——(7) hERG 上 gate AUC 0.58 曾被写成"门没用"，而域内评测对门是
构造必然失败；(8) post-cutoff 的 0.581 一度被当作"前瞻证据"引用；(9) hERG 结论被直接
外推到"DILI 也迟钝"，而 DILI 其实只是功效不足。三条各配一条反例，见 `_RED7_CASES` 等。
"""

from __future__ import annotations

import os
import re

SMALL_N_BANNER = 30  # <30：打横幅，禁止声称"稳健"
QUALITATIVE_ONLY = 10  # <10：只出定性结论，禁止报任何率/差/排序
# C3（2026-11-03 评审）：0.65 此前被当作"红线判据"使用——但它是**约定工作点**，
# 无文献锚定、无功效分析、无 CI。用同一约定值同时充当"测量标尺"和"发布红线"是循环论证。
# 现降级为工作点（workpoint），红线的真正判据改为**必须给 95% CI**（DeLong/bootstrap）：
# CI 是数据自带的精度信息，工作点是人为约定，两者的证据等级不同，不能混用。
GATE_AUC_WORKPOINT = 0.65
GATE_AUC_MIN = GATE_AUC_WORKPOINT  # 兼容旧引用；语义已变，请勿再用作判据

# 红线 7–9 的反例（写进代码，防止"知道有这条规则但想不起来它防什么"）
_RED7_CASES = (
    "hERG：gate AUC 0.580 → 曾写成『本框架域外弃权无效』；"
    "错在评测分布是**域内**，门在域内没有可增加值。"
)
_RED8_CASES = (
    "post-cutoff AUC 0.581 曾与『前瞻验证』并置；"
    "该设计是 temporal external validation，**非**预注册前瞻。"
)
_RED9_CASES = (
    "hERG/BBB 判『模型对悬崖迟钝』后曾外推到 DILI；"
    "DILI 的 MMP 对数 31 < 需 61，状态是 `insufficient_power`，不是『迟钝』。"
)

# 红线 7：评测分布标注的合法取值
EVAL_DISTRIBUTIONS = ("in_domain", "out_of_domain", "mixed", "unknown")

_GATE_CLAIM_PAT = re.compile(
    r"(域外诚实|域外弃权|gate[^。；\n]{0,12}AUC|门[^。；\n]{0,12}(判别力|AUC)"
    r"|PASSTHRU[^。；\n]{0,12}(诚实|谨慎)|弃权[^。；\n]{0,6}(诚实|可靠))"
)
_DIST_TAG_PAT = re.compile(
    r"(评测分布|评测域|eval[_ ]distribution|域内评测|域外评测|in[_ ]domain|out[_ ]of[_ ]domain"
    r"|随机切分≈域内|分布内)"
)
_HONEST_CLAIM_PAT = re.compile(
    r"(域外[^。；\n，]{0,6}诚实|弃权[^。；\n，]{0,8}诚实|PASSTHRU[^。；\n，]{0,10}诚实"
    r"|审慎|谨慎|弃权[^。；\n，]{0,4}可靠|可靠地?弃权)"
)
# 诚实类措辞被否定时不算主张（"覆盖率不代表谨慎程度"不是在做域外诚实断言）
_NEG_PREFIX = ("不代表", "不等于", "不是", "并非", "不能", "不得", "禁止", "不应", "非")


def _honesty_hit(txt):
    """返回第一个**未被否定**的诚实类措辞 match；没有则 None。"""
    for m in _HONEST_CLAIM_PAT.finditer(txt):
        head = txt[max(0, m.start() - 5) : m.start()]
        if any(head.endswith(n) for n in _NEG_PREFIX):
            continue
        return m
    return None


_PROV_MARK_PAT = re.compile(
    r"(post[-_ ]cutoff|post-cutoff|外源留出|时间留出|ChEMBL_37|temporal external validation"
    r"|时间型外部验证)"
)
_NOT_PREREG_PAT = re.compile(r"(非预注册|不是预注册|非前瞻|不是前瞻|不冒充|未预注册)")
_FORBIDDEN_PROSPECTIVE_PAT = re.compile(
    r"(前瞻验证通过|通过前瞻|通过外部盲测|前瞻盲测通过|完成前瞻验证)"
)

_ENDPOINT_DEP_PAT = re.compile(
    r"(端点依赖|逐端点|gate[^。；\n]{0,10}判别力|MMP|活性悬崖|悬崖召回|"
    r"结构扰动稳定|迟钝|域外诚实|PASSTHRU)"
)
_ENDPOINTS_KNOWN = (
    "hERG",
    "DILI",
    "BBB",
    "BBB_Martins",
    "Ames",
    "Caco2",
    "lipophilicity",
    "solubility",
)
_SINGLE_ENDPOINT_SCOPE_PAT = re.compile(r"(单端点|仅本端点|只覆盖|不外推|只在本端点)")
_GLOBAL_CLAIM_PAT = re.compile(r"(所有端点|各端点均|普遍|一律|所有 ADMET 端点)")


class RedLineError(Exception):
    """红线被触发。**不可降级为 warning**——那是红线的意义所在。"""


class ReplayRequired(RedLineError):
    pass


class LowValidityError(RedLineError):
    pass


class NormalizeInputError(RedLineError):
    pass


# ---------------------------------------------------------------- 红线 2
def sample_size_guard(n):
    """红线 2：小样本必须显式降级，不能"看起来像正常结果"。"""
    n = int(n or 0)
    if n < QUALITATIVE_ONLY:
        return dict(
            n=n,
            level="qualitative",
            ranking_allowed=False,
            rates_allowed=False,
            banner=(
                "=" * 68 + "\n"
                "[红线2] n=%d < %d：**只允许定性结论**——禁止报一致率、"
                "差值、排序或风险分层，禁止与文献数值并排比较。\n"
                % (n, QUALITATIVE_ONLY)
                + "=" * 68
            ),
        )
    if n < SMALL_N_BANNER:
        return dict(
            n=n,
            level="banner",
            ranking_allowed=False,
            rates_allowed=True,
            banner=(
                "=" * 68 + "\n"
                "[红线2] n=%d < %d：小样本。允许报点估计 + 95%% CI，"
                "但**不得**声称稳健、不得默认排序（需 `rank --force` 并标 OVERRIDE）。\n"
                % (n, SMALL_N_BANNER)
                + "=" * 68
            ),
        )
    return dict(n=n, level="ok", ranking_allowed=True, rates_allowed=True, banner="")


# ---------------------------------------------------------------- 红线 3
def require_replay(action="publish"):
    """红线 3：对外数字必须能由快照重放复现，否则不可发布。

    放行条件：`ADT_REPLAY=1`（严格离线重放）。应急上网需 `ADT_ALLOW_ONLINE=1`
    并会在返回值里记 `override=True`——即"允许，但留痕"，而不是"允许且无声"。
    """
    # 2026-11-04 / C05：判据统一为 snapshot.replay_mode()（truthy），
    # 消除 ADT_REPLAY=true 时 snapshot 认为在重放、guards 认为不在的口径冲突。
    try:
        from . import snapshot as _SN

        in_replay = bool(_SN.replay_mode())
    except Exception as exc:
        # fail-closed：无法判定重放状态时不得放行
        raise ReplayRequired(
            "红线3：snapshot.replay_mode() 不可用（%r），拒绝放行" % (exc,)
        )
    if in_replay:
        return dict(
            ok=True,
            override=False,
            non_replayable=False,
            replay_mode="strict",
            note="快照重放模式：所有 fetch 走本地快照，sha256 校验通过才返回",
        )
    if os.environ.get("ADT_ALLOW_ONLINE") == "1":
        return dict(
            ok=True,
            override=True,
            non_replayable=True,
            replay_mode="online_override",
            override_reason="ADT_ALLOW_ONLINE=1",
            note=(
                "⚠ 非重放模式（ADT_ALLOW_ONLINE=1）：本次结果标记 "
                "non_replayable，**不可作为论文/决策数字**，只能作为探索；"
                "--publish 下必须由 cli 强制 exit 4（C05），"
                "对外发布前必须在 ADT_REPLAY=1 下重跑"
            ),
        )
    raise ReplayRequired(
        "红线3：%s 需要快照重放模式（ADT_REPLAY=1）。当前为联网取数模式，"
        "结果不可复现，禁止用于论文或对外决策数字。" % action
    )


# ---------------------------------------------------------------- 红线 4
def low_validity_line(endpoints, accepted=False, note=""):
    """红线 4：DILI/Ames 等低有效性端点必须显式接受并留痕。"""
    from . import endpoints as EP

    risky = [
        e for e in (endpoints or []) if EP.endpoint_tier(e)[0] == "not_recommended"
    ]
    if not risky:
        return dict(ok=True, blocked=[], accepted=False)
    if not accepted:
        raise LowValidityError(
            "红线4：端点 %s 属「不推荐用于计算裁决」（DILI/Ames/致癌性/nr_ar_lbd 的判据在"
            "公开基准上不稳定）。如确需使用：加 `--i-accept-low-validity`，"
            "并在报告中写明「自担低有效性」。" % ", ".join(risky)
        )
    return dict(
        ok=True,
        blocked=risky,
        accepted=True,
        note="已显式接受低有效性端点：%s；须在报告中留痕（%s）"
        % (", ".join(risky), note or "未提供理由"),
    )


# ---------------------------------------------------------------- 红线 1
def admission_line(entries):
    """红线 1：名称→结构入口未锚定 InChIKey 或立体未声明 → 阻断流水线。"""
    from . import pubchem as PB

    res = PB.pipeline_guard(entries)
    if not res["ok"]:
        raise NormalizeInputError(
            "红线1：%d 个输入未通过结构准入（缺 InChIKey 或立体未声明）：%s"
            % (
                len(res["blocked"]),
                "; ".join(
                    "%s:%s"
                    % (b.get("name"), "/".join(b.get("reasons") or [b.get("status")]))
                    for b in res["blocked"][:5]
                ),
            )
        )
    return res


# ---------------------------------------------------------------- 红线 6
def interval_line(text, has_ci_or_test=False):
    """红线 6：无区间的比较措辞一律拦截；护栏本身不可关闭。"""
    from . import phrasing as PH

    hits = PH.flag_unqualified_superiority(text, has_ci_or_test=has_ci_or_test)
    if hits:
        raise RedLineError(
            "红线6：出现无 95%% CI / 无配对检验支撑的比较词 %s。改写为"
            "『差异为 X（95%% CI [a,b]）』或『配对检验 p=…』；护栏不可关闭。"
            % ", ".join(hits)
        )
    return dict(ok=True, hits=[])


# ---------------------------------------------------------------- 红线 7
def gate_distribution_line(
    statement, eval_distribution=None, auc=None, endpoint=None, auc_ci=None
):
    """红线 7（第三轮评审 §G / C3）：gate 判别力数字**必须带评测分布标注 + 95% CI**。

    为什么必须有这条：门（AD/弃权层）在**域内**评测时 AUC 构造必然 ≈0.5——
    域内到处都是"模型能预测对"的分子，门没有可增加值。所以"gate AUC 0.58 → 门没用"
    这个推论在域内评测下**不成立**（hERG 的 0.58 就是这么被误读的）。
    门的合格证据只剩**域外强制预测**实验。

    C3 修复（2026-11-03 评审）：原实现用点估计 `auc < 0.65` 判定"不得称诚实"。
    但 0.65 是**约定工作点**（无文献锚定、无功效分析），而端点级 n<500 时 AUC 的
    SE≈0.02–0.03——用点估计与人为阈值比较，等于用抽样噪声与约定值比较。
    现改为：凡声称"域外诚实/审慎/可靠弃权"，**必须**给 95% CI；
    判据改为 CI **上界**是否越过工作点（上界低于工作点 = 统计上无法支持该主张）。

    规则：
    1. 文本提到 gate 判别力/域外弃权/PASSTHRU 诚实 → 必须给 `eval_distribution`；
    2. `eval_distribution` 必须是 EVAL_DISTRIBUTIONS 之一；
    3. `eval_distribution='in_domain'` 时**禁止**任何"域外诚实/审慎/可靠弃权"表述
       （域内测不出这件事）；
    4. 给了 `auc` 且出现诚实类主张 → **必须给 `auc_ci=(lo, hi)`**（DeLong/bootstrap）；
       `hi < GATE_AUC_WORKPOINT` 时禁止该主张（点估计比较不再作为判据）。
    """
    txt = str(statement or "")
    if not _GATE_CLAIM_PAT.search(txt):
        return dict(ok=True, triggered=False, note="文本未涉及 gate 判别力主张")
    if eval_distribution is None:
        raise RedLineError(
            "红线7：文本涉及 gate 判别力/域外弃权表述，但**未标注评测分布**。\n"
            "  原文片段：%s…\n"
            "  必须补 `eval_distribution ∈ %s`——域内 AUC 不能用来评价门"
            "（构造必然 ≈0.5）；门的合格证据只剩域外强制预测。\n"
            "  反例出处：%s" % (txt[:60], list(EVAL_DISTRIBUTIONS), _RED7_CASES)
        )
    if eval_distribution not in EVAL_DISTRIBUTIONS:
        raise RedLineError(
            "红线7：eval_distribution=%r 非法，只能是 %s"
            % (eval_distribution, list(EVAL_DISTRIBUTIONS))
        )
    honest = _honesty_hit(txt)
    if honest and eval_distribution == "in_domain":
        raise RedLineError(
            "红线7：在**域内**评测分布下不得声称『%s』——域内 AUC≈0.5 是构造必然，"
            "不是门的失败，也不是门的成功。改报域外强制预测实验。\n  反例出处：%s"
            % (honest.group(0), _RED7_CASES)
        )
    if honest and auc is not None:
        if auc_ci is None:
            raise RedLineError(
                "红线7（C3）：声称『%s』时必须给 AUC 的 **95%% CI**（DeLong 或 bootstrap，"
                "≥1000 次重抽）。点估计 AUC=%.3f 不能作为红线判据——端点级 n<500 时 "
                "SE≈0.02–0.03，与工作点 %.2f 的差可完全由抽样噪声产生。\n"
                "  允许写法：『gate-as-classifier AUC 0.60 [0.54, 0.66]，out_of_domain；"
                "上界未越过工作点 0.65 → 不称诚实』。\n  反例出处：%s"
                % (honest.group(0), float(auc), GATE_AUC_WORKPOINT, _RED7_CASES)
            )
        try:
            lo, hi = float(auc_ci[0]), float(auc_ci[1])
        except (TypeError, ValueError, IndexError):
            raise RedLineError(
                "红线7：auc_ci 必须是 (lo, hi) 二元组，收到 %r" % (auc_ci,)
            )
        if not (0.0 <= lo <= hi <= 1.0):
            raise RedLineError("红线7：auc_ci=%r 非法（要求 0≤lo≤hi≤1）" % (auc_ci,))
        if hi < GATE_AUC_WORKPOINT:
            raise RedLineError(
                "红线7：AUC=%.3f，95%%CI 上界 %.3f < 工作点 %.2f——统计上无法支持"
                "『%s』。这不是“门没用”（域内 AUC≈0.5 是构造必然），而是"
                "**该证据不足以支撑该主张**。\n  反例出处：%s"
                % (float(auc), hi, GATE_AUC_WORKPOINT, honest.group(0), _RED7_CASES)
            )
    return dict(
        ok=True,
        triggered=True,
        eval_distribution=eval_distribution,
        endpoint=endpoint,
        auc=None if auc is None else float(auc),
        auc_ci=None if auc_ci is None else [float(auc_ci[0]), float(auc_ci[1])],
        note="已标注评测分布"
        + ("" if auc is None else "，AUC=%.3f" % float(auc))
        + (
            ""
            if auc_ci is None
            else "（95%%CI %.3f–%.3f）" % (float(auc_ci[0]), float(auc_ci[1]))
        ),
    )


# ---------------------------------------------------------------- 红线 8
def provenance_line(text):
    """红线 8（第三轮评审 §G）：post-cutoff 类外源数字**必须同句标注「非预注册前瞻」**。

    为什么必须有这条：post-cutoff 时间留出是 TRIPOD+AI 认可的
    temporal external validation，但**不是**预注册前瞻——阈值与口径是见到数据后才定的。
    把它写成"前瞻验证通过"是把"事后解释"冒充"事前承诺"，是本包最容易被抓的一处。
    """
    txt = str(text or "")
    if not txt:
        return dict(ok=True, triggered=False)
    bad = _FORBIDDEN_PROSPECTIVE_PAT.search(txt)
    if bad:
        raise RedLineError(
            "红线8：出现『%s』——post-cutoff 类外源留出**不是**前瞻预注册，"
            "不得写成通过前瞻/盲测。允许写法：『post-cutoff 外源留出上的表现"
            "（非预注册前瞻）』。\n  反例出处：%s" % (bad.group(0), _RED8_CASES)
        )
    if not _PROV_MARK_PAT.search(txt):
        return dict(ok=True, triggered=False, note="文本未涉及 post-cutoff 类外源数字")
    has_number = bool(re.search(r"\d", txt))
    if has_number and not _NOT_PREREG_PAT.search(txt):
        raise RedLineError(
            "红线8：引用了 post-cutoff/外源留出数字，但**同句未标注『非预注册前瞻』**。\n"
            "  原文片段：%s…\n"
            "  改写示例：『post-cutoff 外源留出（n=9443，非预注册前瞻）AUC 0.581 "
            "[0.569, 0.593]』。\n  反例出处：%s" % (txt[:60], _RED8_CASES)
        )
    return dict(ok=True, triggered=True, note="已标注非预注册前瞻")


# ---------------------------------------------------------------- 红线 9
def endpoint_plurality_line(claim, endpoints=None, kind="gate"):
    """红线 9（第三轮评审 §G）：端点依赖类结论**必须三端点并列**，禁单端点外推。

    为什么必须有这条：本包实测证明 gate 判别力与 MMP 迟钝都是**端点依赖**的——
    DILI 上 gate AUC 0.669（有据），hERG 0.580 / BBB 0.514（无据）；
    DILI 的 MMP 只有 31 对（需 61）→ `insufficient_power`，不是"迟钝"。
    在 hERG 上跑一次就写"本框架的门没判别力"，会被 DILI 直接反证。

    规则：
    1. 结论涉及 gate 判别力 / MMP / 活性悬崖 / 迟钝 / PASSTHRU 时，
       必须给 ≥3 个端点，或显式写"单端点/仅本端点/不外推"的限定语；
    2. 出现"所有端点/各端点均/普遍"等全局量词时，必须真的给 ≥3 端点。
    """
    txt = str(claim or "")
    eps = [e for e in (endpoints or []) if e]
    if not _ENDPOINT_DEP_PAT.search(txt):
        return dict(ok=True, triggered=False, note="文本未涉及端点依赖结论")
    scoped = bool(_SINGLE_ENDPOINT_SCOPE_PAT.search(txt))
    global_q = bool(_GLOBAL_CLAIM_PAT.search(txt))
    if global_q and len(eps) < 3:
        raise RedLineError(
            "红线9：出现全局量词但只给了 %d 个端点（需 ≥3）。端点依赖结论禁止外推。\n"
            "  反例出处：%s" % (len(eps), _RED9_CASES)
        )
    if len(eps) < 3 and not scoped:
        raise RedLineError(
            "红线9：%s 类结论只给了 %d 个端点，且未声明『单端点/仅本端点/不外推』。\n"
            "  要么补齐三端点并列（本包默认 hERG / DILI / BBB_Martins），"
            "要么显式限定适用范围。\n  反例出处：%s" % (kind, len(eps), _RED9_CASES)
        )
    return dict(
        ok=True,
        triggered=True,
        n_endpoints=len(eps),
        endpoints=eps,
        scoped_only=scoped,
        note="端点并列满足" if len(eps) >= 3 else "已显式限定单端点",
    )


# ---------------------------------------------------------------- 自检
def red_lines_status():
    """九条红线的**接线**状态（G8 读这个，任一 False 即拒绝发布）。

    C1（2026-11-03 评审）修复：本函数原先返回**硬编码 ok=True 的字典**——它不验证
    任何接线，只复述自身。G8 因此检查的是"红线声称已落地"，而非"红线已落地"，
    与本文档开头"能不能用一条命令绕过"的判据直接矛盾。

    现改为委托 `adt/redlines.py`：
      - 用 AST 探测每条红线在生产代码中的调用点是否真实存在；
      - 检查每条红线是否配有 `REDLINE-<id>` 集成测试；
      - 二者缺一即 ok=False，并把 hardness 如实暴露（hard/soft/conditional）。
    """
    from . import redlines as RL

    st = RL.status()
    _ANTIFACT = {
        "7_gate_eval_distribution": _RED7_CASES,
        "8_external_not_preregistered": _RED8_CASES,
        "9_endpoint_plurality": _RED9_CASES,
    }
    out = {}
    for k, v in st.items():
        out[k] = dict(
            ok=v["ok"],
            where=",".join(v["sites"]) or "(未接线)",
            test=v["test"],
            hardness=v["hardness"],
            name=v["name"],
            missing=v["missing"] or v["test_why"],
            antifact=_ANTIFACT.get(k, ""),
        )
    return out


def all_enforced():
    st = red_lines_status()
    return all(v["ok"] for v in st.values()), st
