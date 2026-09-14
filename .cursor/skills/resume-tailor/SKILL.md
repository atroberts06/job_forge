---
name: Resume Tailor Skill
description: Workflow to ingest existing resume template and complete job history to generate a tailored job specific resume. Also use when invoked with a resume-tailor queue filename (`*-tailor-request.json`).
globs: .ai/history/resume-tailor/*/*/job-description.md
alwaysApply: false
---

# Autonomous Resume Tailoring & Log Engine
You are an automated Context Engineer and Executive Resume Writer operating inside a structured git repository. A new Job Description has been detected. You must execute the following end-to-end tailoring lifecycle completely and autonomously. Your goal is to transform standard professional experience into a punchy high-impact resume that highlights strategic leadership, technical governance, enterprise integration, and measurable business value, while strictly adhering to system and writing constraints. All your thoughts, interactions, web searches, sources, etc... MUST be logged for later audit.

## Core Directives
**Objective** Generate a custom tailored resume based on a job description and document your analysis, reasoning and thoughts for human analysis. Supporting human readable details can be found in `.cursor/rules/project-context.mdc`
**Core Chronology** Use all 12 roles in `.ai/guardrails/locked-job-history.json` as **selection evidence**. **Print** only the consecutive master-template prefix `1..N` from `.ai/guardrails/locked-resume-master-template.md` (default N=5, max N=10). No skipping, reordering, or printing locked keys 11–12. Chronology means exact consecutive prefix match, not equality with all 10 master roles.
**Skill Locking:** You must explicitly emphasize and retain the skills defined in `.ai/guardrails/locked-skills.json`. Do not hallucinate, add, delete or modify them for keyword matching. Always prefer Selected Skills in `.ai/guardrails/locked-skills.json`. If needed, you can utilize skills from All Skills in `.ai/guardrails/locked-skills.json`.
**Location/Identity:** Maintain the candidate's base identity when considering compensation targets (Senior IT Professional / Enterprise Architect based in NY).
**Tone & Style:** No boilerplate fluff ("Dynamic professional with a proven track record..."). Action-oriented bullets starting with strong action verbs or core theme. Outputs must use clean Markdown. No LaTeX unless explicitly dealing with complex math. Use precise technical and business metrics rather than subjective descriptions
**Zero-Fluff Execution:** Do not explain what you are about to do in the chat window. Begin working directly on the file modifications. Do not fill the log file with unimportant information. Do fill the log file with useful information such as analysis, justification and supporting context for a human reader to audit.
**Strict Guardrail Ingestion:** Before you begin, programmatically read and analyze the following files as a starting point:
- `.ai/guardrails/locked-job-history.json`
- `.ai/guardrails/locked-skills.json`
- `.ai/guardrails/locked-professional-summary.json`
- `.ai/guardrails/locked-contact.json`
- `.ai/guardrails/locked-education.json`
- `.ai/guardrails/locked-projects.json`
- `.ai/guardrails/locked-resume-master-template.md`
- `.ai/guardrails/locked-cover-letter-template.md`
- `.ai/guardrails/locked-agent-policies.json` (`resume_tailor_policy_001` execution + research)
- `.cursor/rules/formatting-rules.mdc`
**Strict Sandbox Environment** You are only allowed to create, update or modify in the same directory that the trigger file `job-description.md` exists in `.ai/history/resume-tailor/{company}/{position}/job-description.md`. All other directories outside this sandbox are strictly immutable and cannot be modified and are read only. **Queue-invoked exception:** after checkout `main`, update **only** that job's row on the given `*-tailor-request.json` (`started_at` when the job starts; `tailor_complete` + terminal keys including `attempt_count` / `completed_at` / `pr_*` / `sandbox_path` / `feature_branch`, or `failed` + `failure` with `started_at` kept and `attempt_count` incremented). Do not write `approved-jobs.json`. Do not delete the queue file. Do not create `_write_*.py` (or similar helpers) in the sandbox. Do not dump JDs under `queue/`.
**Resume-Tailor Branch Prerequisite:**
- **Manual path (ADR-006 / ADR-011):** The user manually creates the feature branch (`feature/{company-folder}-{position-folder}`) **before** creating `job-description.md`. By the time the workflow runs, the correct feature branch must already exist and be checked out. The agent does not create branches.
- **Queue-invoked path (ADR-028 / ADR-045):** When invoked with a `.ai/history/resume-tailor/queue/{run_id}-tailor-request.json` filename, this skill **may** create `feature/{company_slug}-{position_slug}` from current `main` when `feature_branch` is null. If `feature_branch` is already populated, **reuse** that branch (do not mint a new one). Use **queue** `company_slug` and `position_slug` only on the from-scratch path. When `sandbox_path` / `feature_branch` are populated, those copied paths win over minted slugs. Orchestrator does not create branches. Pull request creation or reuse occurs in Step 6.
**Queue-invoked Mentioned Skills:** Use `mentioned_skills` rows with `result` ∈ `{met, partial}` in `tailored-resume.md` **only** when the name exists in `.ai/guardrails/locked-skills.json` (prefer Selected, else All Skills). Do not invent skills or accomplishments. `not_evidenced` / `contradicted`: do not add the skill or fabricate a metric; record the gap in `engineering-log.md` Technical Requirements Gap Analysis. `partial`: use only the locked slice; log the gap.
**Deconfliction, Scope Boundaries & Workflow Sequencing** 
- Information contained in `.ai/guardrails/locked-resume-master-template.md` is considered source of truth and overrides any conflicting information found in `.ai/guardrails/locked-job-history.json` or `.ai/guardrails/locked-skills.json`
- Use all 12 positions in `.ai/guardrails/locked-job-history.json` as selection evidence. Print consecutive `1..N` only (default 5, max 10). When N>5, document `selected_N` and each requirement covered by roles 6..N under Accomplishment Selection Strategy.
- You are only allowed to utilize a key metric or accomplishment once within the overall tailored resume. Be selective and use it where it makes the most impact.
- Cover letter generation is in scope (Step 3). Start from `.ai/guardrails/locked-cover-letter-template.md`, resolve nested tokens from `engineering-log.md` `### Core Strategic Themes & Alignment`, and fill the locked Word template via `fill_cover_letter.py`.
- Perform each step of the workflow in order to completion before proceeding to the next step.
**Step 1 order (both entry modes):** qualification first, then research, then accomplishment selection / skill ranking / bullets.

