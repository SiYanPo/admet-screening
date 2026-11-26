# 第三方时间戳（RFC 3161）—— 补充存证，不等同于预注册

## 这是什么

`PREREG_STAGE1_PACKAGE.md` 在 **2026-11-23 16:23:52 (GMT+8) = 08:23:52 GMT** 由公共时间戳权威
**freeTSA**（RFC 3161 TSA）签发了时间戳：

| 项 | 值 |
|---|---|
| 状态 | `Granted` |
| 序列号 | `0x0A6E1091` |
| 被签文件 | `PREREG_STAGE1_PACKAGE.md` |
| 文件 SHA256 | `3399cdf5e4465081d6e4d9f8a2f84500f2507e93d229473936bffb7a97da2cf6` |
| 请求 | `PREREG_STAGE1_PACKAGE.md.tsq`（69 B） |
| 响应 | `PREREG_STAGE1_PACKAGE.md.tsr`（4,643 B，含 TSA 签名与 genTime） |

生成与解析：

```bash
openssl ts -query -data PREREG_STAGE1_PACKAGE.md -sha256 -cert -out PREREG_STAGE1_PACKAGE.md.tsq
curl -s -H "Content-Type: application/timestamp-query" --data-binary @PREREG_STAGE1_PACKAGE.md.tsq \
     -o PREREG_STAGE1_PACKAGE.md.tsr https://freetsa.org/tsr
openssl ts -reply -in PREREG_STAGE1_PACKAGE.md.tsr -text
```

完整验签（需 freeTSA 的 CA 证书）：

```bash
curl -sO https://freetsa.org/files/cacert.pem
openssl ts -verify -in PREREG_STAGE1_PACKAGE.md.tsr \
        -queryfile PREREG_STAGE1_PACKAGE.md.tsq -CAfile cacert.pem
```

## 它能证明什么、不能证明什么

**能**：`PREREG_STAGE1_PACKAGE.md` 的这份字节在 2026-11-23 08:23:52 GMT 之前**已经存在**，
且由第三方（freeTSA）签字——本机时钟改不了它。

**不能**：
1. **不是注册号**。没有公开记录页、没有 DOI、没有「我承诺按此执行」的公开声明。
2. **不解决"公开可核验"**。`.tsr` 目前只在本仓库里；必须先随 Zenodo 存证公开，
   第三方才有东西可验。因此它**不能**单独满足 `adt.prereg` 的锚定要求
   （锚定要求 `doi` 或**公开可访问的** `url`）。
3. 因此 `prereg-status` 仍为 rc=3（UNANCHORED）。这份时间戳是**补强证据**，不是替身。

## 与 Zenodo 的分工

- Zenodo 存证（restricted）：给 **DOI + 公开元数据 + 可引用的承诺**；
- 本目录的 `.tsr`：给 **不可回改的时刻证明**，并作为附件一起上传到 Zenodo，
  让"文件内容"与"时间"两件事互相咬合（DOI 证明公开性，TSA 证明不早于/不晚于某时刻）。
