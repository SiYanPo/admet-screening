# 复现性三件套（REPRODUCIBILITY，P7 / §4-2）

> 对应处方：**P7（U7 / §4-2）**。状态：🟡 框架已立（`manifest.py` 存在），lockfile/digest 待生成。
> 目标：干净机器一条命令起容器复现核心数字。

## 1. 三件套
| 件 | 内容 | 落点 |
|---|---|---|
| ① lockfile | `pip install --require-hashes` 的带 hash 锁定文件 | 新增 `requirements.lock.txt`（由 `pip freeze` + `pip hash` 生成） |
| ② 容器镜像 | Docker / Singularity 镜像 **digest**（非 tag） | `Dockerfile` + `image_digest.txt` |
| ③ 结果指纹链 | 每个关键数字生成机器可读 `manifest.json` | `adt/manifest.py`（已存在，扩到四元组） |

## 2. manifest.json 四元组（守护项06 升级目标）
```json
{
  "value": 0.6274,
  "script_sha": "a1b2c3...",      // 生成该数字的脚本 sha256
  "data_sha": "d4e5f6...",        // 输入数据 sha256
  "env_digest": "sha256:7a8b...",  // 容器/环境 digest
  "generated_at": "2026-10-31T14:31:00+08:00"
}
```
每个 `out_ext/run_*.py` 在写结论时同时产出对应 `manifest.json`，使"命令 → 数据 hash → 环境指纹 → 结论"四元组可审计。

## 3. 环境锚点持久性（U7）
- RDKit 由 ADMET-AI 安装链降版而来——链条稳定性须验证：lockfile 用 hash 级锁定，
  容器镜像带 digest，数据资产（assets/external/）带 sha256 清单。
- 升级 RDKit/numpy 须先在隔离环境验证 75/75 pytest 全绿，再更新 lockfile。
- **2026-10-31 已实测**：新建干净 venv 按 `requirements.lock` 装完，75/75 通过（见
  `BLACKLIST_CLOSEOUT.md` §6）。该轮同时暴露 lock 漏写 `lxml`，已补 `lxml==6.1.3`。

## 4. 外部源 adapter 合规真空（§4-5，见 ADAPTER_COMPLIANCE.md）
7 个外部工具 adapter 的 ToS 与自动访问合规须显式审查，推广给研究生前是硬性门禁。

**验收**：干净机器 `docker run <digest> /run_all.sh` 复现核心数字；manifest.json 四元组齐全。
状态：🟡 docker digest 待生成；lockfile 已存在且经干净 venv 实测 75/75 通过，
但 `pip hash` 级哈希未跑（需 `pip-compile --generate-hashes`）。
