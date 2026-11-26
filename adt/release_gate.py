# -*- coding: utf-8 -*-
"""发布门禁（R02 / R3-4）：把 8 项 🟡 从"待办"转成"门禁"。

评审原话（R3-4）："无快照指纹、无契约快照、无 Docker digest（或等价环境指纹）
→ 拒绝发布。这是把 8 项 🟡 从'待办'转化为'门禁'的制度化动作。"

本模块只做判定，不改任何东西。任一 blocker 未通过 → `passed=False`，
SKILL.md 的 v4.0 标签授予流程必须读取本判定（见 references/RELEASE_POLICY.md）。

检查项：
  G1 requirements.lock 存在且全部行为精确钉版（`pkg==ver`）
  G2 快照库存在（n≥1）且 sha256 全量校验通过
  G3 契约快照存在（adapters 响应快照 ≥1，用于契约测试重放）
  G4 环境指纹已落盘（env_fingerprint.json，含 python/平台/关键库版本）
  G5 运行 manifest 存在（命令→数据hash→环境指纹→结论 四元组）
  G6 容器指纹：Docker digest 或显式声明"以环境指纹替代"（env_fingerprint 双份）
  G7 独立性归因前置：证据 DAG 声明文件存在（可为 pending 占位，但必须显式）
  G8 红线可断言：`guards.red_lines_status()` 九条全部 ok
  G9 标签授予：版本号带 -dev 才允许在未锚定时存在
  G10 主张登记表：每条数字主张的产物存在且字面量命中（第三轮评审 §B）
  G11 负结果默认配置：每条负结果落成默认值且带产物级证据（第三轮评审 §E4）

注：本模块的 G 编号与 `references/05_qa_gates.md` 的 G 编号是**两个独立命名空间**
（前者是发布门禁，后者是分析 QA gate）。第三轮评审说的"release-check G10 门"
指的是本命名空间，故新增项从 G10 续编，不与 05_qa_gates 的 G10（安全裕度）冲突。
"""

import io
import json
import os
import platform
import re
import sys

LOCK_CANDIDATES = ("requirements.lock", "requirements.txt")


def _read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def _item(key, ok, level, detail, fix=""):
    # 2026-11-04 / C03、外审 C V2：禁止把 ok=True 的 warn 归一成 ok。
    # 旧实现 `level if not ok else "ok"` 与 check() 里「warnings 只收 not ok」
    # 构成双重抹除，使 G6/G7/G9/G12 最该被看见的软肋显示 OK 且 warnings=[]。
    return {"key": key, "ok": bool(ok), "level": level, "detail": detail, "fix": fix}


def env_fingerprint():
    fp = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "impl": platform.python_implementation(),
    }
    for mod in ("rdkit", "numpy", "scipy", "sklearn", "pandas", "yaml"):
        try:
            m = __import__(mod)
            fp[mod] = getattr(m, "__version__", "unknown")
        except Exception:
            fp[mod] = "absent"
    return fp


def _check_lock(root):
    for name in LOCK_CANDIDATES:
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        bad = []
        for ln in _read(p).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if "==" not in ln:
                bad.append(ln)
        if bad:
            return _item(
                "G1_pinned_lock",
                False,
                "blocker",
                "%s 存在未精确钉版行：%s" % (name, bad[:3]),
                "改为 pkg==version，或 pip-compile --generate-hashes",
            )
        return _item("G1_pinned_lock", True, "blocker", "%s 全量精确钉版" % name)
    return _item(
        "G1_pinned_lock",
        False,
        "blocker",
        "缺 requirements.lock",
        "从实测环境回填精确版本",
    )


def _check_snapshots(root):
    from adt import snapshot as snap

    root_s = os.path.join(root, "snapshots")
    s = snap.summary(root_s)
    if s["n_snapshots"] == 0:
        return _item(
            "G2_snapshots",
            False,
            "blocker",
            "快照库为空",
            "用 ADT_SNAPSHOT 模式跑一次取数，落盘后重放",
        )
    if s["failed"]:
        return _item(
            "G2_snapshots",
            False,
            "blocker",
            "快照哈希校验失败 %d 条：%s" % (s["failed"], s["failed_ids"]),
            "快照被改动或损坏，重新抓取并归档",
        )
    return _item(
        "G2_snapshots",
        True,
        "blocker",
        "快照 %d 条全部校验通过（源：%s）" % (s["n_snapshots"], s["by_source"]),
    )


