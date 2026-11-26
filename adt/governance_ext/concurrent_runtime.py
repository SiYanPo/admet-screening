# -*- coding: utf-8 -*-
"""并发处理与状态隔离：对象池 + contextvars 请求上下文 + 多进程架构钩子。

原型里 `_TAUT_ENUM = {cap: enumerator}` 是模块级单例。单线程没问题，
并发 100~1000 请求时若 RDKit C++ 对象内部状态被共享，会出现：
  - 结果串扰（A 分子的互变体被算到 B 上）；
  - 若用一把大锁串行化，100 线程排队又会造成事实挂死。

改造为**有界对象池**：
  - 每 cap 一个池，最多 max_instances 个 RDKit enumerator；
  - 锁只保护"创建实例"，绝不包住 Enumerate 调用；
  - 队列 acquire 带超时；超时即 fail-closed 跳过互变枚举并标注原因，
    而不是无限等待 → 结构上不可能死锁；
  - 每个请求拿到独占实例，用完 finally 归还。

预算与判定状态全部放进 RequestContext，由 contextvars 绑定：
  - 线程/asyncio task 各自独立，绝不共享可变全局；
  - 多进程（Celery/Ray）每个 worker 自有池，任务只携带可序列化上下文，
    通过 fork_safe_reset() 在子进程重建池，杜绝 fork 继承的 fd/锁状态。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .budget import TimeBudget


class PoolExhausted(Exception):
    pass


class SafeTautomerPool:
    """有界、超时、无死锁的 enumerator 池。线程安全。"""

    def __init__(
        self,
        cap: int,
        *,
        max_instances: int = 4,
        acquire_timeout_s: float = 2.0,
        factory: Callable[[], Any] = None,
    ):
        if max_instances < 1:
            raise ValueError("max_instances 必须 >= 1")
        self.cap = int(cap)
        self.max_instances = int(max_instances)
        self.acquire_timeout_s = float(acquire_timeout_s)
        self._factory = factory or self._default_factory
        self._available: queue.Queue = queue.Queue()
        self._create_lock = threading.Lock()
        self._created = 0
        self._stats_lock = threading.Lock()
        self._stats = {
            "acquired": 0,
            "released": 0,
            "timeouts": 0,
            "max_wait_ms": 0.0,
            "created": 0,
        }

    def _default_factory(self):
        from rdkit.Chem.MolStandardize import rdMolStandardize

        e = rdMolStandardize.TautomerEnumerator()
        e.SetMaxTautomers(int(self.cap))
        return e

    def _take(self):
        # 快路径：池里有现成实例，完全无锁
        try:
            return self._available.get_nowait(), 0.0
        except queue.Empty:
            pass
        # 慢路径：仅创建动作加锁；锁内不做任何 RDKit 计算
        with self._create_lock:
            if self._created < self.max_instances:
                e = self._factory()
                self._created += 1
                with self._stats_lock:
                    self._stats["created"] = self._created
                return e, 0.0
        t0 = time.monotonic()
        try:
            e = self._available.get(timeout=self.acquire_timeout_s)
        except queue.Empty as exc:
            with self._stats_lock:
                self._stats["timeouts"] += 1
            raise PoolExhausted(
                "互变枚举池耗尽: cap=%d, max_instances=%d, timeout=%.2fs"
                % (self.cap, self.max_instances, self.acquire_timeout_s)
            ) from exc
        return e, (time.monotonic() - t0) * 1000.0

    @contextlib.contextmanager
    def acquire(self):
        e, wait_ms = self._take()
        with self._stats_lock:
            self._stats["acquired"] += 1
            if wait_ms > self._stats["max_wait_ms"]:
                self._stats["max_wait_ms"] = round(wait_ms, 2)
        try:
            yield e
        finally:  # 异常路径也必须归还，杜绝泄漏导致的"锁死"
            self._available.put(e)
            with self._stats_lock:
                self._stats["released"] += 1

    def enumerate_states(self, mol) -> tuple[bool, dict]:
        """返回 (state_sensitive, meta)。池耗尽 → 显式 not_evaluated，绝不留 None。"""
        try:
            with self.acquire() as enum:
                from rdkit import Chem

                tauts = enum.Enumerate(mol)
                distinct = {Chem.MolToSmiles(t) for t in tauts}
                return len(distinct) > 1, {
                    "tautomer_pool": "ok",
                    "n_distinct": len(distinct),
                }
        except PoolExhausted as exc:
            return "not_evaluated", {
                "tautomer_pool": "exhausted",
                "detail": str(exc)[:120],
            }
        except Exception as exc:
            return "not_evaluated", {"tautomer_pool": "error", "detail": str(exc)[:120]}

    def stats(self):
        with self._stats_lock:
            return dict(self._stats)


_POOLS: dict[int, SafeTautomerPool] = {}
_POOL_REGISTRY_LOCK = threading.Lock()
_POOL_CONFIG = {"max_instances": 4, "acquire_timeout_s": 2.0}


def configure_pools(*, max_instances=4, acquire_timeout_s=2.0):
    """启动时配置；已有池不受影响（避免运行中改配置引发竞态）。"""
    global _POOL_CONFIG
    with _POOL_REGISTRY_LOCK:
        _POOL_CONFIG = {
            "max_instances": int(max_instances),
            "acquire_timeout_s": float(acquire_timeout_s),
        }


def get_taut_pool(cap: int) -> SafeTautomerPool:
    with _POOL_REGISTRY_LOCK:
        p = _POOLS.get(int(cap))
        if p is None:
            p = SafeTautomerPool(int(cap), **_POOL_CONFIG)
            _POOLS[int(cap)] = p
        return p


def fork_safe_reset():
    """Celery/Ray/prefork worker 初始化时调用：丢弃父进程继承的池。"""
    with _POOL_REGISTRY_LOCK:
        _POOLS.clear()


def pool_stats():
    with _POOL_REGISTRY_LOCK:
        return {str(cap): p.stats() for cap, p in _POOLS.items()}


# ---------- 请求级状态隔离 ----------
@dataclass
class RequestContext:
    request_id: str
    mode: str = "fast"
    budget: TimeBudget = None
    guard: dict = field(default_factory=dict)
    directive: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)


_CTX: contextvars.ContextVar = contextvars.ContextVar(
    "admet_request_context", default=None
)


def bind_request(ctx: RequestContext):
    """返回 token；调用方必须在 finally 中 reset_request(token)。"""
    return _CTX.set(ctx)


def reset_request(token):
    _CTX.reset(token)


def current_request():
    return _CTX.get()


def new_request(request_id, *, mode="fast") -> RequestContext:
    return RequestContext(
        request_id=request_id, mode=mode, budget=TimeBudget(profile=mode)
    )


class AsyncBudgetRunner:
    """异步入口：每个 task 只操作自己 ctx 里的 budget，无共享可变状态。"""

    def __init__(self, ctx: RequestContext):
        self.ctx = ctx

    async def call(self, fn, source, *args, **kwargs):
        budget = self.ctx.budget
        if not budget.can_call(source):
            budget.mark_skipped(source, "BUDGET_EXHAUSTED")
            return {
                "source": source,
                "domain_flag": "out_of_domain",
                "value": None,
                "reason": "BUDGET_EXHAUSTED",
            }
        timeout = budget.per_api_timeout()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs), timeout=timeout
            )
        except asyncio.TimeoutError:
            budget.mark_skipped(source, "TIMEOUT")
            return {
                "source": source,
                "domain_flag": "out_of_domain",
                "value": None,
                "reason": "TIMEOUT",
            }
        except Exception as exc:
            budget.mark_skipped(source, "ERROR")
            return {
                "source": source,
                "domain_flag": "out_of_domain",
                "value": None,
                "reason": "ERROR",
                "detail": str(exc)[:100],
            }
        budget.mark_done(source)
        return result
