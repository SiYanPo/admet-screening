# -*- coding: utf-8 -*-
"""盲区2：语义脱衣防御（Semantic Stripping）— 物理水印 + 词汇强制替换。

核心认知：不能"阻止"用户把文本复制到 PPT，但可以让**复制后的任何片段**
都无法被伪装成高可信结论：
  1. 词汇层：结论词由 tier 决定，T0 只能生成"初步提示/方向未定"，
     "无异常/安全/通过/PASS"在结构上不可出现在 T0 输出中。
  2. 水印层：SDF/Markdown/JSON 均带 HMAC 封印与零宽不可见标签；
     校验失败一律降级为 T0_STRIPPED（fail-closed，绝不升级）。
  3. 冗余层：可见级别标签 [T0] + 零宽标签 + 机器封印，三重冗余；
     剥离任意一层，剩余层仍把结论钉在原级别。

生产部署：HMAC 密钥必须放 KMS/HSM 并按季度轮换；原型用演示密钥，
只验证机制，不提供真实防篡改强度（报告中明说此边界）。
"""

from __future__ import annotations

import hashlib
import hmac
import json

# 演示密钥；生产：从 KMS 取，绝不随代码分发
DEMO_KEY = b"admet-compliance-demo-key-2026-11"

ZW0, ZW1, ZWSEP = "\u200b", "\u200c", "\u200d"

CLASS_CODES = {
    "UNDETERMINED": "T0",
    "T0_EXPLORATORY": "T0",
    "T1_EXPLORATORY": "T1",
    "T2_DECISION_SUPPORT": "T2",
    "T3_PUBLICATION": "T3",
}

# 每一档的**唯一合法结论句**：下游无论怎么截取，都不会超过本档语义
CONCLUSION = {
    "T0": "初步提示：证据不足、方向未定，需人工复核（探索级，不构成风险判断）",
    "T1": "探索级方向提示：仅供筛选排序参考，须 Rigorous 或湿实验确认",
    "T2": "项目决策级提示：多源方向一致时可作内部决策依据，非论文定论",
    "T3": "可申报级提示：仅限已附实测与独立基准的既定结论范围",
    "T0_STRIPPED": "合规校验失败：结论已被剥离/篡改，按最低可信级处理，禁止引用",
}

# 高风险词：低档输出中严禁出现；出现即视为语义越级
RESERVED_HIGHER = {
    "T0": (
        "无异常",
        "安全",
        "无毒",
        "低风险",
        "风险较低",
        "通过验证",
        "可放心",
        "已确证",
        "PASS",
        "safe",
        "no risk",
        "proven",
        "approved",
    ),
    "T1": ("无异常", "安全", "已确证", "论文级", "可放心", "PASS", "safe", "proven"),
    "T2": ("已确证", "论文级", "可放心", "proven", "完全安全"),
}

# 强制替换表：用户/LLM 传入的越级词被替换为同级合法表达
FORCED_REPLACEMENTS = (
    ("无异常", "初步提示未见明确异常信号（探索级，需复核）"),
    ("无风险", "证据不足，不能判定为无风险（探索级）"),
    ("风险较低", "方向提示偏弱，证据不足以下定论（探索级）"),
    ("低风险", "未见支持定论的风险分级证据（探索级）"),
    ("安全", "证据不足，不能给出耐受性结论（探索级）"),
    ("通过验证", "尚未完成验证（探索级）"),
    ("已确证", "尚未确证（需 Rigorous / 湿实验）"),
    ("PASS", "探索级方向提示（非定论）"),
    ("可推进", "需补充证据后再决策（探索级）"),
    ("safe", "not established (exploratory only)"),
    ("no risk", "no conclusive risk assessment available (exploratory)"),
)
LIFT_WORDS = ("T0", "T1", "T2", "T3", "合规", "decision_support", "publication")


def _zw_encode(payload: str) -> str:
    bits = "".join(format(b, "08b") for b in payload.encode("utf-8"))
    return ZWSEP + "".join(ZW1 if c == "1" else ZW0 for c in bits) + ZWSEP


