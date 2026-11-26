# 换机复现指南（SETUP_REPRODUCE.md）

> 目标：在新电脑上从零把本 skill 完整跑起来并复现全部结论。
> 维护纪律：任何改变运行环境的改动（新依赖、新外部软件、新环境坑）必须同步更新本文件。
> 本版依据 **2026-11-05 全量环境排查实测**重写，替换了 2026-10-31 版中已过时的
> 版本号、镜像、测试数与包名。所有"实测"字样都对应本机跑出的第一手输出。

---

## 0. 最短路径（新电脑只用这一条）

```bash
# 整包拷贝 skill 目录（含 assets/ 内 1.2 GB 的 OneADMET SI、references/、snapshots/、tests/、tools/、instances/）后进入根目录
cd admet-screening
python bootstrap.py
```

`bootstrap.py` 是纯标准库、幂等的：缺什么装什么、装完验证"能不能用"、日志落盘到
`logs/bootstrap_<时间戳>.log`、失败即停并打印返回码与日志尾部。它按顺序做：

1. 按 `requirements.lock` 校验核心 10 个包（import + 版本 + 最小功能调用），缺了才装；
2. 按 `requirements-optional.txt` 装可选层（Pharmpy / pytdc，两组用不同 pip 参数）；
3. 探测外部工具（含 ORCA 有限广度自动发现与 OneADMET SI 定位），把本机实际路径写入 `.env_audit_paths.json`（**不要跨机拷贝这个文件**）；
4. 重生成 `env_fingerprint.json`（换机必然漂移，重生成即视为声明漂移）；
5. 跑 `python -m adt env-audit --json-out env_audit_report.json`；
6. 跑 `python -m pytest -q`（可用 `--skip-tests` 跳过）。

常用变体：

```bash
python bootstrap.py --core-only          # 只装核心层
python bootstrap.py --verify-only        # 只自检，不改环境
python bootstrap.py --network           # 额外探测注册网页可达性
python bootstrap.py --deep              # 深度自检：ORCA 单点实跑 + 1.2 GB SI SHA256
python bootstrap.py --mirror URL        # 前置自定义 PyPI 镜像
python bootstrap.py --skip-tests        # 跳过 15~25 分钟的全量测试
```

换机后随时可单独自检：

```bash
python tools/verify_all.py --quick   # 环境 → API 死代码 → 版本 → release-check
python tools/verify_all.py           # 再加 103 例默认 smoke（含 14 个原生测试）
python -m adt env-audit --quiet          # 0=必需层全绿 / 1=必需层缺失 / 2=仅可选告警
python -m adt env-audit --deep --quiet   # 额外实跑 ORCA 单点 + 1.2 GB SI SHA256/行数
```

> 2026-11-22 同行评审修复：`pytest tests` 曾只收集 `test_smoke_pytest.py`，
> `SKIP` 中的原生测试从未默认执行；现在 smoke 会逐个执行它们。
> 若只跑 `pytest tests -q` 看到 103 个用例才是正常的；少于这个数说明收集配置回退了。

> **模拟换机实测（2026-11-05）**：把 `.env_audit_paths.json` 删掉后重跑 `bootstrap.py`，
> 核心层 10/10 判定"已可用、无需安装"，并通过 `micromamba env list --json` 自动发现
> `D:\mm\envs\pkpd`（判据是目录里真有 `Rscript`），外部层 0 问题，bootstrap exit 0。
> 此时若不设 `ADT_PYSCF_ENV` / `ADT_OPENMM_ENV`，env-audit 返回 **2**（两项可选研究工具未配置），
> 这是预期而非故障；指向对应 conda 环境后即回到 0。

**自检模块本身只用标准库**，因此环境坏到 `import rdkit` 都失败时它仍能跑并报出坏在哪一项 ——
这是刻意的，不这么做"排查环境"就需要先有一个好环境，形成循环依赖。

---

## 1. 环境要求

