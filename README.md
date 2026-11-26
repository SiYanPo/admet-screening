# admet-screening

Research code accompanying the manuscript *"Source-level admission in multi-source
ADMET aggregation is a cost-conditional decision"* (submitted to *Journal of
Cheminformatics*).

This repository contains the pipeline that produces every number in the paper,
the frozen preregistration package, and the audit apparatus. It is **research
code**, not a validated ADMET predictor: the substance of the paper is a
decision-theoretic result about when it pays to gate prediction sources, and the
pipeline exists to make that result recomputable by a third party.

---

## What you can verify, and how long it takes

| Goal | Command | Wall clock |
|---|---|---|
| Confirm the environment and data are complete | `./reproduce.sh --check` | seconds |
| Recompute Tables 1, 2b, 2c and 3 from deposited per-seed records and check every checksum | `./reproduce.sh` | under 1 minute |
| Retrain all five endpoints from raw TDC splits, then recompute the tables | `./reproduce.sh --full` | 41 min measured (322 s primary, 2058 s transferability, 65 s tables) |
| Check that the deposit is ready to be submitted (artefacts, placeholders, remote) | `python tools/check_deposit_ready.py` | seconds |

The default mode is the one to start with. It reads the deposited per-seed
records (`out_keystone_v43/results.json`, `out_keystone_transfer/results.json`),
regenerates the four cost-dependent tables, and compares six SHA-256 digests —
the four tables plus the two per-seed files they derive from — against
`deposit/EXPECTED_SHA256.json`. The tables are a pure function of those inputs,
so a mismatch means the code or the input changed, which is precisely what a
reader wants to be told.

Digests are computed after normalising CRLF to LF, because git may check a text
file out with CRLF on Windows and LF elsewhere. That changes the byte count
without changing a single parsed value, so the digest describes content rather
than the checkout platform. This was verified in both directions:

| Check | Result |
|---|---|
| Author working copy (CRLF, `results.json` = 1 025 872 bytes) | 6/6 match |
| Fresh `git clone` (LF, `results.json` = 984 860 bytes) | 6/6 match |
| Negative control: change `0.2602` to `0.2603` in `critical_cost.csv` | that file reports DIFF, exit code 1; the other five still match |

The negative control matters as much as the positive one: a verifier that
returns success regardless of content is not a verifier.

`--full` retrains the models and rewrites the two per-seed result files, which
means it necessarily invalidates the recorded checksums: those digests cover the
very files it replaces. **A checksum mismatch at the end of `--full` is
therefore expected, not a failure.** To get back to the state under review:

```bash
git checkout -- out_keystone_v43/results.json out_keystone_transfer/results.json
./reproduce.sh          # 6/6 digests pass again
```

What a retrain actually reproduces was measured rather than assumed, and it
splits by code lineage:

| Case | Records | Byte-identical | Max drift |
|---|---|---|---|
| Two transferability endpoints, same code | 1800 | **1800 (100%)** | 0.000000 |
| Three primary endpoints, deposited analysis vs shipped code | 2700 | 2376 (88.0%) | 0.0246 in utility |

The residue in the second row is not stochastic. Every differing record belongs
to a calibration-dependent strategy, while the two strategies that involve no
calibration (S1, S2) are identical to the last digit; the deposited file also
predates three fields the current pipeline writes (`cost_decision_audit`,
`pi_cost_sensitive_rows`, `schema_version`). Drift therefore enters through the
calibration step at a version boundary. Across all five endpoints, no contrast
changes sign, no significance decision changes, and no c* moves by more than
0.0007. Details: `references/RETRAIN_DRIFT.md`,
`tools/compare_retrain.py`.

Each step appends one JSON line to `logs/reproduce_<mode>_<timestamp>.jsonl`
with its return code and duration. No buffered `tee` is used, because a
swallowed tail is exactly what makes a failure hard to diagnose.

---

## Installation

Python 3.12 or newer is required (the pinned NumPy needs it; this was verified on
3.13.14). All direct and transitive pins are in `requirements.lock`.

```bash
# Option A - bootstrapped (idempotent, verifies usability after installing)
python bootstrap.py

# Option B - manual
pip install -r requirements.lock
```

Option C, containerised, pins the base image by digest:

```bash
docker build -f docker/Dockerfile.repro -t admet-screening:2026.11.23 .
docker run --rm admet-screening:2026.11.23   # expect CONTAINER_SELFTEST ok=true
```

The container self-test asserts that RDKit imports, that aspirin has MW 180.16,
and that a Morgan/Tanimoto value matches the host to the last digit, so a
passing self-test means the digest points at a working environment rather than
an empty shell. See `DOCKER_DIGEST` for the recorded image identity and for the
stated limitation that the image was built locally and not pushed to a public
registry.

### Data

TDC `ADMET_Group` splits are read from `out_ext/tdc_cache/admet_group/<endpoint>/`
(`train_val.csv`, `test.csv`; columns `Drug`, `Y`). They are **not**
redistributed here, both because of size and because they carry their own
academic licences. To populate the cache:

```bash
python -c "from tdc import BenchmarkGroup; BenchmarkGroup(name='ADMET_Group', path='out_ext/tdc_cache')"
```

The five endpoints used in the paper are `herg`, `dili`, `bbb_martins`, `ames`
and `cyp3a4_veith`. If the cache is missing, `./reproduce.sh --check` says so
and names the absent paths rather than failing deeper in the pipeline.

The OneADMET supporting information is likewise not redistributed; its size and
SHA-256 are recorded in the Declarations of the manuscript so that an
independently obtained copy can be verified.

---

## Minimal working example