def _check_contract(root):
    d = os.path.join(root, "snapshots", "contracts")
    n = 0
    if os.path.isdir(d):
        n = len([f for f in os.listdir(d) if f.endswith(".json")])
    if n == 0:
        return _item(
            "G3_contract_snapshots",
            False,
            "blocker",
            "无 adapter 契约响应快照",
            "为每个适配器落 1 条真实响应快照到 snapshots/contracts/",
        )
    return _item("G3_contract_snapshots", True, "blocker", "契约快照 %d 条" % n)


def _check_envfp(root):
    p = os.path.join(root, "env_fingerprint.json")
    if not os.path.isfile(p):
        return _item(
            "G4_env_fingerprint",
            False,
            "blocker",
            "未落盘环境指纹",
            "python -m adt.cli env-fp > env_fingerprint.json",
        )
    try:
        saved = json.loads(_read(p))
    except ValueError:
        return _item("G4_env_fingerprint", False, "blocker", "环境指纹文件损坏")
    cur = env_fingerprint()
    diffs = {k: (saved.get(k), v) for k, v in cur.items() if saved.get(k) != v}
    if diffs:
        return _item(
            "G4_env_fingerprint",
            False,
            "warn",
            "环境已漂移：%s" % list(diffs)[:4],
            "重新生成指纹并在材料中声明漂移",
        )
    return _item("G4_env_fingerprint", True, "blocker", "环境指纹一致")


def _check_manifest(root):
    """G5 / C2-a（2026-11-04）：读 manifest.json **内容**并校验四元组，不再数文件。

    旧实现只统计 `run_manifest.*` 的份数 >=1 就 ok —— 外审 C V5 判其为
    「把人工断言自动化」：文件存在不等于四元组真的生成、不等于内容哈希自洽。
    """
    from . import manifest as M

    js, legacy = [], []
    for dirpath, _dirs, files in os.walk(root):
        if "snapshots" in dirpath:
            continue
        for f in files:
            if f == "manifest.json":
                js.append(os.path.join(dirpath, f))
            elif f in ("run_manifest.yaml", "run_manifest.json"):
                legacy.append(os.path.join(dirpath, f))
        if len(js) >= 3 and len(legacy) >= 3:
            break
    if not js and not legacy:
        return _item(
            "G5_manifest",
            False,
            "blocker",
            "无 run_manifest",
            "manifest.write_manifest 产 命令→hash→环境→结论 四元组",
        )
    problems = []
    for p in js[:3]:
        try:
            m = json.loads(_read(p))
        except (ValueError, OSError) as exc:
            problems.append("%s 不可解析（%s）" % (p, exc))
            continue
        missing = [
            k
            for k in (
                "command",
                "script_sha256",
                "data_sha256",
                "env_digest",
                "content_sha256",
            )
            if k not in m
        ]
        if missing:
            problems.append("%s 缺四元组字段 %s" % (p, missing))
            continue
        if M.content_hash(m) != m.get("content_sha256"):
            problems.append("%s 内容哈希不自洽（可能被事后改写）" % p)
        if not isinstance(m.get("data_sha256"), list):
            problems.append("%s data_sha256 非数组" % p)
    if problems:
        return _item(
            "G5_manifest",
            False,
            "blocker",
            "manifest 四元组校验失败：%s" % "; ".join(problems[:3]),
            "重跑 write_manifest 生成 manifest.json；不得手工编辑内容哈希",
        )
    if not js:
        return _item(
            "G5_manifest",
            True,
            "warn",
            "只有 %d 份旧 run_manifest.yaml，无 manifest.json 四元组" % len(legacy),
            "重跑一次批量命令以生成 manifest.json（C2-a）",
        )
    return _item(
        "G5_manifest",
        True,
        "info",
        "manifest.json %d 份：四元组字段与内容哈希逐份自洽" % len(js),
    )


