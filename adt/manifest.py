# -*- coding: utf-8 -*-
"""A3 run manifest（预注册）：每次批量运行前固化判据版本。

阈值在 rules/registry 里是可编辑的；没有 manifest，历史结论无法证明
"当时用的是哪个版本"——事后改阈值再重跑会让结论漂移而无人察觉。

用法：在每个批量命令（saturate/reliab/desire/chembl/bt）的入口调用
write_manifest(outdir, inputs=[...], argv=[...])。同目录覆盖写 run_manifest.yaml，
并追加历史 run_manifest_history.jsonl（保留每次运行的哈希链）。
"""

import hashlib
import io
import json
import os
import sys
import time

# 以 skill 包根为基准解析 git commit，绝不用调用方 cwd（否则会把调用方所在
# 无关仓库的 HEAD 误记为本 skill 的代码版本，制造虚假可复现性）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# C2-a / C12（2026-11-04）：内容哈希必须排除所有「每次运行都会变」的字段。
# 否则「同一输入两次运行 manifest.json 内容哈希相同」永远不成立，四元组无法
# 用来证明「结论是在同一组钉死的输入/环境下产生的」。
CONTENT_HASH_EXCLUDE = frozenset(
    {
        "created_at",
        "generated_at",
        "fetched_at",
        "timestamp",
        "cwd",
        "manifest_sha1",
        "content_sha256",
        "prev_hash",
        "abs_path_at_write",
    }
)


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def effective_params_hash(args_obj, *, exclude=("func", "list_tools", "selftest")):
    """同行评审 §5 参数缺口：把本次生效参数固化成 sha256，供复现时核对。

    只取命令行实际生效的字段（不含内部函数对象），排序后哈希——同一批参数
    在任何机器上都得到同一 hash。CLI 启动时打印，交付包附此值即可证明"跑的是哪组参数"。
    """
    d = {}
    for k, v in vars(args_obj).items():
        if k in exclude or k.startswith("_"):
            continue
        d[k] = str(v)
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _env_digest():
    """环境指纹：钉版依赖 + 解释器 + 平台，取 sha256。"""
    import platform

    d = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "rdkit": _rdkit_version(),
    }
    for m in ("numpy", "scipy", "pandas", "yaml", "sklearn"):
        try:
            mod = __import__(m)
            d[m] = getattr(mod, "__version__", "")
        except Exception:
            d[m] = ""
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _script_sha256(argv):
    """四元组之 script：优先 argv 里可解析的 .py，其次推断 -m adt.cli。"""
    for cand in list(argv or [])[:3]:
        p = str(cand)
        if p.endswith(".py") and os.path.isfile(p):
            return _sha256_file(p)
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("cli.py", "__main__.py"):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            return _sha256_file(p)
    return ""


def _prev_content_hash(outdir):
    """哈希链：上一条 manifest 的**内容哈希**（不是上一条的整文件哈希）。"""
    p = os.path.join(outdir, "run_manifest_history.jsonl")
    last = None
    if os.path.isfile(p):
        for ln in io.open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    last = json.loads(ln)
                except ValueError:
                    continue
    return (last or {}).get("content_sha256") or "GENESIS"


def content_hash(manifest):
    """对排除时间戳/链字段后的内容做 sha256（供门禁与第三方复核调用）。"""
    body = {k: v for k, v in manifest.items() if k not in CONTENT_HASH_EXCLUDE}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _rdkit_version():
    try:
        import rdkit

        return getattr(rdkit, "__version__", "")
    except Exception:
        return ""


def _rel(p):
    """argv 里记相对路径：绝对路径会让 manifest 跨机器不可复现（评估 P2-13）。"""
    try:
        r = os.path.relpath(p, os.getcwd())
        return p if r.startswith(".." + os.sep + "..") else r
    except Exception:
        return p


def write_manifest(outdir, inputs=(), argv=None, extra=None):
    """写 run_manifest.yaml（覆盖）+ 追加 run_manifest_history.jsonl。

    v2.2：记录 rdkit 版本（描述符/标准化结果随版本漂移），argv 相对化。
    """
    os.makedirs(outdir, exist_ok=True)
    # 2026-11-19：显式落"实际使用档位"（首轮报告 🟡 项）。
    # 未声明与声明 academic-internal 必须可区分；None 表示未声明，不猜默认。
    _prof = os.environ.get("ADT_PROFILE")
    rec = dict(
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        argv=[_rel(a) for a in (argv if argv else sys.argv)],
        python=sys.version.split()[0],
        rdkit=_rdkit_version(),
        cwd=os.getcwd(),
        compliance_profile=_prof,
        profile_declaration=(
            "explicit" if _prof else "undeclared_default_academic_internal"
        ),
        inputs={_rel(p): _sha1(p) for p in inputs if p and os.path.exists(p)},
        extra=extra or {},
    )
    # 2026-11-19：移植 TRUST-ADMET 的 git commit 字段（可复现性增量）。
    # 失败时写 None + git_rev_status，绝不伪造；不影响 manifest_sha1 的其它字段。
    try:
        import subprocess

        _r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        rec["git_commit"] = (
            (_r.stdout or "").strip()[:40] if _r.returncode == 0 else None
        )
        rec["git_rev_status"] = "resolved" if rec["git_commit"] else "unavailable"
    except Exception:
        rec["git_commit"] = None
        rec["git_rev_status"] = "unavailable"
    rec["manifest_sha1"] = hashlib.sha1(
        json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    # ---- C2-a / C12：真正的 manifest.json（与 run_manifest.yaml 并存） ----
    # 四元组 = command + script_sha256 + data_sha256[] + env_digest，
    # 另带 estimand_id（L+2 冻结后填）、value、prev_hash、content_sha256。
    # 旧 run_manifest.yaml 只有 sha1 + 时间戳，外审 C V3 判「条间无 prev_hash、
    # 哈希链名不副实」；这里补成可由第三方离线逐字段复核的结构。
    extra = extra or {}
    data = []
    for p in inputs:
        if not p or not os.path.exists(p):
            continue
        try:
            data.append({"path": _rel(p), "sha256": _sha256_file(p)})
        except OSError:
            pass
    mf = dict(
        schema_version="2.0",
        command=" ".join(str(x) for x in rec["argv"]),
        script_sha256=_script_sha256(rec["argv"]),
        data_sha256=data,
        env_digest=_env_digest(),
        estimand_id=extra.get("estimand_id"),
        value=extra.get("value"),
        generated_at=rec["created_at"],
        prev_hash=_prev_content_hash(outdir),
        inputs_sha1=rec["inputs"],
        binding_item="C2-a / C12 / 外审 C V3",
        hash_policy=(
            "content_sha256 排除 created_at/generated_at/prev_hash/"
            "content_sha256/cwd 等易变字段；同一输入两次运行必须相同"
        ),
    )
    mf["content_sha256"] = content_hash(mf)
    with io.open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(mf, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    rec["content_sha256"] = mf["content_sha256"]
    rec["manifest_json"] = "manifest.json"
    rec["estimand_id"] = mf["estimand_id"]

    import yaml

    with io.open(
        os.path.join(outdir, "run_manifest.yaml"), "w", encoding="utf-8"
    ) as fh:
        yaml.safe_dump(rec, fh, allow_unicode=True, sort_keys=False)
    with io.open(
        os.path.join(outdir, "run_manifest_history.jsonl"), "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec["manifest_sha1"]