| 项 | 要求 | 实测 / 说明 |
|---|---|---|
| 操作系统 | Windows / Linux / macOS | 核心依赖为纯 Python + 轮子包；`lxml` 是唯一 C 扩展，缺失自动降级 `html.parser` |
| Python | **≥ 3.11** | 本机 3.13.14；低于 3.11 会被 bootstrap 直接拒绝 |
| pip 镜像 | 首选 `https://repo.huaweicloud.com/repository/pypi/simple/` | 实测 7.5 MB/s；bootstrap 内置 4 镜像 fallback（华为云 → 阿里云 → TUNA → pypi.org），429 自动换源 |
| 官方 pypi.org | **索引 200，但 wheel 下载停滞** | 2026-11-05 实测 `--dry-run` 3 分钟零输出；因此不要把它写死成唯一源 |
| 环境变量 | 见下表，全部可选 | 不设就自动探测；外部工具/大体积数据换机后靠下表变量指路 |

| 变量 | 含义 | 不设时 |
|---|---|---|
| `ADT_OSP_DIR` | PK-Sim/MoBi portable 根目录 | 探测 `~/.workbuddy/binaries/osp`、`<skill>/_vendor/osp`、`/opt/osp` |
| `ADT_MAMBA_EXE` | micromamba 可执行文件 | 探测 `~/.workbuddy/binaries/micromamba/...`、`PATH` |
| `ADT_MAMBA_ROOT` | `MAMBA_ROOT_PREFIX` | 读现有 `MAMBA_ROOT_PREFIX`，否则 `~/micromamba` 等 |
| `ADT_PKPD_ENV` | R + nlmixr2 + rxode2 的 conda 环境 | 探测 `<root>/envs/pkpd` **且验证里面有 Rscript**（目录存在 ≠ 环境完整） |
| `ADT_PYSCF_ENV` | 可选：PySCF 的 conda 环境 | 不设则可选层报 WARN，不影响核心 |
| `ADT_OPENMM_ENV` | 可选：OpenMM 的 conda 环境 | 同上 |
| `ADT_ORCA_DIR` | 含 `orca.exe` 的 ORCA 安装目录 | 有限广度自动发现（HOME / 各盘符根 3 层内，只进工具目录、上限 2500 目录）；命中条件是目录里真有可执行文件 |
| `ADT_ORCA_SEARCH_ROOTS` | 覆盖 ORCA 搜索根（`os.pathsep` 分隔） | 默认 HOME + `/opt` + `/usr/local` + 所有存在的盘符根目录 |
| `ADT_ONEADMET_CSV` | OneADMET SI 解压后的 `oneADMET.csv`（1.2 GB，可放 skill 外） | 默认 `<skill>/assets/external/oneadmet/oneADMET.csv`，也认 `extracted/` 子目录 |

---

## 2. 依赖分三层（**不能合并**）

### 2.1 核心层 `requirements.lock`（精确钉版，2026-11-05 实测回填）

```
rdkit==2026.9.1  pyyaml==6.0.3  requests==2.34.2  numpy==2.5.4
scipy==1.18.1  scikit-learn==1.9.1  pandas==3.1.0
beautifulsoup4==4.15.0  lxml==6.1.3  pytest==9.2.0
```

> **rdkit 版本写法**：PyPI 规范名是 `2026.9.1`（`importlib.metadata.version`），
> 而 `rdkit.__version__` 打印 `2026.09.1`。钉版必须用前者，已 `pip --dry-run` 验证可解析。
> **旧 lock 已作废**：原文件停在 2026-10-31 栈（rdkit 2026.3.6 / pandas 2.3.3），
> 按它装会复现出与当前材料不同的数字。

### 2.2 可选层 `requirements-optional.txt`（实验脚本 / 互操作桥用）

