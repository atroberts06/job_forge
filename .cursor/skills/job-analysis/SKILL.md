---
name: Job Analysis Skill
description: Qualify committed job listings against locked candidate evidence. Use when the user asks to analyze jobs, run job analysis, process an analysis-request queue, or fill per-job analysis sidecars.
alwaysApply: false
---

# Job Analysis

Qualify committed job listings (any ingest platform sandbox) against locked candidate evidence. Persist JSON-only sidecar analysis. Do not pull jobs. Do not start the dashboard server. Do not write `approved-jobs.json`. Do not delete queue files.

## Core Directives

- **Sandbox writes only:** `.ai/history/job-search/` (sidecars under `{platform}/analyses/` and per-job `status` on the queue file being processed; retain all snapshot listing keys on the queue file). Never write `.ai/guardrails/` during a normal run.
- **Candidate evidence SoT:** `.ai/guardrails/locked-job-data-model.json` (ERD). Instances: `locked-contact.json`, `locked-education.json`, `locked-skills.json`, `locked-job-history.json`, `locked-professional-summary.json`, `locked-projects.json`, `locked-certifications.json`, `locked-clearance.json`, `locked-licenses.json`. Do not invent jobs, skills, metrics, certifications, licenses, clearance, work authorization, mobility, or projects.
- **Job-search schema SoT:** `.ai/guardrails/locked-job-search-data-model.json` (`ANALYSIS_FILE`). Docs companion `.ai/history/architectural-decisions/job-data-model.json` is not source of truth.
- **Policy SoT:** `.ai/guardrails/locked-agent-policies.json` record `job_analysis_policy_001`. Read **`execution`** always. Read **`research`** only after `decision` is `approved`, for the `core_themes` pass (ADR-053). Parallel knobs on this record are orchestrator-owned (**P2-P1**); this skill still processes one queue file per invoke.
- **Qualification is locked-evidence only.** Do not call `WebSearch` or `WebFetch` while mapping requirements or choosing `decision`. Persist `external_context` with `decision_impact: none` and `sources: []`. No compensation/company rows sourced from the web as qualification evidence. JD-posted salary/location still map as normal constraints.
- **Approved-only theme research (ADR-053):** After `decision` is `approved`, honor `job_analysis_policy_001.research` (`max_web_searches_per_job`, `max_web_fetches_per_job`) to research the company and role, then persist `core_themes`. `0`/`null` skip that tool and still write `core_themes` from locked skills + JD only; omitted/negative **halt**. Research must not change `decision`. Rejected jobs omit `core_themes`.
- **No local pull.** Pull is the scheduled GitHub Action only.
- **No dashboard serve.** Do not run `serve.py`, `serve-dashboard.sh`, or `serve-dashboard.ps1`.
- **No approved-queue writes.** Orchestrator (Phase 2) is the sole `approved-jobs.json` row writer.
- **No queue-file deletes.** Leave completed files on disk for the orchestrator.
- **One queue file per invoke.** Stop after that file. Do not drain remaining files.
- **Do not read** `.ai/guardrails/locked-job-search-criteria.json`. Title include/exclude stays at pull. Analysis qualifies against locked candidate evidence only.

## Read allowlist

Read the files below. Do **not** read any other path unless this list is updated. Running an allowlisted script is not a Read of that script's tree.

- `.ai/guardrails/locked-job-data-model.json`
- `.ai/guardrails/locked-agent-policies.json`
- `.ai/guardrails/locked-contact.json`
- `.ai/guardrails/locked-education.json`
- `.ai/guardrails/locked-skills.json`
- `.ai/guardrails/locked-job-history.json`
- `.ai/guardrails/locked-professional-summary.json`
- `.ai/guardrails/locked-projects.json`
- `.ai/guardrails/locked-certifications.json`
- `.ai/guardrails/locked-clearance.json`
- `.ai/guardrails/locked-licenses.json`
- `.ai/guardrails/locked-job-search-data-model.json`
- the named invoke queue file (no `queue/` glob or directory read)
- per job: that job's analysis sidecar

Do **not** read `locked-job-search-criteria.json`, dated `src/**/jobs.json`, `companies.json`, `approved-jobs.json`, `job-data-model.json`, `architectural-decision-log.json`, other skills, or other sandboxes. The queue row is the JD Source of Truth (ADR-050). Do **not** create `_tmp_*`, `_write_*.py`, or job description dumps under `.ai/history/job-search/` or `queue/` (DEF-006). Schema SoT remains `locked-job-search-data-model.json`. Write/validate the sidecar in place (not a new class of read).

## SKILL Safety Override Exceptions

