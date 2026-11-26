# -*- coding: utf-8 -*-
"""允许 `python -m adt ...` 等价于 `python -m adt.cli ...`（跨机复现时少踩一个坑）。"""

from .cli import main

main()
