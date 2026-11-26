# 文献 → 模块映射表（v3.0.0 学术升级的依据）

> 本文件回答一个审稿人必问的问题：**你这一层为什么这么做？**
> 每一条都给出"文献 → 被升级的对象 → 改成了什么 → 预期效果"。
> 20 篇文献的真实性（DOI/卷页）核对记录见 `admet-pipeline/参考文献合集_SCI升级_20篇.md`。

---

## 一、优先级排序依据（为什么按这个顺序做）

排序原则是**"错误的代价 × 可修复性"**，不是"文献影响因子"：

| 序 | 判据 | 理由 |
|---|---|---|
| 1 | **纠正错误知识** | 错的知识比缺的知识危险：它会让后续所有推理朝错误方向自信前进。项目里只有 G2（Peng 2023）属于这一类 |
| 2 | **方法学硬伤** | 会让结论在审稿阶段直接被拒，但改写成本低（B2 校准、F3 金标准） |
| 3 | **治理层理论锚点** | 决定"这套东西能不能被称为方法"而非"脚本集合"（A2/A3/F2） |
| 4 | **公式与假设的可辩护性** | 决定 PBPK 章节能否过审（D1–D4、G1、E1） |
| 5 | **不确定性量化** | 提升上限，但不影响结论成立与否（B1、C1/C2） |
| 6 | **报告规范与透明度** | 发表门槛项，可后置但不能缺（F1/F4/F5） |

一句话：**先保证"没说错"，再保证"说得清"，最后才是"说得漂亮"。**

---

## 二、逐条映射

### U1 · G2 Peng 2023 → `transport`（先验纠错）

| 项 | 内容 |
|---|---|
| 文献 | Peng T, et al. RSC Med Chem. 2023;14(5):890–898. DOI: 10.1039/D3MD00078H |
| 被升级对象 | `references/transporter_priors.yaml` 的 OATP2B1 条目 + `adt/transport.py` |
| 改动 | ① 新增 `moiety_rules`：芳环上带糖 → 降一档（direct）；糖在脂肪碳 → 弱降半档（extrapolated）；② `moiety_flags()` 用 SMARTS 判定吡喃糖与芳氧苷；③ 输出 `plausibility_base / plausibility / adjust_reason / adjust_evidence`，任何改动可追溯；④ 档位**只降不升**、只作用于指定转运体 |
| 预期效果 | 把"糖苷=OATP2B1 底物"的默认假设降级为"待实测假设"。本项目 14 个王百合苷由 medium → low_to_medium（extrapolated），SGLT1/P-gp 档位不受影响 |
| 实测 | 异槲皮苷（3-O-糖）判 direct 下调；王百合苷 A 判 extrapolated；槲皮素苷元不触发糖苷规则 |

### U2 · B2 Van Calster 2019 → `calibration` + `benchmark`

| 项 | 内容 |
|---|---|
| 文献 | Van Calster B, et al. BMC Med. 2019;17:230. DOI: 10.1186/s12916-019-1466-7 |
| 被升级对象 | `adt/benchmark.py`（原来只报 AUROC/AUPRC） |
| 改动 | 新增 `adt/calibration.py`：Brier、Brier skill score、校准斜率/截距（logistic 重校准，IRLS）、O:E、ECE、Wilson CI 分箱表；`benchmark` 增 `cal_*` 列与 `calibration_table.csv`；**量纲门控**：unit 必须是概率型且值域 ⊂[0,1]，否则 `not_applicable` |
| 预期效果 | 概率端点的"0.7"不再被默认为"70%"。demo 数据集正好演示：AUROC 0.99（判别力极好）但 slope 2.86、O:E 0.70（校准很差）——判别力与校准必须分开报 |
| 实测 | 完美校准 slope=1.000/intercept=0.000/ECE=0.000；系统性低估 slope=0.833/intercept=+1.52/O:E=2.25 → poor |

### U3 · F3 TDC 2021 → `benchmark`（金标准与标准切分）

