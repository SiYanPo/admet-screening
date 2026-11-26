# 审稿人预演包（Rebuttal Pack v1，2026-11-23）

> 用法：投稿前把这份当"红队演练"。每条给出 ①最可能的攻击原话 ②我们的回应 ③证据（可直接粘进 response letter）
> ④若被追问的补做成本。**不写没有证据的回应**——那比不回应更糟。

---

## 攻击 1｜"你的显著性只是对随机种子稳健，不能外推到新化合物"

**回应**：完全同意，且我们在表里就印了这句。主表（`references/PAPER_TABLE2_MAIN_RESULTS.md`）
用的是配对单位=随机种子的精确符号翻转置换（2^20 全枚举），它回答的是"结论是否被重采样噪声制造"，
**不是**"能否外推到新化合物"。外推需要前瞻/外部队列，我们把它列为独立的、未完成的一步，
并在 `tools/publication_readiness.py` 的 B2 检查里显式标 GAP/PASS，而不是混在显著性里蒙过去。

**证据**：`references/PAPER_TABLE2_MAIN_RESULTS.md` 表头第三行；`out_sensitivity/table2_paired.csv`（逐行 n/Δ/IQR/p）。
**补做成本**：化合物级 bootstrap 需要 per-compound 预测长表（当前只有 7 个化合物的 merged 测量，n 不够）→ 需重跑预测管线，约 1 天。

---

## 攻击 2｜"只有 3 个端点，凭什么说失效边界"

**回应**：3 个端点是**预注册时冻结**的族（Holm m=3），不是事后挑的。我们另外登记了第 4 个端点
（caco2，回归型），并给它单独的量纲与判据（位移比 R + 符号一致率，不用翻转率），避免"混端点凑数"。
扩端点需要新的数据族与许可，已在路线图（K2）。

**证据**：`PREREG_STAGE1_PACKAGE.md` §5.1–5.2；`references/ENDPOINT_ESTIMAND_CARDS.yaml`（4 端点，含 caco2 的 REGRESSION_PROXY）；`adt/estimand.py` 的跨量纲自检 6/6。

---

## 攻击 3｜"既然 S3（仅置信度弃权）就够了，准入层是过度设计"

**回应**：**这正是我们的结论，而且是我们主动报的负结果。** 在 DILI 上 S3−S1 = +0.125
（p=9.5e-06），而 S4−S1 = +0.013（p=0.17）——准入层把弃权层已经拿到的收益吃掉了；
hERG/BBB 上 S4 显著更差（−0.197 / −0.223，Holm p=5.7e-06），且伴随过度弃权（覆盖 0.18/0.35）。
所以本文的贡献不是"我们又做了一个更好的组合器"，而是**用预注册的判据证明了这条路在
参考代价点下不通**，并把"哪里不通"量化成失效边界。

**证据**：`references/PAPER_TABLE2_MAIN_RESULTS.md` 九行全表；`out_keystone_v43/results.json` 的 `per_run`（2,700 行）；
**这条回应也是本文最强的卖点**——审稿人提出它，说明我们得把结论写得更靠前。

---

## 攻击 4｜"负结果有什么发表价值"

**回应**：三点：①这是**预注册**的负结果，按 COS/PLOS 的 RR 政策受保护，不属于"没做出来"；
②它阻止后续研究者在这条路上重复投入（这是可引用的资源）；③失效边界本身是方法学产出——
"准入层的代价随端点从 +0.013 到 −0.223"，比"我们又提升了 0.01 AUC"更有信息量。

**证据**：`PREREG_STAGE1_PACKAGE.md` §3（H1/H0 冻结）、§5.5（失败判据）；
`references/PREREG_ANCHORING_CHECKLIST.md` §4（失败即结论条款模板）；`PAPER_STAGE1_v4.28.md` 的 Anticipated contribution 段。

---

## 攻击 5｜"AD 阈值 0.35 是拍脑袋定的吧"

**回应**：是工程工作点，**不是**数据里的自然边界——我们两年前就这么写了，现在有两条独立实测：
①post-cutoff 分层显示 AUC 随 Tanimoto 平滑上升、0.35 处无跳变；②一维网格（6 档，真实 637 分子）
显示准确率最多变化 0.194（DILI），且变化主要来自覆盖子集改变（risk–coverage 权衡），
模块同时给出 `n_new_decided/n_lost_decided` 供拆分。
因此我们**拒绝**把它标成"已冻结"（G12 持续告警），并在预注册里把它作为**固定参数**而非"发现"。

**证据**：`references/THRESHOLD_REGISTRY.yaml` 的 `ad_anchor`（frozen=false + 两条实测 + 不冻结理由）；
`out_sensitivity/knn_threshold_sensitivity.json`；`SKILL.md` §04。

---

## 攻击 6｜"外部验证是不是同一批数据的重采样？"

**回应（2026-11-24 更新）**：我们提供两层外部证据，且明确区分它们：
① **ChEMBL 时间留出**（target CHEMBL240，`min_document_year=2023`，近重复排除 0.9，逐条记录
`max_tdc_tanimoto`）——同一数据族的时间外推，不当独立队列；
② **FDA DILIrank 2.0 独立队列**——说明书+文献因果标签（与 TDC 实验标签**异源**），按 InChIKey
排除与 TDC DILI 训练/测试集重叠后得 60 化合物（39 阳/21 阴）。参考 Morgan-RF 全队列 AUROC
0.722 [0.578, 0.848]；τ=0.35 准入子集 n=29，AUROC 0.863 [0.622, 1.000]。
**必须随表声明**：FDA 标签与 TDC 标签体系不同（DILI estimand=PARTIAL），只可比较决策排序与相对增益，
不得当临床 DILI 风险预测；参考模型非 S4 全管线。

