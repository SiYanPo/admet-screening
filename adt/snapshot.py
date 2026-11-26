# -*- coding: utf-8 -*-
"""数据快照层（B5 / S7）：把"可复现"从声明变成架构属性。

问题（评审 S7 原话）："没有版本化的数据快照机制，任何新实验的'可复现'声明依旧
建立在活体 API 上。" —— 已发生的事故：PubChem 字段名变更（SMILES→IsomericSMILES
弃用）直接导致一次立体化学丢失；ADMETlab 有 429 限流；ProTox 250 次/天。

设计三条硬规则：
1. **活体调用只用于刷新快照**，计算一律从快照重放（`ADT_REPLAY=1` 时禁止联网）。
2. 每条快照记录 `sha256 + 抓取时间 + 响应 schema 版本 + 源 + 业务键`，落 index.jsonl。
3. 校验失败（哈希不符 / 缺失 / schema 不符）必须**报错而非静默重抓**——
   静默重抓会把"不可复现"重新藏回流程里。

用法：
    from adt import snapshot
    rec = snapshot.fetch("https://pubchem.ncbi.nlm.nih.gov/.../JSON", source="pubchem",
                         key="compound:terfenadine", schema_version="pug-rest/2026-10")
    payload = snapshot.replay(rec["snapshot_id"])      # 离线重放，不联网
"""

import hashlib
import io
import json
import os
import time
import urllib.request

DEFAULT_ROOT = os.environ.get("ADT_SNAPSHOT_DIR", "snapshots")
INDEX_NAME = "index.jsonl"


class SnapshotError(RuntimeError):
    pass


class SnapshotMissing(SnapshotError):
    """重放模式下找不到对应快照 —— 绝不允许回退到联网。"""


