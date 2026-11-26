# -*- coding: utf-8 -*-
"""命令行入口：python -m adt.cli <子命令>

  normalize   Gate 0.5 状态标准化（产出 compounds.csv）
  saturate    全端点饱和扫描（QA gate #11）
  bt          跑 BioTransformer（REST API，2 POST/min）
  xeno-prep   生成 XenoSite 待提交清单（无免费 API，只能人工跑）
  xeno-ingest 把人工读回的结果并入长表

输入约定：两列 TSV / 空白分隔，`ID<TAB>SMILES`；以 # 开头的行忽略。
"""

import argparse
import csv
import io
import json
import os
import statistics as st
import sys

from . import schema
from .normalize import standardize
from .saturation import load_wide, scan, write_report, blocked_endpoints


def read_compounds(path):
    """id<TAB>smiles[<TAB>stereo]

    2026-11-19：第三列 `defined|racemic` 是**显式立体声明**。没有它，消旋药
    （华法林/普萘洛尔/酮康唑/红霉素/环孢素）会被输入闸门永久拦死——提示语却在
    要求用户"声明是消旋体还是立体缺失"，即承诺了一条不存在的门。
    """
    out = []
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            if len(parts) < 2:
                continue
            stereo = parts[2].strip().lower() if len(parts) > 2 else ""
            if stereo not in ("defined", "racemic", "undefined"):
                stereo = ""
            out.append(
                dict(
                    compound_id=parts[0].strip(),
                    input_smiles=parts[1].strip(),
                    stereo=stereo,
                )
            )
    return out


def load_compounds_csv(path, fmt="auto"):
    """兼容两种输入：schema compounds.csv（带表头）与 normalize 同款 TSV
    （id\tsmiles，无表头）。

    C50：此前只认 CSV——给 TSV 时 DictReader 把数据行当表头，**静默空转**
    （bt 对 APAP 的 PHASEII 实测 0 行零告警）。现按首行是否含逗号分流，
    并在空结果时显式警告。
    C61（评估 P2-15）：嗅探是启发式（首行含逗号的 TSV 会误判），
    因此提供显式 `fmt`（auto|csv|tsv），由 CLI --format 传入。
    """
    fmt = (fmt or "auto").lower()
    with io.open(path, encoding="utf-8-sig") as fh:
        first = fh.readline()
        fh.seek(0)
        if fmt == "csv" or (fmt == "auto" and "," in first):
            rows = list(csv.DictReader(fh))
        else:
            # TSV 视为已标准化输入：calc_smiles = input_smiles（无硬门信息，
            # 走 normalize 才有完整门控）
            rows = [
                dict(
                    compound_id=p[0].strip(),
                    input_smiles=p[1].strip(),
                    calc_smiles=p[1].strip(),
                    hard_gate_problems="",
                )
                for p in (ln.rstrip("\n").split("\t") for ln in fh)
                if len(p) >= 2 and p[0].strip()
            ]
    if not rows:
        print("[load] ⚠ %s 解析出 0 个分子（格式不匹配或文件为空）" % path)
    return rows


def load_released_compounds(path, tag="", fmt="auto"):
    """公共层：加载分子并剔除硬门拦截的行（C44 教训——过滤逻辑不能在各
    cmd 复制粘贴：bt 修了 chembl 漏了。所有对外分发类命令一律走这里）。"""
    all_c = load_compounds_csv(path, fmt=fmt)
    comps = [c for c in all_c if not c.get("hard_gate_problems")]
    if len(comps) < len(all_c):
        print(
            "[%s] 硬门拦截 %d 个分子，已排除"
            % (tag or "dispatch", len(all_c) - len(comps))
        )
    return comps


def check_measurements(path, allow_invalid=False, tag="validate"):
    """C55（评估报告 P1-6）：长表契约校验的**唯一强制入口**。

    v2.1.3 加固了 schema.validate 的判别力（C48/C49），但 CLI 十个子命令
    无一调用它——校验器成了摆设。现在 reliab / ledger / sensitize 入口统一
    走本函数：problems>0 即 fail-fast，`--allow-invalid` 可显式跳过（此时
    产物不得用于报告，措辞封顶另行提示）。
    """
    rows = schema.read_measurements(path)
    problems = schema.validate(rows)
    if problems:
        print("[%s] ⚠ 数据契约问题 %d 条（%s）" % (tag, len(problems), path))
        for p in problems[:10]:
            print("   " + p)
        if len(problems) > 10:
            print("   ...（其余 %d 条略）" % (len(problems) - 10))
        if not allow_invalid:
            raise SystemExit(
                "[%s] 长表校验未通过，已停止。修复数据，或显式加 --allow-invalid "
                "（跳过后产物不得用于报告）" % tag
            )
    return rows


def cmd_cstar(a):
    """Cost-boundary diagnosis: solve c* per endpoint from a keystone results file.

    The library implementation lives in :mod:`adt.cost_boundary`; this command
    is the CLI front-end so that users can price a decision design on their own
    endpoints without going through the manuscript's scripts.
    """
    from .cost_boundary import render_markdown, solve_all, write_csv

    results = a.results
    d = json.load(io.open(results, encoding="utf-8"))
    eps = [x for x in a.endpoints.split(",") if x]
    rows = solve_all(d["per_run"], eps, a.baseline)
    if not rows:
        print("[cstar] no endpoint produced a solution; check --results and --endpoints")
        return 2
    os.makedirs(os.path.dirname(a.out_csv) or ".", exist_ok=True)
    write_csv(rows, a.out_csv)
    md = render_markdown(
        rows, a.title, os.path.relpath(results), interim=a.interim,
        generator="adt cstar", baseline=a.baseline,
    )
    os.makedirs(os.path.dirname(a.out_md) or ".", exist_ok=True)
    io.open(a.out_md, "w", encoding="utf-8", newline="\n").write(md)
    print(
        "[cstar] "
        + " | ".join(
            "%s=%.4f[%.4f,%.4f]" % (r["endpoint"], r["c_star"], r["ci_lo"], r["ci_hi"])
            for r in rows
        )
    )
    print("[cstar] -> %s, %s" % (a.out_md, a.out_csv))
    return 0


def cmd_normalize(a):
    comps = read_compounds(a.input)
    from . import pubchem as PB  # R26：输入层硬化（InChIKey 锚定 + 立体声明）

    rows, gate = [], []
    for c in comps:
        try:
            r = standardize(c["input_smiles"])
        except Exception as exc:
            print("[normalize] %s 失败: %s" % (c["compound_id"], exc), file=sys.stderr)
            gate.append(
                dict(
                    compound_id=c["compound_id"],
                    status="fail",
                    reasons="SMILES 不可解析：%s" % exc,
                    inchikey_input="",
                    inchikey_calc="",
                )
            )
            continue
        from .normalize import charges_and_ph

        ph = charges_and_ph(c["input_smiles"])
        r["compound_id"] = c["compound_id"]
        r["note"] = ph.get("note", "")
        # 输入闸门：对**用户输入的结构**判定（不是标准化后的），因为立体丢失
        # 往往就发生在标准化/去盐之前的那一步（badcase 5：Terfenadine/Digoxin 丢手性）。
        racemic = c.get("stereo") == "racemic"
        gv = PB.validate_entry(
            c["compound_id"], c["input_smiles"], declared_racemic=racemic
        )
        gate.append(
            dict(
                compound_id=c["compound_id"],
                status=gv["status"],
                reasons="；".join(gv["reasons"]),
                inchikey_input=gv["inchikey"] or "",
                inchikey_calc=r.get("inchikey", "") or "",
                stereo_state=gv.get("stereo_state", ""),
            )
        )
        rows.append(r)
        warn = (
            ("  << HARD GATE: %s（禁止分发到任何源）" % r["hard_gate_problems"])
            if r["hard_gate_problems"]
            else (
                "  << 状态敏感: %s" % r["state_sensitive"]
                if r["state_sensitive"]
                else ""
            )
        )
        if gv.get("stereo_state") == "racemic_declared":
            warn += "  << RACEMATE: 已声明消旋体/立体未定；结论不得外推到单一对映体"
            r["note"] = "stereo=racemic_declared（结论仅对消旋体成立）；" + (
                r.get("note") or ""
            )
        if gv["status"] != "ok":
            warn += "  << INPUT GATE: %s" % "；".join(gv["reasons"])
        print(
            "[normalize] %-3s %-12s %s%s"
            % (c["compound_id"], r["formula"], r["state_flag"], warn)
        )
    p = os.path.join(a.outdir, "compounds.csv")
    n = schema.write_compounds(p, rows)
    print("[normalize] %d 个分子 -> %s" % (n, p))

    # 闸门报告必须落盘：后续 fetch/decision 只认 inchikey，不认名字
    gp = os.path.join(a.outdir, "input_gate.csv")
    os.makedirs(a.outdir, exist_ok=True)
    with io.open(gp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "compound_id",
                "status",
                "reasons",
                "inchikey_input",
                "inchikey_calc",
                "stereo_state",
            ],
        )
        w.writeheader()
        for g in gate:
            w.writerow(g)
    blocked = [g for g in gate if g["status"] != "ok"]
    if blocked:
        print(
            "[normalize] ⚠ 输入闸门拦截 %d/%d：%s"
            % (
                len(blocked),
                len(gate),
                ", ".join(
                    "%s(%s)" % (b["compound_id"], b["reasons"][:24])
                    for b in blocked[:6]
                ),
            ),
            file=sys.stderr,
        )
        print(
            "[normalize] ⚠ 以上分子**不得进入已发布流水线**（名称→SMILES 只能作交互辅助，"
            "须由 InChIKey 锚定并声明立体）-> %s" % gp,
            file=sys.stderr,
        )
        if getattr(a, "strict_input", False):
            print(
                "[normalize] --strict-input：输入闸门有拦截，命令失败", file=sys.stderr
            )
            sys.exit(3)
    else:
        print(
            "[normalize] 输入闸门：%d/%d 通过（InChIKey 锚定 + 立体已声明）"
            % (len(gate), len(gate))
        )


def cmd_saturate(a):
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.wide], argv=sys.argv)
    rows = load_wide(a.wide)
    diag = []
    recs = scan(rows, diag=diag)
    if diag:
        print(
            "[saturate] ⚠ %d 个列因数值样本 <3 无法判定（本批该端点 QA gate 缺席）：%s"
            % (len(diag), [d["endpoint"] for d in diag][:10])
        )
    p = os.path.join(
        a.outdir, os.path.basename(a.wide).rsplit(".", 1)[0] + "_saturation.csv"
    )
    write_report(p, recs)
    sat = [r for r in recs if r["verdict"] == "saturated_in_set"]
    bad = [r for r in recs if r["verdict"] == "invalid"]
    usable = [r for r in recs if r["verdict"] == "usable"]
    print(
        "[saturate] %d 个数值端点：usable %d / 集合内无区分度 %d / 数值无效 %d -> %s"
        % (len(recs), len(usable), len(sat), len(bad), p)
    )
    if bad:
        print(
            "[saturate] ⚠ 连阈值都不能用（invalid）：%s" % [r["endpoint"] for r in bad]
        )
    blocked = sorted(blocked_endpoints(recs))
    if blocked:
        print(
            "[saturate] 不可用于决策的端点（%d 个，reliab 将据此弃权）：%s"
            % (len(blocked), blocked[:10])
        )
    if getattr(a, "mark_measurements", ""):
        _mark_measurements(
            a.mark_measurements, a.outdir, {r["endpoint"] for r in sat}, set(blocked)
        )
    print(
        "[saturate] 不能排序但阈值仍有效（saturated_in_set）前 12 个：%s"
        % [r["endpoint"] for r in sat[:12]]
    )
    print(
        "[saturate] 可用于排序（usable）前 12 个：%s"
        % [r["endpoint"] for r in usable[:12]]
    )


def _write_batch_qa(meta, outdir, tag=""):
    """B1 批级 QA 落盘（bt / web 各适配器共用）。"""
    qa = (meta or {}).get("batch_qa")
    if not qa:
        return ""
    p = os.path.join(outdir, "batch_qa.csv")
    cols = [
        "source",
        "option",
        "control",
        "observed",
        "expected_min",
        "expected_max",
        "drift",
    ]
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(qa)
    n_drift = len((meta or {}).get("batch_drift") or [])
    print(
        "[%s] 批级 QA（B1 对照）%d 条 -> %s%s"
        % (
            tag or "qa",
            len(qa),
            p,
            ("  << BATCH_DRIFT %d 条，跨批比较降级" % n_drift) if n_drift else "",
        )
    )
    return p


def _load_registry_source(name, path="references/02_source_registry.yaml"):
    """从 registry 取某个源的登记项（化学类白名单/限流等）。

    D2：路径经 resref 解析，安装态从包内 _data/ 读；显式路径不存在时抛
    ReferenceNotFound 而不是返回 {}（返回空字典=把"找不到判据"静默降级为
    "该源无任何限制"，是这一层最危险的失败方式）。
    """
    import yaml
    from . import resref

    if not path:
        path = resref.resolve("02_source_registry.yaml")
    elif not os.path.exists(path):
        path = resref.resolve("02_source_registry.yaml", explicit=path)
    d = yaml.safe_load(io.open(path, encoding="utf-8")) or {}
    for s in d.get("sources") or []:
        if s.get("name") == name:
            return s
    return {}


# D2：这些 argparse 字段历史上以 cwd 相对路径作默认值，共 30 处。
# 在 main() 里统一解析一次，下游拿到的永远是存在的绝对路径。
_REF_ARGS = ("rules", "registry", "priors", "config")


def _resolve_ref_args(a):
    """把 `references/x.yaml` 形式的默认值解析成真实可读路径。

    解析失败即 SystemExit（而不是让下游 open() 抛裸异常或静默降级）。
    显式给的路径（用户自己写 --rules foo.yaml）保持原样，不做任何回落。
    """
    from . import resref

    for fld in _REF_ARGS:
        v = getattr(a, fld, None)
        if not isinstance(v, str) or not v.strip():
            continue
        try:
            setattr(a, fld, resref.resolve_arg(v))
        except resref.ReferenceNotFound as e:
            raise SystemExit("[规则文件] %s" % (e,))
    return a


def cmd_web(a):
    """网页源适配器统一入口（v2.2：admet_ai / protox3 / admetlab3 / vnn 已收编）。"""
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input, a.registry], argv=sys.argv)
    comps = load_released_compounds(a.input, tag="web", fmt=a.format)
    if not comps:
        print("[web] 无可用分子（全部被硬门拦截或文件为空）")
        return
    reg = _load_registry_source(a.source, a.registry)
    src = a.source
    if src == "admet_ai":
        from .adapters.admet_ai import AdmetAIAdapter as K

        ad = K(
            reg,
            raw_dir=a.outdir,
            local=getattr(a, "local", False),
            local_python=getattr(a, "local_python", ""),
        )
    elif src == "protox3":
        from .adapters.protox3 import ProtoxAdapter as K

        ad = K(reg, raw_dir=a.outdir)
    elif src == "admetlab3":
        from .adapters.admetlab3 import AdmetlabAdapter as K

        ad = K(reg, raw_dir=a.outdir)
    elif src == "vnn":
        from .adapters.vnn import VnnAdapter as K

        ad = K(reg, raw_dir=a.outdir)
    else:
        raise SystemExit("未收编的源：%s" % src)

    if a.prepare_only:
        if not hasattr(ad, "prepare"):
            raise SystemExit("%s 无人工桥（prepare）" % src)
        ad.prepare(comps, a.outdir)
        return

    res = ad.run(comps, chemical_class=a.chemical_class)
    if res.meta.get("skipped"):
        print("[web] 该化学类被 registry 登记为不可用：%s" % res.meta["skipped"])
        return
    p = os.path.join(a.outdir, "measurements_%s.csv" % src)
    n = schema.write_measurements_checked(p, res.measurements)
    print("[web] %s：%d 行长表 -> %s" % (src, n, p))
    if res.meta.get("n_matched") is not None:
        print(
            "[web] 对齐 %s/%s 个分子"
            % (res.meta.get("n_matched"), res.meta.get("n_rows"))
        )
    if res.meta.get("unmapped_columns"):
        print(
            "[web] 未映射列 %d 个（不入长表，仅留在原始 CSV）：%s"
            % (res.meta.get("n_unmapped_columns"), res.meta["unmapped_columns"][:8])
        )
    if res.meta.get("errors"):
        print(
            "[web] 错误 %d 条：%s"
            % (len(res.meta["errors"]), [e["compound_id"] for e in res.meta["errors"]])
        )
    _write_batch_qa(res.meta, a.outdir, tag="web")


def cmd_bt(a):
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    comps = load_released_compounds(a.input, tag="bt", fmt=a.format)
    from .adapters.biotransformer import BioTransformerAdapter

    engine = getattr(a, "engine", "auto")
    ad = None
    if engine in ("auto", "biotransformer"):
        bt = BioTransformerAdapter(verbose=True, options=a.options, steps=a.steps)
        # 2026-11-19：先做可达性预检，避免"源不通"被误读成"程序卡死"
        ok = getattr(a, "skip_preflight", False) or bt.preflight()
        if ok:
            ad = bt
        elif engine == "biotransformer":
            print(
                "[bt] ✗ BioTransformer 不可达（%s）：本次不产出任何代谢产物。"
                "这是**源不可用**，不是「该分子无代谢」；请勿把 0 产物读成阴性。"
                % "https://biotransformer.ca",
                file=sys.stderr,
            )
            print(
                "[bt] 跳过命令（rc=3）；确认网络后重试，"
                "或加 --engine sygma 用本地引擎，或改用 readback 回填人工结果。",
                file=sys.stderr,
            )
            sys.exit(3)
        else:
            # auto：降级到本地 SyGMa。必须明说换了引擎，不能让下游以为是
            # BioTransformer 的结果——两者规则覆盖面不同。
            print(
                "[bt] BioTransformer 不可达 → 降级到本地 SyGMa 引擎"
                "（Ridder & Wagener 2008, J Cheminform 1:3）。"
                "产物 source=sygma_local，**不是** BioTransformer 结果，"
                "不得混用/互换。",
                file=sys.stderr,
            )
    if ad is None:
        from .adapters.sygma_local import SyGMaAdapter

        ad = SyGMaAdapter(
            verbose=True, cycles=getattr(a, "cycles", 1), top=getattr(a, "top", 25)
        )
        if not ad.preflight():
            print(
                "[bt] ✗ 本地 SyGMa 不可用：python -m pip install sygma "
                "--no-deps --no-build-isolation（且 setuptools<81）。",
                file=sys.stderr,
            )
            sys.exit(3)
    res = ad.run(comps, chemical_class=a.chemical_class)
    tag = getattr(ad, "name", "biotransformer")
    mp = os.path.join(a.outdir, "measurements_%s.csv" % tag)
    if res.measurements:
        n = schema.write_measurements_checked(mp, res.measurements)
        print("[bt] %d 行长表 -> %s" % (n, mp))
    else:
        print("[bt] 引擎 %s 不产出 measurement 行（只出代谢产物）" % tag)
    if res.metabolites:
        metp = os.path.join(a.outdir, "metabolites_%s.csv" % tag)
        schema.write_metabolites_checked(metp, res.metabolites)
        print("[bt] %d 个代谢产物 -> %s" % (len(res.metabolites), metp))
    else:
        print("[bt] 0 个代谢产物（注意：0 ≠ 无代谢，见适配器 docstring 的覆盖证据）")
    if res.meta.get("errors"):
        print(
            "[bt] 错误 %d 条：%s"
            % (len(res.meta["errors"]), [e["compound_id"] for e in res.meta["errors"]])
        )
    _write_batch_qa(res.meta, a.outdir, tag="bt")


def cmd_xeno_prepare(a):
    from .adapters.xenosite import XenoSiteAdapter, MODELS

    comps = load_compounds_csv(a.input, fmt=a.format)
    ad = XenoSiteAdapter(verbose=True)
    models = a.models or list(MODELS)
    ad.prepare(comps, a.outdir, models)


def cmd_xeno_ingest(a):
    from .adapters.xenosite import XenoSiteAdapter

    ad = XenoSiteAdapter(verbose=True)
    res = ad.ingest(a.file)
    p = os.path.join(a.outdir, "measurements_xenosite.csv")
    n = schema.write_measurements_checked(p, res.measurements)
    print("[xeno] %d 行 -> %s" % (n, p))


def cmd_chembl(a):
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    comps = load_released_compounds(a.input, tag="chembl", fmt=a.format)
    from .adapters.chembl import ChEMBLAdapter

    ad = ChEMBLAdapter(
        verbose=True,
        threshold=a.threshold,
        max_neighbors=getattr(a, "max_neighbors", 40),
    )
    res = ad.run(comps, chemical_class=a.chemical_class)
    p = os.path.join(a.outdir, "measurements_chembl.csv")
    n = schema.write_measurements_checked(p, res.measurements)
    print("[chembl] %d 行 -> %s" % (n, p))
    for r in res.measurements:
        if r["endpoint"] == "chembl_neighbors_tanimoto%d" % a.threshold:
            print("   %s 邻居数 %s" % (r["compound_id"], r["value"]))


def _load_rules(path):
    import yaml

    d = yaml.safe_load(io.open(path, encoding="utf-8"))
    rules = {}
    for e in d.get("endpoints", []):
        rules[e["id"]] = e
    return rules


def cmd_advisory_check(a):
    """非阻断告警：数值结论缺 uncertainty/CI（红线6 提示，不改写入契约）。"""
    rows = schema.read_measurements(a.input)
    w = schema.advisory_warnings(rows)
    print("[advisory-check] %d 行，%d 条非阻断告警" % (len(rows), len(w)))
    for x in w[:30]:
        print("  " + x)
    if len(w) > 30:
        print("  ...（其余 %d 条略）" % (len(w) - 30))
    # 告警不改变退出码：与写入契约分离，避免历史数据迁移被误阻断


def cmd_validate(a):
    """C11 / C1-a（2026-11-04）：validate 不再吞问题，以返回码表达结果。

    旧实现 `allow_invalid=True` + 只打印，使「校验命令」对坏数据恒 rc=0，
    CI 与上层脚本无法据此阻断；且随后会把同一批坏数据原样写出，等于
    把校验器变成了一个有副作用的摆设。现在：不写出任何产物，
    有问题即 SystemExit(3)（3 = 数据契约错误，与 --help 的其它 rc 区分）。
    """
    rows = schema.read_measurements(a.input)
    probs = schema.contract_problems(rows)
    print("[validate] %d 行 / %d 个问题" % (len(rows), len(probs)))
    for x in probs[:10]:
        print("   " + x)
    if not probs:
        print(
            "[validate] OK —— 长表符合契约（predicted/measured 均有值，"
            "measured 均有 provenance）"
        )
        return 0
    print("[validate] 契约未通过；不再写出任何产物（C11）。", file=sys.stderr)
    raise SystemExit(3)


def _mark_measurements(src, outdir, non_ranking, invalid):
    """把饱和扫描结论写回长表（C62，评估 P3-18）。

    v2.1 起 `saturated` 是合法的 domain_flag，但**没有任何代码路径会写它**——
    契约与实现脱节。这里补上唯一正确的写入路径：
      predicted 且端点在 saturated_in_set -> saturated（可读数值，不可排序）
      predicted 且端点在 invalid          -> error（数值越物理边界，禁止被下游使用）
    """
    from .endpoints import canonical_name

    def _c(x):
        return canonical_name(x) or str(x)

    # 宽表列名（DILI/AMES）与长表端点名（dili/ames）必须先归一，否则匹配恒空
    sat_c = {_c(x) for x in non_ranking}
    inv_c = {_c(x) for x in invalid}
    rows = schema.read_measurements(src)
    n_sat = n_bad = 0
    for r in rows:
        if r.get("domain_flag") != "predicted":
            continue
        ep = _c(r.get("endpoint"))
        if ep in sat_c:
            r["domain_flag"] = "saturated"
            n_sat += 1
        elif ep in inv_c:
            r["domain_flag"] = "error"
            old = (r.get("note") or "").strip()
            r["note"] = (old + " | 饱和扫描判 invalid：数值越物理边界，禁止使用").strip(
                " |"
            )
            n_bad += 1
    p = os.path.join(outdir, "measurements_saturated.csv")
    schema.write_measurements_checked(p, rows)
    print(
        "[saturate] 长表标记：saturated %d 行 / error %d 行 -> %s" % (n_sat, n_bad, p)
    )
    print(
        "[saturate] 注意：saturated 行仍可读数值、可用于绝对阈值，"
        "但**不得用于排序**；下游 reliab 会自动把 confidence 降为 low"
    )
    return p


def _load_sat_sets(path):
    """读饱和扫描产物 -> (不能排序集合, 连阈值都不能用集合)。"""
    non_ranking, blocked = set(), set()
    if path and os.path.exists(path):
        with io.open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r["verdict"] == "saturated_in_set":
                    non_ranking.add(r["endpoint"])
                elif r["verdict"] == "invalid":
                    blocked.add(r["endpoint"])
    return non_ranking, blocked


def cmd_coverage(a):
    """端点级覆盖率矩阵（v2.3）：源 × 端点有没有可判值。"""
    from .manifest import write_manifest
    from . import coverage

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows = check_measurements(a.input, a.allow_invalid, tag="coverage")
    matrix, summ = coverage.build(rows, a.min_coverage)
    p = coverage.write(os.path.join(a.outdir, "coverage_matrix.csv"), matrix)
    print("[coverage] %d 个 源×端点 组合 -> %s" % (len(matrix), p))
    for src, d in sorted(summ["by_source"].items()):
        print(
            "   %-14s 覆盖 %.3f  可判端点 %d/%d  全零端点 %d  -> %s"
            % (
                src,
                d["coverage"],
                d["n_usable_endpoints"],
                d["n_endpoints"],
                d["n_zero_endpoints"],
                d["verdict"],
            )
        )
    if summ["zero_endpoints"]:
        print(
            "[coverage] ⚠ 所有源都无可判值的端点（本化学类不可判）：%s"
            % summ["zero_endpoints"]
        )
    zero = [r for r in matrix if r["flag"] == "no_prediction"]
    if zero:
        print(
            "[coverage] 无任何可判值的 源×端点 组合 %d 个（只能弃权，不得读作阴性）"
            % len(zero)
        )


def cmd_background(a):
    """稳健 Z 背景归一化：目标分子相对背景化学型的异常度（移植 E6a）。"""
    from .manifest import write_manifest
    from . import background

    write_manifest(
        a.outdir, inputs=[a.input] + ([a.bg] if a.bg else []) + [a.rules], argv=sys.argv
    )
    rows = check_measurements(a.input, a.allow_invalid, tag="background")
    bg_rows = None
    if a.bg and not a.within_set:
        bg_rows = check_measurements(a.bg, a.allow_invalid, tag="background-bg")
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    out = background.build(
        rows, bg_rows, rules, floor=a.floor, min_bg=a.min_bg, within_set=a.within_set
    )
    p = background.write(os.path.join(a.outdir, "background_z.csv"), out)
    summ = background.summarize(out)
    mode = "within-set（留一法）" if (a.within_set or not a.bg) else "跨化学型背景"
    print("[background] 模式=%s，%d 条 -> %s" % (mode, len(out), p))
    print(
        "[background] flag 分布：%s"
        % ", ".join("%s=%d" % (k, v) for k, v in sorted(summ.items()))
    )
    if summ.get("OUTLIER"):
        print("[background] 相对背景异常（|z|≥2）%d 条" % summ["OUTLIER"])
    n_conf = sum(1 for r in out if "SCALE_CONFLICT" in (r.get("qc_flag") or ""))
    if n_conf:
        print(
            "[background] ⚠ 尺度冲突 %d 条（z_mad 与 z_sd 差>1.5）：不得静默取一个值"
            % n_conf
        )
    if summ.get("BG_TOO_FEW"):
        print("[background] 背景不足 %d 条（n<min_bg）：不计算 Z" % summ["BG_TOO_FEW"])
    if summ.get("missing"):
        print("[background] 缺失 %d 条（域外/失败）：缺失不赋分" % summ["missing"])


def cmd_rank(a):
    """bootstrap 名次区间 + 并列集合（移植 E7c）；默认拒绝 underpowered 排名。"""
    from .manifest import write_manifest
    from . import rank as rankmod

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows = list(csv.DictReader(io.open(a.input, encoding="utf-8-sig")))
    out, pairs, status = rankmod.build(
        rows,
        id_col=a.id_col,
        group_col=a.group_col,
        score_col=a.score_col,
        bootstrap=a.bootstrap,
        thr_low=a.thr_low,
        thr_high=a.thr_high,
        max_cluster_frac=a.max_cluster_frac,
    )
    if status["mode"] == "refused" and not a.force:
        print("[rank] 拒绝排名：%s" % "；".join(status["reasons"]))
        print(
            "[rank] 只允许三态 + Pareto（见 desire）；如需演示区间请加 --force（产物标 OVERRIDE）"
        )
        p = rankmod.write_result(os.path.join(a.outdir, "rank.csv"), [])
        print("[rank] 已写空表 %s（refused）" % p)
        return
    if a.force and not status["ok"]:
        for r in out:
            r["note"] = (r["note"] + " | OVERRIDE：underpowered，仅演示").strip(" |")
        print("[rank] ⚠ --force 覆盖：%s" % "；".join(status["reasons"]))
        print("[rank] 产物标 OVERRIDE，**不得作为正式排名或论文结论**")
    p = rankmod.write_result(os.path.join(a.outdir, "rank.csv"), out)
    pp = rankmod.write_pairs(os.path.join(a.outdir, "rank_pairs.csv"), pairs)
    n_tie = len({r["tie_group"] for r in out if r["tie_group"]})
    print(
        "[rank] %d 个分子 × %d 个轴，bootstrap=%d -> %s"
        % (status["n_compounds"], status["n_groups"], a.bootstrap, p)
    )
    print("[rank] 并列集合 %d 组 -> %s" % (n_tie, pp))
    for r in [x for x in out if x["median_rank"] != ""][:5]:
        print(
            "   %-10s 名次中位 %.1f [%.1f–%.1f] %s"
            % (
                r["compound_id"],
                r["median_rank"],
                r["rank_p05"],
                r["rank_p95"],
                ("并列 " + r["tie_group"]) if r["tie_group"] else "",
            )
        )


