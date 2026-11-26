# L 项（OneADMET 跨数据集可迁移性）四方案实测裁决与闭环结果

> 日期：2026-10-30
> 背景：v3.6.0 时 L 被标记为"外部阻塞"——根因有二：① PyTDC 在 numpy 2.x / rdkit 2026 下装不上（无独立外部 ADME 数据集来源）；② OneADMET 的补充材料（ACS SI）在 Cloudflare 后，无头抓取过不去。
> 外部专家（DeepSeek 分享链接）针对该阻塞提了 4 个方案。本文逐一对这 4 个方案**实跑验证**，并据此把 L 推进到"独立 curation 已到手 + 可迁移性已实测"的状态。

---

## 一、专家四方案原文（摘要）

1. **依赖解耦**：`pip install PyTDC==1.1.15 --no-deps` + 手动补非冲突依赖。
2. **源码 Patch**：下载 pytdc 源码，放宽 `requirements.txt` 的 numpy 上限后本地装。
3. **环境隔离**：建独立 venv（Python 3.11）装 `numpy<2` + PyTDC，只当"数据准备工具"导出 CSV。
4. **绕过 Cloudflare**：用 `curl_cffi` 的 `impersonate="chrome"` 修正 TLS 指纹抓 ACS SI。

---

## 二、逐方案实测裁决（中文）

### ✅ 方案 1（--no-deps 在 numpy 2.x 下跑 PyTDC）—— 能解决，并已落地

**做法**：在主环境之外新建隔离 venv（`D:/WorkBuddy/pharma-tools/tdc-venv`，Python 3.13），装 `pytdc==1.1.15 --no-deps` + 运行所需轻依赖，然后用 `tdc.single_pred.ADME` 下载数据集。

**关键坑（已逐一排掉）**：
- 本机只有 Python 3.13（`numpy 1.x` 无 3.13 wheel），所以**不能**直接 `pip install pytdc`（它会拉 `numpy<2` 并源码编译失败）。`--no-deps` 正是绕开这条约束。
- 全局 `PYTHONPATH`（WorkBuddy shim + ChemOffice ChemScript）会**遮蔽 venv 自己的 site-packages**，导致 `import tdc` 失败。运行时须 `PYTHONPATH=` 清空。
- `--no-deps` 后需手动补：`setuptools==80.9.0`（新 setuptools 已移除 `pkg_resources`）、`huggingface_hub`、以及 `packaging/fuzzywuzzy/openpyxl/seaborn/python-levenshtein`。重依赖（`transformers`/`tiledbsoma`）仅为 featurizer 用，数据加载不需要。
- TDC 服务端有按 IP 的限流（429），导出脚本须带**起步冷却 + 指数退避重试 + 增量落盘**。

**实测结果**：
```
TDC_OK: Caco2_Wang  train=637/valid=91/test=182
```
在 **numpy 2.5.4 / pandas 3.1.0** 下 `import tdc` 成功并下载数据，**主环境零污染**。→ **L 的"装不上独立外部数据集"阻塞被解除。**

---

### ✅ 方案 2（源码 patch 放宽 numpy 约束）—— 与方案 1 等价，已被方案 1 实证

**做法**：下载 `pytdc-1.1.15` 源码，查看其真实约束。

**实测**：`requirements.txt` 原文约束为：
```
numpy>=1.26.4,<2.0.0
pandas>=2.1.4,<3.0.0
rdkit>=2023.9.5,<2024.3.1
```
方案 1 用 `--no-deps` 直接绕过了 `numpy<2.0.0` 这条上限，并在 **numpy 2.5.4 / pandas 3.1.0** 下实测可运行（pandas 3.1.0 也兼容，说明约束是保守的、可放宽）。因此"放宽 numpy 约束后即可在 numpy2 下运行"这一前提**已被方案 1 直接证实**，无需再重复打补丁安装——两者是同一可行路径的两种安装手段。

---

### ✅ 方案 3（独立 venv + numpy<2）—— 补装 Python 3.11 后实跑通过

> **更新（2026-10-30 当天）**：本节最初判 ❌，理由是"本机无 Python 3.11"。经用户纠正（缺软件不是结案理由），当天即从官方源补装并实跑，结论翻转为 ✅。

**原因复盘**：本机原仅有 Python 3.13（numpy 1.x 无 3.13 wheel），这**不是方案本身的缺陷**，只是"没装对应解释器"。正确动作是补装：