def _zw_decode(text: str) -> str:
    if ZWSEP not in text:
        return ""
    parts = text.split(ZWSEP)
    if len(parts) < 2:
        return ""
    frag = parts[1]
    bits = "".join("1" if c == ZW1 else "0" for c in frag if c in (ZW0, ZW1))
    if len(bits) % 8:
        return ""
    try:
        return bytes(int(bits[i : i + 8], 2) for i in range(0, len(bits), 8)).decode(
            "utf-8"
        )
    except UnicodeDecodeError:
        return ""


def decision_class_of(record: dict) -> str:
    """从裁决记录推导**最高**允许的合规级别（只降不升）。"""
    verdict = str(record.get("verdict", "UNDETERMINED")).upper()
    tier = str(record.get("tier_ceiling", "")).upper()
    if (
        verdict in ("UNDETERMINED", "PASSTHRU")
        or tier == "T0"
        or record.get("certainty_modifier") == "low_unresolvable"
        or record.get("reason") == "data_inconsistent"
        or record.get("partial_execution") is True
    ):
        return "T0_EXPLORATORY"
    if tier == "T1" or record.get("mode") == "fast":
        return "T1_EXPLORATORY"
    if tier == "T3" and record.get("measured_evidence"):
        return "T3_PUBLICATION"
    if tier in ("T2", "T3"):
        return "T2_DECISION_SUPPORT"
    return "T0_EXPLORATORY"