| 包 | 精确版本 | 安装方式 | 为什么特殊 |
|---|---|---|---|
| `pharmpy-core` | 2.3.0 | 正常安装 | **正确包名是 `pharmpy-core`**；PyPI 上的 `pharmpy` 只有 0.0.1/0.0.2 两个占位版，照名字装 2.3.0 必失败 |
| `pytdc` | 1.1.15 | `--no-deps` | 元数据声明 `numpy<2 / pandas<3 / rdkit<2024.3.1`，普通安装会强拆核心栈并试图源码编译 numpy（本机无编译器，实测直接失败） |
| `tqdm` / `fuzzywuzzy` / `openpyxl` | 4.70.1 / 0.18.0 / 3.1.5 | `--no-deps` | pytdc import 链的最小运行时集合 |
| `setuptools` | **80.9.0** | `--no-deps` | 更高版本移除 `pkg_resources`，`tdc.utils.load` 会直接 ImportError |
| `huggingface_hub` | 2.4.0 | 正常安装 | 需要自己的传递依赖；实测不会动 numpy/pandas/rdkit |

> 元数据约束 ≠ 运行期约束：实测 `from tdc import BenchmarkGroup` 在
> numpy 2.5.4 / pandas 3.1.0 / rdkit 2026.9.1 下可用。**但绝不能让 pip 自己解析 pytdc 依赖。**

### 2.3 外部工具层（换机后需重新放置，见 §4）

PK-Sim / MoBi / micromamba / R 栈 / Pharmpy，均由 `env-audit` 实跑验证（不是只看文件存在）。

---

## 3. 手工安装（bootstrap 不可用时的等价路径）

```bash
python -m venv .venv                       # Windows: .venv\Scripts\activate
python -m pip install -r requirements.lock -i https://repo.huaweicloud.com/repository/pypi/simple/
python -m pip install "pharmpy-core==2.3.0" -i https://repo.huaweicloud.com/repository/pypi/simple/
python -m pip install --no-deps -i https://repo.huaweicloud.com/repository/pypi/simple/ \
    "pytdc==1.1.15" "tqdm==4.70.1" "fuzzywuzzy==0.18.0" "openpyxl==3.1.5" "setuptools==80.9.0"
python -m pip install "huggingface_hub==2.4.0" -i https://repo.huaweicloud.com/repository/pypi/simple/
python -m adt env-fp --out env_fingerprint.json
python -m adt env-audit --json-out env_audit_report.json
python -m pytest -q
```

**实测基线（2026-11-05）**：`bootstrap.py` 全链路 exit 0；
`python -m pytest -q` → **89/89 通过**（旧文档写的 75/75 与 86/86 均已过时）；
`python -m adt.redlines` → 9/9 已接线；`python -m adt env-audit` → exit 0。

---

## 4. 外部软件：官方来源、精确版本、放置位置

四个工具均**走官方来源、免管理员权限**。本机（2026-11-05）全部已装并实跑验证可用。

| 工具 | 实测版本 | 官方来源（可点击） | 放到哪里 |
|---|---|---|---|
| PK-Sim / MoBi | 12.3.173 / 12.3.136 | **https://github.com/Open-Systems-Pharmacology/PK-Sim/releases** · 官网 https://www.open-systems-pharmacology.org/ | portable ZIP 解压到 `ADT_OSP_DIR/PKSim`、`ADT_OSP_DIR/MoBi`；入口 `PKSim.CLI.exe` |
| micromamba | 2.10.0 | **https://micro.mamba.pm/api/micromamba/win-64/latest**（Linux/macOS 把 `win-64` 换成平台名） | `ADT_MAMBA_EXE`；官方 API 实测 307→conda-forge 的 `micromamba-2.10.0-0.tar.bz2` |
| R + nlmixr2 + rxode2 | 4.5.3 / 5.0.0 / 5.0.2 | conda-forge **https://conda.anaconda.org/conda-forge/** | `ADT_PKPD_ENV`；必须用 `micromamba run -p <env> Rscript ...` |
| qs2 官方二进制 | 0.3.1 | **https://cran.r-project.org/bin/windows/contrib/4.5/qs2_0.3.1.zip** | 覆盖 `<ADT_PKPD_ENV>/lib/R/library/qs2`（见 §6 坑 1） |
| Pharmpy | 2.3.0 | 官方 PyPI `pharmpy-core` | 与主 Python 同环境，bootstrap 自动装 |