def _check_container(root):
    for name in ("DOCKER_DIGEST", "docker_digest.txt"):
        p = os.path.join(root, name)
        if os.path.isfile(p) and _read(p).strip():
            return _item(
                "G6_container_fingerprint", True, "blocker", "Docker digest 已登记"
            )
    declare = os.path.join(root, "env_fingerprint.json")
    if os.path.isfile(declare):
        return _item(
            "G6_container_fingerprint",
            True,
            "warn",
            "无 Docker digest，以环境指纹替代（须在材料中显式声明）",
        )
    return _item(
        "G6_container_fingerprint",
        False,
        "blocker",
        "既无 Docker digest 也无环境指纹",
        "二选一必须落地",
    )


def _check_dag(root):
    for name in ("references/EVIDENCE_DAG.md", "references/EVIDENCE_DAG.yaml"):
        if os.path.isfile(os.path.join(root, name)):
            txt = _read(os.path.join(root, name))
            status = (
                "pending"
                if "status: pending" in txt or "状态：pending" in txt
                else "declared"
            )
            return _item(
                "G7_evidence_dag", True, "warn", "证据 DAG 已声明（%s）" % status
            )
    return _item(
        "G7_evidence_dag",
        False,
        "blocker",
        "缺证据 DAG 声明",
        "至少落一份 references/EVIDENCE_DAG.md（可标 pending）",
    )


def _check_red_lines(root):
    """R34–R39 / C1：九条红线必须**在生产路径上接线**（声明不算、测试通过也不算）。

    C1（2026-11-03 评审）：本检查原先读 `guards.red_lines_status()` 的硬编码
    ok=True 字典——它复述自身而不验证接线，与"能不能用一条命令绕过"的判据矛盾。
    现在读 `redlines.status()`：AST 探测每条红线的生产调用点 + 要求
    `REDLINE-<id>` 集成测试存在，二者缺一即 blocker；并把 hardness 普查写进
    detail，禁止材料层把 soft 告警写成"已阻断"。
    """
    try:
        from . import redlines as RL

        # 红线接线是**代码属性**，不是产物目录属性：G8 必须在 adt 包自身所在根上探测，
        # 否则 `RG.check(临时产物目录)` 会把"接线良好"误判成"未接线"
        # （test_snapshot / test_red_lines_v41 各踩过一次）。
        # C04 / 外审 C V1：必须检查**目标制品 root**，不能检查运行中的 adt 包自身，
        # 否则空 root 下 G8 仍 True（self-attestation）。root 不含源码即判未接线。
        ok, st, bad = RL.all_wired(root)
        census = RL.hardness_census(root)
        not_executed = [
            k for k, v in st.items() if v.get("test_evidence") != "executed"
        ]
        if not_executed:
            return _item(
                "G8_red_lines",
                False,
                "blocker",
                "红线集成测试证据非 executed：%s" % ", ".join(not_executed),
                "G8 只采信 subprocess 真跑的 pytest 节点；static_only 不得放行",
            )
    except Exception as exc:  # 导入失败本身即红线未落地
        return _item(
            "G8_red_lines",
            False,
            "blocker",
            "红线接线自检不可用：%s" % exc,
            "修复 adt/redlines.py",
        )
    if not ok:
        return _item(
            "G8_red_lines",
            False,
            "blocker",
            "红线未接线：%s"
            % "; ".join(
                "%s(%s)" % (k, st[k]["missing"] or st[k]["test_why"]) for k in bad[:4]
            ),
            "在 cli 生产路径调用该守卫，并在 tests/test_redline_wiring.py 加集成用例",
        )
    return _item(
        "G8_red_lines",
        True,
        "info",
        "九条红线均已接线 %d/%d（%s）；硬度普查：%d hard / %d soft / %d conditional"
        % (
            len(st) - len(bad),
            len(st),
            ", ".join(sorted(st)),
            census["by_hardness"].get("hard", 0),
            census["by_hardness"].get("soft", 0),
            census["by_hardness"].get("conditional", 0),
        ),
    )


def _find_prereg_ledger(root):
    """找预注册哈希链（P2.1）。多路径兜底，找不到返回 None。"""
    import glob

    cands = [
        os.path.join(root, "prereg", "prereg.jsonl"),
        os.path.join(root, "prereg", "PREREG.jsonl"),
        os.path.join(root, "references", "prereg_ledger.jsonl"),
    ]
    cands += sorted(glob.glob(os.path.join(root, "prereg", "*.jsonl")))
    for p in cands:
        if os.path.isfile(p):
            return p
    return None