## Read allowlist

Read the files below. Do **not** read any other path unless this list is updated. Running an allowlisted script is not a Read of that script's tree. `fill_resume.py` may read `.ai/history/architectural-decisions/resume-data-model.json` internally; `fill_cover_letter.py` may read `.ai/history/architectural-decisions/cover-letter-data-model.json` internally; the agent must not.

- `.ai/guardrails/locked-job-history.json`
- `.ai/guardrails/locked-skills.json`
- `.ai/guardrails/locked-professional-summary.json`
- `.ai/guardrails/locked-contact.json`
- `.ai/guardrails/locked-education.json`
- `.ai/guardrails/locked-projects.json`
- `.ai/guardrails/locked-resume-master-template.md`
- `.ai/guardrails/locked-cover-letter-template.md`
- `.ai/guardrails/locked-agent-policies.json` (`resume_tailor_policy_001` execution + research)
- `.cursor/rules/formatting-rules.mdc`
- the current sandbox under `.ai/history/resume-tailor/{company}/{position}/` (including `job-description.md`, `engineering-log.md`, and other artifacts this skill writes)
- queue-invoked only: the given `*-tailor-request.json`

Exist-check only (do not Read or MCP contents): `.ai/guardrails/locked-resume-template.docx`, `.ai/guardrails/locked-cover-letter-template.docx`.

Any path not on this list is forbidden until this skill is updated. Do not write `approved-jobs.json`. Do not delete queue files. Do not write `.ai/guardrails/`. Do not read `{platform}/analyses/{encoded_job_id}-analysis.json`. Do not treat `job-id.txt` as a sidecar pointer.

## SKILL Safety Override Exceptions

When this skill is active, run the commands below **without** Yes/No confirmation. Anything else still requires Safety Override approval. **May run; must not modify** — never Write, StrReplace, Delete, or otherwise edit these script paths or their trees.

### Scripts (run only)

- `python scripts/resume-docx/fill_resume.py --sandbox .ai/history/resume-tailor/{company}/{position}`
- `python scripts/cover-letter-docx/fill_cover_letter.py --sandbox .ai/history/resume-tailor/{company}/{position}`
- `python .github/scripts/resume-tailor/upsert_job_description.py --sandbox .ai/history/resume-tailor/{company_slug}/{position_slug} --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json --job-id {id}` (queue-invoked only)
- `python .github/scripts/resume-tailor/upsert_engineering_log.py --sandbox .ai/history/resume-tailor/{company_slug}/{position_slug} --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json --job-id {id}` (queue-invoked only)

### Delete (resume-tailor sandbox artifacts only)

Delete **without** prompting only when the resolved path is inside `.ai/history/resume-tailor/{company}/{position}/` (or the copied `sandbox_path`). Never auto-delete `job-description.md` or `job-id.txt`. Queue-invoked reuse path may delete:

- `engineering-log.md`
- `tailored-resume.md`
- `John_Doe_Resume_*.docx`
- `tailored-cover-letter.md`
- `John_Doe_Cover_Letter_*.docx`
- `tailored-outreach.md`

### Git / gh (mutating / workflow only)

