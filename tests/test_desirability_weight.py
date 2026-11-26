# -*- coding: utf-8 -*-
"""U13 回归：desirability 的指数权重（Derringer-Suich 1980）。

验收点：
  1) 等权时与旧实现逐位一致（向后兼容）
  2) 加权几何平均 = exp(Σ w·ln d / Σ w)
  3) **任一 d=0 → D=0**（Derringer-Suich 的定义性质，不能被权重绕过）
  4) 权重只改"重要性"，不改"短板惩罚"：w 很大也不会把 0 救回来
  5) 非法权重（0/负/非数）退化到等权，不抛异常
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.desirability import _geo  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


print("== 1) 等权 = 旧行为 ==")
check("geo([0.25,1.0])=0.5", abs(_geo([0.25, 1.0]) - 0.5) < 1e-12, _geo([0.25, 1.0]))
check("全部权重=1 等价无权重",
      abs(_geo([0.25, 1.0], [1, 1]) - _geo([0.25, 1.0])) < 1e-12)

print("== 2) 加权公式 ==")
got = _geo([0.25, 1.0], [3, 1])
want = math.exp((3 * math.log(0.25) + 1 * math.log(1.0)) / 4)
check("w=[3,1] 与解析式一致", abs(got - want) < 1e-12, (got, want))
check("偏向低分项（0.25 < 0.354 < 0.5）", 0.25 < got < 0.5, got)
check("w=[1,3] 偏向 1.0（结果 > 0.5）", _geo([0.25, 1.0], [1, 3]) > 0.5)

print("== 3) 短板不可被权重补偿 ==")
check("d=0 且权重很小仍为 0", _geo([0.0, 0.9], [0.01, 100]) == 0.0)
check("等权 d=0 也为 0", _geo([0.0, 0.9]) == 0.0)
check("负值按 0 处理", _geo([-0.2, 0.9], [1, 1]) == 0.0)

print("== 4) 单调性 ==")
check("提高某 d 不会降低 D",
      _geo([0.4, 0.8], [1, 1]) < _geo([0.6, 0.8], [1, 1]))

print("== 5) 非法权重退化 ==")
check("权重全 0 → 等权", abs(_geo([0.25, 1.0], [0, 0]) - 0.5) < 1e-12,
      _geo([0.25, 1.0], [0, 0]))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
