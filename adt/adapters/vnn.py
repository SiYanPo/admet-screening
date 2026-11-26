# -*- coding: utf-8 -*-
"""vNN-ADMET 适配器（v2.2.1：**已端到端验证**，2026-10-28）。

v2.2.0 时只有人工桥（无凭据无法验证自动化）。2026-10-28 用真实账号跑通全链路后
按 Adapter 基类收编；人工桥保留为凭据不可用时的降级通道。

实测链路（本次全部复核）：
  1) 登录：`POST /vnnadmet/login`，字段 `username`/`password`，无验证码。
     失败 → 302 到 `login.xhtml?status=error`；成功 → 302 站内页且 `home.xhtml` 200。
  2) ALTCHA：`GET /public/challenge` → 求 n 使 `sha256(salt+str(n))==challenge`
     （maxnumber=1e6，0.5–1.5 s），把 base64(JSON{...}) 放进字段 `altcha`。
  3) 提交：GET `admetpredinput.xhtml` 开视图 → **同一视图内**连续 POST 逐个 add
     （每次带回新的 `jakarta.faces.ViewState`，total 计数必须 +1）→
     ajax（`Faces-Request: partial/ajax`）点 submit → 响应 XML 出现
     `<redirect url="...checkjob.xhtml?myjob=<hash>">`。
  4) 取结果：GET checkjob 页 → `parse_checkjob()`。

**C65 教训（本次实测）**：就绪判据不能用"正则数有几行 33 td"——`<table.*?</table>`
非贪婪正则遇嵌套表只数到外层，2 个分子的作业页会被判成"还在算"（实测白等 6 分钟，
结果其实早就绪）。**唯一可靠判据是用提取器本身（parse_checkjob）能拿到预期行数。**

输出语义（不要误读）：
  * 站点只给 **Yes/No 类别**，不给概率 → 入长表 value=1/0、unit=class，note 写明非概率；
  * `NoPrediction` = 该分子在该端点**无高置信预测（域外）** → domain_flag=out_of_domain
    **且不带数值**（契约），绝不当 0 或阴性；
  * MRTD 是"最大推荐治疗剂量"→ 参照端点 `vnn_mrtd`（role=reference，不裁决）；
  * CYP×5 / BBB / Pgp×2 / Cytotoxicity / HLM / MMP 无对应规则端点，**不映射**
    （计入 meta["unmapped_endpoints"]），避免"无规则端点"刷屏（C43）。
"""

import base64
import csv
import hashlib
import io
import json
import os
import re
import time

import requests

from .base import Adapter, AdapterResult
from .. import schema

BASE = "https://vnnadmet.bhsai.org/vnnadmet"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TIMEOUT = 90

# 15 个端点（站点固定顺序；前 15 个 td 与后 15 个 td 各一套，需交叉校验）
ENDPOINTS = [
    "DILI",
    "Cytotoxicity",
    "HLM",
    "CYP1A2",
    "CYP3A4",
    "CYP2D6",
    "CYP2C9",
    "CYP2C19",
    "BBB",
    "Pgp_inhibitor",
    "Pgp_substrate",
    "hERG",
    "MMP",
    "AMES",
    "MRTD",
]

# 3 个质量端点（有阈值规则、可与其它源跨组计票）
QUALITY_MAP = {
    "DILI": "dili",
    "hERG": "herg",
    "AMES": "ames",
    "MMP": "mmp",
}  # MMP 于 v2.3.1 升级：两独立组（+ADMET-AI SR-MMP）
# 其余 12 个：**进入裁决管线但不投票**（role=reference，见 03_endpoint_rules.yaml）。
# 升级为质量端点的条件：① 有文献阈值；② 有第 2 个独立方法组。二者缺一即保持参照。
REFERENCE_MAP = {
    "Cytotoxicity": "vnn_cytotoxicity",
    "HLM": "vnn_hlm",
    "CYP1A2": "cyp1a2_inhibition",
    "CYP3A4": "cyp3a4_inhibition",
    "CYP2D6": "cyp2d6_inhibition",
    "CYP2C9": "cyp2c9_inhibition",
    "CYP2C19": "cyp2c19_inhibition",
    "BBB": "vnn_bbb",
    "Pgp_inhibitor": "vnn_pgp_inhibitor",
    "Pgp_substrate": "vnn_pgp_substrate",
    "MRTD": "vnn_mrtd",
}

DEFAULT_CRED = os.path.join(os.path.expanduser("~"), ".workbuddy", "vnn_cred.json")
INGEST_COLS = ["compound_id", "endpoint", "value", "unit", "note"]


