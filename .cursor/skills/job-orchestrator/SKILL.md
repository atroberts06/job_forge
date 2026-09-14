---
name: Job Orchestrator Skill
description: Thin local coordinator for job-analysis consume, tailor-queue fan-out, and ledger commits. Use when the user asks to run the job orchestrator, drain analysis/tailor queues, consume analysis_complete rows, or re-run one job_id after adding locked evidence.
alwaysApply: false
---

# Job Orchestrator

Thin coordinator. Run **scripts + git only**. Do not run resume-tailor or job-analysis LLM steps inline. Do not create feature branches. Do not write `.ai/guardrails/` candidate evidence. Do not edit this skill or other human-maintained skills during a normal run.

Policy lookups: `.ai/guardrails/locked-agent-policies.json` (`job_analysis_policy_001`, `resume_tailor_policy_001`). Orchestrator has no `policies[]` row. Instead, orchestrator uses the configuration of the other agents to manage the workflow.

## SKILL Safety Override Exceptions

When this skill is active, run the commands below **without** Yes/No confirmation. Invoking `/job-orchestrator` (or otherwise activating this skill) **is the user's explicit approval** for those commands, including **creating commits directly on `main`** (protected-destination write) and **`git push origin main`** (protected main-branch publication) when they match this section. Do not treat Auto-review / smart-mode prompts for those matching operations as requiring a second confirmation. Anything else still requires Safety Override approval. **May run; must not modify** — never Write, StrReplace, Delete, or otherwise edit these script paths or their trees.

### Scripts (run only)

- `python .github/scripts/job-search/common/orch_run_log.py` (`--truncate` / `--append` / `--telemetry`)
- `python .github/scripts/job-search/common/consume_analysis_queue.py` (optional `--queue-file`)
- `python .github/scripts/job-search/common/generate-analysis-queue.py` (optional `--job-id`; never `--invoke`)
- `python .github/scripts/job-search/common/purge_dated_src.py`
- `python .github/scripts/job-search/common/validate_job_search.py`
- `python .github/scripts/resume-tailor/generate-tailor-queue.py` (optional `--job-id`)
- `python .github/scripts/job-search/common/claim_tailor_in_progress.py` (`--queue-file`)
- `python .github/scripts/job-search/common/consume_tailor_queue.py` (optional `--queue-file`)
- Dashboard serve (P2-D1 only if port 8765 closed): `.ai/history/job-search/dashboard/serve.py`, `serve-dashboard.sh`, or `serve-dashboard.ps1`

### Git / gh (mutating / workflow only)

**Protected `main` authorization:** the user has explicitly approved these writes on the checked-out `main` branch and publishing them to `origin/main`. Never `--force` / force-push `main`.

- `git checkout main`
- `git add` — job-search consume/ledger paths only (sidecars, `approved-jobs.json`; never stage resume-tailor sandboxes or `*-tailor-request.json`)
- `git commit` **on `main`** (protected-destination write) — messages `chore(job-search): orchestrator consume {UTC date}` and `chore(job-search): orchestrator tailor ledger {UTC date}` only
- `git push origin main` (authorized main-branch publication of those commits only) — never force-push `main`
- `gh pr view {number}`

### Do not modify

- `.github/scripts/job-search/**`
- `.github/scripts/resume-tailor/**`
- `.ai/history/job-search/dashboard/serve.py`
- `.ai/history/job-search/dashboard/serve-dashboard.sh`
- `.ai/history/job-search/dashboard/serve-dashboard.ps1`

## Preflight

1. Confirm checkout is `main`. If not, return to `main` before start (do not create branches).
2. Truncate the orchestrator run log, then **P2-D1** dashboard at `http://127.0.0.1:8765/dashboard/`. If port 8765 is closed, start `.ai/history/job-search/dashboard/serve.py` (`serve-dashboard.sh` or `serve-dashboard.ps1`).

```powershell
python .github/scripts/job-search/common/orch_run_log.py --truncate
```

Then write the replaceable telemetry trailer (`started_at` once; usage fields `null` until observed; `ended_at` stays `null` until persist-at-run-end):

```powershell
python .github/scripts/job-search/common/orch_run_log.py --telemetry '{"started_at":"<UTC now Z>","ended_at":null,"tokens_in":null,"tokens_out":null,"cache_tokens_in":null,"thinking_tokens":null,"context_usage_percent":null,"context_metric_status":"not_programmatically_available"}'
```

