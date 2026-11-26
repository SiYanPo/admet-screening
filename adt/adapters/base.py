# -*- coding: utf-8 -*-
"""适配器基类：统一限流、重试、溯源、对照集校验。

每个源的适配器只实现两件事：
  1) fetch(compound) -> list[long rows] + list[metabolite rows]
  2) control()  —— 返回该源在"本化学类"上是否可用的证据

为什么要把对照集写进基类：本项目实测过"四个源在 DILI 上给出四种失效"
（ADMETlab 14/14 阳、ADMET-AI 0/14 阳、ProTox 13/14 阴、vNN 13/14 拒绝预测），
如果每次都靠人肉判断"这个源的 0 是真 0 还是没覆盖"，一定会再犯。
"""

import time
import traceback


class AdapterResult(object):
    def __init__(self, measurements=None, metabolites=None, meta=None):
        self.measurements = measurements or []
        self.metabolites = metabolites or []
        self.meta = meta or {}

    def __repr__(self):
        return "<AdapterResult m=%d met=%d meta=%s>" % (
            len(self.measurements),
            len(self.metabolites),
            {k: self.meta.get(k) for k in list(self.meta)[:3]},
        )


class Adapter(object):
    name = "base"
    version = ""
    status = "unknown"  # ok | dead | license_required | manual
    min_interval_s = 0.0  # 同一进程内的最小调用间隔
    max_retries = 2

    def __init__(self, registry_entry=None, verbose=True):
        self.reg = registry_entry or {}
        self.verbose = verbose
        self._last_call = 0.0

    def log(self, msg):
        if self.verbose:
            print("[%s] %s" % (self.name, msg), flush=True)

    def throttle(self):
        dt = time.time() - self._last_call
        if dt < self.min_interval_s:
            time.sleep(self.min_interval_s - dt)
        self._last_call = time.time()

    def is_allowed(self, chemical_class):
        """化学类白名单：某个类被登记为不可用时直接拒绝，而不是给一堆假数字。"""
        blocked = self.reg.get("blocked_classes") or []
        for b in blocked:
            if b.get("class") == chemical_class:
                return False, b.get("reason", "该类已登记为不可用")
        return True, ""

    def enforce_profile(self, profile=None):
        """R24/S6：适配器基类强制合规检查（绕过 CLI 直接调用也会被拦）。"""
        from adt import compliance

        if not getattr(self, "skip_compliance", False):
            compliance.enforce(self.name, profile)
        return True

    def run_one(self, compound, chemical_class="", **kw):
        self.enforce_profile(kw.pop("profile", None))
        raise NotImplementedError

    def pre_batch(self, compounds, chemical_class="", **kw):
        """批前钩子（B1 跨批锚点，C56）。

        协议原文（06_playbook §8）：对照必须**混入每一批**，不是事后补测。
        v2.1 及更早的 bt 适配器只在"某分子 0 产物"时才惰性跑对照——整批都
        >0 时该批从未做过漂移检查，等于协议形同虚设。
        返回 list[dict]（批级 QA 记录），由 run() 存入 meta["batch_qa"]。
        """
        return []

    def run(self, compounds, chemical_class="", **kw):
        res = AdapterResult()
        ok, why = self.is_allowed(chemical_class)
        if not ok:
            self.log("SKIP：化学类 %r 被登记为不可用（%s）" % (chemical_class, why))
            res.meta["skipped"] = why
            return res
        qa = self.pre_batch(compounds, chemical_class=chemical_class, **kw) or []
        if qa:
            res.meta["batch_qa"] = qa
            drift = [q for q in qa if q.get("drift")]
            if drift:
                res.meta["batch_drift"] = drift
                self.log("<< BATCH_DRIFT %d 条：跨批比较需降级" % len(drift))
        for i, c in enumerate(compounds, 1):
            cid = c["compound_id"]
            for attempt in range(self.max_retries + 1):
                try:
                    r = self.run_one(c, chemical_class=chemical_class, **kw)
                    res.measurements.extend(r.measurements)
                    res.metabolites.extend(r.metabolites)
                    self.log("[%d/%d] %s ok" % (i, len(compounds), cid))
                    break
                except Exception as exc:
                    if attempt >= self.max_retries:
                        self.log(
                            "[%d/%d] %s FAILED: %s" % (i, len(compounds), cid, exc)
                        )
                        res.meta.setdefault("errors", []).append(
                            dict(
                                compound_id=cid,
                                error=str(exc),
                                trace=traceback.format_exc()[-600:],
                            )
                        )
                        break
                    wait = 5 * (attempt + 1)
                    self.log(
                        "%s 重试 %d/%d，等 %ds（%s）"
                        % (cid, attempt + 1, self.max_retries, wait, exc)
                    )
                    time.sleep(wait)
        return res
