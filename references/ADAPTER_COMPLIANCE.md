# 外部适配器合规审查（ADAPTER_COMPLIANCE）

> 对应处方：**P13（评审 §4-5）**。推广给研究生使用前，外部源 adapter 的 ToS 与自动访问合规**必须是显式审查项**。
> 本文件 2026-10-31 完成**逐站联网核查**（每条均附证据来源）；核查结果标注 ✅/⚠️/❌。
> 诚实声明：以下为对公开 ToS / 论文 / API 文档的核查结论，**不构成法律意见**；商业用途务必由机构法务最终确认。

## 1. 审查对象（7 个外部工具 adapter）
`adt/adapters/`：`admetlab3 / admet_ai / protox3 / vnn / xenosite / biotransformer / chembl`
（其中 chembl 无 key、xenosite 需人工回填、biotransformer 有速率限制——见 SKILL.md 已知限制）。

## 2. 审查维度（每项须给 ✅/⚠️/❌ + 证据）
| 维度 | 问题 |
|---|---|
| 自动访问授权 | ToS 是否允许脚本化/批量访问？是否需显式 API key / 书面授权？ |
| 速率与 robots | 已有退避是否合规？各站速率上限是否载于 ToS？ |
| 数据再分发 | 输出能否进入本 skill 的公开材料/论文？**OpenADMET = CC-BY-4.0；NPASS = CC-BY-NC（非商业）**；其余见逐站表 |
| 凭据存储 | 凭据是否对齐机构安全规范？明文落盘是否合规？ |
| 个人数据 | 是否触及任何个人数据/受控访问？ |

## 3. 逐站核验结论（2026-10-31 联网核查）

| 适配器 | 自动访问 | 许可 / 再分发 | 速率 | 证据 | 结论 |
|---|---|---|---|---|---|
| **admetlab3** (ADMETlab 3.0) | ✅ 显式允许脚本批量 | 免费、无需注册；论文 DOI 10.1093/nar/gkae236 | **≤5 req/s**（USAGE POLICY 明示） | admetlab3.scbdd.com/apis | ✅ 合规；现有 429 退避应改为 ≤5 req/s 节流 |
| **admet_ai** (ADMET-AI) | ⚠️ 形态依赖 | GitHub 代码 **MIT**（可本地 `pip install admet-ai`）；公共 web server 免费无登录（单次≤1000）；Neurosnap API 需 key+额度 | 本地无限制；Neurosnap 按 credits | Swanson et al. 2024, Bioinformatics, btae416, doi:10.1093/bioinformatics/btae416 | ⚠️ 默认走本地/公共 web server（✅）；Neurosnap API 需密钥（⚠️） |
| **protox3** (ProTox-3.0) | ✅ 提供 POST API | **CC-BY-NC**；免费、无需登录、学术/非商业 | **单 IP ≤250 次/天** | Banerjee et al. 2024, NAR, ProTox 3.0 (tox.charite.de/protox3?site=faq) | ✅ 自动访问允许（限 250/day）；⚠️ 商业需确认许可 |
| **vnn** (vNN-ADMET) | ⚠️ 无显式 API ToS | 免费开放 web server（美国政府/陆军 BHS-AI）；无禁止脚本条款，但结果经 email 链接返回 | 无公布硬限 | Schyman et al. 2017, Front Pharmacol, doi:10.3389/fphar.2017.00889, PMID 29255418 | ⚠️ 视作开放学术资源，谨慎批量；凭据本地 |
| **xenosite** (XenoSite, SFU) | ❌ 禁用/人工 | SFU 通用条款禁止对授权资源系统性/大量下载；程序化 API 为收费许可项 | — | SFU Fair Use / Terms（库资源许可优先） | ❌ 自动访问禁用，按人工流程（SKILL.md 已知限制） |
| **biotransformer** (BioTransformer 3.0) | ✅ 本地运行 | **GPL v2.1**（GitHub）/ bio.tools 标 LGPL-3.0；免费非商业，商业需书面许可；须引用 | 本地无限制；web server 有速率限制 | Wishart et al. 2019, J Cheminform, doi:10.1186/s13321-018-0324-5 | ✅ 本地 jar 合规；⚠️ 商业需作者授权 |
| **chembl** (ChEMBL) | ✅ EBI 公共 REST | 数据 **CC-BY-SA 4.0**；免费（含商业）；需 attribution | 无硬限，最佳实践 ~10 req/s、429 退避 | ebi.ac.uk/chembl/api/data；grokipedia/EMBL-EBI 政策 | ✅ 合规，需署名 + 派生数据共享相同条款 |