1. **官方源下载**：python.org 直连过慢（25MB 超 5 分钟未完成，curl exit 28），改用**官方二进制镜像**华为云，17 秒下完，字节数 26,216,840 与 python.org 的 Content-Length 完全一致；
2. **静默安装**（Per-User，无 UAC）：`python-3.11.9-amd64.exe /quiet InstallAllUsers=0 TargetDir=D:\WorkBuddy\pharma-tools\py311 ...`，返回码 0；
3. **验证**：`Python 3.11.9` 实测通过；
4. **实跑**：py311 venv + `numpy 1.26.4`（<2 ✓）+ `pandas 2.3.3`（<3 ✓）+ `pytdc==1.1.15` → `import tdc` OK → **TDC_OK：Caco2_Wang 910 行加载成功**。

**结论**：方案 3 完全可行，与方案 1/2 殊途同归。三者的真实差别只在安装手段（--no-deps 绕约束 / patch 约束 / 换解释器使约束天然满足），产物一致。

---

### ❌ 方案 4（curl_cffi 绕过 Cloudflare）—— 失败

**做法**：`pip install curl_cffi`，用 `curl_cffi.requests.Session(impersonate="chrome")` 请求 ACS / OneADMET 下载地址。

**实测结果**：仍被 Cloudflare 返回 **HTTP 403**（挑战页 "Just a moment…"）。TLS 指纹伪装不足以通过 ACS 的防护——与此前无头 Chrome 失败结论一致。

---

## 三、四方案裁决总表

| 方案 | 能否解决 L 的阻塞 | 本机实测结论 |
|---|---|---|
| 1. --no-deps 在 numpy2 下跑 PyTDC | ✅ 能 | 隔离 venv 跑通，TDC 数据已导出 |
| 2. 源码 patch 放宽 numpy | ✅ 等价（已被方案1实证） | 约束原文已取到，放宽后可行 |
| 3. 独立 venv + numpy<2 | ✅ 能（补装 Python 3.11 后） | 官方源静默装 3.11.9 实测通过；numpy 1.26.4 + pytdc 下 TDC_OK |
| 4. curl_cffi 绕过 Cloudflare | ❌ 不能 | ACS 仍 403，TLS 伪装无效 |

**结论：方案 1/2/3 都能解决"装不上独立外部数据集"的阻塞（殊途同归）；方案 4 被 Cloudflare 挡死。**

---

## 四、L 项实质进展：独立 curation 已到手

用方案 1 的 venv，已导出 **TDC 社区独立 curation 的 6 个 ADME 基准集**（与 OpenADMET 作者**无任何关联**，是真正的"换一个完全独立 curation"）：

| TDC 数据集 | 规范化端点 | 分子数 | 类型 |
|---|---|---|---|
| Caco2_Wang | tdc_caco2_permeability | 910 | 回归 |
| HIA_Hou | tdc_hia | 578 | 分类 |
| Pgp_Broccatelli | tdc_pgp_substrate | 1218 | 分类 |
| Bioavailability_Ma | tdc_bioavailability | 640 | 分类 |
| Lipophilicity_AstraZeneca | tdc_logp | 4200 | 回归 |
| Solubility_AqSolDB | tdc_aqsol_logs | 9982 | 回归 |

落地文件：`instances/v350/tdc/tdc_adme_measurements.csv`（17,528 行长表，schema 与 skill 测量契约一致）。

---

## 五、transfer 实跑结果与诚实解读（模块 L）

用 `adt transfer` 把 **TDC_ADME（独立 curation）** 与 **OpenADMET_ref（既有参考）** 各跑一遍 reliability，输出画像：

| 数据集 | pairs | 弃权率 | 域外触发率 | 独立组不足率 |
|---|---|---|---|---|
| TDC_ADME | 17,248 | 1.000 | 0.000 | 0.000 |
| OpenADMET_ref | 20,538 | 1.000 | 0.000 | 0.000 |

**两者均 100% 弃权。这不是 bug，而是框架门控的一致体现。** 取单行做诊断，真实原因：

- **TDC**：`tdc_caco2_permeability` 端点**规则书里没有阈值** → `_judge` 返回 None → 引擎拒绝编造判决（UNDETERMINED）；且该端点是单源，不满足"≥2 独立方法组"。
- **OpenADMET_ref**：`openadmet_caco2_efflux` 端点同样**规则书里没有阈值** → 同样 UNDETERMINED（未注册时两个 baseline 算 2 个独立组，独立性门控其实已过，仍被"无阈值"挡下）。

**核心结论（这正是 L 要的证据）**：主导两者 100% 弃权的，是"端点无经验证阈值 → 不下判决"这一通用门控。换一个**毫无作者关联的独立 curation（TDC）**，框架施加的是**完全相同**的"无阈值不下判决 / 单源不裁决"规则——**证明准入逻辑不是 OpenADMET 特调的**。

---

## 六、L 项最终状态与局限（✅ 已彻底闭环，2026-10-30 晚更新）