def cmd_benchmark(a):
    """独立分类基准（移植 E8）：AUROC/AUPRC + 聚类 bootstrap + 消融。"""
    from .manifest import write_manifest
    from . import benchmark as bench

    if a.demo:
        pred, truth, clusters = bench.demo_data()
        print(
            "[benchmark] ⚠ DEMO 模式：合成真值，仅验证指标与消融代码，**不得作科学结论**"
        )
    else:
        if not a.predictions or not a.truth:
            sys.exit(
                "[benchmark] 非 demo 模式必须给 --predictions 与 --truth（实测真值）"
            )
        pred = list(csv.DictReader(io.open(a.predictions, encoding="utf-8-sig")))
        if getattr(a, "truth_format", "native") == "tdc":
            if not a.tdc_endpoint:
                sys.exit("[benchmark] --truth-format tdc 必须给 --tdc-endpoint")
            truth, tmeta = bench.load_tdc_truth(
                a.truth,
                a.tdc_endpoint,
                id_col=a.tdc_id_col or None,
                y_col=a.tdc_y_col or None,
            )
            print(
                "[benchmark] TDC 真值：%d 条（id 列=%s，标签列=%s，端点=%s）"
                % (tmeta["n"], tmeta.get("id_col"), tmeta.get("y_col"), a.tdc_endpoint)
            )
            if tmeta["n"] == 0:
                print(
                    "[benchmark] ⚠ TDC 文件未解析出任何带标签的行（列名或端点不匹配）"
                )
        else:
            truth = list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        clusters = (
            list(csv.DictReader(io.open(a.clusters, encoding="utf-8-sig")))
            if a.clusters
            else []
        )
        # Bemis-Murcko 骨架簇（TDC 标准切分）：随机切分会因类似物泄漏虚高 AUROC
        if getattr(a, "scaffold_from", ""):
            comps = load_compounds_csv(a.scaffold_from, fmt="auto")
            clusters = bench.scaffold_clusters(comps)
            n_scaf = len({r["cluster"] for r in clusters})
            print(
                "[benchmark] 骨架簇 %d 个（%d 个分子，Bemis-Murcko）"
                % (n_scaf, len(clusters))
            )
            if getattr(a, "split", False):
                sp, sinfo = bench.scaffold_split(clusters)
                sp_path = os.path.join(a.outdir, "scaffold_split.csv")
                os.makedirs(a.outdir, exist_ok=True)
                with io.open(sp_path, "w", encoding="utf-8-sig", newline="") as fh:
                    w = csv.DictWriter(
                        fh,
                        fieldnames=["compound_id", "cluster", "split"],
                        extrasaction="ignore",
                    )
                    w.writeheader()
                    w.writerows(sp)
                print("[benchmark] 整簇切分 -> %s  %s" % (sp_path, sinfo["sizes"]))
                if sinfo["degenerate"]:
                    print(
                        "[benchmark] ⚠ %s（空集：%s）——本批**不能**做三集验证，"
                        "只能用外部化学类做外部验证"
                        % (sinfo["note"], "、".join(sinfo["empty_splits"]))
                    )
        # 真值守卫：实测真值必须可溯源（C49 同源）。空值不算"测了"。
        filled = [t for t in truth if str(t.get("truth_value") or "").strip() != ""]
        if not filled:
            print(
                "[benchmark] ⚠ truth 里没有任何非空 truth_value——等于没测，"
                "结果会是空/自检级，勿解读"
            )
        missing_prov = sum(
            1 for t in filled if not str(t.get("provenance_url") or "").strip()
        )
        if missing_prov:
            print(
                "[benchmark] ⚠ %d/%d 条真值有数值但缺 provenance_url——"
                "真值必须可溯源（见 references/truth_contract.md），"
                "否则不具备 measured 资格，结果仅供流程自检"
                % (missing_prov, len(filled))
            )
        write_manifest(
            a.outdir,
            inputs=[x for x in (a.predictions, a.truth, a.clusters, a.rules) if x],
            argv=sys.argv,
        )
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    out, summ, tables = bench.build(
        pred, truth, rules, clusters, B=a.bootstrap, demo=a.demo, return_tables=True
    )
    p = bench.write(os.path.join(a.outdir, "benchmark.csv"), out)
    ntab = (
        bench.write_calibration_tables(
            os.path.join(a.outdir, "calibration_table.csv"), tables
        )
        if tables
        else 0
    )
    print("[benchmark] %d 个端点 -> %s" % (len(out), p))
    if ntab:
        print(
            "[benchmark] 校准分箱表 %d 行 -> %s"
            % (ntab, os.path.join(a.outdir, "calibration_table.csv"))
        )
    if summ["mean_auroc"] is not None:
        print(
            "[benchmark] 平均 AUROC %.3f（%d 个可算端点，%d 对）"
            % (summ["mean_auroc"], summ["n_auroc"], summ["n_pairs"])
        )
    for r in out:
        if isinstance(r["auroc"], float):
            print(
                "   %-12s AUROC %.3f [%.3f–%.3f]  AUPRC %s  中位-均值Δ %s  覆盖 %.0f%%"
                % (
                    r["endpoint"],
                    r["auroc"],
                    r["auroc_p05"],
                    r["auroc_p95"],
                    r["auprc"],
                    r["delta_median_vs_mean"],
                    r["coverage"] * 100,
                )
            )
    # 校准（Van Calster 2019）：判别力 ≠ 概率可信，必须分开报
    cal_ok = [r for r in out if r.get("cal_flag") in ("acceptable", "poor")]
    if cal_ok:
        print("[benchmark] 校准（概率量纲端点 %d 个）：" % len(cal_ok))
        for r in cal_ok:
            print(
                "   %-12s Brier %s  BSS %s  O:E %s  slope %s  intercept %s  "
                "ECE %s  → %s"
                % (
                    r["endpoint"],
                    r["brier"],
                    r["brier_skill"],
                    r["oe"],
                    r["cal_slope"],
                    r["cal_intercept"],
                    r["ece"],
                    r["cal_flag"],
                )
            )
            if r["cal_flag"] == "poor":
                print("       ↳ %s" % r["cal_note"])
    else:
        print(
            "[benchmark] 校准：本批无可评估的概率量纲端点"
            "（非概率量纲不得做校准——如 DrugBank percentile 不是概率）"
        )
    if summ["n_pairs"] < 30:
        print(
            "[benchmark] ⚠ 对照 %d 对 <30：只能作流程自检，不足以支撑统计结论"
            % summ["n_pairs"]
        )
    if not a.demo:
        print(
            "[benchmark] 提醒：真值必须是实测（domain_flag=measured）；"
            "预测-伪真值循环不算验证。"
        )


def cmd_tier(a):
    """运行档位 + 项目级结论封顶（T1/T2/T3），并纳入 PROBAST 偏倚风险。"""
    from . import tiers, governance
    from . import benchmark as bench

    recs = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    st = tiers.stats_from_reliability(recs)
    has_bm = bool(a.benchmark and os.path.exists(a.benchmark))
    bench_ok = False
    bm = []
    if has_bm:
        bm = list(csv.DictReader(io.open(a.benchmark, encoding="utf-8-sig")))
        bench_ok = any(
            r.get("auroc") not in ("", None) and "DEMO" not in (r.get("note") or "")
            for r in bm
        )
    has_cov = bool(a.coverage and os.path.exists(a.coverage))
    cal_reported = any(r.get("cal_flag") in ("acceptable", "poor") for r in bm)
    n_scaf = None
    if getattr(a, "compounds", "") and os.path.exists(a.compounds):
        n_scaf = len(
            {
                r["cluster"]
                for r in bench.scaffold_clusters(load_compounds_csv(a.compounds))
            }
        )
    rob = governance.risk_of_bias(
        n_compounds=len({r["compound_id"] for r in recs}),
        n_scaffolds=n_scaf,
        n_sources=len(
            {s for r in recs for s in (r.get("sources") or "").split(";") if s}
        ),
        n_judged_indep2=st["n_judged_indep2"],
        n_measured=st["n_measured"],
        n_judged=st["n_judged"],
        has_benchmark=has_bm,
        benchmark_ok=bench_ok,
        calibration_reported=cal_reported,
        dependency_handled=True,
        provenance_ok=True,
    )
    tier, maxc, missing = tiers.assign(
        st, has_bm, has_cov, bench_ok, rob=rob["overall"]
    )
    print("[tier] 证据构成：%s" % st)
    print("[tier] 偏倚风险（PROBAST）= %s" % rob["overall"])
    print("[tier] 当前档位 = %s → 结论上限 = %s" % (tier, maxc))
    if missing:
        print("[tier] 升级缺口：%s" % "；".join(missing))
    if a.request:
        ok, msg = tiers.enforce(a.request, tier)
        print("[tier] 请求档位 %s：%s" % (a.request, "允许" if ok else "拒绝 — " + msg))
    row = dict(
        tier=tier,
        max_conclusion=maxc,
        **st,
        has_benchmark=has_bm,
        benchmark_ok=bench_ok,
        has_coverage_decl=has_cov,
        risk_of_bias=rob["overall"],
        missing="；".join(missing),
    )
    p = tiers.write(os.path.join(a.outdir, "tier.csv"), row)
    print("[tier] -> %s" % p)


def cmd_qaf(a):
    """监管治理评估：QAF 四原则 + 三层适用域 + PROBAST 偏倚风险。"""
    from . import governance, tiers
    from . import benchmark as bench
    from .manifest import write_manifest

    write_manifest(
        a.outdir,
        inputs=[
            x
            for x in (
                a.reliability,
                a.coverage,
                a.benchmark,
                a.measurements,
                a.compounds,
                a.rules,
            )
            if x
        ],
        argv=sys.argv,
    )
    rel = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    cov = (
        list(csv.DictReader(io.open(a.coverage, encoding="utf-8-sig")))
        if a.coverage and os.path.exists(a.coverage)
        else []
    )
    bm = (
        list(csv.DictReader(io.open(a.benchmark, encoding="utf-8-sig")))
        if a.benchmark and os.path.exists(a.benchmark)
        else []
    )
    tier_row = {}
    tp = a.tier or os.path.join(a.outdir, "tier.csv")
    if os.path.exists(tp):
        rows = list(csv.DictReader(io.open(tp, encoding="utf-8-sig")))
        tier_row = rows[0] if rows else {}
    if not tier_row:
        st = tiers.stats_from_reliability(rel)
        has_bm = bool(bm)
        bench_ok = any(
            r.get("auroc") not in ("", None) and "DEMO" not in (r.get("note") or "")
            for r in bm
        )
        t, maxc, _miss = tiers.assign(st, has_bm, bool(cov), bench_ok)
        tier_row = dict(tier=t, max_conclusion=maxc, **st)

    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    n_ep = len(rules)
    n_unit = sum(1 for v in rules.values() if (v or {}).get("unit"))
    srcs = {r.get("source") for r in cov if r.get("source")}
    # 版本化判据只看**本批实际用到的源**（registry 里 dead/needs_probe 的源不参与）
    meas = (
        list(csv.DictReader(io.open(a.measurements, encoding="utf-8-sig")))
        if a.measurements and os.path.exists(a.measurements)
        else []
    )
    ver_srcs = {
        r.get("source") for r in meas if str(r.get("source_version") or "").strip()
    }
    if not srcs:
        srcs = {r.get("source") for r in meas if r.get("source")}
    manifest = os.path.join(a.outdir, "run_manifest.yaml")
    cal_reported = any(r.get("cal_flag") in ("acceptable", "poor") for r in bm)
    bench_ok = any(
        r.get("auroc") not in ("", None) and "DEMO" not in (r.get("note") or "")
        for r in bm
    )

    qaf = governance.qaf_assess(
        n_endpoints=n_ep,
        n_endpoints_with_unit=n_unit,
        n_sources=len(srcs),
        n_sources_versioned=len(ver_srcs),
        coverage_rows=cov,
        reliability_rows=rel,
        benchmark_rows=bm,
        tier=tier_row.get("tier", "T1"),
        manifest_present=os.path.exists(manifest),
        calibration_reported=cal_reported,
    )

    n_comp = len({r["compound_id"] for r in rel})
    n_scaf = None
    if a.compounds and os.path.exists(a.compounds):
        comps = load_compounds_csv(a.compounds, fmt="auto")
        n_scaf = len({r["cluster"] for r in bench.scaffold_clusters(comps)})

    st = tiers.stats_from_reliability(rel)
    rob = governance.risk_of_bias(
        n_compounds=n_comp,
        n_scaffolds=n_scaf,
        n_sources=len(srcs),
        n_judged_indep2=st["n_judged_indep2"],
        n_measured=st["n_measured"],
        n_judged=st["n_judged"],
        has_benchmark=bool(bm),
        benchmark_ok=bench_ok,
        calibration_reported=cal_reported,
        dependency_handled=True,
        provenance_ok=True,
    )

    adl = governance.ad_levels(rel, cov, tier_row)

    os.makedirs(a.outdir, exist_ok=True)
    with io.open(
        os.path.join(a.outdir, "qaf_compliance.csv"),
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        w = csv.DictWriter(
            fh, fieldnames=["principle", "title", "status", "evidence", "gap"]
        )
        w.writeheader()
        w.writerows(qaf)
    with io.open(
        os.path.join(a.outdir, "ad_levels.csv"), "w", encoding="utf-8-sig", newline=""
    ) as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["level", "scope", "id", "status", "value", "evidence", "note"],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(adl)
    drows = []
    for d in rob["domains"]:
        drows.append(
            dict(domain=d["domain"], judgement=d["judgement"], rationale=d["rationale"])
        )
    with io.open(
        os.path.join(a.outdir, "probast.csv"), "w", encoding="utf-8-sig", newline=""
    ) as fh:
        w = csv.DictWriter(fh, fieldnames=["domain", "judgement", "rationale"])
        w.writeheader()
        w.writerows(drows)

    print("[qaf] OECD QAF 四原则（2023）：")
    for r in qaf:
        print(
            "   %s %-22s %-14s %s"
            % (
                r["principle"],
                r["title"],
                r["status"],
                ("缺口：" + r["gap"]) if r["gap"] != "-" else "",
            )
        )
    print("[qaf] 三层适用域（Hanser 2016）：%s" % _level_brief(adl))
    print("[qaf] PROBAST 偏倚风险：整体 %s" % rob["overall"].upper())
    for d in rob["domains"]:
        print("   %-26s %-7s %s" % (d["domain"], d["judgement"], d["rationale"][:64]))
    print("[qaf] %s" % rob["note"])
    print("[qaf] -> %s（qaf_compliance / ad_levels / probast）" % a.outdir)


def _level_brief(rows):
    out = []
    for lv in ("model", "prediction", "decision"):
        sub = [r for r in rows if r["level"] == lv]
        if not sub:
            continue
        cnt = {}
        for r in sub:
            cnt[r["status"]] = cnt.get(r["status"], 0) + 1
        out.append("%s=%s" % (lv, cnt))
    return "；".join(out)


def cmd_conformal(a):
    """保形预测区间（Norinder 2014）：给点估计配有限样本覆盖率保证。"""
    from . import conformal
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.predictions, a.truth], argv=sys.argv)
    pred = list(csv.DictReader(io.open(a.predictions, encoding="utf-8-sig")))
    truth = list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
    filled = [t for t in truth if str(t.get("truth_value") or "").strip() != ""]
    if not filled:
        print(
            "[conformal] ⚠ truth 里没有非空 truth_value：无校准集，"
            "只能给 ±∞ 区间（等于没有信息）"
        )
    scale_map = {}
    if getattr(a, "scale_file", "") and os.path.exists(a.scale_file):
        for r in csv.DictReader(io.open(a.scale_file, encoding="utf-8-sig")):
            try:
                scale_map[r["compound_id"]] = float(r["sigma"])
            except (KeyError, TypeError, ValueError):
                continue
    if a.mode == "normalized" and not scale_map:
        print(
            "[conformal] ⚠ normalized 模式没有可用 scale_file：退回 sigma=1（等同 absolute）"
        )
    # 2026-11-19（面板实跑）：预测表给错（比如把宽表 gate_scores_*.csv 当成长表）时，
    # 旧实现直接 KeyError: 'endpoint' —— 用户看到 traceback 而不知道"要长表"。
    # 输入形状错误必须在入口判掉，并说明期望列。
    need = ("compound_id", "endpoint", "value")
    miss = [c for c in need if pred and c not in pred[0]]
    if not pred or miss:
        print(
            "[conformal] ✗ 预测表不是 measurements 长表：缺列 %s"
            % (miss or list(need)),
            file=sys.stderr,
        )
        print(
            "[conformal] 期望列：compound_id,endpoint,value[,unit,source,domain_flag]；"
            "宽表（idx/y_true/model_prob）请先经 saturate/长表化，不要直接喂。",
            file=sys.stderr,
        )
        sys.exit(2)
    eps = [a.endpoint] if a.endpoint else sorted({r["endpoint"] for r in pred})
    if a.endpoint and a.endpoint not in set(r["endpoint"] for r in pred):
        print(
            "[conformal] ✗ 指定端点 %r 不在预测表里（现有端点：%s）"
            % (a.endpoint, ", ".join(sorted({r["endpoint"] for r in pred})[:8])),
            file=sys.stderr,
        )
        sys.exit(2)
    allrows, summs = [], []
    for ep in eps:
        rows, summ = conformal.build(
            pred,
            truth,
            ep,
            alpha=a.alpha,
            min_n=a.min_n,
            mode=a.mode,
            scale_map=scale_map,
        )
        allrows.extend(rows)
        summs.append(summ)
        if summ["flag"] == "ok":
            print(
                "[conformal] %-12s n_cal=%d q=%.4f（α=%.2f, %s）→ 目标 %d 个分子"
                % (ep, summ["n_cal"], summ["q"], a.alpha, a.mode, summ["n_targets"])
            )
        else:
            print("[conformal] %-12s 不可用：%s" % (ep, summ["note"][:70]))
    p = conformal.write(os.path.join(a.outdir, "conformal_intervals.csv"), allrows)
    print(
        "[conformal] %d 行 -> %s"
        % (p, os.path.join(a.outdir, "conformal_intervals.csv"))
    )
    ok = [s for s in summs if s["flag"] == "ok"]
    if ok:
        print(
            "[conformal] 区间宽度 %s"
            % "、".join("%s=±%.3f" % (s["endpoint"], s["q"]) for s in ok)
        )
    print(
        "[conformal] 纪律：校准集必须是实测真值；经验覆盖率是构造保证、不是验证；"
        "本区间只保证**边际**覆盖，不保证逐分子覆盖"
    )


def cmd_reporting(a):
    """TRIPOD+AI 自查表 + 源 model card + FAIR 映射。"""
    from . import reporting
    from .manifest import write_manifest

    write_manifest(
        a.outdir,
        inputs=[
            x
            for x in (
                a.reliability,
                a.coverage,
                a.benchmark,
                a.measurements,
                a.compounds,
                a.rules,
                a.registry,
            )
            if x
        ],
        argv=sys.argv,
    )
    rel = (
        list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
        if a.reliability and os.path.exists(a.reliability)
        else []
    )
    cov = (
        list(csv.DictReader(io.open(a.coverage, encoding="utf-8-sig")))
        if a.coverage and os.path.exists(a.coverage)
        else []
    )
    bm = (
        list(csv.DictReader(io.open(a.benchmark, encoding="utf-8-sig")))
        if a.benchmark and os.path.exists(a.benchmark)
        else []
    )
    meas = (
        list(csv.DictReader(io.open(a.measurements, encoding="utf-8-sig")))
        if a.measurements and os.path.exists(a.measurements)
        else []
    )
    tier_row = {}
    tp = os.path.join(a.outdir, "tier.csv")
    if os.path.exists(tp):
        r = list(csv.DictReader(io.open(tp, encoding="utf-8-sig")))
        tier_row = r[0] if r else {}

    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    srcs = {r.get("source") for r in meas if r.get("source")}
    ver = {r.get("source") for r in meas if str(r.get("source_version") or "").strip()}
    real_bm = any(
        x.get("auroc") not in ("", None) and "DEMO" not in (x.get("note") or "")
        for x in bm
    )
    cal = any(x.get("cal_flag") in ("acceptable", "poor") for x in bm)
    ctx = dict(
        skill_version=a.version,
        has_registry=os.path.exists(a.registry),
        has_tier=bool(tier_row),
        tier=tier_row.get("tier", ""),
        n_sources=len(srcs),
        n_sources_versioned=len(ver),
        has_normalize=bool(os.path.exists(a.compounds) and os.path.exists(a.compounds)),
        n_endpoints=len(rules),
        n_endpoints_with_unit=sum(1 for v in rules.values() if (v or {}).get("unit")),
        has_source_groups=os.path.exists(a.registry),
        n_compounds=len({r["compound_id"] for r in rel}),
        n_pos=sum(1 for r in rel if r.get("verdict") == "FAIL"),
        has_coverage=bool(cov),
        has_manifest=os.path.exists(os.path.join(a.outdir, "run_manifest.yaml")),
        has_benchmark=bool(bm),
        has_real_benchmark=real_bm,
        has_calibration=cal,
        has_external=bool(getattr(a, "external", False)),
        has_subgroup=bool(getattr(a, "subgroup", False)),
        has_ledger=os.path.exists(os.path.join(a.outdir, "evidence_ledger.csv")),
        has_units=(
            all((v or {}).get("unit") for v in rules.values()) if rules else False
        ),
    )

    trip = reporting.tripod_checklist(ctx)
    fair = reporting.fair_mapping(ctx)
    cards_rows, md = reporting.model_cards(missing=(srcs - set(reporting.load_cards())))

    reporting.write_csv(
        os.path.join(a.outdir, "tripod_ai_checklist.csv"),
        trip,
        ["code", "section", "item", "status", "evidence", "gap"],
    )
    reporting.write_csv(
        os.path.join(a.outdir, "fair_mapping.csv"),
        fair,
        ["code", "principle", "artifact", "status", "gap"],
    )
    reporting.write_csv(
        os.path.join(a.outdir, "model_cards.csv"),
        cards_rows,
        [
            "source",
            "label",
            "group",
            "intended_use",
            "model_type",
            "training_data",
            "applicability_domain",
            "n_known_failures",
            "version_tracking",
            "rate_limit",
            "access_mode",
            "evidence_level",
        ],
    )
    with io.open(os.path.join(a.outdir, "model_cards.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    ok = sum(1 for t in trip if t["status"] == "satisfied")
    par = sum(1 for t in trip if t["status"] == "partial")
    nm = sum(1 for t in trip if t["status"] == "not_met")
    print(
        "[reporting] TRIPOD+AI 自查：满足 %d / 部分 %d / 未达 %d（共 %d 条）"
        % (ok, par, nm, len(trip))
    )
    for t in trip:
        if t["status"] == "not_met":
            print("   ✗ %-4s %-10s %s" % (t["code"], t["section"], t["gap"][:64]))
    cov_fair = sum(1 for f in fair if f["status"] == "covered")
    print("[reporting] FAIR 映射：%d/%d 条已落地（其余为部分）" % (cov_fair, len(fair)))
    print("[reporting] model card：%d 个源已登记" % len(cards_rows))
    miss = srcs - set(reporting.load_cards())
    if miss:
        print(
            "[reporting] ⚠ 本批用到但未登记 model card 的源：%s"
            % "、".join(sorted(miss))
        )
    print(
        "[reporting] -> %s（tripod_ai_checklist / fair_mapping / model_cards）"
        % a.outdir
    )
    print(
        "[reporting] 说明：TRIPOD+AI 条目文字是按分节语义重写的索引，"
        "引用以 BMJ 2024;385:e078378 原文为准"
    )


def cmd_sensitize(a):
    """E3：阈值敏感性分析（阈值是文献起点值时，必须报告结论对它的敏感度）。"""
    from .manifest import write_manifest
    from . import sensitivity
    from .phrasing import load_source_groups

    write_manifest(
        a.outdir, inputs=[a.input, a.rules, a.saturation, a.registry], argv=sys.argv
    )
    rows = check_measurements(a.input, a.allow_invalid, tag="sensitize")
    rules = _load_rules(a.rules)
    source_groups = load_source_groups(a.registry)
    non_ranking, blocked = _load_sat_sets(a.saturation)
    out, summ = sensitivity.analyze(
        rows, rules, tuple(a.factors), non_ranking, blocked, source_groups
    )
    p = sensitivity.write(os.path.join(a.outdir, "sensitivity.csv"), out)
    print("[sensitize] %d 个阈值摄动组合 -> %s" % (len(out), p))
    if summ["max_global_flip"] is not None:
        print("[sensitize] 全局同时摄动时最大翻转率 %.2f" % summ["max_global_flip"])
    if summ["worst_endpoints"]:
        print(
            "[sensitize] 最敏感端点（翻转率）：%s"
            % ", ".join("%s=%.2f" % (e, r) for e, r in summ["worst_endpoints"][:6])
        )
    crit = sorted(
        {
            r["endpoint"]
            for r in out
            if r["flag"] == "threshold_critical" and r["endpoint"] != "(all)"
        }
    )
    if crit:
        print("[sensitize] ⚠ threshold_critical（不得进对外结论段）：%s" % crit)
    # U6（Sahigara 2012）：AD 阈值本身也是"文献起点"，必须一起摄动
    if getattr(a, "ad", False):
        arows, asumm = sensitivity.ad_analyze(
            rows,
            rules,
            non_ranking,
            blocked,
            source_groups,
            require_grid=tuple(a.require_grid),
        )
        ap = sensitivity.ad_write(os.path.join(a.outdir, "ad_sensitivity.csv"), arows)
        print("[sensitize] AD 阈值摄动 %d 个组合 -> %s" % (len(arows), ap))
        for r in arows:
            print(
                "   %-28s 翻转 %d / 新增 %d / 丢失 %d（基数 %d）%s"
                % (
                    r["variant"],
                    r["n_flipped"],
                    r["n_new_decided"],
                    r["n_lost_decided"],
                    r["n_decided_base"],
                    "  ← " + r["flag"] if r["flag"] != "robust" else "",
                )
            )
        if asumm["max_flip"] is not None:
            print(
                "[sensitize] AD 旋钮最大变更 %d 个判定（%s）——"
                "AD 阈值必须与结论一起报告，不能当常数"
                % (asumm["max_changes"], asumm["worst_variant"])
            )


def cmd_merge(a):
    """合并多源 measurements 长表（F2）。

    **C1-b / C11（2026-11-04）**：
      * 去重键加入 `unit`——同键异量纲的两条数值是不同测量，旧实现会把后一条
        当重复静默丢掉，造成「数值凭空消失」且无任何痕迹；
      * 强制 `source_version` 非空，缺失即 `exit 3`，且**不受 --allow-invalid 豁免**
        （不同版本权重混用不是数据质量瑕疵，是证据链身份丢失）；
      * 预检全部在内存完成，任何不合规都不落盘（含 run_manifest.yaml）。
    """
    from .manifest import write_manifest
    from . import schema

    raw = []
    for p in a.inputs:
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
            raw.append((p, r))
    missing_ver = [
        (p, r.get("compound_id"), r.get("endpoint"))
        for p, r in raw
        if not str(r.get("source_version") or "").strip()
    ]
    if missing_ver:
        print(
            "[merge] ✗ %d 行缺 source_version（不同版本权重不可混用，C1-b）："
            % len(missing_ver)
        )
        for x in missing_ver[:5]:
            print("   ", x)
        print("[merge] 未写出任何产物；补全版本后重试。", file=sys.stderr)
        sys.exit(3)

    write_manifest(a.outdir, inputs=list(a.inputs), argv=sys.argv)
    allrows = []
    per_src = {}
    seen = set()
    dup = 0
    for p, r in raw:
        key = (
            r.get("compound_id"),
            r.get("endpoint"),
            r.get("source"),
            r.get("source_version"),
            r.get("unit"),
        )
        if key in seen and not a.keep_dup:
            dup += 1
            continue
        seen.add(key)
        allrows.append(r)
        s = r.get("source", "")
        per_src[s] = per_src.get(s, 0) + 1
    probs = schema.validate(allrows)
    if probs and not a.allow_invalid:
        print("[merge] ✗ 合并后长表有 %d 个契约问题（前 5）：" % len(probs))
        for x in probs[:5]:
            print("   ", x)
        sys.exit(
            "[merge] 中止：先修数据，或加 --allow-invalid（加了产物也不得用于报告）"
        )
    out = os.path.join(a.outdir, "measurements_merged.csv")
    n = schema.write_measurements_checked(
        out, allrows, require_source_version=True, strict=not a.allow_invalid
    )
    print(
        "[merge] %d 个文件 -> %d 行（去重跳过 %d 行）-> %s"
        % (len(a.inputs), n, dup, out)
    )
    for s, c in sorted(per_src.items()):
        print("   %-14s %d 行" % (s, c))
    # C1-c：端点名未登记必须显式落审计表，禁止用子串兜底静默借用同前缀规则。
    # 即使 0 行也写空表（带表头），便于 CI 机械检查产物是否真的生成过。
    from . import endpoints as EP

    unmapped = EP.audit_unmapped(allrows)
    rep = os.path.join(a.outdir, "unmapped_endpoint_report.csv")
    with io.open(rep, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["row", "compound_id", "endpoint", "how", "reason", "action"]
        )
        w.writeheader()
        for u in unmapped:
            w.writerow(u)
    if unmapped:
        print(
            "[merge] ⚠ %d 行端点未登记 -> %s（这些行不得进入裁决）"
            % (len(unmapped), rep)
        )
    if probs:
        print("[merge] ⚠ 跳过校验：%d 个契约问题（产物不得用于报告）" % len(probs))


def _default_compounds(input_path):
    """在输入文件同目录与 cwd 找 compounds.csv（含 calc_smiles）。找不到返回 ''。"""
    import os as _os

    cand = []
    if input_path:
        d = _os.path.dirname(_os.path.abspath(input_path))
        cand.append(_os.path.join(d, "compounds.csv"))
    cand.append(_os.path.join(_os.getcwd(), "compounds.csv"))
    for c in cand:
        if _os.path.exists(c):
            return c
    return ""


def _load_smiles(path):
    """读 compounds.csv -> {compound_id: calc_smiles}（兼容 smiles 列名）。"""
    import csv as _csv
    import io as _io

    out = {}
    with _io.open(path, encoding="utf-8-sig", newline="") as fh:
        for r in _csv.DictReader(fh):
            cid = (r.get("compound_id") or "").strip()
            smi = (r.get("calc_smiles") or r.get("smiles") or "").strip()
            if cid:
                out[cid] = smi
    return out


def cmd_reliab(a):
    from .reliability import evaluate, summarize, can_rank
    from .manifest import write_manifest
    from .phrasing import allowed_statement, load_source_groups

    write_manifest(
        a.outdir, inputs=[a.input, a.rules, a.saturation, a.registry], argv=sys.argv
    )
    rows = check_measurements(a.input, a.allow_invalid, tag="reliab")
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    source_groups = load_source_groups(a.registry)
    # R35 红线 2：小样本必须显式降级（n<30 横幅；n<10 只出定性结论），不许"看起来像正常结果"
    from . import guards as GD

    _n_comp = len({r["compound_id"] for r in rows})
    _ss = GD.sample_size_guard(_n_comp)
    if _ss["banner"]:
        print(_ss["banner"])
        if _ss["level"] == "qualitative":
            print(
                "[reliab] n=%d：本次输出**只作定性**——不得报一致率/差值/排序/风险分层。"
                % _n_comp,
                file=sys.stderr,
            )
    # C82：把 registry 的"本化学类域外端点"真正落到数据上（此前只登记、无代码读取）
    if os.path.exists(a.registry) and not getattr(a, "no_class_blocks", False):
        if not a.chemical_class:
            print(
                "[reliab] 未指定 --chemical-class：跳过域外端点过滤（混合面板安全）。"
                "若为单一化学类批次（如糖苷），请显式加 --chemical-class cinnamoyl_glycoside"
            )
        else:
            import yaml as _yaml
            from .reliability import apply_class_blocks

            reg = _yaml.safe_load(io.open(a.registry, encoding="utf-8")) or {}
            rows, blocked_detail = apply_class_blocks(rows, reg, a.chemical_class)
            if blocked_detail:
                print(
                    "[reliab] 域外端点（registry blocked，共 %d 组）已置 out_of_domain："
                    % len(blocked_detail)
                )
                for d in blocked_detail:
                    print(
                        "   %-12s %-16s %d 行  ← %s"
                        % (d["source"], d["endpoint"], d["n"], d["evidence"][:56])
                    )
    non_ranking, saturated = _load_sat_sets(a.saturation)
    match_log = []
    recs = evaluate(
        rows, rules, non_ranking, saturated, source_groups, match_log=match_log
    )
    # R21/R37：不推荐计算的端点默认降级（DILI/Ames 等），除非显式承担低有效性
    from .endpoints import apply_tier_policy, canonical_name, QUALITATIVE_NEEDS_EXPERT

    # v4.4：ICH M7 专家规则层接入。对需要双方法的定性端点（ames），用化合物 SMILES
    # 跑 adt/alerts.py 结构警示扫描，标记 expert_rule_layer=True 并构建 alert_cache，
    # 供 apply_tier_policy 做双方法合成（统计结论 × 结构警示命中）。
    # 若未启用/找不到 compounds.csv，则 ames 等维持 UNDETERMINED（ICH M7：两法缺一不判）。
    alert_cache = {}
    if getattr(a, "enable_alerts", True):
        comp_path = a.compounds or _default_compounds(a.input)
        if comp_path and os.path.exists(comp_path):
            from .alerts import alert_positive

            smi_map = _load_smiles(comp_path)
            for cid, smi in smi_map.items():
                try:
                    alert_cache[cid] = bool(alert_positive(smi)) if smi else False
                except Exception:
                    alert_cache[cid] = False
            n_hit = sum(1 for v in alert_cache.values() if v)
            for r in recs:
                ep = canonical_name(r["endpoint"]) or r["endpoint"].lower()
                if ep in QUALITATIVE_NEEDS_EXPERT:
                    r["expert_rule_layer"] = True
            print(
                "[reliab] 专家规则层(adt/alerts.py)已接入：扫描 %d 成分，命中警示 %d"
                % (len(alert_cache), n_hit)
            )
        else:
            print(
                "[reliab] 未指定/找不到 compounds.csv（--compounds），跳过专家规则层；"
                "ames 等 QUALITATIVE_NEEDS_EXPERT 端点维持 UNDETERMINED",
                file=sys.stderr,
            )
    recs, tier_log = apply_tier_policy(
        recs, getattr(a, "i_accept_low_validity", False), alert_cache=alert_cache
    )
    if tier_log:
        p_tier = os.path.join(a.outdir, "endpoint_tier_blocks.csv")
        with io.open(p_tier, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "compound_id",
                    "endpoint",
                    "original_verdict",
                    "new_verdict",
                    "reason",
                ],
            )
            w.writeheader()
            w.writerows(tier_log)
        print(
            "[reliab] %d 条判定因'端点不推荐计算'降为 UNDETERMINED -> %s"
            % (len(tier_log), p_tier)
        )
        print("        如需强行使用（自担低有效性并留痕）：--i-accept-low-validity")
    if match_log:
        print(
            "[reliab] ⚠ %d 行端点**未登记**（C1-c：已禁子串兜底，这些行不得进入裁决）：%s"
            "\n        在 references/endpoint_aliases.yaml 登记显式别名，或在 "
            "03_endpoint_rules.yaml 定义该端点 estimand 后重跑。"
            % (len(match_log), sorted(set(match_log))[:6])
        )
    for r in recs:
        st = allowed_statement(
            r["verdict"],
            r["confidence"],
            r.get("n_indep_groups", 1),
            non_ranking=(r["endpoint"] in non_ranking or r["endpoint"] in saturated),
            measured=(r.get("n_measured", 0) > 0),
            action=r.get("action", ""),
            projection=bool(r.get("projection_used")),
        )
        r["allowed_statement"] = st["template"]
    # v3.1.0 / 工作包 I：GRADE 式确定性修饰符（只标注，不改 verdict）
    from . import certainty as _C

    _C.annotate(recs, rows)
    p = os.path.join(a.outdir, "reliability.csv")
    cols = [
        "compound_id",
        "endpoint",
        "n_total",
        "n_in_domain",
        "n_measured",
        "sources",
        "n_indep_groups",
        "indep_groups",
        "value_used",
        "unit",
        "spread",
        "verdict",
        "confidence",
        "reason",
        "action",
        "bbb_mechanism",
        "allowed_statement",
        "certainty_modifier",
        "certainty_rationale",
        "grade_indirectness",
        "grade_inconsistency",
        "grade_imprecision",
        "grade_rob",
        "expert_rule_layer",
        "alert_hit",
        "projection_used",
    ]
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    c = summarize(recs)
    print("[reliab] %d 个 分子x端点 -> %s" % (len(recs), p))
    print(
        "[reliab] PASS %d / FAIL %d / UNDETERMINED %d"
        % (c.get("PASS", 0), c.get("FAIL", 0), c.get("UNDETERMINED", 0))
    )
    und = [r for r in recs if r["verdict"] == "UNDETERMINED"]
    if und:
        print("[reliab] 前 6 条 UNDETERMINED 的原因：")
        for r in und[:6]:
            print(
                "   %-3s %-10s %s" % (r["compound_id"], r["endpoint"], r["reason"][:64])
            )


def cmd_desire(a):
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input, a.rules], argv=sys.argv)
    from .desirability import (
        compound_scores,
        pareto_front,
        can_rank_full,
        write_reports,
        AXIS_COVERAGE_MIN,
    )

    rules = _load_rules(a.rules)
    rel = (
        schema.read_measurements(a.input)
        if "measurements" in os.path.basename(a.input)
        else list(csv.DictReader(io.open(a.input, encoding="utf-8-sig")))
    )
    ep_rows, ax_rows = compound_scores(rel, rules)
    axes = sorted({r["axis"] for r in ax_rows})
    # 排名守卫：用真实数据的覆盖情况做判定
    n_comp = len({r["compound_id"] for r in ax_rows})
    cov_by_c = {}
    for r in ax_rows:
        cov_by_c.setdefault(r["compound_id"], []).append(r)
    # 全流程实跑暴露（2026-11-22）：自定义 rules（如外部数据的 external_rules.yaml）
    # 没有 axis 分组时，desirability 故意把所有端点标 ungrouped、不产 axis_rows。
    # 旧实现直接 min() 空集 → ValueError 崩溃，用户看不懂。这里 fail-fast 给可定位提示。
    if not cov_by_c:
        n_ungrouped = sum(1 for r in ep_rows if r.get("axis") == "ungrouped")
        if not ep_rows:
            raise SystemExit(
                "[desire] 没有任何端点能按 rules 评分：输入 endpoint 名与 rules 不匹配。\n"
                "  输入端点示例=%s；rules=%s。请换用与之匹配的 rules"
                "（如外部数据用 out_ext/external_rules.yaml），或先给 rules 补齐这些端点。"
                % (sorted({r.get("endpoint") for r in rel})[:5], a.rules)
            )
        raise SystemExit(
            "[desire] 无可用 axis 分组：%d/%d 条端点为 ungrouped（rules=%s）。\n"
            "  几何平均只在同 axis 内定义；请给 rules 的端点加 axis 字段"
            "（exposure/stability/safety/coverage），或改用 references/03_endpoint_rules.yaml。"
            % (n_ungrouped, len(ep_rows), a.rules)
        )
    min_aud = min(sum(x["n_audited"] for x in v) for v in cov_by_c.values())
    # 无簇结构数据时 max_cluster_frac 保守取 1.0（恒拒绝簇条件）；
    # 有真实簇分析（如 Butina 聚类）时用 --max-cluster-frac 传入实测值
    # C60（评估 P3-17）：原实现第三参传 None，分歧条件在 CLI 层被静默跳过。
    # 现从 reliability.csv 的 spread 列取实测最大极差（概率型端点专用口径）。
    spreads = []
    for r in rel:
        if r.get("verdict") == "PASSTHRU":
            continue
        try:
            spreads.append(float(r.get("spread") or ""))
        except (TypeError, ValueError):
            continue
    max_spread = max(spreads) if spreads else None
    ok_rank, why = (
        can_rank_full(n_comp, a.max_cluster_frac, max_spread, min_aud)
        if a.enforce_rank_guard
        else (False, ["rank guard 未启用（--enforce-rank-guard 打开）"])
    )
    front, dom = pareto_front(ax_rows, axes)
    p1, p2 = write_reports(a.outdir, ep_rows, ax_rows, front, dom)
    print(
        "[desire] %d 分子 x %d 端点 -> %s"
        % (n_comp, len({r["endpoint"] for r in ep_rows}), p1)
    )
    print("[desire] 轴聚合 -> %s" % p2)
    print("[desire] Pareto 前沿: %s" % front)
    for r in ax_rows:
        if r["flag"] != "no_audited_endpoints":
            print(
                "   %-3s %-10s geo=%-6s cov=%.2f %-22s front=%s"
                % (
                    r["compound_id"],
                    r["axis"],
                    r["geo_mean"],
                    r["coverage"],
                    r["flag"],
                    "Y" if r["compound_id"] in front else "-",
                )
            )
    if not ok_rank:
        print("[desire] 排名守卫：不允许输出综合排名（%s）" % "; ".join(why[:2]))
    if not a.enforce_rank_guard:
        print(
            "[desire] 提示：默认只输出 Pareto 前沿；讨论名次需过四条件并加 "
            "--enforce-rank-guard（见 04_decision_funnel.md）"
        )