| 项 | 内容 |
|---|---|
| 文献 | Huang K, et al. Therapeutics Data Commons. NeurIPS 2021 Datasets & Benchmarks. arXiv:2102.09548 |
| 被升级对象 | `adt/benchmark.py` 的簇定义与真值来源 |
| 改动 | ① `scaffold_clusters()` Bemis-Murcko 骨架聚类；② `scaffold_split()` 整簇切分（容量约束 + 空集时整簇迁移并声明）；③ `load_tdc_truth()` 读 TDC 格式（Drug_ID/Y 自动识别）；④ CLI `--scaffold-from/--split/--truth-format tdc` |
| 预期效果 | 用随机切分评估同系类似物会因类似物泄漏虚高 AUROC 0.1–0.3；本改动使泄漏在结构上不可能 |
| **实测关键发现** | 14 个王百合苷经 Murcko 骨架化只剩 **2 个骨架** → `degenerate=True`，明确报告"本批不能做三集验证，只能用外部化学类做外部验证"。这是本项目第一次用代码证明"这批分子是同系类似物" |

### U4 · A2 OECD QAF 2023 + A3 Hanser 2016 → `governance` + `qaf` CLI

| 项 | 内容 |
|---|---|
| 文献 | OECD Series on Testing and Assessment No.386, 2023, DOI: 10.1787/d96118f6-en；Hanser T, et al. SAR QSAR Environ Res. 2016;27(11):865–881, DOI: 10.1080/1062936X.2016.1250229 |
| 被升级对象 | `tier`（原为纯工程规则）与 `coverage/reliability` 的分层语义 |
| 改动 | `adt/governance.py`：① `qaf_assess()` 逐条判定 QAF 四原则（satisfied/partial/not_met + 证据 + 缺口）；② `ad_levels()` 输出 Hanser 三层 AD（model/prediction/decision）；③ `qaf` 子命令产出 `qaf_compliance.csv` / `ad_levels.csv` |
| 预期效果 | `tier` 从"我定的规则"升级为"QAF fit-for-purpose 的落地"；论文里可用 A2+A3 组织架构图 |
| 实测 | 14 分子：P1 satisfied（修完 35 个端点的单位缺口后）、P2 satisfied、**P3 not_met（无独立基准）**、P4 partial（T2）；三层 AD：model 2 in_domain/1 limited、prediction 9 limited/5 out_of_domain、decision partial |

### U5 · F2 PROBAST 2019 → `tier`

| 项 | 内容 |
|---|---|
| 文献 | Wolff RF, et al. Ann Intern Med. 2019;170(1):51–58. DOI: 10.7326/M18-1376 |
| 被升级对象 | `tiers.assign()` 与 `tier.csv` |
| 改动 | `risk_of_bias()` 四域（参与者/预测因子/结局/分析）；`tier` 新增 `--compounds`（算骨架簇数）并写入 `risk_of_bias` 列；**rob=high 时不得升 T3**，缺口里明写原因 |
| 预期效果 | 把"自评偏倚风险"变成升档硬门槛，堵住"数据不够却写发表级结论" |
| 实测 | 14 分子整体 HIGH（D3 无实测、D4 无基准无校准）→ 请求 T3 被拒 |

### U6 · A1 Sahigara 2012 → `sensitize --ad`

| 项 | 内容 |
|---|---|
| 文献 | Sahigara F, et al. Molecules. 2012;17(5):4791–4810. DOI: 10.3390/molecules17054791 |
| 被升级对象 | `adt/sensitivity.py`（原来只摄动阈值） |
| 改动 | `ad_analyze()`：AD 的两个旋钮（票数门控 require_sources 1/2/3、域外处置 strict/loose）网格化，分别统计**翻转 / 新增判定 / 丢失判定** |
| 预期效果 | AD 阈值不再被当常数；"放松 AD 会多出多少结论"成为可报的数字 |
| 实测（并抓到 bug） | 14 分子：require=1 会**新增 95 个判定**（基数只有 9）；require=3 **丢失全部 9 个**。这直接暴露 `reliability.py` 单位异构分支绕过 `require_sources` 门控的缺陷（v3.0.0 已修） |

### U7 · D3 Pang & Rowland 1977 → `pbpk`

| 项 | 内容 |
|---|---|
| 文献 | Pang KS, Rowland M. J Pharmacokinet Biopharm. 1977;5(6):625–653. DOI: 10.1007/BF01059688 |
| 被升级对象 | `Eh` 公式的"注释级"自校验 |
| 改动 | `eh_well_stirred()` + `well_stirred_selfcheck()`：fu=1&CLint=Qh→0.500、fu=0.5&CLint=2Qh→0.500、fu=0→∞→1.0，四个解析解写成**可执行断言**；`pbpk` 运行时打印 PASS/FAIL |
| 预期效果 | C81 那类"fu 乘错位置"的错误再也过不去（错误实现会给 0.667 而不是 0.5，断言有区分力） |

### U8 · D4 Obach 2011 → `pbpk.ivive_assumptions()`

