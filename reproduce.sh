#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# reproduce.sh - regenerate the cost-dependent tables of the manuscript
#
#   ./reproduce.sh --check     environment, dependencies, data and artefacts
#   ./reproduce.sh             DEFAULT: regenerate Tables 1, 2b, 2c and 3 from
#                              the deposited per-seed results and verify each
#                              output against deposit/EXPECTED_SHA256.json
#   ./reproduce.sh --full      additionally retrain all five endpoints
#                              (three primary + two transferability) from raw
#                              TDC splits; measured at 41 min
#   ./reproduce.sh --update-hashes
#                              rewrite EXPECTED_SHA256.json after an
#                              intentional change to table formatting
#
# Design notes
#   * `--check` and the default mode are deterministic and take seconds:
#     they re-derive every number from deposited per-seed records, which is
#     the part a reviewer can verify without a GPU or an afternoon.
#   * `--full` retrains models. Random forests are seeded, but floating point
#     and BLAS threading differ across platforms, so --full is expected to
#     agree to within tolerance rather than bit for bit. Measured: 1800/1800
#     identical when the code is unchanged, 88% across the version boundary that
#     separates the deposited analysis from the shipped code (see
#     references/RETRAIN_DRIFT.md). --full therefore ends with a checksum
#     mismatch BY DESIGN, because it rewrites the files those checksums cover.
#   * No log tee is used. Each step appends one JSON line to
#     logs/reproduce_<mode>_<timestamp>.jsonl. A buffered tee can swallow the
#     tail of a failing run, and the tail is exactly what is needed to
#     diagnose it.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="tables"
UPDATE_HASHES=0
for arg in "$@"; do
  case "$arg" in
    --check)          MODE="check" ;;
    --full)           MODE="full" ;;
    --tables)         MODE="tables" ;;
    --update-hashes)  UPDATE_HASHES=1 ;;
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "unknown argument: $arg (try --help)" >&2
      exit 2 ;;
  esac
done

# Interpreter: prefer python3, fall back to python (Windows Git Bash).
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "FATAL: no python3/python on PATH" >&2; exit 3
  fi
fi

mkdir -p logs out_sensitivity references deposit
STAMP="$(date +%Y%m%d_%H%M%S)"
REC="logs/reproduce_${MODE}_${STAMP}.jsonl"
: > "$REC"

say() { printf '%s\n' "$*"; }
rule() { printf '%s\n' "------------------------------------------------------------"; }

# record <step> <rc> <seconds> [detail]
record() {
  "$PY" - "$1" "$2" "$3" "${4:-}" "$REC" <<'PYEOF'
import json, sys, datetime
step, rc, secs, detail, path = sys.argv[1:6]
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "step": step, "rc": int(rc), "seconds": round(float(secs), 2),
        "detail": detail,
    }, ensure_ascii=False) + "\n")
PYEOF
}

# run_step <name> <cmd...>  - fail fast, keep rc and timing
run_step() {
  local name="$1"; shift
  local t0 t1 rc
  say "  -> $name"
  t0=$(date +%s)
  set +e
  "$@" 2>&1 | tail -n 40
  rc=${PIPESTATUS[0]}
  set -e
  t1=$(date +%s)
  record "$name" "$rc" "$((t1 - t0))"
  if [ "$rc" -ne 0 ]; then
    say ""
    say "FAILED: $name (rc=$rc)"
    say "Full record: $REC"
    exit "$rc"
  fi
}

# ---------------------------------------------------------------------------
# Step 1 - environment
# ---------------------------------------------------------------------------
check_env() {
  rule
  say "Environment"
  "$PY" - <<'PYEOF'
import sys, platform
print("  python      %s" % sys.version.split()[0])
print("  platform    %s %s" % (platform.system(), platform.machine()))
missing = []
for mod in ("numpy", "pandas", "sklearn", "rdkit"):
    try:
        m = __import__(mod)
        print("  %-11s %s" % (mod, getattr(m, "__version__", "?")))
    except Exception as exc:
        missing.append("%s (%s)" % (mod, exc))
if missing:
    print("  MISSING: " + ", ".join(missing))
    sys.exit(4)
PYEOF
}