def cmd_ledger(a):
    from .ledger import build, write

    rel = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    axis = (
        list(csv.DictReader(io.open(a.axis, encoding="utf-8-sig")))
        if a.axis and os.path.exists(a.axis)
        else []
    )
    meas = check_measurements(a.measurements, a.allow_invalid, tag="ledger")
    rows = build(rel, axis, meas)
    p = os.path.join(a.outdir, "evidence_ledger.csv")
    n, bad = write(p, rows)
    print(
        "[ledger] %d 条结论 -> %s（unsupported %d 条——必须先修证据或改结论）"
        % (n, p, bad)
    )
    for r in rows:
        if r["status"] == "unsupported":
            print("   UNSUPPORTED %-3s %s" % (r["compound_id"], r["claim"][:70]))


def cmd_transport(a):
    """转运体先验表（v2.5.0）：**决策清单，不是预测**。"""
    from . import transport
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input, a.priors], argv=sys.argv)
    comps = load_compounds_csv(a.input, fmt=getattr(a, "format", "auto"))
    priors = transport.load_priors(a.priors)
    rows = []
    for c in comps:
        smi = c.get("calc_smiles") or c.get("smiles")
        part, _hits, _t = transport.assess(c["compound_id"], smi, priors)
        rows.extend(part)
    if not rows:
        print("[transport] 没有命中任何化学型（检查 SMILES 或 priors 文件）")
        return
    cols = [
        "compound_id",
        "chemotype",
        "chemotype_label",
        "tpsa",
        "moiety",
        "transporter",
        "role",
        "plausibility_base",
        "plausibility",
        "adjust_reason",
        "adjust_evidence",
        "evidence_level",
        "rationale",
        "recommended_assay",
        "predictive_value",
    ]
    p = os.path.join(a.outdir, "transporter_priors.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print("[transport] %d 条 化学型×转运体 先验 -> %s" % (len(rows), p))
    print(
        "[transport] ⚠ 这些是**先验/假设**，不是预测值：三个计算源都不给肠侧转运体"
        "（ADMETlab 只有肝/胆侧 5 个，ADMET-AI 只有 Pgp 抑制剂，vNN 本类全 NoPrediction）"
    )
    adj = [r for r in rows if r.get("plausibility") != r.get("plausibility_base")]
    if adj:
        print(
            "[transport] 苷元/糖苷分档下调 %d 条（Peng 2023：糖苷化不利 OATP2B1 结合）："
            % len(adj)
        )
        seen = set()
        for r in adj:
            key = (r["transporter"], r["plausibility_base"], r["plausibility"])
            if key in seen:
                continue
            seen.add(key)
            print(
                "   %-10s %s → %s  ｜ %s"
                % (
                    r["transporter"],
                    r["plausibility_base"],
                    r["plausibility"],
                    r["adjust_reason"][:56],
                )
            )
    for d in transport.summarize(rows):
        print(
            "   %-22s %-26s 命中 %2d 个分子（medium 及以上 %d）"
            % (d["transporter"], d["role"], d["n"], d["n_medium_up"])
        )
    need = [d for d in transport.summarize(rows) if d["n_medium_up"] > 0]
    if need:
        print("[transport] 建议先做的实验（按优先级）：")
        for d in need[:3]:
            print(
                "   * %s：%s"
                % (d["transporter"], d["assays"][0] if d["assays"] else "-")
            )
    print(
        "[transport] 回填格式：domain_flag=measured + provenance_url；"
        "端点见 references/transporter_priors.yaml 的 backfill_endpoints"
    )


def cmd_pbpk(a):
    """10 状态灌注限制 PBPK + 安全裕度反推（v2.4.0，收编自 e14_pbpk.py）。"""
    from . import pbpk
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input, a.compounds], argv=sys.argv)
    rows_raw = check_measurements(a.input, a.allow_invalid, tag="pbpk")

    vals = {}
    for r in rows_raw:
        if (r.get("domain_flag") or "") not in ("predicted", "measured", "saturated"):
            continue
        try:
            v = float(r["value"])
        except (TypeError, ValueError, KeyError):
            continue
        vals.setdefault((r["compound_id"], r["endpoint"]), []).append(v)

    fa_by, fa_hi = {}, {}
    if a.exposure and os.path.exists(a.exposure):
        for x in csv.DictReader(io.open(a.exposure, encoding="utf-8-sig")):
            if x.get("status") != "ok":
                continue
            try:
                fa_by[x["compound_id"]] = (float(x["fa_lo"]) + float(x["fa_hi"])) / 2
                fa_hi[x["compound_id"]] = float(x["fa_hi"])
            except (TypeError, ValueError, KeyError):
                continue

    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")

    comps = load_compounds_csv(a.compounds, fmt=a.format)
    ic50s = [float(x) for x in str(a.ic50_list).split(",") if x.strip()]
    rows, skipped = [], []
    curves = []  # v4.16：--dump-curves 的 C(t) 累积（供 adt.cli pd 消费）
    for c in comps:
        cid = c["compound_id"]
        smi = c.get("calc_smiles") or c.get("smiles")
        m = Chem.MolFromSmiles(smi) if smi else None
        if m is None:
            skipped.append((cid, "SMILES 无法解析"))
            continue
        mw, clogp = Descriptors.MolWt(m), Descriptors.MolLogP(m)
        cl = st.median(vals.get((cid, "clint_microsome"), []) or [float("nan")])
        fu = st.median(vals.get((cid, "ppb_fu"), []) or [float("nan")])
        if not (cl == cl) or not (fu == fu):
            skipped.append((cid, "缺 CLint 或 fu"))
            continue
        if not pbpk.in_phys_range_ok(cl, fu):
            skipped.append((cid, "CLint/fu 越物理边界"))
            continue
        fa = fa_by.get(cid, a.fa_default)
        ehr = dict(
            fbile=getattr(a, "fbile", 0.0),
            fre=getattr(a, "fre", 0.0),
            kbile=getattr(a, "kbile", pbpk.KB_DEFAULT),
        )
        res = pbpk.simulate(a.dose_mg, cl, fu / 100.0, fa, clogp, **ehr)
        mt = pbpk.metrics(res, mw)
        if getattr(a, "dump_curves", False):
            # c_pl 是 mg/L(=µg/mL)，与 adt.pd_link 的输入约定一致
            step = max(1, len(res["t"]) // 400)
            for i in range(0, len(res["t"]), step):
                curves.append(
                    dict(
                        compound_id=cid,
                        t_h=round(float(res["t"][i]), 4),
                        c_mg_per_L=round(float(res["c_pl"][i]), 8),
                    )
                )
        F = pbpk.bioavailable_fraction(a.dose_mg, cl, fu / 100.0, fa, clogp, mw, **ehr)
        mg = pbpk.margin_table(mt["cmax_nM"], ic50s)
        # v3.0：把 IVIVE 假设与 EHR 机制前提显式化（Obach 2011 / Fagerholm 2008）
        iv = pbpk.ivive_assumptions(cl, fu)
        try:
            from . import transport as _tr

            _prows, _hits, _t = _tr.assess(cid, smi, _tr.load_priors())
            tr_flag = bool(_hits)
        except Exception:  # noqa: BLE001  转运体先验失败不该拖垮 PBPK
            tr_flag = False
        ehrp = pbpk.ehr_prerequisites(
            cl, fu, clogp, transporter_mediated=tr_flag, mw=mw
        )
        row = dict(
            compound_id=cid,
            mw=round(mw, 1),
            clogp=round(clogp, 2),
            clint_um=round(cl, 1),
            fu_pct=round(fu, 1),
            fa=round(fa, 3),
            cmax_nM=round(mt["cmax_nM"], 1),
            tmax_h=round(mt["tmax_h"], 2),
            auc_nMh=round(mt["auc_nMh"], 1),
            thalf_h=round(mt["thalf_h"], 2) if mt["thalf_h"] == mt["thalf_h"] else "",
            F_pbpk=round(F, 3),
            mass_balance_err=float("%.2e" % pbpk.mass_balance(res)),
            fbile=ehr["fbile"],
            fre=ehr["fre"],
            clint_app=iv["clint_app"],
            fu_mic=iv["fu_mic"],
            clint_scaled_lh=iv["clint_scaled_lh"],
            clint_b_lh=iv["clint_b_lh"],
            eh=iv["eh"],
            clh_lh=iv["clh_lh"],
            ehr_verdict=ehrp["verdict"],
            ehr_n_met="%d/%d" % (ehrp["n_met"], ehrp["n_checks"]),
            ehr_note=ehrp["note"],
        )
        for g in mg:
            key = "%g" % g["ic50_uM"]
            row["margin_IC50_%suM" % key] = round(g["margin"], 1)
            row["tier_IC50_%suM" % key] = g["tier"]
        rows.append(row)

    if not rows:
        print("[pbpk] 没有可用分子（缺 CLint/fu？）%s" % skipped)
        return

    # 校验 A
    mb = max(r["mass_balance_err"] for r in rows)
    print(
        "[pbpk] A 质量守恒 最大相对误差 %.2e → %s"
        % (mb, "PASS" if mb < 1e-4 else "FAIL")
    )
    # 校验 B
    rho = pbpk.scenario_rho(rows, fa_by, a.dose_mg)
    print(
        "[pbpk] B 场景稳健性 CLint×2 排序 ρ=%.3f → %s"
        % (rho, "PASS" if rho >= 0.9 else "WARN")
    )
    # 校验 C（可选，耗时长）
    if a.mc and a.mc >= 100:
        pairs = [
            (r["compound_id"], r["mw"], r["clogp"], r["clint_um"], r["fu_pct"])
            for r in rows
        ]
        _, _, rel = pbpk.mc_convergence(
            pairs, a.dose_mg, n=a.mc, fa_span={k: 2 * v for k, v in fa_by.items()}
        )
        print(
            "[pbpk] C MC %d 次折半收敛 最大相对差 %.3f → %s"
            % (a.mc, rel, "PASS" if rel < 0.05 else "WARN")
        )
    else:
        print("[pbpk] C 跳过（--mc <100）")

    base_cols = [
        "compound_id",
        "mw",
        "clogp",
        "clint_um",
        "fu_pct",
        "fa",
        "cmax_nM",
        "tmax_h",
        "auc_nMh",
        "thalf_h",
        "F_pbpk",
        "mass_balance_err",
    ]
    extra = [c for c in rows[0] if c not in base_cols]
    cols = base_cols + sorted(extra)
    p = os.path.join(a.outdir, "pbpk_results.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print("[pbpk] %d 个分子 -> %s" % (len(rows), p))

    if curves:
        cp = os.path.join(a.outdir, "pbpk_curves.csv")
        with io.open(cp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["compound_id", "t_h", "c_mg_per_L"])
            w.writeheader()
            w.writerows(curves)
        print(
            "[pbpk] C(t) 曲线 %d 行 -> %s（可直接喂给 adt.cli pd）" % (len(curves), cp)
        )

    if getattr(a, "dump_cmax", False):
        # v4.21：cardiac 模块的 --exposure 需要 cmax_uM；此前 pbpk 只写 cmax_nM，
        # 导致 cardiac 永远缺文件而 SKIP_MISSING。这里显式落盘。
        cpath = os.path.join(a.outdir, "cmax_uM.csv")
        ccols = ["compound_id", "cmax_uM", "cmax_nM", "tmax_h", "auc_nMh", "thalf_h"]
        with io.open(cpath, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ccols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(
                    dict(
                        compound_id=r["compound_id"],
                        cmax_uM=round(r["cmax_nM"] / 1000.0, 4),
                        cmax_nM=r["cmax_nM"],
                        tmax_h=r["tmax_h"],
                        auc_nMh=r["auc_nMh"],
                        thalf_h=r["thalf_h"],
                    )
                )
        print(
            "[pbpk] Cmax 表 %d 行 -> %s（可直接喂给 adt.cli cardiac --exposure）"
            % (len(rows), cpath)
        )

    if getattr(a, "ehr_scan", False):
        comps = [
            dict(
                compound_id=r["compound_id"],
                mw=r["mw"],
                clogp=r["clogp"],
                clint_um=r["clint_um"],
                fu_pct=r["fu_pct"],
                fa=r["fa"],
            )
            for r in rows
        ]
        sc = pbpk.ehr_scan(comps, a.dose_mg)
        sp = os.path.join(a.outdir, "ehr_scan.csv")
        with io.open(sp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(sc[0]), extrasaction="ignore")
            w.writeheader()
            w.writerows(sc)
        worst_auc = max(sc, key=lambda x: (x["auc_ratio"] or 0))
        worst_th = max(sc, key=lambda x: (x["thalf_ratio"] or 0))
        print("[pbpk] EHR 扫描 %d 组合 -> %s" % (len(sc), sp))
        print(
            "[pbpk] 肠肝循环能把 AUC 最多放大 %.2f×、t½ 最多放大 %.2f×"
            "（fbile=%.2f/fre=%.2f 与 fbile=%.2f/fre=%.2f）"
            % (
                worst_auc["auc_ratio"],
                worst_th["thalf_ratio"],
                worst_auc["fbile"],
                worst_auc["fre"],
                worst_th["fbile"],
                worst_th["fre"],
            )
        )
        print(
            "[pbpk] 说明：这是**边界**不是预测——本类 fbile/fre 无任何数据，"
            "需胆管插管大鼠实测（见 湿实验最小方案_转运体与肠肝循环.md）"
        )
    print(
        "[pbpk] Cmax %.0f–%.0f nM | F %.3f–%.3f | t½ %s–%s h"
        % (
            min(r["cmax_nM"] for r in rows),
            max(r["cmax_nM"] for r in rows),
            min(r["F_pbpk"] for r in rows),
            max(r["F_pbpk"] for r in rows),
            min(r["thalf_h"] for r in rows if r["thalf_h"] != ""),
            max(r["thalf_h"] for r in rows if r["thalf_h"] != ""),
        )
    )
    for ic in ic50s:
        key = "%g" % ic
        print(
            "[pbpk] 安全裕度（IC50=%.3g µM，最坏情形假定）→ %s"
            % (
                ic,
                "、".join(
                    "%s %.0f×(%s)"
                    % (
                        r["compound_id"],
                        r["margin_IC50_%suM" % key],
                        r["tier_IC50_%suM" % key],
                    )
                    for r in rows
                ),
            )
        )
        need = [
            (r["compound_id"], pbpk.dose_at_margin(a.dose_mg, r["cmax_nM"], ic, 30))
            for r in rows
        ]
        print(
            "[pbpk]   要达到 Margin=30 的剂量上限（线性外推）：%s"
            % "、".join("%s %.0f mg" % (c, d) for c, d in need)
        )
    print(
        "[pbpk] 注意：IC50 为假设值时，裕度只作'最坏情形筛查'；"
        "真实 IC50 需膜片钳/铊流实验"
    )

    # ---- v3.0 学术化层：公式自校验 / IVIVE 假设 / EHR 前提 / 申报口径 / CiPA ----
    ws = pbpk.well_stirred_selfcheck()
    print(
        "[pbpk] D well-stirred 自校验（Pang & Rowland 1977）→ %s"
        % ("PASS" if ws["ok"] else "FAIL")
    )
    for c in ws["cases"]:
        if not c["pass"]:
            print("   ✗ %s：期望 %.3f 实得 %.3f" % (c["name"], c["expect"], c["got"]))
    print(
        "[pbpk] E IVIVE 假设（Obach 2011）：MPPGL=%s mg/g、肝重=%s g、fu_mic=%s（未实测）、"
        "血/浆比=%s"
        % (
            pbpk.IVIVE_DEFAULTS["mppgl"],
            pbpk.IVIVE_DEFAULTS["liver_g"],
            pbpk.IVIVE_DEFAULTS["fu_mic"],
            pbpk.IVIVE_DEFAULTS["blood_plasma_ratio"],
        )
    )
    r0 = rows[0]
    iv0 = pbpk.ivive_assumptions(r0["clint_um"], r0["fu_pct"])
    print(
        "[pbpk]   %s 例：CLint_app=%.1f µL/min/mg → CLint_b=%.1f L/h → Eh=%.3f → CLh=%.1f L/h"
        % (
            r0["compound_id"],
            iv0["clint_app"],
            iv0["clint_b_lh"],
            iv0["eh"],
            iv0["clh_lh"],
        )
    )
    print(
        "[pbpk]   敏感性：%s"
        % "、".join("%s→Eh %.2f" % (s["variant"], s["eh"]) for s in iv0["sensitivity"])
    )
    print("[pbpk]   ⚠ %s" % iv0["caveat"])
    nplaus = sum(1 for r in rows if r["ehr_verdict"] == "plausible")
    nunc = sum(1 for r in rows if r["ehr_verdict"] == "uncertain")
    print(
        "[pbpk] F EHR 机制前提（Fagerholm 2008）：具备 %d、部分 %d、不足 %d"
        % (nplaus, nunc, len(rows) - nplaus - nunc)
    )
    for r in rows[:3]:
        print(
            "   %-4s %s（%s）：Eh=%.2f，渗透 clogp=%s"
            % (r["compound_id"], r["ehr_verdict"], r["ehr_n_met"], r["eh"], r["clogp"])
        )
    ap = pbpk.write_academic(os.path.join(a.outdir, "pbpk_academic.csv"), rows)
    print(
        "[pbpk] G 学术字段表 %d 行 -> %s"
        % (ap, os.path.join(a.outdir, "pbpk_academic.csv"))
    )
    q = pbpk.qualification_statement()
    print("[pbpk] H 申报口径（FDA 2018 / EMA 2018）：%s" % q["intended_use"])
    print("[pbpk]   平台资格：%s" % q["platform_qualification"])
    hr = pbpk.herg_evidence_route()
    print("[pbpk] I hERG 证据路线（CiPA, Li 2019）：%s" % hr["route"])
    print("[pbpk]   局限：%s" % hr["limitation"])
    print("[pbpk]   要升级需要：%s" % "、".join(hr["data_needed"]))
    if skipped:
        print("[pbpk] 跳过：%s" % skipped)


def cmd_report(a):
    """从裁决产物一键生成带措辞封顶的结论段（Markdown）。

    每句话都来自 allowed_statement 模板填值——报告写作者不允许越过模板自由发挥。

    C1（2026-11-03 评审）修复：本函数此前**不调用任何红线守卫**，导致
    `guards.provenance_line` / `interval_line` / `gate_distribution_line` /
    `endpoint_plurality_line` 在仓库里零生产调用点——红线只是"测试里能通过的函数"。
    现改为：结论段落盘前，整段文本必须过 `redlines.enforce_report_text`；
    任一红线命中即**不写文件**、落 `REDLINE_VIOLATIONS.md`、exit 4。
    `--publish` 额外触发红线 3（快照重放）与红线 1（输入准入）的发布级校验。
    """
    from . import redlines as RL

    rel = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    # axis 留空 = outdir 内的 axis_scores.csv；显式传参则原样使用。
    # （实测踩过：默认相对路径 out/... 会解析到其他目录的旧产物，全局段
    # 显示与当前 reliability 不匹配的 Pareto 前沿——跨目录污染）
    axis_path = a.axis or os.path.join(a.outdir, "axis_scores.csv")
    axis = (
        list(csv.DictReader(io.open(axis_path, encoding="utf-8-sig")))
        if os.path.exists(axis_path)
        else []
    )
    manifest_sha = ""
    mp = os.path.join(a.outdir, "run_manifest.yaml")
    if os.path.exists(mp):
        import yaml as _yaml

        manifest_sha = (_yaml.safe_load(io.open(mp, encoding="utf-8")) or {}).get(
            "manifest_sha1", ""
        )[:12]

    # ---- 红线 3 / 红线 1（仅发布模式）：探索模式不阻断，但必须留痕 ----
    publish = bool(getattr(a, "publish", False))
    replay_note = ""
    override_active = False
    non_replayable = False
    if publish:
        try:
            rp = RL.require_replay("report --publish")  # REDLINE-3
            replay_note = rp.get("note", "")
            # C05：override 曾被调用方丢弃，导致 --publish 仍写出 conclusions.md。
            override_active = bool(rp.get("override"))
            non_replayable = bool(rp.get("non_replayable"))
        except Exception as exc:
            print("[report] %s" % exc, file=sys.stderr)
            print(
                "[report] 发布模式被红线 3 拦截：结论段未写出。"
                "先用 ADT_REPLAY=1 重放产物，或去掉 --publish 走探索模式。",
                file=sys.stderr,
            )
            sys.exit(4)
        if override_active or non_replayable:
            print(
                "[report] 发布模式被红线 3 拦截：ADT_ALLOW_ONLINE=1 是应急通道，"
                "本次结果 non_replayable=True，禁止 --publish 产出可发布结论段。",
                file=sys.stderr,
            )
            sys.exit(4)
        gate_csv = os.path.join(a.outdir, "input_gate.csv")  # REDLINE-1
        if os.path.exists(gate_csv):
            g = list(csv.DictReader(io.open(gate_csv, encoding="utf-8-sig")))
            bad_in = [r for r in g if r.get("status") not in ("ok", "")]
            if bad_in:
                print(
                    "[report] 红线 1：发布模式的结论段含 %d 个未通过结构准入的分子：%s"
                    % (
                        len(bad_in),
                        ", ".join(str(r.get("compound_id")) for r in bad_in[:6]),
                    ),
                    file=sys.stderr,
                )
                print(
                    "[report] 结论段未写出。先修结构（InChIKey 锚定 + 立体声明）"
                    "或用 --strict-input 重跑 normalize。",
                    file=sys.stderr,
                )
                sys.exit(4)

    lines = ["# 结论段（自动生成，措辞已按 05_qa_gates §12 封顶）", ""]
    # 2026-11-19（面板实跑）：消旋体/立体未定分子可能通过输入闸门（显式声明），
    # 其结论**只对消旋体成立**。发布模式必须在结论段首屏出现这条上限，
    # 否则"PASS/FAIL"会被读成对某个单一对映体的判定——这是不可接受的外推。
    _race = []
    _gate_csv = os.path.join(a.outdir, "input_gate.csv")
    if os.path.exists(_gate_csv):
        try:
            with io.open(_gate_csv, encoding="utf-8-sig") as _fh:
                _race = [
                    r.get("compound_id")
                    for r in csv.DictReader(_fh)
                    if r.get("stereo_state") == "racemic_declared"
                ]
        except Exception:
            _race = []
    if _race:
        lines.append(
            "> **立体上限（RACEMATE）**：%d/%d 个分子为已声明的消旋体或立体未定"
            "（%s）。下列 PASS/FAIL 只对**消旋体**成立，不得外推到单一对映体；"
            "需要手性结论须另测单一异构体。"
            % (
                len(_race),
                len({r.get("compound_id") for r in rel} if rel else _race),
                "、".join(str(x) for x in _race[:8]),
            )
        )
        lines.append("")
    # C05：探索模式也可能跑在应急上网通道下，留痕不能只在 publish 分支做。
    if not publish:
        try:
            from . import snapshot as _SN

            non_replayable = os.environ.get("ADT_ALLOW_ONLINE") == "1" and not bool(
                _SN.replay_mode()
            )
        except Exception:
            non_replayable = os.environ.get("ADT_ALLOW_ONLINE") == "1"
    if non_replayable:
        ok_mark = _mark_non_replayable(a.outdir)
        if not ok_mark:
            print(
                "[report] 红线 3：non_replayable 留痕失败，拒绝写出 conclusions.md。",
                file=sys.stderr,
            )
            sys.exit(4)
        lines.append(
            "> ⚠ NON_REPLAYABLE（C05）：本次运行在 ADT_ALLOW_ONLINE=1 应急通道下，"
            "非快照重放产物，**不可作为论文/汇报/基金申请的数字**；"
            "留痕见 run_manifest.yaml::non_replayable 与 "
            "references/OVERRIDE_LEDGER.yaml。"
        )
        lines.append("")
    if manifest_sha:
        lines.append(
            "> 判据版本 manifest_sha1=%s（预注册，改动阈值后本段需重出）" % manifest_sha
        )
        lines.append("")
    if replay_note:
        lines.append("> 红线 3：%s" % replay_note)
        lines.append("")
    lines += [
        "> 本段不含任何超出 allowed_statement 模板的句子；",
        "> " "禁止的表述（ΔG→Kd、人体剂量推断、定论词）见 05_qa_gates §12。",
        "",
    ]

    by_cid = {}
    for r in rel:
        by_cid.setdefault(r["compound_id"], []).append(r)
    for cid in sorted(by_cid):
        lines.append("## %s" % cid)
        decided = [
            r for r in by_cid[cid] if r["verdict"] not in ("UNDETERMINED", "PASSTHRU")
        ]
        und = [r for r in by_cid[cid] if r["verdict"] == "UNDETERMINED"]
        passthru = [r for r in by_cid[cid] if r["verdict"] == "PASSTHRU"]
        if passthru:
            # v2.3：参照端点可能很多（vNN 一次 12 个），逐条列会把报告撑爆；
            # 聚合为一行（名称 + 数量），细节查 reliability.csv / coverage_matrix.csv
            names = sorted(r["endpoint"] for r in passthru)
            shown = "、".join(names[:6]) + (
                ("等 %d 个" % len(names)) if len(names) > 6 else ""
            )
            if len(names) > 6:
                shown = "、".join(names[:6]) + " 等 %d 个" % len(names)
            lines.append(
                "- 适用域/真值参照 %d 个（不裁决，仅报告）：%s" % (len(names), shown)
            )
        for r in decided:
            tmpl = r.get("allowed_statement") or ""
            stmt = tmpl.format(
                verdict=r["verdict"],
                value=r.get("value_used", ""),
                unit=r.get("unit", ""),
                n_indep=r.get("n_indep_groups", "?"),
            )
            lines.append("- **%s**（%s）：%s" % (r["endpoint"], r["verdict"], stmt))
        if und:
            # v2.3.5：单组端点严化为 require_sources=2 后，信息不能丢——把"唯一方法组
            # 给出的值"单独列出，明确标注**不作判决**。这样"严格"不等于"没用"。
            single = [
                r
                for r in und
                if str(r.get("n_indep_groups")) == "1"
                and str(r.get("value_used", "")) not in ("", "None")
            ]
            if single:
                items = [
                    "%s=%s %s（%s）"
                    % (
                        r["endpoint"],
                        r["value_used"],
                        r.get("unit", ""),
                        r.get("indep_groups", "?"),
                    )
                    for r in sorted(single, key=lambda x: x["endpoint"])
                ]
                shown = "；".join(items[:6])
                if len(items) > 6:
                    shown += " 等 %d 项" % len(items)
                lines.append(
                    "- **单组证据 %d 项（不作判决，仅作参照）**：%s"
                    % (len(single), shown)
                )
            lines.append("- 未判定端点 %d 个：" % len(und))
            for r in und:
                act = r.get("action", "")
                if act:
                    lines.append("  - %s：%s" % (r["endpoint"], act[:90]))
        lines.append("")

    # v2.3：覆盖率段（有 coverage_matrix.csv 才出）
    cp = os.path.join(a.outdir, "coverage_matrix.csv")
    if os.path.exists(cp):
        cov = list(csv.DictReader(io.open(cp, encoding="utf-8-sig")))
        by_src = {}
        for r in cov:
            d = by_src.setdefault(r["source"], dict(n=0, u=0, ep=0, usable=0, zero=0))
            d["n"] += int(r["n"] or 0)
            d["u"] += int(r["n_usable"] or 0)
            d["ep"] += 1
            d["usable"] += 1 if r["flag"] == "usable" else 0
            d["zero"] += 1 if r["flag"] == "no_prediction" else 0
        lines.append("## 覆盖率（源 × 端点）")
        for src, d in sorted(by_src.items()):
            rate = d["u"] / d["n"] if d["n"] else 0.0
            lines.append(
                "- **%s**：覆盖 %.3f（可判 %d/%d 行；可用端点 %d/%d；全零端点 %d）"
                % (src, rate, d["u"], d["n"], d["usable"], d["ep"], d["zero"])
            )
        zero_ep = sorted(
            {
                r["endpoint"]
                for r in cov
                if r["flag"] == "no_prediction"
                and r["endpoint"] not in ("dili", "herg", "ames")
            }
        )
        if zero_ep:
            lines.append(
                "- 全零端点（本批**无可判值**，不得读作阴性）：%s" % "、".join(zero_ep)
            )
        lines.append("")

    if axis:
        front = sorted({r["compound_id"] for r in axis if r.get("pareto") == "front"})
        n_aud = sum(int(r.get("n_audited") or 0) for r in axis)
        n_all = sum(int(r.get("n_endpoints") or 0) for r in axis)
        lines.append("## 全局")
        lines.append(
            "- Pareto 前沿（未被任何分子在全部可比轴上超越）：%s"
            % ("、".join(front) if front else "无（全部证据不足）")
        )
        lines.append(
            "- 轴级可判覆盖率：%d/%d = %.0f%% —— 未覆盖部分以 UNDETERMINED 报告，"
            "不参与任何排名" % (n_aud, n_all, 100.0 * n_aud / max(n_all, 1))
        )
        lines.append(
            "- 排名守卫：本段不输出综合排名；如需名次必须过四条件并启用 "
            "`--enforce-rank-guard`（见 04_decision_funnel.md）"
        )
        lines.append("")

    # E3 阈值稳健性段（有 sensitivity.csv 才出；阈值来源必须随结论一起声明）
    sp = os.path.join(a.outdir, "sensitivity.csv")
    if os.path.exists(sp):
        sens = list(csv.DictReader(io.open(sp, encoding="utf-8-sig")))
        worst = {}
        for r in sens:
            if r["endpoint"] == "(all)" or r.get("flip_rate") in ("", None):
                continue
            worst[r["endpoint"]] = max(
                worst.get(r["endpoint"], 0.0), float(r["flip_rate"])
            )
        glob = [
            float(r["flip_rate"])
            for r in sens
            if r["endpoint"] == "(all)" and r.get("flip_rate") not in ("", None)
        ]
        lines.append("## 阈值稳健性（E3）")
        lines.append(
            "- 阈值来源：**文献起点值（threshold_source=literature）**，"
            "未经本批实测校准——本段所有 PASS/FAIL 均带此前提"
        )
        if glob:
            lines.append("- 全部阈值同时摄动时最大翻转率：%.2f" % max(glob))
        if worst:
            top = sorted(worst.items(), key=lambda x: -x[1])[:5]
            lines.append(
                "- 最敏感端点："
                + "、".join("%s（翻转率 %.2f）" % (e, v) for e, v in top)
            )
            crit = [e for e, v in worst.items() if v > 0.5]
            lines.append(
                "- threshold_critical（结论只能写作“待实测确认”）：%s"
                % ("、".join(crit) if crit else "无")
            )
        lines.append("")

    # ---- 2026-11-11：未覆盖端点强制声明（C82「写了但没接线」的闭环）----
    # 之前 not_covered_endpoints 只被测试读取、生产链路零调用：报告只报 CYP 抑制，
    # 读者会默认 DDI 已评估，而诱导/TDI 根本未覆盖。现在把登记表渲染进结论段，
    # 且**生成失败即拒绝写出**——改 registry → 声明自动变化 → 缺标记可被
    # claims_audit --coverage-declaration 检出，形成 e2e（C82 要求的形态）。
    try:
        from . import coverage_gate as CG

        _cg_entries = CG.load_not_covered(getattr(a, "rules", "") or None)
        lines.extend(CG.declaration_lines(_cg_entries))
        print(
            "[report] 未覆盖端点强制声明：%d 条（CYP 诱导/TDI 等）已并入结论段"
            % len(_cg_entries)
        )
    except Exception as exc:
        print(
            "[report] 未覆盖端点声明生成失败：%r；结论段未写出。"
            "先修 references/03_endpoint_rules.yaml::not_covered_endpoints。" % (exc,),
            file=sys.stderr,
        )
        sys.exit(4)

    # ---- 红线 6/7/8/9 + R12：结论段落盘前的统一文本闸门 ----
    # 顺序很重要：**先拦后写**。任何一条命中都不得生成 conclusions.md，
    # 否则"违规报告已存在"这件事本身会被下游当作可引用产物。
    body = "\n".join(lines)
    eps = sorted({r["endpoint"] for r in rel if r.get("verdict") not in ("PASSTHRU",)})
    ctx = dict(
        n_compounds=len(by_cid),
        endpoints=eps,
        eval_distribution=getattr(a, "eval_distribution", "") or None,
        gate_auc=getattr(a, "gate_auc", None),
    )
    try:
        RL.enforce_report_text(body, outdir=a.outdir, ctx=ctx, stage="report")
    except Exception as exc:
        print(
            "[report] 红线拦截：结论段未写出（%d 条违规）。见 %s"
            % (str(exc).count("## "), os.path.join(a.outdir, "REDLINE_VIOLATIONS.md")),
            file=sys.stderr,
        )
        sys.exit(4)

    p = os.path.join(a.outdir, "conclusions.md")
    io.open(p, "w", encoding="utf-8").write(body + "\n")
    print("[report] %d 个分子的结论段 -> %s" % (len(by_cid), p))


def _mark_non_replayable(outdir):
    """C05：应急通道留痕必须落盘且可机器读取；失败即返回 False（由调用方阻断）。"""
    try:
        import yaml as _yaml

        os.makedirs(outdir, exist_ok=True)
        mp = os.path.join(outdir, "run_manifest.yaml")
        d = {}
        if os.path.isfile(mp):
            d = _yaml.safe_load(io.open(mp, encoding="utf-8")) or {}
        d["non_replayable"] = True
        d["non_replayable_reason"] = "ADT_ALLOW_ONLINE=1 (C05 / REVIEW_FINDINGS.yaml)"
        d["override_ledger_ref"] = "references/OVERRIDE_LEDGER.yaml"
        io.open(mp, "w", encoding="utf-8").write(
            _yaml.safe_dump(d, allow_unicode=True, sort_keys=False)
        )
        return True
    except Exception as exc:
        print("[report] non_replayable 留痕写入失败：%r" % (exc,), file=sys.stderr)
        return False


def cmd_independence(a):
    """工作包 A：独立性量化 + 校准计票（只度量，不改 verdict）。"""
    from . import independence as I
    from .phrasing import load_source_groups
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input, a.registry, a.truth], argv=sys.argv)
    rows = check_measurements(a.input, a.allow_invalid, tag="independence")
    groups = load_source_groups(a.registry)
    pairs = I.pairwise_stats(rows, groups)
    gsum = I.group_summary(pairs, groups)
    eff = I.effective_votes(rows, groups, gsum)

    def _w(name, cols, data):
        p = os.path.join(a.outdir, name)
        with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        return p

    p1 = _w(
        "independence_pairs.csv",
        [
            "endpoint",
            "source_a",
            "source_b",
            "same_group",
            "group",
            "n",
            "n_unit_mismatch",
            "spearman",
            "mean_abs_diff",
            "max_abs_diff",
            "disagree_rate",
            "sufficient",
            "sign_conflict",
            "note",
        ],
        pairs,
    )
    p2 = _w(
        "independence_groups.csv",
        [
            "group",
            "n_pairs",
            "n_endpoints",
            "max_abs_rho",
            "mean_abs_rho",
            "max_pos_rho",
            "n_sign_conflicts",
            "n_unit_mismatch",
            "group_weight",
            "evidence",
            "n_sources",
            "n_eff",
            "n_eff_ratio",
            "independence_status",
            "weight_ci95",
            "power_at_rho",
            "min_detectable_rho",
        ],
        gsum,
    )
    p3 = _w(
        "effective_votes.csv",
        [
            "compound_id",
            "endpoint",
            "n_indep_groups",
            "effective_votes",
            "pseudo_consensus",
            "groups",
        ],
        eff,
    )
    print("[independence] %d 个源对 -> %s" % (len(pairs), p1))
    print("[independence] %d 个独立组 -> %s" % (len(gsum), p2))
    for g in gsum:
        print(
            "   %-16s k=%s ρmax=%-7s w_raw=%-5s w_applied=%-5s gate=%-8s "
            "w95=[%s] n_eff=%-6s power=%-5s %s"
            % (
                g["group"],
                g.get("n_sources"),
                g["max_abs_rho"],
                g["group_weight"],
                g.get("group_weight_effective"),
                g.get("weight_gate"),
                ",".join(str(x) for x in (g.get("weight_ci95") or [])),
                g.get("n_eff"),
                g.get("power_at_rho"),
                g.get("independence_status"),
            )
        )
    for pr in pairs:
        if pr.get("sign_conflict") == "Y":
            print(
                "   ⚠ %s %s vs %s：ρ=%s 负相关（方向/语义冲突，不是冗余）"
                % (pr["endpoint"], pr["source_a"], pr["source_b"], pr["spearman"])
            )
    n_mis = sum(int(pr.get("n_unit_mismatch") or 0) for pr in pairs)
    if n_mis:
        print(
            "   ⚠ %d 对因单位异构（class vs probability）被跳过——"
            "这正是 C78 的触发条件，需先统一单位或走 class_map" % n_mis
        )
    n_pc = sum(1 for r in eff if r["pseudo_consensus"] == "Y")
    print(
        "[independence] 伪共识（整数≥2 组但有效票<1.5）：%d/%d -> %s"
        % (n_pc, len(eff), p3)
    )

    if a.truth and os.path.exists(a.truth):
        truth = list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
        cal = I.vote_calibration(rows, truth, rules)
        mono = I.monotonicity_flag(cal)
        p4 = _w(
            "vote_calibration.csv",
            [
                "endpoint",
                "k",
                "n_raters",
                "n",
                "n_scored",
                "n_errors",
                "n_ties",
                "error_rate_raw",
                "u_smoothed",
                "vote_confidence",
                "status",
            ],
            cal,
        )
        p5 = _w(
            "vote_monotonicity.csv",
            ["endpoint", "n_bins", "n_violations", "monotone"],
            mono,
        )
        print("[independence] 校准表 %d 行 -> %s（单调性 -> %s）" % (len(cal), p4, p5))
        for m in mono:
            if m["monotone"] == "N":
                print(
                    "   ⚠ %s 的 u(k) 不单调（%d 处违例）：校准失败信号，"
                    "不得据此设门控" % (m["endpoint"], m["n_violations"])
                )


def cmd_certainty(a):
    """工作包 I：给 reliability.csv 加 GRADE 式确定性修饰符。"""
    from . import certainty as C
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.reliability, a.measurements], argv=sys.argv)
    recs = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    meas = (
        check_measurements(a.measurements, a.allow_invalid, tag="certainty")
        if a.measurements and os.path.exists(a.measurements)
        else None
    )
    C.annotate(recs, meas)
    cols = list(recs[0].keys()) if recs else ["compound_id", "endpoint"]
    for c in (
        "certainty_modifier",
        "certainty_rationale",
        "decision_trigger",
        "decision_next_step",
        "grade_indirectness",
        "grade_inconsistency",
        "grade_imprecision",
        "grade_rob",
    ):
        if c not in cols:
            cols.append(c)
    p = os.path.join(a.outdir, "certainty.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    from collections import Counter

    c = Counter(r["certainty_modifier"] for r in recs)
    print("[certainty] %d 条 -> %s" % (len(recs), p))
    for k in C.CERTAINTY_LEVELS:
        print("   %-24s %d" % (k, c.get(k, 0)))
    for r in recs:
        if r["certainty_modifier"] == "low_resolvable":
            print(
                "   可解决示例：%s %s -> %s"
                % (r["compound_id"], r["endpoint"], r["action"][:48])
            )


def cmd_selective(a):
    """工作包 H：risk–coverage 曲线，比较结构性弃权 vs 分数型弃权。"""
    from . import selective as S
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.reliability, a.truth, a.measurements], argv=sys.argv
    )
    recs = (
        list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
        if a.reliability and os.path.exists(a.reliability)
        else []
    )
    truth = (
        list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        if a.truth and os.path.exists(a.truth)
        else None
    )
    meas = (
        check_measurements(a.measurements, a.allow_invalid, tag="selective")
        if a.measurements and os.path.exists(a.measurements)
        else None
    )
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    if a.proxy != "holdout" and not recs:
        print("[selective] 非 holdout 模式需要 --reliability")
        return
    vote_table = None
    vp = os.path.join(a.outdir, "vote_calibration.csv")
    if os.path.exists(vp):
        vote_table = list(csv.DictReader(io.open(vp, encoding="utf-8-sig")))
    conf = (
        list(csv.DictReader(io.open(a.conformal, encoding="utf-8-sig")))
        if a.conformal and os.path.exists(a.conformal)
        else None
    )
    if a.proxy == "holdout":
        if not (meas and a.holdout_source):
            print("[selective] --proxy holdout 需要 --measurements 与 --holdout-source")
            return
        from .phrasing import load_source_groups

        groups = load_source_groups(a.registry)
        res = S.holdout_eval(meas, rules, a.holdout_source, groups, conformal=conf)
    else:
        res = S.evaluate(
            recs,
            truth,
            meas,
            rules,
            proxy=a.proxy,
            vote_table=vote_table,
            conformal=conf,
        )
    if res.get("error"):
        print("[selective] %s" % res["error"])
        return
    # 曲线长表
    rows = []
    for name, m in res["methods"].items():
        for pt in m["points"]:
            rows.append(
                dict(
                    method=name,
                    coverage=pt["coverage"],
                    risk=pt["risk"],
                    n_retained=pt["n_retained"],
                )
            )
    p1 = os.path.join(a.outdir, "risk_coverage.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["method", "coverage", "risk", "n_retained"])
        w.writeheader()
        w.writerows(rows)
    summ = S.summary_rows(res)
    p2 = os.path.join(a.outdir, "selective_summary.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "method",
                "n",
                "aurc",
                "risk_at_80",
                "risk_at_90",
                "status",
                "label_source",
            ],
        )
        w.writeheader()
        w.writerows(summ)
    print("[selective] label_source=%s -> %s / %s" % (res["label_source"], p1, p2))
    for s in summ:
        print(
            "   %-16s n=%-4s AURC=%-7s risk@80=%-6s risk@90=%-6s %s"
            % (
                s["method"],
                s["n"],
                s["aurc"],
                s["risk_at_80"],
                s["risk_at_90"],
                s["status"],
            )
        )
    if any(s["status"] == "insufficient" for s in summ):
        print(
            "[selective] ⚠ 可配对 n<10：AURC 只作代码自检，"
            "不得据此下结论（需 truth 或扩大 holdout 数据集）"
        )
    if res["label_source"] == "proxy_majority":
        print(
            "[selective] ⚠ 伪标签（多源多数票），不是外部验证；论文中只能写"
            "“行为合理性”，不得写“准确率”。"
        )