def _check_anchor(root):
    """R28/R32 + P2.1：没有第三方锚定的预注册不得带 v4.0（非 dev）标签。

    2026-11-03 升级（P2.1-b）：此前只看 `-dev` 后缀——**改个数字就能过门**。
    现在去掉 `-dev` 还必须满足：存在预注册链，且 `anchor_status()['claim_allowed']`
    为 True（即真的第三方锚定过）。锚定链缺失 → 仍然 blocker。
    """
    skill = os.path.join(root, "SKILL.md")
    ver = ""
    if os.path.isfile(skill):
        for line in _read(skill).split("\n"):
            if line.strip().startswith("version:"):
                ver = line.split(":", 1)[1].strip()
                break
    if not ver:
        return _item(
            "G9_label_granting",
            True,
            "info",
            "未找到 SKILL.md version 声明：跳过标签门（无法判定则不强判）",
        )
    # 2026-11-04 / C03、外审 C V8：删除「-dev 零成本通行券」。
    # 旧实现见 -dev 即 info 直通，使 4.0-dev 成为绕过全部预注册检查的通道。
    # 现在 -dev 只表示「允许存在未锚定状态」，且必须显式降级为 warn。
    if ver.endswith("-dev"):
        ledger_dev = _find_prereg_ledger(root)
        if ledger_dev is None:
            return _item(
                "G9_label_granting",
                True,
                "warn",
                "版本 %s 为 -dev 且无预注册锚定链：当前全部结论为回溯性，"
                "外部前瞻/第三方复现/预注册锚定均未满足；禁止声称前瞻或"
                "作为可复现包范本推广（见 SKILL.md 状态横幅）" % ver,
                "按 SAP_FROZEN.yaml 完成 T0 冻结与第三方存证后再授予标签",
            )
        try:
            from .prereg import Prereg

            st_dev = Prereg(ledger_dev).anchor_status()
        except Exception as exc:
            return _item(
                "G9_label_granting",
                False,
                "blocker",
                "预注册链不可读（%s）：%s" % (ledger_dev, exc),
                "修复链路",
            )
        if st_dev.get("post_hoc_anchor") or not st_dev.get("claim_allowed"):
            return _item(
                "G9_label_granting",
                True,
                "warn",
                "版本 %s 为 -dev；锚定状态 post_hoc=%s / claim_allowed=%s，"
                "不得声称前瞻（外审 C V3：post_hoc 不产生前瞻证据）"
                % (ver, st_dev.get("post_hoc_anchor"), st_dev.get("claim_allowed")),
            )
        return _item(
            "G9_label_granting",
            True,
            "warn",
            "版本 %s 仍为 -dev（未授予正式标签），锚定 deposited_at=%s；"
            "发布档须显式确认" % (ver, st_dev.get("deposited_at")),
        )

    ledger = _find_prereg_ledger(root)
    if ledger is None:
        return _item(
            "G9_label_granting",
            False,
            "blocker",
            "版本 %s 未带 -dev，但找不到预注册哈希链（prereg/*.jsonl）——"
            "无法证明标准先于数据" % ver,
            "用 adt.prereg.Prereg 登记标准并 attach_anchor(doi/url)，"
            "或把版本改回 -dev",
        )
    try:
        from .prereg import Prereg

        st = Prereg(ledger).anchor_status()
    except Exception as exc:
        return _item(
            "G9_label_granting",
            False,
            "blocker",
            "预注册链不可读（%s）：%s" % (ledger, exc),
            "修复链路或恢复 -dev",
        )
    if not st.get("claim_allowed"):
        return _item(
            "G9_label_granting",
            False,
            "blocker",
            "版本 %s 未带 -dev，但锚定未完成（%s）" % (ver, st.get("warning", "")[:80]),
            "先完成第三方锚定（见 references/PREREG_ANCHORING_CHECKLIST.md）",
        )
    if st.get("post_hoc_anchor"):
        return _item(
            "G9_label_granting",
            False,
            "blocker",
            "版本 %s 的锚定**晚于**标准登记（post_hoc）：第三方时间戳只证明"
            "文件提交时刻，不证明提交时未看过数据；claim_allowed 必须为 False，"
            "不得据此授予前瞻/预注册标签（外审 A/C、D08/P6）" % ver,
            "改投 Results-blind review / Registered Replication，或针对 T0 后新数据重做 RR",
        )
    return _item(
        "G9_label_granting",
        True,
        "info",
        "版本 %s 已第三方锚定（registry=%s doi=%s）"
        % (ver, st.get("registry"), st.get("doi")),
    )