**证据**：`out_ext/external/herg_holdout.json`（design 字段原文：`时间留出外源集（不是前瞻预注册）`）；
`out_ext/external/DILIrank2_independent_DILI.csv`、`DILIrank2_provenance.json`、
`references/EXTERNAL_COHORT2_VALIDATION.md`；`references/TEMPORAL_HOLDOUT_DISCIPLINE.md`。

---

## 攻击 7｜"回归端点的 TOST 结论可信吗？"

**回应**：**不可信，我们已量化并降级。** 由已存 bootstrap CI 代数重算（不重训，避免种子噪声），
margin ∈ {0.3,…,0.7} × 3 端点 × 4 模型共 12 格，**11 格判定翻转**。
因此登记表把 `ratio_margin_tost` 标为 `inferential_use: forbidden_pending_preregistration`：
先预注册 margin，再谈判定；在此之前任何 R 类结论都不得引用。

**证据**：`out_sensitivity/ratio_margin_sensitivity.json`；`references/THRESHOLD_REGISTRY.yaml` 的 `ratio_margin_tost`；
生成器 `tools/ratio_margin_sensitivity.py`（判据与 `adt.mmp.analyze_regression` 同源）。

---

## 攻击 8｜"代码和数据能复现吗？"

**回应**：能给出机器可核验的指纹，而不是"我们尽力了"：
容器 digest（基础镜像按 digest 钉死 + 容器内 7 项自检数值与宿主逐位一致）、
`requirements.lock` 精确钉版、`DATA_MANIFEST.json`（17 资产 SHA256 + 来源 + 许可 + core 模式排除 1.2 GB）、
`tools/verify_all.py` 一条命令复现、78 条命令的 layer/evidence_role 契约（`ADT_ENFORCE_ROLES=1` fail-closed）。

**预注册锚定（2026-11-24 状态，必须如实写）**：OSF 因平台侧 `prevent_project_creation` 三次实测 405，
未使用其失效 URL 假装锚定；Zenodo 因邮箱确认未达而暂缓。我们改用**公开承诺文本 +
RFC3161 第三方时间戳**：公开 URL `https://dpaste.com/9TRMMK4Z5`（HTTP 200 复验、365 天保留），
协议 SHA256 `3399cdf5…`，freeTSA serial `0x0A6E1091`（2026-11-23 08:23:52 GMT）。
`prereg-status` rc=0、`claim_allowed=True`、`post_hoc_anchor=False`。
**边界**：这是 interim public commitment，不是 DOI/注册号；材料只能写"公开承诺 + 时间戳"，
不得写"registered on OSF/Zenodo"。Zenodo 恢复后按 `tools/zenodo_deposit.py` 升级为多锚链。

**证据**：`DOCKER_DIGEST`；`DATA_MANIFEST.json`；`references/EVIDENCE_DAG.yaml`（78 节点/50 边，生成式）；
`anchors/PUBLIC_COMMITMENT.md`；`anchors/tsa/README.md`；
`python -m adt.cli release-check` → PASS（G1–G14）。

---

## 攻击 9｜"CADT/ADMET-EvO 已经做了置信度弃权、适用性域、证据账本和冻结——你还剩什么？"

**回应**：这是本轮最真实的攻击，我们主动把它写进来。CADT（Pharmaceuticals 2026, 10.3390/ph19091445）
的结论句与我们方向一致："uncertainty and applicability-domain terms act as an abstention mechanism
rather than an accuracy gain, and that abstention is not free"；ADMET-EvO（arXiv:2609.10121）确实
实现了证据门、hash 链账本、SHA-256 冻结、≥5 seed held-out 与 source-held-out。我们**不声称**这些机制首创。
差异在两处、且是 kind 而非 degree：① 准入单位——它们的门控/仲裁作用于样本、化合物-靶标对或 agent 行动，
我们的准入单位是"预测源在某一化学类/端点上的资格"，判定先于 voting/BMA/stacking；② 输出——它们报告
排序/校准/命中保持，我们报告的是在统一三价代价下**净收益符号何时翻转**的边界（cABS 0.2→0.5），
并以精确符号翻转置换 + Holm 给出 p。简言之：它们证明"弃权不免费"，我们量化"准入在什么代价上开始付费更多"。

**证据**：`references/PRIOR_ART_UPDATE_2026-11-24_LIBRARY.md` 逐篇差异表；
`references/PAPER_TABLE_H2_COST_SWEEP.md`（81 行代价扫描）；`references/PAPER_TABLE2_MAIN_RESULTS.md`。
**代价**：若审稿人要求把 source-level 换成 sample-level 以对齐 CADT，则本文 novelty 消失——因此这一区分必须在
Introduction 第一段就写明，不能留到 discussion。

---

## 使用建议

1. 投稿前逐条自问"如果我是审稿人，看到这句会怎么打"——本文件只是起点。
2. 每条回应只引用**能重算的东西**（文件 + 命令 + 数字），不引用"我们认为"。
3. 攻击 3 一定要写进 Introduction 的贡献段：**主动承认简单方案更好**，比被审稿人指出强十倍。
