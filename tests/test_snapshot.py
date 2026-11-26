# -*- coding: utf-8 -*-
"""R01 快照层 + R02 发布门禁 回归测试（脚本式，可直接 python 运行）。"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import snapshot as SNAP          # noqa: E402
from adt import release_gate as RG       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_snapshot_roundtrip_and_tamper():
    root = tempfile.mkdtemp(prefix="adt_snap_")
    try:
        payload = '{"PropertyTable":{"Properties":[{"SMILES":"C[C@H](N)C(=O)O"}]}}'
        rec = SNAP.write_snapshot("pubchem", payload, key="compound:alanine",
                                  schema_version="pug-rest/test", root=root)
        assert rec["sha256"] == SNAP.sha256_bytes(payload)
        assert SNAP.replay(rec["snapshot_id"], root) == payload
        assert SNAP.summary(root)["verified"] == 1
        # 篡改 → 必须报错，不得静默通过
        with io.open(rec["path"], "w", encoding="utf-8") as f:
            f.write(payload.replace("C[C@H]", "CC"))
        bad = [r for r in SNAP.verify(root) if not r[1]]
        assert bad, "篡改后 verify 应失败"
        try:
            SNAP.replay(rec["snapshot_id"], root)
            raise AssertionError("篡改后 replay 必须抛 SnapshotError")
        except SNAP.SnapshotError:
            pass
        # 重放模式缺失快照 → 拒绝联网
        os.environ["ADT_REPLAY"] = "1"
        try:
            SNAP.fetch("https://example.invalid/x", source="pubchem", key="compound:ghost",
                       root=root)
            raise AssertionError("重放模式缺快照时必须抛 SnapshotMissing")
        except SNAP.SnapshotMissing:
            pass
        finally:
            os.environ.pop("ADT_REPLAY", None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _build_release_fixture(root, with_contract=True, with_snapshot=True):
    with io.open(os.path.join(root, "requirements.lock"), "w", encoding="utf-8") as f:
        f.write("rdkit==2026.3.6\nnumpy==2.5.4\n")
    if with_snapshot:
        SNAP.write_snapshot("admet_ai", '{"ok":1}', key="probe",
                            schema_version="contract/test",
                            root=os.path.join(root, "snapshots"))
    if with_contract:
        d = os.path.join(root, "snapshots", "contracts")
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, "admet_ai_probe.json"), "w", encoding="utf-8") as f:
            f.write('{"response":{}}')
    with io.open(os.path.join(root, "env_fingerprint.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(RG.env_fingerprint(), ensure_ascii=False))
    with io.open(os.path.join(root, "run_manifest.yaml"), "w", encoding="utf-8") as f:
        f.write("cmd: pytest\nsha1: deadbeef\n")
    refs = os.path.join(root, "references")
    os.makedirs(refs, exist_ok=True)
    with io.open(os.path.join(refs, "EVIDENCE_DAG.md"), "w", encoding="utf-8") as f:
        f.write("status: pending\n")
    # v4.4：G10/G12 把它们当作"完整夹具"的必要输入（此前夹具停留在 G1–G9 时代，
    # 新门禁一加就把缺失当 blocker → 测试误报）。产物路径按 skill 包根解析，
    # 故复制真实登记表即可通过，无需复制产物本身。
    # C04 / 外审 C V1：G11 现在检查**目标 root** 的登记表，不再读运行中包内的
    # defaults.YAML_PATH。夹具须自带该文件，否则「完整夹具」名不副实。
    for _name in ("CLAIMS_REGISTRY.yaml", "THRESHOLD_REGISTRY.yaml",
                  "NEGATIVE_RESULT_DEFAULTS.yaml"):
        _src = os.path.join(ROOT, "references", _name)
        if os.path.isfile(_src):
            shutil.copy2(_src, os.path.join(refs, _name))


def test_release_gate_pass_and_block():
    root = tempfile.mkdtemp(prefix="adt_rel_")
    try:
        _build_release_fixture(root)
        res = RG.check(root)
        items = {i["key"]: i for i in res["items"]}
        # C04 / 外审 C V1（2026-11-04）：G8 改为检查目标制品 root 的源码 +
        # subprocess 真跑的 9 个 pytest 节点证据。只有产物、没有 adt/ 与 tests/
        # 的临时夹具**必须**判未接线；旧断言 `res["passed"] is True` 依赖的正是
        # 「门禁查运行中包自己」这个已修复的 self-attestation 漏洞，故撤销。
        assert items["G8_red_lines"]["ok"] is False
        assert items["G8_red_lines"]["level"] == "blocker"
        # 夹具已补齐 G11 登记表 → 该门应通过
        assert items["G11_negative_result_defaults"]["ok"] is True
        # 本测试真正要锁的两条：钉版与契约快照不得被绕过
        assert "G1_pinned_lock" not in res["blockers"], res["blockers"]
        assert "G3_contract_snapshots" not in res["blockers"], res["blockers"]
        # 去掉契约快照 → 必须拦截
        shutil.rmtree(os.path.join(root, "snapshots", "contracts"))
        res2 = RG.check(root)
        assert "G3_contract_snapshots" in res2["blockers"]
        # 去掉钉版 → 必须拦截
        with io.open(os.path.join(root, "requirements.lock"), "w", encoding="utf-8") as f:
            f.write("rdkit>=2026\n")
        res3 = RG.check(root)
        assert "G1_pinned_lock" in res3["blockers"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    test_snapshot_roundtrip_and_tamper()
    print("OK snapshot roundtrip/tamper/replay-block")
    test_release_gate_pass_and_block()
    print("OK release gate pass/block")
    print("ALL PASS test_snapshot.py")
