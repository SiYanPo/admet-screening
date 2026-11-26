# -*- coding: utf-8 -*-
"""从任意目录调用 skill（把 skill 根目录加入 sys.path 后再走 cli）。

用法:
  python <skill_dir>/run.py normalize --in hits.txt --outdir out
  python <skill_dir>/run.py saturate --wide wide.csv --outdir out
  python <skill_dir>/run.py bt --in out/compounds.csv --outdir out --option CYP450
  python <skill_dir>/run.py xeno-prep --in out/compounds.csv --outdir out
  python <skill_dir>/run.py xeno-ingest --file readback.csv --outdir out
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from adt.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
