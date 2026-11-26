# -*- coding: utf-8 -*-
"""挑战包自评脚本（无第三方依赖）。用法：python score.py submission.json

判定规则与 adt/replication.score 一致：只有 expected.json 里 `counted=true`
的指标参与 all_pass；`counted=false` 的指标容差已接近量级，只打印 INFO。
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(sub_path):
    exp = json.load(io.open(os.path.join(HERE, "expected.json"), encoding="utf-8"))
    sub = json.load(io.open(sub_path, encoding="utf-8"))
    got = sub.get("metrics") or {}
    rows, n_pass, near, n_counted = [], 0, 0, 0
    for m in exp["metrics"]:
        counted = m.get("counted", True)
        n_counted += 1 if counted else 0
        raw = got.get(m["name"])
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val is None:
            rows.append(dict(name=m["name"], status="MISSING" if counted else "INFO",
                             expected=m["value"], tol=m["tol"], got=None, delta=None,
                             counted=counted))
            continue
        delta = float(val) - float(m["value"])
        ok = abs(delta) <= float(m["tol"]) + 1e-12
        if counted:
            n_pass += 1 if ok else 0
            near += 1 if abs(delta) < 0.05 * float(m["tol"]) else 0
        rows.append(dict(name=m["name"],
                         status=("PASS" if ok else "FAIL") if counted else "INFO",
                         expected=m["value"], tol=m["tol"], got=float(val),
                         delta=round(delta, 6), counted=counted))
    total = n_counted
    # 2026-11-19：README 要求"交实现+环境指纹"，评分器必须真的查——否则文档与代码不一致
    env = sub.get("environment") or {}
    env_missing = [k for k in ("python", "rdkit", "numpy")
                   if not str(env.get(k) or "").strip()]
    impl = sub.get("implementation")
    if isinstance(impl, str):
        has_impl = bool(impl.strip())
    elif isinstance(impl, dict):
        files = impl.get("files")
        has_impl = bool(str(impl.get("code") or "").strip()
                        or str(impl.get("repo") or "").strip()
                        or (isinstance(files, list)
                            and [f for f in files if str(f or "").strip()])
                        or str(files or "").strip())
    else:
        has_impl = False
    prov_missing = ([] if has_impl else ["implementation"])
    prov_missing += ["environment." + k for k in env_missing]
    all_pass = (n_pass == total and total > 0)
    suspicious = bool(all_pass and near == total)
    verdict = ("pass_with_manual_review" if (all_pass and suspicious)
               else "pass" if all_pass else "fail")
    if all_pass and prov_missing:
        verdict = "numbers_only"
    out = dict(pack=exp.get("pack_id"), n_total=total, n_pass=n_pass,
               pass_rate=round(n_pass / float(total), 4) if total else 0.0,
               all_pass=all_pass, suspicious_identical=suspicious,
               verdict=verdict,
               verdict_note=("零偏差不等于造假：规范完全确定时零偏差是必然结果；"
                             "但也不等于独立复现成功——须人审实现代码后另行确认。"
                             "numbers_only = 数字对上但缺实现/环境指纹，不构成复现"),
               provenance=dict(implementation_present=has_impl,
                               environment_missing=env_missing,
                               missing=prov_missing,
                               complete=not prov_missing),
               rows=rows)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if verdict in ("pass", "pass_with_manual_review"):
        return 0
    return 2 if verdict == "numbers_only" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "submission.json"))