class ComplianceSeal:
    def __init__(self, key=None):
        self.key = key or DEMO_KEY

    def _mac(self, payload: dict) -> str:
        body = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def seal(self, record: dict, *, endpoint=None) -> dict:
        dc = decision_class_of(record)
        code = CLASS_CODES[dc]
        payload = {
            "decision_class": dc,
            "verdict": record.get("verdict", "UNDETERMINED"),
            "tier_ceiling": record.get("tier_ceiling", "T0"),
            "inchikey": record.get("inchikey"),
            "endpoint": endpoint or record.get("endpoint"),
        }
        mac = self._mac(payload)
        tag_payload = "%s|%s" % (code, mac[:8])
        return {
            "decision_class": dc,
            "code": code,
            "verdict": payload["verdict"],
            "tier_ceiling": payload["tier_ceiling"],
            "inchikey": payload["inchikey"],
            "endpoint": payload["endpoint"],
            "mac": mac,
            "invisible_tag": _zw_encode(tag_payload),
            "visible_tag": "[%s]" % code,
            "conclusion": CONCLUSION[code],
            "payload_digest": hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16],
        }

    def verify(self, envelope: dict) -> dict:
        """校验封印。任何缺失/不符 → T0_STRIPPED（fail-closed）。"""
        need = ("decision_class", "code", "mac", "invisible_tag", "payload_digest")
        missing = [k for k in need if not envelope.get(k)]
        if missing:
            return {
                "ok": False,
                "status": "STRIPPED",
                "missing": missing,
                "effective_class": "T0_STRIPPED",
            }
        dc = envelope["decision_class"]
        expected_code = CLASS_CODES.get(dc)
        if expected_code is None or expected_code != envelope["code"]:
            return {
                "ok": False,
                "status": "CLASS_TAMPERED",
                "effective_class": "T0_STRIPPED",
            }
        payload = {
            "decision_class": dc,
            "verdict": envelope.get("verdict", "UNDETERMINED"),
            "tier_ceiling": envelope.get("tier_ceiling", "T0"),
            "inchikey": envelope.get("inchikey"),
            "endpoint": envelope.get("endpoint"),
        }
        mac_ok = hmac.compare_digest(self._mac(payload), str(envelope["mac"]))
        tag = _zw_decode(str(envelope["invisible_tag"]))
        tag_ok = tag == "%s|%s" % (expected_code, str(envelope["mac"])[:8])
        digest_ok = hmac.compare_digest(
            hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16],
            str(envelope["payload_digest"]),
        )
        ok = mac_ok and tag_ok and digest_ok
        return {
            "ok": ok,
            "status": "OK" if ok else "TAMPERED",
            "checks": {"mac": mac_ok, "invisible_tag": tag_ok, "digest": digest_ok},
            "effective_class": dc if ok else "T0_STRIPPED",
        }

    # ---------- 输出层 ----------
    def render_json(self, record: dict, *, endpoint=None) -> str:
        env = self.seal(record, endpoint=endpoint)
        return json.dumps(
            {"compliance_envelope": env, "record": record}, ensure_ascii=False, indent=2
        )

    def render_markdown(self, record: dict, *, endpoint=None, extra="") -> str:
        env = self.seal(record, endpoint=endpoint)
        lines = [
            "# ADMET 判定报告",
            "",
            "%s 判定级别：%s%s"
            % (env["visible_tag"], env["decision_class"], env["invisible_tag"]),
            "",
            "**结论：%s %s**" % (env["visible_tag"], env["conclusion"]),
            "",
            "| 字段 | 值 |",
            "| --- | --- |",
            "| verdict | %s |" % env["verdict"],
            "| tier_ceiling | %s |" % env["tier_ceiling"],
            "| endpoint | %s |" % (env["endpoint"] or "未指定"),
            "| inchikey | %s |" % (env["inchikey"] or "未提供"),
            "| 载荷指纹 | %s |" % env["payload_digest"],
            "| 封印 HMAC | %s |" % env["mac"],
            "",
            "> 合规声明：本结论的措辞与级别由确定性模板生成，禁止手工提升；"
            "复制时请连同级别标签与封印一并引用。",
        ]
        if extra:
            lines += ["", extra]
        return "\n".join(lines)

    def render_sdf(self, record: dict, *, endpoint=None, molblock=None) -> str:
        env = self.seal(record, endpoint=endpoint)
        title = "ADMET_%s_%s%s" % (env["code"], env["mac"][:8], env["invisible_tag"])
        block = molblock or (
            "  Mrv ADMET placeholder\n\n  1  0  0  0  0  0            999 V2000\n"
            "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
            "M  END\n"
        )
        props = [
            ("COMPLIANCE_LEVEL", env["decision_class"]),
            ("DECISION_CODE", env["code"]),
            ("TIER_CEILING", env["tier_ceiling"]),
            ("VERDICT", env["verdict"]),
            ("WM_HMAC", env["mac"]),
            ("WM_PAYLOAD_DIGEST", env["payload_digest"]),
            ("WM_INVISIBLE", env["invisible_tag"]),
            ("CONCLUSION_LOCKED", env["conclusion"]),
            ("ENDPOINT", str(env["endpoint"] or "")),
            ("INCHIKEY", str(env["inchikey"] or "")),
        ]
        out = [title, block.rstrip("\n"), ""]
        for k, v in props:
            out.append("> <%s>" % k)
            out.append(v)
            out.append("")
        out.append("$$$$")
        return "\n".join(out)

    def verify_output(self, text: str, *, fmt="markdown") -> dict:
        """从输出文本反解封印并校验；不合法 → T0_STRIPPED。"""
        env = {}
        if fmt == "json":
            try:
                env = json.loads(text).get("compliance_envelope", {})
            except Exception:
                env = {}
        elif fmt == "sdf":
            lines = text.splitlines()
            for i, line in enumerate(lines):
                m = line.strip()
                if m.startswith("> <") and m.endswith(">"):
                    key = m[3:-1]
                    val = lines[i + 1] if i + 1 < len(lines) else ""
                    env[key] = val if key == "WM_INVISIBLE" else val.strip()
            # 零宽标签：优先用属性原始值，其次从 title 恢复
            if env.get("WM_INVISIBLE"):
                env["invisible_tag"] = env["WM_INVISIBLE"]
            else:
                env["invisible_tag"] = lines[0] if lines else ""
            if env.get("COMPLIANCE_LEVEL"):
                env["decision_class"] = env["COMPLIANCE_LEVEL"]
            for src, dst in (
                ("DECISION_CODE", "code"),
                ("WM_HMAC", "mac"),
                ("WM_PAYLOAD_DIGEST", "payload_digest"),
                ("TIER_CEILING", "tier_ceiling"),
                ("VERDICT", "verdict"),
                ("INCHIKEY", "inchikey"),
                ("ENDPOINT", "endpoint"),
            ):
                if src in env:
                    env[dst] = env[src] or None
        else:
            if "判定级别：" in text:
                seg = text.split("判定级别：", 1)[1].split("\n", 1)[0]
                seg = (
                    seg.replace("\u200b", "")
                    .replace("\u200c", "")
                    .replace("\u200d", "")
                )
                parts = seg.strip().split()
                if parts:
                    env["decision_class"] = parts[0]
                    env["code"] = CLASS_CODES.get(parts[0], "")
            env["invisible_tag"] = text
            for label, key in (
                ("verdict", "verdict"),
                ("tier_ceiling", "tier_ceiling"),
                ("endpoint", "endpoint"),
                ("inchikey", "inchikey"),
                ("封印 HMAC", "mac"),
            ):
                marker = "| %s |" % label
                if marker in text:
                    val = text.split(marker, 1)[1].split("|", 1)[0].strip()
                    env[key] = val or None
            m = [ln for ln in text.splitlines() if "载荷指纹 |" in ln]
            if m:
                frag = [p.strip() for p in m[0].split("|") if p.strip()]
                env["payload_digest"] = frag[-1] if frag else ""
                decoded = _zw_decode(text)
                if "|" in decoded and not env.get("mac"):
                    env["mac"] = decoded.split("|", 1)[1]
        res = self.verify(env)
        res["format"] = fmt
        return res


