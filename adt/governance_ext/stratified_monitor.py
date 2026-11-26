# -*- coding: utf-8 -*-
"""盲区1：化学空间分层监控（Stratified Chemical Space Monitoring）。

全局金标准探针只能抓"整体平移/系统变笨"，抓不到针对某一专利骨架的
定向投毒：攻击者在核心 scaffold 上永远输出"低风险"，其余分子正常。

两层防御：
  1. **局部探针**：按 (Murcko 骨架, 药效团签名) 分桶建立锚点，
     只比较同桶分子，局部漂移不会被全局均值淹没。
  2. **反事实探针**：对分子加一个"无关甲基"再预测；
     若结果断崖式翻转（|Δ|>阈值 或方向翻转），高度怀疑局部后门。

依赖 RDKit；任何标准化失败 fail-closed 为 ALERT，绝不静默放过。
"""

from __future__ import annotations

import hashlib
import json


def _mol_from(smiles):
    from rdkit import Chem

    m = Chem.MolFromSmiles(str(smiles))
    if m is None:
        raise ValueError("SMILES 无法解析")
    return m


def scaffold_of(smiles):
    try:
        from rdkit.Chem.Scaffolds import MurckoScaffold

        m = _mol_from(smiles)
        sc = MurckoScaffold.MurckoScaffoldSmiles(mol=m)
        return sc or "NO_SCAFFOLD"
    except Exception:
        return "PARSE_FAILED"


def pharmacophore_signature(smiles):
    """药效团粗签名：HBD/HBA/芳香环/净电荷分箱，用于骨架内再分层。"""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski

        m = _mol_from(smiles)
        hbd = min(4, int(Lipinski.NumHDonors(m)))
        hba = min(8, int(Lipinski.NumHAcceptors(m))) // 2
        ar = min(4, int(Descriptors.NumAromaticRings(m)))
        charge = max(-2, min(2, int(Chem.GetFormalCharge(m))))
        return "HBD%d_HBA%d_AR%d_Q%+d" % (hbd, hba, ar, charge)
    except Exception:
        return "UNKNOWN_PHARM"


def probe_key(smiles):
    sc = scaffold_of(smiles)
    ph = pharmacophore_signature(smiles)
    return {"scaffold": sc, "pharmacophore": ph, "key": "%s|%s" % (sc, ph)}


def methyl_probe_smiles(smiles):
    """确定性加一个甲基：选第一个可成键且未饱和的重原子。"""
    from rdkit import Chem

    m = Chem.RWMol(_mol_from(smiles))
    target = None
    for atom in m.GetAtoms():
        if atom.GetSymbol() == "H":
            continue
        # 有可取代氢的重原子才是化学上合理的甲基化位点
        if atom.GetTotalNumHs() > 0:
            target = atom.GetIdx()
            break
    if target is None:
        return None, "NO_AVAILABLE_VALENCE"
    try:
        new_idx = m.AddAtom(Chem.Atom(6))
        m.AddBond(target, new_idx, Chem.BondType.SINGLE)
        Chem.SanitizeMol(m)
        return Chem.MolToSmiles(m.GetMol()), None
    except Exception as exc:
        return None, str(exc)[:120]