def _make_soup(html):
    """构造 BeautifulSoup，优先 lxml，缺失时退回内置 html.parser。

    背景（2026-10-31 干净机复现实测）：lxml 是 C 扩展，历史上未写进
    requirements，照 lock 装完的环境里 `BeautifulSoup(html, "lxml")` 会抛
    `FeatureNotFound`，导致 checkjob 解析直接崩。本解析路径只用到
    find_all("table"/"tr"/"td") 与 get_text，两个解析器结果等价，故降级安全。
    """
    from bs4 import BeautifulSoup

    last = None
    for parser in ("lxml", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception as exc:  # FeatureNotFound / 解析器加载失败
            last = exc
    raise RuntimeError(
        "beautifulsoup4 无可用解析器（lxml 与 html.parser 均失败）: %r" % (last,)
    )


def parse_checkjob(html):
    """解析 checkjob 结果页 -> [dict(ID, SMILES, <15 端点>)]。

    兼容扁平 33-td 行（14 分子页）与嵌套表（2 分子页）；扫所有表、用 set1/set2
    交叉校验并去重（页面同时存在可见/隐藏两套结果）。
    """
    import warnings

    try:
        from bs4 import XMLParsedAsHTMLWarning

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except Exception:
        pass

    soup = _make_soup(html)
    out, seen = [], set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) != 33:
                continue
            txt = [td.get_text(" ", strip=True).strip() for td in tds]
            name, smiles = txt[16], txt[17]
            if not name or name in seen:
                continue
            first, second = txt[1:16], txt[18:33]
            ok = True
            for a, b in zip(first, second):
                a_norm = "" if a in ("", "NoPrediction") else a
                if a_norm == "":
                    if b != "NoPrediction":
                        ok = False
                        break
                elif a_norm != b:
                    ok = False
                    break
            if not ok:
                continue
            row = {"ID": name, "SMILES": smiles}
            row.update(dict(zip(ENDPOINTS, second)))
            out.append(row)
            seen.add(name)
    return out