## 4. 处置规则（P13 验收）
- ❌ 项（xenosite）：该 adapter **禁用自动访问或降级为人工流程**；SKILL.md 已知限制已标注。
- ⚠️ 项（admet_ai/Neurosnap、protox3 商业、vnn、biotransformer 商业）：带显式合规声明进入，报告脚注引用本审查结论。
- ✅ 项（admetlab3、protox3 学术、biotransformer 本地、chembl）：自动访问合规，按各站速率上限节流。
- 凭据存储对齐机构安全规范（系统凭据库而非明文文件；仓内 `vnn_cred.json` 须 git-ignore）。
- 本文件作为**每次发布前的合规门禁之一**。

## 5. 已澄清的外部事实纠错（评审 editorial）
- **NPASS 许可纠正**：此前文档写"CC-BY-4.0（OpenADMET/NPASS）"有误——**NPASS 实为 CC-BY-NC（非商业）**（Bioregistry + NAR 2018 论文确认）；OpenADMET 系列才是 CC-BY-4.0。两者不可混写。
- **OpenADMET 持久化 DOI（U4，已核实可点击）**：
  - PXR blind challenge data: **https://doi.org/10.5281/zenodo.21617804**（CC BY 4.0）
  - ASAP-Polaris-OpenADMET blind challenge data: **https://doi.org/10.5281/zenodo.15582067**
  - ASAP-Polaris ligand pose PDBs: **https://doi.org/10.5281/zenodo.15320448**（CC BY 4.0）
- **Chow 检验年份纠正（U1）**：评审草稿的"Chow 1957"为**误引**；正确出处为 **Chow, G.C. (1960), "Tests of Equality Between Sets of Coefficients in Two Linear Regressions", Econometrica 28(3): 591–605**。本 skill 若引用结构断点检验须用 1960。

## 6. 待办（不臆造"已合规"）
- 商业用途逐项法务确认（protox3 / biotransformer / admet_ai-Neurosnap）。
- admetlab3 adapter 现有 429 退避逻辑改为显式 ≤5 req/s 节流（与官方 USAGE POLICY 对齐）。
- xenosite 维持人工流程，待获得正式许可后再评估自动访问。

## 7. 建议独立成短文（R33 / 评审 R2-5）

评审指出：本文件的**内容**已超出"一个 skill 的合规附录"的量级——它是"**多源 in silico
工具的许可与自动访问合规横评**"，且每条都带可点击证据。压在 skill 附件里会被埋掉。
建议独立成一篇**短方法学通讯 / 数据可用性短文**（4–6 页，无需新实验）：

- **拟题**：*Automated access and licensing compliance of public ADMET prediction services:
  a per-adapter audit for reproducible multi-source screening*
- **核心贡献（三条，均可独立核验）**：
  1. 7 个常用 ADMET 服务的**逐站**合规矩阵（自动访问授权 × 再分发许可 × 速率上限 × 凭据要求），每条附一手证据链接；
  2. 三类**易被误用**的许可陷阱：`CC-BY-NC` 被当成可商用（NPASS / ProTox）、`GPL` 派生边界
     （BioTransformer 本地运行 vs 分发）、"无显式 API ToS ≠ 允许脚本批量"（vNN）；
  3. **可执行的处置规则**：把许可等级编译成 4 档 profile 并在**适配器基类**强制执行
     （`adt/compliance.py` + `adt/adapters/base.py`），使"合规"从声明变成代码约束。
- **图表清单（现成，无需补做）**：逐站合规矩阵（本文 §3 表）；4 档 profile × 允许动作矩阵；
  一次越权调用的拦截与报错样例（`ComplianceError`）。
- **适投方向**：J Cheminform / JCIM 的 "data & software availability" 类短文、
  Digital Discovery 的 reproducibility 专栏、或作为主文（`references/POSITIONING.md`）的补充材料。
- **必须先声明的边界**：本文**不构成法律意见**，商业用途须由机构法务确认（见 §1 声明）。

## 8. badcase 5 原文锁定（R33 / 评审 R3-5）

评审要求：**badcase 5（PubChem 字段变更致立体丢失 + no-op 零对照对确定性模型退化）
必须原样保留在对外材料中，不得因"看起来像自家 bug"而删改或软化**。
理由是它同时证明了"故障注入能抓到真问题"与"作者不会把踩坑改写成一次通过"。

执行约定：
- `外部评审材料_v4.0-dev.md` 的 badcase 5 段落为**锁定文本**，后续版本只允许**追加**新证据，
  不允许重写既有叙述；如需更正事实，采用"原文 + [更正] 说明"的并列形式。
- 任何把该段改写成"首次即通过""未发生立体丢失"的版本视为违规。

