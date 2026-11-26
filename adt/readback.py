# -*- coding: utf-8 -*-
"""通用外部结果回填通道（v4.20）：给"没有 API、只能人在浏览器里跑"的工具一条合规入口。

背景：截图里一半的推荐工具（SwissADME / AOMP / Graph-pKa / CardioSafe /
Cardiosim-Tox / HerbToxNet / KAN-PROSPECT / MicrobeTCM / GutBugDB）**都没有可编程 API**。
对这类工具，写爬虫既违反 ToS（XenoSite 已明确口径：程序化访问需商业许可），
也极脆弱（前端框架一改就废）。本 skill 在 XenoSite 上已经确立了正确做法：
**prepare 人工跑 → 导出文件 → ingest 回填**，并把出处写进 provenance_url。

本模块把"回填"从一次性脚本升级成契约：
  1. 每个源一个 schema（references/readback_schemas.yaml）：列名 → 端点 id / 单位；
  2. 回填时**强制 InChIKey/规范 SMILES 对齐**（铁律 1：结构不真，后面全废）——
     对不上的分子进 unmatched 报表，绝不静默丢弃、也绝不用名字硬配；
  3. 未映射的列**逐列报出来**（不静默丢），否则"少了一半端点"没人知道；
  4. 所有行经 `schema.measurement()` 落长表，`measured` 必须带 provenance_url
     （没 DOI/URL 的自动降级为 manual，并记一笔）。
"""

from __future__ import division

import io
import os

import yaml