**GitHub 在本网络被墙**（实测 `api.github.com` 直连 15 s 超时）。换机下载 OSP 时：

```bash
# 用固定 IP 绕行（IP 会失效，失效时轮换 140.82.116.x 段）
curl --resolve "api.github.com:443:140.82.116.6" \
     https://api.github.com/repos/Open-Systems-Pharmacology/PK-Sim/releases/latest
# objects.githubusercontent.com / codeload 一般可达；下载后解压到 ADT_OSP_DIR
```

`bootstrap.py --external` 不猜 release 资产名：缺失时只打印上述官方网址与目标目录，
由人下载，避免"猜接口"类失败（admetasar3 的教训）。

### 4.1 需要注册 / 授权 / 人机验证的项目（**当场给网址，不要等问**）

| 项目 | 网址 | 需要做什么 | 拿回什么 |
|---|---|---|---|
| OneADMET SI（1.2 GB，**已随包**） | **https://pubs.acs.org/doi/10.1021/acs.jmedchem.6c00049** | 本机 2026-10-30 已过验证下载，2026-11-05 复核并落位；**换机整包拷贝即可**。重下载时：浏览器过 Cloudflare → Supporting Information → "Molecular formula strings (ZIP)"（`jm6c00049_si_002.zip`）→ 解压出 `oneADMET.csv` 放到 `assets/external/oneadmet/` | 35 MB ZIP → 1,197,248,494 B CSV（SHA256 `c0860bf9...`）；完整复现链见 §5.1 |
| ORCA（学术免费，**本机已注册且实装 6.1.1**） | **https://www.faccts.de/customer/** | 本机 36 GB 解压目录 / 293 个 exe 已实跑 H2O 单点通过。**换机需重新注册**：4 字段（姓名/邮箱/机构/密码）、无验证码、密码邮件下发；下载区不支持断点续传 | `ADT_ORCA_DIR` 指向含 `orca.exe` 的目录；不设则自动发现。playbook §2.4 的 PySCF 仍是主线免注册替代 |
| vNN ADMET（需登录） | **https://vnnadmet.bhsai.org/vnnadmet/** | 注册登录 + ALTCHA 工作量证明；凭据写到 `~/.workbuddy/vnn_cred.json` | 凭据文件；缺失时适配器优雅降级为 NoPrediction |
| Simcyp（商业授权） | **https://www.simcyp.com/** | 商业许可（本机探测超时） | 许可；本 skill 只做量级估算，**不内嵌** |
| GastroPlus（商业授权） | **https://www.simulations-plus.com/software/gastroplus/** | 商业许可 | 同上 |
| XenoSite 程序化 API | **https://xenosite.org** | 学术网页免费，API 需商业许可 | 本 skill 只做 readback 回填，不模拟网页提交 |
| Zenodo / OpenADMET | **https://zenodo.org/records/21504733** | 本机 DNS 解析失败，但数据**已随包分发**，无需下载 | — |

---

## 5. 外部数据

| 路径 | 状态 | 许可 |
|---|---|---|
| `assets/external/openadmet/`（train/test/raw + LICENSE + PROVENANCE） | **随包**，无需下载 | CC-BY-4.0（Zenodo 21504733） |
| `assets/external/npass/`（1,307 rat-LD50 + 76 ADME） | **随包**，无需下载 | 学术免费（cite NAR 2026） |
| `assets/herg_reference_ic50.csv`、`assets/controls/` | **随包** | — |
| `assets/external/oneadmet/oneADMET.csv` | **随包**（1.2 GB，2026-11-05 落位并验 SHA256） | ACS SI（免费 Supporting Information） |
| `instances/v350/oneadmet/*.csv`、`instances/v350/tdc/tdc_adme_measurements.csv` | **随包**（模块 L 三组测量长表快照） | 同上 / TDC |
| `tools/*.py`（3 个零硬编码重建脚本） | **随包** | — |

