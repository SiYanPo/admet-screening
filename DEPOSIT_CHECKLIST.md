# Deposit checklist — the two cells I cannot fill

Two items in the manuscript can only be completed by the corresponding author,
because both require an account action. Everything else is already in the
deposit. This file exists so that the last step takes minutes rather than an
afternoon, and so that nobody has to remember which lines to edit.

Run `python tools/check_deposit_ready.py --paper <manuscript.md>` at any point to
see whether the items below are still outstanding. It exits non-zero while any
of them remain.

---

## What is already true

| Item | Status |
|---|---|
| `LICENSE` at root, MIT, OSI-approved | present |
| `README.md` with installation, minimal example, table-to-command map | present |
| `reproduce.sh` + `Makefile`, executable, three modes | present, executed |
| `requirements.lock`, 22 pins | present |
| `docker/Dockerfile.repro` + `DOCKER_DIGEST` self-test record | present |
| `deposit/EXPECTED_SHA256.json`, 6 digests | present, verified 6/6 |
| git repository, branch `main`, tag `v0.9.1`, clean tree | present |
| `.zenodo.json`, `CITATION.cff` | present, DOI field pending |

Only two values are missing: the public URL and the minted DOI. Both are
placeholders in exactly four places, listed under step 5.

---

## Optional step 0 — the reproducibility pilot collection

*Journal of Cheminformatics* lists a collection titled **"Improving
Reproducibility and Reusability in the Journal of Cheminformatics"**
(<https://link.springer.com/collections/egbgjbgfbh>). Its description says the
journal is piloting an additional software reproducibility and reusability
review, that "any author whose submission has an associated code repository is
free to participate", and that authors opt in by selecting the collection from
the dropdown during submission.

One caveat I could not resolve from outside: the journal's collections index
lists this collection with the status **Closed**, while the collection page
itself uses the present tense and describes participation as open. The most
plausible reading is that the topical call has closed but the pilot review
continues, but I cannot confirm that, and you should not plan around it.

**What to do:** when you reach the submission form, look for this collection in
the dropdown. If it is there, select it — five of the seven checks already pass
(see the conformance table in `README.md`), and the remaining two are exactly
the deposit steps below. If it is not there, submit normally; the pilot review
is an add-on, not a requirement.

The seven checks, for reference: (1) LICENSE in root, (2) README in root,
(3) public issue tracker, (4) externally archived with a DOI referenced in the
README, (5) installation documentation in the README, (6) straightforwardly
installable, (7) conforms to an external linter. Checks 1, 2, 5, 6 and 7 pass
now. Check 3 follows automatically from step 2 (the repository's Issues tab).
Check 4 is step 4.

---

## Step 1 — create an empty public repository

On GitHub: **New repository → name `admet-screening` → Public → do not
initialise with README, .gitignore or licence** (the deposit already has all
three). Copy the SSH or HTTPS URL it shows.

Why "public": the journal requires the materials to be accessible "without the
need for registration, login or agreement with license terms". A private repo
fails that test even if a reviewer is later given access.

---

## Step 2 — push

```bash
cd C:/Users/huawei/.workbuddy/skills/admet-screening
git remote add origin https://github.com/<your-account>/admet-screening.git
git push -u origin main
git push origin v0.9.0 v0.9.1
```

Expected: the push completes and `git remote -v` now prints `origin`. The two
tags matter because the manuscript cites `v0.9.1`.

Sanity check — this must work from a machine that is not yours:

```bash
git clone https://github.com/<your-account>/admet-screening.git /tmp/verify
cd /tmp/verify && ./reproduce.sh
# expect: [hash] all 6 deterministic table outputs match.
```

If that command succeeds, the reproducibility claim in the paper is literally
true and can be verified by a reviewer in under a minute.

---

## Step 3 — connect Zenodo to GitHub

On Zenodo: **sign in with GitHub → top-right avatar → Settings → GitHub → find
`admet-screening` → flip the switch on.**

`.zenodo.json` is already in the repository, so Zenodo will read the title,
description, keywords and licence from it. **Before publishing, replace the
`creators` entry** — it currently reads `admet-screening contributors`, which
would produce a wrong citation. Use real names and ORCIDs.

---

## Step 4 — create the release that mints the DOI

On GitHub: **Releases → Draft a new release → choose existing tag `v0.9.1` →
title `v0.9.1` → Publish release.**

Zenodo mints the DOI at that moment and shows it on the record page, of the form
`10.5281/zenodo.NNNNNNN`.

---

## Step 5 — replace four placeholders

| Where | Current text | Replace with |
|---|---|---|
| `README.md` (line ~221) | `Zenodo DOI `10.5281/zenodo.XXXXXXX`` | the minted DOI |
| `CITATION.cff` | *(no `doi:` field yet)* | add `doi: 10.5281/zenodo.NNNNNNN` |
| Manuscript, Declarations item 1 | `[https://github.com/ORG/admet-screening]` | the real URL |
| Manuscript, Declarations item 3 | `[10.5281/zenodo.xxxxxxx]` | the minted DOI |

In the manuscript, also change the wording at those two items from *"This cell
is a placeholder pending deposit"* / *"reserved at submission"* to the live
values, and delete the sentence that begins *"Two items remain placeholders at
the time of writing…"*.

Then rebuild and verify:

```bash
python tools/check_deposit_ready.py --paper <manuscript.md>
# expect: READY: all declared artefacts present, no placeholders, remote configured.
```

---

## Step 6 — regenerate the Word files

The manuscript lives outside this repository, in the submission workspace:

```bash
cd <workspace>/output/20261124_jcheminf
python build_manuscript_html.py && python postprocess_html.py
python "$PLUGIN/skills/html-to-doc/scripts/convert_doc.py" \
    --html stage2/formatted-manuscript.html --output <workspace>/ADMET_投稿论文_final.docx
```

Check that the conversion reports `missing 0` and that the abstract is still at
or under 350 words.

---

## What is deliberately not on this list

- **`assets/` (1.2 GB OneADMET SI) and `out_ext/` (100 MB TDC splits)** are
  excluded from the deposit. They carry third-party licences and cannot be
  redistributed; `README.md` says how to obtain them. This is a licensing
  constraint, not an omission, and the manuscript states it.
- **The retrain artefacts** (`out_retrain_check/`) are included, so a reviewer
  can check the drift numbers without spending 41 minutes.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Reviewer gets `bad interpreter: bash^M` | `.gitattributes` not honoured | `.gitattributes` pins `*.sh` to LF; re-clone rather than editing in place |
| `./reproduce.sh` reports MISSING artefacts | clone missing the results files | the deposit must contain `out_keystone_v43/results.json` and `out_keystone_transfer/results.json` |
| Checksums differ after `--full` | expected: `--full` rewrites the files the digests cover | `git checkout --` the two results files, then `./reproduce.sh` |
| Zenodo record has wrong authors | `.zenodo.json` `creators` not edited | edit on the Zenodo record before publishing the DOI |
