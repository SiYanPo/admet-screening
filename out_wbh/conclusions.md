# 结论段（自动生成，措辞已按 05_qa_gates §12 封顶）

> 判据版本 manifest_sha1=3ead9793f2e4（预注册，改动阈值后本段需重出）

> 本段不含任何超出 allowed_statement 模板的句子；
> 禁止的表述（ΔG→Kd、人体剂量推断、定论词）见 05_qa_gates §12。

## WBLG-A
- 适用域/真值参照 16 个（不裁决，仅报告）：chembl_admet_assay_count、chembl_max_tanimoto、chembl_neighbors_t40、chembl_neighbors_t70、cyp1a2_inhibition、cyp2c19_inhibition 等 16 个
- **mmp**（PASS）：2 个独立方法组经**单位投射（class_map）**后方向一致指向 PASS（非原始数值共识）
- **单组证据 8 项（不作判决，仅作参照）**：ames=0.0 class（neighbor_qsar）；caco2_papp_ab=-6.5675 log10(cm/s)（descriptor_ml）；carcinogenicity=0.2219 probability（descriptor_ml）；clint_microsome=25.8074 uL/min/mg（descriptor_ml）；nr_ar_lbd=0.5272 probability（descriptor_ml）；ppb_fu=40.9803 percent（descriptor_ml） 等 8 项
- 未判定端点 10 个：
  - ames：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - caco2_papp_ab：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - carcinogenicity：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - clint_microsome：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - dili：逐源复核适用域；必要时补实测，禁止取平均
  - herg：补概率输出或补实测；当前只能作定性参照
  - nr_ar_lbd：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - ppb_fu：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - sr_are：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - sr_p53：再找一个方法学独立的源，或补实测（同族源不叠加证据）

## WBLG-B
- 适用域/真值参照 16 个（不裁决，仅报告）：chembl_admet_assay_count、chembl_max_tanimoto、chembl_neighbors_t40、chembl_neighbors_t70、cyp1a2_inhibition、cyp2c19_inhibition 等 16 个
- **单组证据 10 项（不作判决，仅作参照）**：ames=0.0 class（neighbor_qsar）；caco2_papp_ab=-6.5247 log10(cm/s)（descriptor_ml）；carcinogenicity=0.3682 probability（descriptor_ml）；clint_microsome=43.5775 uL/min/mg（descriptor_ml）；dili=0.0 class（neighbor_qsar）；mmp=0.0509 probability（descriptor_ml） 等 10 项
- 未判定端点 11 个：
  - ames：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - caco2_papp_ab：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - carcinogenicity：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - clint_microsome：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - dili：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - herg：补概率输出或补实测；当前只能作定性参照
  - mmp：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - nr_ar_lbd：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - ppb_fu：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - sr_are：再找一个方法学独立的源，或补实测（同族源不叠加证据）
  - sr_p53：再找一个方法学独立的源，或补实测（同族源不叠加证据）

## 覆盖率（源 × 端点）
- **admet_ai**：覆盖 1.000（可判 24/24 行；可用端点 0/12；全零端点 0）
- **admetlab3**：覆盖 1.000（可判 18/18 行；可用端点 0/9；全零端点 0）
- **chembl**：覆盖 1.000（可判 8/8 行；可用端点 0/4；全零端点 0）
- **protox3**：覆盖 1.000（可判 6/6 行；可用端点 0/3；全零端点 0）
- **vnn_admet**：覆盖 0.200（可判 6/30 行；可用端点 0/15；全零端点 11）
- 全零端点（本批**无可判值**，不得读作阴性）：cyp1a2_inhibition、cyp2c19_inhibition、cyp2c9_inhibition、cyp2d6_inhibition、cyp3a4_inhibition、vnn_bbb、vnn_cytotoxicity、vnn_hlm、vnn_pgp_inhibitor、vnn_pgp_substrate

## 阈值稳健性（E3）
- 阈值来源：**文献起点值（threshold_source=literature）**，未经本批实测校准——本段所有 PASS/FAIL 均带此前提
- 全部阈值同时摄动时最大翻转率：0.00
- 最敏感端点：mmp（翻转率 0.00）
- threshold_critical（结论只能写作“待实测确认”）：无

