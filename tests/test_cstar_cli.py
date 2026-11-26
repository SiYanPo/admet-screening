# -*- coding: utf-8 -*-
"""Tests for ``adt.cost_boundary`` and the ``adt cstar`` command.

The estimator is algebraic, so the ground truth is not a fitted value but a
hand-computable identity: on synthetic per-run data constructed so that the
utility difference is exactly linear, the solved c* must equal the value the
construction implies, and the identity gap (fitted slope minus Delta(1-cov))
must be zero to machine precision.
"""

from __future__ import annotations

import io
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from adt.cost_boundary import solve_all, solve_endpoint  # noqa: E402


def _per_run_linear(endpoint="SYN", seeds=20, slope=0.75, intercept=0.30):
    """Synthetic records with Delta-u exactly linear in the abstention price."""
    rows = []
    for seed in range(seeds):
        for cp, x in [
            ("abstain=0.05", 0.05), ("abstain=0.10", 0.10),
            ("abstain=0.20", 0.20), ("abstain=0.50", 0.50),
            ("abstain=1.00", 1.00), ("ref", 0.50),
        ]:
            du = intercept - slope * x
            rows.append(dict(endpoint=endpoint, strategy="S4_full_admission",
                             cost_point=cp, seed=seed, utility=du,
                             coverage=round(1.00 - slope, 4)))
            rows.append(dict(endpoint=endpoint, strategy="S1_naive_majority",
                             cost_point=cp, seed=seed, utility=0.0, coverage=1.00))
    return rows


def test_solve_endpoint_exact_linear():
    """On exact linear data, c* = intercept/slope and identity gap is ~0."""
    per_run = _per_run_linear(slope=0.75, intercept=0.30)
    r = solve_endpoint(per_run, "SYN")
    assert r is not None
    assert r["c_star"] == pytest.approx(0.30 / 0.75, abs=1e-3)
    assert r["identity_gap"] == pytest.approx(0.0, abs=1e-3)
    assert r["r2_min"] == pytest.approx(1.0, abs=1e-6)
    assert r["n_seeds"] == 20


def test_solve_endpoint_insufficient_seeds_returns_none():
    per_run = _per_run_linear(seeds=3)
    per_run = [r for r in per_run if r["cost_point"] != "abstain=1.00"]
    r = solve_endpoint(per_run, "SYN")
    assert r is None


def test_solve_all_skips_missing_endpoint():
    per_run = _per_run_linear(endpoint="A")
    rows = solve_all(per_run, ["A", "NOT_THERE"])
    assert [r["endpoint"] for r in rows] == ["A"]


def test_cstar_on_deposited_results():
    """Against the deposited keystone file, c* must match the published Table 2b."""
    p = os.path.join(ROOT, "out_keystone_v43", "results.json")
    if not os.path.exists(p):
        pytest.skip("deposited results not present in this checkout")
    per_run = json.load(io.open(p, encoding="utf-8"))["per_run"]
    r = solve_endpoint(per_run, "hERG")
    assert r is not None
    assert r["c_star"] == pytest.approx(0.2602, abs=1e-3)


def test_cli_cstar(tmp_path):
    """``python -m adt.cli cstar`` writes both outputs and exits 0."""
    p = os.path.join(ROOT, "out_keystone_v43", "results.json")
    if not os.path.exists(p):
        pytest.skip("deposited results not present in this checkout")
    md = tmp_path / "c.md"
    csv = tmp_path / "c.csv"
    import subprocess
    proc = subprocess.run(
        [os.sys.executable, "-m", "adt.cli", "cstar", "--results", p,
         "--endpoints", "BBB_Martins", "--out-md", str(md), "--out-csv", str(csv)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert md.exists() and csv.exists()
    text = csv.read_text(encoding="utf-8")
    assert "BBB_Martins" in text and "0.2091" in text