__all__ = [
    "load_schemas",
    "ingest",
    "DEFAULT_SCHEMA",
    "normalize_key",
    "BACKFILL_FLAGS",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA = os.path.join(
    os.path.dirname(_HERE), "references", "readback_schemas.yaml"
)

# 回填通道**只允许**这三个取值（C2 信任根约束）：
#   predicted —— 工具自身的预测值（默认）
#   measured  —— 回填的是实测数据，且必须带显式 provenance_url（否则自动降级 manual）
#   manual    —— 人工从网页读数录入（无引文时的兜底）
# **禁止** out_of_domain / saturated / error：这三个取值改变的是"可判性"与"是否入票"，
# 只能由 reliability.apply_class_blocks 与饱和扫描产生。若允许回填表自行声明，
# 任何人只要在 CSV 里写一列就能把分子踢出裁决 —— 这正是 C2 审计要堵的洞。
BACKFILL_FLAGS = ("predicted", "measured", "manual")


def load_schemas(path=None):
    p = path or DEFAULT_SCHEMA
    if not os.path.exists(p):
        raise IOError("readback schema 不存在：%s" % p)
    with io.open(p, encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
    return d.get("sources") or {}


def _canon_smiles(s):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(s) if s else None
    if m is None:
        return None
    return Chem.MolToSmiles(m, isomericSmiles=True)


def _inchikey_of(s):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(s) if s else None
    if m is None:
        return None
    try:
        return Chem.MolToInchiKey(m)
    except Exception:  # noqa: BLE001  InChI 不可用时不阻断回填
        return None


def normalize_key(raw, key_kind="smiles"):
    """把回填表里的标识统一成可比较的规范化值。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    if key_kind == "inchikey":
        return raw.upper()
    if key_kind == "compound_id":
        return raw
    return _canon_smiles(raw) or raw


def ingest(
    source,
    csv_path,
    compounds=None,
    schema_path=None,
    domain_flag=None,
    provenance_url=None,
    source_version="",
    col_map_override=None,
):
    """把一份人工导出的结果表回填成长表行。

    compounds: compounds.csv 行（含 compound_id / calc_smiles / inchikey）；
               给了就做结构对齐，没给则直接用回填表的 compound_id（并报无对齐）。
    col_map_override: {"源列名": {"id": 端点, "unit": 单位}}，用于 schema 里还没登记
               的源（或列名与登记不符时）。**这是唯一允许的"临时映射"方式**——
               宁可让人显式写映射，也不做列名模糊匹配（那会静默错配端点）。
    返回 (rows, report)。
    """
    from .schema import measurement

    schemas = load_schemas(schema_path)
    if source not in schemas and not col_map_override:
        raise ValueError(
            "未知回填源 %r 且未给 --map；已注册：%s" % (source, sorted(schemas))
        )
    sch = schemas.get(source) or {}
    key_col = sch.get("key_column", "SMILES")
    key_kind = (sch.get("key_kind") or "smiles").lower()
    default_source_version = sch.get("source_version", "")
    url = provenance_url or sch.get("url", "")
    explicit_url = bool(provenance_url)
    flag = domain_flag or sch.get("domain_flag", "predicted")
    if flag not in BACKFILL_FLAGS:
        raise ValueError(
            "回填通道不接受 domain_flag=%r；BACKFILL_FLAGS 只允许 %s。"
            "out_of_domain/saturated/error 会改变可判性与是否入票，"
            "只能由 reliability.apply_class_blocks 与饱和扫描产生，"
            "不允许由回填表（或 schema）自行声明。" % (flag, list(BACKFILL_FLAGS))
        )
    col_map = dict(sch.get("endpoints") or {})
    if col_map_override:
        col_map.update(col_map_override)
    class_tokens = {
        str(k).lower(): v for k, v in (sch.get("class_tokens") or {}).items()
    }
    id_col = sch.get("id_column", "compound_id")

    with io.open(csv_path, encoding="utf-8-sig") as fh:
        import csv as _csv

        reader = _csv.DictReader(fh)
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("回填表为空：%s" % csv_path)

    # ---- 结构对齐 ----
    index = {}
    for c in compounds or []:
        smi = c.get("calc_smiles") or c.get("input_smiles") or c.get("smiles")
        for k in (
            _canon_smiles(smi),
            (c.get("inchikey") or "").upper() or None,
            c.get("compound_id"),
        ):
            if k:
                index[k] = c["compound_id"]

    rows, unmatched, problems = [], [], []
    cols = list(raw_rows[0].keys())
    ignore = set(sch.get("ignore_columns") or [])
    unmapped = [
        c
        for c in cols
        if c not in (key_col, id_col) and c not in col_map and c not in ignore
    ]

    for i, r in enumerate(raw_rows, 1):
        cid = None
        if compounds:
            cid = index.get(normalize_key(r.get(key_col), key_kind))
            if cid is None:
                unmatched.append((i, (r.get(key_col) or "")[:60]))
                continue
        else:
            cid = (r.get(id_col) or r.get(key_col) or "").strip()
            if not cid:
                problems.append("row %d: 无 compound_id 也无 SMILES" % i)
                continue

        for col, spec in col_map.items():
            if col not in r:
                continue
            raw = (r.get(col) or "").strip()
            if raw == "":
                continue
            endpoint = spec["id"] if isinstance(spec, dict) else str(spec)
            unit = spec.get("unit", "") if isinstance(spec, dict) else ""
            low = raw.lower()
            if low in class_tokens:
                val = class_tokens[low]
            else:
                try:
                    val = float(raw)
                except ValueError:
                    val = raw  # 文本类（如 High/Medium/Low）原样保留
            f = flag
            note = ""
            # measured 必须有**显式**引文（DOI/具体实验页），工具主页不算
            if f == "measured" and not explicit_url:
                f = "manual"
                note = (
                    "缺显式 provenance_url（工具主页不算引文），measured 降级为 manual"
                )
            rows.append(
                measurement(
                    compound_id=cid,
                    endpoint=endpoint,
                    value=val,
                    unit=unit,
                    source=source,
                    source_version=source_version or default_source_version,
                    domain_flag=f,
                    provenance_url=url,
                    note=note,
                )
            )

    report = dict(
        source=source,
        n_input=len(raw_rows),
        n_rows=len(rows),
        n_compounds=len({r["compound_id"] for r in rows}),
        unmatched=unmatched[:20],
        n_unmatched=len(unmatched),
        unmapped_columns=unmapped,
        problems=problems,
        endpoints_covered=sorted({r["endpoint"] for r in rows}),
        key_kind=key_kind,
        structure_checked=bool(compounds),
        notice=sch.get("notice", ""),
    )
    return rows, report
