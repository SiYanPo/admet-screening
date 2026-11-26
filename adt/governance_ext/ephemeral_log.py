# -*- coding: utf-8 -*-
"""盲区4：影子模式数据毒药积累 —— 脱敏与内存消散（Data Ephemerality）。

原则：
  - 日志只记录"指纹哈希 + 判定摘要 + 采样分数"，严禁原始 SMILES；
  - 双跑用的 payload 是浅拷贝，跑完在 finally 中递归清空容器引用；
  - 落盘只写哈希，且带 TTL，过期自动 purge；
  - 导出给人复核的样本也只给哈希，科学家通过安全通道按需回取原始结构。

诚实的边界：CPython 的 str 不可变、内存清零需要 C 层 mlock/secure-zero，
本原型只能做到"针对日志系统不留存 + 主动丢弃引用 + 容器清零"。
真正的物理消散应由短生命周期 worker（进程级隔离）实现，报告中明确说明。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone


def fingerprint(payload) -> str:
    """稳定指纹：dict 按键排序；不做可逆变换。"""
    if isinstance(payload, dict):
        body = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
    else:
        body = str(payload).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def scrub(obj):
    """递归清空可变容器；返回已清除字段数。"""
    n = 0
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            obj[k] = None
            n += 1
        obj.clear()
    elif isinstance(obj, list):
        while obj:
            obj.pop()
            n += 1
    elif isinstance(obj, bytearray):
        for i in range(len(obj)):
            obj[i] = 0
        n += 1
    return n


_SMI_HINT = re.compile(r"[CNOPSc	nops](?:[=#:()]|\d)")


def assert_no_raw_structure(text: str) -> dict:
    """扫描导出内容，确认没有可疑 SMILES 片段。

    先做 JSON 结构化扫描：跳过 hash/digest/mac 类字段（十六进制串会
    误触 SMILES 正则），只检查真正可能承载结构的文本字段。
    """
    hits = []
    try:
        obj = json.loads(text)

        def walk(x, key=""):
            if any(t in key.lower() for t in ("hash", "digest", "mac", "sig")):
                return
            if isinstance(x, dict):
                for k, v in x.items():
                    walk(v, k)
            elif isinstance(x, list):
                for v in x:
                    walk(v, key)
            elif isinstance(x, str) and len(x) < 200:
                if "SMILES" in x.upper() or _SMI_HINT.search(x):
                    hits.append("%s=%s" % (key, x[:100]))

        walk(obj)
    except (ValueError, TypeError):
        for line in str(text).splitlines():
            if re.search(r"\b[0-9a-f]{32,}\b", line):
                continue
            if "SMILES" in line.upper() or _SMI_HINT.search(line):
                hits.append(line.strip()[:120])
    return {"clean": not hits, "suspicious_lines": hits[:10]}


class EphemeralShadowLog:
    """只存哈希和判定的影子日志。与 ShadowChannel 组合使用。"""

    def __init__(self, *, max_records=10000, ttl_s=7 * 86400):
        self.max_records = max_records
        self.ttl_s = ttl_s
        self.records = []

    def add(self, payload, decision_summary: dict, *, ab=None, error=None):
        fp = fingerprint(payload)
        rec = {
            "mol_hash": fp,
            "new_block": bool(decision_summary.get("block")),
            "reason": str(decision_summary.get("reason") or "")[:120],
            "ab": ab,
            "error": str(error)[:120] if error else None,
            "ts": time.time(),
        }
        self.records.append(rec)
        if len(self.records) > self.max_records:
            del self.records[: len(self.records) - self.max_records]
        return rec

    def purge_expired(self, now=None):
        now = now or time.time()
        before = len(self.records)
        self.records = [r for r in self.records if now - r["ts"] <= self.ttl_s]
        return {"purged": before - len(self.records), "remaining": len(self.records)}

    def export(self, *, fmt="json") -> str:
        """只导出哈希；任何原始结构字段都不存在。"""
        slim = [
            {
                "mol_hash": r["mol_hash"],
                "new_block": r["new_block"],
                "reason": r["reason"],
                "ab": r["ab"],
                "error": r["error"],
            }
            for r in self.records
        ]
        out = json.dumps(
            {"n": len(slim), "records": slim}, ensure_ascii=False, indent=2
        )
        check = assert_no_raw_structure(out)
        if not check["clean"]:
            raise RuntimeError(
                "影子日志导出含可疑结构信息，已阻止: %s" % check["suspicious_lines"][:2]
            )
        return out

    def stats(self):
        n = len(self.records)
        return {
            "n": n,
            "new_blocked": sum(1 for r in self.records if r["new_block"]),
            "errors": sum(1 for r in self.records if r["error"]),
            "new_blocked_only": sum(
                1 for r in self.records if r["ab"] == "new_blocked_only"
            ),
        }


def run_shadow_ephemeral(channel, payload, *, old_decision=None, log=None):
    """双跑入口：payload 用局部拷贝，finally 清空；日志只收哈希摘要。"""
    import copy

    local = copy.copy(payload) if isinstance(payload, dict) else payload
    err = None
    eff, info = None, None
    try:
        eff, info = channel.run(local, old_decision=old_decision)
    except Exception as exc:  # 外层兜底：即使 channel 未吞异常也不外泄 payload
        err = exc
        raise
    finally:
        if log is not None and info is not None:
            log.add(
                payload,
                {
                    "block": bool((info.get("new_dec") or {}).get("block")),
                    "reason": info.get("new_reason"),
                },
                ab=info.get("ab"),
                error=err or info.get("error"),
            )
        n = scrub(local) if isinstance(local, dict) else 0
        try:
            del local
        except Exception:
            pass
    return eff, info


def secure_worker_note():
    """给部署文档的机器可读提示：短生命周期 worker 才是物理消散的正解。"""
    return {
        "strategy": "one_task_one_worker_process",
        "reason": "CPython str/bytes 不可变，无法在纯 Python 层保证内存零化",
        "required": [
            "Celery max_tasks_per_child=1",
            "Ray actor 每 N 任务回收",
            "worker 内禁止写原始 SMILES 到 stdout/stderr",
            "共享内存/对象存储禁用",
        ],
        "prototype_guarantee": "日志与导出仅含 SHA-256 指纹；引用被主动丢弃",
    }
