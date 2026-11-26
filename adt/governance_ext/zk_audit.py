# -*- coding: utf-8 -*-
"""盲区1 / 追问3：零知识审计证据契约（结构盲化 + 哈希承诺 + Merkle 证明）。

B2B 两端都不愿泄露核心资产：
  - 药企不愿把内部 SMILES 交给 CRO 的审计系统；
  - CRO 不愿向药企暴露算法实现与其余客户分子。

本模块给出**可验证但不泄露**的证据契约：
  1. 承诺 leaf = SHA256(canonical_smiles + audit_salt + endpoint
                        + manifest_digest + protocol_version)
     —— 不含 SMILES 明文；salt 由审计双方通过安全通道共享。
  2. 多分子 batch 用 Merkle 树汇总为一个 root；CRO 只提供目标分子的
     包含证明（兄弟节点路径），不暴露其它叶子。
  3. 药企拿自己的原始分子 + salt 重算 leaf，验证 root 一致即可证明
     "该分子确实被审计过且 manifest 未被篡改"。

诚实边界：这是**哈希承诺（Hash Commitment）**，不是 zk-SNARK。
它证明"我持有能生成该承诺的原文"，不证明计算过程正确；
算法正确性仍需版本化 manifest + 变异门禁 + 审计抽检共同保证。
真正的 ZK 电路（如 Groth16）应作为后续升级，本模块预留接口形状。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

PROTOCOL_VERSION = "zk-audit-v1"


def canonical_smiles(smiles: str) -> str:
    """尽力规范化；有 RDKit 时用它，避免盐/芳香写法造成承诺不一致。"""
    try:
        from rdkit import Chem

        m = Chem.MolFromSmiles(str(smiles))
        if m is not None:
            return Chem.MolToSmiles(m)
    except Exception:
        pass
    return str(smiles).strip()


def commitment(
    smiles,
    salt,
    *,
    endpoint=None,
    manifest_digest=None,
    inchikey=None,
    protocol_version=PROTOCOL_VERSION,
) -> str:
    body = {
        "canonical_smiles": canonical_smiles(smiles),
        "salt": str(salt),
        "endpoint": endpoint,
        "inchikey": inchikey,
        "manifest_digest": manifest_digest,
        "protocol_version": protocol_version,
    }
    return hashlib.sha256(
        json.dumps(
            body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _pair_hash(a, b):
    return hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()


def merkle_root(leaves):
    lv = [str(x) for x in leaves]
    if not lv:
        return ""
    while len(lv) > 1:
        if len(lv) % 2:
            lv.append(lv[-1])  # 奇数个叶子复制末尾，标准做法
        lv = [_pair_hash(lv[i], lv[i + 1]) for i in range(0, len(lv), 2)]
    return lv[0]


def merkle_proof(leaves, index):
    """返回 [(sibling, position)]，position=0 表示 sibling 在左。"""
    lv = [str(x) for x in leaves]
    if index < 0 or index >= len(lv):
        raise IndexError("叶子索引越界")
    proof = []
    while len(lv) > 1:
        if len(lv) % 2:
            lv.append(lv[-1])
        sib = index ^ 1
        proof.append((lv[sib], 0 if sib < index else 1))
        lv = [_pair_hash(lv[i], lv[i + 1]) for i in range(0, len(lv), 2)]
        index //= 2
    return proof


def verify_merkle(leaf, proof, root) -> bool:
    h = str(leaf)
    for sibling, position in proof or []:
        h = _pair_hash(sibling, h) if position == 0 else _pair_hash(h, sibling)
    return h == root


def manifest_digest(manifest: dict) -> str:
    """对不含 SMILES 的 manifest 主体做摘要。"""
    clean = {
        k: v
        for k, v in manifest.items()
        if k not in ("root", "proof", "leaf", "audit_evidence")
    }
    return hashlib.sha256(
        json.dumps(
            clean, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class BlindAuditManifest:
    """生成不含原始结构的盲化审计清单。"""

    def __init__(
        self,
        salt,
        *,
        algorithm_id="admet-screening",
        algorithm_version="0.3.0-production-proto",
    ):
        self.salt = str(salt)
        self.algorithm_id = algorithm_id
        self.algorithm_version = algorithm_version

    def build(self, smiles_list, *, endpoint, execution_summary, inchikey_list=None):
        digest = manifest_digest(
            {
                "algorithm_id": self.algorithm_id,
                "algorithm_version": self.algorithm_version,
                "endpoint": endpoint,
                "execution_summary": execution_summary,
                "protocol_version": PROTOCOL_VERSION,
            }
        )
        ik = inchikey_list or [None] * len(smiles_list)
        leaves = [
            commitment(
                s, self.salt, endpoint=endpoint, manifest_digest=digest, inchikey=ik[i]
            )
            for i, s in enumerate(smiles_list)
        ]
        root = merkle_root(leaves)
        return {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "endpoint": endpoint,
            "execution_summary": execution_summary,
            "protocol_version": PROTOCOL_VERSION,
            "manifest_digest": digest,
            "n_molecules": len(leaves),
            "root": root,
            # 只公布 salt 的承诺，salt 本身经审计通道传递
            "salt_commitment": hashlib.sha256(self.salt.encode("utf-8")).hexdigest(),
            "_leaves": leaves,  # 仅在 CRO 侧保留；对外发布时 strip_private()
        }

    @staticmethod
    def strip_private(manifest: dict) -> dict:
        return {k: v for k, v in manifest.items() if k != "_leaves"}

    def evidence(self, manifest, index):
        """给合作方的包含证明：只有目标路径，没有任何 SMILES。"""
        leaves = manifest.get("_leaves", [])
        return {
            "index": int(index),
            "leaf": leaves[index],
            "proof": merkle_proof(leaves, int(index)),
            "root": manifest["root"],
            "manifest_digest": manifest["manifest_digest"],
            "salt_commitment": manifest["salt_commitment"],
        }


def verify_evidence(
    public_manifest, evidence, smiles, salt, *, endpoint=None, inchikey=None
) -> dict:
    """药企侧验证：只需自己的 SMILES + salt + 公开 manifest + CRO 的证明。"""
    reasons = []
    if evidence.get("root") != public_manifest.get("root"):
        reasons.append("root 不一致")
    if evidence.get("manifest_digest") != public_manifest.get("manifest_digest"):
        reasons.append("manifest_digest 不一致")
    if evidence.get("salt_commitment") != public_manifest.get("salt_commitment"):
        reasons.append("salt_commitment 不一致")
    recomputed = commitment(
        smiles,
        salt,
        endpoint=endpoint or public_manifest.get("endpoint"),
        manifest_digest=public_manifest.get("manifest_digest"),
        inchikey=inchikey,
        protocol_version=public_manifest.get("protocol_version", PROTOCOL_VERSION),
    )
    if recomputed != evidence.get("leaf"):
        reasons.append("SMILES 与承诺不匹配（分子不同或 manifest 被篡改）")
    if not verify_merkle(
        recomputed, evidence.get("proof", []), public_manifest.get("root", "")
    ):
        reasons.append("Merkle 包含证明失败")
    ok = not reasons
    return {
        "ok": ok,
        "reasons": reasons,
        "verified_leaf": recomputed[:16],
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "note": "仅证明分子被纳入承诺与审计批次，不证明算法执行正确",
    }


# ---- 水印被清洗后的语义升档追溯 ----
_HIGH_CONFIDENCE_TERMS = (
    "无异常",
    "安全",
    "无毒",
    "低风险",
    "风险较低",
    "通过验证",
    "已确证",
    "PASS",
    "safe",
    "proven",
    "no risk",
)


def locked_digest(text: str) -> str:
    return hashlib.sha256(" ".join(str(text).split()).encode("utf-8")).hexdigest()


def trace_uplift(original_conclusion, translated_text, *, envelope=None) -> dict:
    """检测"清洗零宽水印后用 LLM 翻译成高置信报告"的语义升档。

    结论词的哈希承诺写进审计 manifest；任何改写都会产生新的 digest，
    无法与原始承诺匹配——即使不可见字符被全部删除。
    """
    hits = [t for t in _HIGH_CONFIDENCE_TERMS if t in str(translated_text)]
    same = " ".join(str(original_conclusion).split()) == " ".join(
        str(translated_text).split()
    )
    dg = locked_digest(translated_text)
    env = envelope or {}
    env_digest = env.get("conclusion_digest")
    return {
        "uplift_suspected": bool(hits or not same),
        "high_confidence_terms": hits,
        "translation_digest": dg,
        "matches_locked_conclusion": same,
        "matches_audit_commitment": (env_digest is None) or (dg == env_digest),
        "status": "UPLIFT_SUSPECTED" if (hits or not same) else "FAITHFUL_COPY",
        "note": "零宽水印可清洗，但结论承诺在审计链上；改写无法获得原批次的审计背书",
    }
