# 评审整改台账（2026-11-03，doc_revision 4.5）

> 来源：`admet-screening_同行评审报告_v1.md`（§2 问题清单 + §8 执行清单 + §1.5/§1.6 + §4）
> 原则：**每条都要能指到一个可执行命令或一个测试**。只有文字没有代码的，标 ⚠ 并说明原因。
> 验证入口（任何人可复跑）：
> ```bash
> python -m adt.redlines        # 红线接线普查 + 硬度
> python -m adt.flag_audit      # domain_flag 写入点白名单
> python -m adt.cli release-check   # G1–G12
> python -m pytest tests/       # 86 个测试文件（含 300+ 用例）
> ```

## 一、已确认问题（C1–C10）

| # | 问题 | 处理 | 证据（代码/测试） | 状态 |
|---|---|---|---|---|
| C1 | 红线 3/6/7/8/9 在生产路径**零调用点**；`red_lines_status()` 硬编码 `ok=True`；G8 验证自声明 | 新建 `adt/redlines.py`（AST 探测 + `REDLINE-<id>` 测试）；`report` 落盘前统一开火；`cmd_report` 接 `require_replay`/`admission`；G8 改读探测结果 | `adt/redlines.py`；`adt/cli.py::cmd_report`；`adt/release_gate.py::_check_red_lines`；`tests/test_redline_wiring.py`（12 例，subprocess 端到端） | ✅ |
| C2 | `bbb.postprocess` 裸 `except: pass` 静默吞错 | 失败留痕（`bbb_mechanism=layer_failed:<异常>`）+ 置信度降 low + reason 写明 | `adt/reliability.py`；`tests/test_c2_flag_audit.py::test_bbb_layer_failure_leaves_trace` | ✅ |
| C3 | `GATE_AUC_MIN=0.65` 约定值充当红线阈值，无 CI | 拆分 `GATE_AUC_WORKPOINT`（约定工作点）与红线判据（**必须给 95% CI，CI 上界须越过工作点**） | `adt/guards.py::gate_distribution_line(auc_ci=...)`；`tests/test_v44_guards.py::TestRedLine7CIRequirement`（5 例） | ✅ |
| C4 | 校准计票公式 `u=(err+.5)/(n+1)` 标成"Clark 2014" | 改标 Jeffreys/Laplace 伪计数平滑（Jeffreys 1946；Agresti & Coull 1998），Clark 2014 降为**启发来源**；8 处同步 | `adt/independence.py`、`SKILL.md`、`08_literature_map.md`、`09_reliability_landscape.md`、`U9` | ✅ |
| C5 | 21 个 `run_*.py` 零测试覆盖，其中 5 个在 `--help` 时**执行全流程**（`run_replication_pack` 会写挑战包） | 新建 `tests/test_experiment_scripts.py`（40 例：清单完整性/`--help` 无副作用/产物存在/数字进 registry）；给 5 个无 argparse 的脚本加 `--help` 早退 | `tests/test_experiment_scripts.py`；5 个脚本的 `__main__` 块 | ✅ |
| C6 | 首轮报告称"U9 阈值普查是空白模板"——**该判断错误**（表已填 24 项）；真缺陷是**代码常量一个都没登记** | 更正并新增 §B「代码常量普查」13 项；新增双向一致性测试（AST 扫常量 ↔ 文档必须有） | `references/U9_THRESHOLD_CENSUS.md` §B；`tests/test_threshold_census.py`（5 例） | ✅ |
| C7 | 归因计数三处互不相容（六类/七类/8 类+other） | 建唯一真源 `abstain_attrib.TAXONOMY`（弃权 8 + 源可靠性 1 = 九类，`other` 兜底不计）；SKILL.md 改为引用常量 | `adt/abstain_attrib.py`；`tests/test_c7_c9_taxonomy.py` | ✅ |
| C8 | `cli.py` 3.1k 行；`run_*.py` 与框架边界无文档 | README 增「框架入口 vs 一次性评测脚本」+ 已知技术债明示（拆分留 P2） | `README_CN.md` 新增章节 | ⚠ 边界已文档化，**物理拆分未做**（风险>收益，见 README） |
| C9 | 单位异构投射路径与同构中位数路径共享置信度档，报告模板会写成"中位 X" | `projection_used=True` 列 + `phrasing` 独立档 `projected`（禁用"中位/概率"表述） | `adt/reliability.py`；`adt/phrasing.py`；`adt/cli.py`（列 + 传参）；`tests/test_c7_c9_taxonomy.py` | ✅ |
| C10 | `version: 4.0-dev` 与 v4.1–v4.4 双轨，无法定位数字出处 | 三条轨（能力等级/材料修订 `doc_revision`/产物身份 `manifest_sha1`）+ 引用纪律 | `SKILL.md` 顶部「版本语义」 | ✅ |

