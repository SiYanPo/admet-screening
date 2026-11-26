# 来源依赖与独立票审计（自动生成，请勿手改）

> 生成器：`tools/source_dependence_audit.py --check` 可作 CI 门禁。
> 规则：`independence_group` 相同的源**只记 1 张独立票**（注册表 §头部两票半原则）；
> 共享训练数据/基础模型/近邻池的源不得当作相互独立的证据。

## 独立组（能投几票）

| 独立组 | 源 | 有效独立票 |
|---|---|---|
| `database` | `toxric`、`microbetcm`、`gutbugdb`、`masi` | **1** |
| `deep_learning` | `deeppurpose` | **1** |
| `descriptor_ml` | `admetlab3`、`admet_ai` | **1** |
| `descriptor_rules` | `swissadme` | **1** |
| `dl_atomwise` | `xenosite` | **1** |
| `experimental_truth` | `chembl`、`cas_benchchem` | **1** |
| `herg_specialist` | `predherg`、`cardiosafe`、`cardiosim_tox`、`mtf_herg` | **1** |
| `legacy_qsar` | `admetasar3` | **1** |
| `neighbor_qsar` | `protox3`、`vnn_admet` | **1** |
| `pbpk_platform` | `pk_sim_mobi` | **1** |
| `poppk_tooling` | `nlmixr2`、`pharmpy` | **1** |
| `quantum_chemistry` | `pyscf`、`orca` | **1** |
| `rule_engine` | `biotransformer` | **1** |
| `tcm_specific` | `herbtoxnet`、`kan_prospect` | **1** |

## 逐源明细

| 源 | status | 注册表组 | model card 组 | 训练数据声明 |
|---|---|---|---|---|
| `admetlab3` | ok | descriptor_ml | descriptor_ml | not_disclosed（文献称基于 ChEMBL/PubChem 大规模 curated 集） |
| `admet_ai` | ok | descriptor_ml | descriptor_ml | TDC ADMET 基准集（公开） |
| `protox3` | ok | neighbor_qsar | neighbor_qsar | not_disclosed |
| `vnn_admet` | ok | neighbor_qsar | neighbor_qsar | Tox21 / 内部集（论文公开部分） |
| `deeppurpose` | ok | deep_learning | deep_learning | 随模型而定 |
| `biotransformer` | ok | rule_engine | rule_engine | 文献反应规则库 |
| `xenosite` | license_required | dl_atomwise | dl_atomwise | not_disclosed |
| `admetasar3` | needs_probe | legacy_qsar | — | — |
| `predherg` | needs_probe | herg_specialist | — | — |
| `toxric` | needs_probe | database | — | — |
| `swissadme` | ok | descriptor_rules | — | — |
| `chembl` | ok | experimental_truth | experimental_truth | 文献提取的实测活性 |
| `pkcsm` | dead | — | — | — |
| `pass_online` | dead | — | — | — |
| `admetmesh` | redundant | — | — | — |
| `pyscf` | ok | quantum_chemistry | — | — |
| `orca` | needs_probe | quantum_chemistry | — | — |
| `cas_benchchem` | ok | experimental_truth | — | — |
| `microbetcm` | ok | database | — | — |
| `gutbugdb` | ok | database | — | — |
| `masi` | needs_probe | database | — | — |
| `cardiosafe` | paper_only | herg_specialist | — | — |
| `cardiosim_tox` | paper_only | herg_specialist | — | — |
| `mtf_herg` | paper_only | herg_specialist | — | — |
| `herbtoxnet` | paper_only | tcm_specific | — | — |
| `kan_prospect` | paper_only | tcm_specific | — | — |
| `pk_sim_mobi` | ok | pbpk_platform | — | — |
| `nlmixr2` | ok | poppk_tooling | — | — |
| `pharmpy` | ok | poppk_tooling | — | — |

## 待闭合问题（0）

- 无

## 审稿边界声明

本表只记录**声明层面的**来源依赖；真正的数值独立性还需看跨源残差相关（见 `adt/reliability.py`），二者缺一不可。共享 TDC/PubChem 训练生态的两个源即使算法族不同，也不得当作两次独立确认。