- `git checkout main`
- `git fetch`
- `git checkout {feature_branch}` (queue-invoked reuse path when that branch exists locally or on `origin`)
- `git checkout -b feature/{company_slug}-{position_slug}` (queue-invoked from-scratch path only)
- `git branch -d` (or equivalent delete) of a leftover merged `feature/{company}-{position}` when the skill directs on the **from-scratch** path, and of an unused local feature branch created in queue step 4 when `upsert_job_description.py` exits non-zero; never force-push `main`
- `git add` — resume-tailor sandbox `{company}/{position}/` only
- `git commit` — message `feat(resume-tailor): {Company Name} - {Role Title}`
- `git push` — current feature branch to `origin` only
- `gh pr list` / `gh pr view` — to detect an existing PR for the feature branch
- `gh pr create` — targeting `main` per Step 6 only when no open PR exists for that branch

### Do not modify

- `scripts/resume-docx/**`
- `scripts/cover-letter-docx/**`
- `.github/scripts/**`

## Entry modes

**Entry-mode gate:** Choose exactly one path from invoke context.

- If a `*-tailor-request.json` is in context → **queue-invoked**. This wins even if `job-description.md` is also present.
- Else if a sandbox `.ai/history/resume-tailor/{company}/{position}/job-description.md` is in context → **legacy manual**.
- Else → **fail-closed**. Report that neither a queue filename nor `job-description.md` was provided. Do not proceed.

### Manual path
Existing Branch Alignment Check below. User is already on the matching `feature/` branch. Require `job-description.md` before Steps 1–6. Do not read job-search or tailor-queue files. Do **not** run `upsert_job_description.py`. Do **not** run `upsert_engineering_log.py`. Human-written JD stays. Agent writes the **full** `engineering-log.md` against locked evidence (same rules as job-analysis: named tech as requirements, mandatory vs preferred, no hallucinated jobs/skills/metrics). Do **not** write an analysis sidecar. Do **not** upsert `approved-jobs.json`. Manual tailor still produces the resume.

### Queue-invoked path (ADR-028 / ADR-045)
Process **every row** in the given `*-tailor-request.json` (1b analysis grain). Lookup `resume_tailor_policy_001` in `.ai/guardrails/locked-agent-policies.json` (**execution + research**; fan-out stays serial). Qualification SoT is the given queue row: `decision`, `justification`, `unmet_mandatory`, `mentioned_skills` (already minted from the sidecar by `generate-tailor-queue.py`). Do not read `jobs.json` or analysis sidecars. Do not write `approved-jobs.json`. Do not delete the queue file. Do not open the next queue file.

Per job, in array order:

1. Confirm checkout is `main` before starting the job.
2. **Reuse vs from-scratch preflight:** read this row's `feature_branch` (and `sandbox_path` if present).
   - **Reuse:** `feature_branch` is a non-empty string. `git fetch`. If that branch exists locally or on `origin`, check it out. `sandbox_path` (copied) and `feature_branch` (copied) **win** over minted `company_slug` / `position_slug`. Delete only generated sandbox artifacts: `engineering-log.md`, `tailored-resume.md`, `John_Doe_Resume_*.docx`, `tailored-cover-letter.md`, `John_Doe_Cover_Letter_*.docx`, `tailored-outreach.md`. Keep `job-description.md` and `job-id.txt`. Skip `git checkout -b`. Then set this queue row `started_at` to UTC now Z and continue from step 6 (upsert engineering log) unless `job-description.md` is missing — then run step 5 upsert JD first.
   - **Missing branch:** `feature_branch` is populated but the branch is gone after fetch → fall back to from-scratch using minted `company_slug` / `position_slug`.
   - **From-scratch:** `feature_branch` is null or empty. `sandbox_path = .ai/history/resume-tailor/{company_slug}/{position_slug}/` and `feature_branch = feature/{company_slug}-{position_slug}` from the queue row `company_slug` and `position_slug` (required on minted rows). Do not re-kebab `company` or `title`.
3. **P2-X1:** if the sandbox exists and `job-id.txt` contains a **different** `id` → mark this queue row `failed` with `failure.code: collision` (plus `message`, `failed_at` UTC Z, `step: p2-x1`); increment `attempt_count` (`null` → 0, then +1); keep `started_at` if already written; stay on `main`; continue remaining rows. Same `id` (or no `job-id.txt`) is overwrite, not a collision. Leave the existing PR untouched.
4. **From-scratch branch create only:** if a leftover merged `feature/{company_slug}-{position_slug}` branch exists, delete it first. Never force-push `main`. Then `git checkout -b {feature_branch}` from `main`. Then set this queue row `started_at` to UTC now Z.
5. **From-scratch (and reuse when JD is missing):** **Run** (do not edit) `python .github/scripts/resume-tailor/upsert_job_description.py --sandbox .ai/history/resume-tailor/{company_slug}/{position_slug} --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json --job-id {id}` (reuse path: pass the copied `sandbox_path` instead of minted slugs). The script creates the sandbox, writes **P2-J1** `job-description.md` and `job-id.txt` from the **queue row payload only**. Do not Write/MCP the JD. Do not create `_write_*.py` (or similar) in the sandbox. Do not dump JDs under `queue/`. The script must emit this shape:

