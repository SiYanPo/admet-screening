# CLI 物理拆分方案（K1：4,943 行 → <800 行 dispatcher）

> 状态：**方案已冻结，代码未执行**。理由见 §4 风险裁决；本文件把"未做"变成"有精确路径的待办"。
> 依据实测：`adt/cli.py` 共 4,943 行；`cmd_*` 函数位于 111–3928 行（约 3,818 行）；
> `main()` 与 `add_parser(...)` 注册区位于 3974–4943 行（约 970 行）。
> 78 条命令已在 `adt/command_roles.py` 声明 layer/evidence_role/contract，`validate_registry()` 实测 (True, [], [])。

## 目标结构

```
adt/cli.py                  <800 行：仅 main() + dispatch + 统一错误码
adt/cli_parsers.py          ~970 行：从注册区原样搬迁，按 layer 分组函数
adt/cli_core.py             ~700 行：normalize/saturate/validate/... (14 条)
adt/cli_sources.py          ~650 行：web/chembl/vnn/... (13 条)
adt/cli_decision.py         ~650 行：gate/qaf/ablate/desire/... (13 条)
adt/cli_evidence.py         ~1,500 行：release-check/prereg/estimand/... (31 条)
adt/cli_experimental.py     ~350 行：SHADOW 层命令 (7 条)
```

## 三步执行（顺序不可换）

1. **A：抽 parser（低风险）**
   把 3974–4943 行按 layer 切成 5 个 `add_<layer>_parsers(sub)` 函数到 `cli_parsers.py`。
   `cli.py` 只保留 `main()` 调用它们。验收：`adt --help` 与全部 78 个子命令 `--help` 逐字一致
   （用 `tests/test_help_all.py` 同进程 `CLI.main` 路径比对）；命令名零漂移。

2. **B：抽 dispatch（中风险）**
   按 `command_roles.ROLES[cmd]["layer"]` 把 `cmd_*` 函数整体搬到 5 个层模块；
   `cli.py` 的 dispatch 改为 `getattr(layer_module, "cmd_"+cmd)(a)`。
   验收：`ADT_ENFORCE_ROLES=1 python -m adt.cli release-check` rc=0；`validate_registry()` 仍 True；
   `tests/test_peer_review_fixes.py` 全过。

3. **C：统一错误码（高风险，最后做）**
   给每个 `cmd_*` 返回统一 `CmdResult(code, payload, evidence_role)`；
   把 `raise SystemExit(rc)` 收敛到 `main()` 一处。
   验收：`tests/test_cli_exit_codes.py`（新增）覆盖 0/2/3/4 四类退出码；
   旧脚本 `fullrun_20261122/runlog.jsonl` 的 73 条命令 rc 回放一致。

## 不可省略的回归门禁（每步都要跑）

```bash
python -m pytest tests/test_help_all.py tests/test_redline_wiring.py tests/test_peer_review_fixes.py -q
ADT_ENFORCE_ROLES=1 python -m adt.cli release-check
python tools/command_usage_census.py   # 确认命令总数仍为 78
```

## 为什么现在不做（风险裁决）

- 角色声明 + fail-closed 门禁已经在生产链上（G8 9/9 接线），**治理目的已达成**；
- 物理拆分只降低维护成本、不提高科学可信度，而 CLI 是 78 条命令的唯一入口，一次回归失败会毁掉整个复现链；
- 用户规则"简单优先"：不为工程美学引入新的失败点。
- 优先级：U1 锚定 > SOURCE_DEPENDENCE/PACT 差异化 > 论文主表/图 > K1 物理拆分。