## 二、外部评审（R-A / R-B / R-C / R-D）修订

| # | 要求 | 处理 | 证据 |
|---|---|---|---|
| R-A.1 | G8 不能只靠静态分析，要"注册表 + subprocess 集成测试"双轨 | 注册表在 `redlines.REGISTRY`；G8 需"静态调用点 ∧ `REDLINE-<id>` 测试"二者同时成立；端到端用例走 subprocess 断言**返回码与文件是否生成** | `adt/redlines.py`、`tests/test_redline_wiring.py` |
| R-A.2 | 5 个核心脚本的 smoke test 必须含**数值快照断言** | 不另造口径：核心产物必须被 `CLAIMS_REGISTRY` 引用，且 `verify_registry()` 通过（文件存在 + 字面量命中） | `tests/test_experiment_scripts.py::test_core_artifacts_covered_by_claims_registry` |
| R-B | OpenADMET 时序切分**不是前瞻** | 新增 `TEMPORAL_HOLDOUT_DISCIPLINE.md`（三类设计界定 + 排除清单 + 措辞对照表）；SKILL.md 条件② 增排除清单；当前状态改为"②未满足"；不再把时序切分叫前瞻 | `references/TEMPORAL_HOLDOUT_DISCIPLINE.md`；`SKILL.md` 条件② |
| R-C | P3.3 大模型交叉验证**暂缓** | 路线图写明三条反对理由（循环论证/不可审计/未校准）与唯一可接受形态（先作为源注册） | `references/COMMUNITY_BENCHMARK_ROADMAP.md` |
| R-D | `domain_flag` 写入点必须穷举并白名单 | 新建 `adt/flag_audit.py`：AST 扫 11 处写入点，逐点登记取值集合 + 正当性；新增未登记写入点即测试红 | `adt/flag_audit.py`；`tests/test_c2_flag_audit.py` |

## 三、P2 / P3 落地物

| 项 | 状态 | 物 |
|---|---|---|
| P2.1 预注册锚定执行包 | ✅ 清单 + **新增 `adt.cli prereg-status`** + **G9 升级**（去 `-dev` 必须 `claim_allowed=True`） | `references/PREREG_ANCHORING_CHECKLIST.md`；`adt/cli.py::cmd_prereg_status`；`adt/release_gate.py::_check_anchor` |
| P2.2 前瞻盲测 | ⚠ 纪律与验收标准已写死，**执行未做**（需新数据；见 §四黑榜） | `TEMPORAL_HOLDOUT_DISCIPLINE.md` §3 |
| P2.3 外部第二实现者 | ❌ 未做（需外部人力） | `replication/` 挑战包已存在 |
| P2.4 统计升级 | ✅ **Ames 差值 CI 已算**（0.0915，95%CI [0.0479, 0.1345]，不含 0）；四个 CI 工具函数 + 11 例测试；**gate AUC 的 CI 仍缺**（无 per-sample 分数，已登记 P2.4-b） | `adt/stats_ci.py`；`run_ames_release_ci.py`；`out_ext/tdc/ames_release_ci.json`；`STATISTICAL_POLICY.md` |
| P2.5 第二外源集 | ⚠ 规范已写（换源**且**换端点），执行未做 | `references/SECOND_EXTERNAL_SOURCE_SPEC.md` |
| P3.1 / P3.2 | ⚠ 路线图 + 启动条件（必须先有外部复现） | `references/COMMUNITY_BENCHMARK_ROADMAP.md` |
| P3.3 | ✅ 明确暂缓并给理由 | 同上 |

## 四、推广（§4）

| 项 | 状态 | 物 |
|---|---|---|
| 《10 分钟准入说明》 | ✅ | `references/ONBOARDING_10MIN.md`（含立体化学卡点、n 边界、三条禁令、T1/T2/T3 分级、红线硬度诚实声明） |
| 使用规范第 8–10 条 | ✅ | `SKILL.md` §高专业度使用规范（现十条） |
| 对外表述降级 | ✅ | `SKILL.md` §九条红线顶部"2026-11-03 更正"+ 硬度普查（7 hard / 1 soft / 1 conditional） |

## 五、测试与门禁（整改后实测）

```
pytest tests/                → 86 passed（**口径=86 个测试文件各跑一次**；用例总数远大于此，详见 pyproject.toml 只收集 test_smoke_pytest.py 这一事实）
                              其中 test_gate_mmp_v42.py 内含 5 个新增 P2.4-b 回归用例
python -m adt.redlines       → PASS，9/9 接线，7 hard / 1 soft / 1 conditional
python -m adt.flag_audit     → PASS，11 处写入点全部登记
python -m adt.cli release-check → PASS，G1–G12（G10 由 19 条升至 23 条主张）
python run_gate_audit.py --endpoint {hERG,DILI,BBB_Martins} --dump-scores ...
                             → 三端点 AUC CI 全部落盘，verdict_ci 分别为
                               uninformative_unconfirmed / informative_unconfirmed /
                               uninformative_supported
```