Dual-write: every chat-visible status line this skill would print also goes to `.ai/history/orchestrator/run.log` (UTF-8, UTC ISO prefix). **Each orch turn** appends the chat line **and rewrites** the telemetry trailer with a cumulative snapshot of **this orch session only** — not a sum of nested analysis/tailor agents. Fill what this agent can; do not invent tokens or %. Subagent transcripts appear only if copied into this agent's chat/log. Persist the file at run end (do not delete). Set `ended_at` on the final trailer rewrite.

```powershell
python .github/scripts/job-search/common/orch_run_log.py --append "your chat line"
python .github/scripts/job-search/common/orch_run_log.py --telemetry '{"started_at":"<same as truncate>","ended_at":null,"tokens_in":null,"tokens_out":null,"cache_tokens_in":null,"thinking_tokens":null,"context_usage_percent":null,"context_metric_status":"not_programmatically_available"}'
```

3. If `.ai/history/job-search/queue/*-analysis-request.json` has any `status: analysis_complete` rows → run consume:

```powershell
python .github/scripts/job-search/common/consume_analysis_queue.py
```

Repeat until no `analysis_complete` rows remain (or pass `--queue-file` for a specific leftover). Fail-closed if the script exits non-zero.

## Analysis loop

1. If no incomplete analysis queue files remain (`jobs[]` not all `analysis_complete`) →

```powershell
python .github/scripts/job-search/common/generate-analysis-queue.py
```

Never pass `--invoke`. Default envelope `invoke` is `batch`. `generate-analysis-queue.py` discovers every sandbox with `src/` (optional `--platform`). Default is all platforms; one queue file is one platform.

2. **P2-P1:** if more than one incomplete analysis queue file exists, ask **Sequential/Bounded Parallel** before bounded parallel analysis. Read `job_analysis_policy_001.parallel` (`max_parallel_agents`, `parallel_requires_confirmation`, `parallel_declined_behavior`). Sequential → sequential. Bounded Parallel → at most `max_parallel_agents` analysis invokes. Consume still **after** each invoke (no overlap).
3. Launch a **fresh** job-analysis agent per invoke. Payload: analysis queue **filename** + repo root. Agent follows `.cursor/skills/job-analysis/SKILL.md` and stops after that file.
4. Consume that file:

```powershell
python .github/scripts/job-search/common/consume_analysis_queue.py --queue-file .ai/history/job-search/queue/{run_id}-analysis-request.json
```

5. Repeat until no eligible jobs and no `analysis_complete` rows awaiting consume.
6. **P2-M1a / P2-T1:** purge dated `src/`, validate, then **commit on `main` and `git push origin main`** (explicitly approved protected-destination write and main-branch publication; see Safety Override Exceptions). 

```powershell
python .github/scripts/job-search/common/purge_dated_src.py
```

Validate **each** existing `{platform}/approved-jobs.json` under `.ai/history/job-search/` (skip `queue` and `dashboard`; skip missing files). Do not validate only greenhouse.

```powershell
python .github/scripts/job-search/common/validate_job_search.py .ai/history/job-search/{platform}/approved-jobs.json
```

Stage only job-search consume paths: sidecars, `approved-jobs.json` (`status: approved`), analysis queue deletions, dated-`src/` purge. Never stage resume-tailor sandboxes or gitignored `*-tailor-request.json`.

Commit message: `chore(job-search): orchestrator consume {UTC date}`

`git push origin main` (authorized). Working tree must be clean before fan-out.

## Fan-out loop

7. Mint tailor-request files (`resume_tailor_policy_001.execution.max_jobs_per_agent`; script mints `run_id`s):

```powershell
python .github/scripts/resume-tailor/generate-tailor-queue.py
```

`generate-tailor-queue.py` discovers every sandbox with `src/` (optional `--platform`). Default is all platforms; one tailor-request file is one platform. Queue-invoked identity is `company_slug` / `position_slug` on each row (ADR-045 always-suffix from `source_job_id`). Claim stays file-level.

If nothing eligible, skip to the report. Do not push `main` again if the ledger was not mutated.

