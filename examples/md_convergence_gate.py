# -*- coding: utf-8 -*-
"""B3 MD 收敛门（借自外部 skill S6 的判据设计，独立实现）。

主指标：**接触图 Tanimoto 驻留**——每帧的"配体-受体接触残基集合"与相邻帧的
Jaccard 相似度时间序列。明确弃用配体 RMSD：它会把"同一结合模式内的合理重定向"
误判为失稳（外部线的设计依据）。

配套：块平均误差（把 Tanimoto 序列分 5 块，块间 SD / sqrt(n_blocks)）。

判据：
  frames < 20               -> insufficient_frames（结论自动封顶"静态敏感性"）
  末四分之一 mean(t) >= 0.85 且块误差 <= 0.10 -> converged
  否则                       -> not_converged

用法（在 md 环境跑，只需 numpy）：
  python md_convergence_gate.py --dcd md/Mv2/prod.dcd --pdb md/Mv2/complex_solv_min.pdb \
      --n-protein 4851 --n-ligand 58
"""
import argparse
import os
import struct
import sys

import numpy as np


def read_dcd(path):
    """极简 CHARMM DCD 读取器（OpenMM 的 DCDFile 只写不读）。

    实测格式（与 e7_mmgbsa_openmm.read_dcd 一致，已被本项目验证）：
    头 276 字节（ntitle=2）；每帧 = unit-cell 记录（48B 数据 + 前后 4B 长度标记）
    在前，随后 x/y/z 三个 4*natom 块（各带前后 4B 标记）。
    返回 (natom, frames)，frames = list[np.ndarray (natom,3) float32]。
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    assert raw[:4] == struct.pack("<i", 84), "not a DCD (bad first block)"
    assert raw[4:8] == b"CORD", "not a DCD (no CORD magic)"
    nframes = struct.unpack("<i", raw[8:12])[0]
    natom = struct.unpack("<i", raw[268:272])[0]
    frames = []
    off = 276
    for i in range(nframes):
        nbyte = struct.unpack("<i", raw[off:off + 4])[0]
        assert nbyte == 48, "frame %d: expected cell block 48, got %d" % (i, nbyte)
        off += 8 + nbyte
        coords = np.empty((natom, 3), dtype=np.float32)
        for d in range(3):
            nbyte = struct.unpack("<i", raw[off:off + 4])[0]
            assert nbyte == 4 * natom, "frame %d axis %d: block %d != %d" % (
                i, d, nbyte, 4 * natom)
            coords[:, d] = np.frombuffer(raw, dtype="<f4", count=natom,
                                         offset=off + 4)
            off += 8 + 4 * natom
        frames.append(coords)
    return natom, frames


def parse_residues(pdb, natom):
    """从 PDB 读前 natom 个原子的残基 id（按文件顺序一一对应）。"""
    res = []
    with open(pdb) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                try:
                    res.append(int(line[22:26]))
                except ValueError:
                    # 残基号 >9999 的溢出编码（如 A000）——只出现在溶剂区，
                    # 蛋白/配体区不受影响；占位 -1 保证索引对齐
                    res.append(-1)
                if len(res) == natom:
                    break
    assert len(res) == natom, "PDB 原子数 %d < DCD NATOM %d" % (len(res), natom)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcd", required=True, nargs="+",
                    help="一个或多个 DCD（断点续跑的 prod.dcd prod_seg2.dcd），按序拼接")
    ap.add_argument("--pdb", required=True)
    ap.add_argument("--n-protein", type=int, required=True,
                    help="前 n_protein 个原子为受体")
    ap.add_argument("--n-ligand", type=int, required=True,
                    help="其后 n_ligand 个为配体；其余（溶剂/离子）忽略")
    ap.add_argument("--cut", type=float, default=4.5)
    args = ap.parse_args()

    natom = None
    frames = []
    for path in args.dcd:
        na, fr = read_dcd(path)
        if natom is None:
            natom = na
        assert na == natom, "NATOM 不一致: %s (%d) vs %d" % (path, na, natom)
        print("[gate] %-14s NATOM=%d, 帧=%d" % (os.path.basename(path), na, len(fr)))
        frames.extend(fr)
    print("[gate] 合计帧数=%d" % len(frames))
    if len(frames) < 20:
        print("[gate] verdict = insufficient_frames（<20 帧）"
              "—— **结论封顶：所有 MM-GBSA/占据率表述只能写'静态敏感性假设'**")
        sys.exit(2)

    res = parse_residues(args.pdb, natom)
    nP, nL = args.n_protein, args.n_ligand
    resP = np.array(res[:nP])
    cut2 = args.cut ** 2

    seq = []
    for f in frames:
        P, L = f[:nP], f[nP:nP + nL]
        d2 = ((P[:, None, :] - L[None, :, :]) ** 2).sum(-1)   # (nP, nL)
        hit = (d2 < cut2).any(axis=1)
        seq.append(frozenset(resP[hit].tolist()))

    t = [len(a & b) / len(a | b) for a, b in zip(seq, seq[1:])]
    q = max(len(t) // 4, 1)
    first_q, last_q = float(np.mean(t[:q])), float(np.mean(t[-q:]))
    blocks = np.array_split(np.array(t), 5)
    bm = [float(np.mean(b)) for b in blocks]
    block_err = float(np.std(bm) / np.sqrt(len(bm)))

    converged = last_q >= 0.85 and block_err <= 0.10
    print("[gate] 相邻帧接触图 Tanimoto：首四分之一 %.3f -> 末四分之一 %.3f"
          % (first_q, last_q))
    print("[gate] 块均值 %s | 块误差 %.3f" %
          (["%.3f" % x for x in bm], block_err))
    if converged:
        print("[gate] verdict = converged —— 轨迹可用于 MM-GBSA / 占据率")
    else:
        print("[gate] verdict = not_converged —— **结论封顶：只允许'静态敏感性'表述**")
        sys.exit(3)


if __name__ == "__main__":
    main()
