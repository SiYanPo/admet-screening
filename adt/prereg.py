# -*- coding: utf-8 -*-
"""工作包 P11：源纳入/排除**预注册**（C12 确认偏差通道）+ supersede 重评留痕。

### 评审核心批评

> "mppb 因 ρ 符号翻转被**事后排除**——以不稳健统计做纳入/排除决策，系统性抬高
> '矩阵内一致性'叙事（C12 确认偏差通道）。"

### 处方（本模块落地）

1. **先定标准、后看数据**：源纳入/排除标准先经 `register_criteria` 登记（生成 hash），
   之后任何 `decide` 必须引用该 prereg_id；历史决策（看数据后做的）必须标 `post_hoc=True`
   —— 允许补登记，但**不得伪装成预注册**。
2. **supersede 重评**：以新统计量/新标准触发，事件链上保留（原决策 hash → 新决策 +
   触发统计量 + 理由），append-only、可回放。
3. **哈希链防篡改**：每条事件 sha256(canonical_json + prev_hash)，`verify()` 全链校验，
   `footnote()` 产出可直接引用的报告脚注（登记位置 + 链头 hash）。

### 判据语义（与 C12 一致）

- 统计噪声（ρ 符号翻转、CI 含 0）**不构成排除理由**：正确处置是**保留 + sign_conflict
  标注**（见 reliability.SOURCE_CONFLICT_REASON），而不是剔除后抬高一致性。
- 结构性原因（数据不可用 / 单位口径错误 / 覆盖率 <0.30 / 同源重复）才可排除。

### 诚实边界

- 本模块只管**决策留痕与回放**，不评估源质量本身；评估仍由 source_rho / reliability 产出。
- 历史（post-hoc）决策补登记时必须如实标注，链上可见、不可抹除。
"""

from __future__ import annotations

import hashlib
import io
import json
import os

STRUCTURAL_EXCLUDE_REASONS = (
    "data_unavailable",
    "unit_mismatch",
    "coverage_below_floor",
    "duplicate_source",
    "endpoint_out_of_scope",
)

# ---- R28（评审 R3-2 / A5）：外部时间戳锚定 ----
# 问题：本地 append-only 链只能证明"链内顺序"，**不能证明"先于数据"**——
# 谁都能事后补一条带更早时间戳的事件（本机时钟可改）。
# 处方：把 prereg 文档的哈希提交到第三方存证（OSF / Zenodo / arXiv / 机构仓库），
# 由**第三方**给出不可回改的 deposited_at；本模块负责记录与该锚点的绑定关系。
ANCHOR_REGISTRIES = ("OSF", "Zenodo", "arXiv", "institutional", "other")
_DOI_RE = r"^10\.\d{4,9}/\S+$"
ANCHOR_KEYS = ("registry", "doi", "url", "deposited_at", "doc_sha256", "note")


def _now():
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _parse_dt(raw):
    """宽松解析 ISO 8601 → **naive UTC**（带时区的先换算，naive 视为 UTC）。

    P2.2：时序校验要处理三类真实输入 —— OSF 的 `2026-11-23T03:22:32.070200Z`、
    本地链的 `2026-11-23T10:31:49`、以及只有日期的 `2026-11-23`。
    混用 aware/naive 会在比较时抛 TypeError，因此统一归一到 naive UTC；
    对"数据是否晚于锚定"这种日级判断，UTC 归一不改变结论。
    """
    import datetime

    if raw is None:
        return None
    if isinstance(raw, datetime.datetime):
        dt = raw
    else:
        s = str(raw).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(s)
        except Exception:  # noqa: BLE001
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _h(obj):
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _norm_anchor(anchor):
    """校验并规范化外部锚定信息。**允许留空**（anchor=None → 返回 None）。

    留空不是错误，但 `anchor_status()` 会返回 anchored=False，并在 `footnote()`
    里印 `UNANCHORED`——即"可以没有，但不许假装有"。
    """
    if anchor is None:
        return None
    if not isinstance(anchor, dict):
        raise PreregError("external_anchor 必须是 dict（或 None）")
    a = {k: anchor.get(k) for k in ANCHOR_KEYS if anchor.get(k) not in (None, "")}
    reg = (a.get("registry") or "").strip()
    if reg and reg not in ANCHOR_REGISTRIES:
        raise PreregError("registry 必须是 %s 之一" % (ANCHOR_REGISTRIES,))
    doi = (a.get("doi") or "").strip()
    if doi:
        import re

        if not re.match(_DOI_RE, doi):
            raise PreregError(
                "DOI 形态不合法：%r（应形如 10.17605/OSF.IO/ABCDE）" % doi
            )
    if not (doi or a.get("url")):
        raise PreregError("外部锚定必须给 doi 或 url 之一（否则无法被第三方核验）")
    return a