def _check_claims_registry(root):
    """G10（第三轮评审 §B 制度化）：标 ✅ 必须附产物路径 + 数字，且数字真的在产物里。

    为什么是 blocker：空心 ✅ 是本包已发生过的事实事故（R14/R19/R20 标 ✅ 但
    `out_gate/`、`out_p8/` 从未生成）。规则留在文档里就会被绕过，因此做成门禁。
    """
    from . import claims_audit

    path = os.path.join(root, "references", "CLAIMS_REGISTRY.yaml")
    if not os.path.isfile(path):
        return _item(
            "G10_claims_registry",
            False,
            "blocker",
            "缺 references/CLAIMS_REGISTRY.yaml：数字主张无产物级凭证",
            "建立登记表并把每条数字绑到产物路径 + 字面量",
        )
    res = claims_audit.verify_registry(path)
    if not res["passed"]:
        return _item(
            "G10_claims_registry",
            False,
            "blocker",
            "主张登记表 %d/%d 条失败：%s"
            % (
                res["n_failed"],
                res["n_entries"],
                "; ".join("%s:%s" % (f["id"], f["why"]) for f in res["failures"][:3]),
            ),
            "补齐产物或改正字面量；不得用四舍五入后的数字充数",
        )
    # C3 / 外审 C V3（2026-11-04）：字面量命中只证明「这个数字出现在某个文件里」，
    # 不等于「该主张被结构化验证」。必须把字段级结果显式摊在门禁上：
    #   structured>0 才算真证据；literal_only 一律 warn，禁止用 OK(info) 冒充通过。
    try:
        fa = (
            claims_audit.verify_registry_fields(path)
            if hasattr(claims_audit, "verify_registry_fields")
            else None
        )
    except Exception:  # 审计器自身故障不得静默通过
        fa = None
    if fa is None:
        return _item(
            "G10_claims_registry",
            True,
            "warn",
            "主张登记表 %d/%d 条字面量通过，但字段级审计不可用"
            "（不得据此声称证据链完整）" % (res["n_verified"], res["n_entries"]),
            "运行 `python -m adt.claims_audit --strict-fields` 修好审计器",
        )
    n_struct = fa["n_field_matched"]
    n_adm = fa["n_entries"] - fa["n_retracted"]
    ratio = (n_struct / float(n_adm)) if n_adm else 0.0
    detail = (
        "主张 %d/%d 字面量通过；字段级：structured=%d/%d admissible / "
        "literal_only=%d / mismatch=%d (ratio=%.2f)"
        % (
            res["n_verified"],
            res["n_entries"],
            n_struct,
            n_adm,
            fa["n_field_unresolved"],
            fa["n_field_failed"],
            ratio,
        )
    )
    if fa["n_field_failed"]:
        return _item(
            "G10_claims_registry",
            False,
            "blocker",
            detail,
            "字段级 mismatch 说明产物中的数字与主张不符，必须改主张或改产物",
        )
    if n_struct == 0:
        return _item(
            "G10_claims_registry",
            True,
            "warn",
            detail,
            "全部主张仅字面量命中（literal_only）：只证明数字出现在文件里，"
            "不构成结构化证据链；须逐条补 expect_field_path 并绑定 JSON 字段",
        )
    # 2026-11-18 硬化：field evidence ratio < 0.8 在 strict（发表档）下阻断。
    # 本轮已补全至 25/25=1.00；阈值 0.8 给后续新增主张留 20% 未绑定缓冲，
    # 一旦退化到 <80% 即在 `release-check --strict` 下失败，防止"字面量通过"冒充证据链。
    if ratio < 0.8:
        return _item(
            "G10_claims_registry",
            True,
            "warn",
            detail,
            "字段级证据覆盖 %d/%d < 80%%，strict 发表档将阻断；"
            "补 expect_field_path / expect_code_symbol" % (n_struct, n_adm),
        )
    return _item("G10_claims_registry", True, "info", detail)