| 项 | 内容 |
|---|---|
| 文献 | Obach RS. Curr Top Med Chem. 2011;11(4):450–466. DOI: 10.2174/156802611794480873 |
| 被升级对象 | CLint → 肝清除的隐式缩放 |
| 改动 | 显式列出 MPPGL/肝重/fu_mic/血浆比/Qh 五项假设（含"未实测→假定 1.0"的警示），给出 CLint_scaled→CLint_b→Eh→CLh 全链与 ±2× 敏感性；`pbpk_academic.csv` 落盘 |
| 预期效果 | 审稿人问"你的 IVIVE 假设是什么"时有表可查；fu_mic 未实测这一**最可能低估 CLint** 的环节被写在明面上 |

### U9 · D1 FDA 2018 + D2 EMA 2018 → `pbpk.qualification_statement()`

| 项 | 内容 |
|---|---|
| 文献 | FDA *PBPK Analyses — Format and Content*, Final, Aug 2018；EMA/CHMP/458101/2016, effective 2019-07-01 |
| 被升级对象 | PBPK 的用途声明与报告结构 |
| 改动 | 七段声明：预期用途（"不用于剂量选择/DDI 豁免/替代临床 PK"）、平台资格（未经 qualification）、验证（三项内部校验做过、外部验证未做）、敏感性、预测性能（不可评估）、局限、EMA 报告 7 段清单 |
| 预期效果 | 杜绝"用自建 12 状态模型暗示 regulator-grade"的过度声称 |

### U10 · G1 Fagerholm 2008 → `pbpk.ehr_prerequisites()`

| 项 | 内容 |
|---|---|
| 文献 | Fagerholm U. J Pharm Pharmacol. 2008;60(5):535–542. DOI: 10.1211/jpp.60.5.0001 |
| 被升级对象 | `--ehr-scan` 的边界扫描（原为纯参数网格） |
| 改动 | 三条机制前提（低代谢提取 Eh<0.30、中等以上渗透性、主动转运参与）+ 一条信息项（MW 阈值不成立，**不计分**）；输出 plausible/uncertain/unlikely |
| 预期效果 | EHR 从"参数随便扫"变成"先问这个分子有没有资格谈 EHR" |
| 实测 | 14 个糖苷全部 **uncertain（2/4）**：低清除 ✓、转运体 ✓、但 clogp −2.2~−1.3（极性过大）✗ → EHR 只能作上界，不能当预测 |

### U11 · E1 Li 2019 CiPA → `pbpk.herg_evidence_route()`

| 项 | 内容 |
|---|---|
| 文献 | Li Z, et al. Clin Pharmacol Ther. 2019;105(2):466–475. PMID: 30151907 |
| 被升级对象 | hERG 安全裕度段的证据路线 |
| 改动 | 声明当前为 `single_channel_ic50_anchor`，写出局限（无法区分代偿性延长；糖苷可能激动/部分阻断）、CiPA 路线（hERG+Na_v1.5+Ca_v1.2→ORd 模型）、升级所需数据 |
| 预期效果 | "只看 hERG IC50"被显式标为简化路线，与 C84/C85 的"只报档位"形成闭环 |

### U12 · B1 Norinder 2014 → `conformal`

| 项 | 内容 |
|---|---|
| 文献 | Norinder U, et al. J Chem Inf Model. 2014;54(6):1596–1603. DOI: 10.1021/ci5001168 |
| 被升级对象 | 点估计 + 三态（缺区间） |
| 改动 | `adt/conformal.py`：split conformal，q=第 ceil((n+1)(1−α)) 个绝对残差；n 太小时给 ±∞ 而不是编窄区间；目标分子若也在校准集则标 `self_calibrated`（不参与覆盖率统计） |
| 预期效果 | 输出"ŷ ± q（80% 覆盖，n_cal=…）"，比"±20% 经验值"有统计依据 |
| 纪律 | 经验覆盖率是**构造保证**不是验证；只保证边际覆盖，不保证逐分子覆盖 |

### U13 · C1 Derringer-Suich 1980 + C2 Wager 2010 → `desirability`

| 项 | 内容 |
|---|---|
| 文献 | Derringer G, Suich R. J Qual Technol. 1980;12(4):214–219；Wager TT, et al. ACS Chem Neurosci. 2010;1(6):435–449. DOI: 10.1021/cn100008c |
| 被升级对象 | 原来的等权几何平均（无出处） |
| 改动 | `_geo(vals, weights)` 实现加权几何平均 D=(∏d^w)^(1/Σw)，w 从规则 `weight` 读（默认 1.0 → 旧行为不变）；`references/desirability_method.md` 说明"w 是指数不是线性系数"、"任一 d=0 则 D=0"、何时不能用 |
| 预期效果 | "为什么用几何平均"从经验变为可引用；同时保留"不能有致命短板"的数学性质 |