**顺带发现并修掉的两个历史漏洞**（不在原清单内）：

1. `tests/test_smoke_pytest.py` 的 `SCRIPTS` 是**硬编码列表**，5 个测试文件
   （`test_v44_guards.py`、`test_v44_gates.py`、`test_v43_measures.py`、
   `test_gate_mmp_v42.py`、`test_ames_alerts_wired.py`）**从未被默认批跑**——
   其中 `test_v44_guards.py` 正是红线 7/8/9 的单元测试。即："红线 7–9 有测试"
   这句话在整改前**不成立**。已全部登记，并新增元测试
   `test_every_test_file_is_registered` 防复发。
2. `python -m pytest tests/` 的"75 passed"是**文件数**而非用例数
   （`pyproject.toml` 只收集 `test_smoke_pytest.py`）。这个口径会让人误判覆盖度，
   已在 README/台账中说明：**报覆盖率时须报用例数**（当前 300+）。

## 六、仍开着的事项（不许忘）

| # | 事项 | 状态 | 说明 |
|---|---|---|---|
| O1 | gate AUC 的 95% CI | ✅ **已关闭（2026-11-03 P2.4-b）** | `--dump-scores` 已加，三端点重跑并落盘；三个口径分开命名、估计量双实现交叉核对、`verdict_ci` 四态；详见 `STATISTICAL_POLICY.md` §P2.4-b |
| O6 | gate CI 未覆盖**训练**随机性 | 🔶 **新开** | 现有 bootstrap 只对评测集重抽（固定模型/固定切分）。要覆盖训练不确定须 nested/repeated-CV 种子级重抽 = P2.4-c |
| O2 | 前瞻盲测（条件②） | 🔶 开 | 需"方案冻结后新产生的数据"；按 `TEMPORAL_HOLDOUT_DISCIPLINE.md` §3 执行 |
| O3 | 外部第二实现者（条件③） | 🔶 开 | 需非本仓库作者；发 `replication/` 挑战包 |
| O4 | `cli.py` 物理拆分 | 🔶 开（P2） | 收益 < 风险；拆分前先用 e2e 锁行为 |
| O5 | D1（Clark 2014 原文核对）/ D2（BBB 双层机制的转运体先验覆盖度） | ✅ D1 已关闭；✅ D2 已量化 | **D1（2026-11-03 已查原文）**：Clark 2014 (J Cheminform 6:34) 协议 step 7 含 `(err+0.5)/(n+1)` 连续性修正，原"纯 laundering"判断过度更正，改为 Jeffreys/Laplace 起源 + Clark 2014 合法次级引用。**D2（2026-11-03 已量化）**：`run_b2_coverage.py` 跑 406 个 BBB_Martins SMILES，结果转运体级覆盖 1/18、分子级 ≤7.1%（保守上限），OATP2B1 规则为黄酮专属、对 CNS 集几乎不触发；`bbb.py` 三通道决议仅被动层 + 休眠 OATP2B1 层可执行，P-gp/BCRP/GLUT1/SGLT1/OATP1A2/LAT1 仅叙事。详见 `references/B2_transporter_coverage.md`，"双层机制"表述应降级 |

### O1 关闭时顺带抓出的三处"工具自己造谣"（都已在代码里锁死）

1. **列名撒谎**：`--dump-scores` 第一版把头写成 `gate_passed`，写的却是模型预测
   （`prob>=0.5`），真正的门是 `sim>=0.35`。下游若照列名读，会把"模型预测"当"门判决"，
   于是"门的判别力"里混进模型自己的准确率。→ 改为 `model_pred` / `gate_passed` 分列。
2. **张冠李戴**：第一版把 `model_auc`（0.792）的 CI 写在 gate 名下。→ 拆成三个命名口径，
   并在 `CLAIMS_REGISTRY.yaml` 里写明"只报 0.792 是给门贴模型的精度"。
3. **判读写死**：`sentence_zh` 第一版把结论写死成 hERG 的叙事，于是 DILI
   （AUC 0.668 > 0.65）被机器生成成"点估计低于工作点 0.65"。→ 改为由 `verdict_ci` 驱动，
   并加回归测试 `test_interpretation_never_claims_below_floor_when_point_is_above`。

### 本轮最重要的科学更正（比补齐一个字段重要）

补 CI 之前，材料写"hERG 门与随机丢弃在**统计上不可区分**"。补完发现
0.580 的 95%CI 是 **[0.456, 0.701]**——上界越过 0.65 工作点。
**这句话方向反了**：既没证明"门有判别力"，也没证明"门没判别力"。
n=132 只够说"未证明有"。已在 `GATE_AND_P8_MMP_v4.2.md` / `POSITIONING.md` /
`gate_audit.py` 三处同步改口，并把"禁止写什么"写进主张登记表。