def _check_negative_defaults(root):
    """G11（第三轮评审 §E4）：负结果必须进默认配置，且默认值带产物级证据。"""
    from . import defaults

    # C04 / 外审 C V1：改为检查目标制品 root，不读运行中包内的 defaults.YAML_PATH。
    yaml_path = os.path.join(root, "references", "NEGATIVE_RESULT_DEFAULTS.yaml")
    if not os.path.isfile(yaml_path):
        return _item(
            "G11_negative_result_defaults",
            False,
            "blocker",
            "缺 references/NEGATIVE_RESULT_DEFAULTS.yaml（目标 root=%s）" % root,
            "把每条负结果落成一个默认值并绑证据",
        )
    res = defaults.assert_consistent(yaml_path)
    if res["ok"]:
        return _item(
            "G11_negative_result_defaults",
            True,
            "info",
            "%d 条负结果全部落成默认值，证据 %d 条核对通过"
            % (res["n_entries"], res["n_evidence_verified"]),
        )
    detail = []
    if res["mismatches"]:
        detail.append(
            "yaml/代码不一致：%s"
            % "; ".join(
                "%s(yaml=%r,code=%r)" % (m["key"], m["yaml"], m["code"])
                for m in res["mismatches"][:3]
            )
        )
    if res["evidence_failures"]:
        detail.append(
            "证据失败：%s"
            % "; ".join(
                "%s(%s)" % (f["key"], f["why"]) for f in res["evidence_failures"][:3]
            )
        )
    if not detail:
        detail.append(
            "条目数 %d 与代码默认值数 %d 不等"
            % (res["n_entries"], res["n_defaults_in_code"])
        )
    return _item(
        "G11_negative_result_defaults",
        False,
        "blocker",
        "；".join(detail),
        "同步 yaml 与 adt/defaults.py，并补产物证据",
    )


def _check_threshold_freeze(root):
    """G12（次轮 A8 / 第三轮 §E4）：阈值漂移为阻断项，未冻结/无敏感性为告警项。"""
    from . import threshold_audit

    res = threshold_audit.audit(
        os.path.join(root, "references", "THRESHOLD_REGISTRY.yaml")
    )
    if not res.get("exists"):
        return _item(
            "G12_threshold_freeze",
            False,
            "blocker",
            "缺 references/THRESHOLD_REGISTRY.yaml：阈值来历无登记",
            "登记阈值 + 冻结状态 + 敏感性证据",
        )
    if res["drift"]:
        return _item(
            "G12_threshold_freeze",
            False,
            "blocker",
            "阈值漂移：%s"
            % "; ".join(
                "%s(登记 %r 未见于 %s)"
                % (
                    d["id"],
                    d["value_token"],
                    d["token_not_found_in"] or d["missing_files"],
                )
                for d in res["drift"][:3]
            ),
            "同步代码与登记表；不得单方面改阈值",
        )
    soft = [g for g in res["gaps"] if g["kind"] != "literature_without_citation"]
    if soft:
        return _item(
            "G12_threshold_freeze",
            True,
            "warn",
            "%d/%d 条阈值已冻结；告警 %d 项（%s）"
            % (
                res["n_frozen"],
                res["n_thresholds"],
                len(soft),
                "; ".join("%s:%s" % (g["id"], g["kind"]) for g in soft[:3]),
            ),
        )
    return _item(
        "G12_threshold_freeze",
        True,
        "ok",
        "%d 条阈值无漂移、全部冻结、来历 %s" % (res["n_thresholds"], res["census"]),
    )