### U14 · F1 TRIPOD+AI 2024 → `reporting`

| 项 | 内容 |
|---|---|
| 文献 | Collins GS, et al. BMJ. 2024;385:e078378. DOI: 10.1136/bmj-2023-078378 |
| 被升级对象 | `report`（原来只有结论段） |
| 改动 | `tripod_checklist()` 16 条分节自查表（标题/背景/目标/数据来源/对象/结局/预测因子/样本量/缺失/开发/判别力/校准/外部验证/亚组/输出/可得性），每条给 status+证据+缺口 |
| 预期效果 | 论文 Methods/Results 可直接按表组织；审稿人问"你报了校准吗"时有明确答案 |
| 实测 | 14 分子：满足 11 / 部分 2 / **未达 3（判别力、校准、外部验证）**——正是项目真实状态 |

### U15 · F5 Mitchell 2019 → model card

| 项 | 内容 |
|---|---|
| 文献 | Mitchell M, et al. FAT\* '19, pp.220–229. DOI: 10.1145/3287560.3287596 |
| 被升级对象 | 8 个预测源的"能不能信"（原为口头经验） |
| 改动 | `references/source_cards.yaml` 逐源登记：预期用途、模型类型、训练数据（未披露就写 not_disclosed）、适用域、**已知失效（带案例编号）**、版本追踪、限流、接入方式、证据等级；`reporting` 渲染 csv + markdown |
| 预期效果 | 透明度项从"我们很小心"变成"这是 8 张卡"；同时把已知坑（DrugBank 是百分位、ProTox Probability 不是阳性概率、vNN 类别需 class_map）固化在源头 |

### U16 · F4 FAIR 2016 → FAIR 映射

| 项 | 内容 |
|---|---|
| 文献 | Wilkinson MD, et al. Sci Data. 2016;3:160018. DOI: 10.1038/sdata.2016.18 |
| 被升级对象 | provenance/manifest/ledger 的"为什么这么做" |
| 改动 | `fair_mapping()` 把 F1–F4/A1–A2/I1–I3/R1.1–R1.3 共 13 条映射到具体产物（inchikey+provenance_url / schema / source_version / registry / aliases+unit_for / manifest+ledger / QAF+TRIPOD+PROBAST），逐条给 status |
| 预期效果 | 论文 Data Availability 段可直接引用；"可复现"从形容词变成条目对照 |

---

## 三、被文献**纠正**的一个既有实现（不是新增，是改错）

`reliability.py` 的"跨源单位异构 → class_map 投射"分支，原先在投射方向一致后**直接落 PASS 并 continue**，绕过了下方的 `require_sources` 门控。
后果：把 require_sources 调到 3，MMP 的 9 个 PASS 依然是 PASS——"两票半"原则在异构单位端点上完全失效。

这一缺陷是在 U6（AD 阈值摄动）跑到 require=3 时"翻转数为 0"才暴露的：
**理论上必须翻转，实际没翻 → 说明门控没生效**。
修复后同一实验给出 require=3 翻转 9/9，并成为论文里"AD 阈值敏感性"的核心证据。

教训（已写入案例库）：**敏感性分析不只是给结论加误差棒，它还是门控接线是否正确的探针。**

---

## 四、v3.1.0 新增文献（工作包 A–K）

> 这一层的目标不是"再加几个端点"，而是把"证据准入"从工程约束提升为**可检验、可比较、可证伪的方法学命题**。
> 与 09_reliability_landscape.md 的分工表配套阅读。