The smallest thing that exercises the decision layer end to end is the critical
cost estimator, which is also the paper's main deliverable. It needs only two
coverage values and one zero-cost utility difference per endpoint:

```bash
python tools/analytic_critical_cost.py \
    --results out_keystone_v43/results.json \
    --endpoints hERG,DILI,BBB_Martins
```

Expected output:

```
[c*] hERG=0.2602[0.2449,0.2777] | DILI=0.5150[0.4353,0.6352] | BBB_Martins=0.2091[0.1938,0.2793]
```

That single line is Table 2b. Adding endpoints requires no code change:

```bash
python tools/analytic_critical_cost.py \
    --results out_keystone_transfer/results.json \
    --endpoints Ames,CYP3A4_Veith \
    --out-md references/CRITICAL_COST_TRANSFER.md \
    --out-csv out_sensitivity/critical_cost_transfer.csv \
    --interim
```

which reproduces Table 2c (`0.7939` and `0.9019`). The `--interim` flag labels
the output as a transferability demonstration so that it is not mistaken for a
preregistered result.

### Which command produces which table

| Manuscript table | Command | Output |
|---|---|---|
| Table 1 (primary paired comparison, exact sign-flip + Holm) | `python tools/paper_table2.py` | `out_sensitivity/table2_paired.csv` |
| Table 2b (critical cost, primary endpoints) | `python tools/analytic_critical_cost.py` | `out_sensitivity/critical_cost.csv` |
| Table 2c (critical cost, transferability endpoints) | see above | `out_sensitivity/critical_cost_transfer.csv` |
| Table 3 (cost sweep, 81 rows) and Figures 1-2 | `python tools/paper_figures.py` | `out_sensitivity/table_h2_cost_sweep.csv`, `figures/*.png` |

Rendered Markdown versions land in `references/`.

---

## Repository layout

```
adt/                    decision layer, gates, cost arithmetic, CLI
tools/                  table and figure generators, audits, checksum verifier
run_keystone.py         the five-strategy pipeline (S1-S5) over TDC endpoints
docker/                 digest-pinned reproduction image and self-test
deposit/                EXPECTED_SHA256.json (deterministic table checksums)
references/             rendered tables, prior-art scans, audit records
out_keystone_v43/       per-seed results, primary endpoints (2700 records)
out_keystone_transfer/  per-seed results, transferability endpoints (1800 records)
out_sensitivity/        the four deposited CSVs
prereg/                 frozen preregistration log
figures/                manuscript figures
reproduce.sh            entry point described above
```

---

## Scope and known limitations

These are stated here as well as in the manuscript, because a reader who only
looks at the repository should not have to infer them.

- **The critical cost is exact only under a fixed decision rule.** In the S1-S5
  pipeline the classification threshold is fixed at 0.5 and cost enters scoring
  only, so a fixed set of decisions is re-priced and Δu is linear in the
  abstention price. Under a cost-sensitive threshold the decision mask moves
  with price, linearity breaks, and c* must be estimated numerically.
- **Five endpoints are still five endpoints.** The 4.3-fold range of c* across
  them is evidence that the quantity is endpoint-dependent; it is not an
  estimate of its distribution over ADMET endpoints. Two of the five were
  selected after the primary analysis.
- **Regression endpoints are excluded from inference.** The displacement-ratio
  criterion is sensitive to its equivalence margin, and a sensitivity sweep
  produced verdict reversals in 11 of 12 cells.
- **Retraining is byte-exact when the code is unchanged, and 88% exact across the
  version boundary that separates the deposited analysis from the shipped code.**
  The residue is confined to calibration-dependent strategies; see
  `references/RETRAIN_DRIFT.md` for the measurement rather than the assertion.

---

## Conformance to the reproducibility pilot's seven checks

*Journal of Cheminformatics* runs a pilot in which a submission with an
associated code repository can opt into an additional reproducibility and
reusability review. That review asks seven questions; the state of each is:

| # | Check | Status |
|---|---|---|
| 1 | LICENSE file in the repository root | **Yes** — `LICENSE`, MIT |
| 2 | README file in the repository root | **Yes** — this file |
| 3 | Associated public issue tracker | **Yes on GitHub** — the repository's Issues tab, enabled by default once pushed; not available before the deposit is public |
| 4 | Externally archived (Zenodo/FigShare) and referenced in the README | **Pending** — `.zenodo.json` is in place; the minted DOI replaces the placeholder in the citation section below at deposit |
| 5 | README contains installation documentation | **Yes** — see Installation, two paths plus a container |
| 6 | Code installable in a straightforward manner | **Yes** — `python bootstrap.py` or `pip install -r requirements.lock`; the container path needs one build command |
| 7 | Code conforms to an external linter | **Yes** — black 26.10.1, `line-length = 88` pinned in `pyproject.toml`; all 178 modules pass `black --check` |

Two of the seven remain open and both depend on the deposit step rather than on
further work: the archive DOI (#4) and, transitively, the public issue tracker
(#3), which does not exist until the repository is pushed. Everything else is
already true in this repository, and checks 1, 2, 5, 6 and 7 can be verified
by a reviewer without contacting the authors.

## Licence and citation

MIT Licence; see `LICENSE` at the repository root. OSI-approved, no registration
or login required to obtain the code.

Archived release: Zenodo DOI `10.5281/zenodo.XXXXXXX` *(reserved at submission;
the live DOI replaces this line and is also recorded in `CITATION.cff` before
publication)*.

Citation metadata is in `CITATION.cff`. Please cite the archived release rather
than a commit hash, so that the cited artefact is the one that was reviewed.