```markdown
# {company} - {title}

- **Location:** {location}
- **URL:** {url}

## Job description

{description_text}

## Analysis summary

- **Decision:** {decision}
- **Justification:** {justification}

## Unmet mandatory requirements

- {normalized}: {note}

## Mentioned Skills

- **{normalized}** (`{importance}`, `{result}`): {note}
```

Empty `unmet_mandatory` and empty `mentioned_skills` each render as a single `- None`. Unmet mandatory: one unbolded `- {normalized}: {note}` per item. Mentioned Skills: one bullet per `mentioned_skills[]` row (colon always present, even if note is empty). Do **not** open `{platform}/analyses/{encoded_job_id}-analysis.json`. If the script exits non-zero: `git checkout main`, delete the unused local feature branch created in from-scratch step 4, mark this queue row `failed` (`failure.code: collision` and `step: p2-x1` when stderr contains `ERROR: job-id.txt mismatch`; otherwise `failure.code: tailor_preflight` and `step: p2-j1` for any other `ERROR:`), keep `started_at`, set `attempt_count` to `(null→0)+1`, leave `completed_at` / `pr_*` as they were, continue remaining rows. Do not invent a helper fallback.
6. After preflight, **run** (do not edit) `python .github/scripts/resume-tailor/upsert_engineering_log.py --sandbox {sandbox_path} --queue-file .ai/history/resume-tailor/queue/{run_id}-tailor-request.json --job-id {id}` (`sandbox_path` is the copied path on reuse, otherwise minted slugs). The script upserts `engineering-log.md` sections 1–3 from the queue row, including `### Core Strategic Themes & Alignment` from `core_themes` when present, and leaves placeholders for Additional Company/Role Expectations, Compensation Target, and section 4. Do not re-derive qualification prose the script already wrote.
7. Then research, then remaining Steps 1–6 in this sandbox (section 4 is still agent-written; engineering-log gaps for skills not in `locked-skills.json`). Stage **only** the sandbox directory for this job.
8. `git checkout main`. **Then** set that queue row:
   - **Success:** `status: tailor_complete`; `attempt_count` = `(null→0)+1`; `completed_at` UTC now Z; `pr_url` / `pr_number` / `sandbox_path` / `feature_branch` from this run (reuse keeps the same values when the open PR is reused).
   - **Failure:** keep `started_at`; `attempt_count` = `(null→0)+1`; leave `completed_at` / `pr_*` as they were; `failed` + `failure` (**P2-E1** `code`: `collision` | `tailor_preflight` | `tailor_skill` | `validate` | `git` | `pr_create` | `unknown`).
   Then the next job.

After the file: report **filename + per-job status**. **Stop.**

## Execution Sequence
### Pre-Flight Validation Check & Dependencies
<!--
**Identity Check** Confirm your author identity is set. If it is not, run the following commands to set your Agent identity.
```bash
git config user.name "Resume Agent"
git config user.email "resume-agent@internal.ai"
git config --list
```
-->
**Required Inputs Check:** Apply the Entry-mode gate first. Missing both a `*-tailor-request.json` and a sandbox `job-description.md` in context → **fail-closed**; abort and report that neither trigger was provided. Queue filename in context selects queue-invoked even when `job-description.md` is also present. Then verify the following files exist: `.ai/guardrails/locked-job-history.json`, `.ai/guardrails/locked-skills.json`, `.ai/guardrails/locked-professional-summary.json`, `.ai/guardrails/locked-contact.json`, `.ai/guardrails/locked-education.json`, `.ai/guardrails/locked-projects.json`, `.ai/guardrails/locked-resume-master-template.md`, `.ai/guardrails/locked-cover-letter-template.md`, `.ai/guardrails/locked-agent-policies.json`, `.ai/guardrails/locked-resume-template.docx`, `.ai/guardrails/locked-cover-letter-template.docx`. Do **not** Read or MCP `locked-resume-template.docx` or `locked-cover-letter-template.docx`; `fill_resume.py` and `fill_cover_letter.py` are the only readers. Manual path also requires `.ai/history/resume-tailor/<company>/<position>/job-description.md`. Queue-invoked from-scratch runs `upsert_job_description.py` to mint that JD (P2-J1) after branch create. Queue-invoked reuse keeps `job-description.md` / `job-id.txt` and skips that script unless the JD is missing. Do not run it on the manual path. Do not require `.ai/guardrails/locked-job-search-criteria.json`.
- *Conflict Action:* If the entry-mode gate fails or any of these files are missing, abort the workflow and report the exact missing trigger or path.