def sha256_bytes(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _root(root=None):
    return root or os.environ.get("ADT_SNAPSHOT_DIR", DEFAULT_ROOT)


def _ensure_dir(p):
    if not os.path.isdir(p):
        os.makedirs(p)


def _safe(s):
    keep = []
    for ch in str(s):
        keep.append(ch if (ch.isalnum() or ch in "-_.") else "_")
    return "".join(keep)


def replay_mode():
    """ADT_REPLAY=1 → 只读快照，禁止联网。"""
    return os.environ.get("ADT_REPLAY", "") not in ("", "0", "false", "False")


def write_snapshot(
    source, payload, key="", schema_version="", root=None, meta=None, fetched_at=None
):
    """落盘一条快照，返回记录 dict（含 snapshot_id / sha256 / path）。"""
    root = _root(root)
    src_dir = os.path.join(root, _safe(source))
    _ensure_dir(src_dir)
    if not isinstance(payload, (str, bytes)):
        payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = sha256_bytes(payload)
    ts = fetched_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    snap_id = "%s__%s__%s" % (
        _safe(key or "payload"),
        digest[:12],
        ts.replace("-", "").replace(":", ""),
    )
    # C2-b / C12（2026-11-04）：CAS —— 文件名即内容 sha256，同内容天然去重，
    # 且不可能出现「文件名说 A、内容却是 B」而无人察觉的情况。
    # 旧实现把 Windows 反斜杠绝对路径写进 index.jsonl，Linux CI 上 G2 必挂。
    fname = digest + ".json"
    body_path = os.path.join(src_dir, fname)
    with io.open(body_path, "wb") as f:
        f.write(payload.encode("utf-8") if isinstance(payload, str) else payload)
    rel_path = "%s/%s" % (_safe(source), fname)  # POSIX，相对 root
    rec = {
        "snapshot_id": snap_id,
        "source": source,
        "key": key,
        "sha256": digest,
        "bytes": len(payload),
        "fetched_at": ts,
        "schema_version": schema_version or "unspecified",
        "path": body_path.replace(os.sep, "/"),  # 兼容旧消费方；无反斜杠
        "rel_path": rel_path,  # 与 cwd 解耦的正解
        "cas": True,
        "path_policy": "resolve_path(rec, root) = root / rel_path；索引不含反斜杠",
        "meta": meta or {},
    }
    with io.open(os.path.join(src_dir, INDEX_NAME), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_snapshots(root=None, source=None):
    root = _root(root)
    if not os.path.isdir(root):
        return []
    srcs = [source] if source else sorted(os.listdir(root))
    out = []
    for s in srcs:
        p = os.path.join(root, s, INDEX_NAME)
        if not os.path.isfile(p):
            continue
        for ln in io.open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    raise SnapshotError("index 损坏：%s" % p)
    return out


def _find(snapshot_id, root=None, source=None):
    for rec in list_snapshots(root, source):
        if rec["snapshot_id"] == snapshot_id:
            return rec
    return None


def resolve_path(rec, root=None):
    """索引记录 → 本机可打开路径（C2-b：与 cwd 解耦）。

    优先用 `rel_path` + 显式 root 拼装；旧记录只有 `path` 时，
    绝对路径直接用，相对路径按 root 拼装。POSIX 分隔符统一由 split("/") 处理。
    """
    base = _root(root)
    rp = rec.get("rel_path")
    if rp:
        return os.path.normpath(os.path.join(base, *str(rp).split("/")))
    p = str(rec.get("path") or "")
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(base, *p.split("/")))


def verify(root=None, snapshot_id=None):
    """校验哈希。返回 [(snapshot_id, ok, msg)]；snapshot_id 为空则全量校验。"""
    root = _root(root)
    recs = list_snapshots(root)
    if snapshot_id:
        recs = [r for r in recs if r["snapshot_id"] == snapshot_id]
        if not recs:
            return [(snapshot_id, False, "not_found")]
    out = []
    for r in recs:
        p = resolve_path(r, root)
        if not os.path.isfile(p):
            out.append((r["snapshot_id"], False, "missing_body"))
            continue
        with io.open(p, "rb") as f:
            body = f.read()
        got = sha256_bytes(body)
        out.append(
            (
                r["snapshot_id"],
                got == r["sha256"],
                "ok" if got == r["sha256"] else "sha256_mismatch",
            )
        )
    return out


def replay(snapshot_id, root=None, source=None, as_text=True):
    rec = _find(snapshot_id, root, source)
    if rec is None:
        raise SnapshotMissing("快照不存在：%s（重放模式禁止联网回退）" % snapshot_id)
    with io.open(resolve_path(rec, root), "rb") as f:
        body = f.read()
    if sha256_bytes(body) != rec["sha256"]:
        raise SnapshotError("快照哈希不符，拒绝重放：%s" % snapshot_id)
    if as_text:
        return body.decode("utf-8")
    return body


def find_latest(source, key=None, root=None):
    hits = [
        r for r in list_snapshots(root, source) if (key is None or r.get("key") == key)
    ]
    return hits[-1] if hits else None


def fetch(
    url,
    source,
    key="",
    schema_version="",
    root=None,
    timeout=30,
    headers=None,
    meta=None,
    refresh=False,
):
    """取数并落快照。重放模式或已存在同 (source,key,schema) 快照 → 直接重放。"""
    root = _root(root)
    if not refresh:
        prev = find_latest(source, key, root)
        if prev is not None and prev.get("schema_version") == (
            schema_version or "unspecified"
        ):
            if replay_mode() or os.environ.get("ADT_SNAPSHOT_PREFER_LOCAL", "1") != "0":
                return prev, replay(prev["snapshot_id"], root)
    if replay_mode():
        raise SnapshotMissing(
            "重放模式（ADT_REPLAY=1）下不存在可复用快照：%s / %s —— 拒绝联网"
            % (source, key)
        )
    req = urllib.request.Request(
        url, headers=headers or {"User-Agent": "admet-screening/4.x (+snapshot-layer)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    rec = write_snapshot(
        source,
        body,
        key=key,
        schema_version=schema_version,
        root=root,
        meta=dict(meta or {}, url=url),
    )
    return rec, body.decode("utf-8", errors="replace")


def summary(root=None):
    recs = list_snapshots(root)
    srcs = {}
    for r in recs:
        srcs[r["source"]] = srcs.get(r["source"], 0) + 1
    checks = verify(root)
    bad = [c for c in checks if not c[1]]
    return {
        "n_snapshots": len(recs),
        "by_source": srcs,
        "verified": len(checks) - len(bad),
        "failed": len(bad),
        "failed_ids": [c[0] for c in bad][:10],
    }