check_data() {
  rule
  say "Data and artefacts"
  # A cloned deposit has no raw TDC splits: they are excluded because they carry
  # third-party licences. Verifying the tables does not need them, retraining
  # does. So the raw splits are required only under --full, and reported as
  # optional otherwise. Getting this wrong would make a fresh clone look broken.
  REQUIRE_RAW="${1:-0}" "$PY" - <<'PYEOF'
import json, os, sys

need_raw = os.environ.get("REQUIRE_RAW") == "1"

# Required for table verification: the per-seed records and the generators.
artefacts = [
    "out_keystone_v43/results.json",
    "out_keystone_transfer/results.json",
    "tools/paper_table2.py",
    "tools/paper_figures.py",
    "tools/analytic_critical_cost.py",
    "deposit/EXPECTED_SHA256.json",
]
# Required only for --full.
raw = [
    "out_ext/tdc_cache/admet_group/herg/train_val.csv",
    "out_ext/tdc_cache/admet_group/dili/train_val.csv",
    "out_ext/tdc_cache/admet_group/bbb_martins/train_val.csv",
    "out_ext/tdc_cache/admet_group/ames/train_val.csv",
    "out_ext/tdc_cache/admet_group/cyp3a4_veith/train_val.csv",
]

bad = []
for p in artefacts:
    ok = os.path.exists(p)
    print("  %-58s %s" % (p, ("ok (%d bytes)" % os.path.getsize(p)) if ok else "MISSING"))
    if not ok:
        bad.append(p)

# Per-seed record counts: 5 strategies x 9 cost points x 20 seeds x endpoints.
for f, want in (("out_keystone_v43/results.json", 2700),
                ("out_keystone_transfer/results.json", 1800)):
    if os.path.exists(f):
        n = len(json.load(open(f, encoding="utf-8"))["per_run"])
        flag = "ok" if n >= want else "LOW"
        print("  %-58s %s (%d rows, expected >= %d)" % (f + " ::per_run", flag, n, want))
        if n < want:
            bad.append(f)

if need_raw:
    print("  -- raw TDC splits (required by --full) --")
    for p in raw:
        ok = os.path.exists(p)
        print("  %-58s %s" % (p, "ok" if ok else "MISSING"))
        if not ok:
            bad.append(p)
else:
    have = sum(1 for p in raw if os.path.exists(p))
    print("  raw TDC splits: %d/%d present "
          "(optional; needed only for --full)" % (have, len(raw)))

if bad:
    print("  incomplete: " + ", ".join(bad))
    if not need_raw:
        print("  To verify tables, only the artefacts above are required. "
              "To retrain, also populate out_ext/tdc_cache (see README.md).")
    sys.exit(5)
PYEOF
}

# ---------------------------------------------------------------------------
# Step 2 - regenerate tables (deterministic)
# ---------------------------------------------------------------------------
regen_tables() {
  rule
  say "Regenerating tables from deposited per-seed results"

  run_step "table1_pairwise" "$PY" tools/paper_table2.py
  run_step "table3_cost_sweep_and_figures" "$PY" tools/paper_figures.py
  run_step "table2b_critical_cost_primary" "$PY" tools/analytic_critical_cost.py
  run_step "table2c_critical_cost_transfer" \
    "$PY" tools/analytic_critical_cost.py \
      --results out_keystone_transfer/results.json \
      --endpoints Ames,CYP3A4_Veith \
      --out-md references/CRITICAL_COST_TRANSFER.md \
      --out-csv out_sensitivity/critical_cost_transfer.csv \
      --title "Critical cost on two endpoints outside the preregistered set (transferability demonstration)" \
      --interim
}

verify_hashes() {
  rule
  say "Verifying table checksums against deposit/EXPECTED_SHA256.json"
  HASH_ARGS=()
  if [ "$UPDATE_HASHES" -eq 1 ]; then HASH_ARGS+=(--update); fi
  "$PY" tools/verify_table_hashes.py "${HASH_ARGS[@]+"${HASH_ARGS[@]}"}"
}

# ---------------------------------------------------------------------------
# Step 3 - optional full retrain
# ---------------------------------------------------------------------------
retrain_all() {
  rule
  say "Retraining five endpoints (3 primary + 2 transferability), 20 seeds each"
  say "Measured wall clock: 41 min. Results are written only at the end, so an interrupt leaves them untouched."
  run_step "retrain_primary" \
    "$PY" run_keystone.py --endpoints hERG,DILI,BBB_Martins --seeds 20 --outdir out_keystone_v43
  run_step "retrain_transfer" \
    "$PY" run_keystone.py --endpoints Ames,CYP3A4_Veith --seeds 20 --outdir out_keystone_transfer
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
say "reproduce.sh  mode=$MODE  root=$ROOT"
say "record: $REC"

if [ "$MODE" = "check" ]; then
  check_env
  check_data 0
  rule
  say "Environment and artefacts complete. Next: ./reproduce.sh  (tables, under 1 min)"
  exit 0
fi

if [ "$MODE" = "full" ]; then
  check_env
  check_data 1
  retrain_all
else
  # Table regeneration still needs the deposited records, so check them first
  # rather than failing inside a generator with an opaque traceback.
  check_data 0
fi

regen_tables
verify_hashes

rule
say "Done. Record: $REC"
say "Tables: out_sensitivity/table2_paired.csv, table_h2_cost_sweep.csv,"
say "        critical_cost.csv, critical_cost_transfer.csv"
say "Rendered: references/PAPER_TABLE2_MAIN_RESULTS.md, PAPER_TABLE_H2_COST_SWEEP.md,"
say "          ANALYTIC_CRITICAL_COST.md, CRITICAL_COST_TRANSFER.md"
