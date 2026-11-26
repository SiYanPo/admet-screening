# -*- coding: utf-8 -*-
"""合规模块（R23 / A12 + R24 / S6 + R25 / R2-3）：把"许可提醒"变成"代码级隔离"。

评审 C12 原话："没有按使用场景分级的合规决策树……CC-BY-NC 源的程序化批量调用是否
触发 NC 条款，属于机构法务必须回答的问题，框架应内置'NC 源隔离开关'而非仅文字提醒。"
评审 S6 补充："合规档无法解决'用户绕过档位直接调适配器'→ 需在适配器基类做 profile 强制检查。"

因此本模块提供两层：
  1) 档位（profile）→ 允许/摘除的源清单；
  2) 适配器基类在 `run_one` 前置检查（见 adapters/base.py `enforce_profile`），
     绕过 CLI 直接实例化适配器也会被拦。

**本模块不构成法律意见**（与 ADAPTER_COMPLIANCE.md 一致）。许可事实来自该文件的联网核验。
"""

import io
import os

# 许可类别（与 references/ADAPTER_COMPLIANCE.md §3 一一对应）
LICENSE_CLASS = {
    "admet_ai": "MIT_or_web_ToS",  # 代码 MIT；公共 web server 免费无登录
    "admetlab3": "free_rate_limited",  # 免费、≤5 req/s
    "protox3": "CC-BY-NC",  # 非商业
    "chembl": "CC-BY-SA-4.0",  # 署名 + 派生同条款
    "biotransformer": "GPL-2.1",  # 商业需书面许可
    "vnn": "open_no_explicit_ToS",  # 无显式 API ToS
    "xenosite": "MANUAL_ONLY",  # SFU 条款禁止程序化访问
    "pubchem": "public_domain_ish",  # PUG REST 公开数据
    "tdc": "MIT_wrapper_data_mixed",  # 包 MIT，数据随数据集
    "npass": "CC-BY-NC",  # 非商业
    "openadmet": "CC-BY-4.0",  # 须署名
}

# 各档位**禁用**的源（程序化调用即违规或高风险）
PROFILE_BLOCK = {
    "academic-internal": set(["xenosite"]),
    "academic-shared": set(["xenosite"]),
    "pre-commercial": set(["xenosite", "protox3", "npass"]),
    "commercial": set(["xenosite", "protox3", "npass", "biotransformer", "vnn"]),
}
PROFILES = tuple(PROFILE_BLOCK)

# R25：即便档位允许，GPL/派生边界敏感的源默认关闭，需显式开启
DEFAULT_OFF = {"biotransformer": "ADT_ENABLE_BIOTRANSFORMER"}


class ComplianceError(RuntimeError):
    pass


def resolve_profile(profile=None):
    p = profile or os.environ.get("ADT_PROFILE", "academic-internal")
    if p not in PROFILE_BLOCK:
        raise ComplianceError("未知合规档位：%s（可选：%s）" % (p, ", ".join(PROFILES)))
    return p


def blocked_sources(profile=None):
    return sorted(PROFILE_BLOCK[resolve_profile(profile)])


def allowed(profile, source):
    return source not in PROFILE_BLOCK[resolve_profile(profile)]


def filter_sources(profile, sources):
    """返回 (allowed, removed, reasons)。"""
    p = resolve_profile(profile)
    ok, removed = [], []
    for s in sources:
        (ok if s not in PROFILE_BLOCK[p] else removed).append(s)
    reasons = {
        s: "license %s blocked in profile %s" % (LICENSE_CLASS.get(s, "unknown"), p)
        for s in removed
    }
    return ok, removed, reasons


def explicitly_disabled(source):
    """R25：默认关闭的源，返回所需开关的环境变量名（未开启则该源不可用）。"""
    env = DEFAULT_OFF.get(source)
    if env is None:
        return None
    return None if os.environ.get(env, "") in ("1", "true", "True") else env


def default_call_log_path():
    """合规留痕的默认绝对路径：skill 内 logs/，不再写调用方当前工作目录。

    同行评审 §5 输入缺口：`archive_call` 旧缺省写当前目录，用户在哪个目录跑
    就在哪留下文件——既不进交付包，也无法稳定归档。改为 skill 内固定位置，
    由 `ADT_CALL_LOG` 显式覆盖（测试/多租户仍可重定向）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs", "compliance_calls.jsonl")


def archive_call(source, profile=None, action="invoke", extra=None):
    """R38 红线 5：商用/准商用档位下，每次外部源调用必须留痕（可归档给法务/审稿人）。

    日志路径：`ADT_CALL_LOG` 环境变量；缺省 skill 内 `logs/compliance_calls.jsonl`。
    写失败不静默：抛出异常——"合规日志写不进去"本身就应中止调用。
    """
    import datetime
    import json

    p = resolve_profile(profile)
    line = dict(
        ts=datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        source=source,
        profile=p,
        action=action,
        license=LICENSE_CLASS.get(source, "unknown"),
        adt_version=os.environ.get("ADT_VERSION", "4.0-dev"),
    )
    if extra:
        line.update(extra)
    path = os.environ.get("ADT_CALL_LOG") or default_call_log_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def aggregate_calls(path=None):
    """同行评审 §5：每次外部源调用的聚合审计（按 源×档位×许可 计数）。

    `path=None` 时读默认留痕文件；文件不存在返回空结构而非报错——
    "从未有商用调用"是合法状态。产物可直接附在交付包给审稿人/法务核对。
    """
    import json

    path = path or os.environ.get("ADT_CALL_LOG") or default_call_log_path()
    counts = {}
    n = 0
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                key = (
                    r.get("source", "?"),
                    r.get("profile", "?"),
                    r.get("license", "unknown"),
                )
                counts["|".join(key)] = counts.get("|".join(key), 0) + 1
                n += 1
    return dict(
        path=path, n_calls=n, by_source_profile_license=dict(sorted(counts.items()))
    )


def enforce(source, profile=None):
    """适配器调用前的强制检查；不合规直接抛错（不静默降级）。"""
    p = resolve_profile(profile)
    if source in PROFILE_BLOCK[p]:
        raise ComplianceError(
            "源 %s 在档位 %s 下被禁用（许可：%s）。"
            "切换到合适档位或用 --profile 显式声明使用场景。"
            % (source, p, LICENSE_CLASS.get(source, "unknown"))
        )
    env = explicitly_disabled(source)
    if env:
        raise ComplianceError(
            "源 %s 默认关闭（%s）；如确需使用，设 %s=1 并在报告中保留调用日志。"
            % (source, LICENSE_CLASS.get(source, "unknown"), env)
        )
    if p in ("pre-commercial", "commercial"):
        archive_call(source, p)  # 红线 5：商用必须留痕
    return True


def report(profile=None):
    p = resolve_profile(profile)
    rows = []
    for src, lic in sorted(LICENSE_CLASS.items()):
        rows.append(
            {
                "source": src,
                "license": lic,
                "allowed": src not in PROFILE_BLOCK[p],
                "default_off": bool(explicitly_disabled(src)),
            }
        )
    return {
        "profile": p,
        "sources": rows,
        "blocked": sorted(PROFILE_BLOCK[p]),
        "note": "许可事实见 references/ADAPTER_COMPLIANCE.md；本模块不构成法律意见",
    }
