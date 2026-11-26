# -*- coding: utf-8 -*-
"""版本单一源（D3 修复，2026-11-17）。

## 三条轨为什么必须分开显示

历史问题：`pyproject.toml` 写 3.2.1、`SKILL.md` 写 4.0-dev、文档写 4.25、
`adt/__init__.py` 写 0.1.0 —— 四条轨互相矛盾，外部用户 `pip show` 看到 3.2.1
却被告知"这是 v4"，审稿人要"产物身份"时无从对齐。

但把四个数字改成一样是**伪造**（`references/VERSION_POLICY.yaml` 的
`policy.do_not` 明令禁止）：`4.0-dev` 的 `-dev` 是 G9 发布门禁的机器可读约束，
四条授予条件未满足就不能去掉。所以正解是**各轨标清语义 + 对外只暴露一个号**：

| 轨道 | 字段 | 语义 | 谁能改 |
|---|---|---|---|
| 对外发布号 | `__version__` | pip 元数据、wheel 名、引用写法 | 发版时改 |
| 能力等级 | `CAPABILITY_LEVEL` | G9 门禁授予状态；`-dev` = 未授予 | 仅 G9 |
| 材料修订 | `DOC_REVISION` | 文档/代码修订号，每次实质改动 +0.1 | 作者 |
| 产物身份 | manifest_sha1 + snapshot sha256 | 某个具体数字的唯一身份 | 自动 |

`adt --version` 一次打印三轨并给出引用建议，`python -m adt.version --strict`
继续做分歧台账审计（未登记分歧 exit 3）。
"""

from __future__ import annotations

# ---- 对外发布号：pip metadata / wheel 名 / 论文引用都应写这个 ----
__version__ = "0.9.0"

# ---- 能力等级：G9 四条授予条件（第三方锚定/外部复现/前瞻证据/红线硬度）未满足 ----
CAPABILITY_LEVEL = "4.0-dev"

# ---- 材料修订：本次 = D1–D9 工程修复 + doctor/summary/decision-record/translate ----
DOC_REVISION = "4.37 (2026-11-25)"

RELEASE_CHANNEL = "pre-1.0 (external users: pin exact version)"

_CITATION = (
    "引用数字时写产物身份（manifest_sha1 前 12 位 + 产物路径），"
    "不要写『v4.26 的结果』——材料修订号只用于沟通文档版本，不构成证据。"
)


def banner():
    return "\n".join(
        [
            "admet-screening %s  [%s]" % (__version__, RELEASE_CHANNEL),
            "  capability_level  %s   （G9 未授予：-dev 不是落后，是门禁状态）"
            % CAPABILITY_LEVEL,
            "  doc_revision      %s" % DOC_REVISION,
            "  artifact_identity manifest_sha1 + snapshot sha256（见 run_manifest.yaml）",
            "",
            _CITATION,
        ]
    )


def as_dict():
    return dict(
        version=__version__,
        capability_level=CAPABILITY_LEVEL,
        doc_revision=DOC_REVISION,
        channel=RELEASE_CHANNEL,
        citation_note=_CITATION,
    )