---

## 七、第三步自查追加（2026-11-03 晚，P2.4-b 之后的连带发现）

以"外审专家"视角反查时抓到两处**比补字段更要紧**的问题，均已修完。

### 7.1 多重比较：只报最好的那个 p（治不了就别说"某些端点有效"）

材料说"门在某些端点上有效"，却只报 DILI 的 Fisher p=0.0267，从未披露另两次也测了。
新增 `adt/stats_ci.holm()` + `run_gate_multiplicity.py`（产物
`out_ext/tdc/gate_multiplicity.json`）：

| 端点 | Fisher p | Holm p | 差值 95%CI | 差值 98.3%CI（族内） |
|---|---|---|---|---|
| hERG | 1.0000 | 1.0000 | +0.001 [−0.148, +0.126] | 跨 0 |
| DILI | 0.0267 | **0.0801** | −0.193 [−0.321, −0.030] | **[−0.349, +0.014] 跨 0** |
| BBB_Martins | 0.7554 | 1.0000 | +0.011 [−0.054, +0.072] | 跨 0 |

**m=3 校正后无一项显著。** 所以"DILI 上门有据"只能按**单端点口径**写，
且必须同段声明跨端点归纳时不成立。这条已进主张登记表（24/24）。

顺带修 `stats_ci._z` 的静默兜底 bug：`alpha=0.05/3` 曾退回 1.96，使"校正后区间"
与 95% 完全相同——**校正声明本身在撒谎**。已改为标准库正态分位数。

### 7.2 测试绿灯一直亮着但没通电（本轮最危险的发现）

`test_smoke_pytest.py` 用 `python <script>` 跑每个测试文件。对**函数式**文件
（只有 `def test_xxx()`、无模块级断言）这是**空跑**：rc=0，一条没跑，却计入"通过"。

- 实测：`tests/test_experiment_scripts.py`（自称 44 例）在本版之前**一例都没执行**。
- 一被真跑，立刻暴露 3 个真失败：① `run_gate_multiplicity.py` 未登记；
  ② `run_gate_audit.py --dump-scores` 的 help 含 `95% CI` → argparse 抛
  `ValueError` → **`--help` 直接崩**；③ 静态守卫判据只认变量名 `_a`，
  把 `any(a in ("-h","--help"))` 误判为无守卫（检查太字面 = 假阳性来源）。

修法：`python <script>` 之后追加 `pytest <script>`（仅当文件含 `def test_`），
断言不得出现 `no tests ran`；自身排除；对偶发 rdkit access violation 重试一次。

| 指标 | 之前 | 之后 |
|---|---|---|
| 真执行的测试文件 | 48 | 86 |
| `def test_` 实际执行 | 0 | 253 |
| assert 语句（静态） | — | 721 |

**这是被批评的"声明式治理"在测试层的原样重演**：绿灯证明的是"进程返回 0"，
不是"断言被执行"。此条已写入 `CHANGELOG.md` v4.8 与 `README_CN.md` 的纪律段。

### 7.3 校准 / 类不平衡 / 决策曲线（黑榜里唯一能自己补的外部效度证据）

新增 `run_gate_metrics.py`（只读 `gate_scores_*.csv`，不重训，任何人可复算）：

| 端点 | 模型 AUC | 校准斜率 | Brier（全判基率） | AP/基率 | 门 MCC |
|---|---|---|---|---|---|
| hERG | 0.7916 | 1.1101 | 0.1442（0.1948） | 1.21 | −0.001 |
| DILI | 0.8957 | **2.8933** | 0.1555（0.2496） | 1.73 | 0.235 |
| BBB | 0.8675 | 1.1441 | 0.0934（0.1552） | 1.19 | −0.017 |

三个新结论：
1. **DILI 校准斜率 2.89**（理想 1.0）→ 概率被压得过窄，不能直接当风险阈值用；
2. **AP 被基率撑高**：除基率后只剩 1.2–1.7 倍富集，只报 AP 0.9 属选择性呈现；
3. **DCA：0.2–0.7 全部阈值上"域过滤"的净收益都不如"全部预测"** → 域过滤在决策
   净收益上是负贡献。此条封死"PASSTHRU 提高决策质量"的写法，门的正当性只剩
   合规/可追溯，不能再拿"更谨慎"辩护。

顺带修掉自己写的 bug：`gate` 的 MCC 第一版把 `sims`（连续值）当二值门判决去 `== 1`，
结果 tp/tn/fp/fn 全近似 0、MCC 恒为 0.000——**看起来像"门毫无关联"，实际是我拿错了变量**。
这类"0.000"最危险，因为它符合预期叙事。