**Branch Alignment Check (manual path, ADR-006 / ADR-011):** Before any file modifications on the manual path, verify the active Git branch aligns with the resume-tailor sandbox directory path. Branch identity is derived **only from the two parent folders** of `job-description.md` (not from JD free text or engineering-log). Queue-invoked from-scratch creates the branch first (ADR-028) and skips this check until after `git checkout -b`. Queue-invoked reuse checks out the copied `feature_branch` and aligns to the copied `sandbox_path`.
1. Resolve the resume-tailor sandbox path from the trigger file (e.g., `.ai/history/resume-tailor/volkswagen-group/solution-architect/job-description.md` → company folder `volkswagen-group`, position folder `solution-architect`).
2. Read `{company-folder}` and `{position-folder}` as the two path segments under `.ai/history/resume-tailor/` (already kebab-case).
3. Derive the expected branch name: `feature/{company-folder}-{position-folder}`.
4. Read the current Git branch (`git branch --show-current` or equivalent).
5. Validate:
   - Current branch **equals** the expected branch name exactly.
   - Current branch is **not** `main`.
   - Current branch matches the `feature/` prefix convention.
- *Conflict Action:* If the current branch is `main`, does not match the expected branch, or Git is unavailable, abort the workflow immediately. Report the expected branch name, the actual branch name, and the resume-tailor directory path. Do not proceed with Steps 1–6 until the user checks out the correct feature branch.

**Branch-to-Directory Mapping Reference:**
- One feature branch maps to one nested resume-tailor sandbox directory (ADR-011). Both folder segments and the branch use kebab-case slugs.
- Manual path: branch `feature/volkswagen-group-solution-architect` ↔ directory `.ai/history/resume-tailor/volkswagen-group/solution-architect/` (parent folders of `job-description.md`; no `source_job_id` suffix).
- Queue-invoked from-scratch (ADR-045): branch `feature/{company_slug}-{position_slug}` ↔ `.ai/history/resume-tailor/{company_slug}/{position_slug}/` from the queue row. `position_slug` always includes the `source_job_id` suffix.
- Queue-invoked reuse: when `feature_branch` / `sandbox_path` are populated, those copied values win over minted slugs. Checkout the copied branch; write in the copied sandbox.

### Step 1: Create the engineering log `engineering-log.md` and document your thoughts
Once all the sections in step 1 are complete, do not continue to update `engineering-log.md`.

**Queue-invoked:** after preflight, run `upsert_engineering_log.py` (do not edit the script). Then fill only the research placeholders and section 4 as directed below. Do not overwrite sections 1–3 qualification prose or `### Core Strategic Themes & Alignment` the script wrote from the queue row.

**Manual:** do not run the upsert script. Create or overwrite `engineering-log.md` in the company specific working directory with the full schema below, written against locked evidence.

```markdown
# Engineering Log: [Company Name] - [Role Title]
Timestamp: {{CURRENT_TIMESTAMP}}

## 1. Job Description Architecture Mapping
- **Key Themes Identified:** Analyze the core themes of the target JD.
- **Experience Requirements** List the experience requirements (typically in years).
- **Hard Technical Requirements:** List out the explicit tech stacks, skills requested. Treat every skill listed in job description as a requirement.
- **Additional Company/Role Expectations Identified:** Search the web and analyze publicly available information on the company and look for any additional themes not mentioned in the target JD. Things that the company would look for in an ideal candidate.
- **Compensation Target:** List the expected salary range in the target JD. Search the web and find a competitive salary expectation for location New York City Area / New Jersey specifically.

## 2. Gap Analysis & Guardrail Compliance
- **Experience Requirement Gap Analysis** Verify the experience requirement in the target JD and analyze it against `.ai/guardrails/locked-job-history.json`. Calculate years and industry tenure as unique qualifying calendar months. Exclude employment gaps. Do not double-count overlapping months. Do not use `locked-projects.json` for tenure or years of experience. Default printed N=5. Select the smallest N ∈ 6..10 only when the added prefix closes a JD required or preferred gap not covered by 1..5: years, industry tenure, or a unique locked skill/accomplishment. Determine if sufficient experience exists and document your analysis (how are you determining that there is or isn't sufficient experience).
- **Technical Requirements Gap Analysis:** Verify the hard technical requirements in the target JD and analyze it against `.ai/guardrails/locked-skills.json` Selected Skills and All Skills sections. Prefer matching target JD to Selected Skills unless there is no clear matching skill and you must use All Skills. If there is no matching skill listed in either section make note of it. On the queue-invoked path, walk `## Mentioned Skills` / `mentioned_skills`: log `not_evidenced` / `contradicted` / locked-skills misses here; do not invent skills. Positioning headline and professional summary come from `.ai/guardrails/locked-professional-summary.json`, not from skills.
- **Accomplishment Selection Strategy:** Analyze the target industry & JD, find and select supporting accomplishments per role in `locked-job-history.json` that helps fulfill the target JD requirements. The exact wording of the accomplishment is able to be modified. Do not modify the exact metric, just the wording around it if needed. When N>5, record `selected_N` and each required or preferred item covered by roles 6..N. Never invent accomplishments, metrics, skills, or placeholder numbers. Qualitative locked outcomes are allowed when no number exists. **Page-fill assessment (N>5 only, ADR-051):** after Step 2c, record the last-page fill % reported by the filler, the gap-closing locked evidence considered, and each add/keep decision — or, if the page stays under the ~75% target, why no further gap-closing evidence remained. Omit this note for `N<=5`.
- **Deconfliction Strategy:** All information found in `.ai/guardrails/locked-resume-master-template.md` is considered source of truth and overrides any conflicting facts, dates, skills or accomplishments found in `.ai/guardrails/locked-job-history.json` or `.ai/guardrails/locked-skills.json`.

