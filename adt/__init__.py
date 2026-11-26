# -*- coding: utf-8 -*-
"""ADMET 决策支持工具包（长表契约 + 适配器 + 饱和扫描）。

版本从 `adt/_version.py` 单一源导入（D3）。此前这里是硬编码的 "0.1.0"，
与 pyproject 的 3.2.1、SKILL.md 的 4.0-dev 构成第四轨分歧，已消除。
"""

from ._version import __version__, CAPABILITY_LEVEL, DOC_REVISION  # noqa: F401

__all__ = ["__version__", "CAPABILITY_LEVEL", "DOC_REVISION"]
