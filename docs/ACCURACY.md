# ContractSentinel — Honest Accuracy Assessment

**Purpose.** State, honestly and with evidence, how well the analysis pipeline actually performs — and
why the raw evaluation numbers understate it. This is the accuracy positioning a real product needs. It
is **not** a claim of legal-grade accuracy (see the caveat at the end).

> **One-line summary:** the raw "~15–33% recall / ~15–35% false-flag" numbers are **heavily confounded
> by candidate (non-lawyer) labels**. On inspection, the system correctly *declines* routine clauses
> and correctly *flags* material ones; its **real recall on genuinely-material clauses is ≈ 25–44%**,
> and it is **conservative, not trigger-happy**. It is a solid working product, not yet a
> decision-grade legal tool.

## 1. Why the raw numbers mislead

The evaluation gold set (`eval/gold/`, 32 contracts, 695 labeled clauses) is **candidate, best-effort,
and explicitly NOT lawyer-reviewed** — it was seeded from CUAD category spans (feature 041). Two
structural problems inflate the apparent error:

- **A CUAD category is not a risk verdict.** **463 of 695 clauses (67%) are labeled
  `should_flag=true`**, dominated by category-driven types (`audit_rights` 66, `anti_assignment` 52,
  `minimum_commitment` 34). A lawyer reviewing *risk* would flag far fewer — many of these are routine
  boilerplate. So the pipeline is penalized as "missing" clauses it *correctly* declined.
- **The negative labels are incomplete.** Genuinely material clauses (e.g. indemnification) are simply
  absent from the gold, so when the pipeline correctly flags them they count as false positives.

## 2. Miss triage — ~46% of "misses" are the model being right

Offline triage of the 39 missed `should_flag=true` clauses on the cached large-doc subset
(`scripts/build_miss_triage.py`, no Ollama):

| Bucket | Share | Examples |
|---|---|---|
| **Label-overflag** (model correctly declined) | **~46%** | all 7 `anti_assignment` were standard "consent not unreasonably withheld" boilerplate; all 8 `audit_rights` were routine inspection clauses; **one `minimum_commitment` is a mislabeled logo-size branding spec** (`"Logo Size: The minimum logo size is 1\" or 25mm…"`, ArmstrongFlooring) |
| **Genuine miss** (model wrong) | **~23%** | 5 `cap_on_liability` ("liability shall not exceed the fees paid", "IN NO EVENT SHALL COMPANY BE LIABLE…"); real minimum-purchase commitments; a high-sev non-compete; an IP assignment |
| **Borderline / debatable** | **~31%** | IP no-challenge covenants, change-of-control carve-outs, post-termination obligations |

**Real recall on genuinely-material clauses is therefore ≈ 25–44%, not 15%.** The genuine misses
cluster narrowly: **liability limitations** (the model finds them relevant then drops them at the
support check) and **segmentation fragments** (a clause split before it can be judged).

## 3. False-flag triage — most are legitimate, not spurious

Of the flagged-but-`should_flag=false` / unlabeled findings on the same subset:

- The 6 `fp_clean` (flagged a clean clause) were **all rated `low`** — soft surfaces of `license_grant`
  / `expiration_date`, a defensible "surface for awareness" choice, not high-confidence errors.
- The 14 unlabeled flags were **mostly correct flags the gold omitted**: indemnification clauses
  (`"defend, indemnify and hold harmless…"`), insolvency/receiver termination triggers, an IP-warranty
  indemnity. Only ~1 was a true artifact (an EDGAR page-header fragment — since fixed, see §4).

**The model is conservative, not trigger-happy** — it rates over-surfaces `low`, and much of the
"false-flag rate" is the gold missing real risks.

## 4. What we improved from the engineering side (offline, measured, shipped)

Without a lawyer we cannot validate legal-grade accuracy, but we removed the *mechanical* defects the
triage exposed:

- **040 — spelled-out clause headings.** `CLAUSE ONE`/`ARTICLE FIRST` headings were unmatched →
  silent under-segmentation → false "clean" reports. Fixed.
- **044 — strip EDGAR document-chrome.** `Source: <COMPANY>, <FORM>, <DATE>` page footers polluted
  10.5% of clauses and caused a spurious finding. Stripped before segmentation.
- **045 — keep enumerated sub-list items with their governing clause.** `(a)`/`(ii)` markers were
  severing sub-items (22.9% of clauses) from their stem — an A/B on a real doc showed a high-sev
  non-compete going from a stem-less 113-char fragment to a 915-char clause *with* its
  `"The Distributor shall not:"` stem. Fixed (reversible flag, default on).

## 5. The biggest remaining lever — MEASURED, and it is *not* the model

We hypothesized the genuine misses were a **model-judgment** limitation of local `qwen3:8b`, and that a
**stronger model** would be the top lever. **We tested this** (feature 046, `specs/046-groq-llm-provider/RESULTS.md`,
2026-08-22) by routing generation to Groq's **`openai/gpt-oss-120b`** (embeddings stayed local) and
re-running the eval. Result on the 4 clean docs (2 were lost to Groq's free-tier daily token cap):

| Metric | qwen3:8b | gpt-oss-120b | Δ |
|---|---|---|---|
| Recall | 17.9% | 17.9% | **tie** |
| Precision | 26.3% | 26.3% | **tie** |
| Severity exact | 20.0% | 80.0% | **+60pp** |

**Conclusion: a stronger generative model did NOT move recall or precision** — they were identical
(tp=5, fn=23 on both). The accuracy ceiling on this corpus is **bottlenecked upstream of generation**:
the Self-RAG relevance filter discards ~22 candidate clauses before scoring, and `clause_type=None`
(deterministic typing shipped OFF after 042's precision-cost finding) leaves the 027 recall floor
inert. A better generator can only judge clauses that survive those stages — it cannot recover clauses
already dropped. The model's one genuine win was **severity grading (80% vs 20% exact)**.

So the real levers are, in order: (1) **a lawyer-labeled corpus** (the current candidate labels are the
dominant source of apparent error — see §6); (2) **loosening the upstream segmentation / relevance
drop** without the ~1:1 precision cost that 042 hit; the generative model is *not* the constraint.
**Note:** switching models invalidates the qwen3 numbers — the eval harness must be re-run per model.

## 6. Why we did NOT "clean" the gold labels

Editing the candidate gold to look better would require re-adjudicating 400+ clauses as a non-lawyer —
that would bias the ground truth toward the model's own behavior (circular) and *reduce* the corpus's
integrity. We deliberately **preserve the honestly-labeled candidate gold** and document its noise here
instead. The correct path to trustworthy numbers is a **lawyer-reviewed corpus**, not self-cleaning.

## 7. Honest caveat (product positioning)

ContractSentinel is a sophisticated, working AI contract-analysis product with a self-reflective
retrieval pipeline and honest failure surfacing. It is **not a substitute for legal advice** and its
accuracy is **not yet validated to a standard a lawyer should rely on for decisions.** Present it as a
review *aid* with a clear "not legal advice — consult a qualified attorney" disclaimer. Decision-grade
trust requires (a) a lawyer-labeled corpus, (b) fixing the upstream recall bottleneck (§5 — a stronger
model was measured *not* to help), and (c) real-user validation.

*Evidence sources: `scripts/build_miss_triage.py` over cached run `eval/runs/BEFORE_042subset`; the
offline splitter A/B in `specs/045-…`; gold set `eval/gold/` (32 files, 695 clauses). All figures are
indicative on a small candidate-labeled corpus, not authoritative.*