## 3. Skill Selection & Ranking
**Skill Selection** Produce a list of mapped skills tailored to the job description. Selected skills are mapped to the corresponding list here
**Skill Ranking** Analyze all skills and rerank them in order of importance tailored to the job description. Most relevant on top.
### Selected Skills

### All Skills

## 4. Core Modifications Detail
- Use the following format for each position. 
- Accomplishments should be selected in support of selected skills which are mapped according to the job description.
- Use `locked-resume-master-template.md` as a minimum starting point and pull additional supporting evidence from `locked-job-history.json`.
- If an accomplishment in `locked-job-history.json` better fits the job description, use `locked-job-history.json` over `locked-resume-master-template.md` for generating specific bullet points.
- 1-5 bullet points per included role. Target 3 when at least 3 locked accomplishments exist; otherwise use the available locked evidence without padding. When `N>5` (accordion), you **may** use up to 5 bullets on a printed role when the extra bullet is gap-closing locked evidence that also improves last-page fill (ADR-051, Step 2c); this is still gap-only, never padding. Never invent accomplishments or metrics. Every bullet is `Theme: Action verb + technical scope + locked result`. Keep or rewrite the theme per JD so it matches the bullet and a relevant requirement/skill. Do not put a tool/skill name in the theme unless it exists in `locked-skills.json`. Use a locked quantitative result when available and a qualitative locked outcome otherwise. `spearheaded` is allowed only when that word supports the matching locked evidence. Older roles stay condensed. The Experience column may grow past one page; there is no hard two-page limit or CI gate. When `N>5`, run the advisory last-page fill re-evaluation in Step 2c.
### Position Name / Title

#### Existing Bullet point
- Insert the exact existing bullet point from `locked-resume-master-template.md`

#### New Bullet point
- Insert the new tailored bullet point