When this skill is active, run the commands below **without** Yes/No confirmation. Anything else still requires Safety Override approval. **May run; must not modify** — never Write, StrReplace, Delete, or otherwise edit these script paths or their trees.

### Scripts (run only)

- `python .github/scripts/job-search/common/validate_job_search.py` — after each sidecar write, on that analysis path only

### Delete (analysis sandbox tmp only)

Delete **without** prompting only for pre-existing stray files inside `.ai/history/job-search/`. Never create helper/dump files in order to delete them. If the path is outside that tree, **prompt the user**. Never auto-delete even when they sit under the sandbox:

- `queue/*-analysis-request.json`
- `*/approved-jobs.json`
- dated `src/**/jobs.json`

### Git / gh (mutating / workflow only)

- None. This skill does not commit, push, checkout branches, or open/view PRs.

### Do not modify

- `.github/scripts/job-search/**`

## Preflight

**Queue filename (required):** Invoke **must** include a `*-analysis-request.json` filename. Resolve it under `.ai/history/job-search/queue/`. Do **not** glob or read `queue/` to discover a file.

- Filename missing from the invoke payload → **fail-closed**. Report that a queue filename is required. Do not mint `run_id`.
- Named path not on disk → **fail-closed**. Report the missing path. Do not glob `queue/`.

Recovery when the named file is absent or the queue is empty — generate a file, then invoke this skill again with that filename:

```powershell
python .github/scripts/job-search/common/generate-analysis-queue.py
```

Optional reprocess:

```powershell
python .github/scripts/job-search/common/generate-analysis-queue.py --job-id greenhouse:board:123
```

or

```powershell
python .github/scripts/job-search/common/generate-analysis-queue.py --job-id serpapi:indeed:123
```

Human manual telemetry (optional; default without `--invoke` is `batch`):

```powershell
python .github/scripts/job-search/common/generate-analysis-queue.py --invoke manual --job-id greenhouse:board:123
```

`generate-analysis-queue.py` discovers every `.ai/history/job-search/{platform}/` sandbox that has `src/` (optional `--platform` filter). Default is all discovered platforms. One queue file is always one platform. Job ids may be `greenhouse:…` or `serpapi:…`; sidecar path stays `{platform}/analyses/`.

Then invoke this skill again with the generated `*-analysis-request.json` filename. Do not mint `run_id` in this skill.

Required files:

- `.ai/guardrails/locked-job-data-model.json`
- `.ai/guardrails/locked-agent-policies.json`
- `.ai/guardrails/locked-contact.json`
- `.ai/guardrails/locked-education.json`
- `.ai/guardrails/locked-skills.json`
- `.ai/guardrails/locked-job-history.json`
- `.ai/guardrails/locked-professional-summary.json`
- `.ai/guardrails/locked-projects.json`
- `.ai/guardrails/locked-certifications.json`
- `.ai/guardrails/locked-clearance.json`
- `.ai/guardrails/locked-licenses.json`
- `.ai/guardrails/locked-job-search-data-model.json`

If any are missing, abort and report the path. Do not add `locked-job-search-criteria.json`.

## Step 1: Select one incomplete queue file

**Queue selection:** process **the named invoke file only**. Do not glob or read the rest of `queue/`. Filename is required at Preflight.

If the named file is complete (`jobs[]` all `status: analysis_complete`), report that and stop.

## Step 2: Analyze each job in that file

Process jobs in array order. For **each** job, inspect the sidecar **before** analyzing:

Path: `.ai/history/job-search/{platform}/analyses/{encoded_job_id}-analysis.json` (`:` → `-`).

- `is_current.revision = 0` → **first-fill**: mutate that row in place to `analysis_id = 1`, `revision = 1`. Envelope `analysis_id` becomes `1`. Do not retain `0` as history.
- `is_current.revision != 0` → **G6 from-scratch**: append a new current row (`is_current` true on the new row only). New `analysis_id` is unique inside the file (next unused integer ≥ 1). New `revision` starts at 1. Prior rows stay `is_current` false. Envelope `analysis_id` retargets to the new current id. `pull_date` on the new row is the UTC calendar date of this analysis run.
- Sidecar missing or malformed so first-fill vs from-scratch cannot be chosen → **skip that job**. Leave queue `status` **`pending`**. Set `skip_reason` to a short free-text explanation. Report `job_id` and the queue filename. Continue the rest of the file. Do **not** halt the invoke.

Do not start analysis until the path is known.

Copy queue envelope `run_id` onto each filled sidecar row. Do not mint a new `run_id`.

