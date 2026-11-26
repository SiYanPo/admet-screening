# 排除规则（冻结 · Stage 1 附件）

**冻结版本**：`EXCLUSION-RULES-20261118-01`
**状态**：本文件在 OSF 锚定前冻结；锚定后**不得修改**。若确需修改，必须新开版本并在 Stage 2 中标注为方案偏离（protocol deviation），不得静默替换。
**适用对象**：Stage 1 RR 的主分析集（前瞻标签集）。回溯集仅用于功效分析，其排除按历史脚本既定规则，不受本文件约束。

---

## 1. 分子/记录级排除（按优先级顺序执行，先命中先排除）

| 序 | 规则 | 判据（机器可读） | 归因码 | 说明 |
|---|---|---|---|---|
| E1 | 结构无效 | `standardize()` 失败，或 InChIKey 为空/格式非法 | `E_STRUCT_INVALID` | 禁止名称→SMILES 直连（红线 1）；立体缺失按 E2 |
| E2 | 立体化学缺失 | InChIKey 存在但立体层缺失且端点对立体敏感 | `E_STEREO_MISSING` | 按 `input_gate.csv` 留痕；不静默补齐 |
| E3 | 域外且无 AD 分数 | `domain_flag=out_of_domain` 且 `sim`/AD score 缺失 | `E_OOD_NO_AD` | 无法做 AD 判定的记录不进入主分析 |
| E4 | 单位不可换算 | 测量单位不在 `03_endpoint_rules.yaml` 换算表内 | `E_UNIT_UNMAPPED` | 不得按"原样放行"处理（红线：单位真源单一） |
| E5 | 重复记录 | 同一 InChIKey + 同一端点 + 同一源出现多次 | `E_DUPLICATE` | 保留首次入库记录，其余排除，留 manifest |
| E6 | 标签缺失/歧义 | 金标准标签为 NA 或同时满足 PASS 与 FAIL 定义 | `E_LABEL_AMBIGUOUS` | 不借用预测值反推标签 |
| E7 | 解盲后新增排除 | **禁止** | `E_POST_UNBLIND` | 解盲后不得新增任何排除规则；违反即方案偏离 |

## 2. 端点级排除

- **hERG**：estimand 未绑定（NOT_AN_ESTIMAND）。主分析**允许**纳入该端点，但按 SAP §5.5，
  任何推断性结论自动撤销，只作描述；不得与 always-positive accuracy 跨量纲比较（G13 blocker）。
- **Ames**：仅在 `--i-accept-low-validity` 且留痕时纳入；双方法缺一不判（UNDETERMINED）。
- **DILI**：单源外源结论不得升格为普适主张（SAP §5.5）。

## 3. 排除报告的强制产物

每次分析必须落 `input_gate.csv`，逐行含：`compound_id, endpoint, source, decision(PASS/EXCLUDE), rule_id, detail`。
- 排除行必须有归因码（上表 E1–E7），不允许空白。
- `decision=PASS` 行数必须等于主分析集 n；两者不等即失败（写入端强校验）。
- 该文件与 `run_manifest.yaml` 一同归档，构成"哪些数据被排除、为什么"的证据链。

## 4. 不得做的事（红线）

1. 不得因"某端点结论不好看"而事后加排除规则（E7）。
2. 不得把 out_of_domain 当作"已判定失败"——它是 UNDETERMINED，不是 FAIL。
3. 不得把 percentile（DrugBank ADMET-AI）当概率单位（假校准）。
4. 不得在排除规则里写死任何一台机器的绝对路径（换机可复现要求）。