`env-audit` 会把 17 个随包数据/协议文件逐项校验"存在且非空"，并**单独**校验
1.2 GB SI（默认查字节数 + 表头；`--deep` 追加 SHA256 + 行数），缺失即判 required 缺失。

### 5.1 模块 L（跨数据集可迁移性）的逐位复现链

2026-11-05 用随包 SI 从零重跑，两个长表与 2026-10-30 产物**逐字节一致**，
`transfer_profiles.csv` 与既有结论**逐位一致**（OneADMET 11,944 对 / 值级拒绝 0；
OpenADMET_raw 29,258 值 / 拒绝 38 = 0.1299%；TDC_ADME 17,248 对 / 弃权率 1.000）。

```bash
# 1) 量纲探针（映射前强制步骤；pX = -log10(X)、%bound、per-kg 清除率不映射）
python tools/probe_oneadmet_dimensions.py
# 2) 从 1.2 GB SI 重建两组长表（默认校验 SHA256，口径不符直接拒绝）
python tools/build_oneadmet_longtables.py
# 3) 三组一起跑方向性检验（TDC 用随包离线快照，不需要联网）
python -m adt transfer \
  --datasets "instances/v350/oneadmet/oneadmet_measurements.csv=OneADMET_meas,instances/v350/oneadmet/openadmet_raw_measurements.csv=OpenADMET_raw,instances/v350/tdc/tdc_adme_measurements.csv=TDC_ADME" \
  --expected-order "OneADMET_meas,OpenADMET_raw" \
  --outdir instances/v350/oneadmet/transfer
# 4) 可选：需要重新从 TDC 服务器取数时才跑（联网 + 限流冷却；离线复现不必）
python tools/tdc_export.py
```

`retrieved_at` 固定为 SI 取数时刻（属数据内容），故意不用当前时间，
以保证不同机器上的产物可逐字节比对。

---

## 6. 已知环境坑（换机必读）

1. **`library(rxode2)` 挂死 ≠ 缺编译器**。真因是 conda 的 `r-qs2 0.2.1` 与
   RcppParallel 自带 `tbb.dll` 死锁。修法（用变量，不要写死路径）：
   ```bash
   mv  "$ADT_PKPD_ENV/lib/R/library/qs2" "$ADT_PKPD_ENV/lib/R/library/qs2.bak-0.2.1"
   curl -sSLo qs2.zip https://cran.r-project.org/bin/windows/contrib/4.5/qs2_0.3.1.zip
   unzip -q qs2.zip -d "$ADT_PKPD_ENV/lib/R/library/"
   ```
   换完 `rxode2` 4 秒加载、`rxSolve` 一次编译通过，**不需要 Rtools**。
2. **别直接调 `Rscript.exe`**：会报 `error while loading shared libraries: ?`。
   用 `micromamba run -p "$ADT_PKPD_ENV" Rscript ...`（它才设好 PATH / DLL 搜索路径）。
3. **`MAMBA_ROOT_PREFIX` 不要放在长中文路径下**：会崩
   `remove_all: The directory is not empty`。用短 ASCII 路径。
4. **PKSim.CLI 的退出码不可作验收**：`--version` 与 `version` 都返回 **rc=1**，
   但版本串照常写到 stderr。以"有没有产出版本串"为准（与 MODULE_MAP §4.2 同一结论）。
5. **PK-Sim 会静默丢仿真**：`snap -p` 返回 0、日志写 "Project saved"，
   但 `Simulations` 变 0。验收看**产物计数**，不看退出码。化合物层已实测 32/32 逐位一致；
   仿真层未闭环，不得写入材料。