def _check_estimand(root):
    """G13（2026-11-17 同行评审七寸修复）：端点 estimand 绑定门。

    C01 撤回的前置条件是 references/ENDPOINT_ESTIMAND_CARDS.yaml 存在且被接线。
    此前该卡从未创建（RETRACTION_NOTE 明列但仓库缺失）。本门：
      ① 卡存在且可解析；② 内置自检（跨量纲必拦、合法比较放行）；
      ③ 真实 C01 产物若存在，必须如实标 inference_revoked + cross_dim invalid。
    任一失败即 blocker：未绑定 estimand 的结论不得对外。
    """
    from . import estimand

    card = os.path.join(root, "references", "ENDPOINT_ESTIMAND_CARDS.yaml")
    if not os.path.isfile(card):
        return _item(
            "G13_estimand_binding",
            False,
            "blocker",
            "缺 references/ENDPOINT_ESTIMAND_CARDS.yaml：C01 撤回的前置条件未满足",
            "创建端点 estimand 绑定卡（金标准/量纲/基线/合法比较）",
        )
    try:
        ok, rows = estimand.selftest()
    except Exception as exc:
        return _item(
            "G13_estimand_binding",
            False,
            "blocker",
            "estimand 自检异常：%s" % exc,
            "修复 adt/estimand.py",
        )
    if not ok:
        bad = [r["name"] for r in rows if not r["ok"]]
        return _item(
            "G13_estimand_binding",
            False,
            "blocker",
            "estimand 自检失败：%s" % ", ".join(bad),
            "修复跨量纲/绑定判据",
        )
    # 真实 C01 产物一致性
    art = os.path.join(root, "out_ext", "external", "external_cuts_summary_v2.json")
    audit_note = "; C01 产物一致性已验"
    if os.path.isfile(art):
        try:
            r = estimand.audit_artifact(art)
            if r["verdict"] == "BLOCK":
                return _item(
                    "G13_estimand_binding",
                    False,
                    "blocker",
                    "C01 产物 estimand 声明不自洽：%s" % r["reason"],
                    "产物须标 inference_revoked + cross_dim invalid",
                )
        except Exception as exc:
            return _item(
                "G13_estimand_binding",
                False,
                "blocker",
                "C01 产物审计异常：%s" % exc,
                "检查产物 JSON",
            )
    else:
        audit_note = "; C01 产物缺失（仅自检）"
    n_ep = len((estimand.load_cards().get("endpoints") or {}))
    return _item(
        "G13_estimand_binding",
        True,
        "ok",
        "estimand 卡 %d 端点、跨量纲自检 %d/%d 通过%s"
        % (n_ep, len(rows), len(rows), audit_note),
    )