#### Justification / notes
- **Overall** Avoid filler words and be direct whenever possible while still maintaining clean, professional style.
- **Overall** Avoid repeated use of the same words or phrases. Limit the usage to once or twice maximum through the entirety of the finalized text
- **For each role** Explain why you added, removed, altered or kept specific bullets. It is ok to keep existing bullets as they are if you determine no changes are needed. Do not make changes to the existing bullets if it is not adding value in any way.
- **For each role** Explain the alignment strategy for for each bullet to the target JD as well as the overall career and skill progression over time.
- **For each role** Tweak bullet points *only* to highlight relevant architectural patterns, key accomplishments, key responsibilities, major contributions, or anything matching the JD, ensuring locked skills remain prominent.
- **For each role** Be clear, concise and do not overexplain. Ideally, start with the what, then follow up with major contribution illustrating business value add.
```

**Then research (both entry modes):** Lookup `resume_tailor_policy_001` **execution + research**. Fill the script placeholders (queue-invoked) or the manual section 1 research bullets: company/role WebSearch and NYC/NJ compensation WebSearch/WebFetch. Honor `research`: `0`/`null` skip that tool and still write the headings (note skipped-per-policy); omitted/negative **halt** the tailor job; first-ship caps are **5** searches and **3** fetches per job. Research is audit-only in `engineering-log.md`. It must not invent locked skills, jobs, or metrics, and must not change the queue row `decision`.

**Then remaining work:** accomplishment selection / section 4 (queue-invoked section 4 is still agent-written), then Steps 2–6.

### Step 2: Generate and tailor the resume `tailored-resume.md`
- Once the engineering-log.md is populated and complete, create or overwrite `tailored-resume.md` in the same directory.
- Parse `.ai/guardrails/locked-resume-master-template.md` and emit consecutive roles `1..N` only (default 5, max 10). Do not print keys 11–12.
- Generate custom tailored bullet points for each printed role from `engineering-log.md`. Preserve a concise executive / enterprise-architecture emphasis, no-fluff tone, contextual use of evidenced technologies, and telescoping treatment of older roles. Keep 1–5 bullets per printed role (target 3); when `N>5`, up to 5 is allowed only for gap-closing locked evidence that also improves last-page fill (Step 2c / ADR-051).
- Generate a new list of skills from `engineering-log.md`. Re-rank the skills in order of importance. Prefer `JOB_SKILL_1..3` from `### Core Strategic Themes & Alignment` when those names exist in `.ai/guardrails/locked-skills.json`. A skill or platform may appear only when it exists in `.ai/guardrails/locked-skills.json` and its queue evidence is `met` or the supported slice of `partial`. Log unsupported JD terms as gaps. Do not invent or placeholder metrics. Do not mirror unsupported JD technologies. Do not include 3–5 alternative bullets in final artifacts. Do not use `spearheaded` unless that word supports the matching locked evidence.
- **CRITICAL CONSTRAINT**: Whenever possible, use locked platform names (e.g. SAP S/4HANA) in place of generic platform terminology. Mention a platform only when it exists in `locked-skills.json` and is `met` or the supported slice of `partial`.
- **CRITICAL CONSTRAINT**: Do not hallucinate, invent or modify companies, modify job titles, shift dates or change employment chronology. Printed role headers must equal the consecutive master-template prefix `1..N`.
- **CRITICAL CONSTRAINT**: You are strictly FORBIDDEN from creating, hallucinating, or modifying the core metrics of accomplishment. You may ONLY select relevant bullets from the matching role pool in `engineering-log.md`. Integrate the bullets seamlessly under their respective roles. You may alter the sentence structure or change text as necessary to fit the job description and formatting standards. You can only utilize a key metric or accomplishment once. Every printed bullet needs a non-empty `Theme:` before the first colon. Direct action starters. Technical context. Locked quantitative result when available; qualitative locked outcome otherwise.
- **Formatting & Deconfliction Strategy** Apply formatting standards from `.cursor/rules/formatting-rules.mdc`. These rules should be applied in addition to the formatting in `.ai/guardrails/locked-resume-master-template.md`. Word fill bolds the theme through the first colon (colon included).

### Step 2b: Fill the sandbox Word resume
- After `tailored-resume.md` is written, run `python scripts/resume-docx/fill_resume.py --sandbox .ai/history/resume-tailor/{company}/{position}`.
- The filler gathers locked section objects internally and writes `John_Doe_Resume_{Company_Title_Case}.docx` in the sandbox. Do not Read `.ai/history/architectural-decisions/resume-data-model.json`.
- `{{PROFESSIONAL_SUMMARY_SUMMARY}}` comes from `locked-professional-summary.json` only. `{{CONTACT_LINKS_1_URL}}` comes from `contact.links[0].url` in `locked-contact.json`. Do not read `locked-job-search-criteria.json`.
- `{{PROJECTS_1_TITLE}}` and `{{PROJECTS_1_SUMMERY}}` bind from `locked-projects.json` key `"1"` (ADR-052). Do not add a `## Projects` section to `tailored-resume.md`. Do not rewrite project title/summary. When both fields are null the filler removes the entire Projects block.
- The filler prints an advisory line after `wrote {dest}`, e.g. `last page ~42% full across 3 page(s) (target >=75% usable)` (ADR-051). This is informational only; it never fails the fill. Use it in Step 2c.
- Never write `.ai/guardrails/` during a normal resume-tailor run. Abort if the filler exits non-zero.

### Step 2c: Accordion last-page fill re-evaluation (N>5 only, ADR-051)
Gate: run this step **only** when the printed prefix was deepened past the default five (`N>5`). If `N<=5`, skip this step entirely — default resumes are untouched and this is a no-op.

The estimator is **advisory, never a gate**: it never edits the docx and never blocks the run. The remedy is **gap-only** — every addition must be locked evidence that closes a JD required/preferred gap and adds thematic relevance. **Never pad.** No invented jobs, skills, or metrics.

Loop-until, using the printed fill % from Step 2b:
1. If the last-page fill is **>=~75%** (or already **>=~65%** and no gap-closing locked evidence remains), stop — the page is adequately filled. Log the assessment (below) and continue to Step 3.
2. While `N>5` **and** last-page fill `< ~65%` **and** gap-closing locked evidence remains:
   a. First add a **relevant additional bullet to an already-printed role** — a locked accomplishment that closes a JD required/preferred gap; the role must stay within the **1–5 bullet** max.
   b. If no such bullet remains, **extend `N` by the next consecutive master role** (ADR-049 prefix rule) **only if** that role adds gap-closing evidence. Do not skip, reorder, or print keys 11–12. Bounded by max 10 roles.
   c. Regenerate `tailored-resume.md`, re-run `fill_resume.py` (Step 2b), and re-read the printed fill %.