class StratifiedAnchorStore:
    """分层锚点；按 (scaffold, pharmacophore, endpoint) 建桶。"""

    def __init__(self):
        self._anchors = {}

    def add(
        self,
        smiles,
        endpoint,
        expected,
        *,
        tolerance=0.1,
        version="v1",
        source="scaffold-anchor",
    ):
        k = probe_key(smiles)
        key = (k["key"], endpoint, version)
        rec = {
            "key": k,
            "endpoint": endpoint,
            "expected": float(expected),
            "tolerance": float(tolerance),
            "version": version,
            "source": source,
            "fingerprint": hashlib.sha256(
                json.dumps(key, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:12],
        }
        self._anchors[key] = rec
        return rec

    def get(self, smiles, endpoint, version="v1"):
        k = probe_key(smiles)
        return self._anchors.get((k["key"], endpoint, version))


def stratified_drift(anchor, observed):
    if anchor is None:
        return {
            "status": "NO_LOCAL_ANCHOR",
            "alert": False,
            "note": "该分层无局部锚点；不误报，但需补锚点",
        }
    drift = abs(float(observed) - anchor["expected"])
    alert = drift > anchor["tolerance"]
    return {
        "status": "LOCAL_DRIFT" if alert else "LOCAL_OK",
        "alert": alert,
        "drift": round(drift, 6),
        "tolerance": anchor["tolerance"],
        "scaffold": anchor["key"]["scaffold"],
        "pharmacophore": anchor["key"]["pharmacophore"],
    }


def counterfactual_check(smiles, predict_fn, *, endpoint="dili", flip_threshold=0.3):
    """加甲基后断崖翻转 → 局部后门警报。"""
    try:
        base = float(predict_fn(smiles, endpoint=endpoint))
    except Exception as exc:
        return {"alert": True, "status": "PREDICT_FAILED", "detail": str(exc)[:120]}
    m_smiles, err = methyl_probe_smiles(smiles)
    if m_smiles is None:
        return {
            "alert": True,
            "status": "COUNTERFACTUAL_CONSTRUCTION_FAILED",
            "detail": err,
        }
    try:
        mutated = float(predict_fn(m_smiles, endpoint=endpoint))
    except Exception as exc:
        return {"alert": True, "status": "PREDICT_FAILED", "detail": str(exc)[:120]}
    delta = mutated - base
    flip = (base > 0.5) != (mutated > 0.5)
    alert = abs(delta) > flip_threshold or flip
    return {
        "alert": alert,
        "status": "COUNTERFACTUAL_FLIP" if alert else "COUNTERFACTUAL_STABLE",
        "base": round(base, 6),
        "methylated": round(mutated, 6),
        "delta": round(delta, 6),
        "direction_flip": flip,
        "methyl_probe_smiles": m_smiles,
        "threshold": flip_threshold,
    }


class BucketDriftMonitor:
    """桶内 EWMA/CUSUM：抓低曲率、系统性平移（如整桶 -0.15）。"""

    def __init__(self, *, k=0.03, h=0.35, ewma_lambda=0.3):
        self.k, self.h, self.lam = float(k), float(h), float(ewma_lambda)
        self.state = {}

    def update(self, bucket, residual):
        st = self.state.setdefault(
            bucket, {"pos": 0.0, "neg": 0.0, "ewma": None, "n": 0, "mean": 0.0}
        )
        r = float(residual)
        st["n"] += 1
        st["mean"] += (r - st["mean"]) / st["n"]
        st["pos"] = max(0.0, st["pos"] + r - self.k)
        st["neg"] = max(0.0, st["neg"] - r - self.k)
        st["ewma"] = (
            r if st["ewma"] is None else self.lam * r + (1 - self.lam) * st["ewma"]
        )
        alert = st["pos"] > self.h or st["neg"] > self.h
        return {
            "bucket": bucket,
            "n": st["n"],
            "mean": round(st["mean"], 6),
            "cusum_pos": round(st["pos"], 6),
            "cusum_neg": round(st["neg"], 6),
            "ewma": round(st["ewma"], 6),
            "alert": alert,
        }

    def scan(self, records, *, bucket_key="scaffold", expected):
        """records: [{"scaffold":..., "observed":...}]；expected 可为函数或字典。"""
        out = []
        for r in records:
            bucket = r.get(bucket_key)
            exp = expected(bucket) if callable(expected) else expected.get(bucket)
            if exp is None:
                continue
            out.append(self.update(bucket, float(r.get("observed")) - float(exp)))
        alerts = [x for x in out if x["alert"]]
        return {
            "records": out,
            "n": len(out),
            "n_alert": len(alerts),
            "status": "SYSTEMATIC_DRIFT" if alerts else "CLEAN",
        }


class CounterfactualOperatorLibrary:
    """最小攻击面算子库；每个算子都必须能生成可证伪的反事实。"""

    def __init__(self):
        self.ops = {
            "methyl": self._methyl,
            "halogen_scan": self._halogen,
            "ring_to_pyridine": self._ring_to_pyridine,
            "charge_flip": self._charge_flip,
        }

    @staticmethod
    def _mol(smiles):
        from rdkit import Chem

        m = Chem.MolFromSmiles(str(smiles))
        if m is None:
            raise ValueError("PARSE_FAILED")
        return Chem.RWMol(m)

    @staticmethod
    def _add_atom(m, symbol):
        from rdkit import Chem

        for atom in m.GetAtoms():
            if atom.GetSymbol() != "H" and atom.GetTotalNumHs() > 0:
                idx = atom.GetIdx()
                new = m.AddAtom(Chem.Atom(symbol))
                m.AddBond(idx, new, Chem.BondType.SINGLE)
                Chem.SanitizeMol(m)
                return Chem.MolToSmiles(m.GetMol())
        return None

    def _methyl(self, smiles):
        m = self._mol(smiles)
        v = self._add_atom(m, 6)
        return [(v, "methyl")] if v else []

    def _halogen(self, smiles):
        out = []
        for sym, name in ((9, "F"), (17, "Cl"), (35, "Br")):
            try:
                m = self._mol(smiles)
                v = self._add_atom(m, sym)
                if v:
                    out.append((v, "halogen_%s" % name))
            except Exception:
                continue
        return out

    def _ring_to_pyridine(self, smiles):
        from rdkit import Chem

        m = self._mol(smiles)
        for atom in m.GetAtoms():
            if (
                atom.GetIsAromatic()
                and atom.GetSymbol() == "C"
                and atom.GetTotalNumHs() > 0
                and atom.IsInRing()
            ):
                atom.SetAtomicNum(7)
                try:
                    Chem.SanitizeMol(m)
                    return [(Chem.MolToSmiles(m.GetMol()), "ring_to_pyridine")]
                except Exception:
                    return []
        return []

    def _charge_flip(self, smiles):
        from rdkit import Chem

        s = Chem.MolToSmiles(Chem.MolFromSmiles(str(smiles)))
        for a, b in (("C(=O)O", "C(=O)[O-]"), ("C(=O)[O-]", "C(=O)O")):
            if a in s:
                v = s.replace(a, b, 1)
                if Chem.MolFromSmiles(v) is not None:
                    return [(v, "charge_flip")]
        return []

    def variants(self, smiles):
        out = []
        for name, fn in self.ops.items():
            try:
                out.extend(fn(smiles))
            except Exception:
                continue
        return out

    def coverage(self, records, *, id_key="id"):
        covered, blind, per_op = 0, [], {}
        for i, r in enumerate(records):
            vs = self.variants(r.get("smiles"))
            if vs:
                covered += 1
                for _, op in vs:
                    per_op[op] = per_op.get(op, 0) + 1
            else:
                blind.append(r.get(id_key, i))
        return {
            "n": len(records),
            "covered": covered,
            "coverage": round(covered / max(1, len(records)), 4),
            "blind_spots": blind,
            "per_operator": per_op,
            "status": "PROBE_BLIND_SPOT" if covered < len(records) else "COVERED",
        }


def operator_assertions(
    records, predict_fn, *, endpoint="dili", flip_threshold=0.15, ops=None
):
    """每个算子绑定可证伪断言：已知安全分子的反事实若方向翻转/大幅偏移即报警。"""
    lib = CounterfactualOperatorLibrary()
    out = []
    for r in records:
        smi = r.get("smiles")
        try:
            base = float(predict_fn(smi, endpoint=endpoint))
        except Exception:
            out.append({"smiles": smi, "status": "PREDICT_FAILED", "alert": True})
            continue
        vs = lib.variants(smi)
        if ops:
            vs = [(v, o) for v, o in vs if o in ops]
        if not vs:
            out.append(
                {"smiles": smi, "status": "NO_OPERATOR_REACHABLE", "alert": True}
            )
            continue
        for variant, op in vs:
            try:
                val = float(predict_fn(variant, endpoint=endpoint))
            except Exception:
                out.append(
                    {"smiles": smi, "op": op, "status": "PREDICT_FAILED", "alert": True}
                )
                continue
            delta = val - base
            flip = (base <= 0.5) != (val <= 0.5)
            alert = flip or abs(delta) > flip_threshold
            out.append(
                {
                    "smiles": smi,
                    "op": op,
                    "base": round(base, 6),
                    "variant": round(val, 6),
                    "delta": round(delta, 6),
                    "alert": alert,
                    "status": (
                        "DIRECTION_FLIP"
                        if flip
                        else "LARGE_SHIFT" if alert else "STABLE"
                    ),
                }
            )
    return {
        "records": out,
        "n_alert": sum(1 for x in out if x["alert"]),
        "n": len(out),
        "status": (
            "OPERATOR_ASSERTION_FAILED" if any(x["alert"] for x in out) else "PASS"
        ),
    }


class StratifiedMonitor:
    def __init__(self, store=None):
        self.store = store or StratifiedAnchorStore()

    def run(
        self, records, predict_fn, *, endpoint="dili", version="v1", flip_threshold=0.3
    ):
        """records: [{"smiles": ..., "observed": 0.x}]；返回逐条与汇总。"""
        out = []
        for rec in records:
            smi = rec.get("smiles")
            anchor = self.store.get(smi, endpoint, version)
            local = stratified_drift(anchor, rec.get("observed"))
            cf = counterfactual_check(
                smi, predict_fn, endpoint=endpoint, flip_threshold=flip_threshold
            )
            out.append(
                {
                    "smiles_hash": hashlib.sha256(str(smi).encode()).hexdigest()[:16],
                    "local": local,
                    "counterfactual": cf,
                    "alert": local["alert"] or cf["alert"],
                }
            )
        n_alert = sum(1 for r in out if r["alert"])
        return {
            "records": out,
            "n": len(out),
            "n_alert": n_alert,
            "status": "POISONING_SUSPECTED" if n_alert else "CLEAN",
        }
