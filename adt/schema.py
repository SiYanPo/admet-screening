# -*- coding: utf-8 -*-
"""ADMET 长表数据契约。

设计要点（为什么不用宽表）：
  本项目踩过的坑全来自宽表——换结构后列对不上、按行号匹配错位
  （ADMETlab 结果里 A 与 L 的 raw_smiles 前缀相同）、不同源的列名不一致。

所以固定三张表：
  compounds.csv     一行一个分子（标准化前后的 SMILES 必须都记）
  measurements.csv  长表，一行 = 一个分子 × 一个端点 × 一个源
  metabolites.csv   代谢产物（可选，来自 BioTransformer 之类）

所有写盘都走本模块，保证字段顺序与取值域一致。
"""

import csv
import io
import os
from datetime import datetime

# ---- 取值域 ----------------------------------------------------------------
DOMAIN_FLAGS = {
    "measured",  # 有实测真值
    "predicted",  # 模型在适用域内的预测
    "out_of_domain",  # 源明确拒绝预测（NoPrediction）或经判据判定域外
    "saturated",  # 在本化学类上无区分力（≥90% 同向 / 极差 <5%）
    "manual",  # 人工从网页读数录入
    "error",  # 调用失败
}

COMPOUND_COLS = [
    "compound_id",
    "input_smiles",
    "calc_smiles",
    "state_flag",
    "formula",
    "inchikey",
    "mw",
    "clogp",
    "hard_gate_problems",
    "state_sensitive",
    "note",
]

MEASUREMENT_COLS = [
    "compound_id",
    "endpoint",
    "value",
    "unit",
    "source",
    "source_version",
    "retrieved_at",
    "domain_flag",
    "uncertainty",
    "provenance_url",
    "note",
]

METABOLITE_COLS = [
    "compound_id",
    "metabolite_smiles",
    "metabolite_inchikey",
    "name",
    "reaction_type",
    "enzymes",
    "biosystem",
    "source",
    "provenance_url",
]