def cmd_failure_modes(a):
    """工作包 J：失效模式检测 + precision/recall（有标签时）。"""
    from . import failure_modes as F
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.input, a.reliability, a.registry, a.labels], argv=sys.argv
    )
    rows = check_measurements(a.input, a.allow_invalid, tag="failure-modes")
    rel = (
        list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
        if a.reliability and os.path.exists(a.reliability)
        else None
    )
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    reg = None
    if a.registry and os.path.exists(a.registry):
        import yaml as _yaml

        reg = _yaml.safe_load(io.open(a.registry, encoding="utf-8")) or {}
    from .phrasing import load_source_groups

    groups = load_source_groups(a.registry) if a.registry else {}
    hits = F.detect(
        rows, rel, rules, reg, a.chemical_class, groups, expect_sources=a.expect_sources
    )
    labels = (
        list(csv.DictReader(io.open(a.labels, encoding="utf-8-sig")))
        if a.labels and os.path.exists(a.labels)
        else None
    )
    metrics = F.evaluate_detectors(hits, labels)
    p1, p2 = F.write(a.outdir, hits, metrics)
    from collections import Counter

    c = Counter(h["mode"] for h in hits)
    print("[failure-modes] %d 条命中 -> %s" % (len(hits), p1))
    for m, n in sorted(c.items()):
        print("   %-24s %d" % (m, n))
    print(
        "[failure-modes] 指标 -> %s（label_source=%s）"
        % (p2, metrics.get("label_source"))
    )


def cmd_perturb(a):
    """工作包 C：结构扰动传播（descriptor 模式 + 可选 predictions 长表）。"""
    from . import perturbation as P
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.compounds, a.predictions], argv=sys.argv)
    comps = load_compounds_csv(a.compounds, fmt=getattr(a, "format", "auto"))
    if not comps:
        print("[perturb] 没有分子（检查 compounds.csv / --format）")
        return
    d_rows, d_agg = P.analyze_descriptors(comps, use_calc=getattr(a, "use_calc", False))
    pred_agg = None
    if a.predictions and os.path.exists(a.predictions):
        long_rows = list(csv.DictReader(io.open(a.predictions, encoding="utf-8-sig")))
        pred_agg = P.analyze_predictions(long_rows)
    p1, p2, p3 = P.write(a.outdir, d_rows, d_agg, pred_agg)
    print("[perturb] %d 个分子 x 变体 x 描述符 -> %s" % (len(comps), p1))
    print("[perturb] 描述符敏感性汇总 -> %s" % p2)
    for r in d_agg:
        print(
            "   %-8s mean_rel=%-8s max=%-8s invariant=%s"
            % (r["descriptor"], r["mean_rel_delta"], r["max_rel_delta"], r["invariant"])
        )
    if pred_agg is not None:
        print("[perturb] 预测位移/源间分歧 -> %s" % p3)
        for r in pred_agg:
            print(
                "   %-12s ratio=%-8s %s"
                % (r["endpoint"], r["ratio_structure_to_source"], r["interpretation"])
            )


def cmd_decision_value(a):
    """工作包 D：决策曲线 + 实验预算三策略对比。"""
    from . import decision_value as D
    from . import certainty as C
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.reliability, a.truth, a.measurements], argv=sys.argv
    )
    recs = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    if "certainty_modifier" not in (recs[0] if recs else {}):
        C.annotate(recs, None)
    truth = (
        list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        if a.truth and os.path.exists(a.truth)
        else None
    )
    meas = (
        check_measurements(a.measurements, a.allow_invalid, tag="decision-value")
        if a.measurements and os.path.exists(a.measurements)
        else None
    )
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    res = D.build(
        recs,
        truth,
        meas,
        rules,
        proxy=a.proxy,
        budget=a.budget,
        cost_fp=a.cost_fp,
        p_convert=a.p_convert,
    )
    if res.get("error"):
        print("[decision-value] %s" % res["error"])
        return
    p1 = os.path.join(a.outdir, "decision_value.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "strategy",
                "n_selected",
                "tp",
                "fp",
                "expected_utility",
                "utility_per_experiment",
                "note",
            ],
        )
        w.writeheader()
        w.writerows(res["rows"])
    p2 = os.path.join(a.outdir, "decision_curve.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["pt", "n_selected", "tp", "fp", "net_benefit"]
        )
        w.writeheader()
        w.writerows(res["curve"])
    print("[decision-value] label_source=%s -> %s / %s" % (res["label_source"], p1, p2))
    for r in res["rows"]:
        print(
            "   %-12s n=%-6s TP=%-6s FP=%-6s EU=%s"
            % (r["strategy"], r["n_selected"], r["tp"], r["fp"], r["expected_utility"])
        )
    if res["label_source"] == "proxy_majority":
        print(
            "[decision-value] ⚠ 伪标签；只能写“给定预算下的期望效用”，"
            "不得写“提高了准确率”。"
        )


def cmd_dst(a):
    """工作包 E：DST all-in vs 证据准入对照。"""
    from . import dst as DS
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows = check_measurements(a.input, a.allow_invalid, tag="dst")
    blocked = set()
    if a.chemical_class and a.registry and os.path.exists(a.registry):
        import yaml as _yaml
        from .failure_modes import _blocked_set

        reg = _yaml.safe_load(io.open(a.registry, encoding="utf-8")) or {}
        blocked = set(_blocked_set(reg, a.chemical_class).keys())
    rel = (
        list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
        if a.reliability and os.path.exists(a.reliability)
        else None
    )
    cmp_rows = DS.compare(rows, rule=a.rule, blocked=blocked, reliability=rel)
    p1 = os.path.join(a.outdir, "dst_compare.csv")
    cols = [
        "compound_id",
        "endpoint",
        "n_total",
        "n_in_domain",
        "n_blocked",
        "allin_conflict",
        "allin_bel_pos",
        "allin_pl_pos",
        "allin_ignorance",
        "allin_decision",
        "allin_reason",
        "adm_conflict",
        "adm_bel_pos",
        "adm_pl_pos",
        "adm_ignorance",
        "adm_decision",
        "adm_reason",
        "decisions_differ",
        "reliab_verdict",
        "dst_overclaims",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(cmp_rows)
    s = DS.summarize(cmp_rows)
    p2 = os.path.join(a.outdir, "dst_summary.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(s.keys()))
        w.writeheader()
        w.writerow(s)
    print(
        "[dst] %d 条（rule=%s，blocked %d 个源×端点）-> %s"
        % (len(cmp_rows), a.rule, len(blocked), p1)
    )
    if not blocked:
        print(
            "[dst] 提示：未给 --chemical-class/registry，域外源只能以 ignorance 参与"
            "（Dempster 单位元，与排除等价）。要有对照差异，请指定化学类。"
        )
    print(
        "[dst] all-in 判死 %d 条 / 准入控制判死 %d 条 / 裁决不同 %d 条"
        % (s["allin_decisive"], s["admission_decisive"], s["n_decisions_differ"])
    )
    if rel is not None:
        print(
            "[dst] ⚠ DST 判死但框架弃权（过度裁决）：%d 条——"
            "说明在源共享训练生态时，Dempster 把相关证据当独立，产生假确定性"
            % s["dst_overclaims_vs_reliab"]
        )
    print(
        "[dst] 注意：域外源若只赋 ignorance（θ=1），它就是 Dempster 单位元，"
        "与排除等价；真正制造过度裁决的是'已登记域外但仍投概率票'的源。"
    )


def cmd_external(a):
    """工作包 B/G：把外部公开数据转成三张契约表。"""
    from . import external as E
    from .manifest import write_manifest

    # data_dir 是目录，不能直接 SHA1；只把 outdir 产物入 manifest
    write_manifest(a.outdir, inputs=[], argv=sys.argv)
    if a.dataset == "openadmet":
        res = E.write_openadmet(a.data_dir, a.outdir, split=a.split)
        print(
            "[external] OpenADMET %s: %d 分子 / %d 实测 -> %s"
            % (
                a.split,
                res["meta"]["n_compounds"],
                res["meta"]["n_measurements"],
                a.outdir,
            )
        )
        print("[external] compounds=%s" % os.path.basename(res["compounds"]))
        print("[external] measurements=%s" % os.path.basename(res["measurements"]))
        print(
            "[external] truth=%s（PASS/FAIL 为分析阈值）"
            % os.path.basename(res["truth"])
        )
    else:
        res = E.write_npass(a.data_dir, a.outdir)
        c = res["meta"]["counts"]
        n_all = c["train"]["compounds"] + c["test"]["compounds"]
        print(
            "[external] NPASS curated: %d 分子（train %d / test %d）/ ADME %d 条 -> %s"
            % (
                n_all,
                c["train"]["compounds"],
                c["test"]["compounds"],
                res["meta"]["n_adme"],
                a.outdir,
            )
        )
    if res.get("rules"):
        print("[external] 规则=%s" % os.path.basename(res["rules"]))


def cmd_baseline(a):
    """工作包 B/G：train split 训练 Ridge，test split 预测（基线，不是外部工具）。"""
    from . import external as E
    from .manifest import write_manifest

    write_manifest(
        a.outdir,
        inputs=[a.train_meas, a.test_meas, a.train_compounds, a.test_compounds],
        argv=sys.argv,
    )
    methods = ["rdkit", "morgan"] if a.method == "both" else [a.method]
    rules = _load_rules(a.rules) if a.rules and os.path.exists(a.rules) else None
    for m in methods:
        p, p2, n = E.write_baseline(
            a.train_meas,
            a.test_meas,
            a.train_compounds,
            a.test_compounds,
            a.outdir,
            method=m,
            rules=rules,
        )
        print(
            "[baseline] %-7s %d 行 -> %s（风险分数版 %s）"
            % (m, n, p, os.path.basename(p2))
        )


def cmd_conformal_check(a):
    """工作包 F：UNDETERMINED 的 conformal 区间是否系统性更宽。"""
    from . import conformal_check as CC
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.conformal, a.reliability], argv=sys.argv)
    # C07：conformal-check 同步加独立集断言，禁止沿用自校准覆盖率作验证证据。
    _cc_summary = os.path.join(
        os.path.dirname(os.path.abspath(a.conformal or "")),
        "conformal_class_summary.csv",
    )
    if os.path.isfile(_cc_summary):
        _d = {
            r[0]: r[1]
            for r in csv.reader(io.open(_cc_summary, encoding="utf-8-sig"))
            if len(r) >= 2
        }
        if str(_d.get("disjoint", "")).lower() != "true":
            print(
                "[conformal-check] ⚠ NON_EVIDENCE：覆盖率来自自校准集"
                "（disjoint≠true），不构成独立验证（C07）；"
                "请用 conformal-class 重新生成不相交产物。"
            )
    conf = CC.load(a.conformal)
    rel = CC.load(a.reliability)
    per, summ = CC.assess(conf, rel)
    p1, p2 = CC.write(a.outdir, per, summ)
    print(
        "[conformal-check] %d 条（UNDET %d / 可判 %d，跳过 %d）-> %s"
        % (
            summ["n_total"],
            summ["n_undetermined"],
            summ["n_decided"],
            summ["n_skipped"],
            p1,
        )
    )
    for r in per:
        print(
            "   %-14s n=%-5s median_width=%s"
            % (r["verdict"], r["n"], r["median_width"])
        )
    print(
        "[conformal-check] AUC(宽度预测弃权)=%s，中位比=%s"
        % (summ["auc_width_vs_abstention"], summ["ratio"])
    )
    print("[conformal-check] %s -> %s" % (summ["conclusion"], p2))


def cmd_landscape(a):
    """工作包 K：输出与 conformal/AD/DST/多数投票的分工表（CSV/Markdown）。"""
    from . import landscape as L

    thesis, rows = L.load(a.config)
    p1, p2 = L.write(a.outdir, thesis, rows)
    print("[landscape] %d 条策略 -> %s / %s" % (len(rows), p1, p2))
    print("[landscape] thesis: %s" % thesis)