6. **目录存在 ≠ 环境完整**：`env-audit` 判定 R 环境必须真的找到 `Rscript` 可执行文件
   并实跑出 R / nlmixr2 / rxode2 / qs2 四个版本（gmx_MMPBSA 连败 5 轮的教训）。
7. **旧 lock 漂移**：见 §2.1。引用数字时按 `manifest_sha1` 追产物身份，不要按文档版本号。
8. **`pharmpy` 不是 `pharmpy-core`**：见 §2.2。
9. **pytdc 必须 `--no-deps`**：见 §2.2；`setuptools==80.9.0` 是硬要求。
10. **华为云镜像高频请求会短暂 429**：冷却后恢复；bootstrap 自动换源，不要人肉重试。
11. **全局 PYTHONPATH 遮蔽 venv**：运行前 `PYTHONPATH= python ...`（清空）。
12. **pytest 60+ 子进程误报失败**：`tests/conftest.py` 已把 `tmp_path` 固定到
    `tests/.scratch/`，打包/同步时**不要**清理或删除 `.scratch`。
13. **Git Bash 不能执行下载的 .exe**（报 No such file or directory）：用 PowerShell 或 cmd。
14. **Git 行尾**：`.sh` 用 LF、Windows `.bat` 用 CRLF；clone 时 `git config core.autocrlf false`。
15. **`lxml` 必须显式装**：`adt/adapters/vnn.py` 缺它会降级 `html.parser`（功能等价但有回归测试）；
    lock 已钉 `lxml==6.1.3`。
16. **TDC 服务端按 IP 限流**：批量导出加起步冷却 + 指数退避（脚本已内置）。
17. **历史材料里的绝对路径不是可执行指令**：`外部评审材料包_*.md`、
    `L项四方案实测裁决与闭环结果.md` 等文件里的 `C:/Users/...`、`D:/...` 是**当次运行记录**，
    换机后不要照抄；一律改用 §1 的环境变量与相对路径。
18. **换机后 G4 必然告警**：`env_fingerprint.json` 含 Python/平台/库版本；
    `bootstrap.py` 已自动重生成并在材料中声明漂移，这是预期行为，不是故障。
19. **ORCA `--version` 也返回 rc=2**：与 PK-Sim 同类陷阱，版本串在 banner 里
    （`Program Version 6.1.1  -  RELEASE  -`）。`env-audit --deep` 的验收是实跑
    HF/def2-SVP H2O 单点，看 `ORCA TERMINATED NORMALLY` 与
    `FINAL SINGLE POINT ENERGY -75.960838753103 Eh`，不以退出码判定。
20. **OneADMET SI 的哈希就是口径**：`c0860bf9c47806d9867f95b84bdfda8a62c189f891e1d951765fdd283d51034c`，
    738,162 行。换了 SI 版本就不要声称复现 v3.6.1 的 L 项数字；
    `tools/build_oneadmet_longtables.py` 默认会拒绝哈希不符的输入。

---

## 7. 复现四层验证（换机后按顺序做）

| 层 | 命令 | 通过标准 |
|---|---|---|
| 环境层 | `python -m adt env-audit --quiet` | exit 0（必需层全绿）；exit 2 表示仅可选/外部告警，需读报告决定 |
| 深度层 | `python -m adt env-audit --deep --quiet` | exit 0；ORCA 单点 E=-75.960838753103 Eh、1.2 GB SI SHA256 匹配 |
| 测试层 | `python -m pytest -q` | 89/89 通过，exit 0 |
| 命令层 | `python -m adt transfer --help`、`python -m adt.redlines`、`python -m adt env-audit --json-out ...` | 全部 exit 0；红线 9/9 已接线 |
| 结论层 | `python -m adt external` / `baseline` / `benchmark`（必须用 `*_risk.csv` 输入） | 数字与 CHANGELOG v3.5.0/v3.6.0 一致，容差 ±0.001；引用按 `manifest_sha1` |
| 模块 L 结论层 | §5.1 的三条命令 | 两组测量长表与既有产物逐字节一致；`transfer_profiles.csv` 逐位一致 |

