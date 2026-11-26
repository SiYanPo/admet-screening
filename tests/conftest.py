# -*- coding: utf-8 -*-
"""pytest 夹具：把 skill 根目录加入 sys.path（使 `import adt` 生效）。

另外覆盖 `tmp_path`：**默认 pytest 的 tmp_path 会后置清理**，而本仓库要跑
60+ 个子进程 pytest 会话（一个测试文件一个会话），每个会话的清理都落在同一个
"turn"里累计删除动作；超过环境的批量删除阈值（50）就会要求人工确认、令子进程
返回非零，表现为**整批测试误报失败**（2026-10-30 实测：8 个用例因此失败，代码本身全绿）。

这里改成"**不删除的 scratch 目录**"：每次运行复用同一目录、按用例 nodeid 分子目录、
写入即覆盖。代价是运行后留一点临时文件（同步时排除），换来测试结果稳定、
不被文件系统策略干扰。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

# 2026-11-04 / §7「失败可发现」：`test_reliability.py` 是脚本式自执行文件，
# 顶层直接 `sys.exit(0)`；pytest 收集时 import 它即抛 SystemExit → INTERNALERROR，
# 导致整批测试无法收集（`pytest -q` 从来跑不通，只能靠 --ignore 绕过）。
# 它已由 `test_smoke_pytest.py::SCRIPTS` 以子进程方式**真实运行**，故在收集层
# 排除，而不是把它改成"导入时什么都不做"的假绿。
collect_ignore = ["test_reliability.py"]

SCRATCH = os.path.join(ROOT, "tests", ".scratch")


@pytest.fixture
def tmp_path(request):
    """替代内置 tmp_path：稳定、可复用、**不做删除**。"""
    os.makedirs(SCRATCH, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in request.node.nodeid)
    d = os.path.join(SCRATCH, safe[-120:])
    os.makedirs(d, exist_ok=True)
    from pathlib import Path
    return Path(d)