def cmd_conformal_scale(a):
    """工作包 F：描述符空间 k-NN 距离 -> normalized conformal 的 sigma。"""
    from . import conformal_scale as CS
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.train_compounds, a.target_compounds], argv=sys.argv
    )
    rows = CS.compute(a.train_compounds, a.target_compounds, k=a.k)
    if not rows:
        print("[conformal-scale] 没有可用分子（检查 compounds.csv）")
        return
    p = os.path.join(a.outdir, "conformal_scale.csv")
    n = CS.write(p, rows)
    sig = [r["sigma"] for r in rows]
    print("[conformal-scale] %d 个目标分子（k=%d）-> %s" % (n, a.k, p))
    print(
        "[conformal-scale] sigma 范围 %.3f–%.3f，中位 %.3f"
        % (min(sig), max(sig), sorted(sig)[len(sig) // 2])
    )


# ---- 深水区 2.1：SAR 预筛轴（结构-通透性瓶颈诊断）----
def cmd_sar(a):
    """SAR pre-screen：TPSA/MW/HBD/HBA/XlogP 与 BBB± 参照集比较，输出瓶颈诊断。"""
    from . import sar
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows, op = sar.screen_file(a.input, outdir=a.outdir)
    if not rows:
        print("[sar] 没有可用分子（检查 compounds.csv 的 calc_smiles/input_smiles）")
        return
    print("[sar] %d 个分子 -> %s" % (len(rows), op))
    for r in rows:
        flag = {"unlikely": "✗", "uncertain": "?", "plausible": "✓"}.get(
            r["passive_permeability_screen"], "?"
        )
        print(
            "   %s %-12s TPSA=%-7s MW=%-7s 瓶颈=%s"
            % (
                flag,
                r["compound_id"],
                r["TPSA"],
                r["MW"],
                r["bottleneck"] or "（包络内）",
            )
        )


# ---- 深水区 2.3：酰基葡萄糖醛酸化结构警示与风险分级 ----
def cmd_acyl_glucuronide(a):
    """acyl glucuronidation 结构警示：羧酸存在 / α-碳取代 / 共轭程度 -> 风险分级。"""
    from . import acyl_glucuronide as AG
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows, op = AG.assess_file(a.input, outdir=a.outdir)
    if not rows:
        print("[acyl-glucuronide] 没有可用分子（检查 compounds.csv）")
        return
    print("[acyl-glucuronide] %d 个分子 -> %s" % (len(rows), op))
    for r in rows:
        print(
            "   %-12s grade=%-6s 羧酸=%-1d 酯=%-1d α=%s 烯醇化=%-1d 共轭=%-1d"
            % (
                r["compound_id"],
                r["acyl_glucuronide_risk"],
                r["has_carboxylic_acid"],
                r["has_ester"],
                r["alpha_substitution"],
                r["enolizable"],
                r["conjugated"],
            )
        )


# ---- 深水区 2.3 增量：糖苷水解-苷元暴露轴 ----
def cmd_glycoside_hydrolysis(a):
    """糖苷水解-苷元暴露轴：O-糖苷键类型 + 肠道水解/苷元首过风险分级。"""
    from . import glycoside_hydrolysis as GH
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    rows, op = GH.assess_file(a.input, outdir=a.outdir)
    if not rows:
        print("[glycoside-hyd] 没有可用分子（检查 compounds.csv）")
        return
    print("[glycoside-hyd] %d 个分子 -> %s" % (len(rows), op))
    for r in rows:
        print(
            "   %-12s 键型=%-18s 水解=%-6s 首过=%-6s"
            % (
                r["compound_id"],
                r["glycoside_bond_type"],
                r["intestinal_hydrolysis_risk"],
                r["aglycone_first_pass_risk"],
            )
        )


# ---- 方向1：类条件（Mondrian）保形 —— 与 2026 少数类失效文献对话 ----
def cmd_conformal_class(a):
    """类条件保形：二分类端点的边际 vs Mondrian 覆盖对比 + 弃权-风险曲线。"""
    from . import conformal as CF
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.predictions, a.truth], argv=sys.argv)
    pred_rows = list(csv.DictReader(io.open(a.predictions, encoding="utf-8-sig")))
    truth_rows = (
        list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig"))) if a.truth else []
    )
    # 2026-11-04 / C07：生产入口必须是不相交校准/评测集。
    # 旧入口 build_class_conditional_endpoint 在同一 pairs 上既算 q 又算 coverage，
    # 且样本一大就把 self_calibrated_demo 静默覆盖成 ok。
    try:
        cal, test, summary, curve = CF.build_class_conditional_disjoint(
            pred_rows, truth_rows, a.endpoint, alpha=a.alpha
        )
    except ValueError as exc:
        print("[conformal-class] 拒绝自校准：%s" % exc, file=sys.stderr)
        print(
            "[conformal-class] 覆盖率必须在不相交测试集上评估（C07）。", file=sys.stderr
        )
        sys.exit(4)
    if not test:
        print("[conformal-class] 评测集为空，拒绝产出覆盖率（C07）。", file=sys.stderr)
        sys.exit(4)
    print(
        "[conformal-class] 端点=%s  disjoint=true  cal=%d eval=%d overlap=0  α=%.2f"
        % (a.endpoint, summary["calibration_n"], summary["eval_n"], a.alpha)
    )
    print(
        "   边际覆盖=%.3f  类条件覆盖: 类0=%.3f 类1=%.3f"
        % (
            summary["marginal_coverage"],
            summary["class_coverage_0"],
            summary["class_coverage_1"],
        )
    )
    print(
        "   少数类覆盖缺口 MCG=%.3f  覆盖不平衡 CII=%.3f"
        % (summary["minority_coverage_gap"], summary["coverage_imbalance_index"])
    )
    print("   flag=%s" % summary["flag"])
    os.makedirs(a.outdir, exist_ok=True)
    with open(
        os.path.join(a.outdir, "conformal_class_summary.csv"),
        "w",
        encoding="utf-8",
        newline="",
    ) as fh:
        import csv as _csv

        w = _csv.writer(fh)
        for k in (
            "endpoint",
            "n_pairs",
            "alpha",
            "n0",
            "n1",
            "marginal_q",
            "mondrian_q0",
            "mondrian_q1",
            "marginal_coverage",
            "class_coverage_0",
            "class_coverage_1",
            "minority_coverage_gap",
            "coverage_imbalance_index",
            "flag",
            # C07 验收字段：产物必须自带不相交证据
            "disjoint",
            "calibration_n",
            "eval_n",
            "self_calibrated",
            "compound_id_overlap",
            "split_method",
            "evidence_grade",
        ):
            w.writerow([k, summary.get(k)])
    with open(
        os.path.join(a.outdir, "conformal_class_curves.csv"),
        "w",
        encoding="utf-8",
        newline="",
    ) as fh:
        import csv as _csv

        w = _csv.writer(fh)
        w.writerow(["mode", "threshold_idx", "coverage", "accuracy"])
        for i, (cov, acc) in enumerate(curve["marginal"]):
            w.writerow(["marginal", i + 1, cov, acc])
        for i, (cov, acc) in enumerate(curve["mondrian"]):
            w.writerow(["mondrian", i + 1, cov, acc])


# ---- 方向4：跨化学类裁决行为一致性 ----
def cmd_cross_class(a):
    """跨化学类一致性：多个 reliability.csv 同组行为指标对比 + 单调变化预测检验。"""
    from . import crossclass as XC
    from .manifest import write_manifest

    paths = a.reliability  # 多值
    labels = (a.labels.split(",") if a.labels else []) or ["" for _ in paths]
    write_manifest(a.outdir, inputs=paths, argv=sys.argv)
    spaces = [XC.analyze_space(p, lbl) for p, lbl in zip(paths, labels)]
    comp = XC.compare_spaces(
        spaces,
        prediction_note=a.prediction_note,
        expected_highest_abstention=(a.expected_high or None),
        expected_lowest_abstention=(a.expected_low or None),
    )
    print("[cross-class] %d 个化学空间对比" % len(spaces))
    for s in comp["ordered_by_abstention"]:
        print(
            "   %-22s n=%d  弃权率=%.3f  裁决率=%.3f  PASS=%.3f FAIL=%.3f"
            % (
                s["label"],
                s["n_rows"],
                s["abstention_rate"],
                s["decided_rate"],
                s["pass_rate"],
                s["fail_rate"],
            )
        )
    print("   预测检验: %s" % comp["prediction_check"])
    XC.write(os.path.join(a.outdir, "cross_class_summary.csv"), spaces, comp)


# ---- 方向A：准入层消融（工作包 D 缺口 + 三次评审"组件级贡献"）----
def _parse_sources(spec):
    """'path=label[:group],path2=label2' -> [(path,label,group)]"""
    out = []
    for item in [x.strip() for x in (spec or "").split(",") if x.strip()]:
        path, _, rest = item.partition("=")
        if not rest:
            label, group = os.path.basename(path), ""
        else:
            label, _, group = rest.partition(":")
        out.append((path.strip(), label.strip(), group.strip()))
    return out


def cmd_ablate(a):
    """四条件消融：无准入 / 仅单位守卫 / 完整准入 / 准入+保形。"""
    from . import ablation as AB
    from .manifest import write_manifest

    specs = _parse_sources(a.sources)
    if not specs:
        raise SystemExit("[ablate] --sources 为空（格式 path=label[:group],...）")
    write_manifest(
        a.outdir,
        inputs=[p for p, _, _ in specs] + [a.truth, a.conformal],
        argv=sys.argv,
    )
    rows = AB.load_panel(specs)
    if a.corrupt and a.corrupt != "none":
        rows = AB.corrupt(rows, mode=a.corrupt, frac=a.corrupt_frac)
    truth = AB.load_truth(a.truth) if (a.truth and os.path.exists(a.truth)) else {}
    if not truth:
        raise SystemExit("[ablate] 没有可用真值（--truth），无法计算 decided_accuracy")
    rules = _load_rules(a.rules) if (a.rules and os.path.exists(a.rules)) else {}
    meta = dict(
        panel=(
            "controlled_corruption:%s" % a.corrupt
            if a.corrupt not in ("", "none")
            else "as_provided"
        ),
        panel_mix="; ".join("%s(%s)" % (lbl, grp or lbl) for _, lbl, grp in specs),
    )
    res = AB.run(
        rows, truth, meta, conformal_path=a.conformal, outdir=a.outdir, rules=rules
    )
    print("[ablate] panel=%s  n_truth=%d" % (meta["panel"], len(truth)))
    for s in res["summary"]:
        print(
            "   %-26s coverage=%.3f  decided_acc=%s"
            % (s["condition"], s["coverage"] or 0, s["decided_accuracy"])
        )
    print("   conformal: %s" % res["conformal_status"])
    for v in res["verdict"]:
        print("   判定: %s" % v)
    # 同行评审 §4 分歧 1 / B3：把"源级 vs 样本级"可证伪卡随产物落盘，
    # 避免它成为没人调用的孤岛函数（报告 P1-1 同型缺陷）。
    card = AB.source_admission_falsifiability_card(res)
    fp = os.path.join(a.outdir, "source_admission_falsifiability.json")
    with io.open(fp, "w", encoding="utf-8") as fh:
        json.dump(card, fh, ensure_ascii=False, indent=2)
    print("[ablate] 源级可证伪卡: %s（evidence=%s）" % (fp, card["evidence"]))


# ---- 模块N：UNDETERMINED 结构化弃权归因 ----
def cmd_abstain_why(a):
    from . import abstain_attrib as AA
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.reliability], argv=sys.argv)
    recs = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    AA.annotate(recs)
    d1 = AA.distribution(recs, by="primary")
    d2 = AA.distribution(recs, by="endpoint")
    p1, p2, p3 = AA.write(a.outdir, recs, d1, d2)
    print(
        "[abstain-why] %d 条记录，其中 UNDETERMINED %d 条 -> %s"
        % (len(recs), d1["n_undetermined"], p1)
    )
    for r in d1["rows"]:
        print(
            "   %-34s %3d (%.1f%%)"
            % (r["abstention_reason"], r["n"], 100 * (r["share"] or 0))
        )


# ---- 模块M：结构性 vs 模型依赖弃权对比 ----
def cmd_abstain_cmp(a):
    from . import abstention_compare as AC
    from .manifest import write_manifest

    write_manifest(
        a.outdir,
        inputs=[a.reliability, a.truth, a.measurements, a.conformal],
        argv=sys.argv,
    )
    recs = list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
    truth = (
        list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        if a.truth and os.path.exists(a.truth)
        else None
    )
    meas = (
        check_measurements(a.measurements, a.allow_invalid, tag="abstain-cmp")
        if a.measurements and os.path.exists(a.measurements)
        else None
    )
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    conf = (
        list(csv.DictReader(io.open(a.conformal, encoding="utf-8-sig")))
        if a.conformal and os.path.exists(a.conformal)
        else None
    )
    res = AC.compare_by_endpoint(
        recs,
        truth_rows=truth,
        measurements=meas,
        rules=rules,
        proxy=a.proxy,
        conformal=conf,
        min_pairs=a.min_pairs,
    )
    print("[abstain-cmp] %d 个端点" % len(res["per_endpoint"]))
    for name, v in sorted(res["spread"].items()):
        print(
            "   %-18s endpoints=%d  mean_AURC=%s  sd=%s"
            % (
                name,
                v["n_endpoints"],
                "%.4f" % v["mean_aurc"] if v["mean_aurc"] is not None else "-",
                "%.4f" % v["sd"] if v["sd"] is not None else "-",
            )
        )
    print("   预测检验: %s" % res["prediction_check"])
    AC.write(a.outdir, res)


# ---- 模块O：失效模式三层检测 ----
def cmd_fail_layers(a):
    from . import failure_modes as FM
    from . import failure_layers as FL
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.input, a.reliability, a.rules, a.registry], argv=sys.argv
    )
    rows = check_measurements(a.input, a.allow_invalid, tag="fail-layers")
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    registry = None
    if a.registry and os.path.exists(a.registry):
        import yaml as _yaml

        registry = _yaml.safe_load(io.open(a.registry, encoding="utf-8")) or {}
    recs = (
        list(csv.DictReader(io.open(a.reliability, encoding="utf-8-sig")))
        if a.reliability and os.path.exists(a.reliability)
        else None
    )
    hits = FM.detect(
        rows,
        reliability=recs,
        rules=rules,
        registry=registry,
        chemical_class=a.chemical_class,
        expect_sources=a.expect_sources,
    )
    s = FL.summarize(
        hits, n_measurements=len(rows), n_records=len(recs or []), curated=a.curated
    )
    FL.write(a.outdir, hits, s)
    print("[fail-layers] 总命中 %d / %d 行" % (len(hits), len(rows)))
    for r in s["rows"]:
        print(
            "   %-28s 命中 %d（模式 %d/%d）"
            % (r["label"], r["n_hits"], r["n_modes_hit"], r["modes_defined"])
        )
    print("   特异性: %s" % s["specificity_note"][:110])


# ---- 模块L：跨数据集可迁移性 ----
def cmd_transfer(a):
    from . import transfer as TR
    from .manifest import write_manifest

    specs = _parse_sources(a.datasets)
    if len(specs) < 2:
        raise SystemExit("[transfer] 需要至少两个数据集：--datasets 'p1=n1,p2=n2'")
    write_manifest(a.outdir, inputs=[p for p, _, _ in specs], argv=sys.argv)
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    groups = {}
    if a.registry and os.path.exists(a.registry):
        from .phrasing import load_source_groups

        groups = load_source_groups(a.registry)
    # C-2026-11-03：decided_accuracy 此前是「文档宣称可选、CLI 无法触达」的死代码。
    # 现在 --truth 给了就真算；不给则跳过并在输出里显式标注 not_evaluated。
    truth_rows = None
    if getattr(a, "truth", ""):
        if not os.path.exists(a.truth):
            raise SystemExit("[transfer] --truth 路径不存在：%s" % a.truth)
        truth_rows = list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))
        write_manifest(
            a.outdir, inputs=[p for p, _, _ in specs] + [a.truth], argv=sys.argv
        )
        n_cls = sum(
            1
            for t in truth_rows
            if (t.get("truth_class") or "").strip().upper() in ("PASS", "FAIL")
        )
        if n_cls == 0:
            raise SystemExit(
                "[transfer] --truth 里没有任何 PASS/FAIL 真值类，"
                "decided_accuracy 不可估（需要 truth_class 列）"
            )
    profiles = []
    for path, name, _ in specs:
        rows = check_measurements(path, a.allow_invalid, tag="transfer:" + name)
        prof = TR.profile(name, rows, rules, groups)
        if truth_rows is not None:
            da = TR.decided_accuracy(name, rows, truth_rows, rules, groups)
            prof["n_decided_eval"] = da["n_eval"]
            prof["decided_accuracy"] = da["decided_accuracy"]
        else:
            prof["n_decided_eval"] = None
            prof["decided_accuracy"] = None
        profiles.append(prof)
    order = (
        tuple(x.strip() for x in a.expected_order.split(","))
        if a.expected_order
        else None
    )
    res = TR.compare(profiles, expected_order=order, proxy=bool(a.proxy))
    print("[transfer] %d 个数据集" % len(profiles))
    for p in profiles:
        da = (
            (
                "decided_acc=%s (n_decided=%s)"
                % (p.get("decided_accuracy"), p.get("n_decided_eval"))
            )
            if truth_rows is not None
            else "decided_acc=not_evaluated(未给 --truth)"
        )
        print(
            "   %-16s pairs=%d 弃权率=%.3f 域外触发率=%.3f  %s"
            % (
                p["name"],
                p["n_pairs"],
                p["abstention_rate"] or 0,
                p["domain_block_rate"] or 0,
                da,
            )
        )
    print("   方向性检验: %s" % res["prediction_check"])
    TR.write(a.outdir, res)


# ---- 方向B：Regaloside A vs B case study ----
def cmd_regaloside_ab(a):
    from . import case_regaloside as CR
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[], argv=sys.argv)
    res = CR.run()
    p1, p2, p3 = CR.write(res, a.outdir)
    print("[regaloside-ab] A(0.52%%) vs B(9.1%%) -> %s" % p3)
    print("   判定: %s" % res["verdict"][:200])
    for c in res["can_distinguish"]:
        print("   能区分: %s" % c)


# ---- 工作包 G：时间留出 temporal holdout 裁决（早期证据 → 晚期分子）----
def cmd_prospect(a):
    """用早期数据训练的模型裁决晚期分子，报 PASS 组实测失败率。"""
    from . import prospective as PR
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.measurements, a.truth, a.rules, a.registry], argv=sys.argv
    )
    rows = check_measurements(a.measurements, a.allow_invalid, tag="prospect")
    truth = PR.load_truth(a.truth)
    if not truth:
        raise SystemExit("[prospect] --truth 没有可判 PASS/FAIL 记录")
    rules = _load_rules(a.rules) if os.path.exists(a.rules) else {}
    groups = {}
    if a.registry and os.path.exists(a.registry):
        from .phrasing import load_source_groups

        groups = load_source_groups(a.registry)
    # 2026-11-04 / C08：禁止再自称前瞻；并检查预注册锚定状态。
    claim_allowed = False
    try:
        from .prereg import Prereg
        from . import release_gate as _RG

        _ledger = _RG._find_prereg_ledger(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        if _ledger:
            _st = Prereg(_ledger).anchor_status()
            claim_allowed = bool(_st.get("claim_allowed")) and not _st.get(
                "post_hoc_anchor"
            )
    except Exception:
        claim_allowed = False
    meta = dict(
        task="temporal holdout adjudication (early evidence -> late molecules)",
        design_type="temporal_holdout",
        not_preregistered=True,
        prereg_claim_allowed=claim_allowed,
        split_note=a.split_note
        or "OpenADMET-ExpansionRx 官方时序 split（train 早期 / test 晚期）；这是数据集设计时的切分，不是 T0 冻结后产生的新数据",
        early_evidence=a.early or "(未指定)",
        late_targets=a.measurements,
        truth=a.truth,
        wording_ban=[
            "true_prospective_claim",
            "prospective_blind_validation_claim",
            "prospective_validation_passed_claim",
        ],
    )
    if claim_allowed:
        print(
            "[prospect] ⚠ 检测到预注册锚定，但本命令仍属 temporal holdout；"
            "不得仅凭锚定改称前瞻（C08 / TEMPORAL_HOLDOUT_DISCIPLINE.md）"
        )
    res = PR.run(
        rows,
        truth,
        rules=rules,
        groups=groups,
        chemical_class=a.chemical_class,
        baseline_policy=a.baseline,
        outdir=a.outdir,
        meta=meta,
    )
    print("[prospect] %d 条晚期记录 / %d 个真值对" % (len(rows), len(truth)))
    for label, s in res["results"]:
        o = s["overall"]
        print(
            "   %-24s coverage=%s  decided_acc=%s  PASS失败率=%s  FAIL虚警率=%s"
            % (
                label,
                o["coverage"],
                o["decided_accuracy"],
                o["pass_failure_rate"],
                o["fail_false_alarm_rate"],
            )
        )


# ---- 工作包 A：真实源间相关性 ----
def cmd_source_rho(a):
    """两个真实源的逐端点 Spearman ρ + bootstrap CI（按 SMILES 对齐）。"""
    from . import source_rho as SR
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.source_a, a.source_b], argv=sys.argv)
    eps = (
        [x.strip() for x in a.endpoints.split(",") if x.strip()]
        if a.endpoints
        else None
    )
    res = SR.compare(
        a.source_a, a.source_b, endpoints=eps, label_a=a.label_a, label_b=a.label_b
    )
    print(
        "[source-rho] 对齐 %d 个分子 / %d 个共享端点"
        % (res["n_compounds"], res["n_shared_endpoints"])
    )
    print("   中位 Spearman ρ = %s" % res["median_spearman"])
    for r in res["rows"]:
        print(
            "   %-16s n=%2d  rho=%-7s CI=[%s, %s] 一致率=%s"
            % (
                r["endpoint"],
                r["n_pairs"],
                r["spearman"],
                r["ci_lo"],
                r["ci_hi"],
                r["class_agreement"],
            )
        )
    print("   判读: %s" % SR.verdict(res))
    SR.write(a.outdir, res)


# ---- F1 源注册门（CI 化）：真实执行入口 ----
def cmd_source_admit(a):
    """F1 注册门：候选源准入判定 = Clopper-Pearson 95% CI 上界 ≤ tol。

    C-2026-11-03：`adt.stats_ci.registration_gate` 此前已实现且有单测，但**没有任何
    管线步骤调用它**（SKILL.md 判据表的 F1 条款是"应做"规范而非已执行）——典型的
    文档-代码漂移。本命令是它的真实执行入口。

    输入 CSV（`--results`）必需列：`source, n, observed_failures`
    （observed_failures = 该源在验证集上的"失败/未通过"条数）。
    输出 `source_admission.json`，每源携带 n / observed_rate / ci_lower / ci_upper / passes，
    并显式区分「有统计把握地不过线」与「n 不足、不能宣称通过（带 CI 标注进入）」。
    """
    from . import stats_ci as SC
    from .manifest import write_manifest

    if not os.path.exists(a.results):
        raise SystemExit("[source-admit] --results 不存在：%s" % a.results)
    write_manifest(a.outdir, inputs=[a.results], argv=sys.argv)
    rows = list(csv.DictReader(io.open(a.results, encoding="utf-8-sig")))
    need = {"source", "n", "observed_failures"}
    if rows and not need.issubset(set(rows[0].keys())):
        raise SystemExit(
            "[source-admit] --results 缺列：需要 %s，实际 %s"
            % (sorted(need), sorted(rows[0].keys()))
        )
    out_rows = []
    for r in rows:
        name = (r.get("source") or "").strip()
        if not name:
            continue
        try:
            n = int(float(r.get("n")))
            obs = int(float(r.get("observed_failures")))
        except (TypeError, ValueError):
            raise SystemExit("[source-admit] %s 的 n/observed_failures 非数值" % name)
        if n < 0 or obs < 0 or obs > n:
            raise SystemExit(
                "[source-admit] %s 的 n=%s / observed=%s 非法（须 0≤obs≤n）"
                % (name, n, obs)
            )
        g = SC.registration_gate(obs, n, tol=a.tol, alpha=a.alpha)
        g["source"] = name
        g["decision"] = (
            "admit_with_ci_flag"
            if (not g["passes"] and g["n"] > 0 and g["ci_lower"] < a.tol)
            else ("admit" if g["passes"] else "reject")
        )
        g["disclosure_required"] = bool(not g["passes"])
        out_rows.append(g)
    payload = dict(
        tol=a.tol,
        alpha=a.alpha,
        criterion="Clopper-Pearson 95% CI upper <= tol",
        caveat=(
            "不通过 ≠ 源不可用：小源因 n 不足 CI 宽，应带 CI 标注进入并声明"
            "构成偏差（注册表向大源系统性倾斜）"
        ),
        rows=out_rows,
    )
    if a.design_p is not None:
        payload["design_curve"] = dict(
            p_true=a.design_p,
            pass_probability=SC.gate_pass_probability(
                a.design_p, tol=a.tol, alpha=a.alpha
            ),
        )
    p = os.path.join(a.outdir, "source_admission.json")
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("[source-admit] F1 注册门（CI 上界≤%g，alpha=%g）-> %s" % (a.tol, a.alpha, p))
    for g in out_rows:
        print(
            "   %-16s n=%-4d 失败率=%-7s CI=[%s, %s]  %s"
            % (
                g["source"],
                g["n"],
                (
                    ("%.4f" % g["observed_rate"])
                    if g["observed_rate"] is not None
                    else "-"
                ),
                g["ci_lower"],
                g["ci_upper"],
                "PASS（有把握不过线）" if g["passes"] else "未通过（%s）" % g["note"],
            )
        )
    if a.design_p is not None:
        print(
            "   设计曲线（真失败率 %g）：%s"
            % (a.design_p, payload["design_curve"]["pass_probability"])
        )


# ---- 工作包 A/C：结构变体提交清单 ----
def cmd_ac_plan(a):
    """生成 A/C 用的结构变体提交清单（original/去立体/互变体）+ 分批。"""
    from . import ac_plan as AP
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.compounds], argv=sys.argv)
    comps = AP.load_compounds(a.compounds)
    if not comps:
        raise SystemExit("[ac-plan] 没有读到 compound_id + SMILES")
    kinds = tuple(x.strip() for x in a.kinds.split(",") if x.strip())
    rows = AP.build(comps, kinds=kinds, include_controls=a.controls)
    batches = AP.to_batches(rows, size=a.batch_size, skip_noop=not a.keep_noop)
    meta = dict(
        compounds=a.compounds,
        n_compounds=len(comps),
        kinds=",".join(kinds),
        batch_size=a.batch_size,
        controls=("included" if a.controls else "excluded"),
    )
    p1, p2, p3 = AP.write(a.outdir, rows, batches, meta)
    n_noop = sum(1 for r in rows if r.get("noop") == "Y")
    print(
        "[ac-plan] %d 个分子 -> %d 行变体（no-op %d 行已跳过）-> %d 批"
        % (len(comps), len(rows), n_noop, len(batches))
    )
    print("   清单: %s" % p1)
    print("   分批: %s（每批 SMILES 在 batches/ 下）" % p2)
    print("   说明: %s" % p3)


# ---- 工作包 C：预测值位移 ----
def cmd_pred_shift(a):
    """结构扰动引起的源预测位移 vs 源间分歧。"""
    from . import pred_displacement as PD
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.variants, a.source_shift], argv=sys.argv)
    rows = PD.load_long(a.variants)
    if not rows:
        raise SystemExit(
            "[pred-shift] --variants 没有可解析记录"
            "（需 compound_id,variant,endpoint,value）"
        )
    src = PD.load_source_shift(a.source_shift)
    disp = PD.displacement(rows)
    flip_counts, flip_detail = PD.threshold_flips(rows, thr=a.flip_threshold)
    cmp_rows = PD.compare(disp, src, flip_check=flip_counts)
    p1, p2 = PD.write(a.outdir, cmp_rows, note=a.note, flip_detail=flip_detail)
    print("[pred-shift] %d 个 (端点,变体) 组合 -> %s" % (len(cmp_rows), p1))
    for r in cmp_rows[:20]:
        print(
            "   %-16s %-16s 位移=%-9s 源间=%-9s 比值=%-6s 翻转=%s"
            % (
                r["endpoint"],
                r["variant"],
                r["mean_abs_shift"],
                r.get("source_shift"),
                r.get("ratio_vs_source"),
                r.get("threshold_flips") or 0,
            )
        )
    if flip_detail:
        print("   阈值翻转共 %d 例（明细见 threshold_flips.csv）" % len(flip_detail))
        for r in sorted(flip_detail, key=lambda x: -abs(x["delta"]))[:5]:
            print(
                "      %s %s %s: %.3f -> %.3f"
                % (
                    r["endpoint"],
                    r["variant"],
                    r["compound_id"],
                    r["original"],
                    r["variant_value"],
                )
            )
    print("   判读: %s" % PD.verdict(cmp_rows))


def cmd_endpoint_tiers(a):
    """R21：端点三级清单（可裁决 / 仅定性 / 不推荐计算）。"""
    from adt.endpoints import tier_table

    rows = tier_table()
    for r in rows:
        print("%-22s %-18s %s" % (r["endpoint"], r["tier"], r["reason"]))
    if a.out:
        with io.open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["endpoint", "tier", "reason"])
            w.writeheader()
            w.writerows(rows)


def cmd_indep_power(a):
    """R05：相关检验功效报告（拒绝静默出权重的前置）。"""
    from adt.stats_ci import correlation_power_report

    ns = [int(x) for x in a.n.split(",") if x.strip()]
    out = [correlation_power_report(n, alpha=a.alpha) for n in ns]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(
            json.dumps(out, ensure_ascii=False, indent=2)
        )


def cmd_indep_bayes(a):
    """R07/B1：相关性矩阵贝叶斯收缩 → n_eff 后验 → 裁决稳健概率。"""
    from adt.independence import bayes_contraction

    k = a.k
    if a.rho_matrix:
        rows = [r for r in csv.reader(io.open(a.rho_matrix, encoding="utf-8-sig")) if r]
        R = [[float(x) for x in r] for r in rows]
    else:
        R = [[1.0 if i == j else a.rho for j in range(k)] for i in range(k)]
    votes = [float(x) for x in a.votes.split(",")] if a.votes else None
    res = bayes_contraction(R, n_obs=a.n, votes=votes, n_draws=a.draws, seed=a.seed)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(
            json.dumps(res, ensure_ascii=False, indent=2)
        )


def _load_timestamps(path):
    """读数据时间戳：JSON 数组 / {"timestamps":[...]} / 每行一个（可带 CSV 列）。

    P2.2 的输入不可控（审稿人可能给 CSV、给 JSON、给纯文本），这里做宽容解析，
    解析失败的条目由 `Prereg.temporal_validity()` 记为 bad_timestamp 并拒绝放行。
    """
    import json as _json

    raw = open(path, encoding="utf-8-sig").read().strip()
    if not raw:
        return []
    if raw[0] in "[{":
        try:
            obj = _json.loads(raw)
        except Exception:  # noqa: BLE001
            obj = None
        if isinstance(obj, list):
            return [str(x) for x in obj]
        if isinstance(obj, dict):
            for key in ("timestamps", "data_timestamps", "dates", "collected_at"):
                if isinstance(obj.get(key), list):
                    return [str(x) for x in obj[key]]
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s.split(",")[-1].strip())  # 末列当时间戳（容忍 "id,date" 形式）
    return out


def cmd_prereg_status(a):
    """打印预注册锚定状态（P2.1：把"能不能声称已预注册"变成一条命令）。

    为什么需要它：`adt/prereg.py` 只有 Python API，评审复现/协作方无从确认
    "这份材料到底锚定没锚定"。本命令让 G9 的判定可被人手复核：
    exit 0 = claim_allowed=True；exit 3 = 未锚定（材料不得写"已完成预注册"）。
    """
    import json as _json
    from .prereg import Prereg

    if not os.path.exists(a.log):
        print("[prereg] 找不到预注册链：%s" % a.log, file=sys.stderr)
        sys.exit(3)
    p_obj = Prereg(a.log)
    st = p_obj.anchor_status()
    print(_json.dumps(st, ensure_ascii=False, indent=2))
    if not st.get("claim_allowed"):
        print(
            "[prereg] UNANCHORED：材料只能写『标准已登记，待第三方时间戳锚定』",
            file=sys.stderr,
        )
        sys.exit(3)
    print(
        "[prereg] 锚定有效：registry=%s doi=%s deposited_at=%s"
        % (st.get("registry"), st.get("doi"), st.get("deposited_at"))
    )

    # P2.2：给出数据时间戳时，额外校验"锚定先于数据"
    path = getattr(a, "data_timestamps", None)
    if path:
        if not os.path.exists(path):
            print("[prereg] 数据时间戳文件不存在：%s" % path, file=sys.stderr)
            sys.exit(4)
        rows = _load_timestamps(path)
        tv = p_obj.temporal_validity(rows)
        print(_json.dumps({"temporal_validity": tv}, ensure_ascii=False, indent=2))
        if not tv.get("ok"):
            print(
                "[prereg] 时序不合规（%s）：%d 条数据不晚于锚定，主分析集须剔除"
                % (tv.get("reason"), tv.get("n_violations") or 0),
                file=sys.stderr,
            )
            sys.exit(4)
        print(
            "[prereg] 时序合规：%d 条数据全部晚于锚定 %s"
            % (tv["n_data"], tv["anchor_date"])
        )


def cmd_prereg_init(a):
    """登记一条可机器判定的判据到预注册哈希链（append-only）。

    同行评审 P1-1 同型缺陷修复：此前 Prereg 只有 Python API，用户/审稿人
    无从通过 CLI 建立可复核的预注册链，prereg-status 永远是"文件不存在"。
    本命令提供写入口；未给外部锚定时如实标记 UNANCHORED（不得声称已预注册）。
    """
    import json as _json
    from .prereg import Prereg, PreregError

    try:
        criteria = _json.loads(a.criteria)
    except Exception as ex:
        raise SystemExit("[prereg] --criteria 必须是 JSON 对象：%s" % ex)
    if not isinstance(criteria, dict):
        raise SystemExit("[prereg] --criteria 必须是 JSON 对象（不是数组/标量）")
    anchor = None
    if a.doi or a.registry:
        anchor = {
            "registry": a.registry,
            "doi": a.doi,
            "deposited_at": a.deposited_at or "",
        }
    try:
        pr = Prereg(a.log)
        h = pr.register_criteria(
            a.name, criteria, note=a.note or "", external_anchor=anchor
        )
    except PreregError as ex:
        raise SystemExit("[prereg] %s" % ex)
    st = pr.anchor_status()
    print("[prereg] 已登记 criteria=%s hash=%s → %s" % (a.name, h, a.log))
    if not st.get("claim_allowed"):
        print(
            "[prereg] UNANCHORED：仅完成本机登记；须补第三方时间戳"
            "（--registry/--doi/--deposited-at）才可声称已预注册",
            file=sys.stderr,
        )
    return 0


