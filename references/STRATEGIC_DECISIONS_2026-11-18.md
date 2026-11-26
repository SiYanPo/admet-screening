# 学术策略裁决记录（2026-11-18）—— 用户授权下的专业判断

> 背景：第二轮整改报告 §3 列出 5 项"学术品味分歧（需用户/旗舰模型定夺）"。
> 用户 2026-11-18 明确授权："需要我裁决的问题请你通过专业的判断和分析哪个是最优解，确定后直接执行。"
> 本文件把 5 项逐项裁决、给出依据、并把裁决**落到材料**（不是停留在讨论）。
> 每项标注：裁决 / 依据 / 已执行动作 / 残余风险。

---

## 裁决 1：负结果是否重新包装为"正面贡献"？

**裁决：是——把 framing 定为"准入层失效边界的检测框架"，负结果作为该框架的一等实证输出，而非歉疚项。**

依据：
- 不是话术包装。对标证据链（POSITIONING_EVIDENCE §1）已确认创新点是**层级顺序 + 归因 + 同尺度代价**这一组合，而"能在什么代价区间/端点上证明准入层无效"正是该框架的核心可证伪输出。Hendrickx 2024 的 rejector 综述、Mora 2024 的 AD 误差分析都没有"检测准入层失效边界"这一用法。
- Nature Methods 类明确要求 novelty+validation+benchmarking（证据 §3）；把负结果组织成"检测框架 + 边界图"才同时满足 novelty 与诚实性，硬说"准入层有用"会被自己的 blacklist 当场证伪。
- 风险：若读成"又一个负面结果罗列"，novelty collapse。缓解：主图必须是**边界图**（代价区间 × 端点 × Δu 符号/显著性），负结果作为该图的点，而非正文olist。

已执行：
- 新建 `PAPER_STAGE1_v4.28.md`，标题与核心命题按此 framing 重写。
- `POSITIONING.md` 增裁决段，明确"失效边界检测框架"为对外唯一 framing。

残余风险：审稿人若坚持"检测框架本身也要证明有效"——已在 §局限声明中明确：框架输出的是"不可证明有益"的边界，不是"证明有害"的断言，后者需要 estimand 绑定后重做。

---

## 裁决 2：是否值得为 Registered Report 再投入？

**裁决：是——RR 是最高期望值路径，且其必要性来自一个被普遍误解的事实：致命伤是 estimand 未绑定，不是结果负。**

依据：
- 证据 §3：Locascio 2017 两阶段法、COS 期刊清单、Lange 2025（Stats Med，方法学论文本身以带时间戳注册为确证核心）一致表明——判据在结果前锁定后，负结果被制度保护，不再是"因为结果不好被拒"。
- 反向论证：若不走 RR，当前材料在 soundness 刊也只能以探索性研究发表（结论降级、引用衰减）；投入 RR 把同样的负结果升级为确证性，边际成本低（只需冻结命题/SAP + OSF 提交），期望收益显著。
- 唯一反对意见是"RR 不保证引用/声誉回报"——但这是所有发表决策共有的不确定性，不构成不做的理由；且本 skill 的核心命题若不以 RR 冻结，连"可被反驳"都做不到。

已执行：
- 产出 `PREREG_STAGE1_PACKAGE.md`：冻结命题 + 完整 SAP（estimand 绑定、主/次终点、分析集、多重比较、停止规则）+ OSF 提交字段清单 + 可直接点击的注册地址。
- 主文草稿 `PAPER_STAGE1_v4.28.md` 按 RR Stage 1 结构组织（引言/命题/方法/预注册声明），Stage 2 结果位留空并标注"须 OSF 锚定后解封"。

残余风险：RR 需外部真人在 OSF 提交（我无法代注册账号）——这是**执行交接**，不是决策未定；报告给出逐步填写说明与网址。

---

## 裁决 3：旗舰刊 vs 专门负结果刊？

**裁决：双轨——主线 Stage 1 RR 投"接受 RR 的 soundness 刊"（首选 PLOS ONE / Nature Human Behaviour / Elsevier RR 刊表）；负结果专集（PLOS ONE Missing Pieces / Scientific Reports null-findings）为 backup；Nature Methods 类旗舰方法刊本轮不投；JONNPR 仅末位备选。**