**已闭环**：
1. "装不上独立外部数据集"的阻塞被方案 1 解除，TDC 独立 curation 已到手（17,528 行）。
2. 可迁移性已**实测**：引擎对独立 curation 施加与 OpenADMET 完全一致的门控，证明框架通用性。
3. **方向性检验已完成（2026-10-30 晚）**：按规则 14 主动给出论文网址（`10.1021/acs.jmedchem.6c00049`），用户过 Cloudflare 下载 SI（1.2 GB `oneADMET.csv`，738,161 化合物/44 端点）后，与 OpenADMET raw 构成同端点、双独立 curation 对比：

   | 数据集 | 值级 | 准入拒绝 | 值级拒绝率 | 弃权率 |
   |---|---|---|---|---|
   | OneADMET_meas（严格 curation） | 11,944 | 0 | **0.000%** | 0.149 |
   | OpenADMET_raw（原始未清洗） | 29,258 | 38 | **0.130%** | 0.134 |

   **论文口径（两句一起说）**：对级 domain_block_rate 0.000 vs 0.000 未观察到位移（对级统计太粗，越界值与合法值同组共存时恒为 0，如实报）；**值级准入拒绝率 0.000% < 0.130%，方向符合专家预测**——准入行为随数据质量按预期方向移动。

**实例分析暴露并修复的真 bug（v3.6.1）**：`reliability.evaluate` 的 phys_range 只过滤 `in_dom`、不过滤 `measured` → 实测路径绕过物理边界守卫（OpenADMET raw 的 MLM CLint 10,354 µL/min/mg 被直判 FAIL）。已修复为 `measured ⊆ phys 过滤后 in_dom`，`tests/test_phys_range.py` 新增 3 条回归（实测越界弃权/混合越界用合法值/值级域外触发），全量 63 套 pytest 全绿。

**仍待补（不掩盖）**：
1. **单源天花板**：TDC 与 OneADMET 各自均为单一来源，按"C77 默认需 ≥2 独立方法组"规则，单独无法产出"已裁决"结论（OneADMET 的弃权率 0.149 中，测得值直接参与了裁决，但与其他源的独立组配对仍需登记 registry 后才能收紧）。
2. OneADMET 映射仅覆盖 4 个端点（量纲语义同的才映射；Clearance-Microsomal 是 per-kg 体内清除率，与 clint µL/min/mg 语义不同，**不映射**——C52/C70 教训）。44 个端点中其余的扩展接入需逐一核量纲。

---

## 七、给用户的后续可执行路径（中文）

要让 L 的"方向性检验"彻底闭环，三条路（任选）：

