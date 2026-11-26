# -*- coding: utf-8 -*-
"""判据/注册表资源解析层 —— D2 修复（2026-11-17）。

## 修的是什么

v4.0-dev 之前，全仓 30 处 argparse 默认值写成 `default="references/xxx.yaml"`，
模块内还有 `path="references/CLAIMS_REGISTRY.yaml"` 这样的函数默认参数。
它们是 **cwd 相对路径**：只要不是在源码树根目录运行，`reliab / desire /
tier / qaf / merge` 就全部读不到规则表。全仓 `importlib.resources` 命中 0 次。

两种失败方式都不可接受：
  - 裸 `FileNotFoundError: references/03_endpoint_rules.yaml` —— 用户看不懂；
  - 更糟的是某些调用点把它吞掉后按"无规则"降级 —— 静默给出错误结论。

## 解析顺序（固定、可打印、不猜）

1. **显式路径**（`--rules value` 用户自己给了）→ 原样使用；不存在则**立刻抛错**，
   并列出这次找过的每一个位置。用户明确指定却读不到，不许回落到别的文件。
2. `$ADT_REFERENCES` 指向的目录（部署时把判据外置到共享盘 / 只读挂载）。
3. **源码树 references/**（仅当 `adt/` 的同级存在 `pyproject.toml`，即开发态）。
   放这一档是为了开发时改 YAML 立即生效，行为与修复前完全一致。
4. **包内资源 `adt/_data/`**（随 wheel 分发；安装态的唯一保证）。
5. 都不命中 → `ReferenceNotFound`，消息里含全部搜索路径。

## 为什么包内副本不会与 references/ 漂移

`tests/test_data_sync.py` 逐文件比对 sha256；`tools/sync_references.py`
重新生成副本。CI 里任一文件不一致即失败 —— 用测试而不是自觉来保证一致。
"""

from __future__ import annotations

import os
import sys
from importlib import resources as _res

PKG = "adt._data"
ENV_VAR = "ADT_REFERENCES"
_EXPLICIT_PREFIX = "references/"

# 需要随包分发的判据文件（与 references/*.yaml 同步；见 tools/sync_references.py）
# 注：EVIDENCE_DAG / OVERRIDE_LEDGER 是**运行时产物**（前者是 .md，release_gate
# 检查其存在性；后者由 cmd 写入 outdir），不属于随包静态判据，故不在此列。
SYNCED = (
    "02_source_registry.yaml",
    "03_endpoint_rules.yaml",
    "ENDPOINT_ESTIMAND_CARDS.yaml",  # 2026-11-17 G13：C01 撤回前置条件，必须随 wheel 分发
    "CLAIMS_REGISTRY.yaml",
    "NEGATIVE_RESULT_DEFAULTS.yaml",
    "RULE_CONFLICT_LEDGER.yaml",
    "SEED_POLICY.yaml",
    "SPLIT_TYPE_REGISTRY.yaml",
    "THRESHOLD_REGISTRY.yaml",
    "VERSION_POLICY.yaml",
    "endpoint_aliases.yaml",
    "readback_schemas.yaml",
    "reliability_landscape.yaml",
    "source_cards.yaml",
    "transporter_priors.yaml",
)

# as_file() 的临时文件必须在进程内保活，否则 Traversable 被 GC 后路径失效
_KEEP = []


class ReferenceNotFound(FileNotFoundError):
    """判据文件在所有已知位置都找不到。消息必须能定位到"缺哪个 / 找过哪"。"""

    def __init__(self, name, searched):
        self.name = name
        self.searched = list(searched)
        lines = ["判据文件 %r 找不到。已按下列顺序搜索：" % (name,)]
        for i, (label, path) in enumerate(self.searched, 1):
            lines.append("  %d. %-28s %s" % (i, label, path))
        lines.append(
            "修复：① 在源码树根目录运行；或 ② 设 ADT_REFERENCES=<references 目录>；"
            "或 ③ 用 --rules/--registry 显式给出路径。"
        )
        super().__init__("\n".join(lines))


