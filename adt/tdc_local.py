# -*- coding: utf-8 -*-
"""本地 TDC ADMET_Group 切分读取器（不依赖 `tdc` 包）。

## 为什么需要它
原脚本一律 `from tdc import BenchmarkGroup`。这在有网的开发机上没问题，
但它把"能跑基准"绑定在一个**非核心依赖**上：`tdc` 未安装时脚本直接
`ModuleNotFoundError` 崩掉（2026-11-01 实测：`run_p8_mmp_regression.py` 与
`run_external_holdout.py` 三个端点全部因此失败，而数据其实早已缓存在本地）。

TDC 的 BenchmarkGroup 缓存布局是稳定的：
    <cache>/admet_group/<name>/train_val.csv
    <cache>/admet_group/<name>/test.csv
两列：`Drug`（SMILES）、`Y`（标签）。直接读这两个 CSV 即可，
不引入 tdc/pytdc 的安装负担，也不再触发联网。

`tdc` 若可用则仍优先用它（保证与官方口径完全一致），否则回落到 CSV。
"""

import os

import pandas as pd


def dataset_dir(cache, name):
    return os.path.join(cache, "admet_group", name.lower())


def is_available(cache, name):
    d = dataset_dir(cache, name)
    return os.path.exists(os.path.join(d, "train_val.csv")) and os.path.exists(
        os.path.join(d, "test.csv")
    )


def load_split(cache, name):
    """返回 `{"train_val": DataFrame, "test": DataFrame}`。

    列保证含 `Drug` / `Y`。优先走官方 `tdc` 包；不可用时读本地 CSV。
    """
    try:
        from tdc import BenchmarkGroup  # noqa: F401

        bg = BenchmarkGroup(name="ADMET_Group", path=cache)
        d = bg.get(name)
        return {"train_val": d["train_val"], "test": d["test"]}
    except Exception:  # noqa: BLE001
        pass
    if not is_available(cache, name):
        raise FileNotFoundError(
            "找不到 %s 的本地切分（%s/train_val.csv、test.csv），"
            "且 tdc 包不可用。请先下载一次 TDC ADMET_Group 缓存。"
            % (name, dataset_dir(cache, name))
        )
    d = dataset_dir(cache, name)
    out = {}
    for split, fn in (("train_val", "train_val.csv"), ("test", "test.csv")):
        df = pd.read_csv(os.path.join(d, fn))
        missing = {"Drug", "Y"} - set(df.columns)
        if missing:
            raise ValueError(
                "%s 缺少列 %s（实际列：%s）" % (fn, sorted(missing), list(df.columns))
            )
        out[split] = df
    return out