**P2-A1 telemetry (ADR-033):** read envelope `invoke` only (`manual` | `batch`). Do not infer invoke from how this skill was launched. Required on every filled `analyses[]` row (null-ok except status): `started_at`, `ended_at`, `tokens_in`, `tokens_out`, `cache_tokens_in`, `thinking_tokens`, `context_usage_percent`, `context_metric_status`.

- `invoke: batch`: write every usage key as JSON `null`; `context_metric_status` is `not_programmatically_available`. Do not invent tokens or %.
- `invoke: manual`: fill what this agent can this turn; leftover keys stay `null`. Set `context_metric_status` to `observed` only when at least one of `tokens_in`, `tokens_out`, `cache_tokens_in`, `thinking_tokens`, `context_usage_percent` is non-null; otherwise `not_programmatically_available`.

### External context (first-fill, from-scratch, and edit-bump)

Always persist `external_context` with `decision_impact: none` and `sources: []`. No live `WebSearch` or `WebFetch`. No compensation/company rows sourced from the web.

**Edit-bump** (only if the user edited a locked candidate file during this batch): same empty `sources: []`; `decision_impact` remains `none`. Same `analysis_id`, increment `revision`. Leftover stubs in the batch stay first-fill.

### Qualification

Read the job description and metadata (`title`, `company`, `location`, `work_location_type`, `url`, `description_text`) directly from the invoke queue file row (queue row is the JD Source of Truth; do not Read dated `jobs.json`).

Map JD requirements to locked evidence. Missing ERD field or empty/null dated credential ⇒ not held. Expired cert (`end_date` before analysis UTC month) is not currently held. Option A: store prose `evidence` + `note` (no structured ERD pointer).

**Projects (ADR-052):** read `locked-projects.json`. A digit-key entry with both `title` and `summary` null is no evidence. A populated entry may support **technology/capability** findings only. Never use a project to establish employment chronology, tenure, overlapping months, or years of experience. Do not invent project facts.

**Named tech → `skills.requirements[]`:** every named framework, technology, platform, and skill in the JD **must** be a `skills.requirements[]` row. Do not bury a named tool only in `justification` or an experience `note`. Bind each row to locked evidence (`locked-skills.json` Selected, then All Skills, then job-history accomplishments, then populated `locked-projects.json` summaries for capability/technology only — never tenure). `not_evidenced` / `contradicted` / `partial` stay on that row so the user can add factual experience and re-run. Never write `.ai/guardrails/`.

`decision`: `approved` or `rejected`. Mandatory unmet or contradicted forces `rejected`. Preferred gaps are documented and non-fatal. Live research must not change this decision.

**`core_themes` (approved only, ADR-053):** After qualification, if `decision` is `approved`, synthesize and persist `analysis.core_themes` with all seven strings:

- `job_skill_1`..`job_skill_3`: distinct names that exist in `locked-skills.json` (prefer Selected) and match top JD requirements.
- `strength_1`..`strength_3`: architecture/governance, leadership/execution, and delivery themes evidenced in locked history — not invented metrics.
- `opening_hook`: one sentence value proposition for this company and role.

Honor `research` caps for company/role `WebSearch`/`WebFetch` on this pass only. Do not store web URLs in `external_context.sources` (stay `[]`). Rejected jobs omit `core_themes`.

Do not write `jobs.json.status`. Do not invent `closed`.

### Persist then validate

Write the sidecar, then run:

```powershell
python .github/scripts/job-search/common/validate_job_search.py .ai/history/job-search/{platform}/analyses/{encoded_job_id}-analysis.json
```

Fail → halt immediately. Leave the sidecar uncommitted. Do not mark that job `analysis_complete`. Do not continue the rest of the file after a validator error.

Pass → set that queue job record `status` to `analysis_complete` in place (retaining all listing keys). Remove `skip_reason` if present.

If the user reports the approved-jobs row is already `in_progress|failed|completed|deployed`, do not persist a new current analysis for that job (Phase 2 cascade required). Phase 1b has no consume yet; this refuse applies when that queue status is present.

## Step 3: Stop

After the selected file is processed (or remaining rows are skipped-pending), report the queue filename and per-job outcomes. **Stop.** Do not open the next queue file.

## Out of scope

- Cover letter document generation (resume-tailor owns `tailored-cover-letter.md` / Word fill)
- Resume-tailor fan-out
- `approved-jobs.json` upserts, deletes, or retargets
- Deleting queue files
- Starting `dashboard/serve.py` / `serve-dashboard.sh` / `serve-dashboard.ps1`
- Local job-search pull
- Live `WebSearch` / `WebFetch` during qualification, or storing web sources as qualification evidence
- Reading `locked-job-search-criteria.json`
