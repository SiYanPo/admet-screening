# -*- coding: utf-8 -*-
"""换机后的环境自检（env-audit）—— 纯标准库，零第三方依赖。

为什么必须只用标准库：环境坏到 `import rdkit` 都失败时，自检脚本自身必须还能跑，
否则"排查环境"这件事本身就要先有一个好环境，形成循环依赖。

四条设计约束（缺一条，"换机可复现"就是空话）：
1. 验证**产物可用**，不验证"路径存在"：包要 import 且过一个最小功能调用；
   外部 exe 要实跑 --version；R 栈要 library() 出真实版本号。
   （教训来自 gmx_MMPBSA 安装事故：conda-meta 目录存在 != 环境完整。）
2. 零硬编码本机路径：外部工具全部走 `ADT_*` 环境变量 + 候选路径自动探测。
3. 区分三层：required（缺了不能跑）/ optional（缺了功能降级）/ external（换机需重装），
   退出码可机器判：0=必需层全绿；1=必需层缺失；2=只有可选或漂移告警。
4. 网络探测默认关闭（首页 200 != 预测可用，pkCSM 教训）；要显式 --network。

用法：
    python -m adt.env_audit                      # 人类可读摘要
    python -m adt.env_audit --json-out env_audit_report.json
    python -m adt.env_audit --network           # 额外探测注册源可达性
    python -m adt.env_audit --deep              # 额外做重验证（ORCA 单点 / 1.2GB 数据哈希）
    python -m adt env-audit --help              # 也可从主 CLI 进入

覆盖变量（全部可选，不设就自动探测）：
    ADT_OSP_DIR       PK-Sim/MoBi portable 根目录（其下应有 PKSim/、MoBi/）
    ADT_MAMBA_EXE     micromamba 可执行文件
    ADT_MAMBA_ROOT    MAMBA_ROOT_PREFIX
    ADT_PKPD_ENV      R + nlmixr2 + rxode2 的 conda 环境路径
    ADT_PYSCF_ENV     PySCF 可选环境（可选层）
    ADT_OPENMM_ENV    OpenMM 可选环境（可选层）
    ADT_ORCA_DIR      含 orca.exe 的 ORCA 安装目录（学术注册软件）
    ADT_ORCA_SEARCH_ROOTS   ORCA 自动发现时的搜索根，os.pathsep 分隔
    ADT_ONEADMET_CSV  OneADMET SI 解压后的 oneADMET.csv（1.2 GB，可放在 skill 外）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import importlib.metadata as _md
import io
import json
import os
import platform
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")

# ---------------------------------------------------------------- 工具函数


def _run(cmd, timeout=90, env=None, cwd=None):
    """实跑一条命令，返回 (rc, first_lines)。绝不抛异常，超时/缺失都变成可读结果。"""
    e = os.environ.copy()
    if env:
        e.update({k: str(v) for k, v in env.items() if v is not None})
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=e,
            cwd=cwd,
        )
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        return p.returncode, out
    except FileNotFoundError:
        return 127, "FileNotFoundError: %s" % (cmd[0] if cmd else "")
    except subprocess.TimeoutExpired:
        return 124, "TimeoutExpired after %ss: %s" % (
            timeout,
            " ".join(map(str, cmd[:3])),
        )
    except Exception as ex:  # 任何意外都报出来，不静默吞
        return 126, "%s: %s" % (type(ex).__name__, ex)


def _first_existing(paths, is_dir=False):
    for p in paths:
        if not p:
            continue
        p = os.path.expandvars(os.path.expanduser(p))
        if os.path.isdir(p) if is_dir else os.path.isfile(p):
            return p
    return ""


def _which(name):
    from shutil import which

    return which(name) or ""


def discover_orca(max_dirs=2500):
    """有限广度地找 ORCA 安装目录，零硬编码本机绝对路径。

    默认搜索根 = HOME + /opt + /usr/local + 所有存在的盘符根目录；可用
    ADT_ORCA_SEARCH_ROOTS 覆盖。只下探 3 层、只进看起来像工具目录的分支、
    访问目录总数上限 2500，避免变成全盘扫描。命中条件：目录名以 orca 开头
    且目录内有 orca.exe / orca（产物可用，不是目录存在就算）。
    """
    raw = os.environ.get("ADT_ORCA_SEARCH_ROOTS", "")
    roots = [x.strip() for x in raw.split(os.pathsep) if x.strip()]
    if not roots:
        roots = [HOME, "/opt", "/usr/local"]
        if os.name == "nt":
            for letter in "CDEFGH":
                d = letter + ":/"
                if os.path.isdir(d):
                    roots.append(d)
    toolish = {
        "workbuddy",
        "tools",
        "pharma-tools",
        "opt",
        "local",
        "software",
        "apps",
        "bin",
        "programs",
        "dev",
        "data",
    }
    skip = {
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "appdata",
        "users",
        "$recycle.bin",
        "system volume information",
        "node_modules",
        ".git",
        "envs",
        "conda-meta",
        ".workbuddy",
        "temp",
        "tmp",
        "recovery",
    }
    visited = [0]
    seen = set()

    def has_exe(d):
        return os.path.isfile(os.path.join(d, "orca.exe")) or os.path.isfile(
            os.path.join(d, "orca")
        )

    def scan(d, depth):
        if visited[0] >= max_dirs or depth > 3:
            return ""
        try:
            entries = list(os.scandir(d))
        except OSError:
            return ""
        for e in entries:
            if visited[0] >= max_dirs:
                return ""
            low = e.name.lower()
            if low in skip or low.startswith("."):
                continue
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            p = e.path
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            seen.add(key)
            visited[0] += 1
            if low.startswith("orca") and has_exe(p):
                return p
            if depth < 3 and (depth == 0 or low in toolish or low.startswith("orca")):
                hit = scan(p, depth + 1)
                if hit:
                    return hit
        return ""

    for r in roots:
        r = os.path.expandvars(os.path.expanduser(r))
        if not os.path.isdir(r):
            continue
        if has_exe(r):
            return os.path.normpath(r)
        hit = scan(r, 0)
        if hit:
            return os.path.normpath(hit)
    return ""


def _env_has_rscript(env_dir):
    """目录存在 != 环境完整（gmx_MMPBSA 事故教训）。必须有 Rscript 可执行文件。"""
    if not env_dir or not os.path.isdir(env_dir):
        return False
    for rel in (
        "Scripts/Rscript.exe",
        "bin/Rscript",
        "lib/R/bin/x64/Rscript.exe",
        "lib/R/bin/Rscript",
    ):
        if os.path.isfile(os.path.join(env_dir, rel)):
            return True
    return False


def _local_config():
    """读取 bootstrap 生成的本机路径映射（不进版本库，换机后重新生成）。"""
    p = os.path.join(ROOT, ".env_audit_paths.json")
    if not os.path.isfile(p):
        return {}
    try:
        d = json.loads(io.open(p, encoding="utf-8").read())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _item(cid, tier, status, detail, evidence="", fix=""):
    return {
        "id": cid,
        "tier": tier,
        "status": status,
        "detail": detail,
        "evidence": evidence.strip()[:600],
        "fix": fix,
    }


# ---------------------------------------------------------------- 路径解析


def resolve_paths():
    """只探测，不判定；返回所有外部工具的候选解析结果。

    优先级：环境变量 > bootstrap 落盘的本机映射 > 通用自动探测 > PATH。
    绝不把任何一台机器的绝对路径写死在代码里。
    """
    cfg = _local_config()

    def pick(key, envkey):
        return os.environ.get(envkey, "") or cfg.get(key, "")

    osp = pick("osp_dir", "ADT_OSP_DIR")
    mamba = pick("mamba", "ADT_MAMBA_EXE")
    root = pick("mamba_root", "ADT_MAMBA_ROOT")
    pkpd = pick("pkpd", "ADT_PKPD_ENV")
    pyscf_env = pick("pyscf_env", "ADT_PYSCF_ENV")
    openmm_env = pick("openmm_env", "ADT_OPENMM_ENV")
    orca_dir = pick("orca_dir", "ADT_ORCA_DIR") or discover_orca()
    oneadmet_csv = pick("oneadmet_csv", "ADT_ONEADMET_CSV") or _first_existing(
        [
            os.path.join(ROOT, "assets", "external", "oneadmet", "oneADMET.csv"),
            os.path.join(
                ROOT, "assets", "external", "oneadmet", "extracted", "oneADMET.csv"
            ),
        ]
    )
    orca = ""
    if orca_dir:
        orca = _first_existing(
            [os.path.join(orca_dir, "orca.exe"), os.path.join(orca_dir, "orca")]
        )
    if not orca:
        orca = _which("orca") or _which("orca.exe")

    osp_dir = osp or _first_existing(
        [
            os.path.join(HOME, ".workbuddy", "binaries", "osp"),
            os.path.join(ROOT, "_vendor", "osp"),
            os.path.join(ROOT, ".local", "osp"),
            "/opt/osp",
        ],
        is_dir=True,
    )

    pksim = (
        _first_existing(
            [
                os.path.join(osp_dir, "PKSim", "PKSim.CLI.exe") if osp_dir else "",
                os.path.join(osp_dir, "PKSim", "PKSim.CLI") if osp_dir else "",
            ]
        )
        or _which("PKSim.CLI")
        or _which("PKSim.CLI.exe")
    )

    mobi = _first_existing(
        [
            os.path.join(osp_dir, "MoBi", "MoBi.exe") if osp_dir else "",
            os.path.join(osp_dir, "MoBi", "MoBi") if osp_dir else "",
        ]
    )

    if not mamba:
        mamba = _first_existing(
            [
                os.path.join(
                    HOME,
                    ".workbuddy",
                    "binaries",
                    "micromamba",
                    "Library",
                    "bin",
                    "micromamba.exe",
                ),
                os.path.join(
                    HOME, ".workbuddy", "binaries", "micromamba", "bin", "micromamba"
                ),
                os.path.join(ROOT, "_vendor", "bin", "micromamba.exe"),
                "/opt/conda/bin/micromamba",
            ]
        ) or _which("micromamba")

    if not root:
        root = os.environ.get("MAMBA_ROOT_PREFIX", "") or _first_existing(
            [
                os.path.join(HOME, "micromamba"),
                os.path.join(HOME, ".local", "share", "mamba"),
                os.path.join(ROOT, "_vendor", "mamba"),
            ],
            is_dir=True,
        )

    if not pkpd:
        # 候选必须真的带 Rscript：只看目录存在会把残留目录当完整环境
        for cand in [
            os.path.join(root, "envs", "pkpd") if root else "",
            os.path.join(HOME, ".workbuddy", "binaries", "mamba", "pkpd"),
            os.path.join(ROOT, "_vendor", "envs", "pkpd"),
            os.path.join(HOME, "micromamba", "envs", "pkpd"),
        ]:
            if _env_has_rscript(cand):
                pkpd = cand
                break
    elif not _env_has_rscript(pkpd):
        # 显式配置错了也要报出来，不静默接受
        pass

    return {
        "osp_dir": osp_dir,
        "pksim": pksim,
        "mobi": mobi,
        "mamba": mamba,
        "mamba_root": root,
        "pkpd": pkpd,
        "pyscf_env": pyscf_env,
        "openmm_env": openmm_env,
        "orca_dir": orca_dir,
        "orca": orca,
        "oneadmet_csv": oneadmet_csv,
    }


# ---------------------------------------------------------------- Python 层


def _version(dist, mod=None):
    try:
        return _md.version(dist)
    except Exception:
        m = mod if mod is not None else None
        return getattr(m, "__version__", "unknown") if m else "absent"


def _probe_pkg(cid, dist, modname, tier, probe=None, fix=""):
    """import + 版本 + 最小功能调用。probe 返回证据字符串，抛异常即判不可用。"""
    try:
        m = importlib.import_module(modname)
    except Exception as ex:
        return _item(
            cid,
            tier,
            "missing",
            "import 失败: %s" % ex,
            "%s: %s" % (type(ex).__name__, ex),
            fix or "bootstrap 重装该包",
        )
    v = _version(dist, m)
    ev = "import ok, version=%s" % v
    if probe:
        try:
            ev += "; " + probe(m)
        except Exception as ex:
            return _item(
                cid,
                tier,
                "missing",
                "import 成功但最小功能调用失败",
                "%s: %s" % (type(ex).__name__, ex),
                fix or "版本不兼容，按 lock 重装",
            )
    return _item(cid, tier, "ok", "可用", ev)


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return _item(
        "py.version",
        "required",
        "ok" if ok else "missing",
        "Python %d.%d.%d (%s)" % (v.major, v.minor, v.micro, platform.platform()),
        sys.executable,
        "" if ok else "需要 >= 3.11（conftest / 类型语法 / scipy 轮子）",
    )


def check_packages():
    out = [check_python()]

    def _chem(m):
        chem = importlib.import_module("rdkit.Chem")
        return "MolFromSmiles(CCO) atoms=%d" % chem.MolFromSmiles("CCO").GetNumAtoms()

    def _stats(m):
        st = importlib.import_module("scipy.stats")
        return "spearmanr=%s" % round(
            float(st.spearmanr([1, 2, 3], [1, 2, 3]).statistic), 3
        )

    def _metrics(m):
        met = importlib.import_module("sklearn.metrics")
        return "roc_auc=%s" % met.roc_auc_score([0, 1], [0.1, 0.9])

    req = [
        ("pkg.rdkit", "rdkit", "rdkit", _chem),
        ("pkg.numpy", "numpy", "numpy", lambda m: "sum=%s" % m.array([1, 2, 3]).sum()),
        ("pkg.scipy", "scipy", "scipy", _stats),
        ("pkg.sklearn", "scikit-learn", "sklearn", _metrics),
        (
            "pkg.pandas",
            "pandas",
            "pandas",
            lambda m: "DataFrame=%s" % (m.DataFrame({"a": [1]}).shape,),
        ),
        ("pkg.yaml", "pyyaml", "yaml", lambda m: "safe_load=%s" % m.safe_load("a: 1")),
        (
            "pkg.requests",
            "requests",
            "requests",
            lambda m: "Session=%s" % type(m.Session()).__name__,
        ),
        (
            "pkg.bs4",
            "beautifulsoup4",
            "bs4",
            lambda m: "parse=%r"
            % m.BeautifulSoup("<b>x</b>", "html.parser").get_text(),
        ),
        ("pkg.pytest", "pytest", "pytest", None),
    ]
    for cid, dist, mod, probe in req:
        out.append(_probe_pkg(cid, dist, mod, "required", probe))

    # lxml：代码已做 html.parser 降级，故只算 optional，但装上更稳（vnn 适配器）
    out.append(
        _probe_pkg(
            "pkg.lxml",
            "lxml",
            "lxml.etree",
            "optional",
            lambda m: "etree.tag=%r" % m.fromstring("<a/>").tag,
            "pip install lxml（缺失会降级 html.parser）",
        )
    )

    opt = [
        (
            "opt.pharmpy",
            "pharmpy-core",
            "pharmpy",
            lambda m: "create_datainfo=%s"
            % (hasattr(importlib.import_module("pharmpy.modeling"), "create_datainfo")),
        ),
        (
            "opt.pytdc",
            "pytdc",
            "tdc",
            lambda m: "BenchmarkGroup=%s" % hasattr(m, "BenchmarkGroup"),
        ),
        ("opt.tqdm", "tqdm", "tqdm", None),
        ("opt.fuzzywuzzy", "fuzzywuzzy", "fuzzywuzzy", None),
        ("opt.openpyxl", "openpyxl", "openpyxl", None),
        ("opt.pkg_resources", "setuptools", "pkg_resources", None),
    ]
    for cid, dist, mod, probe in opt:
        out.append(
            _probe_pkg(
                cid, dist, mod, "optional", probe, "python bootstrap.py --optional"
            )
        )
    return out


# ---------------------------------------------------------------- 外部工具层


def check_externals(paths, deep=False):
    out = []

    # PK-Sim CLI：必须实跑 --version（只存在不算）
    if not paths["pksim"]:
        out.append(
            _item(
                "ext.pksim",
                "external",
                "missing",
                "未找到 PKSim.CLI",
                "ADT_OSP_DIR 未设且候选路径均不存在",
                "python bootstrap.py --external 或设 ADT_OSP_DIR",
            )
        )
    else:
        rc, log = _run([paths["pksim"], "--version"], timeout=60)
        # 2026-11-05 实测：PKSim.CLI 12.3.173 的 --version / version 都返回 rc=1，
        # 但版本字符串照常写到 stderr。该 CLI 的退出码不可作验收（MODULE_MAP §4.2 同结论），
        # 以**产物（版本串）**为准，rc 只作为证据留存。
        import re as _re

        ok = "PKSim.CLI" in log and bool(_re.search(r"\d+\.\d+\.\d+", log))
        out.append(
            _item(
                "ext.pksim",
                "external",
                "ok" if ok else "missing",
                "PKSim.CLI 可执行（版本串已产出）" if ok else "未产出版本串",
                "[rc=%s; rc=1 为该 CLI 固有行为] %s" % (rc, log[:300]),
                "" if ok else "重下 OSP portable ZIP（见 SETUP_REPRODUCE.md）",
            )
        )

    # MoBi：纯 GUI，只验证文件存在与非零大小（不假装能 headless 跑）
    mobi = paths["mobi"]
    if mobi and os.path.getsize(mobi) > 0:
        out.append(
            _item(
                "ext.mobi",
                "external",
                "ok",
                "MoBi GUI 已就位（无 headless CLI，不实跑）",
                "%s (%d bytes)" % (mobi, os.path.getsize(mobi)),
            )
        )
    else:
        out.append(
            _item(
                "ext.mobi",
                "external",
                "warn",
                "MoBi 缺失（GUI 可选）",
                "未找到 MoBi.exe",
                "随 PK-Sim 同包下载",
            )
        )

    # micromamba
    if not paths["mamba"]:
        out.append(
            _item(
                "ext.micromamba",
                "external",
                "missing",
                "未找到 micromamba",
                "PATH 与候选路径均无",
                "python bootstrap.py --external",
            )
        )
    else:
        rc, log = _run([paths["mamba"], "--version"], timeout=60)
        ok = rc == 0 and log.strip()
        out.append(
            _item(
                "ext.micromamba",
                "external",
                "ok" if ok else "missing",
                "micromamba 可执行" if ok else "存在但 --version 失败",
                "[rc=%s] %s" % (rc, log[:200]),
                "" if ok else "重下官方 micromamba",
            )
        )

    # R + nlmixr2 + rxode2：必须通过 micromamba run 实跑，且三个包都报版本
    if not (paths["mamba"] and paths["pkpd"]):
        out.append(
            _item(
                "ext.r_pkpd",
                "external",
                "missing",
                "R/PK-PD 环境未配置",
                "mamba=%s pkpd=%s" % (bool(paths["mamba"]), bool(paths["pkpd"])),
                "设 ADT_MAMBA_EXE / ADT_PKPD_ENV，或 python bootstrap.py --with-r",
            )
        )
    else:
        rscript = (
            'cat(R.version.string,"|");'
            'cat(as.character(packageVersion("nlmixr2")),"|");'
            'cat(as.character(packageVersion("rxode2")),"|");'
            'cat(as.character(packageVersion("qs2")),"\\n")'
        )
        env = {"MAMBA_ROOT_PREFIX": paths["mamba_root"]} if paths["mamba_root"] else {}
        rc, log = _run(
            [paths["mamba"], "run", "-p", paths["pkpd"], "Rscript", "-e", rscript],
            timeout=180,
            env=env,
        )
        # 必须能解析出四段（R / nlmixr2 / rxode2 / qs2），且退出码为 0
        parts = [x.strip() for x in log.splitlines() if x.count("|") >= 3]
        ok = rc == 0 and bool(parts)
        out.append(
            _item(
                "ext.r_pkpd",
                "external",
                "ok" if ok else "missing",
                "R/nlmixr2/rxode2/qs2 实跑通过" if ok else "R 栈实跑失败",
                "[rc=%s] %s" % (rc, log[:400]),
                "" if ok else "见 SETUP_REPRODUCE §5b：qs2 必须换官方 CRAN 二进制",
            )
        )

    # 可选 QC/MD 环境：只有在显式指定时才检查（不把别的项目的环境当本 skill 依赖）
    for cid, envkey, mod, hint in [
        ("opt.pyscf", "pyscf_env", "pyscf", "DF-B3LYP 量子化学（playbook §2.4）"),
        ("opt.openmm", "openmm_env", "openmm", "MD（playbook §2.3 要求 8.1.2）"),
    ]:
        e = paths[envkey]
        if not e:
            out.append(
                _item(
                    cid,
                    "optional",
                    "warn",
                    "未配置 %s（不影响核心运行）" % hint,
                    "设 ADT_%s 指向 conda 环境即可纳入自检" % envkey.upper(),
                )
            )
            continue
        if not (paths["mamba"] and os.path.isdir(e)):
            out.append(_item(cid, "optional", "missing", "配置了 %s 但不可用" % cid, e))
            continue
        rc, log = _run(
            [
                paths["mamba"],
                "run",
                "-p",
                e,
                "python",
                "-c",
                "import %s;print(getattr(%s,'__version__','?'))" % (mod, mod),
            ],
            timeout=120,
            env=(
                {"MAMBA_ROOT_PREFIX": paths["mamba_root"]}
                if paths["mamba_root"]
                else {}
            ),
        )
        out.append(
            _item(
                cid,
                "optional",
                "ok" if rc == 0 else "missing",
                "%s 实跑通过" % hint if rc == 0 else "%s 实跑失败" % hint,
                "[rc=%s] %s" % (rc, log[:200]),
            )
        )

    # ORCA 6.1.1（学术注册）。实测 --version 返回 rc=2，但版本串照常输出到 banner，
    # 与 PK-Sim 的 rc=1 同类陷阱：验收只认"版本串已产出"，不认退出码。
    orca = paths["orca"]
    if not orca:
        out.append(
            _item(
                "ext.orca",
                "external",
                "warn",
                "未找到 ORCA（不影响主线：playbook §2.4 用 PySCF 免注册替代）",
                "ADT_ORCA_DIR 未设且有限广度自动发现未命中",
                "https://www.faccts.de/customer/ 学术注册后下载，并设 ADT_ORCA_DIR",
            )
        )
    else:
        import re as _re

        rc, log = _run([orca, "--version"], timeout=60)
        m = _re.search(r"Program Version\s+([\d.]+)", log)
        ok = bool(m)
        out.append(
            _item(
                "ext.orca",
                "external",
                "ok" if ok else "missing",
                "ORCA %s 可执行（版本串已产出）" % m.group(1) if ok else "未产出版本串",
                "[rc=%s; rc!=0 为该 CLI 固有行为] %s" % (rc, log[:260]),
                "" if ok else "重下 ORCA 或设 ADT_ORCA_DIR",
            )
        )
        if deep and ok:
            with tempfile.TemporaryDirectory(prefix="adt_orca_") as td:
                inp = os.path.join(td, "h2o.inp")
                with io.open(inp, "w", encoding="ascii", newline="\n") as fh:
                    fh.write(
                        "! HF def2-SVP\n%pal nprocs 1 end\n"
                        "* xyz 0 1\nO 0 0 0\nH 0 0 0.96\nH 0.93 0 -0.24\n*\n"
                    )
                rc2, out2 = _run([orca, inp], timeout=180, cwd=td)
                ok2 = rc2 == 0 and "ORCA TERMINATED NORMALLY" in out2
                e2 = _re.search(r"FINAL SINGLE POINT ENERGY\s+(-?[\d.]+)", out2)
                out.append(
                    _item(
                        "ext.orca.deep",
                        "external",
                        "ok" if ok2 else "missing",
                        (
                            "ORCA HF/def2-SVP H2O 单点实跑通过"
                            if ok2
                            else "ORCA 单点实跑失败"
                        ),
                        "[rc=%s] E=%s Eh" % (rc2, e2.group(1) if e2 else "n/a"),
                        "" if ok2 else "检查 MPI / 路径，见 SETUP_REPRODUCE §6",
                    )
                )
    return out


# ---------------------------------------------------------------- 数据/协议层

DATA_FILES = [
    "assets/herg_reference_ic50.csv",
    "assets/controls/controls.csv",
    "assets/truth_template.csv",
    "assets/external/openadmet/expansion_data_train.csv",
    "assets/external/openadmet/expansion_data_test.csv",
    "assets/external/openadmet/expansion_data_raw.csv",
    "assets/external/openadmet/LICENSE.md",
    "assets/external/openadmet/PROVENANCE.json",
    "assets/external/npass/npass_adme_subset.csv",
    "assets/external/npass/npass_structures_subset.csv",
    "assets/external/npass/npass_tox_ld50_rat.csv",
    "assets/external/npass/PROVENANCE.json",
    "references/02_source_registry.yaml",
    "references/03_endpoint_rules.yaml",
    "references/readback_schemas.yaml",
    "requirements.lock",
    "SETUP_REPRODUCE.md",
]


def check_data():
    out = []
    for rel in DATA_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            out.append(
                _item(
                    "data." + rel.replace("/", "."),
                    "required",
                    "missing",
                    "缺失或空文件",
                    p,
                    "从随包快照恢复整个 skill 目录",
                )
            )
            continue
        n = 0
        try:
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                n = sum(1 for _ in fh)
        except Exception:
            pass
        out.append(
            _item(
                "data." + rel.replace("/", "."),
                "required",
                "ok",
                "存在且非空",
                "%d bytes / %d lines" % (os.path.getsize(p), n),
            )
        )
    return out


ONEADMET_SHA256 = "c0860bf9c47806d9867f95b84bdfda8a62c189f891e1d951765fdd283d51034c"
ONEADMET_BYTES = 1197248494


def check_oneadmet(paths, deep=False):
    """1.2 GB SI 是模块 L 的输入，随包分发；换机漏拷即 required 缺失。

    默认只查大小 + 表头（不读 1.2 GB）；--deep 才做全文件 SHA256 + 行数。
    哈希不匹配 = 数据口径变了，不得声称复现既有 L 项结论。
    """
    p = paths["oneadmet_csv"]
    if not p or not os.path.isfile(p):
        return [
            _item(
                "data.oneadmet",
                "required",
                "missing",
                "OneADMET SI 缺失（模块 L 无法复现）",
                "未找到 assets/external/oneadmet/oneADMET.csv",
                "整包拷贝时勿省略 1.2 GB 数据，或设 ADT_ONEADMET_CSV；"
                "重下载见 SETUP_REPRODUCE §4.1",
            )
        ]
    size = os.path.getsize(p)
    with io.open(p, "rb") as fh:
        head = fh.readline().decode("utf-8", "replace").strip()
    need = ("SMILES", "PUBLIC___LogPapp_Caco_Public.csv", "PPB_Human_Public.csv")
    ok = size == ONEADMET_BYTES and all(c in head for c in need)
    items = [
        _item(
            "data.oneadmet",
            "required",
            "ok" if ok else "missing",
            "OneADMET SI 大小/表头校验通过" if ok else "OneADMET SI 大小或表头不符",
            "%d bytes (expected %d); header=%r" % (size, ONEADMET_BYTES, head[:80]),
            "" if ok else "重新解压 jm6c00049_si_002.zip，或设 ADT_ONEADMET_CSV",
        )
    ]
    if deep and ok:
        import hashlib

        h = hashlib.sha256()
        nlines = 0
        with open(p, "rb") as fh:
            for line in fh:
                h.update(line)
                nlines += 1
        good = h.hexdigest() == ONEADMET_SHA256
        items.append(
            _item(
                "data.oneadmet.deep",
                "required",
                "ok" if good else "missing",
                "OneADMET SI SHA256 校验通过" if good else "SHA256 不匹配（口径已变）",
                "sha256=%s lines=%d" % (h.hexdigest(), nlines),
                "" if good else "不得用不同 SI 声称复现；重新下载或标注口径漂移",
            )
        )
    return items


def check_fingerprint():
    p = os.path.join(ROOT, "env_fingerprint.json")
    if not os.path.isfile(p):
        return [
            _item(
                "env.fingerprint",
                "optional",
                "warn",
                "未落盘环境指纹",
                p,
                "python -m adt env-fp --out env_fingerprint.json",
            )
        ]
    try:
        saved = json.loads(io.open(p, encoding="utf-8").read())
    except Exception as ex:
        return [_item("env.fingerprint", "optional", "warn", "指纹文件损坏", str(ex))]
    cur = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "impl": platform.python_implementation(),
    }
    for mod in ("rdkit", "numpy", "scipy", "sklearn", "pandas", "yaml"):
        try:
            cur[mod] = getattr(importlib.import_module(mod), "__version__", "unknown")
        except Exception:
            cur[mod] = "absent"
    diffs = {k: (saved.get(k), v) for k, v in cur.items() if saved.get(k) != v}
    if diffs:
        return [
            _item(
                "env.fingerprint",
                "optional",
                "warn",
                "环境已漂移（G4 会报 warn）",
                json.dumps(diffs, ensure_ascii=False)[:400],
                "换机后重生成指纹并在材料中声明漂移，属预期",
            )
        ]
    return [
        _item(
            "env.fingerprint",
            "optional",
            "ok",
            "环境指纹一致",
            json.dumps(cur, ensure_ascii=False)[:300],
        )
    ]


def check_network():
    import urllib.request

    urls = [
        ("ADMETlab3", "https://admetlab3.scbdd.com/"),
        ("ADMET-AI", "https://admet.ai.greenstonebio.com/"),
        ("ProTox3", "https://tox.charite.de/protox3/"),
        ("vNN", "https://vnnadmet.bhsai.org/vnnadmet/"),
        ("ChEMBL", "https://www.ebi.ac.uk/chembl/api/data/status.json"),
        (
            "PubChem",
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/property/MolecularFormula/JSON",
        ),
        ("BioTransformer", "https://biotransformer.ca/"),
        ("SwissADME", "https://www.swissadme.ch/"),
        ("PyPI", "https://repo.huaweicloud.com/repository/pypi/simple/"),
        ("OSP", "https://www.open-systems-pharmacology.org/"),
    ]
    out = []
    for name, u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                out.append(
                    _item("net." + name, "network", "ok", "HTTP %s" % r.status, u)
                )
        except Exception as ex:
            out.append(
                _item(
                    "net." + name,
                    "network",
                    "warn",
                    "不可达（换机网络差异）",
                    "%s: %s" % (type(ex).__name__, str(ex)[:120]),
                )
            )
    # 首页 200 不等于预测引擎可用（pkCSM 教训），单列一条说明
    out.append(
        _item(
            "net.disclaimer",
            "network",
            "ok",
            "以上仅为首页可达性；预测端点可用性以 02_source_registry.yaml 的 verified_* 为准",
            "pkCSM 反例：前端 200、预测 POST 8/8 500",
        )
    )
    return out


# ---------------------------------------------------------------- 汇总


def build_report(network=False, deep=False):
    paths = resolve_paths()
    checks = []
    checks += check_packages()
    checks += check_externals(paths, deep=deep)
    checks += check_data()
    checks += check_oneadmet(paths, deep=deep)
    checks += check_fingerprint()
    if network:
        checks += check_network()

    def pick(tier, status):
        return [c["id"] for c in checks if c["tier"] == tier and c["status"] == status]

    req_missing = pick("required", "missing")
    opt_missing = pick("optional", "missing") + pick("optional", "warn")
    ext_missing = pick("external", "missing") + pick("external", "warn")
    if req_missing:
        code = 1
    elif opt_missing or ext_missing:
        code = 2
    else:
        code = 0

    return {
        "schema": "adt-env-audit/1.0",
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "skill_root": ROOT,
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "resolved_paths": paths,
        "summary": {
            "n_checks": len(checks),
            "required_missing": req_missing,
            "optional_issues": opt_missing,
            "external_issues": ext_missing,
            "exit_code": code,
        },
        "checks": checks,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="env-audit", description="换机后的 ADMET skill 环境自检"
    )
    ap.add_argument(
        "--json-out", default="", dest="json_out", help="把完整报告写成 JSON"
    )
    ap.add_argument(
        "--network", action="store_true", help="额外探测注册源（首页可达性）"
    )
    ap.add_argument(
        "--deep",
        action="store_true",
        help="重验证：ORCA H2O 单点实跑 + OneADMET 1.2 GB SHA256/行数",
    )
    ap.add_argument("--quiet", action="store_true", help="只打印摘要与异常项")
    ap.add_argument(
        "--required-only",
        action="store_true",
        dest="required_only",
        help=(
            "进程退出码只反映必需层：必需层全绿即 rc=0（即使可选/外部层有告警）。"
            "用于 `env-audit --required-only && next-step` 这类 CI 链；"
            "JSON 里的 summary.exit_code 仍保留原始 0/1/2 语义不变。"
        ),
    )
    a = ap.parse_args(argv)

    rep = build_report(network=a.network, deep=a.deep)
    blob = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.json_out:
        with io.open(a.json_out, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        print("[env-audit] JSON -> %s" % a.json_out)

    s = rep["summary"]
    print("=" * 72)
    print("ADMET skill 环境自检  %s" % rep["generated_at"])
    print("root=%s  python=%s" % (rep["skill_root"], rep["python"]["version"]))
    print("-" * 72)
    for c in rep["checks"]:
        if a.quiet and c["status"] == "ok":
            continue
        flag = {"ok": "OK  ", "warn": "WARN", "missing": "MISS"}[c["status"]]
        print("%s [%-8s] %-28s %s" % (flag, c["tier"], c["id"], c["detail"]))
        if c["status"] != "ok" and c["evidence"]:
            print("       evidence: %s" % c["evidence"][:220].replace("\n", " | "))
        if c["status"] != "ok" and c["fix"]:
            print("       fix:      %s" % c["fix"])
    print("-" * 72)
    print("必需层缺失: %s" % (s["required_missing"] or "无"))
    print("可选层问题: %d 项" % len(s["optional_issues"]))
    print("外部层问题: %d 项" % len(s["external_issues"]))
    print(
        "退出码: %d  (0=必需层全绿 / 1=必需层缺失 / 2=仅可选或漂移告警)"
        % s["exit_code"]
    )
    rc = s["exit_code"]
    if a.required_only and rc == 2:
        # 必需层全绿、仅可选/外部层告警：--required-only 下进程返回 0，
        # 使 `env-audit --required-only && 下一步` 的直觉链成立。
        # 报表里的 summary.exit_code 保持 2（诊断信息不丢），只调进程码。
        rc = 0
        print(
            "       [--required-only] 必需层全绿，进程码 2→0；"
            "可选/外部告警见上，仍需人工判断是否安装。"
        )
    print("=" * 72)
    return rc


if __name__ == "__main__":
    sys.exit(main())