class VnnAdapter(Adapter):
    name = "vnn_admet"
    version = "web-2026-10"
    status = "ok"
    min_interval_s = 1.0
    max_retries = 1

    def __init__(
        self,
        registry_entry=None,
        verbose=True,
        user=None,
        password=None,
        cred_path=None,
        max_per_job=10,
        poll_timeout=1800,
        poll_interval=20,
        raw_dir="",
    ):
        Adapter.__init__(self, registry_entry, verbose)
        self.raw_dir = raw_dir
        self.max_per_job = max_per_job
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self.user, self.password = self._load_cred(user, password, cred_path)

    # ---------------- 凭据 ----------------
    @staticmethod
    def _load_cred(user, password, cred_path=None):
        if user and password:
            return user, password
        u = os.environ.get("VNN_USER", "")
        p = os.environ.get("VNN_PASS", "")
        if u and p:
            return u, p
        for path in [cred_path, DEFAULT_CRED]:
            if path and os.path.exists(path):
                try:
                    d = json.load(io.open(path, encoding="utf-8"))
                    if d.get("username") and d.get("password"):
                        return d["username"], d["password"]
                except Exception:
                    continue
        return "", ""

    def _need_cred(self):
        if not (self.user and self.password):
            raise RuntimeError(
                "vNN 需要账号。三种提供方式任一：\n"
                "  1) 环境变量 VNN_USER / VNN_PASS；\n"
                "  2) 凭据文件 ~/.workbuddy/vnn_cred.json："
                '{"username": "...", "password": "..."}；\n'
                "  3) 人工桥：web --source vnn --prepare-only 生成任务单，网页跑完再 ingest。"
            )

    # ---------------- 网络 ----------------
    def open_session(self):
        self._need_cred()
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        s.get(BASE + "/login.xhtml", timeout=TIMEOUT)
        r = s.post(
            BASE + "/login",
            data={"username": self.user, "password": self.password},
            headers={
                "Referer": BASE + "/login.xhtml",
                "Origin": "https://vnnadmet.bhsai.org",
            },
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        loc = r.headers.get("Location", "")
        if "status=error" in loc or r.status_code not in (301, 302, 303, 307):
            raise RuntimeError(
                "登录被拒（HTTP %s，Location=%r）" % (r.status_code, loc)
            )
        h = s.get(BASE + "/home.xhtml", timeout=TIMEOUT, allow_redirects=False)
        if h.status_code != 200:
            raise RuntimeError("登录看似成功但 home.xhtml -> HTTP %s" % h.status_code)
        self.log("登录 OK（user=%s）" % self.user)
        return s

    def solve_altcha(self, s):
        """求 ALTCHA proof-of-work；解出后自校验，防 challenge 过期。"""
        ch = s.get(BASE + "/public/challenge", timeout=TIMEOUT).json()
        if str(ch.get("algorithm", "SHA-256")).upper() != "SHA-256":
            raise RuntimeError("未知 ALTCHA 算法：%r" % ch.get("algorithm"))
        salt, target = ch["salt"], ch["challenge"]
        n = None
        for i in range(int(ch["maxnumber"]) + 1):
            if hashlib.sha256((salt + str(i)).encode()).hexdigest() == target:
                n = i
                break
        if n is None:
            raise RuntimeError("ALTCHA 在 maxnumber 内无解")
        assert hashlib.sha256((salt + str(n)).encode()).hexdigest() == target
        payload = {
            "algorithm": ch.get("algorithm", "SHA-256"),
            "challenge": target,
            "number": n,
            "salt": salt,
            "signature": ch.get("signature", ""),
            "test": False,
        }
        self.log("ALTCHA 已解（n=%d）" % n)
        return base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()

    @staticmethod
    def _viewstate(html):
        """取 j_idt32 表单自己的 ViewState；取不到退回全文最后一个。

        （实测：页面存在多个 ViewState 字段，必须取表单作用域内的最后一个，
        否则 ajax 提交会被判视图失效。）
        """
        m = re.search(r'<form id="j_idt32".*?</form>', html, re.S)
        scope = m.group(0) if m else html
        found = re.findall(
            r'name="jakarta\.faces\.ViewState"[^>]*value="([^"]+)"', scope
        )
        if not found:
            found = re.findall(
                r'name="jakarta\.faces\.ViewState"[^>]*value="([^"]+)"', html
            )
        if not found:
            raise RuntimeError("未取到 jakarta.faces.ViewState（页面结构变了？）")
        return found[-1]

    @staticmethod
    def _total(html):
        """站点文案固定为 "Total query compounds: N"；取不到返回 -1（同已验证实现）。"""
        txt = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html))
        m = re.search(r"Total query compounds\s*:?\s*(\d+)", txt)
        return int(m.group(1)) if m else -1

    def submit_job(self, s, compounds, job_name):
        """同视图逐个 add → ajax 提交 → 返回 checkjob URL。"""
        r = s.get(BASE + "/admetpredinput.xhtml", timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError("admetpredinput.xhtml HTTP %s" % r.status_code)
        vs = self._viewstate(r.text)
        for c in compounds:
            before = self._total(r.text)
            r = s.post(
                BASE + "/admetpredinput.xhtml",
                data={
                    "j_idt32": "j_idt32",
                    "j_idt32:jobName": job_name,
                    "j_idt32:smilesString": c["calc_smiles"],
                    "j_idt32:compoundName": c["compound_id"],
                    "j_idt32:addQueryCompound": "j_idt32:addQueryCompound",
                    "jakarta.faces.ViewState": vs,
                },
                headers={"Referer": BASE + "/admetpredinput.xhtml"},
                timeout=TIMEOUT,
            )
            after = self._total(r.text)
            if after != before + 1:
                raise RuntimeError(
                    "添加 %s 失败（total %d -> %d）——多半是 "
                    "ViewScoped 视图被重建" % (c["compound_id"], before, after)
                )
            vs = self._viewstate(r.text)
            time.sleep(0.25)
        self.log("已加入 %d 个分子，提交中…" % len(compounds))

        rs = s.post(
            BASE + "/admetpredinput.xhtml",
            data={
                "j_idt32": "j_idt32",
                "j_idt32:jobName": job_name,
                "j_idt32:smilesString": "",
                "j_idt32:compoundName": "",
                "j_idt32:submitAdmetPredButton": "j_idt32:submitAdmetPredButton",
                "jakarta.faces.ViewState": vs,
                "jakarta.faces.partial.ajax": "true",
                "jakarta.faces.source": "j_idt32:submitAdmetPredButton",
                "jakarta.faces.partial.execute": "@all",
                "jakarta.faces.partial.render": "j_idt32",
            },
            headers={
                "Referer": BASE + "/admetpredinput.xhtml",
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        red = re.search(r'<redirect url="([^"]+)"', rs.text)
        if not red:
            raise RuntimeError(
                "提交未返回 redirect（%d B）：%s" % (len(rs.text), rs.text[:160])
            )
        url = red.group(1)
        return url if url.startswith("http") else "https://vnnadmet.bhsai.org" + url

    def poll_job(self, s, url, n_expected):
        """C65：就绪判据 = 提取器能拿到 n_expected 行（不是数 33-td 正则）。"""
        t0 = time.time()
        last = ""
        while time.time() - t0 < self.poll_timeout:
            r = s.get(url, timeout=TIMEOUT)
            try:
                rows = parse_checkjob(r.text)
            except Exception as exc:  # noqa: BLE001
                rows, last = [], "解析异常：%s" % exc
            if len(rows) >= n_expected:
                self.log(
                    "结果就绪：%d 行（等待 %ds）" % (len(rows), int(time.time() - t0))
                )
                return rows, r.text
            last = "已解析 %d/%d 行" % (len(rows), n_expected)
            self.log("计算中（%s），%d s 后重查" % (last, self.poll_interval))
            time.sleep(self.poll_interval)
        raise RuntimeError("轮询超时（%ds）：%s" % (self.poll_timeout, last))

    # ---------------- 原始留档（完整 15 端点） ----------------
    def save_raw(self, parsed, html, url, job):
        """把完整 15 端点宽表 + 结果页 HTML 落盘。

        C67（本次重跑发现）：长表只应放**决策相关**端点（3 个质量 + MRTD），
        但把 CYP×5/BBB/Pgp×2/Cytotoxicity/HLM/MMP 直接丢掉会让"重跑对账"
        变成"新表里没有 → 全判变化"。**不参与裁决 ≠ 不保存**：
        完整结果落宽表，供审计与跨批次对比。
        """
        if not self.raw_dir:
            return ""
        os.makedirs(self.raw_dir, exist_ok=True)
        p = os.path.join(self.raw_dir, "vnn_wide.csv")
        cols = ["ID", "SMILES"] + ENDPOINTS
        exists = os.path.exists(p)
        with io.open(
            p, "a", encoding="utf-8-sig" if not exists else "utf-8", newline=""
        ) as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            if not exists:
                w.writeheader()
            for r in parsed:
                w.writerow({k: r.get(k, "") for k in cols})
        hp = os.path.join(
            self.raw_dir, "vnn_checkjob_%s.html" % url.split("myjob=")[-1][:12]
        )
        io.open(hp, "w", encoding="utf-8").write(html)
        self.log("原始宽表 -> %s；结果页 -> %s" % (p, os.path.basename(hp)))
        return p

    # ---------------- 行转换 ----------------
    def to_measurements(self, parsed, prov):
        rows, unmapped = [], set()
        for r in parsed:
            cid = r["ID"]
            for ep in ENDPOINTS:
                v = (r.get(ep) or "").strip()
                if ep in QUALITY_MAP:
                    canon = QUALITY_MAP[ep]
                    if v in ("Yes", "No"):
                        rows.append(
                            schema.measurement(
                                cid,
                                canon,
                                1 if v == "Yes" else 0,
                                "class",
                                self.name,
                                self.version,
                                "predicted",
                                "",
                                prov,
                                "vNN %s=%s（站点只给类别 Yes/No，不给概率）" % (ep, v),
                            )
                        )
                    else:
                        rows.append(
                            schema.measurement(
                                cid,
                                canon,
                                "",
                                "class",
                                self.name,
                                self.version,
                                "out_of_domain",
                                "",
                                prov,
                                "NoPrediction：该端点无高置信预测（Outside applicability domain）",
                            )
                        )
                elif ep in REFERENCE_MAP:
                    canon = REFERENCE_MAP[ep]
                    if ep == "MRTD":
                        if re.match(r"^[0-9.]+$", v or ""):
                            rows.append(
                                schema.measurement(
                                    cid,
                                    canon,
                                    float(v),
                                    "mg/day",
                                    self.name,
                                    self.version,
                                    "predicted",
                                    "",
                                    prov,
                                    "vNN MRTD（最大推荐治疗剂量；分类模型衍生，仅作参照）",
                                )
                            )
                    elif v in ("Yes", "No"):
                        rows.append(
                            schema.measurement(
                                cid,
                                canon,
                                1 if v == "Yes" else 0,
                                "class",
                                self.name,
                                self.version,
                                "predicted",
                                "",
                                prov,
                                "vNN %s=%s（参照端点：无阈值、单方法组，不参与投票）"
                                % (ep, v),
                            )
                        )
                    else:
                        rows.append(
                            schema.measurement(
                                cid,
                                canon,
                                "",
                                "class",
                                self.name,
                                self.version,
                                "out_of_domain",
                                "",
                                prov,
                                "NoPrediction：无高置信预测（Outside applicability domain）",
                            )
                        )
                else:
                    unmapped.add(ep)
        return rows, sorted(unmapped)

    # ---------------- 上层 ----------------
    def run(self, compounds, chemical_class="", **kw):
        res = AdapterResult()
        ok, why = self.is_allowed(chemical_class)
        if not ok:
            self.log("SKIP：化学类 %r 被登记为不可用（%s）" % (chemical_class, why))
            res.meta["skipped"] = why
            return res
        if not compounds:
            return res
        qa = self.pre_batch(compounds, chemical_class=chemical_class, **kw)
        if qa:
            res.meta["batch_qa"] = qa

        try:
            s = self.open_session()
        except Exception as exc:  # noqa: BLE001
            self.log("登录失败：%s" % exc)
            res.meta["errors"] = [
                dict(compound_id=c["compound_id"], error=str(exc)) for c in compounds
            ]
            return res

        jobs, rows = [], []
        unmapped = set()
        chunks = [
            compounds[i : i + self.max_per_job]
            for i in range(0, len(compounds), self.max_per_job)
        ]
        for bi, chunk in enumerate(chunks, 1):
            job = "admet_%s_%d" % (time.strftime("%m%d%H%M"), bi)
            try:
                url = self.submit_job(s, chunk, job)
                self.log(
                    "[批 %d/%d] 作业 %s" % (bi, len(chunks), url.split("myjob=")[-1])
                )
                parsed, html = self.poll_job(s, url, len(chunk))
                self.save_raw(parsed, html, url, job)
            except Exception as exc:  # noqa: BLE001
                self.log("[批 %d/%d] 失败：%s" % (bi, len(chunks), exc))
                res.meta.setdefault("errors", []).append(
                    dict(
                        compound_id=",".join(c["compound_id"] for c in chunk),
                        error=str(exc),
                    )
                )
                continue
            jobs.append(dict(job=job, url=url, n=len(parsed)))
            part, unm = self.to_measurements(parsed, url)
            rows.extend(part)
            unmapped.update(unm)
            self.log(
                "[批 %d/%d] 完成：%d 分子 / %d 行"
                % (bi, len(chunks), len(parsed), len(part))
            )

        res.measurements = rows
        res.meta.update(
            jobs=jobs,
            n_jobs=len(jobs),
            n_compounds=len({m["compound_id"] for m in rows}),
            unmapped_endpoints=sorted(unmapped),
        )
        return res

    def run_one(self, compound, chemical_class="", **kw):
        r = self.run([compound], chemical_class=chemical_class, **kw)
        return AdapterResult(r.measurements, r.metabolites, r.meta)

    # ---------------- 人工桥（凭据不可用时的降级通道） ----------------
    def prepare(self, compounds, outdir):
        os.makedirs(outdir, exist_ok=True)
        p = os.path.join(outdir, "vnn_tasks.csv")
        with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(
                fh, fieldnames=["compound_id", "calc_smiles", "formula", "urls"]
            )
            w.writeheader()
            for c in compounds:
                w.writerow(
                    dict(
                        compound_id=c["compound_id"],
                        calc_smiles=c["calc_smiles"],
                        formula=c.get("formula", ""),
                        urls=BASE,
                    )
                )
        self.log(
            "待提交清单 -> %s（%d 个分子；单作业上限 %d）"
            % (p, len(compounds), self.max_per_job)
        )
        self.log("读回契约：%s" % ",".join(INGEST_COLS))
        return p

    def ingest(self, path):
        with io.open(path, encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError("空文件: %s" % path)
        missing = [c for c in INGEST_COLS if c not in rows[0]]
        if missing:
            raise ValueError("缺列: %s（契约列=%s）" % (missing, INGEST_COLS))
        from .. import endpoints as _ep

        out = []
        for r in rows:
            raw = (r.get("endpoint") or "").strip()
            canon = _ep.canonical_name(raw) or raw
            val = (r.get("value") or "").strip()
            out.append(
                schema.measurement(
                    r["compound_id"],
                    canon,
                    val,
                    r.get("unit", ""),
                    self.name,
                    self.version,
                    ("manual" if val else "out_of_domain"),
                    "",
                    BASE,
                    r.get("note", ""),
                )
            )
        self.log("ingest %d 行 -> 长表" % len(out))
        return AdapterResult(out, [])