def cmd_snapshot_summary(a):
    from adt import snapshot as SNAP

    s = SNAP.summary(a.root)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(s, ensure_ascii=False, indent=2))


def cmd_snapshot_verify(a):
    from adt import snapshot as SNAP

    rows = SNAP.verify(a.root, a.id or None)
    bad = [r for r in rows if not r[1]]
    print("[snapshot-verify] %d 条，失败 %d 条" % (len(rows), len(bad)))
    for r in bad[:20]:
        print("   FAIL %s  %s" % (r[0], r[2]))
    if bad:
        raise SystemExit(1)


def cmd_env_fp(a):
    from adt import release_gate as RG

    fp = RG.env_fingerprint()
    txt = json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=True)
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        print("[env-fp] -> %s" % a.out)
    print(txt)


def cmd_env_audit(a):
    """换机后的环境自检（v4.22）：退出码 0/1/2 由 env_audit 自己决定。"""
    from adt import env_audit as EA

    argv = []
    if a.json_out:
        argv += ["--json-out", a.json_out]
    if a.network:
        argv += ["--network"]
    if getattr(a, "deep", False):
        argv += ["--deep"]
    if a.quiet:
        argv += ["--quiet"]
    if getattr(a, "required_only", False):
        argv += ["--required-only"]
    # main() 里是 `a.func(a)`（返回值被丢弃），所以必须用 SystemExit 传递退出码，
    # 否则 CI 会把"必需层缺失"误读成成功。
    raise SystemExit(EA.main(argv))


def cmd_release_check(a):
    from adt import release_gate as RG

    res = RG.check(a.root)
    print("[release-check] %s" % ("PASS" if res["passed"] else "BLOCKED"))
    for it in res["items"]:
        # 2026-11-04 纠错：**门的状态（ok）与门的等级（level）必须分开显示**。
        # 旧实现按 level 打标，把「blocker 级且已通过」的 G1/G2/G3 印成 BLOCK，
        # 又把新增的 level="info" 直接 KeyError 崩掉 —— 两者都会让门禁结果不可读。
        if not it["ok"]:
            mark = "FAIL "
        elif it["level"] == "warn":
            mark = "WARN "
        else:
            mark = "OK  "
        print("   %s %-5s %-26s %s" % (mark, it["level"], it["key"], it["detail"]))
        if not it["ok"] and it["fix"]:
            print("        fix: %s" % it["fix"])
    if a.json_out:
        with io.open(a.json_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False, indent=2))
    if not res["passed"]:
        raise SystemExit(2)


def cmd_pka(a):
    """电离状态 / pKa 层（v4.14）：类别级文献区间 + Henderson–Hasselbalch。"""
    from . import ionization as IZ
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    comps = load_compounds_csv(a.input, fmt=getattr(a, "format", "auto"))
    rows, skipped = [], []
    for c in comps:
        cid = c["compound_id"]
        smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles")
        prof = IZ.ionization_profile(smi, ph=a.ph)
        if not prof["available"]:
            skipped.append((cid, "SMILES 不可解析"))
            continue
        logp = ""
        if smi:
            try:
                from rdkit import Chem, RDLogger
                from rdkit.Chem import Descriptors

                RDLogger.DisableLog("rdApp.*")
                m = Chem.MolFromSmiles(smi)
                logp = round(Descriptors.MolLogP(m), 3) if m else ""
            except Exception:  # noqa: BLE001  logP 缺失不阻断电离判定
                logp = ""
        ld = IZ.logd_from_logp(logp, prof) if logp != "" else {}
        agg = {}
        for g in prof["groups"]:
            agg.setdefault(g["name"], []).append(g["pka"])
        rows.append(
            dict(
                compound_id=cid,
                ph=prof["ph"],
                charge_class=prof["charge_class"],
                n_acid=prof["n_acid"],
                n_base=prof["n_base"],
                zwitterion=int(bool(prof["zwitterion"])),
                f_neutral=prof["f_neutral"],
                f_neutral_lo=prof["f_neutral_range"][0],
                f_neutral_hi=prof["f_neutral_range"][1],
                net_charge=prof["net_charge"],
                net_charge_lo=prof["net_charge_range"][0],
                net_charge_hi=prof["net_charge_range"][1],
                ionizable_groups=";".join(
                    "%s×%d" % (k, len(v)) for k, v in agg.items()
                ),
                pka_centres=";".join("%s=%.1f" % (k, v[0]) for k, v in agg.items()),
                bracket_straddles_ph=int(bool(prof["bracket_straddles_ph"])),
                clogp=logp,
                logd_7_4=ld.get("logD", ""),
                logd_7_4_lo=ld.get("logD_range", ("", ""))[0],
                logd_7_4_hi=ld.get("logD_range", ("", ""))[1],
                pka_grade=prof["pka_grade"],
                limits=prof["limits"],
            )
        )
    if not rows:
        print("[pka] 没有可用分子（SMILES 不可解析？）%s" % skipped)
        return
    cols = list(rows[0].keys())
    p = os.path.join(a.outdir, "ionization.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("[pka] %d 个分子 -> %s" % (len(rows), p))
    for c in comps:
        cid = c["compound_id"]
        smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles")
        print("   " + IZ.render(IZ.ionization_profile(smi, ph=a.ph), cid))
    n_ion = sum(
        1
        for r in rows
        if r["charge_class"] != "neutral_no_group"
        and r["charge_class"] != "neutral_dominant"
    )
    print(
        "[pka] ⚠ pKa 是**类别级文献区间**（±1 log 量级），不是本分子实测；"
        "只能用于电离分区与方向判断（%d/%d 个分子在 pH %.1f 下显著电离）"
        % (n_ion, len(rows), a.ph)
    )
    print(
        "[pka] 需要数值请用 Graph-pKa/电位滴定，再走 "
        "`adt.cli readback --source graphpka` 回填"
    )


_CARDIAC_KEYS = {
    "herg": "herg",
    "cav12": "cav12",
    "cav1.2": "cav12",
    "nav15": "nav15",
    "nav1.5": "nav15",
}


def cmd_cardiac(a):
    """心脏离子通道三联（v4.15）：证据齐全度 + 通道级裕度，不给净效应概率。"""
    from . import cardiac_panel as CP
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[a.input] + ([a.exposure] if a.exposure else []), argv=sys.argv
    )
    rows_raw = check_measurements(a.input, a.allow_invalid, tag="cardiac")

    by_cid = {}
    n_manual = 0
    for r in rows_raw:
        # 2026-11-19（面板实跑）：旧实现只收 predicted/measured，把 `manual` 静默丢掉。
        # 后果自相矛盾：本命令自己打印的指引说"cardiac 端点只能来自膜片钳实测或
        # Cardiosim-Tox 回填"，而 readback 默认就可能写 manual —— 用户照做后
        # 得到"没有识别到 cardiac_* 端点"，等于把刚回填的数据吃掉。
        if (r.get("domain_flag") or "") not in ("predicted", "measured", "manual"):
            continue
        if r.get("domain_flag") == "manual":
            n_manual += 1
        ep = (r.get("endpoint") or "").lower()
        ch = None
        for k, v in _CARDIAC_KEYS.items():
            if ep.startswith("cardiac_") and (k in ep):
                ch = v
                break
        if ch is None:
            continue
        try:
            val = float(r["value"])
        except (TypeError, ValueError, KeyError):
            continue
        slot = by_cid.setdefault(r["compound_id"], {}).setdefault(ch, {})
        if "ic50" in ep:
            slot["ic50_uM"] = val
        elif "inh" in ep or "inhibition" in ep:
            slot["inh_pct"] = val

    cmax = {}
    if a.exposure and os.path.exists(a.exposure):
        for x in csv.DictReader(io.open(a.exposure, encoding="utf-8-sig")):
            try:
                cmax[x["compound_id"]] = float(
                    x.get("cmax_uM") or x.get("cmax_uM_like") or ""
                )
            except (TypeError, ValueError, KeyError):
                continue

    if n_manual:
        print(
            "[cardiac] 注意：纳入 %d 条 domain_flag=manual 的人工读数"
            "（须核对 provenance_url；manual 不进源独立性计票）" % n_manual
        )
    if not by_cid:
        print("[cardiac] 没有识别到 cardiac_* 端点。需要长表里有以下任一：")
        for ch in CP.CHANNELS:
            print(
                "   %-8s %s / %s" % (ch["id"], ch["ic50_endpoint"], ch["inh_endpoint"])
            )
        print(
            "[cardiac] 这些端点目前**没有任何计算源提供**（ADMETlab/ADMET-AI/vNN "
            "都只给 hERG 概率），只能来自膜片钳实测或 Cardiosim-Tox 回填："
        )
        print(
            "   adt.cli readback --source cardiosim_tox --file <导出.csv> "
            "--compounds out/compounds.csv --map '列名=cardiac_herg_ic50:uM'"
        )
        return

    out = CP.panel(by_cid, cmax)
    cols = list(out[0].keys())
    p = os.path.join(a.outdir, "cardiac_panel.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print("[cardiac] %d 个分子 -> %s" % (len(out), p))
    for r in out:
        print(
            "   %-14s %-32s 已测 %d/3 缺 %s"
            % (
                r["compound_id"],
                r["panel_verdict"],
                r["n_channels"],
                r["missing_channels"] or "-",
            )
        )
    n_herg_only = sum(1 for r in out if r["n_channels"] == 1)
    if n_herg_only:
        print(
            "[cardiac] ⚠ %d 个分子只有 hERG 单通道：**不能据此排除**多通道致心律"
            "失常风险（Cav1.2 阻断可抵消 APD 延长；Nav1.5 晚电流可独立致心律失常）"
            % n_herg_only
        )
    print(
        "[cardiac] 说明：未做 ORd/AP 仿真，net_effect=not_estimated；"
        "「三通道全 LOW」≠ 安全，只等于「在已测通道内未见高风险」"
    )


def cmd_pd(a):
    """PK/PD 连接（v4.16）：Hill 直接效应 / 效应室 / fT>EC50 / 最小 TMDD。"""
    from . import pd_link as PD
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.curves], argv=sys.argv)

    curves = {}
    with io.open(a.curves, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cid = r.get("compound_id") or "?"
            try:
                t = float(r["t_h"])
                c = float(r["c_mg_per_L"])
            except (TypeError, ValueError, KeyError):
                continue
            curves.setdefault(cid, []).append((t, c))

    if not curves:
        print("[pd] %s 里没有 (compound_id, t_h, c_mg_per_L) 记录" % a.curves)
        return

    mw_by = {}
    if a.compounds and os.path.exists(a.compounds):
        for c in load_compounds_csv(a.compounds, fmt=getattr(a, "format", "auto")):
            smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles")
            try:
                from rdkit import Chem, RDLogger
                from rdkit.Chem import Descriptors

                RDLogger.DisableLog("rdApp.*")
                m = Chem.MolFromSmiles(smi) if smi else None
                if m is not None:
                    mw_by[c["compound_id"]] = Descriptors.MolWt(m)
            except Exception:  # noqa: BLE001
                continue

    out, tmdd_out = [], []
    for cid, pts in curves.items():
        pts.sort()
        t = [p[0] for p in pts]
        c_mg = [p[1] for p in pts]
        mw = mw_by.get(cid) or a.mw
        if not mw:
            print(
                "[pd] %s 缺 mw（--mw 或 --compounds）→ 无法把 mg/L 换成 µM，跳过" % cid
            )
            continue
        c_uM = PD.c_mg_per_L_to_uM(c_mg, mw)
        try:
            m = PD.pd_metrics(
                t,
                c_uM,
                a.ec50,
                a.emax,
                n=a.hill_n,
                e0=a.e0,
                ke0=a.ke0 or None,
                interval_h=a.dosing_interval,
                label=cid,
            )
        except PD.PDParameterError as e:
            print("[pd] %s 参数不合法：%s" % (cid, e))
            continue
        m.update(
            compound_id=cid,
            mw=round(mw, 2),
            cmax_plasma_uM=round(max(c_uM), 4),
            ec50_um=a.ec50,
            emax=a.emax,
            ke0=a.ke0 or "",
        )
        out.append(m)
        if a.tmdd_params:
            vals = [float(x) for x in a.tmdd_params.split(",")]
            if len(vals) != 5:
                print("[pd] --tmdd-params 需要 5 个值：R0,kon,koff,kint,kdeg")
            else:
                try:
                    d = PD.tmdd_minimal(t, c_uM * 1000.0, *vals, label=cid)
                    d.update(compound_id=cid)
                    tmdd_out.append(d)
                except PD.PDParameterError as e:
                    print("[pd] TMDD 拒绝计算（%s）：%s" % (cid, e))

    if not out:
        print("[pd] 没有产出任何 PD 指标")
        return
    p = os.path.join(a.outdir, "pd_metrics.csv")
    base = [
        "compound_id",
        "mw",
        "cmax_plasma_uM",
        "ec50_um",
        "emax",
        "ke0",
        "t_above_ec50_h",
        "t_above_ec90_h",
        "frac_interval_above_ec50",
        "effect_auc",
        "effect_peak",
        "t_peak_effect_h",
        "driver",
        "status",
    ]
    cols = base + [k for k in out[0] if k not in base]
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print("[pd] %d 个分子 -> %s" % (len(out), p))
    for r in out:
        fi = r["frac_interval_above_ec50"]
        print(
            "   %-14s fT>EC50=%.2f h（间隔覆盖 %s）峰效应 %.1f @ %.2f h"
            % (
                r["compound_id"],
                r["t_above_ec50_h"],
                "-" if fi == "" else "%.0f%%" % (100 * float(fi)),
                r["effect_peak"],
                r["t_peak_effect_h"],
            )
        )
    if a.dosing_interval:
        n_ok = sum(1 for r in out if (r["frac_interval_above_ec50"] or 0) >= 0.5)
        print(
            "[pd] 以 %g h 为给药间隔：%d/%d 个分子在间隔内 ≥50%% 时间高于 EC50"
            % (a.dosing_interval, n_ok, len(out))
        )
    if tmdd_out:
        q = os.path.join(a.outdir, "pd_tmdd.csv")
        with io.open(q, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(tmdd_out[0]), extrasaction="ignore")
            w.writeheader()
            w.writerows(tmdd_out)
        print("[pd] TMDD 最小模型 %d 条 -> %s" % (len(tmdd_out), q))
    print("[pd] ⚠ %s" % PD.qualification_statement())


def cmd_pbpk_qualify(a):
    """PBPK 资格认定（v4.17）：AFE/AAFE/2 倍内比例 + 惯例工作点判定。"""
    from . import pbpk_qualify as PQ
    from .manifest import write_manifest

    write_manifest(a.outdir, inputs=[a.obs, a.pred], argv=sys.argv)

    pairs = []
    # 2026-11-19（面板实跑）：pred 路径写错时旧行为是裸 FileNotFoundError，
    # 用户看到的是 20 行 traceback 而不是"文件不存在"。这类输入错误必须干净退出。
    if not os.path.exists(a.pred):
        print("[pbpk-qualify] ✗ 预测表不存在：%s" % a.pred, file=sys.stderr)
        print(
            "[pbpk-qualify] 期望列：compound_id,time_h,pred,unit（可含 obs）；"
            "可由 `adt.cli pbpk --dump-curves` 产出。",
            file=sys.stderr,
        )
        sys.exit(3)
    with io.open(a.pred, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            pairs.append(
                dict(
                    compound_id=r.get("compound_id"),
                    time_h=r.get("time_h"),
                    obs=r.get("obs"),
                    pred=r.get("pred"),
                    unit=r.get("unit"),
                )
            )
    if a.obs and os.path.exists(a.obs) and a.obs != a.pred:
        # 允许 obs/pred 分表：按 (compound_id,time_h) 合并
        idx = {}
        with io.open(a.obs, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                idx[(r.get("compound_id"), str(r.get("time_h")))] = r
        merged = []
        for p in pairs:
            o = idx.get((p["compound_id"], str(p["time_h"])))
            if o is None:
                continue
            merged.append(
                dict(
                    compound_id=p["compound_id"],
                    time_h=p["time_h"],
                    obs=o.get("value") or o.get("obs"),
                    pred=p.get("pred") or p.get("value"),
                    unit=p.get("unit") or o.get("unit"),
                )
            )
        pairs = merged

    try:
        res = PQ.qualify(pairs, intended_use=a.intended_use)
    except PQ.QualificationError as e:
        # 2026-11-19：拒绝语义统一到 rc=4（与红线/门禁拦截同码）。旧值 2 与
        # argparse 的"用法错误"撞车，脚本无法区分"参数写错"和"数据不合格"。
        print("[pbpk-qualify] 拒绝评估：%s" % e)
        raise SystemExit(4)

    rows = [
        dict(
            compound_id=r["compound_id"],
            n_obs=r["n_obs"],
            afe=r["afe"],
            aafe=r["aafe"],
            pct_2fold=r["pct_2fold"],
            worst_fold=r["worst_fold"],
        )
        for r in res["per_compound"]
    ]
    p = os.path.join(a.outdir, "pbpk_qualification.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    j = os.path.join(a.outdir, "pbpk_qualification.json")
    with io.open(j, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=2))

    print(
        "[pbpk-qualify] 配对 n=%d（%d 个化合物，最少 %d 个时点），单位 %s"
        % (
            res["n_pairs"],
            res["n_compounds"],
            res["min_timepoints"],
            res["unit"] or "-",
        )
    )
    print(
        "[pbpk-qualify] AFE %.2f  AAFE %.2f  2倍内 %.0f%%  3倍内 %.0f%%  "
        "rmse(log10) %.2f"
        % (
            res["afe"],
            res["aafe"],
            100 * res["pct_2fold"],
            100 * res["pct_3fold"],
            res["rmse_log10"],
        )
    )
    print("[pbpk-qualify] 判定：%s —— %s" % (res["verdict"], res["reason"]))
    print("[pbpk-qualify] 允许表述：%s" % res["allowed_statement"])
    print("[pbpk-qualify] 阈值来源：%s" % res["thresholds"]["source"])
    print("[pbpk-qualify] 边界：%s" % res["limits"])
    print("[pbpk-qualify] 产物：%s / %s" % (p, j))


def cmd_interop(a):
    """外部 PK/PD 工具互操作（v4.18）：PK-Sim 参数表 / NONMEM-nlmixr2 数据集。"""
    from . import interop as IO
    from .manifest import write_manifest

    write_manifest(
        a.outdir, inputs=[x for x in (a.compounds, a.curves) if x], argv=sys.argv
    )

    if a.what in ("pk-sim", "all"):
        params, pka_by, ion_by, pka_centres = {}, {}, {}, {}
        if a.compounds and os.path.exists(a.compounds):
            from rdkit import Chem, RDLogger
            from rdkit.Chem import Descriptors

            RDLogger.DisableLog("rdApp.*")
            for c in load_compounds_csv(a.compounds, fmt=getattr(a, "format", "auto")):
                cid = c["compound_id"]
                smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles")
                m = Chem.MolFromSmiles(smi) if smi else None
                if m is None:
                    continue
                try:
                    from . import ionization as IZ

                    prof = IZ.ionization_profile(smi)
                    pka_by[cid] = sorted(
                        {round(float(g["pka"]), 1) for g in prof["groups"]}
                    )
                    # 快照要写 PK-Sim 的 PkaTypes（必须带 Acid/Base 类型）
                    pka_centres[cid] = [
                        dict(kind=g["kind"], pka=g["pka"]) for g in prof["groups"]
                    ]
                    # PK-Sim 的 compound type 看"有没有酸/碱基团"，不看 pH 7.4 的净电荷：
                    # 同时有酸性和碱性基团 = ampholyte（即使当下不是两性离子）
                    if prof["n_acid"] and prof["n_base"]:
                        ion_by[cid] = (
                            "zwitterion" if prof["zwitterion"] else "ampholyte"
                        )
                    elif prof["n_acid"]:
                        ion_by[cid] = "acid"
                    elif prof["n_base"]:
                        ion_by[cid] = "base"
                    else:
                        ion_by[cid] = "neutral"
                except Exception:  # noqa: BLE001  电离失败不阻断导出
                    pass
                params[cid] = dict(
                    mw=Descriptors.MolWt(m), clogp=Descriptors.MolLogP(m)
                )
        if not params:
            print("[interop] --what pk-sim 需要 --compounds（含 SMILES）")
        else:
            rows, meta = IO.pk_sim_compounds(params, pka_by, ion_by)
            p = os.path.join(a.outdir, "pk_sim_compounds.csv")
            IO.write_pk_sim_compounds(p, rows)
            print("[interop] PK-Sim 化合物参数 %d 个 -> %s" % (len(rows), p))
            for name, note in meta["fields_without_source"]:
                print("   未映射：%-38s %s" % (name, note))
            if meta["columns_empty_in_batch"]:
                print(
                    "   本批全空：%s（导入 PK-Sim 后需按内置模型补）"
                    % ", ".join(meta["columns_empty_in_batch"])
                )
            if getattr(a, "snapshot", False):
                snap, smeta = IO.pk_sim_snapshot(params, pka_centres, ion_by)
                sp = os.path.join(a.outdir, "pk_sim_snapshot.json")
                IO.write_pk_sim_snapshot(sp, snap)
                print(
                    "[interop] PK-Sim 快照（Version %d）-> %s"
                    % (smeta["snapshot_version"], sp)
                )
                print(
                    "[interop]    用 PKSim.CLI snap -p -i <snapshot 所在目录> -o <输出目录>"
                    " 即可转 .pksim5（已实测）"
                )
                for w in smeta["problems"]:
                    print("[interop]    快照提醒：%s" % w)
                for nm, why in smeta["omitted"]:
                    print("[interop]    故意留空：%-38s %s" % (nm, why))
            print("[interop] %s" % IO.INTEROP_NOTICE)

    if a.what in ("nonmem", "all"):
        if not a.curves or not os.path.exists(a.curves):
            print("[interop] --what nonmem 需要 --curves（模拟或观测的 C(t)）")
        else:
            recs = []
            with io.open(a.curves, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    recs.append(
                        dict(
                            id=r["compound_id"],
                            time=r["t_h"],
                            dv=r.get("c_mg_per_L"),
                            amt=0,
                            dvid=1,
                        )
                    )
            # 每个化合物补一条给药记录（t=0, EVID=1）
            dosed = []
            for cid in sorted({x["id"] for x in recs}):
                dosed.append(
                    dict(
                        id=cid,
                        time=0.0,
                        amt=a.dose_mg,
                        dv="",
                        cmt=getattr(a, "dose_cmt", 1),
                        evid=1,
                    )
                )
            id_map = IO.nonmem_id_map(dosed + recs)
            oc = getattr(a, "obs_cmt", None)
            rows = IO.nonmem_dataset(
                dosed + recs,
                id_map=id_map,
                default_cmt=getattr(a, "dose_cmt", 1),
                obs_cmt=oc,
            )
            masked = IO.mask_nonpositive_obs(rows)
            if masked:
                print(
                    "[interop] 已屏蔽 %d 条非正观测（MDV=1）：模拟曲线的"
                    "数值零不是测量值，当真实值会主导目标函数" % masked
                )
            problems = IO.validate_nonmem(
                rows,
                expect_cmt_split=(oc is not None and oc != getattr(a, "dose_cmt", 1)),
            )
            p = os.path.join(a.outdir, "nonmem_dataset.csv")
            IO.write_nonmem(p, rows)
            mp = os.path.join(a.outdir, "nonmem_id_map.csv")
            with io.open(mp, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["compound_id", "ID"])
                for cid_k in sorted(id_map):
                    w.writerow([cid_k, id_map[cid_k]])
            print("[interop] NONMEM/nlmixr2 数据集 %d 行 -> %s" % (len(rows), p))
            print(
                "[interop] ID 映射（NONMEM 要求整数 ID）%d 条 -> %s" % (len(id_map), mp)
            )
            if problems:
                print("[interop] 契约问题 %d 条：" % len(problems))
                for x in problems[:10]:
                    print("   - %s" % x)
            else:
                print("[interop] 契约校验通过")
            q = os.path.join(a.outdir, "nlmixr2_skeleton.R")
            with io.open(q, "w", encoding="utf-8") as fh:
                ini = IO.pk_initials(rows, dose_mg=a.dose_mg)
                note = None
                if ini:
                    note = (
                        "# 初值由 pk_initials 从 C(t) 推得（%d 个化合物取中位数）："
                        "V0=AMT/Cmax、ka0=1/Tmax、CL0=λz·V0、addSd=0.05·median(C)。\n"
                        "# 这些是初值不是估计结果；%r" % (ini["n_compounds"], ini)
                    )
                fh.write(
                    IO.nlmixr2_skeleton(
                        data_path=os.path.abspath(p).replace("\\", "/"),
                        init_note=note,
                        cl_init=ini.get("cl_init", 5.0),
                        v_init=ini.get("v_init", 50.0),
                        ka_init=ini.get("ka_init", 0.6),
                        add_sd=ini.get("add_sd", 0.1),
                    )
                )
            print(
                "[interop] nlmixr2 骨架 -> %s（nlmixr2_fit_passed；实测 FOCEI 收敛，但 ID=化合物，eta 不是 IIV）"
                % q
            )
            print("[interop] %s" % IO.INTEROP_NOTICE)


def _gut_micro_write_report(
    outdir,
    rows,
    *,
    source="biotransformer",
    source_version="3.0",
    provenance_url="https://biotransformer.ca",
    qc=None,
    controlled=False,
):
    """gut-micro 的共同写盘 + 标注 QC 报告（REST 与人工导出两条路径共用）。"""
    from . import gut_microbiome as GM

    outr = GM.metabolite_rows(
        rows,
        source=source,
        source_version=source_version,
        provenance_url=provenance_url,
    )
    p = os.path.join(outdir, "metabolites_gut.csv")
    if outr:
        with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(outr[0]), extrasaction="ignore")
            w.writeheader()
            w.writerows(outr)
        print("[gut-micro] 菌群来源产物 %d 条 -> %s" % (len(outr), p))
    else:
        print("[gut-micro] 菌群来源产物 0 条 -> 记 out_of_domain（不是'无代谢'）")

    bad = [r for r in outr if r["label_check"] == "inconsistent"]
    if bad:
        print(
            "[gut-micro] ⚠ %d/%d 条转化的 reaction_type 与质量差矛盾（实测已知缺陷）："
            % (len(bad), len(outr))
        )
        for r in bad[:5]:
            print(
                "   %s: %s（Δm=%.2f）"
                % (r["compound_id"], r["reaction_type"][:40], r["label_delta_mass"])
            )
        print(
            "   结论：只引用 metabolite_smiles/inchikey，不要引用 reaction_type/enzymes"
        )
    qc = qc or {}
    if qc.get("out_of_domain"):
        print(
            "[gut-micro] out_of_domain %d 个：%s"
            % (
                len(qc["out_of_domain"]),
                [d["compound_id"] for d in qc["out_of_domain"]],
            )
        )
    print("[gut-micro] 边界：%s" % GM.limits_statement())
    return outr


def cmd_gut_micro(a):
    """肠道菌群代谢（v4.19）：BioTransformer HGUT + biosystem 过滤 + 标注 QC。

    两条路径：
      1) 默认：真实调 REST；REST 不可达时明确报"调用失败（不是无代谢）"；
      2) --from-export FILE：读人工导出的 BioTransformer JSON，只跑 QC 协议
         （biosystem 过滤 + 反应标注一致性），不联网。source/manual_export 如实标记，
         不得冒充实时 REST 结果。这修复了"QC 函数无 CLI 入口"的 P1-1 同型缺陷，
         让 REST 不可达时 scientific protocol 仍可真实触发。
    """
    from . import gut_microbiome as GM
    from .manifest import write_manifest

    # 路径 2：人工导出 JSON —— 不联网，跑真实 QC 协议
    if getattr(a, "from_export", None):
        with io.open(a.from_export, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
        rows = GM.parse_response(raw, compound_id=None)
        # 只保留菌群来源（biosystem 过滤），如实报告被排除的
        n_before = len(rows)
        rows = GM.filter_biosystem(rows, want="gut")
        print(
            "[gut-micro] 人工导出：解析 %d 条转化，biosystem=gut 过滤后 %d 条"
            % (n_before, len(rows))
        )
        print(
            "[gut-micro] 来源标记 manual_export（非实时 REST）；provenance=%s"
            % a.from_export
        )
        write_manifest(a.outdir, inputs=[a.from_export], argv=sys.argv)
        _gut_micro_write_report(
            a.outdir,
            rows,
            source="biotransformer_manual_export",
            source_version="manual",
            provenance_url="manual_export:" + os.path.basename(a.from_export),
            qc={},
            controlled=False,
        )
        return

    # 路径 1：真实 REST
    write_manifest(a.outdir, inputs=[a.input], argv=sys.argv)
    comps = load_compounds_csv(a.input, fmt=getattr(a, "format", "auto"))
    if not comps:
        print("[gut-micro] 没有分子")
        return
    try:
        rows, qc = GM.run_gut(
            comps,
            option=a.option,
            steps=a.steps,
            control=not a.no_control,
            dump_dir=a.outdir if a.dump_raw else None,
            poll_timeout=getattr(a, "poll_timeout", None),
        )
    except Exception as e:  # noqa: BLE001  网络/限流：如实报，不当作"无代谢"
        print("[gut-micro] 调用失败（不是'无代谢'）：%s" % e)
        raise SystemExit(3)

    controlled = not a.no_control
    print(
        "[gut-micro] option=%s 阳性对照=%s → %s"
        % (
            qc["option"],
            qc["control"] if controlled else "未跑(--no-control)",
            (
                ("PASS" if qc.get("control_pass") else "DRIFT/FAIL")
                if controlled
                else "不适用"
            ),
        )
    )
    n_prod = qc["n_products"]
    print(
        "[gut-micro] 每分子唯一代谢物数：%s"
        % ", ".join(
            "%s=%s" % (k, "FAILED" if v is None else v) for k, v in n_prod.items()
        )
    )
    if qc.get("failed"):
        print(
            "[gut-micro] ⚠ %d/%d 个分子未取到结果（超时/网络，**不是'无代谢'**；"
            "本批 poll_timeout=%ss，可 --poll-timeout 放宽）："
            % (len(qc["failed"]), len(comps), qc.get("poll_timeout_s"))
        )
        for f in qc["failed"]:
            print("   %s [%s] %s" % (f["compound_id"], f["stage"], f["reason"]))
        print("[gut-micro] 这些分子在产物表里**缺席**，不得按 0 产物解读")
    if controlled and not qc.get("control_pass"):
        print(
            "[gut-micro] ⚠ 阳性对照未达期望值：本次结果只能作背景，"
            "不得用于跨批比较（batch_drift）"
        )

    _gut_micro_write_report(a.outdir, rows, qc=qc, controlled=controlled)


def cmd_readback(a):
    """通用回填（v4.20）：无 API 工具的人工导出表 -> 长表契约行。"""
    from . import readback as RB
    from .manifest import write_manifest

    write_manifest(
        a.outdir,
        inputs=[a.file] + ([a.compounds] if a.compounds else []),
        argv=sys.argv,
    )

    override = {}
    for item in a.map or []:
        if "=" not in item:
            raise SystemExit("--map 格式：'源列名=端点id[:单位]'，收到 %r" % item)
        left, right = item.split("=", 1)
        ep, _, unit = right.partition(":")
        override[left.strip()] = dict(id=ep.strip(), unit=unit.strip())

    if a.kind == "microbe":
        # 菌群数据库（MicrobeTCM/GutBugDB/MASI）：产物是"互作记录"，不是 measurement
        from . import gut_microbiome as GM

        recs, problems = GM.ingest_microbe_db(a.file, source=a.source)
        p = os.path.join(a.outdir, "microbe_interactions_%s.csv" % a.source)
        if recs:
            with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(recs[0]), extrasaction="ignore")
                w.writeheader()
                w.writerows(recs)
        print(
            "[readback] 菌群数据库 %s：%d 条互作记录 -> %s"
            % (a.source, len(recs), p if recs else "(空)")
        )
        print(
            "[readback] ⚠ 这些是**文献/数据库注解**（evidence_level="
            "database_annotation, predictive_value=none），**不进 reliab 计票**"
        )
        for x in problems[:10]:
            print("[readback]   问题：%s" % x)
        return

    comps = None
    if a.compounds and os.path.exists(a.compounds):
        comps = load_compounds_csv(a.compounds, fmt=getattr(a, "format", "auto"))
    try:
        rows, rep = RB.ingest(
            a.source,
            a.file,
            compounds=comps,
            domain_flag=a.domain_flag or None,
            provenance_url=a.provenance_url,
            col_map_override=override or None,
        )
    except Exception as e:  # noqa: BLE001
        print("[readback] 失败：%s" % e)
        raise SystemExit(2)

    p = os.path.join(a.outdir, "measurements_readback_%s.csv" % a.source)
    if rows:
        schema.write_measurements_checked(p, rows)
    print(
        "[readback] %s：输入 %d 行 → 长表 %d 行 / %d 个分子"
        % (a.source, rep["n_input"], rep["n_rows"], rep["n_compounds"])
    )
    print("[readback] 端点覆盖：%s" % (", ".join(rep["endpoints_covered"]) or "-"))
    if rep["n_unmatched"]:
        print(
            "[readback] ⚠ 结构对齐失败 %d 行（已丢弃，未硬配）：%s"
            % (rep["n_unmatched"], rep["unmatched"][:5])
        )
    if rep["unmapped_columns"]:
        print(
            "[readback] ⚠ 未映射列 %d 个（未静默丢弃，用 --map 指定）：%s"
            % (len(rep["unmapped_columns"]), rep["unmapped_columns"][:10])
        )
    if not rep["structure_checked"]:
        print(
            "[readback] ⚠ 未给 --compounds：跳过了结构对齐（铁律 1 未执行），"
            "结果只能作草稿"
        )
    if rep["problems"]:
        for x in rep["problems"][:10]:
            print("[readback]   问题：%s" % x)
    if rep["notice"]:
        print("[readback] 说明：%s" % rep["notice"].strip())
    if rows:
        print("[readback] 产物：%s" % p)


# ---- 2026-11-11：离线结构干扰红旗层（Gate 0.5 之后，不进 reliab 计票）----
def cmd_interference(a):
    """PAINS/BRENK/NIH 离线结构干扰红旗 + 类药性三态（不淘汰分子）。"""
    from . import interference as IF

    if a.selftest:
        rep = IF.selftest()
        print(
            "[interference] 自检 %d 例：%s（失败 %d）"
            % (
                rep["n_cases"],
                "PASS" if rep["passed"] else "FAIL",
                len(rep["failures"]),
            )
        )
        for d in rep["details"]:
            print(
                "   %-14s %-20s strong=%d weak=%d %s"
                % (
                    d["case"],
                    d["flag"],
                    d["n_strong"],
                    d["n_weak"],
                    "" if d["ok"] else "✗",
                )
            )
        for f in rep["failures"]:
            print(
                "   ✗ %s expect=%s got=%s hits=%s"
                % (f["case"], f["expect"], f["flag"], f["hits"])
            )
        if not rep["passed"]:
            raise SystemExit(1)
        return

    cats = tuple(a.catalogs) if a.catalogs else IF.CATALOG_NAMES
    if a.smiles:
        r = IF.assess(a.smiles, a.compound_id, include_catalogs=cats)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    if not a.input:
        raise SystemExit("[interference] 需要 --smiles 或 --in（或 --selftest）")

    rows, paths = IF.assess_file(a.input, outdir=a.outdir, include_catalogs=cats)
    print(
        "[interference] %d 个分子：none=%d / weak_only=%d / suspect=%d / invalid=%d"
        % (
            len(rows),
            sum(1 for r in rows if r["flag"] == IF.FLAG_NONE),
            sum(1 for r in rows if r["flag"] == IF.FLAG_WEAK_ONLY),
            sum(1 for r in rows if r["flag"] == IF.FLAG_SUSPECT),
            sum(1 for r in rows if r["flag"] == IF.FLAG_INVALID),
        )
    )
    for r in rows:
        print(
            "   %-16s %-20s %-20s strong=%d weak=%d"
            % (
                r["compound_id"] or "(unnamed)",
                r["flag"],
                r["gate_action"],
                r["n_strong"],
                r["n_weak"],
            )
        )
    print(
        "[interference] ⚠ 红旗层，不产生 verdict、不进 reliab 计票、不写长表；"
        "weak_only 不折减结论，suspect 须降级并做正交实验确认"
    )
    print("[interference] 产物：%s | %s" % (paths["csv"], paths["json"]))


# ---- 2026-11-11：数据源健康探针（可复跑，不自动改写注册表）----
def cmd_source_health(a):
    """GET 探测 + 时间戳报告；首页 200 不等于预测后端可用。"""
    from . import source_health as SH

    rep = SH.probe(
        names=a.sources or None,
        timeout=a.timeout,
        registry_path=a.registry or None,
        outdir=a.outdir,
    )
    print(
        "[source-health] %s  探测 %d 个源，前端 200 的 %d 个；"
        "预测后端确认可用 0 个（本探针不提交作业）"
        % (rep["generated_at"], rep["n_probed"], rep["n_frontend_ok"])
    )
    for e in rep["sources"]:
        print(
            "   %-16s registry=%-14s http=%-5s reachable=%-5s final=%s"
            % (
                e["name"],
                e["registry_status"],
                str(e.get("http_status")),
                str(e.get("frontend_reachable")),
                e.get("final_url", ""),
            )
        )
        if e.get("error"):
            print("       error: %s" % e["error"])
    print(
        "[source-health] ⚠ 不自动改写 02_source_registry.yaml；"
        "首页 200 是引诱（pkCSM 2026-11-04：前端全活、POST 8/8 500）"
    )
    print("[source-health] 产物：%s" % rep.get("_report_path"))


# ---- 2026-11-11：未覆盖端点声明闸门（C82 闭环，登记表 -> 产物）----
def cmd_coverage_gate(a):
    """读 not_covered_endpoints，渲染/校验强制声明；改注册表即改变产物。"""
    from . import coverage_gate as CG

    entries = CG.load_not_covered(a.rules or None)
    if a.selftest:
        rep = CG.selftest()
        print(
            "[coverage-gate] 自检 %d 例：%s（登记端点 %d 条）"
            % (rep["n_cases"], "PASS" if rep["passed"] else "FAIL", rep["n_entries"])
        )
        for c in rep["results"]:
            print(
                "   %-24s applicable=%-5s passed=%-5s %s"
                % (c["case"], c["applicable"], c["passed"], "" if c["ok"] else "✗")
            )
        if not rep["passed"]:
            raise SystemExit(1)
        return
    if a.emit:
        print(CG.declaration_text(entries))
        return
    if a.outdir:
        os.makedirs(a.outdir, exist_ok=True)
        p = os.path.join(a.outdir, "coverage_declaration.md")
        io.open(p, "w", encoding="utf-8").write(CG.declaration_text(entries) + "\n")
        print(
            "[coverage-gate] 声明段 %d 条 -> %s（无时间戳，逐字节确定）"
            % (len(entries), p)
        )
    if a.check:
        res = CG.audit_texts(a.check, a.rules or None)
        print(
            "[coverage-gate] 扫描 %d 份文本，适用 %d 份，违规 %d 条：%s"
            % (
                res["n_scanned"],
                res["n_applicable"],
                res["n_violations"],
                "PASS" if res["passed"] else "FAIL",
            )
        )
        for v in res["violations"][:20]:
            print("   ✗ %s:%d %s" % (v["file"], v["line"], v["why"]))
        if not res["passed"]:
            raise SystemExit(1)
        return
    if not a.outdir:
        print(CG.declaration_text(entries))


def _make_selftest_cmd(mod_name):
    """为纯自检模块生成 CLI handler（统一 selftest 协议）。"""

    def _h(a):
        import importlib

        m = importlib.import_module("adt." + mod_name)
        ok, rows = m.selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r.get("detail", "")[:60])
            )
        print("[%s] %s" % (mod_name, "PASS" if ok else "FAIL"))
        if not ok:
            raise SystemExit(4)

    _h.__name__ = "cmd_" + mod_name.replace("-", "_")
    return _h


def cmd_trust(a):
    """单分子可信决策 / 数据忠实性门 / 预注册判据报告（prior-art 移植，已修三缺陷）。"""
    from . import trust as T

    if a.selftest:
        ok, rows = T.selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:70])
            )
        print("[trust] %s" % ("PASS" if ok else "FAIL"))
        if not ok:
            raise SystemExit(4)
        return
    if a.numeric_coverage:
        vals = [float(x) for x in a.values.split(",") if x.strip()]
        r = T.numeric_coverage(vals, a.numeric_coverage)
    elif a.prereg_report:
        p = dict(
            id=a.prereg_id or "primary",
            threshold=float(a.threshold),
            direction=a.direction,
        )
        r = T.prereg_criterion_report(
            p,
            dict(value=float(a.observed)),
            dict(value=float(a.noise_floor)),
            post_hoc_adjusted=a.post_hoc_adjusted,
        )
    else:
        print(
            "trust：请给 --selftest / --numeric-coverage TEXT --values V[,V] / --prereg-report"
        )
        raise SystemExit(2)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if isinstance(r, dict) and r.get("verdict") == "ESCALATE":
        raise SystemExit(4)
    if isinstance(r, dict) and r.get("integrity") == "FAIL":
        raise SystemExit(4)


