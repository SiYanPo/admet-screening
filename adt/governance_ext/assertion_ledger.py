# -*- coding: utf-8 -*-
"""测试防腐（Anti Test-Rot）：断言账本 + 变更票据 + HMAC 签名。

问题：半年后开发者为了让 CI 变绿，把 assert value == 0.852 改成 0.850。
      若断言改动无人知晓、无证据、无审批，测试套件会静默腐化。

机制（三层）：
1. AST 级断言指纹：不依赖文件整哈希（格式化也会改），而是逐条提取
   check(name, cond) / assert cond 的规范化表达式 + 数值字面量，生成 id。
2. 账本签名：账本用 HMAC-SHA256 签名。生产环境密钥放 CI KMS，
   开发者工作区无法重签；原型用 evidence/.ledger_hmac_key 演示同一机制。
3. 变更票据：任何断言新增/删除/修改，必须附带签过名的 Ticket
   （reason / approver / linked_issue / mutation_run_id），且新账本的
   变异分数不得低于基线。没有票据 → CI 直接失败。

注意：原型中密钥文件与代码同仓，因此只能演示"机制"，不能提供真实
      防篡改强度；生产部署必须把密钥移到 CI 侧 KMS/HSM。此边界在报告中
      明说，不做虚假安全承诺。
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone

LEDGER_VERSION = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_key(key_path):
    with open(key_path, "rb") as fh:
        key = fh.read().strip()
    if len(key) < 16:
        raise ValueError("HMAC key 太短（<16 bytes），拒绝签署账本")
    return key


def generate_key(key_path):
    """生成演示密钥。生产：此文件不应进入代码仓，应由 CI 注入。"""
    key = os.urandom(32).hex().encode("ascii")
    os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
    with open(key_path, "wb") as fh:
        fh.write(key)
    return key


def _canonical(obj):
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _sign(payload, key):
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def _assertions_from_source(src, relpath):
    """用 AST 提取断言；表达式优先保留源码字面量（0.8500 ≠ 0.85）。"""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "check"
            and len(node.args) >= 2
        ):
            try:
                name = ast.literal_eval(node.args[0])
            except Exception:
                name = "<dynamic>"
            raw_expr = ast.get_source_segment(src, node.args[1])
            expr = " ".join(raw_expr.split()) if raw_expr else ast.unparse(node.args[1])
            kind = "check"
        elif isinstance(node, ast.Assert):
            name = "<assert@%d>" % node.lineno
            raw_expr = ast.get_source_segment(src, node.test)
            expr = " ".join(raw_expr.split()) if raw_expr else ast.unparse(node.test)
            kind = "assert"
        else:
            continue
        literals = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, (bool, str)):
                literals.append(repr(sub.value))
        # 保留源码里的数字写法：0.8500 与 0.85 语义相同，但"改断言"必须被看见
        literals.extend(re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", expr))
        aid = hashlib.sha256(
            ("%s|%s|%s|%s" % (relpath, name, kind, expr)).encode("utf-8")
        ).hexdigest()[:16]
        out.append(
            {
                "id": aid,
                "name": str(name)[:120],
                "kind": kind,
                "line": node.lineno,
                "expr_sha256": hashlib.sha256(expr.encode("utf-8")).hexdigest(),
                "literals": sorted(set(literals))[:20],
            }
        )
    return sorted(out, key=lambda d: (d["line"], d["id"]))


def build_ledger(test_dir, key_path, out_path, *, ticket=None):
    """扫描 test_dir 下所有 test_*.py，生成签名账本。

    ticket 是可选 dict：{"reason","approver","linked_issue","mutation_run_id"}。
    若本次构建相对旧账本有断言变化，则必须提供 ticket，否则拒绝生成
    （防止"顺手改断言"）。首次构建无旧账本时允许无 ticket。
    """
    key = _load_key(key_path)
    files = {}
    for fn in sorted(os.listdir(test_dir)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        path = os.path.join(test_dir, fn)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        files[fn] = {
            "sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
            "assertions": _assertions_from_source(src, fn),
        }
    payload = {
        "version": LEDGER_VERSION,
        "generated_at": _now(),
        "files": files,
        "ticket": ticket or None,
    }
    old = None
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                old = json.load(fh)
        except Exception:
            old = None
    if old is not None:
        diff = compare_ledgers(old, payload)
        if diff["changed"] and not ticket:
            raise PermissionError(
                "断言发生变化但未提供变更票据（ticket）：%s" % diff["summary"]
            )
        missing = [
            k
            for k in ("reason", "approver", "linked_issue", "mutation_run_id")
            if not (ticket or {}).get(k)
        ]
        if ticket and missing:
            raise ValueError("变更票据缺字段: %s" % ", ".join(missing))
    payload["signature"] = _sign(
        {k: v for k, v in payload.items() if k != "signature"}, key
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


def verify_ledger(ledger_path, test_dir, key_path):
    """校验账本签名 + 当前测试源码是否与账本一致。"""
    key = _load_key(key_path)
    with open(ledger_path, "r", encoding="utf-8") as fh:
        ledger = json.load(fh)
    body = {k: v for k, v in ledger.items() if k != "signature"}
    expected = _sign(body, key)
    sig_ok = hmac.compare_digest(expected, ledger.get("signature", ""))
    current = {}
    for fn in sorted(os.listdir(test_dir)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        with open(os.path.join(test_dir, fn), "r", encoding="utf-8") as fh:
            src = fh.read()
        current[fn] = {
            "sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
            "assertions": _assertions_from_source(src, fn),
        }
    diff = compare_ledgers(ledger, {"files": current})
    diff["signature_ok"] = sig_ok
    diff["ok"] = sig_ok and not diff["changed"]
    return diff


def compare_ledgers(old, new):
    """比较两份账本（只比 files 部分），输出人类可读的差异。"""
    of, nf = old.get("files", {}), new.get("files", {})
    added, removed, modified = [], [], []
    for fn in sorted(set(of) | set(nf)):
        if fn not in of:
            added.append("%s(新文件)" % fn)
            continue
        if fn not in nf:
            removed.append(fn)
            continue
        oa = {a["id"]: a for a in of[fn].get("assertions", [])}
        na = {a["id"]: a for a in nf[fn].get("assertions", [])}
        add_ids, rem_ids = set(na) - set(oa), set(oa) - set(na)
        # 同一断言"名字"同时出现在新增和删除里 → 判为修改（Test Rot 的典型形态）
        key_add = {}
        for aid in add_ids:
            key_add.setdefault((na[aid]["name"], na[aid]["kind"]), []).append(aid)
        paired = set()
        for aid in sorted(rem_ids):
            old = oa[aid]
            k = (old["name"], old["kind"])
            if key_add.get(k) and len(key_add[k]) == 1:
                nid = key_add[k][0]
                new = na[nid]
                o_lit, n_lit = set(old["literals"]), set(new["literals"])
                modified.append(
                    {
                        "file": fn,
                        "id": aid,
                        "name": old["name"],
                        "old_expr": old["expr_sha256"][:12],
                        "new_expr": new["expr_sha256"][:12],
                        "numeric_literal_change": sorted((o_lit ^ n_lit))[:8],
                    }
                )
                paired.add(aid)
                paired.add(nid)
        for aid in sorted(add_ids - paired):
            added.append("%s:%s %s" % (fn, aid, na[aid]["name"]))
        for aid in sorted(rem_ids - paired):
            removed.append("%s:%s %s" % (fn, aid, oa[aid]["name"]))
        for aid in sorted(set(oa) & set(na)):
            if oa[aid]["expr_sha256"] != na[aid]["expr_sha256"]:
                o_lit, n_lit = set(oa[aid]["literals"]), set(na[aid]["literals"])
                modified.append(
                    {
                        "file": fn,
                        "id": aid,
                        "name": na[aid]["name"],
                        "old_expr": oa[aid]["expr_sha256"][:12],
                        "new_expr": na[aid]["expr_sha256"][:12],
                        "numeric_literal_change": sorted((o_lit ^ n_lit))[:8],
                    }
                )
    changed = bool(added or removed or modified)
    summary_parts = []
    if added:
        summary_parts.append("新增%d" % len(added))
    if removed:
        summary_parts.append("删除%d" % len(removed))
    if modified:
        summary_parts.append("修改%d" % len(modified))
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "changed": changed,
        "summary": ", ".join(summary_parts) if summary_parts else "无变化",
    }


def check_mutation_non_regression(new_report, baseline_path, *, min_score=None):
    """断言改动后，变异分数不得退化；核心致命变异不得从 killed 变 survived。"""
    with open(baseline_path, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    bscore = float(base.get("score", 0))
    nscore = float(new_report.get("score", 0))
    reasons = []
    if nscore < bscore - 1e-9:
        reasons.append("变异分数退化 %.4f → %.4f" % (bscore, nscore))
    if min_score is not None and nscore < min_score:
        reasons.append("变异分数 %.4f 低于门禁 %.4f" % (nscore, min_score))
    bsurv = {m["mid"] for m in base.get("mutants", []) if m["status"] == "survived"}
    nsurv = {
        m["mid"] for m in new_report.get("mutants", []) if m["status"] == "survived"
    }
    if nsurv - bsurv:
        reasons.append("新增存活变异: %s" % ", ".join(sorted(nsurv - bsurv)[:5]))
    return {
        "ok": not reasons,
        "reasons": reasons,
        "baseline_score": bscore,
        "new_score": nscore,
    }