依据：
- 证据 §3：Nature Methods 明列 novelty+validation+benchmarking+general applicability，当前材料缺"前瞻 validation"这一项（G9 条件②未满足），硬投=高概率 desk reject。
- PLOS ONE / Scientific Reports / PeerJ 采用 soundness 模型（不因"结果负"拒稿），且 PLOS ONE 接受 RR——与裁决 2 的 RR 路径兼容，一次投稿同时解决"负结果保护"与"RR 确证"。
- 证据 §3 明确："Elsevier Journal of Negative Results" 不存在、专门负结果刊生态已萎缩，故不以专门刊为主线。

已执行：投稿策略表写入 `PAPER_STAGE1_v4.28.md` §投稿策略与 `PREREG_STAGE1_PACKAGE.md` §目标期刊。

残余风险：期刊政策随时变——投稿前须按报告中给的官方链接二次核对当前 RR 接收状态（链接在证据文件中）。

---

## 裁决 4：estimand 未绑定——致命缺陷还是诚实的探索性限制？

**裁决：对当前回溯性材料，它是推断性结论的致命缺陷（必须明确撤销相关结论的推断资格，不得含糊）；但在 RR 框架下，把它作为 Stage 1 必须冻结的核心元素，从而把探索性限制转为确证性前提。二者不是二选一，是时序上的两个阶段。**

依据：
- C01 撤回的第一手证据（RETRACTION_NOTE、out_ext/external/external_cuts_summary_v2.json）证明：estimand 未绑定时，AUC 不承载决策含义，任何"域外不可用/门有效"的结论都无推断资格——这不是措辞问题，是推断有效性问题，必须硬处理。
- Lange 2025（证据 §3）允许探索性方法学研究，但要求明确标注；故当前材料可保留为"探索性"——条件是**不得**再把已撤回结论写进对外材料，且必须显著标注探索性状态。
- 两条同时成立，不矛盾：承认当前是探索性（诚实） + 用 Stage 1 冻结 estimand 升级为确证（进步）。

已执行：
- G13 estimand 门（首轮已建）在 release-check 中为 blocker，保证未绑定结论不进对外材料。
- `PAPER_STAGE1_v4.28.md` §estimand 声明同时写"当前探索性状态"与"Stage 1 冻结清单"，不掩盖也不过度自贬。
- `PREREG_STAGE1_PACKAGE.md` 把 hERG/BBB/DILI/caco2 的 estimand 卡逐条列为 Stage 1 必须确认项。

残余风险：湿实验金标准（膜片钳 IC50、外源 DILI 标签）仍需真人——SAP 已写明"无金标准时的替代判定规则"（Dawid–Skene 无监督一致性 + 独立第二源），避免因为无金标准而无法开出 Stage 1。

---

## 裁决 5：JONNPR 等小众刊的索引/声望风险？

**裁决：不投。仅作为"所有主流 soundness 刊 + RR 路径均失败"时的末位备选，且材料中必须标注其索引/声望局限。**

依据：
- 证据 §3：JONNPR 非 Springer、西班牙 PROEDITIO 出版、收费 250€、索引与声望弱。对一个以"方法学严谨"为核心卖点的工作，投低索引刊会削弱而非增强主张可信度。
- 主流 soundness 刊（PLOS ONE / Sci Rep / PeerJ / BMC Res Notes）同样欢迎负结果且索引正常，没有理由先选小众刊。

已执行：投稿策略表把 JONNPR 列为末位备选并附局限标注。

残余风险：若所有主流路径失败，末位备选仍可保证"成果可发表"，不至于完全沉没——这是保留它而非删除的原因。

---

## 裁决后的整体状态

5 项分歧**全部裁决完毕并落到材料**（`PAPER_STAGE1_v4.28.md`、`PREREG_STAGE1_PACKAGE.md`、`POSITIONING.md`、`references/POSITIONING_EVIDENCE_2026-11-18.md`）。
不再有"待用户定夺"的悬置项。用户后续只需执行**操作交接**性质的两步：① OSF 实名注册并提交 Stage 1 包；② 安排外部真人复现/湿实验金标准——这些是决策已定后的执行，不再是判断未定。
