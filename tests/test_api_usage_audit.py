# -*- coding: utf-8 -*-
"""API 零引用审计的回归：未登记公共函数不得进入默认批跑。"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_api_usage_audit_has_no_unregistered_dead_public_api(tmp_path):
    out = tmp_path / "api_usage.json"
    r = subprocess.run([sys.executable, "tools/api_usage_audit.py",
                        "--json-out", str(out)],
                       cwd=HERE, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n_unregistered"] == 0, data["unregistered"]
    assert all(z["allowlisted"] and z["reason"] for z in data["zero"]), data["zero"]