def package_root():
    """返回 adt/ 的父目录（源码树根 or site-packages）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_source_tree():
    """adt/ 同级有 pyproject.toml 即视为开发态（此时 references/ 是权威编辑位）。"""
    root = package_root()
    return os.path.isfile(os.path.join(root, "pyproject.toml")) and os.path.isdir(
        os.path.join(root, "references")
    )


def search_paths(name):
    """返回 [(label, path)]，顺序即解析优先级。"""
    out = []
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(("$%s" % ENV_VAR, os.path.join(env, name)))
    root = package_root()
    if is_source_tree():
        out.append(("源码树 references/", os.path.join(root, "references", name)))
    try:
        trav = _res.files(PKG).joinpath(name)
        if trav.is_file():
            out.append(("包内 adt/_data/", str(trav)))
    except (ModuleNotFoundError, ImportError, AttributeError):
        pass
    return out


def resolve(name, explicit=None):
    """把判据文件名解析成可 `open()` 的路径。

    name     : 纯文件名，如 "03_endpoint_rules.yaml"
    explicit : 用户显式给的路径（含 "references/" 前缀也可以）。非空时不做任何回落。
    """
    if explicit:
        p = os.path.normpath(str(explicit))
        if os.path.isfile(p):
            return p
        # 允许用户写 "references/x.yaml" 而后台已切到包内资源
        base = os.path.basename(p)
        for label, cand in search_paths(base):
            if os.path.isfile(cand):
                raise ReferenceNotFound(
                    p, [(label, cand)] + search_paths(base) + [("你给的路径", p)]
                )
        raise ReferenceNotFound(p, search_paths(base) + [("你给的路径", p)])

    cands = search_paths(name)
    for _label, path in cands:
        if os.path.isfile(path):
            return path

    # wheel 被装成 zip（罕见）时 files() 不是真实路径，退回 as_file 解包
    try:
        trav = _res.files(PKG).joinpath(name)
        if trav.is_file():
            f = _res.as_file(trav)
            p = f.__enter__()
            _KEEP.append(f)
            return str(p)
    except Exception:
        pass

    raise ReferenceNotFound(name, cands or [("(无可用候选)", "-")])


def read_text(name, explicit=None, encoding="utf-8"):
    with open(resolve(name, explicit), "r", encoding=encoding) as f:
        return f.read()


def read_bytes(name, explicit=None):
    with open(resolve(name, explicit), "rb") as f:
        return f.read()


def strip_prefix(value):
    """把历史写法 "references/x.yaml" 归一成 "x.yaml"；其他值原样返回。"""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if v.startswith(_EXPLICIT_PREFIX):
        return v[len(_EXPLICIT_PREFIX) :]
    return v


def resolve_arg(value):
    """给 argparse 结果用：空值→None；"references/x"→解析后的真实路径；其他原样。

    返回 None 表示"调用方该用模块内的缺省解析"。
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.startswith(_EXPLICIT_PREFIX):
        return resolve(v[len(_EXPLICIT_PREFIX) :])
    return v


def describe():
    """doctor / --version 用：当前生效的资源位置与来源。"""
    root = package_root()
    src = "源码树" if is_source_tree() else "已安装包"
    rows = []
    for name in SYNCED:
        try:
            p = resolve(name)
            rows.append(
                dict(
                    name=name,
                    path=p,
                    ok=True,
                    where=(
                        "包内"
                        if os.sep + "_data" + os.sep in p
                        else (
                            "$" + ENV_VAR
                            if os.environ.get(ENV_VAR)
                            and p.startswith(os.environ[ENV_VAR])
                            else "references/"
                        )
                    ),
                )
            )
        except ReferenceNotFound as e:
            rows.append(
                dict(
                    name=name,
                    path=None,
                    ok=False,
                    where="-",
                    error=str(e).splitlines()[0],
                )
            )
    return dict(
        package_root=root,
        mode=src,
        env=os.environ.get(ENV_VAR),
        n_total=len(SYNCED),
        n_ok=sum(1 for r in rows if r["ok"]),
        files=rows,
    )