3. If gap-closing evidence is exhausted while still under target, **ship as-is** and log why the page stays under target. Underfill under the gap-only rule is legitimate.

Naturally bounded by max 10 roles and max 5 bullets/role. Record the page-fill assessment in `engineering-log.md` section 2 (see below) before Step 3.

### Step 3: Generate and fill the cover letter
- Ingest `.ai/guardrails/locked-cover-letter-template.md` as the immutable starting prose.
- Resolve nested tokens (`JOB_SKILL_1..3`, `STRENGTH_1..3`, `OPENING_HOOK`, `COMPANY_NAME`, `JOB_TITLE`, `JOB_ID`, `RECIPIENT_NAME`, `CURRENT_DATE`, contact slots) from `engineering-log.md` `### Core Strategic Themes & Alignment`, locked contact, and the sandbox JD. Do not invent skills or metrics. `job_skill_*` values must exist in `locked-skills.json`.
- Write `tailored-cover-letter.md` in the sandbox using the master heading/metadata/section schema (`## Opener`, `## Body 1`, `## Body 2`, `## Call to Action`, `## Closing`). Nested `{{` tokens must be gone before fill.
- Run `python scripts/cover-letter-docx/fill_cover_letter.py --sandbox .ai/history/resume-tailor/{company}/{position}`.
- The filler writes `John_Doe_Cover_Letter_{Company_Title_Case}.docx`. Do not Read `.ai/history/architectural-decisions/cover-letter-data-model.json`. Do not Read or MCP the locked Word template.
- Abort if the filler exits non-zero.

### Step 4: Generate Messaging Assets
- Create `tailored-outreach.md` in the same resume-tailor sandbox directory
- If the JD was sent via LinkedIn, a crisp, scannable InMail message block tailored specifically to the recruiter or hiring manager for this role.
- If the JD was sent via email, generate a response email tailored specifically to the recruiter or hiring manager for this role.
- Include bracketed placeholders [ ] for any variable parameters like target salary or phone number.
- If you are unable to determine if the JD was sent via email or LinkedIn, use email by default.

### Step 5: Completion Confirmation
Once `engineering-log.md`, `tailored-resume.md`, `John_Doe_Resume_*.docx`, `tailored-cover-letter.md`, `John_Doe_Cover_Letter_*.docx`, and `tailored-outreach.md` are successfully written to disk, proceed immediately to Step 6. Do not merge or modify `main`.

### Step 6: Commit, Push, and Open Pull Request
After Step 5 artifacts are verified on disk, commit resume-tailor artifacts, push to `origin` and open pull request for review.

**Pre-Flight Checks (Step 6):**
- Re-confirm Steps 1–5 output files exist in the resume-tailor sandbox directory: `job-description.md`, `engineering-log.md`, `tailored-resume.md`, `John_Doe_Resume_*.docx`, `tailored-cover-letter.md`, `John_Doe_Cover_Letter_*.docx`, and `tailored-outreach.md`.
- Re-confirm branch alignment per the Pre-Flight Branch Alignment Check (current branch must still match this sandbox's feature branch: copied `feature_branch` on reuse, otherwise `feature/{company-folder}-{position-folder}`).
- Confirm `gh` CLI is available and authenticated (`gh auth status`).
- Confirm the working tree is a git repository with remote `origin` configured.

**Execution Sequence:**
1. Stage **only** files within the resume-tailor sandbox directory (`.ai/history/resume-tailor/{company}/{position}/`). Do not stage changes outside this path.
2. Commit with message: `feat(resume-tailor): {Company Name} - {Role Title}` (human-readable company and role from the job description).
3. Push the current feature branch to `origin`.
4. **PR reuse (queue-invoked):** `gh pr list` / `gh pr view` for this feature branch targeting `main`.
   - If an **open** PR already exists: do **not** run `gh pr create`. Keep that `pr_url` / `pr_number`.
   - If the PR is **merged or closed**, or none exists: open a pull request targeting `main` via `gh pr create` and overwrite `pr_url` / `pr_number` with:
     - **Title:** `Resume Tailor: {Company Name} - {Role Title}`
     - **Body:** Summary of structural alignment changes from Step 5, list of files produced, and a note that the PR awaits human review per ADR-006.
   Manual path (no queue): always `gh pr create` as today.
5. **Do not merge.** Await human PR approval. GitHub Actions will assign the repository owner as reviewer, apply the `ready-for-review` label, and run CI validation checks.

**Conflict Action:** If any pre-flight check fails, abort Step 6 and report the exact failure. Do not push or open a PR with incomplete artifacts.

**Step 6 Completion Confirmation:** Reply in the main chat window with a short summary of structural alignment changes, the branch name, and the PR URL. Confirm the PR is open and awaiting human review.