`env_audit_report.json` 建议随复现材料归档：它含每个检查项的第一手证据
（版本串、返回码、文件行数），是可以被第三方逐条核对的环境凭证。

---

## 8. 2026-11-05 排查结论（已验证 / 未验证）

**已装且实跑通过**：核心 10 包、可选层 7 项、`PKSim.CLI 12.3.173`、`MoBi`、
`micromamba 2.10.0`、`R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2 + qs2 0.3.1`、
`Pharmpy 2.3.0`、`pytdc 1.1.15`（BenchmarkGroup import）、PySCF 2.14.0（独立 conda 环境）、
OpenMM 8.1.2（独立 conda 环境）、17 个随包数据/协议文件、
**ORCA 6.1.1**（HF/def2-SVP H2O 单点 rc=0，E=-75.960838753103 Eh）、
**OneADMET SI**（1,197,248,494 B / 738,162 行 / SHA256 校验通过）。

**本次从官方来源补装**：`pharmpy-core==2.3.0`、`pytdc==1.1.15`（`--no-deps`）、
`tqdm / fuzzywuzzy / openpyxl / setuptools==80.9.0 / huggingface_hub==2.4.0`。
其中 PyPI 包通过华为云官方镜像下载（实测 pypi.org wheel 下载停滞，见 §1）。

**不重装、已明确登记**：
- `DeepPurpose`：registry 已判本化学类 16 端点中 10 个 UNUSABLE，`deep_learning` 组相关数字属**存档证据**；
  无 adapter 文件、核心 `adt/` 不 import 它，重装需整套 torch 栈且会污染主环境。
- `ORCA`：**已注册且实装 6.1.1**（2026-11-05 复核），纳入 `env-audit` 外部层；
  换机后才需要重新注册下载（§4.1 给网址）。playbook §2.4 的 PySCF 仍是主线免注册替代，
  两者同属 `quantum_chemistry` 独立组，不得当成两张独立票。
- `Simcyp / GastroPlus`：商业授权；本 skill 定位是量级估算，架构上是 hand-off 而非内嵌。

**未验证 / 需人工**：
- 网络层 `env-audit --network` 是**时点快照**：2026-11-05 一次探测里
  ADMETlab3 / ADMET-AI / ProTox3 / ChEMBL / PubChem / BioTransformer / OSP 全部 200，
  而 vNN 超时、SwissADME 403、华为云 PyPI 429；同一批 URL 在另一次探测中均为 200。
  429 / 403 / 超时是限流或瞬时波动，不代表永久不可用，也不代表预测端点可用
  （首页 200 ≠ 预测可用，pkCSM 反例见 registry）。
- ~~OneADMET SI 1.2 GB 需过 Cloudflare~~ → **2026-11-05 已闭环**：ZIP 在
  `~/Downloads/jm6c00049_si_002.zip`，CSV 已落位 `assets/external/oneadmet/`，
  SHA256/行数/表头验过，模块 L 已用随包脚本逐位复现（§5.1）；换机整包拷贝即可。
- `bootstrap.bat` 双击执行：沙箱安全策略禁止从 Bash 调 `cmd.exe`，
  PowerShell 隐式调用会挂起；已做 CRLF/纯 ASCII 静态校验，
  同一逻辑可用 `python bootstrap.py --verify-only` 实测（exit 0）。
- PK-Sim **仿真层**往返未闭环（化合物层 32/32 已验，见坑 5）；
- 三个商业平台无 headless CLI，无法自动化验收；
- 换机到 Linux/macOS 后的 conda-forge R 环境重建耗时未知（repodata 约 294 MB，本机 15 s 仅收 2.5 MB）。