def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _write(path, cols, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return len(rows)


def write_compounds(path, rows):
    return _write(path, COMPOUND_COLS, rows)


def write_measurements(path, rows):
    bad = [r for r in rows if r.get("domain_flag") not in DOMAIN_FLAGS]
    if bad:
        raise ValueError(
            "domain_flag 取值非法: %s" % sorted({r.get("domain_flag") for r in bad})
        )
    return _write(path, MEASUREMENT_COLS, rows)


def write_metabolites(path, rows):
    return _write(path, METABOLITE_COLS, rows)


def read_measurements(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def measurement(
    compound_id,
    endpoint,
    value,
    unit,
    source,
    source_version="",
    domain_flag="predicted",
    uncertainty="",
    provenance_url="",
    note="",
):
    if domain_flag not in DOMAIN_FLAGS:
        raise ValueError("domain_flag 非法: %r" % domain_flag)
    return dict(
        compound_id=compound_id,
        endpoint=endpoint,
        value=value,
        unit=unit,
        source=source,
        source_version=source_version,
        retrieved_at=now(),
        domain_flag=domain_flag,
        uncertainty=uncertainty,
        provenance_url=provenance_url,
        note=note,
    )


def validate(rows, require_domain=True):
    """轻量自检：返回问题列表，空列表表示通过。"""
    problems = []
    for i, r in enumerate(rows, 1):
        if not r.get("compound_id"):
            problems.append(f"row {i}: 缺 compound_id")
        if not r.get("endpoint"):
            problems.append(f"row {i}: 缺 endpoint")
        if require_domain and r.get("domain_flag") not in DOMAIN_FLAGS:
            problems.append(f"row {i}: domain_flag={r.get('domain_flag')!r}")
        if r.get("domain_flag") == "out_of_domain" and r.get("value") not in ("", None):
            problems.append(f"row {i}: out_of_domain 不应带数值（会被误算）")
        # C48：predicted 带空值会在聚合层产生"看似可判的空数"（饱和扫描实测踩过）
        if r.get("domain_flag") in ("predicted", "measured") and r.get("value") in (
            "",
            None,
        ):
            problems.append(f"row {i}: {r.get('domain_flag')} 但 value 为空")
        # C49：measured 无 provenance 会斩断结论溯源链（A2 ledger 的前提）
        if r.get("domain_flag") == "measured" and not r.get("provenance_url"):
            problems.append(f"row {i}: measured 缺 provenance_url（溯源链断裂）")
    return problems


def advisory_warnings(rows):
    """非阻断告警（2026-11-19，首轮报告 🟡）：数值结论应带 uncertainty/CI。

    **刻意不进 validate()/contract_problems()**：那两个返回值被
    `write_measurements_checked` 当作硬契约，任何条目都会拒绝落盘；
    把告警塞进去会把历史数据迁移全部打断（本轮实测踩过，已修）。
    本函数供显式 `python -m adt.cli advisory-check` 或报告层调用，
    只提示、不阻断写入，符合"红线6 在文本层扫措辞"的既有定位。
    """
    warnings = []
    for i, r in enumerate(rows, 1):
        v = r.get("value")
        has_value = v not in ("", None)
        unc = str(r.get("uncertainty") or "").strip()
        # 2026-11-19：manual（人工读网页/文献录入）同样是"数值进结论"，没区间就该提示；
        # 旧集合漏了 manual，等于给人工读数开了免检通道。
        if (
            has_value
            and r.get("domain_flag") in ("predicted", "measured", "manual")
            and not unc
            and not r.get("ci_lo")
            and not r.get("ci_hi")
        ):
            warnings.append(
                f"row {i}: 数值 {v} 无 uncertainty/CI（红线6：不得无区间进结论）"
            )
    return warnings


# ---- C11 / C1-a（2026-11-04）：写入端强校验 --------------------------------
# 根因：validate() 只被 CLI 的**读取端**调用，且十余个子命令可显式
# --allow-invalid；而 write_measurements() 只查 domain_flag 取值域，
# 坏数据（out_of_domain 带值、缺 compound_id、未登记列被 extrasaction="ignore"
# 静默丢弃）能直接落盘并进入证据链。校验必须前移到「写」这一刻。
class ContractViolation(ValueError):
    """长表写入契约违规：不落盘、不产生半成品产物（C11 / C1-a）。"""


METABOLITE_REQUIRED = ("compound_id", "metabolite_smiles", "source")


def contract_problems(rows, require_source_version=False, check_unregistered_cols=True):
    """写入前的完整契约检查；返回问题列表（空 = 通过）。

    比 validate() 多三类：
      * 未登记且非空的列 —— `_write` 的 extrasaction="ignore" 会静默丢弃，
        是「产物看起来写了、关键字段其实没写」的直接来源；
      * 同一 (compound_id, endpoint, source, source_version) 键的 unit 冲突；
      * 可选强制 source_version（由 C1-b 的 merge 入口启用）。
    """
    rows = list(rows)
    problems = list(validate(rows))
    known = set(MEASUREMENT_COLS)
    seen_units = {}
    for i, r in enumerate(rows, 1):
        if check_unregistered_cols:
            extra = sorted(
                {
                    str(k)
                    for k, v in r.items()
                    if k not in known and str(v or "").strip() != ""
                }
            )
            if extra:
                problems.append(
                    f"row {i}: 未登记列 {extra} 会被 _write 静默丢弃，证据链断裂"
                )
        key = tuple(
            str(r.get(k) or "")
            for k in ("compound_id", "endpoint", "source", "source_version")
        )
        unit = str(r.get("unit") or "").strip()
        if key in seen_units and seen_units[key] != unit:
            problems.append(
                f"row {i}: 同键 {key} 的 unit 冲突 {seen_units[key]!r} vs {unit!r}"
                "（异量纲数值不可合并）"
            )
        seen_units.setdefault(key, unit)
        if require_source_version and not str(r.get("source_version") or "").strip():
            problems.append(
                f"row {i}: 缺 source_version（不同版本权重不可混用，C1-b / C11）"
            )
    return problems


def _raise_contract(problems, path):
    head = "\n".join("   " + p for p in problems[:10])
    more = (
        ("\n   ...（其余 %d 条略）" % (len(problems) - 10))
        if len(problems) > 10
        else ""
    )
    raise ContractViolation(
        "长表写入被拒绝（C11 / C1-a）：%d 个契约问题，目标文件未写出：%s\n%s%s"
        % (len(problems), path, head, more)
    )


def write_measurements_checked(path, rows, require_source_version=False, strict=True):
    """写入端强校验入口。strict=True（默认）时任何问题都不落盘。

    `strict=False` 仅供显式的历史数据迁移脚本使用；产物必须自带
    `non_evidence` 标记，且不得进入报告（由调用方负责，不在本函数内猜用途）。
    """
    rows = list(rows)
    problems = contract_problems(rows, require_source_version=require_source_version)
    if problems and strict:
        _raise_contract(problems, path)
    return _write(path, MEASUREMENT_COLS, rows)


def write_metabolites_checked(path, rows, strict=True):
    """代谢产物写入端：补必需字段断言（C11 / C1-a）。"""
    rows = list(rows)
    problems = []
    for i, r in enumerate(rows, 1):
        for c in METABOLITE_REQUIRED:
            if not str(r.get(c) or "").strip():
                problems.append(f"row {i}: metabolites 缺必需字段 {c}")
    if problems and strict:
        _raise_contract(problems, path)
    return _write(path, METABOLITE_COLS, rows)
