# -*- coding: utf-8 -*-
"""ADMETlab 429 守护：反复重试直到成功（可续跑、全量留痕）。

背景（C76）：ADMETlab 3.0 的限流是**站点侧封禁窗口**，实测连续 5 轮 429，
单次进程内那套"最多退避 1 小时"的序列经常撑不到窗口打开。与其在代码里堆更长的
sleep，不如把它做成**可中断、可续跑的外部守护**：每次失败只记一行日志、等固定间隔
再来一次，成功即落盘退出。

用法：
  python examples/admetlab_until_success.py --in out/compounds.csv --outdir out \\
      --interval 480 --max-hours 6

判定成功的唯一标准：长表里**有行**（不是 HTTP 200、不是"页面像结果页"）。
失败一律记 status（post-429 / no-csrf / no-result-id / dl-xxx），不猜、不编。
"""
import argparse
import io
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import schema                                    # noqa: E402
from adt.adapters.admetlab3 import AdmetlabAdapter        # noqa: E402


def log(path, msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_compounds(path):
    """复用 CLI 的双格式加载（CSV 带表头 / TSV 无表头）。"""
    from adt.cli import load_compounds_csv
    return load_compounds_csv(path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--interval", type=float, default=480,
                    help="两次尝试之间的间隔秒数（默认 480 = 8 min）")
    ap.add_argument("--max-hours", type=float, default=6,
                    help="最长守护小时数（默认 6 h）")
    ap.add_argument("--force", action="store_true", help="已有结果也重跑")
    ap.add_argument("--first-2", action="store_true",
                    help="先只提交前 2 个分子探窗口（推荐，成功后再全量）")
    a = ap.parse_args(argv)

    os.makedirs(a.outdir, exist_ok=True)
    logp = os.path.join(a.outdir, "admetlab_retry.log")
    outp = os.path.join(a.outdir, "measurements_admetlab.csv")

    if os.path.exists(outp) and not a.force:
        n = len(schema.read_measurements(outp))
        if n:
            log(logp, "已有结果 %d 行 -> %s，跳过（--force 可重跑）" % (n, outp))
            return 0

    comps = load_compounds(a.input)
    if not comps:
        log(logp, "输入为空，退出")
        return 2
    if a.first_2:
        comps = comps[:2]
    log(logp, "守护启动：%d 个分子，间隔 %.0f s，上限 %.1f h"
        % (len(comps), a.interval, a.max_hours))

    t_end = time.time() + a.max_hours * 3600
    attempt = 0
    while time.time() < t_end:
        attempt += 1
        ad = AdmetlabAdapter(verbose=False, raw_dir=a.outdir,
                             backoff=[0], max_wait_s=0)
        res = ad.run(comps)
        n = len(res.measurements)
        if n:
            schema.write_measurements_checked(outp, res.measurements)
            log(logp, "✅ 第 %d 次尝试成功：%d 行长表 -> %s"
                % (attempt, n, outp))
            return 0
        errs = res.meta.get("errors") or []
        status = (errs[0].get("error", "")[:120] if errs else "未知（0 行）")
        log(logp, "✗ 第 %d 次失败：%s" % (attempt, status))
        left = t_end - time.time()
        if left <= 0:
            break
        wait = min(a.interval * (1 + random.random() * 0.2), left)
        log(logp, "  等待 %.0f s 后重试（剩余 %.1f h）" % (wait, left / 3600))
        time.sleep(wait)

    log(logp, "⚠ 守护到期仍未成功（共 %d 次尝试）。%s"
        % (attempt, "可用 --interval 加大间隔或稍后再跑；已有落盘宽表仍可离线复算。"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
