# -*- coding: utf-8 -*-
"""从 NPASS 3.0 官方下载文件抽取可随包分发的 curated 子集。

官方文件（2026-10-29 下载）：
  https://bidd.group/NPASS/downloadFiles/NPASS3.0_activities.txt        (105 MB, 1,048,756 行)
  https://bidd.group/NPASS/downloadFiles/NPASS3.0_toxicity.txt          (3.3 MB, 34,975 行)
  https://bidd.group/NPASS/downloadFiles/NPASS3.0_naturalproducts_structure.txt (65 MB)

抽取规则（**只做单位明确的归一，不替用户插补**）：
  - 毒性基准：Rattus norvegicus + LD50 + mg/kg（含 mg.kg-1）→ 每化合物取中位数
  - ADME 子集：PPB(%) / LogD7.4 / Clearance(µL/min)，其余单位不明者丢弃
  - 结构：只保留上述化合物，SMILES + InChIKey 原样

跑法：
  python examples/extract_npass.py --activities _extdata/npass/NPASS3.0_activities.txt \
      --toxicity _extdata/npass/NPASS3.0_toxicity.txt \
      --structures _extdata/npass/NPASS3.0_naturalproducts_structure.txt \
      --outdir assets/external/npass
"""
import argparse
import csv
import io
import json
import os
import statistics


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def extract_adme(activities):
    kw = ("caco", "permeab", "ppb", "protein binding", "clearance",
          "half-life", "t1/2", "logd", "solubility", "bioavailability")
    out = []
    with io.open(activities, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            t = (r.get("activity_type") or "")
            tl = t.lower()
            if not any(k in tl for k in kw):
                continue
            v = _f(r.get("activity_value"))
            u = (r.get("activity_units") or "").strip()
            if v is None:
                continue
            # 只保留单位明确、可归一的
            if t == "PPB" and u == "%" and 0 <= v <= 100:
                ep, unit = "npass_ppb_bound", "%"
            elif t in ("LogD7.4", "CLogD") and u in ("n.a.", ""):
                ep, unit = "npass_logd", "logD"
            elif t == "Clearance" and u in ("ul min-1", "uL/min", "ul/min"):
                ep, unit = "npass_clearance", "uL/min"
            else:
                continue
            out.append(dict(np_id=r.get("np_id", ""), endpoint=ep, value=v,
                            unit=unit, activity_type=t,
                            organism=r.get("assay_organism", ""),
                            ref_id=r.get("ref_id", "")))
    return out


def extract_ld50(toxicity):
    by = {}
    with io.open(toxicity, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if (r.get("activity_type") or "") != "LD50":
                continue
            if "Rattus" not in (r.get("assay_organism") or ""):
                continue
            u = (r.get("activity_units") or "").strip().lower().replace(" ", "")
            if u not in ("mg/kg", "mg.kg-1", "mgkg-1"):
                continue
            v = _f(r.get("activity_value"))
            if v is None or v <= 0:
                continue
            by.setdefault(r["np_id"], []).append(v)
    out = []
    for np_id, vals in sorted(by.items()):
        out.append(dict(np_id=np_id, ld50_median_mg_kg=round(statistics.median(vals), 4),
                        n_records=len(vals), ld50_min=min(vals), ld50_max=max(vals),
                        organism="Rattus norvegicus"))
    return out


def load_structures(path, need_ids):
    out = {}
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r.get("np_id") in need_ids:
                out[r["np_id"]] = r
    return out


def _write(path, cols, rows):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activities", required=True)
    ap.add_argument("--toxicity", required=True)
    ap.add_argument("--structures", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    adme = extract_adme(a.activities)
    ld50 = extract_ld50(a.toxicity)
    need = {r["np_id"] for r in adme} | {r["np_id"] for r in ld50}
    structs = load_structures(a.structures, need)

    for r in adme:
        s = structs.get(r["np_id"], {})
        r["smiles"] = s.get("SMILES", "")
        r["inchikey"] = s.get("InChIKey", "")
    for r in ld50:
        s = structs.get(r["np_id"], {})
        r["smiles"] = s.get("SMILES", "")
        r["inchikey"] = s.get("InChIKey", "")

    p1 = os.path.join(a.outdir, "npass_tox_ld50_rat.csv")
    n1 = _write(p1, ["np_id", "smiles", "inchikey", "ld50_median_mg_kg",
                     "n_records", "ld50_min", "ld50_max", "organism"], ld50)
    p2 = os.path.join(a.outdir, "npass_adme_subset.csv")
    n2 = _write(p2, ["np_id", "smiles", "inchikey", "endpoint", "value", "unit",
                     "activity_type", "organism", "ref_id"], adme)
    p3 = os.path.join(a.outdir, "npass_structures_subset.csv")
    n3 = _write(p3, ["np_id", "smiles", "inchikey"],
                [dict(np_id=k, smiles=v.get("SMILES", ""),
                      inchikey=v.get("InChIKey", "")) for k, v in sorted(structs.items())])

    meta = dict(dataset="NPASS 3.0", source_url="https://bidd.group/NPASS/index.php",
                download_page="https://bidd.group/NPASS/downloadnpass.html",
                extracted_at="2026-10-29",
                counts=dict(ld50_compounds=n1, adme_records=n2, structures=n3),
                rules=dict(ld50="Rattus norvegicus LD50 mg/kg, median per compound",
                           adme="PPB %bound / LogD7.4 / Clearance uL/min only"),
                license_note="NPASS is free for academic/non-commercial use; "
                             "cite Lin et al. Nucleic Acids Res 2026;54:D1519-D1527 "
                             "(DOI 10.1093/nar/gkaf1196). This is a curated subset, "
                             "not the full NPASS database.")
    with io.open(os.path.join(a.outdir, "PROVENANCE.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print("[npass] LD50 %d 化合物 -> %s" % (n1, p1))
    print("[npass] ADME %d 条 -> %s" % (n2, p2))
    print("[npass] structures %d -> %s" % (n3, p3))


if __name__ == "__main__":
    main()