def cmd_claims_fragility(a):
    """主张脆弱性五分类普查（SciForge 移植，需人确认，不做自动判定）。"""
    from . import claims_audit as C

    registry = a.registry or "references/CLAIMS_REGISTRY.yaml"
    rp = (
        registry
        if os.path.isabs(registry)
        else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), registry
        )
    )
    if not os.path.isfile(rp):
        print("[fragility] 登记表不存在：%s" % registry)
        raise SystemExit(2)
    rows = C.fragility_census(registry)
    from collections import Counter

    cnt = Counter(r["category"] for r in rows)
    print("[fragility] 普查 %d 条：%s" % (len(rows), dict(cnt)))
    for r in rows:
        if r["category"] not in ("supported",):
            print("  %-38s %-17s %s" % (r["id"], r["category"], r["remediation"][:70]))
    if a.json_out:
        with io.open(a.json_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_knn_sensitivity(a):
    """kNN/Tanimoto 阈值一维网格敏感性（关闭 RISK_COVERAGE_PROTOCOL §3）。"""
    from . import knn_sensitivity as KS

    if a.selftest:
        ok, ns = KS.selftest()
        print(
            "[knn-sensitivity] selftest %s n_by_threshold=%s"
            % ("PASS" if ok else "FAIL", ns)
        )
        if not ok:
            raise SystemExit(4)
        return
    rep = KS.analyze()
    os.makedirs(a.outdir, exist_ok=True)
    p = os.path.join(a.outdir, "knn_threshold_sensitivity.json")
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
    n_crit = sum(
        1
        for ep, per in rep["by_endpoint"].items()
        for g in per.values()
        if g.get("verdict") == "threshold_critical"
    )
    print("[knn-sensitivity] -> %s" % p)
    print("[knn-sensitivity] 临界组合 %d/6：单阈值结论不得直接进对外材料" % n_crit)
    for ep, per in rep["by_endpoint"].items():
        for gn, g in per.items():
            if "verdict" in g:
                print(
                    "  %-12s %-14s max|dacc|=%-6s %s"
                    % (ep, gn, g.get("max_abs_acc_delta"), g["verdict"])
                )


def cmd_estimand(a):
    """Estimand 绑定门（G13）：跨量纲/未绑定主张的机器可判阻断。"""
    from . import estimand as ES

    if a.selftest:
        ok, rows = ES.selftest()
        for r in rows:
            print(
                "[%s] %s : %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:100])
            )
        print("[estimand] %s" % ("PASS" if ok else "FAIL"))
        if not ok:
            raise SystemExit(4)
        return
    if a.compare:
        r = ES.check_comparison(a.compare[0], a.compare[1])
    elif a.claim:
        r = ES.check_claim(a.endpoint or "", a.claim)
    elif a.text:
        r = ES.validate_text(a.text)
    elif a.artifact:
        r = ES.audit_artifact(a.artifact)
    else:
        print(
            "estimand：请给 --selftest / --compare A B / --claim / --text / --artifact"
        )
        raise SystemExit(2)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["verdict"] == "BLOCK":
        raise SystemExit(4)


# ---- 2026-11-11：把 local_admet 6 工具接入主 CLI（此前只有独立子包入口）----
def cmd_local_tools(a):
    """把 6 个离线工具接到主 CLI（显式重建 argv，不用 REMAINDER）。

    实测踩过：子命令里 `nargs=argparse.REMAINDER` 会把 `--list-tools` 等
    以 `--` 开头的参数交给**主解析器**，报 "unrecognized arguments"。
    改成显式注册参数 + 重建 argv 后，调用形态与普通子命令一致。
    """
    import importlib

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        LA = importlib.import_module("local_admet.cli")
    except Exception as exc:
        raise SystemExit("[local-tools] 无法加载 local_admet：%r" % (exc,))
    av = []
    if a.list_tools:
        av.append("--list-tools")
    if a.selftest:
        av.append("--selftest")
    if a.deterministic:
        av.append("--deterministic")
    for flag, val in (
        ("--tool", a.tool),
        ("--smiles", a.smiles),
        ("--smiles-file", a.smiles_file),
        ("--id", a.cid),
        ("--features", a.features),
        ("--dose-mg", a.dose_mg),
        ("--ph", a.ph),
        ("--format", a.format),
        ("--out", a.out),
    ):
        if val not in (None, ""):
            av += [flag, str(val)]
    rc = LA.main(av)
    print(
        "[local-tools] ⚠ rule-based-local-proxy，非 SciMiner 模型；"
        "source=local_admet 不进 reliab 计票、不得用于对外定论",
        file=sys.stderr,
    )
    # main() 忽略 func 的返回值，失败码必须显式传播，否则子命令会假绿。
    if rc:
        raise SystemExit(int(rc))
    return 0


class _RawVersion(argparse.Action):
    """原样打印多行版本横幅并退出。

    不能用 `action="version"`：argparse 的 _VersionAction 会走 formatter，
    把 banner 的换行 reflow 成一段（实测 3.13 上三轨挤成一行，正好毁掉
    版本可分读的目的）。这里直接 print，保持逐行。
    """

    def __init__(
        self,
        option_strings,
        dest=argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        help=None,
        const=None,
    ):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )
        self.const = const

    def __call__(self, parser, namespace, values, option_string=None):
        print(self.const)
        parser.exit(0)


