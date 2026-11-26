# 公开承诺存证（INTERIM，非 DOI）

## 做了什么

Zenodo 邮箱确认邮件始终未到（收件箱/垃圾箱均无），OSF 平台侧禁用项目创建。
换思路后，把冻结协议的**公开承诺文本**发布到可匿名公开、带创建时间与 365 天保留期的第三方粘贴服务，
并以此完成机器可读锚定。

| 项 | 值 |
|---|---|
| 公开 URL | **https://dpaste.com/9TRMMK4Z5** |
| 创建时间 | 2026-11-24T01:21:35+08:00（页面显示 expires in 365 days） |
| 文本原件 | `anchors/commitment_PREREG_STAGE1_20261124.txt` |
| 被承诺文档 | `PREREG_STAGE1_PACKAGE.md`，SHA256 `3399cdf5e4465081d6e4d9f8a2f84500f2507e93d229473936bffb7a97da2cf6` |
| 独立时间证明 | RFC3161 / freeTSA，serial `0x0A6E1091`，2026-11-23T08:23:52 GMT（`.tsq`/`.tsr` 在 `anchors/tsa/`） |
| 锚定结果 | `prereg-status` **rc=0**，`claim_allowed=True`，`post_hoc_anchor=False`，`n_anchors=1` |
| 冻结项 | `prospective_data_window.rule = min(data_ts) > anchor_date`（在 via=register_criteria 的同事件里） |

第三方复查命令：

```bash
curl -s https://dpaste.com/9TRMMK4Z5 | grep 3399cdf5e4   # 公开页含文档哈希
openssl ts -verify -in anchors/tsa/PREREG_STAGE1_PACKAGE.md.tsr \
  -queryfile anchors/tsa/PREREG_STAGE1_PACKAGE.md.tsq -CAfile cacert.pem
python -m adt.cli prereg-status --log prereg/prereg.jsonl   # rc=0
```

## 它证明了什么、没证明什么

**能证明**：这份精确字节的协议、冻结命题与前瞻时间窗，在 2026-11-24 01:21 之前已经公开存在；
且 RFC3161 时间戳独立证明同一文档在 2026-11-23 08:23 GMT 已存在。两者均不依赖本机时钟。

**不能证明 / 必须披露**：
1. **这不是 DOI、不是 OSF/Zenodo 注册号**。材料中只能写"公开承诺存证（interim public commitment, non-registry）"，
   **禁止**写"registered on OSF/Zenodo"或"已获预注册 DOI"。
2. dpaste 保留 365 天，**不能作为永久引用**。投稿前必须升级到 Zenodo/Zenodo 同类注册表 DOI；
   升级后保留本 URL 作为**过渡期证明链**（先有 paste，再有 DOI，顺序一致、无回改）。
3. 粘贴服务不提供同行评审或寄存保障；它只是"公开 + 时间戳"。
4. 机器闸门 `claim_allowed=True` 表示"存在可第三方核验的公开锚点与冻结项"，
   **不表示**期刊会把它当作 Registered Report 的注册号。

## 升级路径（拿到 Zenodo 邮箱确认后）

```bash
python tools/zenodo_deposit.py            # restricted + DOI，自动附 SHA256SUMS.txt
python tools/prereg_anchor_stage1.py --registry Zenodo --url <record> --doi <doi> \
  --deposited-at <ISO>                    # 第二条锚点，形成多锚链（n_anchors=2）
python -m adt.cli prereg-status            # 仍 rc=0，claim_allowed=True
```

升级后把本文件 §"必须披露"第 1–2 条替换成 DOI 表述，并在 cover letter 里说明过渡链。