8. For each incomplete tailor-queue file (lowest `batch_number` first):
   - Confirm checkout is `main`.
   - Claim that file's **pending** rows onto the ledger as `in_progress` **locally** (working tree; no `main` commit/push). Per-job claim is forbidden; tailor must not write `approved-jobs.json`.

```powershell
python .github/scripts/job-search/common/claim_tailor_in_progress.py --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json
```

   - Launch a **fresh** resume-tailor agent. Payload: tailor queue **filename** + repo root. Agent processes **every row** in that file (serial), returns to `main` between jobs, reports filename + per-job status, and **stops**. It does not write `approved-jobs.json` or delete the queue file. Claim sets `in_progress` only; the tailor skill owns `started_at` / `attempt_count`.
9. After the agent returns:
   - Confirm checkout is `main`.
   - Validate each `tailor_complete` PR: `gh pr view {number}` — exists, base is `main`.
   - Consume rows onto the ledger **locally** (drains completed rows and deletes the file if fully drained):

```powershell
python .github/scripts/job-search/common/consume_tailor_queue.py --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json
```

   Manual bulk (no `--queue-file`) consumes every `*-tailor-request.json` in batch order. The orch loop still passes one file.

   - **No** `main` commit/push in this loop. Then the next file.
10. After the last file: validate each existing `{platform}/approved-jobs.json`. **Commit on `main` and `git push origin main`** (explicitly approved) with mutated ledger execution fields only (`completed`/`failed` + `pr_*` / **P2-E1**). Skip this push if the ledger was not mutated.

Commit message: `chore(job-search): orchestrator tailor ledger {UTC date}`

**Orchestrator run ends.** Rewrite the telemetry trailer with `ended_at` set (same closed keys; still this orch session only). Report status in chat. Human then reviews/approves/merges resume PRs, deletes feature branches, prunes, checkouts `main`. CD Drive follows merge (ADR-006).

## Single-job re-run (P2-G6s)

Alternate entry when the user names one `job_id` after editing locked evidence. Do not run the full-day generator drain. Still scripts + git only; still fresh analysis/tailor agents. Do **not** close/abandon the resume PR. Do **not** delete the feature branch. Do **not** clear `pr_*` / `sandbox_path` / `feature_branch`.

1. User (human) edited locked candidate files. Agents do not write `.ai/guardrails/`.
2. Read the ledger row for that `job_id` (or note it is missing).
3. **Pre-handoff** (`approved` or no ledger row):
   - `python .github/scripts/job-search/common/generate-analysis-queue.py --job-id {id}` (fail-closed if leftover analysis queues). Do **not** pass `--invoke` (stays `batch`).
   - Fresh job-analysis (G6 from-scratch).
   - Consume (delete/retarget/upsert). First-fill writes the full ledger shape (resume-tailor keys `null`). Update-fill refreshes analysis keys and keeps populated resume-tailor keys.
   - If still `approved`: `python .github/scripts/resume-tailor/generate-tailor-queue.py --job-id {id}` and fan-out that file.
4. **Post-handoff** (`in_progress` | `failed` | `completed` | `deployed`):
   - Consume retargets the row to `status: approved` and keeps `pr_*` / `sandbox_path` / `feature_branch` / `attempt_count`. Then step 3 (analysis + consume already done if you started from consume; otherwise generate-analysis-queue `--job-id`, analyze, consume, then generate-tailor-queue `--job-id` and fan-out).
   - Tailor **reuses** the copied `feature_branch` when it still exists (checkout, wipe generated artifacts, push, reuse the open PR). If the branch is gone after fetch, from-scratch with minted slugs. **P2-X1** does not fire on the same `id`.
5. Same **P2-M1a** commits as a normal run (post-analysis push; post-tailor ledger push if fan-out ran).

## Subagent handoff payloads

| Target | Payload (minimum) |
|--------|-------------------|
| job-analysis | Analysis queue filename; repo root |
| resume-tailor | Tailor queue filename; repo root (agent processes every row in the file) |

## Out of scope

- Creating feature branches
- Writing `approved-jobs.json` from analysis or tailor agents
- Staging `{company}/{position}/` or `*-tailor-request.json` on `main`
- Merging resume-tailor PRs
- Rewriting git history
- P2-R1 rebuild-manifest cascade