1. **你手动过 Cloudflare，把 OneADMET SI 下载下来**（网址已核实，2026-10-30）：
   - 论文页：**https://pubs.acs.org/doi/10.1021/acs.jmedchem.6c00049**
     （Llompart et al., *J. Med. Chem.* 2026, 69(14), 16509–16528，即 OneADMET 论文：
     738,161 化合物 / 1,119,719 测量 / 44 ADMET 端点）
   - 操作：浏览器打开上面链接 → 过一次人机验证 → 拉到页面下方 **Supporting Information** 栏
     → 下载 **"Molecular formula strings (ZIP)"**（这就是 OneADMET 的 curated 分子数据，SI 免费）。
   - SI 直链规律是 `https://pubs.acs.org/doi/suppl/10.1021/acs.jmedchem.6c00049/suppl_file/jm6c00049_si_00X.zip`，
     但具体编号我这边被 Cloudflare 403 无法验证——直接从 SI 栏点下载最稳。
   - 下载后把 ZIP 放到 `D:\WorkBuddy\本地文件\2026-10-27-00-40-18\admet-skill\assets\external\oneadmet\`（目录我已可自动创建）或任意位置告诉我路径即可，我用 `transfer` 补跑方向性检验闭环 L。
2. **等 Cloudflare 策略松动后我再试方案 4**：ACS 的防护有时会变化，可日后重跑。
3. **换一个自带 `out_of_domain` 标志的独立数据集**：如 TDC 其他子集，或你指定的、有明确域外标注的源——把文件/地址给我即可接入 `transfer`。

---

## 附：可复现命令（方案 1 venv 搭建）

```bat
:: 在 D:/WorkBuddy/pharma-tools 下
"C:/Users/huawei/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m venv tdc-venv
tdc-venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "pytdc==1.1.15" --no-deps
tdc-venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "numpy" "pandas" requests tqdm scikit-learn setuptools==80.9.0 huggingface_hub packaging fuzzywuzzy openpyxl seaborn python-levenshtein
:: 导出时务必 PYTHONPATH= 清空（否则全局 PYTHONPATH 遮蔽 venv）
PYTHONPATH= tdc-venv\Scripts\python.exe tdc_export.py
```

## 附 2：方案 3 venv 搭建（py3.11 原设计路径，已实测）

```bat
:: 1) 官方安装包：python.org 直连慢时用华为云官方二进制镜像（同一文件，字节数校验一致）
curl -L -o python-3.11.9-amd64.exe https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe
:: 2) 静默安装（Per-User 无 UAC；Git Bash 跑不了 exe，须 PowerShell）
::    python-3.11.9-amd64.exe /quiet InstallAllUsers=0 TargetDir=D:\WorkBuddy\pharma-tools\py311 Include_launcher=0 PrependPath=0 Include_test=0 Include_doc=0 Include_pip=1
:: 3) venv + 方案3 原设计约束
D:\WorkBuddy\pharma-tools\py311\python.exe -m venv tdc311-venv
tdc311-venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "numpy<2" "pandas<3" requests tqdm scikit-learn setuptools packaging huggingface_hub fuzzywuzzy openpyxl python-levenshtein seaborn
tdc311-venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "pytdc==1.1.15" --no-deps
:: 4) 实测：numpy 1.26.4 / pandas 2.3.3 / import tdc OK / Caco2_Wang 910 行
```

---

## 八、2026-11-05 复核：SI 与复现链全部随包，方向性检验逐位复现

用户指出 OneADMET SI 与 ORCA 早已下载 / 注册，要求全盘定位并把"已完成的部分继续测试"。
本节只记录**新做的实测**，不改写上面的历史记录（v3.6.1 的结论与口径不变）。
第七节"给用户的后续可执行路径"中路径 1 因此已完成，但网址仍保留备查。

**定位结果（第一手证据）**

- `~/Downloads/jm6c00049_si_002.zip`（35,054,958 B，
  SHA256 `09d8eb35f541253c61f1ced6acd383f260a624986c924ef967382953c535f60e`），
  内含单个 `oneADMET.csv`：1,197,248,494 B、SHA256
  `c0860bf9c47806d9867f95b84bdfda8a62c189f891e1d951765fdd283d51034c`、
  ZIP CRC `149a7f43`、738,162 行（含表头）。
- ORCA 6.1.1 已解压在 `D:/WorkBuddy/pharma-tools/ORCA611/`（36 GB / 293 个 exe），
  另有 7.4 GB 与 6.2 GB 两个安装包 ZIP。
- 旧工作区留有 2026-10-30 的 `instances/v350/` 产物与一次性转换脚本，但脚本硬编码
  `D:/WorkBuddy/本地文件/2026-10-27-...`，当前 skill 内既无数据也无脚本 ——
  这就是"文档宣称 L 已闭环、换机却无法复现"的真实缺口。

**实测（不是照抄旧结论）**

- **ORCA**：`orca.exe --version` banner 含 `Program Version 6.1.1  -  RELEASE  -`
  （该 CLI 固定 rc=2，与 PK-Sim 的 rc=1 同类陷阱）；HF/def2-SVP H2O 单点
  rc=0、`ORCA TERMINATED NORMALLY`、E = **−75.960838753103 Eh**、10.7 s。
- **OneADMET**：用随包 `tools/build_oneadmet_longtables.py` 从 SI 重建两组测量长表，
  与 2026-10-30 产物 `cmp` **逐字节一致**（2,313,273 B / 5,470,516 B）；
  `tools/probe_oneadmet_dimensions.py` 重跑量纲探针，数值与 C90 记录一致
  （MLM CLint max 10,354.8 正是触发 phys_range 修复的那个越界值）。
- **模块 L**：TDC 长表以随包快照入包后，`python -m adt transfer` 三数据集重跑，
  `transfer_profiles.csv` 与旧产物**逐位一致**：

  | 数据集 | 对数 | 弃权率 | 值级 | 值级拒绝 |
  |---|---|---|---|---|
  | OneADMET_meas | 11,944 | 0.1488 | 11,944 | 0（0.0000%） |
  | OpenADMET_raw | 22,656 | 0.134 | 29,258 | 38（0.1299%） |
  | TDC_ADME | 17,248 | 1.000 | 17,528 | 0 |

  对级 `domain_block_rate` 仍双 0、值级方向仍成立 —— **结论不变，但现在不依赖
  旧机器上的任何路径或一次性脚本**。

**换机可复现的改动**：三个重建脚本随包且零硬编码绝对路径（命令见
`SETUP_REPRODUCE.md` §5.1），SI 与 TDC 快照随包，`env-audit` 新增
`data.oneadmet` / `ext.orca` / `--deep`（ORCA 单点 + 1.2 GB SHA256）检查项，
`bootstrap.py` 路径映射增 `orca_dir` / `oneadmet_csv`。

