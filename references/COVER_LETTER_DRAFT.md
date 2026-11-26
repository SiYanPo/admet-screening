# Cover Letter 草稿（三版：J Cheminform / JCIM / Digital Discovery）

> **2026-11-24 更新**：prior-art 句已纳入 CADT / MIRAGE-DTA / NeuroBACE-ML / ADMET-EvO 四篇新逼近工作，见 `references/PRIOR_ART_UPDATE_2026-11-24_LIBRARY.md`。
> 占位符 `[...]` 需作者填。**投稿前必须**完成三件事：① Zenodo DOI 升级或明确披露 interim commitment；
> ② 若已做湿实验，补入 Stage 2 数据；③ 按目标刊格式压缩字数。

---

## 版本 A｜Journal of Cheminformatics（首选，methods + negative result）

Dear Editor,

We submit a Stage 1 Registered Report protocol and its preregistered decision analysis asking a
narrow but practical question: **when does admitting an evidence source into a molecular-property
combination help, and when does it hurt?** Multi-source ADMET prediction usually votes or weights
all available sources, implicitly assuming every source is admissible for the molecule and endpoint
at hand. We formalise an auditable, source-level admission layer that decides *before* combination,
attributes each decision, and prices abstention and error on one utility scale.

The contribution is deliberately not a new predictor. We test a frozen hypothesis (H1: positive
paired utility gain of full admission over naive voting on ≥2/3 endpoints at the reference cost
point) and report the **cost-dependent failure boundary** as a first-class output. Using exact
sign-flip permutation tests and Holm correction, H1 is not supported at the reference point, while
a pre-specified secondary hypothesis is strongly supported: the sign of the benefit flips between
c_abstain = 0.2 and 0.5. We further show that the value comes largely from abstention rather than
from admission itself — a result we consider more useful to the community than a positive headline.

We position the work explicitly against 2026 prior art. Sample-level confidence gating with an
applicability-domain abstention signal (CADT), reliability-aware evidence arbitration (MIRAGE-DTA),
reliability-aware screening (NeuroBACE-ML) and an evidence-gated self-evolving ADMET agent with a
hash-chained ledger and frozen recipes (ADMET-EvO) each cover one component; Honest ADMET, the
Trustworthy ADMET Benchmark, AdmitOR, SciForge and PACT cover others. None tests *source-level*
admission under a unified false-PASS/false-FAIL/abstain cost function with a quantified boundary. The protocol, frozen hypotheses, analysis plan,
estimand cards and machine-enforced release gates are public; a second, independently sourced DILI
cohort (FDA DILIrank 2.0, n=60, no InChIKey overlap with training data) provides external support
for the applicability-domain gate.

We believe the manuscript fits J Cheminformatics because it offers a falsifiable methodological
claim, a reusable decision framework, and an honest negative result with a quantitative boundary,
rather than another accuracy benchmark.

Sincerely, `[作者]` on behalf of all authors.

---

## 版本 B｜JCIM（更偏方法学/化学信息学）

Dear Editor,

We report a preregistered evaluation of **source-level evidence admission** for multi-source ADMET
decision-making. Unlike sample-level selective prediction, our admission unit is the *prediction
source* for a given chemical class and endpoint, and the decision is made before voting/BMA/stacking.
A unified cost triple (false PASS, false FAIL, abstention) allows the same question to be asked at
nine cost points with paired bootstrap intervals and exact sign-flip tests.

Key findings: (i) at the preregistered reference cost point the full admission layer does not
outperform naive voting on two of three endpoints; (ii) the benefit becomes significantly positive
when abstention is cheap (c_abstain ≤ 0.2, Δu up to +0.64 on DILI) and strongly negative when it is
expensive; (iii) confidence-only abstention captures most of the gain, so the extra admission
machinery is not justified at the reference point. We release the failure-boundary map as the
main citable output.

The work includes a provenance-aware source-independence audit (29 sources collapsed into 14
independent groups), an estimand-binding gate that mechanically blocks cross-dimensional claims,
and an external DILI cohort from FDA DILIrank 2.0 independent of TDC training data. Distinct from evidence-gated agents that accumulate verdicts in a hash-chained ledger
(ADMET-EvO), the unit of decision here is the prediction source and the output is a cost-dependent
boundary. All numbers are generated from committed scripts and hash-locked dependencies plus a
container digest.

Sincerely, `[作者]`.

---

## 版本 C｜Digital Discovery（更偏可复现/数据驱动决策）

Dear Editor,

We present a reproducible, decision-oriented framework for multi-source ADMET prediction in which
the unit of trust is the *evidence source*, not the individual molecule. The framework combines a
provenance-aware independence audit, an applicability-domain admission gate, a unified
abstention/error cost function, and machine-enforced claim governance (hash chains, release gates,
container and data manifests). We test its central hypothesis under preregistration and report the
cost region in which it fails as a quantitative, citable map.

The distinction from confidence-gated triage (CADT), evidence arbitration (MIRAGE-DTA) and
self-evolving evidence agents (ADMET-EvO) is the decision layer and its unit: we do not add another
model or diagnostic, we ask whether the diagnostics should change which *sources* are allowed to
vote, and at what cost. Across three endpoints and nine cost configurations, the sign of the
benefit flips at c_abstain ≈ 0.2–0.5; a compound-level bootstrap confirms the applicability-domain
gate outperforms confidence-only abstention at matched coverage on two of three endpoints.

All artefacts — frozen protocol, RFC 3161 timestamp, exact permutation tables, two figures,
independent FDA cohort, and container digest — are public and generated by scripts.

Sincerely, `[作者]`.
