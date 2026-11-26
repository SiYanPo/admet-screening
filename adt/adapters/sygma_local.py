# -*- coding: utf-8 -*-
"""SyGMa 本地代谢预测引擎（BioTransformer 的**降级替代**，不是等价物）。

### 为什么需要它
`biotransformer.ca` 在本网络下不可达（实测：裸域 HTTPS/HTTP 均 20s 超时、
`www` 只回 301 指向裸域、发 `Host: biotransformer.ca` 借 www 的边也超时）。
旧行为只能整段记 REFUSED —— 诚实地"不冒充"，但代谢预测这一层就永久空着。

### 替代引擎的事实基础（必须随产物一起说）
* **SyGMa**：Ridder L, Wagener M. *SyGMa: combining expert knowledge and empirical
  scoring in the generation of metabolic routes.* J Cheminform. 2008;1:3.
  —— 基于 Reactivity Rule Set 的 I/II 相代谢途径生成器，规则集公开可审计，
  输出可用 empirical scoring 排序（本适配器用 `Tree.calc_scores`）。
* 装法（**实测可复现**，2026-11-19）：
  `python -m pip install sygma --no-deps --no-build-isolation -i https://pypi.org/simple`
  坑：① 构建隔离里没有 rdkit，setup.py 直接 ImportError，必须 `--no-build-isolation`；
      ② sygma 1.1.0 仍 `import pkg_resources`，setuptools ≥81 已移除该模块，
        需 `pip install "setuptools<81"`。
* **不等价声明**：SyGMa 的规则覆盖面与 BioTransformer 不同（前者偏 CYP/Phase II
  专家规则 + 经验打分，后者含微生物、肠道菌群等模块）。因此本引擎的产物
  `source=sygma_local`，`biosystem=human`，并**不得**拿来冒充 BioTransformer 结果；
  两者若日后都可用，应作为两个独立源并存，而不是互相替代。

### 与"0 产物 ≠ 无代谢"的关系
SyGMa 对同一分子可能给出大量节点（伊马替尼 1 个 cycle 即 >2000 节点），
所以本适配器按分数截断并**显式记录截断**（`n_nodes_total` / `n_kept`），
被截掉的部分不是"不存在"，只是没进表。
"""

import os
import time

from .base import Adapter, AdapterResult


def _rules_dir():
    import sygma

    return os.path.join(os.path.dirname(sygma.__file__), "rules")


class SyGMaAdapter(Adapter):
    name = "sygma_local"
    version = "1.1.0"
    status = "local"
    min_interval_s = 0.0

    def __init__(self, verbose=True, cycles=1, top=25, min_score=0.05):
        Adapter.__init__(self, verbose=verbose)
        self.cycles = max(1, int(cycles))
        self.top = max(1, int(top))
        self.min_score = float(min_score)

    # ---------------------------------------------------------------- 可用性
    def preflight(self, timeout=10):
        try:
            import sygma  # noqa: F401

            d = _rules_dir()
            for f in ("phase1.txt", "phase2.txt"):
                if not os.path.exists(os.path.join(d, f)):
                    self.log("预检失败：缺规则文件 %s" % f)
                    return False
            return True
        except Exception as exc:  # noqa: BLE001
            self.log("预检失败（%s）：%s" % (type(exc).__name__, exc))
            return False

    def _scenario(self):
        from sygma import Scenario

        d = _rules_dir()
        return Scenario(
            [
                [os.path.join(d, "phase1.txt"), self.cycles],
                [os.path.join(d, "phase2.txt"), 1],
            ]
        )

    # ---------------------------------------------------------------- 预测
    def run(self, compounds, chemical_class="", **kw):
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")
        sc = self._scenario()
        metabolites, meta = [], dict(
            engine="sygma_local",
            rules="phase1+phase2",
            cycles=self.cycles,
            per_compound=[],
            errors=[],
        )
        t0 = time.time()
        for c in compounds:
            cid = c.get("compound_id") or ""
            smi = c.get("calc_smiles") or c.get("smiles") or c.get("input_smiles")
            mol = Chem.MolFromSmiles(smi) if smi else None
            if mol is None:
                meta["errors"].append(dict(compound_id=cid, error="bad_smiles"))
                continue
            try:
                tree = sc.run(Chem.Mol(mol))
                tree.calc_scores()
            except Exception as exc:  # noqa: BLE001
                meta["errors"].append(dict(compound_id=cid, error=str(exc)[:160]))
                continue
            parent_key = getattr(tree, "parentkey", None)
            nodes = []
            for k, n in tree.nodes.items():
                if k == parent_key:
                    continue
                sc_ = float(getattr(n, "score", 0.0) or 0.0)
                nodes.append((sc_, n))
            nodes.sort(key=lambda x: -x[0])
            kept = [(s, n) for s, n in nodes if s >= self.min_score][: self.top]
            meta["per_compound"].append(
                dict(compound_id=cid, n_nodes_total=len(nodes), n_kept=len(kept))
            )
            for sc_, n in kept:
                try:
                    msmi = Chem.MolToSmiles(n.mol)
                    ikey = (
                        Chem.MolToInchiKey(n.mol)
                        if hasattr(Chem, "MolToInchiKey")
                        else ""
                    )
                except Exception:  # noqa: BLE001
                    continue
                rule = getattr(n, "rule", None)
                rname = getattr(rule, "name", "") if rule is not None else ""
                pathway = getattr(n, "pathway", "") or ""
                metabolites.append(
                    dict(
                        compound_id=cid,
                        metabolite_smiles=msmi,
                        metabolite_inchikey=ikey,
                        name="",
                        reaction_type=(rname or pathway or "sygma_rule")[:120],
                        enzymes=self._enzymes(rname, pathway),
                        biosystem="human",
                        source=self.name,
                        provenance_url="https://doi.org/10.1186/1758-2946-1-3",
                    )
                )
        meta["elapsed_s"] = round(time.time() - t0, 1)
        self.log(
            "%d 个分子 -> %d 个代谢产物（%s）"
            % (
                len(compounds),
                len(metabolites),
                "、".join(
                    "%s:%d/%d" % (d["compound_id"], d["n_kept"], d["n_nodes_total"])
                    for d in meta["per_compound"][:4]
                ),
            )
        )
        if meta["errors"]:
            self.log("错误 %d 条" % len(meta["errors"]))
        return AdapterResult([], metabolites, meta)

    @staticmethod
    def _enzymes(rname, pathway):
        """从规则名/通路名里抽酶名（SyGMa 规则名形如 CYP_1A2_...）。"""
        txt = ("%s %s" % (rname, pathway)).upper()
        hits = []
        for e in (
            "CYP1A2",
            "CYP2A6",
            "CYP2B6",
            "CYP2C8",
            "CYP2C9",
            "CYP2C19",
            "CYP2D6",
            "CYP2E1",
            "CYP3A4",
            "CYP3A5",
            "UGT",
            "SULT",
            "NAT",
            "GST",
            "FMO",
            "MAO",
            "ADH",
            "AO",
        ):
            if e.upper() in txt:
                hits.append(e)
        return ";".join(hits)