| 文献 | 模块（工作包） | 改动 | 预期效果 |
|---|---|---|---|
| OneADMET, JMC 2026（多平台数据重叠审计） | independence（A） | 用 Spearman/Fleiss κ 量化同组源冗余；ρ≥0.90 降半票；负相关标 sign_conflict | 把"多平台≠多来源"从审计发现变成**计票规则的设计原则** |
| Parrondo-Pizarro et al., J Cheminform 2025（ADME 数据错位/不一致） | failure_modes（J）、单位守卫 | 新增 unit_isomerism/version_drift 等 7 类不变量检测 | 数据不一致从"事后发现"变成"入口拦截" |
| **Jeffreys 1946 / Agresti & Coull 1998**（伪计数平滑） | independence（A） | `u(k)=(err_k+0.5)/(n_k+1)`，vote_confidence=1−u；n<5 标 insufficient | 公式的真实出处；n 小时避免 0/1 极端估计 |
| Clark 2014（Clark RD et al., J Cheminform 2014;6:34, doi:10.1186/1758-2946-6-34） | independence（A） | **合法次级引用**：协议 step 7 用「tally+1 / error+0.5」连续性修正 = 本式 `(err+0.5)/(n+1)`；但其 headline 方法是 beta-binomial 拟合 `u(k)=ER·f(k)/g(k)`，本包**未实现**（C4 已查原文核实，2026-11-03） | 引用 laundering 已消除：公式起源仍归 Jeffreys 1946 / Agresti & Coull 1998，Clark 2014 作次级支撑，不得声称"实现 Clark 方法" |
| Fleiss 1971（多评分者 κ） | independence（A） | 组内一致性 κ，与 Spearman 并列 | 多源一致性有标准统计量，不再只靠阈值 |
| Vickers & Elkin 2006（决策曲线） | decision_value（D） | 净收益曲线 + 预算三策略期望效用 | UNDETERMINED 获得**决策论**而非仅认识论的辩护 |
| GRADE Guidelines 30 | certainty（I） | 三态 → 5 档确定性修饰符（可解决/不可解决/需实验） | 与循证医学/毒理学的证据分级语言可互操作 |
| OpenADMET blind challenges 2026 | external / baseline（G，v3.2.0） | `assets/external/openadmet/` 随包分发（CC-BY-4.0，持久化 DOI 见 SKILL.md U4：zenodo.21617804/15582067/15320448；train 5,326 / test 2,282 × 9 终点）；`external` 转契约表，`baseline` 训练 RDKit/Morgan Ridge 预测 test | 真实前瞻性基准：RDKit AUROC 0.656 / Morgan 0.730；不再只是协议 |
| NPASS 3.0 三工具基准 2026 | external / baseline（B，v3.2.0） | `assets/external/npass/` 随包分发官方 curated 子集（1,307 rat-LD50 + 76 ADME，许可 CC-BY-NC 非商业，非此前误写的 CC-BY-4.0）；`examples/extract_npass.py` 可复现 | 天然产物毒性基准：RDKit AUROC 0.660 [0.595–0.720]；评审提到的 201,905 三工具表不在官方下载包，未分发 |
| Honest ADMET 2026 | selective（H） | risk–coverage；结构性弃权 vs conformal 宽度/方差；分布偏移子集 | 证明"弃权应由证据准入驱动，而非单一模型不确定性" |
| TOXTRUST / DST | dst（E） | Dempster/Yager 组合；all-in vs 准入；统计过度裁决 | 与证据组合传统明确分工：**准入是组合的前置层** |
| Sahigara 2012（AD 阈值摄动） | sensitize --ad（已有） | 保留 | AD 旋钮是门控接线的探针 |

### 4.1 这一层新增的"可证伪命题"

1. **P1（独立性）**：同组源的正相关越高，其"第二票"的增量信息越少；ρ≥0.90 时两票的有效票应 <1.5。
   - 可证伪：若在某个端点上 ρ≥0.90 但两源对真值的错误率显著不同，则降权会损失信息。
2. **P2（弃权）**：结构性弃权的 risk–coverage 曲线在分布偏移子集上应比分数型弃权退化更慢。
   - 可证伪：若 conformal 宽度的 AURC 在所有端点上都不劣于结构性弃权，则本框架的弃权层无增量价值。
3. **P3（决策）**：固定预算下，admission 策略的期望效用应不低于 vote_all 与 random。
   - 可证伪：若在真实真值上 admission 的 EU 更低，则"准入更划算"不成立。
4. **P4（结构）**：结构扰动的位移/源间分歧比在部分端点上应 ≥0.5（说明源间分歧含结构伪影）。
   - 可证伪：若所有端点的 ratio 都 <<0.5，则 Gate 0 只是工程卫生，不是方法学前提。
5. **P5（组合）**：DST 在源共享训练生态时会把相关证据当独立，产生"判死但框架弃权"的过度裁决。
   - 可证伪：若 DST 的过度裁决数为 0，则"准入是组合前置层"的论证不成立。

> 这五条就是论文的"结果"骨架：每条对应一个 `adt` 子命令与一张可复现的表。