## 未覆盖端点声明（强制 · 由 coverage_gate 自动生成）

> 本节由 `adt/coverage_gate.py` 读 `03_endpoint_rules.yaml` 自动生成；
> **任何 CYP / DDI / 安全性结论都必须连同本节一起引用**。
> 未覆盖 ≠ 阴性结论；`partially_covered` 仅表示有结构级预警，
> 仍无实验判据，不得据此下 PASS/FAIL。

- <!-- coverage:colloidal_aggregation --> **colloidal_aggregation**（胶体聚集导致的假阳性）：**部分覆盖（仅结构预警）**。
  - 现有覆盖：adt/interference.py::physical_interference（cLogP≥3 且芳香环≥2 → suspect；离线结构级预警，不投票、不判 FAIL）
  - 缺口：2026-11-11 补上结构级预警，但仍是 rule-based proxy：无浓度依赖、无去污剂对照、无 DLS/NMR 实测，不得据预警下「已聚集/已排除」结论
  - 所需证据：±0.01% Triton X-100 的活性/抑制曲线对比 + DLS 或 NMR 聚集证据
  - 约束：与 PAINS 互补，不是同一机制；命中 PAINS 不等于会发生聚集。
- <!-- coverage:cyp_induction --> **cyp_induction**（CYP 诱导（PXR / AhR / CAR））：**未覆盖**。
  - 缺口：ADMETlab 3.0 的 122 列里没有 CYP 诱导端点（02_source_registry.yaml 已实测登记）；
  - 所需证据：人肝细胞 PXR/AhR 报告基因或 mRNA/酶活诱导倍数（≥2 独立供体）
  - 约束：抑制 ≠ 诱导。只报 CYP 抑制就下「无 DDI 风险」结论属系统性漏洞。
- <!-- coverage:cyp_tdi --> **cyp_tdi**（CYP 时间依赖抑制（TDI / 机制性失活））：**未覆盖**。
  - 缺口：目前只在 04_decision_funnel.md 的湿实验清单（第二批）里，无任何计算实现
  - 所需证据：±NADPH 预孵 0/15/30 min 的 IC50 位移，或 kobs / k_inact / K_I
  - 约束：可逆抑制 IC50 不能替代 TDI；DDI 结论必须显式标注本项未覆盖。
- <!-- coverage:fluorescence_interference --> **fluorescence_interference**（荧光/发光检测干扰（自荧光、淬灭））：**部分覆盖（仅结构预警）**。
  - 现有覆盖：adt/interference.py::physical_interference（香豆素/色酮发色团、共轭双键≥4、多酚内滤 → suspect/possible；离线结构级预警）
  - 缺口：2026-11-11 补上发色团与共轭体系的结构预警，但无激发/发射光谱、无内滤定量，不得据预警给出实测光学结论
  - 所需证据：无酶/无靶对照下的化合物本底荧光与内滤效应测定
  - 约束：中药多酚/黄酮类高发；须用正交（非光学）读数复核。
- <!-- coverage:redox_cycling --> **redox_cycling**（氧化还原循环 / 成醌反应性）：**部分覆盖（仅结构预警）**。
  - 现有覆盖：04_decision_funnel.md Gate 3（定性提示）+ adt/transport.py 邻苯二酚化学型 + adt/interference.py::physical_interference（严格 SMARTS：邻苯二酚/对苯二酚/邻氨基酚；愈创木基不命中，C87 回归）
  - 缺口：2026-11-11 补齐成醌前体的严格结构识别，但只有定性提示/结构预警，无 GSH 加合物与过氧化氢定量；Gate 3 仍映射为「强制进第二批湿实验」而非数值端点
  - 所需证据：GSH 捕获 + HRMS/MS（± NADPH）、或 DCFH/过氧化氢定量

> 登记与产物一致性：改 `not_covered_endpoints` 后本段自动变化；
> 缺任一 `<!-- coverage:<id> -->` 标记即视为声明不完整（可用
> `python -m adt.claims_audit --coverage-declaration` 校验）。

