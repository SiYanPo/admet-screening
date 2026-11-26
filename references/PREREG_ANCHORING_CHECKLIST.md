# 预注册第三方锚定执行清单（P2.1，2026-11-03）

> **目的**：把 v4.0 标签授予条件① 从"想做"变成"可执行、可验收"。
> 本文件的每一条都能在 1 天内判断"做到了 / 没做到"，不接受"基本完成"。

## 0. 先判断：你到底需要哪一档

| 档 | 场景 | 最低要求 | 允许的对外表述 |
|---|---|---|---|
| **A. 探索**（默认） | 组内筛分子、选买哪几个 | 不需要预注册 | "探索性分析，未预注册"（材料里必须写这句） |
| **B. 内部预注册**（推荐） | 组会/内部报告/开题 | 方案 hash + 日期落盘（`adt/prereg.py`） | "内部预注册（未第三方锚定）" |
| **C. 第三方锚定** | 投稿方法学论文 | OSF/Zenodo 存证 + 时间戳 | "预注册已锚定（anchor: OSF-xxxx）" |

**纪律**：B 档**不得**写成 C 档。`Prereg.anchor_status()` 返回
`claim_allowed=False` 时，任何材料写"预注册"都属违规（`phrasing` 会拦）。

## 1. 冻结什么（缺一项即不算完成）

| # | 冻结内容 | 载体 | 为什么必须冻 |
|---|---|---|---|
| 1 | 主假设（一句话，可证伪） | `SAP_PROTOCOL.md` §主假设 | 不写死就永远"事后成立" |
| 2 | 端点清单 + 端点级判读规则 | `03_endpoint_rules.yaml` + `THRESHOLD_REGISTRY.yaml` | 换端点=换结论 |
| 3 | 代价三元组 `c_abstain / c_false_PASS / c_false_FAIL` 及其网格 | `SAP_PROTOCOL.md` §代价 | 效用结论对代价极敏感（实测：弃权成本≥0.5 时 5/9 组合变差） |
| 4 | 样本量与最小可行 n | `STATISTICAL_POLICY.md` | n 不可事后调整 |
| 5 | 判读规则（什么算支持/反驳/不确定） | `SAP_PROTOCOL.md` §判读 | 防止"结果出来再定标准" |
| 6 | 分析代码 commit hash | git | 代码变了就不是同一实验 |
| 7 | 缺失数据的处理（如源无预测） | `04_decision_funnel.md` | 缺失处理方式可翻转结论 |
| 8 | **失败即结论条款** | 本文件 §4 | 负结果必须公布，否则选择性报告 |

## 2. 锚定操作（30 分钟可完成）

1. 登记标准（生成哈希链）：
   ```python
   from adt.prereg import Prereg
   p = Prereg("prereg/prereg.jsonl")
   p.register_criteria(
       name="abstention_layer_utility",
       criteria={"main": "dU>0 on >=8/9 endpoint pairs when c_abstain<=0.2*c_false_FAIL",
                 "endpoints": ["herg", "dili", "bbb_martins"],
                 "cost_grid": [[0.2, 5, 1], [0.5, 5, 1], [1.0, 5, 1]],
                 "n_min": 200},
       note="v4.0 主假设（写入 OSF 前冻结）")
   ```
   说明：冻结项 = §1 的 8 项；`Prereg` 对每次登记做哈希链，`verify()` 可查篡改。
2. 上传到第三方存证：
   - OSF：新建 project → 上传 `PREREG_v1.yaml` → **Registrations → Create**（获得 DOI 与时间戳）；
   - 或 Zenodo：上传 → Publish（获得 DOI）；
   - 或机构 Git：`git commit` + 打 tag + 推送（若机构有可信时间戳服务更佳）。
3. 回填锚定事件（**必须走 API，不要手改 jsonl**）：
   ```python
   p.attach_anchor({"registry": "OSF", "doi": "10.17605/OSF.IO/XXXXX",
                    "url": "https://osf.io/XXXXX", "deposited_at": "2026-11-10"})
   ```
   该事件的 `via` 会被记成 `external_anchor`，若晚于标准登记则
   `anchor_status()` 标 `post_hoc_anchor=True`（材料须写明日期差）。
4. 验收（一条命令，可交给第三方复核）：
   ```bash
   python -m adt.cli prereg-status --log prereg/prereg.jsonl
   ```
   `exit 0` = `claim_allowed=True`；`exit 3` = 未锚定（材料不得写"已完成预注册"）。

## 3. 锚定之后可以改什么、不可以改什么

| 可改（须记录 diff） | 不可改 |
|---|---|
| 实现 bug（判读逻辑不变） | 端点清单 |
| 代码性能优化 | 代价三元组与网格 |
| 文档措辞 | 判读规则与阈值 |
| 增加**辅助**分析（标注 exploratory） | 主假设的方向 |

**违规后果**：任何"锚定后改阈值"的操作，都使锚定失效，须重新锚定并说明原因；
材料里必须披露"本分析在锚定后做过 N 次修订"，否则等于伪造时间序。

## 4. 失败即结论条款（模板，可直接贴进 OSF）

> 本研究承诺：无论主要终点结果是否支持假设，均按预注册方案完整报告；
> 若主要终点不支持假设，本研究将报告该负结果并讨论其边界条件，不进行
> 端点替换、样本追加或阈值重调以求得阳性结论。若确需探索性分析，全部标注
> `exploratory` 并与主要结果分节呈现。

## 5. 与现有代码的接线状态

| 能力 | 状态 | 位置 |
|---|---|---|
| 冻结/hash 计算 | ✅ 已有 | `adt/prereg.py` |
| `anchor_status()` 判定 | ✅ 已有 | `adt/prereg.py` |
| `prereg-status` 命令行复核 | ✅ **本轮新增** | `adt/cli.py::cmd_prereg_status` |
| G9 标签门读 anchor 状态 | ✅ **本轮升级**（去 `-dev` 必须 `claim_allowed=True`，否则 blocker；`post_hoc_anchor` 降为 warn 并要求披露日期差） | `adt/release_gate.py::_check_anchor` |
| 前瞻窗口校验（数据晚于锚定） | ✅ **2026-11-23 已实现（P2.2 关闭）** | `adt/prereg.py::Prereg.temporal_validity` / `temporal_window_declared`；CLI `prereg-status --data-timestamps`；回归 `tests/test_prereg_temporal.py`（5 passed） |

> **P2.2 已关闭（2026-11-23）**：`prospective_data_window` 现在可写进冻结项参与哈希，
> `temporal_validity(data_timestamps)` 用真实数据时间戳反查 `min(data_ts) > anchor_date`，
> 违规时 `prereg-status` 返回 exit 4 并打印违规条数。语义边界仍然诚实：
> 它校验的是**你交给它的时间戳**，不是"这些标签客观上没被看过"——后者只能靠
> 第三方（OSF/Zenodo）时间戳 + 数据来源方的采集日志共同支撑。
