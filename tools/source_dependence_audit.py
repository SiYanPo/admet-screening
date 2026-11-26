# -*- coding: utf-8 -*-
"""来源独立性/来源依赖审计（reviewer kill-shot #1 的机器化防线）。

背景（2026-11-23 文献检索）：PACT(arXiv:2609.01662) 与 data-incest/covariance-intersection 文献
明确指出：多源若共享训练数据/基础模型/描述符生态，"一致"不等于互证，投票会重复计数。
本 skill 已有 `independence_group` 约定（同组只记 1 独立票），但从来没有机器校验：
  · 3 个源在注册表里缺 independence_group；
  · `deeppurpose` 在注册表=deep_learning、在 model card=descriptor_ml（冲突）。
本工具把这件事变成可重算、可进 CI 的门禁。

输出：references/SOURCE_DEPENDENCE.md（人读表）
运行：
  python tools/source_dependence_audit.py            # 生成文档并打印问题
  python tools/source_dependence_audit.py --check    # CI：有问题 exit 1
"""

from __future__ import annotations

import argparse
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load():
    import yaml

    reg = (
        yaml.safe_load(
            io.open(
                os.path.join(ROOT, "references", "02_source_registry.yaml"),
                encoding="utf-8",
            )
        )
        or {}
    )
    cards = (
        yaml.safe_load(
            io.open(
                os.path.join(ROOT, "references", "source_cards.yaml"), encoding="utf-8"
            )
        )
        or {}
    )
    return reg.get("sources") or [], cards.get("sources") or []


def audit():
    regs, cards = load()
    cmap = {c.get("id"): c for c in cards}
    rows, issues = [], []
    for s in regs:
        name = s.get("name")
        g_reg = s.get("independence_group")
        card = cmap.get(name)
        g_card = (card or {}).get("independence_group")
        train = (card or {}).get("training_data")
        status = s.get("status")
        active = status == "ok"
        if not g_reg and active:
            issues.append(
                dict(
                    source=name,
                    kind="missing_independence_group",
                    why="注册表缺 independence_group：不得计入独立票",
                )
            )
        if card and g_card and g_reg and g_card != g_reg and active:
            issues.append(
                dict(
                    source=name,
                    kind="group_conflict",
                    why="注册表=%s 但 model card=%s" % (g_reg, g_card),
                )
            )
        if card and not train:
            issues.append(
                dict(
                    source=name,
                    kind="training_data_undeclared",
                    why="model card 缺 training_data 声明",
                )
            )
        rows.append(
            dict(
                source=name,
                label=s.get("label"),
                status=status,
                reg_group=g_reg or "—",
                card_group=g_card or "—",
                training_data=str(train or "—")[:70],
                has_card=bool(card),
            )
        )
    return rows, issues


def to_md(rows, issues):
    groups = {}
    for r in rows:
        if r["reg_group"] and r["reg_group"] != "—":
            groups.setdefault(r["reg_group"], []).append(r["source"])
    L = [
        "# 来源依赖与独立票审计（自动生成，请勿手改）",
        "",
        "> 生成器：`tools/source_dependence_audit.py --check` 可作 CI 门禁。",
        "> 规则：`independence_group` 相同的源**只记 1 张独立票**（注册表 §头部两票半原则）；",
        "> 共享训练数据/基础模型/近邻池的源不得当作相互独立的证据。",
        "",
        "## 独立组（能投几票）",
        "",
        "| 独立组 | 源 | 有效独立票 |",
        "|---|---|---|",
    ]
    for g, names in sorted(groups.items()):
        L.append("| `%s` | %s | **1** |" % (g, "、".join("`%s`" % n for n in names)))
    L += [
        "",
        "## 逐源明细",
        "",
        "| 源 | status | 注册表组 | model card 组 | 训练数据声明 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        L.append(
            "| `%s` | %s | %s | %s | %s |"
            % (
                r["source"],
                r["status"] or "—",
                r["reg_group"],
                r["card_group"],
                r["training_data"],
            )
        )
    L += ["", "## 待闭合问题（%d）" % len(issues), ""]
    if issues:
        for i in issues:
            L.append("- **%s** `%s`：%s" % (i["kind"], i["source"], i["why"]))
    else:
        L.append("- 无")
    L += [
        "",
        "## 审稿边界声明",
        "",
        "本表只记录**声明层面的**来源依赖；真正的数值独立性还需看跨源残差相关"
        "（见 `adt/reliability.py`），二者缺一不可。共享 TDC/PubChem 训练生态的两个源"
        "即使算法族不同，也不得当作两次独立确认。",
        "",
    ]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    rows, issues = audit()
    p = os.path.join(ROOT, "references", "SOURCE_DEPENDENCE.md")
    if a.check:
        if issues:
            for i in issues:
                print("[source-dep] %s %s: %s" % (i["kind"], i["source"], i["why"]))
            print("[source-dep] %d 项未闭合" % len(issues))
            return 1
        print(
            "[source-dep] OK (%d 源, %d 组)"
            % (len(rows), len({r["reg_group"] for r in rows}))
        )
        return 0
    io.open(p, "w", encoding="utf-8", newline="\n").write(to_md(rows, issues))
    print(
        "[source-dep] %d 源 / %d 组 / %d 问题 -> references/SOURCE_DEPENDENCE.md"
        % (
            len(rows),
            len({r["reg_group"] for r in rows if r["reg_group"] != "—"}),
            len(issues),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