def sanitize_for_tier(text: str, record: dict, *, seal=None) -> dict:
    """对用户/LLM 提供的自由文本做强制词汇替换（越级词一律降级表达）。"""
    seal = seal or ComplianceSeal()
    dc = decision_class_of(record)
    code = CLASS_CODES[dc]
    out = str(text)
    applied = []
    for bad, good in FORCED_REPLACEMENTS:
        if bad in out:
            out = out.replace(bad, good)
            applied.append(bad)
    hits = [w for w in RESERVED_HIGHER.get(code, ()) if w in out]
    # 二次兜底：替换后仍命中保留词 → 整段丢弃，只留同级确定性结论
    if hits:
        out = CONCLUSION[code]
        applied.append("__FALLBACK_TO_LOCKED_CONCLUSION__")
    return {
        "text": out,
        "decision_class": dc,
        "code": code,
        "replaced": applied,
        "residual_forbidden": hits,
        "locked_conclusion": CONCLUSION[code],
    }


def classify_copy(text: str) -> dict:
    """对**已被复制/剥离上下文**的片段做独立风险评级。

    返回 max_claimable_class：片段中若出现越级词则标 SUSPICIOUS，
    绝不会因为删掉水印而自动升级。
    """
    low = str(text)
    suspicious = []
    for code, words in RESERVED_HIGHER.items():
        for w in words:
            if w in low and code in ("T0", "T1"):
                suspicious.append("%s:%s" % (code, w))
    has_locked = any(c in low for c in CONCLUSION.values())
    has_visible = any(("[%s]" % c) in low for c in ("T0", "T1", "T2", "T3"))
    has_invisible = _zw_decode(low) != ""
    return {
        "suspicious_terms": sorted(set(suspicious)),
        "has_locked_conclusion": has_locked,
        "has_visible_tag": has_visible,
        "has_invisible_tag": has_invisible,
        "max_claimable_class": "T0" if (suspicious or has_locked) else "UNVERIFIED",
        "note": "复制片段永远不能凭空升档；无封印片段不得用于正式决策",
    }