class PreregError(Exception):
    pass


class Prereg:
    """append-only 预注册事件链（jsonl，每行一事件，hash 链防篡改）。"""

    def __init__(self, log_path):
        self.log_path = log_path
        self.events = []
        if os.path.exists(log_path):
            with io.open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.events.append(json.loads(line))

    # ---- 事件追加 -------------------------------------------------------
    def _append(self, ev_type, payload):
        prev = self.events[-1]["hash"] if self.events else "GENESIS"
        ev = dict(type=ev_type, ts=_now(), payload=payload, prev_hash=prev)
        ev["hash"] = _h(ev)
        self.events.append(ev)
        d = os.path.dirname(os.path.abspath(self.log_path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with io.open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev["hash"]

    # ---- 三类事件 -------------------------------------------------------
    def register_criteria(
        self,
        name,
        criteria,
        note="",
        external_anchor=None,
        prospective_data_window=None,
    ):
        """先定标准（预注册起点）。criteria: dict；返回 prereg_id(=hash)。

        `external_anchor`（R28）：第三方存证的绑定信息，**可留空**。
        形如 ``{"registry":"OSF","doi":"10.17605/OSF.IO/ABCDE",
        "deposited_at":"2026-11-01T10:00:00","doc_sha256":"..."}``。
        给 url 或 doi 之一即可；留空时 `anchor_status()` 会返回 anchored=False。

        `prospective_data_window`（P2.2，2026-11-23 新增）：前瞻数据时间窗声明，
        形如 ``{"rule": "min(data_ts) > anchor_date", "data_ts_source": "labels.csv:collected_at"}``。
        它把"锚定发生在看到数据之前"从**口头承诺**变成**机器可校验的冻结项**：
        锚定后可用 `temporal_validity()` 拿真实数据时间戳反查。
        此前该条只写在 `references/PREREG_ANCHORING_CHECKLIST.md` §5 的"仍是空的"里。
        """
        if not isinstance(criteria, dict) or not criteria:
            raise PreregError("criteria 必须为非空 dict（可机器判定的标准）")
        if prospective_data_window is not None:
            if not isinstance(prospective_data_window, dict):
                raise PreregError("prospective_data_window 必须是 dict（或省略）")
            criteria = dict(criteria)
            criteria["prospective_data_window"] = prospective_data_window
        payload = dict(name=name, criteria=criteria, note=note)
        a = _norm_anchor(external_anchor)
        if a:
            payload["external_anchor"] = a
        return self._append("register_criteria", payload)

    def attach_anchor(self, external_anchor, note=""):
        """**事后**补外部锚定（例：标准先在本机登记，三天后才上传 OSF）。

        这是允许的，但必须留痕：`anchor_status()` 会标 `post_hoc_anchor=True`，
        因为第三方时间戳只能证明"文档提交时刻"，**不能**证明"提交时还没看过数据"。
        """
        return self._append(
            "external_anchor",
            dict(external_anchor=_norm_anchor(external_anchor), note=note),
        )

    def anchor_status(self):
        """返回外部时间戳锚定状态；未锚定时明确禁止"已完成预注册"这类主张。"""
        anchors = []
        first_criteria_ts = None
        for e in self.events:
            p = e.get("payload") or {}
            if e["type"] == "register_criteria" and first_criteria_ts is None:
                first_criteria_ts = e["ts"]
            if p.get("external_anchor"):
                item = dict(p["external_anchor"])
                item.update(ts=e["ts"], via=e["type"])
                anchors.append(item)
        out = dict(
            anchored=bool(anchors),
            n_anchors=len(anchors),
            first_criteria_ts=first_criteria_ts,
            anchors=anchors,
        )
        if not anchors:
            out.update(
                claim_allowed=False,
                warning=(
                    "UNANCHORED：链上只有本机时钟时间戳，无法证明'标准先于数据'"
                    "（本机时钟可改、事后可补登记）。材料中不得声称'已完成预注册'，"
                    "只能写'标准已登记，待第三方时间戳锚定'。"
                ),
            )
            return out
        a = anchors[0]
        post_hoc = a["via"] == "external_anchor"
        # 2026-11-17 修复（同行评审第一手复现）：旧实现无论是否 post_hoc 都把
        # claim_allowed 置 True。但外部评审 C01/C18 的教训是：事后锚定只证明
        # "文档提交时刻"，不证明"提交时未看过数据"，因此**不能**授予"已预注册"
        # 的机器可读资格。SKILL.md 授予条件①把 claim_allowed 当判据，旧行为
        # 会让一个 post_hoc 锚定点一下就满足①——这正是它要防的事。
        # 现在：只有"与标准登记同事件、且锚定时间早于任何数据引用"才可能为 True；
        # post_hoc 一律 False。G9 此前靠自己额外的 post_hoc 分支兜底，
        # 现在原语本身也正确，双重防线。
        out.update(
            doi=a.get("doi"),
            registry=a.get("registry"),
            url=a.get("url"),
            deposited_at=a.get("deposited_at"),
            post_hoc_anchor=post_hoc,
            claim_allowed=not post_hoc,
        )
        if post_hoc:
            out["warning"] = (
                "锚定事件晚于标准登记：第三方时间戳只证明"
                "'文档提交时刻'，不证明'提交时未看过数据'；"
                "claim_allowed 已强制为 False，材料不得据此声称已预注册。"
            )
        return out

    # ---- P2.2：前瞻窗口校验（2026-11-23）-------------------------------
    def temporal_validity(self, data_timestamps):
        """校验"锚定先于数据"：min(data_ts) 必须**晚于**锚定日期。

        为什么单独一条：`anchor_status()` 只能证明"锚定过"，不能证明
        "锚定发生在看到数据之前"。把真实数据的采集时间喂进来，才能把
        G9 从"有锚点"升级为"有锚点**且**时序正确"。

        参数
        ----
        data_timestamps : iterable[str|datetime]
            每条前瞻数据的采集/标签获得时间（ISO 8601）。允许带时区。

        返回
        ----
        dict(ok, reason, anchor_date, n_data, n_violations, min_data_ts,
             early_examples)
            ok=False 时 reason ∈ {no_anchor, no_data, data_before_anchor, bad_timestamp}
        """
        st = self.anchor_status()
        anchors = st.get("anchors") or []
        anchor_raw = None
        if anchors:
            anchor_raw = anchors[0].get("deposited_at") or anchors[0].get("ts")
        anchor_dt = _parse_dt(anchor_raw)
        if anchor_dt is None:
            return dict(
                ok=False,
                reason="no_anchor",
                anchor_date=None,
                n_data=0,
                n_violations=0,
                min_data_ts=None,
                early_examples=[],
                note="无外部锚定或锚定缺日期：先锚定再谈时序",
            )

        rows = list(data_timestamps or [])
        parsed, bad, early = [], [], []
        for raw in rows:
            dt = _parse_dt(raw)
            if dt is None:
                bad.append(raw)
                continue
            parsed.append(dt)
            if dt <= anchor_dt:
                early.append(str(raw))
        if not parsed:
            return dict(
                ok=False,
                reason="no_data",
                anchor_date=anchor_raw,
                n_data=0,
                n_violations=len(bad),
                min_data_ts=None,
                early_examples=[],
                note="没有可解析的数据时间戳",
            )

        mn = min(parsed)
        ok = (not early) and (not bad)
        reason = "ok" if ok else ("data_before_anchor" if early else "bad_timestamp")
        return dict(
            ok=ok,
            reason=reason,
            anchor_date=anchor_raw,
            n_data=len(parsed),
            n_violations=len(early) + len(bad),
            min_data_ts=mn.isoformat(),
            early_examples=early[:5] + [str(b) for b in bad[:5]],
            note=(
                "时序正确：全部数据晚于锚定"
                if ok
                else "存在不晚于锚定时刻的数据：这些记录**不得**进入主分析集"
            ),
        )

    def temporal_window_declared(self):
        """返回链上声明的 prospective_data_window（若有）。"""
        for e in reversed(self.events):
            p = e.get("payload") or {}
            c = p.get("criteria") or {}
            if isinstance(c, dict) and c.get("prospective_data_window"):
                return c["prospective_data_window"]
        return None

    def decide(
        self, source, endpoint, action, prereg_id, reason, evidence="", post_hoc=False
    ):
        """登记一条纳入/排除决策。

        action ∈ include/exclude/annotate。post_hoc=True 标记历史补登记。
        exclude 必须给结构性理由（见 STRUCTURAL_EXCLUDE_REASONS），
        除非 post_hoc=True（历史决策如实登记，但链上可见其事后性）。
        """
        if action not in ("include", "exclude", "annotate"):
            raise PreregError("action 必须为 include/exclude/annotate")
        if (
            not post_hoc
            and action == "exclude"
            and reason not in STRUCTURAL_EXCLUDE_REASONS
        ):
            raise PreregError(
                "预注册链上新排除必须给结构性理由（%s）；统计噪声不是排除理由——"
                "用 annotate+sign_conflict 保留源"
                % (", ".join(STRUCTURAL_EXCLUDE_REASONS))
            )
        crit = self._criteria_of(prereg_id)
        if crit is None:
            raise PreregError("prereg_id 未找到（须先 register_criteria）")
        return self._append(
            "decision",
            dict(
                source=source,
                endpoint=endpoint,
                action=action,
                prereg_id=prereg_id,
                reason=reason,
                evidence=evidence,
                post_hoc=bool(post_hoc),
            ),
        )

    def supersede(
        self,
        source,
        endpoint,
        action,
        prereg_id,
        reason,
        trigger_stat,
        supersedes_hash,
        evidence="",
    ):
        """supersede 重评：action/reason + 触发统计量 + 被替代事件的 hash。"""
        if action not in ("include", "exclude", "annotate"):
            raise PreregError("action 必须为 include/exclude/annotate")
        if not self._criteria_of(prereg_id):
            raise PreregError("prereg_id 未找到")
        if not any(e.get("hash") == supersedes_hash for e in self.events):
            raise PreregError(
                "supersedes_hash 不在事件链中（留痕必须指向真实历史事件）"
            )
        if trigger_stat is None:
            raise PreregError("supersede 必须携带触发重评的统计量")
        return self._append(
            "supersede",
            dict(
                source=source,
                endpoint=endpoint,
                action=action,
                prereg_id=prereg_id,
                reason=reason,
                trigger_stat=trigger_stat,
                supersedes_hash=supersedes_hash,
                evidence=evidence,
            ),
        )

    # ---- 查询 / 校验 / 回放 ---------------------------------------------
    def _criteria_of(self, prereg_id):
        for e in self.events:
            if e["type"] == "register_criteria" and e["hash"] == prereg_id:
                return e["payload"]["criteria"]
        return None

    def verify(self):
        """哈希链校验。返回 dict(ok, checked, broken_at)。"""
        prev = "GENESIS"
        for i, e in enumerate(self.events):
            want = dict(
                type=e["type"],
                ts=e["ts"],
                payload=e["payload"],
                prev_hash=e["prev_hash"],
            )
            if e["prev_hash"] != prev or _h(want) != e.get("hash"):
                return dict(ok=False, checked=i, broken_at=i)
            prev = e["hash"]
        return dict(ok=True, checked=len(self.events), broken_at=None)

    def replay(self, source=None, endpoint=None):
        """回放当前状态：按事件顺序应用 decision/supersede，返回最新动作表。"""
        state = {}
        for e in self.events:
            if e["type"] not in ("decision", "supersede"):
                continue
            p = e["payload"]
            key = (p["source"], p["endpoint"])
            if source and key[0] != source:
                continue
            if endpoint and key[1] != endpoint:
                continue
            state[key] = dict(
                action=p["action"],
                reason=p["reason"],
                last_event=e["type"],
                hash=e["hash"],
                trigger_stat=p.get("trigger_stat"),
            )
        if source or endpoint:
            return {
                k: v
                for k, v in state.items()
                if (not source or k[0] == source) and (not endpoint or k[1] == endpoint)
            }
        return state

    def footnote(self):
        """报告脚注：全部纳入/排除决策登记位置 + 链头 hash（P11 处方第 3 条）。"""
        v = self.verify()
        n = sum(1 for e in self.events if e["type"] in ("decision", "supersede"))
        head = self.events[-1]["hash"] if self.events else "GENESIS"
        a = self.anchor_status()
        if a["anchored"]:
            anchor_line = "外部时间戳锚定：%s（doi=%s，第三方提交日 %s）%s" % (
                a.get("registry") or "registry?",
                a.get("doi") or a.get("url"),
                a.get("deposited_at") or "(未记录)",
                "；⚠ 锚定晚于登记（post_hoc）" if a.get("post_hoc_anchor") else "",
            )
        else:
            anchor_line = (
                "外部时间戳锚定：**UNANCHORED**（无第三方存证，"
                "不得声称已完成预注册）"
            )
        return (
            "源纳入/排除决策预注册留痕：共 %d 条（事件链校验 %s），"
            "登记文件 %s，链头 hash=%s；%s"
            % (
                n,
                "通过" if v["ok"] else "失败",
                os.path.basename(self.log_path),
                head[:16],
                anchor_line,
            )
        )
