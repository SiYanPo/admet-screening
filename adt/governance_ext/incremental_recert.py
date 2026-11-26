# -*- coding: utf-8 -*-
"""盲区3：增量式知识融合 / 自动化再认证（Incremental Re-certification）。

科学半衰期会让成千上万条历史预测逐渐过期。若每条都推给科学家，
就是"再认证疲劳"。本模块用算力换人力：

  - 新法规/新知识发布 → 生成版本化 KnowledgeUpdate（带 guidance_hash）；
  - 系统按适用性过滤历史记录，**静默批量重跑**；
  - 只有当新旧判定（tier / verdict / direction）发生冲突时才报警；
  - 一致的大批量重算只产生一个 quiet summary；
  - checkpoint 支持中断续跑，不重复报警。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class KnowledgeUpdate:
    rule_id: str
    guidance: str
    effective_date: str
    applies_to: dict  # {"endpoint": "dili", "scaffold":可选}
    guidance_hash: str = ""

    @staticmethod
    def make(rule_id, guidance, effective_date, applies_to):
        gh = hashlib.sha256(
            json.dumps(
                {
                    "rule_id": rule_id,
                    "guidance": guidance,
                    "effective_date": effective_date,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return KnowledgeUpdate(rule_id, guidance, effective_date, applies_to, gh)


def applicable(update, record):
    for k, v in (update.applies_to or {}).items():
        if record.get(k) != v:
            return False
    return True


def reevaluate(record, update, new_rule_fn):
    """调用新知识规则；异常 fail-closed 为 UNDETERMINED 并报警。"""
    try:
        out = new_rule_fn(dict(record), update)
        return {
            "tier": out.get("tier_ceiling", record.get("tier_ceiling", "T0")),
            "verdict": out.get("verdict", record.get("verdict", "UNDETERMINED")),
        }
    except Exception as exc:
        return {"tier": "T0", "verdict": "UNDETERMINED", "error": str(exc)[:120]}


def _classify(old, new):
    if old.get("tier") != new.get("tier") or old.get("verdict") != new.get("verdict"):
        return "CONFLICT"
    if new.get("error"):
        return "ERROR"
    return "STABLE"


class IncrementalRecertification:
    def __init__(self, update: KnowledgeUpdate, new_rule_fn, *, checkpoint=None):
        self.update = update
        self.new_rule_fn = new_rule_fn
        self.processed = set((checkpoint or {}).get("processed", []))
        self.alerts = list((checkpoint or {}).get("alerts", []))
        self.started_at = datetime.now(timezone.utc).isoformat()

    def run(self, historical_records, *, dry_run=False):
        """批量静默重跑；只把冲突/错误放进 alerts。dry_run 不写 checkpoint。"""
        batch_alerts = []
        n_stable = n_skip = 0
        for i, rec in enumerate(historical_records):
            rid = str(rec.get("id") or i)
            if rid in self.processed:
                n_skip += 1
                continue
            if not applicable(self.update, rec):
                n_stable += 1  # 不适用 = 静默通过，不报警
                if not dry_run:
                    self.processed.add(rid)
                continue
            old = {
                "tier": rec.get("tier_ceiling", "T0"),
                "verdict": rec.get("verdict", "UNDETERMINED"),
            }
            new = reevaluate(rec, self.update, self.new_rule_fn)
            status = _classify(old, new)
            if status in ("CONFLICT", "ERROR"):
                alert = {
                    "record_id": rid,
                    "status": status,
                    "old": old,
                    "new": new,
                    "rule_id": self.update.rule_id,
                    "guidance_hash": self.update.guidance_hash,
                    "needs_human": True,
                }
                batch_alerts.append(alert)
                if not dry_run:
                    self.alerts.append(alert)
            else:
                n_stable += 1
            if not dry_run:
                self.processed.add(rid)
        return {
            "update": {
                "rule_id": self.update.rule_id,
                "guidance_hash": self.update.guidance_hash,
                "effective_date": self.update.effective_date,
            },
            "n_input": len(historical_records),
            "n_processed_now": len(historical_records) - n_skip,
            "n_stable": n_stable,
            "n_skipped_checkpoint": n_skip,
            "n_alert": len(batch_alerts),
            "alerts": batch_alerts,
            "summary": "仅 %d/%d 条冲突需人工；其余静默再认证"
            % (len(batch_alerts), len(historical_records)),
        }

    def checkpoint(self):
        return {
            "processed": sorted(self.processed),
            "alerts": self.alerts,
            "started_at": self.started_at,
            "rule_id": self.update.rule_id,
            "guidance_hash": self.update.guidance_hash,
        }