def main(argv=None):
    from ._version import banner as _banner

    ap = argparse.ArgumentParser(prog="adt")
    # D3：三轨版本一次说清（对外号 / 能力等级 / 材料修订），并给出引用建议。
    ap.add_argument(
        "--version",
        action=_RawVersion,
        const=_banner(),
        help="打印对外发布号 / 能力等级 / 材料修订 三轨版本并退出",
    )
    ap.add_argument(
        "--profile",
        default=None,
        choices=[
            "academic-internal",
            "academic-shared",
            "pre-commercial",
            "commercial",
        ],
        help="使用场景档位（R38 红线 5）。pre-commercial/commercial 会强制归档"
        "调用日志到 ADT_CALL_LOG（缺省 skill 内 logs/compliance_calls.jsonl）",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("cstar")
    p.add_argument("--results", required=True,
                   help="keystone results JSON containing per_run records")
    p.add_argument("--endpoints", required=True,
                   help="comma-separated endpoint list to solve")
    p.add_argument("--out-md", required=True, help="Markdown report path")
    p.add_argument("--out-csv", required=True, help="CSV summary path")
    p.add_argument("--title", default="Critical abstention cost c*")
    p.add_argument("--interim", action="store_true",
                   help="label output as a transferability demonstration")
    p.add_argument("--baseline", default="S1_naive_majority",
                   choices=["S1_naive_majority", "S3_calibrated_conformal"],
                   help="comparator the admission layer is priced against; "
                        "S3 asks whether admission still pays once the comparator "
                        "already carries a coverage guarantee")
    p.set_defaults(func=cmd_cstar)

    p = sub.add_parser("normalize")
    p.add_argument("--in", dest="input", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--strict-input",
        action="store_true",
        help="输入闸门有拦截（缺 InChIKey / 立体未声明）即返回非零退出码",
    )
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("saturate")
    p.add_argument("--wide", required=True)
    p.add_argument(
        "--mark-measurements",
        default="",
        help="可选：把结论写回长表，产出 measurements_saturated.csv",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_saturate)

    p = sub.add_parser("bt")
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--option",
        dest="options",
        nargs="+",
        default=["CYP450"],
        choices=[
            "CYP450",
            "EC-BASED",
            "PHASEII",
            "HGUT",
            "ENVMICRO",
            "ALLHUMAN",
            "SUPERBIO",
            "ABIOTICBIO",
        ],
    )
    p.add_argument("--steps", type=int, default=1)
    p.add_argument("--chemical-class", default="cinnamoyl_glycoside")
    p.add_argument(
        "--format",
        choices=["auto", "csv", "tsv"],
        default="auto",
        help="输入格式（默认嗅探；首行含逗号的 TSV 请显式指定 tsv）",
    )
    p.add_argument(
        "--engine",
        choices=["auto", "biotransformer", "sygma"],
        default="auto",
        help="代谢引擎：auto=先试 BioTransformer（不可达则降级 SyGMa 本地引擎）；"
        "biotransformer=只用网页服务（不可达即 rc=3）；"
        "sygma=只用本地 SyGMa（Ridder & Wagener 2008，偏 CYP/II 相专家规则）",
    )
    p.add_argument(
        "--top",
        type=int,
        default=25,
        help="SyGMa 每分子保留的产物上限（按经验分数排序；截断数会写进 meta）",
    )
    p.add_argument(
        "--cycles",
        type=int,
        default=1,
        help="SyGMa I 相规则迭代次数（≥2 会组合爆炸：伊马替尼 1 cycle 已 >2000 节点）",
    )
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        dest="skip_preflight",
        help="跳过源可达性预检（仅在你确认源可达时使用）",
    )
    p.set_defaults(func=cmd_bt)

    p = sub.add_parser("xeno-prep")
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--outdir", required=True)
    p.add_argument("--models", nargs="*", default=None)
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.set_defaults(func=cmd_xeno_prepare)

    p = sub.add_parser("xeno-ingest")
    p.add_argument("--file", required=True)
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_xeno_ingest)

    p = sub.add_parser("chembl")
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--threshold", type=int, default=40, help="ChEMBL 允许 40-100，官方推荐 40-70"
    )
    p.add_argument("--chemical-class", default="cinnamoyl_glycoside")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument(
        "--max-neighbors",
        type=int,
        default=40,
        dest="max_neighbors",
        help="相似邻居上限（默认 40；每邻居都要取活性，30 分子规模下是主要耗时项）",
    )
    p.set_defaults(func=cmd_chembl)

    p = sub.add_parser("validate")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("advisory-check")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.set_defaults(func=cmd_advisory_check)

    p = sub.add_parser("web")
    p.add_argument(
        "--source", required=True, choices=["admet_ai", "protox3", "admetlab3", "vnn"]
    )
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--outdir", required=True)
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--chemical-class", default="cinnamoyl_glycoside")
    p.add_argument(
        "--local",
        action="store_true",
        help="admet_ai 本地离线推理（需 admet-ai 包；与网页服务权重不同版本，勿混用）",
    )
    p.add_argument(
        "--local-python",
        default="",
        dest="local_python",
        help="本地推理所用 Python 解释器路径（默认当前解释器）",
    )
    p.add_argument(
        "--prepare-only", action="store_true", help="只生成人工桥任务单（vnn）"
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("reliab")
    p.add_argument("--in", dest="input", required=True, help="measurements.csv")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--saturation", default="")
    p.add_argument(
        "--registry",
        default="references/02_source_registry.yaml",
        help="源独立性分组 + 本化学类域外端点都来自此文件",
    )
    p.add_argument(
        "--chemical-class",
        default="",
        help="用于查 blocked_endpoints_in_class；默认空=不过滤（混合面板安全）。"
        "单一糖苷批次请显式传 cinnamoyl_glycoside",
    )
    p.add_argument(
        "--no-class-blocks",
        action="store_true",
        help="关闭域外端点过滤（仅用于对照实验）",
    )
    p.add_argument(
        "--allow-invalid",
        action="store_true",
        help="跳过长表契约校验（跳过后产物不得用于报告）",
    )
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--i-accept-low-validity",
        action="store_true",
        dest="i_accept_low_validity",
        help="R21/R37：允许使用'不推荐计算'的端点（DILI/Ames 等），"
        "被拦记录写 endpoint_tier_blocks.csv 留痕",
    )
    p.add_argument(
        "--compounds",
        default="",
        help="compounds.csv（含 compound_id,calc_smiles）；reliab 用它对 "
        "QUALITATIVE_NEEDS_EXPERT 端点（ames）跑结构警示扫描以做 ICH M7 双方法合成",
    )
    p.add_argument(
        "--enable-alerts",
        dest="enable_alerts",
        action="store_true",
        default=True,
        help="（默认）对 ames 等需专家规则层的端点调用 adt/alerts.py 做 ICH M7 双方法合成",
    )
    p.add_argument(
        "--no-alerts",
        dest="enable_alerts",
        action="store_false",
        help="关闭结构警示层（ames 等将保持 UNDETERMINED，仅用于对照实验）",
    )
    p.set_defaults(func=cmd_reliab)

    p = sub.add_parser("sensitize")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--saturation", default="")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument(
        "--factors",
        nargs="+",
        type=float,
        default=[0.2, 0.5],
        help="阈值摄动比例（0.2 = ±20%%）",
    )
    p.add_argument(
        "--ad",
        action="store_true",
        help="额外做适用域旋钮摄动（Sahigara 2012）：票数门控 × 域外处置",
    )
    p.add_argument(
        "--require-grid",
        nargs="+",
        type=int,
        default=[1, 2, 3],
        help="AD 票数门控网格（默认 1/2/3 个独立方法组）",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_sensitize)

    p = sub.add_parser("coverage")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument(
        "--min-coverage",
        type=float,
        default=0.30,
        help="整源平均覆盖率低于此值判 background_only（G6）",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("background")
    p.add_argument(
        "--in", dest="input", required=True, help="目标分子 measurements 长表"
    )
    p.add_argument(
        "--bg", default="", help="背景分子 measurements 长表（可选；缺省=within-set）"
    )
    p.add_argument(
        "--within-set",
        action="store_true",
        help="以本批分子自身为背景（留一法，回答本批内谁离群）",
    )
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument(
        "--floor", type=float, default=0.30, help="尺度下限（≈重复性量级，项目校准值）"
    )
    p.add_argument("--min-bg", type=int, default=5, help="背景 n 低于此值不计算 Z")
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_background)

    p = sub.add_parser("rank")
    p.add_argument(
        "--in",
        dest="input",
        required=True,
        help="axis_scores.csv 或任意 (id,组,分数) 长表",
    )
    p.add_argument("--id-col", default="compound_id")
    p.add_argument("--group-col", default="axis")
    p.add_argument("--score-col", default="geo_mean")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--thr-low", type=float, default=0.40)
    p.add_argument("--thr-high", type=float, default=0.60)
    p.add_argument(
        "--max-cluster-frac",
        type=float,
        default=1.0,
        help="实测最大同类簇占比；默认 1.0=保守拒绝排名",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="underpowered 时仍计算（产物标 OVERRIDE，仅演示）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("benchmark")
    p.add_argument("--predictions", default="", help="预测长表（多源）")
    p.add_argument("--truth", default="", help="truth.csv（实测真值）")
    p.add_argument(
        "--clusters",
        default="",
        help="可选 cluster 表（compound_id,cluster），用于聚类 bootstrap",
    )
    p.add_argument(
        "--scaffold-from",
        default="",
        help="从含 SMILES 的化合物表算 Bemis-Murcko 骨架簇（TDC 标准切分）；"
        "给了它就不用 --clusters",
    )
    p.add_argument(
        "--split",
        action="store_true",
        help="配合 --scaffold-from：再产出 scaffold_split.csv（整簇 train/val/test）",
    )
    p.add_argument(
        "--truth-format",
        default="native",
        choices=["native", "tdc"],
        help="truth 文件格式：native（本 skill 契约）或 tdc（Drug_ID/Y）",
    )
    p.add_argument(
        "--tdc-endpoint",
        default="",
        help="--truth-format tdc 时的端点名（如 DILI / hERG）",
    )
    p.add_argument("--tdc-id-col", default="", help="TDC id 列名（默认自动识别）")
    p.add_argument("--tdc-y-col", default="", help="TDC 标签列名（默认自动识别）")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument(
        "--demo",
        action="store_true",
        help="合成真值演示（仅验证指标与消融代码，非科学结论）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("tier", aliases=["gate"])
    p.add_argument("--reliability", required=True)
    p.add_argument(
        "--benchmark", default="", help="benchmark.csv（可选；真值基准才算数）"
    )
    p.add_argument(
        "--coverage", default="", help="coverage_matrix.csv（可选；覆盖声明）"
    )
    p.add_argument(
        "--request",
        default="",
        choices=["", "T1", "T2", "T3"],
        help="请求档位，校验是否越级",
    )
    p.add_argument(
        "--compounds",
        default="",
        help="化合物表（含 SMILES）：用于算骨架簇数，进 PROBAST D1 判定",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_tier)

    p = sub.add_parser("qaf")
    p.add_argument("--reliability", required=True)
    p.add_argument("--coverage", default="", help="coverage_matrix.csv")
    p.add_argument("--benchmark", default="", help="benchmark.csv（含校准列）")
    p.add_argument("--measurements", default="", help="measurements 长表（查源版本号）")
    p.add_argument("--compounds", default="", help="化合物表（含 SMILES，算骨架簇数）")
    p.add_argument("--tier", default="", help="tier.csv（缺省读 outdir/tier.csv）")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_qaf)

    p = sub.add_parser("conformal")
    p.add_argument("--predictions", required=True, help="measurements 长表（多源）")
    p.add_argument("--truth", required=True, help="实测真值（truth.csv 契约）")
    p.add_argument("--endpoint", default="", help="单个端点；缺省=全部端点")
    p.add_argument(
        "--alpha", type=float, default=0.2, help="误覆盖水平（0.2 → 目标 80%% 覆盖）"
    )
    p.add_argument(
        "--min-n",
        type=int,
        default=20,
        help="校准集最少实测条数（不足则标 insufficient）",
    )
    p.add_argument(
        "--mode",
        choices=["absolute", "normalized"],
        default="absolute",
        help="absolute=固定宽度；normalized=宽度随 sigma 变化（需 --scale-file）",
    )
    p.add_argument(
        "--scale-file",
        default="",
        dest="scale_file",
        help="normalized 模式的 {compound_id,sigma} CSV（见 conformal-scale）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_conformal)

    p = sub.add_parser("reporting")
    p.add_argument("--reliability", default="")
    p.add_argument("--coverage", default="")
    p.add_argument("--benchmark", default="")
    p.add_argument("--measurements", default="")
    p.add_argument("--compounds", default="")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--version", default="", help="工具版本号（写进 TRIPOD 1a）")
    p.add_argument(
        "--external", action="store_true", help="声明已有独立化学类/独立实验室验证"
    )
    p.add_argument("--subgroup", action="store_true", help="声明已按化学型分层报告")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_reporting)

    p = sub.add_parser("merge")
    p.add_argument(
        "--inputs", nargs="+", required=True, help="多个 measurements 长表（同 schema）"
    )
    p.add_argument(
        "--keep-dup",
        action="store_true",
        help="保留重复行（默认按 (cid,ep,source,version,unit) 去重取首条；"
        "C1-b：unit 入键，异量纲不再被静默丢弃）",
    )
    p.add_argument(
        "--allow-invalid",
        action="store_true",
        help="跳过长表契约校验（跳过后产物不得用于报告）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("desire")
    p.add_argument(
        "--in", dest="input", required=True, help="reliability.csv 或 measurements 长表"
    )
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--outdir", required=True)
    p.add_argument(
        "--enforce-rank-guard",
        action="store_true",
        help="满足四条件才允许讨论排名（默认只输出 Pareto）",
    )
    p.add_argument(
        "--max-cluster-frac",
        type=float,
        default=1.0,
        help="实测最大同类簇占比（无数据时保持 1.0 = 保守拒绝）",
    )
    p.set_defaults(func=cmd_desire)

    p = sub.add_parser("ledger")
    p.add_argument("--reliability", required=True)
    p.add_argument("--axis", default="", help="可选：axis_scores.csv，把轴级结论也入账")
    p.add_argument("--measurements", required=True, help="measurements 长表")
    p.add_argument(
        "--allow-invalid",
        action="store_true",
        help="跳过长表契约校验（跳过后产物不得用于报告）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_ledger)

    p = sub.add_parser("transport")
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--priors", default="references/transporter_priors.yaml")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_transport)

    p = sub.add_parser("pbpk")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--compounds", required=True, help="compounds.csv（含 SMILES）")
    p.add_argument(
        "--exposure", default="", help="E13 exposure_screening.csv（取逐分子 Fa）"
    )
    p.add_argument("--dose-mg", type=float, default=100.0)
    p.add_argument("--fa-default", type=float, default=0.26)
    p.add_argument(
        "--ic50-list",
        default="1,10,30",
        help="用于反推安全裕度的 hERG IC50 假定值（µM，逗号分隔）",
    )
    p.add_argument(
        "--mc", type=int, default=0, help="MC 次数（0=跳过；≥100 做收敛校验）"
    )
    p.add_argument(
        "--fbile",
        type=float,
        default=0.0,
        help="肝消除进入胆汁的分数（0=无肠肝循环，默认）",
    )
    p.add_argument("--fre", type=float, default=0.0, help="胆汁中药物被重吸收的分数")
    p.add_argument("--kbile", type=float, default=0.4, help="胆汁排入肠腔速率（1/h）")
    p.add_argument(
        "--ehr-scan",
        action="store_true",
        help="跑 fbile×fre 网格，量化肠肝循环对 AUC/t½ 的放大边界",
    )
    p.add_argument(
        "--dump-curves",
        action="store_true",
        dest="dump_curves",
        help="落 C(t) 曲线 pbpk_curves.csv（供 adt.cli pd 做 PK/PD 连接）",
    )
    p.add_argument(
        "--dump-cmax",
        action="store_true",
        dest="dump_cmax",
        help="落 cmax_uM.csv（compound_id,cmax_uM,...），供 adt.cli cardiac --exposure",
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_pbpk)

    p = sub.add_parser("report")
    p.add_argument("--reliability", required=True)
    p.add_argument(
        "--axis",
        default="",
        help="留空 = 用 outdir 内的 axis_scores.csv（防跨目录污染）",
    )
    p.add_argument(
        "--outdir", required=True, help="同时作为 run_manifest.yaml 的查找目录"
    )
    # 红线 3/1（C1 修复）：发布模式才强制快照重放 + 输入准入；探索模式只留痕
    p.add_argument(
        "--publish",
        action="store_true",
        help="发布模式：强制 ADT_REPLAY=1 且输入全部通过结构准入，否则 exit 4",
    )
    # 红线 7（C1 修复）：报告涉及 gate 判别力主张时必须能给评测分布
    p.add_argument(
        "--eval-distribution",
        default="",
        dest="eval_distribution",
        choices=["", "in_domain", "out_of_domain", "mixed", "unknown"],
        help="报告所引 gate 数字的评测分布（红线 7）",
    )
    p.add_argument(
        "--gate-auc",
        type=float,
        default=None,
        dest="gate_auc",
        help="gate-as-classifier AUC（红线 7 的 CI 判据用）",
    )
    p.add_argument(
        "--rules",
        default="",
        help="端点规则表（缺省用随包 03_endpoint_rules.yaml；供回归测试注入）",
    )
    p.set_defaults(func=cmd_report)

    # ---- v3.1.0 学术化升级：工作包 A/C/D/E/H/I/J ----
    p = sub.add_parser("independence")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument(
        "--truth", default="", help="可选 truth.csv：给了才做 vote 校准（k 票 -> u(k)）"
    )
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_independence)

    p = sub.add_parser("certainty")
    p.add_argument("--reliability", required=True)
    p.add_argument("--measurements", default="")
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_certainty)

    p = sub.add_parser("selective")
    p.add_argument(
        "--reliability", default="", help="reliability.csv（holdout 模式可不给）"
    )
    p.add_argument("--truth", default="", help="truth.csv（有实测才算真 risk）")
    p.add_argument("--measurements", default="", help="无 truth 时用多数票做 proxy")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument(
        "--proxy",
        choices=["none", "majority", "holdout"],
        default="none",
        help="无 truth 时：majority=多源多数票（循环，仅示意）；"
        "holdout=留一源（非循环，需 --holdout-source）",
    )
    p.add_argument("--holdout-source", default="", dest="holdout_source")
    p.add_argument(
        "--conformal",
        default="",
        help="可选 conformal.csv（含 width 列）：作为第三条分数型弃权基线",
    )
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_selective)

    p = sub.add_parser("failure-modes", aliases=["failmodes"])
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--reliability", default="")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument(
        "--chemical-class",
        default="",
        help="用于查 blocked_endpoints_in_class（C82 检测）",
    )
    p.add_argument(
        "--labels",
        default="",
        help="可选标签表（mode,compound_id,endpoint,is_failure）",
    )
    p.add_argument(
        "--expect-sources",
        nargs="*",
        default=None,
        help="预期出现的源；缺失即报 silent_empty_source",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_failure_modes)

    p = sub.add_parser("perturb")
    p.add_argument("--compounds", required=True, help="compounds.csv（含 SMILES）")
    p.add_argument(
        "--predictions",
        default="",
        help="可选长表（compound_id,variant,endpoint,source,value,unit）",
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument(
        "--use-calc",
        action="store_true",
        dest="use_calc",
        help="用 calc_smiles（已标准化）而非 input_smiles；默认用原始输入",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_perturb)

    p = sub.add_parser("decision-value", aliases=["dvalue"])
    p.add_argument("--reliability", required=True)
    p.add_argument("--truth", default="")
    p.add_argument("--measurements", default="", help="无 truth 时用多数票做 proxy")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--proxy", choices=["none", "majority"], default="none")
    p.add_argument("--budget", type=int, default=10, help="实验预算（分子数）")
    p.add_argument(
        "--cost-fp",
        type=float,
        default=3.0,
        help="一个假阳性的代价（以实验成本为单位）",
    )
    p.add_argument(
        "--p-convert",
        type=float,
        default=0.5,
        help="UNDETERMINED-可解决 补信息后被救回的期望比例",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_decision_value)

    p = sub.add_parser("dst")
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--rule", choices=["dempster", "yager"], default="dempster")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument(
        "--chemical-class",
        default="",
        help="给了才把 registry 的 blocked 端点从准入里排除（对照才有意义）",
    )
    p.add_argument(
        "--reliability",
        default="",
        help="可选 reliability.csv：统计'DST 判死但框架弃权'的过度裁决",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_dst)

    p = sub.add_parser("external")
    p.add_argument("--dataset", required=True, choices=["openadmet", "npass"])
    p.add_argument("--data-dir", required=True, dest="data_dir")
    p.add_argument(
        "--split",
        default="test",
        choices=["train", "test", "raw"],
        help="OpenADMET 的 split（train/test/raw）；NPASS 忽略",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_external)

    p = sub.add_parser("baseline")
    p.add_argument("--train-meas", required=True, dest="train_meas")
    p.add_argument("--test-meas", required=True, dest="test_meas")
    p.add_argument("--train-compounds", required=True, dest="train_compounds")
    p.add_argument("--test-compounds", required=True, dest="test_compounds")
    p.add_argument("--method", choices=["rdkit", "morgan", "both"], default="rdkit")
    p.add_argument(
        "--rules", default="", help="端点规则（决定风险方向；OpenADMET/NPASS 各有一份）"
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("conformal-check", aliases=["ccheck"])
    p.add_argument(
        "--conformal", required=True, help="conformal_intervals.csv（含 width/flag）"
    )
    p.add_argument("--reliability", required=True, help="reliability.csv（含 verdict）")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_conformal_check)

    p = sub.add_parser("landscape")
    p.add_argument("--config", default="references/reliability_landscape.yaml")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_landscape)

    p = sub.add_parser("conformal-scale", aliases=["cscale"])
    p.add_argument("--train-compounds", required=True, dest="train_compounds")
    p.add_argument("--target-compounds", required=True, dest="target_compounds")
    p.add_argument("--k", type=int, default=5, help="第 k 近邻距离作为难度（默认 5）")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_conformal_scale)

    # ---- 深水区 2.1 SAR 预筛轴 ----
    p = sub.add_parser("sar", aliases=["sar-screen"])
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_sar)

    # ---- 深水区 2.3 酰基葡萄糖醛酸化结构警示 ----
    p = sub.add_parser("acyl-glucuronide", aliases=["acylglu"])
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_acyl_glucuronide)

    # ---- 深水区 2.3 增量：糖苷水解-苷元暴露轴 ----
    p = sub.add_parser("glycoside-hyd", aliases=["glycosh"])
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_glycoside_hydrolysis)

    # ---- 方向1：类条件（Mondrian）保形 ----
    p = sub.add_parser("conformal-class", aliases=["ccclass"])
    p.add_argument("--predictions", required=True, help="measurements 长表（多源）")
    p.add_argument(
        "--truth", default="", help="实测真值（truth.csv 契约，class_0_1 类端点）"
    )
    p.add_argument("--endpoint", required=True, help="二分类端点名（如 vnn_bbb）")
    p.add_argument(
        "--alpha", type=float, default=0.1, help="误覆盖水平（0.1 → 目标 90%% 覆盖）"
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_conformal_class)

    # ---- 方向4：跨化学类裁决行为一致性 ----
    p = sub.add_parser("cross-class", aliases=["xclass"])
    p.add_argument(
        "--reliability",
        required=True,
        nargs="+",
        help="多个 reliability.csv（每个一个化学空间）",
    )
    p.add_argument("--labels", default="", help="逗号分隔的对应标签（缺省用文件名）")
    p.add_argument(
        "--prediction-note",
        dest="prediction_note",
        default="",
        help="关于单调变化预测的文字说明（进产物）",
    )
    p.add_argument(
        "--expected-high",
        dest="expected_high",
        default="",
        help="预期弃权率最高（可裁决性最低）的化学空间标签；给出后预测检验按预期方向判定",
    )
    p.add_argument(
        "--expected-low",
        dest="expected_low",
        default="",
        help="预期弃权率最低（可裁决性最高）的化学空间标签；给出后预测检验按预期方向判定",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_cross_class)

    # ---- 方向A：准入层消融（工作包 D 缺口）----
    p = sub.add_parser("ablate", aliases=["ablation"])
    p.add_argument(
        "--sources",
        required=True,
        help="多源长表：'path=label[:group],...'（group=独立方法组）",
    )
    p.add_argument("--truth", required=True, help="truth.csv（含 truth_class）")
    p.add_argument(
        "--rules",
        default="references/03_endpoint_rules.yaml",
        help="端点规则（把真实量纲投影成 PASS/FAIL；勿用 *_risk.csv）",
    )
    p.add_argument("--conformal", default="", help="可选 conformal.csv（含 width）")
    p.add_argument(
        "--corrupt",
        default="none",
        choices=["none", "domain", "unit", "version", "pseudo"],
        help="受控注入一种已知失效，用于隔离准入规则的作用",
    )
    p.add_argument("--corrupt-frac", type=float, default=0.30, dest="corrupt_frac")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_ablate)

    # ---- 模块N：UNDETERMINED 结构化弃权归因 ----
    p = sub.add_parser("abstain-why", aliases=["awhy"])
    p.add_argument("--reliability", required=True)
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_abstain_why)

    # ---- 模块M：结构性 vs 模型依赖弃权对比 ----
    p = sub.add_parser("abstain-cmp", aliases=["acmp"])
    p.add_argument("--reliability", required=True)
    p.add_argument("--truth", default="")
    p.add_argument("--measurements", default="")
    p.add_argument("--conformal", default="", help="可选 conformal.csv（含 width）")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--proxy", choices=["none", "majority"], default="none")
    p.add_argument(
        "--min-pairs",
        type=int,
        default=10,
        dest="min_pairs",
        help="端点已裁决配对数低于此值标 insufficient",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_abstain_cmp)

    # ---- 模块O：失效模式三层检测 ----
    p = sub.add_parser("fail-layers", aliases=["flayers"])
    p.add_argument("--in", dest="input", required=True, help="measurements 长表")
    p.add_argument("--reliability", default="")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--chemical-class", default="", dest="chemical_class")
    p.add_argument("--expect-sources", nargs="*", default=None, dest="expect_sources")
    p.add_argument(
        "--curated",
        action="store_true",
        help="标记输入为 curated 数据：触发 0 时输出特异性未被挑战的告警",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_fail_layers)

    # ---- 模块L：跨数据集可迁移性 ----
    p = sub.add_parser("transfer")
    p.add_argument(
        "--datasets",
        required=True,
        help="'path1=name1,path2=name2'（每个一组测量长表）",
    )
    p.add_argument(
        "--expected-order",
        default="",
        dest="expected_order",
        help="'better,worse'：声明哪个数据集 curation 更好，按方向判定",
    )
    p.add_argument(
        "--proxy",
        action="store_true",
        help="标记为代理运行（同一来源的 curation 子集），不等于外部效度",
    )
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument(
        "--truth",
        default="",
        help="可选实测真值表（需 compound_id,endpoint,truth_class 列）；"
        "给了才计算 transfer.decided_accuracy（C-2026-11-03 接线）",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_transfer)

    # ---- 方向B：Regaloside A vs B case study ----
    p = sub.add_parser("regaloside-ab", aliases=["regab"])
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_regaloside_ab)

    # ---- 工作包 G：时间留出裁决（temporal holdout，非前瞻）----
    p = sub.add_parser("prospect", aliases=["prospective"])
    p.add_argument("--measurements", required=True, help="晚期分子上的多源预测长表")
    p.add_argument("--truth", required=True, help="晚期分子实测真值（truth.csv）")
    p.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    p.add_argument("--registry", default="references/02_source_registry.yaml")
    p.add_argument("--chemical-class", default="", dest="chemical_class")
    p.add_argument(
        "--baseline",
        choices=["none", "majority", "unit_guard", "both"],
        default="both",
        help="对照策略：none=只报准入层；majority=无准入多数投票（忽略单位，"
        "故意朴素）；unit_guard=只做单位守卫；both=两者都给",
    )
    p.add_argument("--early", default="", help="早期证据来源描述（进产物）")
    p.add_argument(
        "--split-note", default="", dest="split_note", help="时序切分说明（进产物）"
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_prospect)

    # ---- 工作包 A：真实源间相关性 ρ ----
    p = sub.add_parser("source-rho", aliases=["srho"])
    p.add_argument(
        "--source-a",
        required=True,
        dest="source_a",
        help="源 A 宽表（如 admetlab3_raw.csv）",
    )
    p.add_argument(
        "--source-b",
        required=True,
        dest="source_b",
        help="源 B 宽表（如 admet_ai_raw.csv）",
    )
    p.add_argument(
        "--endpoints",
        default="",
        help="逗号分隔的端点白名单（缺省=所有共享列，自动剔除 Lipinski/QED）",
    )
    p.add_argument("--label-a", default="source_A", dest="label_a")
    p.add_argument("--label-b", default="source_B", dest="label_b")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_source_rho)

    # ---- F1 源注册门（CI 化）：真实执行入口 ----
    p = sub.add_parser("source-admit", aliases=["sadmit"])
    p.add_argument(
        "--results",
        required=True,
        help="候选源验证结果 CSV，必需列 source,n,observed_failures",
    )
    p.add_argument(
        "--tol",
        type=float,
        default=0.05,
        help="失败率容差（默认 0.05 = 5%%）；判据为 CP95 CI 上界 ≤ tol",
    )
    p.add_argument(
        "--alpha", type=float, default=0.05, help="I 类水平（默认 0.05 → 95%% CI）"
    )
    p.add_argument(
        "--design-p",
        type=float,
        default=None,
        dest="design_p",
        help="可选：给定真实失败率，输出各 n 下注册门通过概率（设计端曲线）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_source_admit)

    # ---- 工作包 A/C：结构变体提交清单 ----
    p = sub.add_parser("ac-plan", aliases=["acplan"])
    p.add_argument("--compounds", required=True, help="compounds.csv（含 calc_smiles）")
    p.add_argument(
        "--kinds",
        default="original,stereo_removed,tautomer",
        help="要生成的变体类型（逗号分隔）",
    )
    p.add_argument("--batch-size", type=int, default=5, dest="batch_size")
    p.add_argument(
        "--controls", action="store_true", help="附加 4 个控制分子（先跑一批确认链路）"
    )
    p.add_argument(
        "--keep-noop",
        action="store_true",
        dest="keep_noop",
        help="保留 no-op 变体（默认跳过以省配额）",
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_ac_plan)

    # ---- 工作包 C：预测值位移 ----
    p = sub.add_parser("pred-shift", aliases=["pshift"])
    p.add_argument(
        "--variants",
        required=True,
        help="变体预测长表：compound_id,variant,endpoint,value",
    )
    p.add_argument(
        "--source-shift",
        default="",
        dest="source_shift",
        help="source-rho 的 source_rho_by_endpoint.csv（提供源间位移参照）",
    )
    p.add_argument(
        "--flip-threshold",
        type=float,
        default=0.5,
        dest="flip_threshold",
        help="PASS/FAIL 阈值（默认 0.5；logP/logS/logD 自动跳过）",
    )
    p.add_argument("--note", default="")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_pred_shift)

    # ---- R21：端点三级清单 ----
    p = sub.add_parser("endpoint-tiers")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_endpoint_tiers)

    # ---- R05：相关检验功效报告 ----
    p = sub.add_parser("indep-power")
    p.add_argument("--n", default="14,30,60,100,200", help="配对数，逗号分隔")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_indep_power)

    # ---- R07/B1：独立性贝叶斯收缩 ----
    p = sub.add_parser("indep-bayes")
    p.add_argument("--k", type=int, default=3, help="源数")
    p.add_argument("--rho", type=float, default=0.5, help="等相关 ρ（等距矩阵时使用）")
    p.add_argument(
        "--rho-matrix", default="", dest="rho_matrix", help="可选：k×k 相关矩阵 CSV"
    )
    p.add_argument("--n", type=int, default=100, help="计算 ρ 的配对数")
    p.add_argument("--votes", default="", help="各源投票 +1/-1/0，逗号分隔")
    p.add_argument("--draws", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_indep_bayes)

    # ---- R01/B5：数据快照层 ----
    p = sub.add_parser("snapshot-summary")
    p.add_argument("--root", default="snapshots")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_snapshot_summary)

    # ---- P2.1：预注册锚定状态（G9 的人手复核入口）----
    p = sub.add_parser("prereg-init")
    p.add_argument("--name", required=True, help="判据名（如 primary_endpoint_rule）")
    p.add_argument(
        "--criteria",
        required=True,
        help='判据 JSON 对象，如 \'{"endpoint":"hERG","rule":"..."}\'',
    )
    p.add_argument("--note", default="")
    p.add_argument("--log", default="prereg/prereg.jsonl")
    p.add_argument("--registry", default="", help="第三方注册机构（如 OSF）")
    p.add_argument("--doi", default="", help="第三方存证 DOI/URL")
    p.add_argument("--deposited-at", default="", help="第三方存证时间戳 ISO8601")
    p.set_defaults(func=cmd_prereg_init)

    p = sub.add_parser("prereg-status")
    p.add_argument(
        "--log",
        default="prereg/prereg.jsonl",
        help="预注册哈希链 jsonl（Prereg 的事件日志）",
    )
    p.add_argument(
        "--data-timestamps",
        default=None,
        help="可选：前瞻数据时间戳文件（每行一个 ISO8601，或 JSON 数组）。"
        "给出时额外校验『锚定先于数据』（P2.2）：违反则 exit 4",
    )
    p.set_defaults(func=cmd_prereg_status)

    p = sub.add_parser("snapshot-verify")
    p.add_argument("--root", default="snapshots")
    p.add_argument("--id", default="")
    p.set_defaults(func=cmd_snapshot_verify)

    p = sub.add_parser("env-fp")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_env_fp)

    # v4.22：换机后可机器判的环境自检（纯标准库，环境坏掉时也能跑）
    p = sub.add_parser("env-audit")
    p.add_argument(
        "--json-out",
        default="",
        dest="json_out",
        help="把完整报告写成 JSON（建议随复现材料一起归档）",
    )
    p.add_argument(
        "--network",
        action="store_true",
        help="额外探测注册源首页可达性（首页 200 不等于预测可用）",
    )
    p.add_argument(
        "--deep",
        action="store_true",
        help="重验证：ORCA H2O 单点实跑 + OneADMET 1.2 GB SHA256/行数",
    )
    p.add_argument("--quiet", action="store_true", help="只打印摘要与异常项")
    p.add_argument(
        "--required-only",
        action="store_true",
        dest="required_only",
        help="退出码只反映必需层：必需层全绿即 rc=0（可选/外部告警不阻断）",
    )
    p.set_defaults(func=cmd_env_audit)

    # ---- R02/R3-4：发布门禁 ----
    p = sub.add_parser("release-check")
    p.add_argument("--root", default=".")
    p.add_argument("--json-out", default="", dest="json_out")
    p.set_defaults(func=cmd_release_check)

    # ================= v4.14–v4.20 扩展（截图工具收编 + PK/PD） =================

    # v4.14：电离状态 / pKa 层（Gate 0.5 的补证）
    p = sub.add_parser("pka")
    p.add_argument("--in", dest="input", required=True, help="compounds.csv")
    p.add_argument("--ph", type=float, default=7.4)
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_pka)

    # v4.15：心脏离子通道三联（hERG + Cav1.2 + Nav1.5）
    p = sub.add_parser("cardiac")
    p.add_argument(
        "--in", dest="input", required=True, help="measurements 长表（cardiac_* 端点）"
    )
    p.add_argument(
        "--exposure",
        default="",
        help="含 compound_id,cmax_uM 的表（可用 pbpk 的 cmax_nM/1000）",
    )
    p.add_argument("--allow-invalid", action="store_true")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_cardiac)

    # v4.16：PK/PD 连接（Hill / 效应室 / fT>EC50 / TMDD）
    p = sub.add_parser("pd")
    p.add_argument(
        "--curves",
        required=True,
        help="C(t) 表：compound_id,t_h,c_mg_per_L（pbpk --dump-curves 产出）",
    )
    p.add_argument("--compounds", default="", help="compounds.csv（算 mw 用）")
    p.add_argument("--mw", type=float, default=0.0, help="统一 mw（无 compounds 时）")
    p.add_argument("--ec50", type=float, required=True, help="EC50/IC50（µM）")
    p.add_argument("--emax", type=float, default=100.0)
    p.add_argument("--hill-n", type=float, default=1.0, dest="hill_n")
    p.add_argument("--e0", type=float, default=0.0)
    p.add_argument(
        "--ke0", type=float, default=0.0, help="效应室速率（1/h，0=直接效应）"
    )
    p.add_argument(
        "--dosing-interval",
        type=float,
        default=0.0,
        dest="dosing_interval",
        help="给药间隔（h），用于折算 fT>EC50 覆盖率",
    )
    p.add_argument(
        "--tmdd-params",
        default="",
        dest="tmdd_params",
        help="R0,kon,koff,kint,kdeg（5 个值；缺一即拒绝计算）",
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_pd)

    # v4.17：PBPK 资格认定（AFE/AAFE/2 倍内）
    p = sub.add_parser("pbpk-qualify")
    p.add_argument(
        "--pred", required=True, help="预测表：compound_id,time_h,pred,unit（可含 obs）"
    )
    p.add_argument("--obs", default="", help="可选：观测表（与 pred 按 cid+time 合并）")
    p.add_argument(
        "--intended-use", default="screening_level_exposure", dest="intended_use"
    )
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_pbpk_qualify)

    # v4.18：外部 PK/PD 工具互操作
    p = sub.add_parser("interop")
    p.add_argument("--what", choices=["pk-sim", "nonmem", "all"], default="all")
    p.add_argument("--compounds", default="")
    p.add_argument("--curves", default="")
    p.add_argument("--dose-mg", type=float, default=100.0, dest="dose_mg")
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="额外写 OSP 快照 JSON（PK-Sim/MoBi 可直接加载；已实测通过）",
    )
    p.add_argument(
        "--dose-cmt",
        type=int,
        default=1,
        dest="dose_cmt",
        help="给药腔号（口服布局默认 1=胃肠道）",
    )
    p.add_argument(
        "--obs-cmt",
        type=int,
        default=2,
        dest="obs_cmt",
        help="观测腔号（口服布局默认 2=中央室；与给药腔相同会在 NONMEM ADVAN2 下把观测读成胃肠道）",
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_interop)

    # v4.19：肠道菌群代谢子模块
    p = sub.add_parser("gut-micro")
    p.add_argument(
        "--in",
        dest="input",
        default="",
        help="compounds.csv（REST 路径必填；--from-export 时可省）",
    )
    p.add_argument(
        "--from-export",
        default="",
        dest="from_export",
        help="人工导出的 BioTransformer JSON：只跑 biosystem 过滤 + 标注 QC，"
        "不联网；source 标 manual_export，不得冒充实时 REST",
    )
    p.add_argument("--option", default="HGUT", choices=["HGUT", "ALLHUMAN", "SUPERBIO"])
    p.add_argument("--steps", type=int, default=1)
    p.add_argument(
        "--no-control",
        action="store_true",
        help="跳过阳性对照（仅调试；正式分析必须跑对照）",
    )
    p.add_argument(
        "--dump-raw",
        action="store_true",
        dest="dump_raw",
        help="落原始 JSON（bt_raw_<cid>.json），供审计反应标注一致性",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=None,
        dest="poll_timeout",
        help="单分子轮询上限秒数（默认 240）。HGUT 对多羟基糖苷常需更久；"
        "超时记 failed 并继续下一个，不整批失败",
    )
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_gut_micro)

    # v4.20：无 API 工具的通用回填通道
    p = sub.add_parser("readback")
    p.add_argument(
        "--source",
        required=True,
        help="references/readback_schemas.yaml 里的源名（swissadme/aoamp/...）",
    )
    p.add_argument("--file", required=True, help="人工导出的 CSV")
    p.add_argument(
        "--compounds", default="", help="compounds.csv（做结构对齐，强烈建议给）"
    )
    p.add_argument(
        "--map",
        nargs="*",
        default=None,
        help="列映射覆盖：'源列名=端点id[:单位]'，可多个",
    )
    p.add_argument(
        "--kind",
        choices=["measurements", "microbe"],
        default="measurements",
        help="microbe = 菌群数据库互作记录（MicrobeTCM/GutBugDB/MASI），"
        "产出 microbe_interactions_<src>.csv 而非长表",
    )
    p.add_argument(
        "--domain-flag",
        default="",
        dest="domain_flag",
        choices=["", "predicted", "measured", "manual"],
    )
    p.add_argument("--provenance-url", default="", dest="provenance_url")
    p.add_argument("--format", choices=["auto", "csv", "tsv"], default="auto")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_readback)

    # 2026-11-11：离线结构干扰红旗层
    p = sub.add_parser("interference")
    p.add_argument(
        "--in",
        dest="input",
        default="",
        help="compounds.csv 或 id<TAB>smiles（优先用 calc_smiles）",
    )
    p.add_argument("--smiles", default="", help="单分子 SMILES（与 --in 二选一）")
    p.add_argument("--compound-id", default="", dest="compound_id")
    p.add_argument(
        "--catalogs",
        nargs="*",
        default=None,
        help="子集：PAINS_A PAINS_B PAINS_C BRENK NIH（缺省全开）",
    )
    p.add_argument(
        "--selftest",
        action="store_true",
        help="跑 7 例正/负对照（含 C87 愈创木基回归），不写盘",
    )
    p.add_argument("--outdir", default="out_interference")
    p.set_defaults(func=cmd_interference)

    # 2026-11-11：数据源健康探针
    p = sub.add_parser("source-health")
    p.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="源名（缺省 pkcsm/admetasar3/swissadme/biotransformer）",
    )
    p.add_argument("--timeout", type=int, default=8, help="单次 GET 超时秒数")
    p.add_argument("--registry", default="", help="自定义源注册表路径")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_source_health)

    # 2026-11-11：未覆盖端点声明闸门（C82 接线）
    p = sub.add_parser("coverage-gate")
    p.add_argument("--rules", default="", help="端点规则表（缺省随包）")
    p.add_argument("--emit", action="store_true", help="只打印声明段")
    p.add_argument(
        "--check",
        nargs="*",
        default=None,
        help="校验这些文本是否带完整声明；缺标记即 exit 1",
    )
    p.add_argument("--selftest", action="store_true", help="正反双向自检")
    p.add_argument("--outdir", default="", help="写出 coverage_declaration.md")
    p.set_defaults(func=cmd_coverage_gate)

    # 2026-11-17：estimand 绑定门（G13；C01 跨量纲撤回的可执行防复发）
    p = sub.add_parser("estimand")
    p.add_argument("--selftest", action="store_true", help="内置正反例自检")
    p.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="两指标是否可同句比较（跨量纲→exit 4）",
    )
    p.add_argument("--claim", help="端点主张文本")
    p.add_argument("--endpoint", help="--claim 配套端点名")
    p.add_argument("--text", help="扫描文本中已知违规表达式")
    p.add_argument("--artifact", help="审计产物 JSON 的 estimand 声明自洽性")
    p.set_defaults(func=cmd_estimand)

    # 2026-11-18：kNN/Tanimoto 阈值网格敏感性（RISK_COVERAGE_PROTOCOL §3）
    p = sub.add_parser("knn-sensitivity")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--outdir", default="out_sensitivity")
    p.set_defaults(func=cmd_knn_sensitivity)

    # 2026-11-19：prior-art 移植三件套
    p = sub.add_parser("trust")
    p.add_argument("--selftest", action="store_true")
    p.add_argument(
        "--numeric-coverage",
        dest="numeric_coverage",
        help="源文本：检查 --values 里的数是否真的出现过（AdmitOR numeric-coverage）",
    )
    p.add_argument("--values", default="", help="逗号分隔的提取数值")
    p.add_argument("--prereg-report", action="store_true", dest="prereg_report")
    p.add_argument("--prereg-id", dest="prereg_id", default="")
    p.add_argument("--threshold", type=float, default=0.0)
    p.add_argument("--observed", type=float, default=0.0)
    p.add_argument("--noise-floor", type=float, default=0.0, dest="noise_floor")
    p.add_argument("--direction", choices=["<=", ">="], default="<=")
    p.add_argument("--post-hoc-adjusted", action="store_true", dest="post_hoc_adjusted")
    p.set_defaults(func=cmd_trust)

    p = sub.add_parser("claims-fragility")
    p.add_argument("--registry", default="")
    p.add_argument("--json-out", default="", dest="json_out")
    p.set_defaults(func=cmd_claims_fragility)

    # 2026-11-19：100 篇精读移植三件套 + 技能市场 100 skill 移植四件套
    for _name, _mod, _help in [
        (
            "evidence-streams",
            "evidence_streams",
            "两证据流互补/冗余判定（PMID 42798706）",
        ),
        (
            "silent-failure",
            "silent_failure",
            "静默失败率与置信-误差对齐（PMID 42003704）",
        ),
        ("perm-contribution", "perm_contribution", "组件贡献置换检验（PMID 40899589）"),
        ("deviation", "deviation", "OOS/OOT 偏差检测与处置（技能市场 pharma-csv-pro）"),
        (
            "retrieval-card",
            "retrieval_card",
            "可复现检索策略卡（技能市场 search-strategy-builder）",
        ),
        (
            "power-analysis",
            "power_analysis",
            "前瞻性样本量/功效规划（技能市场 quantitative-research）",
        ),
        # 2026-11-19（G14）：统计量外部对照台账的数据面——实跑 scipy/闭式参考实现比对
        (
            "external-compare",
            "external_comparison",
            "G14 外部对照：统计量与参考实现逐点比对",
        ),
    ]:
        p = sub.add_parser(_name, help=_help)
        p.add_argument("--selftest", action="store_true")
        p.set_defaults(func=_make_selftest_cmd(_mod))

    # 2026-11-11：local_admet 6 工具的主 CLI 入口（参数原样透传）
    p = sub.add_parser("local-tools")
    p.add_argument("--tool", default="", help="6 个工具名之一 / 别名 / all")
    p.add_argument("--smiles", default="", help="单个 SMILES")
    p.add_argument("--smiles-file", default="", dest="smiles_file")
    p.add_argument("--id", default="", dest="cid")
    p.add_argument(
        "--features", default="", help="ADMET Predictor 端点筛选，如 T / A,D,T"
    )
    p.add_argument("--dose-mg", type=float, default=None, dest="dose_mg")
    p.add_argument("--ph", type=float, default=None)
    p.add_argument("--format", choices=["json", "long"], default="json")
    p.add_argument("--out", default="")
    p.add_argument("--list-tools", action="store_true", dest="list_tools")
    p.add_argument("--selftest", action="store_true")
    p.add_argument(
        "--deterministic",
        action="store_true",
        help="long 表用固定 retrieved_at，使两次运行逐字节一致",
    )
    p.set_defaults(func=cmd_local_tools)

    a = ap.parse_args(argv)
    # 同行评审 §5 参数缺口：生效参数哈希打印到 stderr（不污染 stdout 产物/--help 解析）。
    # ADT_SHOW_PARAM_HASH=1 显式开启；CI/复现包可用它证明"跑的是哪组参数"。
    if os.environ.get("ADT_SHOW_PARAM_HASH", "") in ("1", "true", "True"):
        try:
            from . import manifest as _MF

            print(
                "[effective-params] sha256=%s" % _MF.effective_params_hash(a),
                file=sys.stderr,
            )
        except Exception:
            pass
    # D2：判据 YAML 的默认值历史上是 cwd 相对路径（30 处）。统一解析一次。
    a = _resolve_ref_args(a)
    # R38 红线 5：使用场景必须显式声明；commercial/pre-commercial 会强制归档调用日志。
    prof = getattr(a, "profile", None)
    if prof:
        from . import compliance as CMP

        CMP.resolve_profile(prof)  # 未知档位直接报错
        os.environ["ADT_PROFILE"] = prof
    # 同行评审 §6 B19：命令角色声明必须与 CLI 机器绑定——新增命令未在
    # command_roles 登记即 fail-closed（审计性元数据孤岛是报告 P1-1 的同型缺陷）。
    # 只在 ADT_ENFORCE_ROLES=1 时强校验，避免历史脚本 --help 路径受影响；
    # 默认批跑的 test_all_cli_commands_have_evidence_role 始终校验。
    if os.environ.get("ADT_ENFORCE_ROLES", "") in ("1", "true", "True"):
        from . import command_roles as _CR

        _ok, _und, _stale = _CR.validate_registry()
        if not _ok:
            raise SystemExit(
                "[cli] 命令角色声明未同步：undeclared=%s stale=%s" % (_und, _stale)
            )
    # validate 不落盘产物，没有 outdir（C55 附带修复）
    if getattr(a, "outdir", None):
        os.makedirs(a.outdir, exist_ok=True)
    a.func(a)


if __name__ == "__main__":
    main()
