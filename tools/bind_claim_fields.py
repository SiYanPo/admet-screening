# -*- coding: utf-8 -*-
"""为 CLAIMS_REGISTRY.yaml 的每条主张自动生成并校验 expect_field_path。

纪律（对齐 adt/claims_audit.verify_registry_fields 的判定）：
  * 每个 expect token 必须能在"路径解析出的值的 JSON 序列化"里找到；
  * 字符串 flag 作为 dict key 出现时，绑定到其父 dict（序列化含 key 名）；
  * 先自校验 field_match=True，才写回；自校验不过的条目一律不动、报 UNBOUND；
  * 已撤回（status=superseded / admissible=false）主张不参与绑定。

用法：python tools/bind_claim_fields.py [--write]  （默认 dry-run 只报告）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "references", "CLAIMS_REGISTRY.yaml")


def leaves(obj, path=""):
    """yield (resolver_path, value)。resolver_path 用 . 分层、[] 表示展开 list。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, (path + "." if path else "") + k)
    elif isinstance(obj, list):
        for v in obj:
            yield from leaves(v, path + "[]")
    else:
        yield path, obj


def parents(obj, target_key, path=""):
    """找所有含 target_key 作为 key 的 dict 的 resolver path。"""
    out = []
    if isinstance(obj, dict):
        if target_key in obj:
            out.append(path)
        for k, v in obj.items():
            out.extend(parents(v, target_key, (path + "." if path else "") + k))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(parents(v, target_key, path + "[]"))
    return out


def ser(v):
    return (
        v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    )


def resolve(obj, path):
    """与 claims_audit._resolve_field_path 完全一致的解析。"""
    cur = [obj]
    for part in [x for x in str(path).split(".") if x]:
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part
        nxt = []
        for c in cur:
            if not isinstance(c, dict) or key not in c:
                continue
            v = c[key]
            if is_list and isinstance(v, list):
                nxt.extend(v)
            else:
                nxt.append(v)
        cur = nxt
    return cur


def is_nl(v):
    return isinstance(v, str) and (len(v) > 80 or (" " in v and len(v) > 30))


def verify(paths, tokens, obj):
    vals = []
    for sub in paths:
        vals.extend(resolve(obj, sub.strip()))
    vals = [v for v in vals if not is_nl(v)]
    corpus = json.dumps(vals, ensure_ascii=False, sort_keys=True) if vals else ""
    missing = [str(t) for t in tokens if str(t) not in corpus]
    return not missing, missing


def bind_entry(e):
    art = e.get("artifact") or ""
    tokens = [str(x) for x in (e.get("expect") or [])]
    if not tokens:
        return None, "no_expect"
    if not art.endswith(".json"):
        return None, "non_json"
    p = os.path.join(ROOT, art)
    if not os.path.isfile(p):
        return None, "no_file"
    obj = json.load(io.open(p, encoding="utf-8"))
    lv = list(leaves(obj))

    # 每个 token 找候选路径：值内含 token 的叶子；或作为 key 出现的父 dict
    cand = []
    for t in tokens:
        c = set()
        for path, v in lv:
            # 关键：排除自然语言值（resolver 会过滤掉它们），
            # 否则贪心会选到含 0.580 的中文解释句，自检时该值被过滤导致 fail。
            if is_nl(v):
                continue
            if t in ser(v):
                c.add(path)
        # key 形式：key 名本身即 token，父 dict 序列化含 key；父 dict 不是 NL
        for kp in parents(obj, t):
            pv = resolve(obj, kp)
            if all(not is_nl(x) for x in pv):
                c.add(kp)
        cand.append(c)
    if any(not c for c in cand):
        return None, "token_unlocatable:" + ",".join(
            t for t, c in zip(tokens, cand) if not c
        )

    # 贪心最小覆盖：每次选覆盖剩余 token 最多、路径数最少的组合
    remaining = set(range(len(tokens)))
    chosen = []
    while remaining:
        best = None
        for path in sorted(set().union(*[cand[i] for i in remaining])):
            covered = {i for i in remaining if path in cand[i]}
            if not covered:
                continue
            score = (len(covered), -len(path.split(".")))
            if best is None or score > best[0]:
                best = (score, path, covered)
        if best is None:
            return None, "no_cover"
        chosen.append(best[1])
        remaining -= best[2]
        if len(chosen) > 12:
            return None, "too_many_paths"

    ok, missing = verify(chosen, tokens, obj)
    if not ok:
        return None, "selfcheck_failed:" + ",".join(missing)
    return " / ".join(chosen), "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    doc = yaml.safe_load(io.open(REG, encoding="utf-8"))
    results = []
    for e in doc["entries"]:
        eid = e.get("id")
        if (
            e.get("status") == "superseded"
            or e.get("admissible_for_external_use") is False
        ):
            results.append((eid, "SKIP_RETRACTED", ""))
            continue
        if (
            e.get("expect_field_path")
            and e.get("field_path_status") != "unresolved：字段级比对尚未绑定"
        ):
            results.append((eid, "ALREADY_BOUND", str(e.get("expect_field_path"))[:60]))
            continue
        fp, why = bind_entry(e)
        if fp is None:
            results.append((eid, "UNBOUND:" + why, ""))
        else:
            results.append((eid, "BIND", fp))
            e["expect_field_path"] = fp
            e["field_path_status"] = (
                "bound_by_tools.bind_claim_fields 2026-11-18 (selfcheck field_match=True)"
            )
            e["evidence_grade"] = "structured_field_evidence_pending_audit"

    print("=== binding plan ===")
    for eid, st, fp in results:
        print("  %-42s %-16s %s" % (eid, st.split(":")[0], fp[:90]))
    n_ok = sum(
        1 for _, st, _ in results if st in ("BIND", "ALREADY_BOUND", "SKIP_RETRACTED")
    )
    print("\nready=%d/%d" % (n_ok, len(results)))

    if a.write:
        # 逐字段文本替换，保留 YAML 的复杂引号与注释
        text = io.open(REG, encoding="utf-8").read()
        bindmap = {eid: fp for eid, st, fp in results if st == "BIND"}
        for eid, fp in bindmap.items():
            pat = re.compile(
                r"(  - id: "
                + re.escape(eid)
                + r"\b.*?)(    expect_field_path: null\n)",
                re.S,
            )

            def repl(m):
                return (
                    m.group(1)
                    + "    expect_field_path: "
                    + json.dumps(fp, ensure_ascii=False)
                    + "\n"
                )

            text, n = pat.subn(repl, text)
            if n != 1:
                print("WARN replace count for %s = %d" % (eid, n))
            # 同时更新该条目的 field_path_status 与 evidence_grade
            blk = re.compile(
                r"(  - id: "
                + re.escape(eid)
                + r"\b.*?)(    field_path_status: )[^\n]*(\n)",
                re.S,
            )
            text, n2 = blk.subn(
                lambda m: m.group(1)
                + m.group(2)
                + json.dumps(
                    "bound_by_tools.bind_claim_fields 2026-11-18 (selfcheck field_match=True)",
                    ensure_ascii=False,
                )
                + m.group(3),
                text,
            )
            blk2 = re.compile(
                r"(  - id: "
                + re.escape(eid)
                + r"\b.*?)(    evidence_grade: )[^\n]*(\n)",
                re.S,
            )
            text, n3 = blk2.subn(
                lambda m: m.group(1)
                + m.group(2)
                + '"structured_field_evidence_pending_audit"'
                + m.group(3),
                text,
            )
        io.open(REG, "w", encoding="utf-8").write(text)
        print("WROTE", REG)


if __name__ == "__main__":
    main()