def _check_external_comparison(root):
    """G14（2026-11-19，技能市场 round 后自查）：统计量外部对照台账门。

    三轮事故的共同结构是"selftest 与实现同源，模型错则两边一起错"：
      R1 t 分布 df 用 n；R1 Holm 回填错位（结论颠倒）；R2 OOT 基线含待检尾部（漏报）。
    本门的判据是"有没有另一个来源的实现"，不是"有没有再写一遍 selftest"：
      ① 台账存在且可解析；② `required_modules`（棘轮）全部被 entries 覆盖；
      ③ 每条挂对照脚本 / 独立审查报告 / 回归测试节点，且文件与测试名真实存在；
      ④ **实跑** adt.external_comparison.run()，逐条比对实测偏差 ≤ 台账声明容差
         —— 不采信台账里的数字自述，避免"台账写 0、代码已漂移"。
    任一失败即 blocker：无外部对照的统计量不得进发布。
    """
    import yaml

    path = os.path.join(root, "references", "EXTERNAL_COMPARISON_LEDGER.yaml")
    if not os.path.isfile(path):
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "缺 references/EXTERNAL_COMPARISON_LEDGER.yaml："
            "统计量外部对照纪律未成账",
            "按三轮事故（df/Holm/OOT）建台账并挂对照脚本与审查报告",
        )
    try:
        led = yaml.safe_load(_read(path)) or {}
    except Exception as exc:
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "台账不可解析：%s" % exc,
            "修复 YAML",
        )

    entries = led.get("entries") or []
    required = led.get("required_modules") or []
    if not entries or not required:
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "台账缺 entries 或 required_modules",
            "补齐台账",
        )

    problems = []
    covered = {str(e.get("module") or "") for e in entries}
    missing = [m for m in required if m not in covered]
    if missing:
        problems.append("棘轮未覆盖：%s" % ", ".join(missing))

    for e in entries:
        name = e.get("module") or "<未命名>"
        for key in (
            "statistic",
            "reference",
            "comparison_script",
            "review_report",
            "regression_test",
            "tolerance",
        ):
            if e.get(key) in (None, ""):
                problems.append("%s 缺字段 %s" % (name, key))
        cs = e.get("comparison_script")
        if cs and not os.path.isfile(os.path.join(root, cs)):
            problems.append("%s 的对照脚本不存在：%s" % (name, cs))
        rr = e.get("review_report")
        if rr and not os.path.isfile(os.path.join(root, rr)):
            problems.append("%s 的独立审查报告不存在：%s" % (name, rr))
        rt = str(e.get("regression_test") or "")
        if "::" in rt:
            f, tname = rt.split("::", 1)
            fp = os.path.join(root, f)
            if not os.path.isfile(fp):
                problems.append("%s 的回归测试文件不存在：%s" % (name, f))
            elif ("def %s(" % tname) not in _read(fp):
                problems.append("%s 的回归测试节点不存在：%s" % (name, rt))

    if problems:
        head = "; ".join(problems[:4])
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "台账不合规（%d 项）：%s" % (len(problems), head),
            "补齐脚本/报告/测试节点，或把模块移入不得发布的清单",
        )

    from . import external_comparison

    try:
        r = external_comparison.run()
    except Exception as exc:
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "外部对照执行异常：%s" % exc,
            "修复 adt/external_comparison.py",
        )

    # 实测偏差 vs 台账声明容差（同一 module 键对齐）
    declared = {str(e.get("module")): float(e.get("tolerance")) for e in entries}
    drift = []
    for got in r["entries"]:
        if got["skipped"]:
            continue
        tol = declared.get(got["module"])
        if tol is None:
            drift.append("%s 未在台账声明" % got["module"])
        elif got["max_abs_deviation"] > tol + 1e-15:
            drift.append(
                "%s 实测 %.3g > 容忍 %.3g"
                % (got["module"], got["max_abs_deviation"], tol)
            )
    if drift:
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "外部对照超容差：%s" % "; ".join(drift[:4]),
            "实现已漂移：修实现或（若参考实现有误）改参考并记录理由",
        )
    if not r["all_passed"]:
        bad = [e["module"] for e in r["entries"] if not e["passed"]]
        return _item(
            "G14_external_comparison",
            False,
            "blocker",
            "对照未全通过：%s" % ", ".join(bad),
            "逐条排查偏差来源",
        )

    skipped = r["skipped"]
    detail = "%d 模块 / %d 对照点全部通过（实测最大偏差 %.1e）" % (
        len(r["entries"]),
        r["n_points"],
        max((e["max_abs_deviation"] or 0.0) for e in r["entries"]),
    )
    if skipped:
        # 无 scipy 的环境不能硬拦（离线可用性是既有设计目标），但必须显式降级
        return _item(
            "G14_external_comparison",
            False,
            "warn",
            detail
            + "；%d 条降级跳过（缺 scipy）：%s" % (len(skipped), ", ".join(skipped)),
            "装上 scipy 后复跑；跳过项不得对外声称已对照",
        )
    return _item("G14_external_comparison", True, "ok", detail)


def check(root=".", include_dag=True, strict=False):
    """发布门禁。

    strict=True（T3 发表档）：warn 不得归一成 ok 且必须进机器可读 warnings[]，
    并**一并阻断发布**（§7.1 第十条硬约束）。
    """
    items = [
        _check_lock(root),
        _check_snapshots(root),
        _check_contract(root),
        _check_envfp(root),
        _check_manifest(root),
        _check_container(root),
    ]
    if include_dag:
        items.append(_check_dag(root))
    items.append(_check_red_lines(root))
    items.append(_check_anchor(root))
    items.append(_check_claims_registry(root))
    items.append(_check_negative_defaults(root))
    items.append(_check_threshold_freeze(root))
    items.append(_check_estimand(root))
    items.append(_check_external_comparison(root))
    blockers = [i for i in items if i["level"] == "blocker" and not i["ok"]]
    # 第二重抹除修复：level==warn 无论 ok 都要进 warnings[]
    warns = [i for i in items if i["level"] == "warn"]
    if strict:
        blockers = blockers + [i for i in warns if i not in blockers]
    return {
        "passed": not blockers,
        "strict": bool(strict),
        "items": items,
        "blockers": [i["key"] for i in blockers],
        "warnings": [i["key"] for i in warns],
        "warnings_detail": [
            dict(key=i["key"], detail=i["detail"], fix=i["fix"]) for i in warns
        ],
    }
