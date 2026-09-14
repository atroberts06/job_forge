# Installation and Setup

macOS and Windows bootstrap from clone to local validation. Day-to-day operations live in [README.md](README.md). Use the bash blocks on macOS (or Git Bash). Use the PowerShell blocks on Windows.

---

## Prerequisites

Install these before cloning:

| Tool | Purpose | Verify |
| --- | --- | --- |
| Git | Clone, hooks, PRs | `git --version` |
| Python matching [`.python-version`](.python-version) | Repo runtime (currently 3.14) | `python --version` or `python3 --version` |
| bash | macOS Terminal or Git Bash; POSIX hook | `bash --version` |
| PowerShell | Windows hook wrapper and copies | `$PSVersionTable.PSVersion` |
| Cursor | Skills, rules, Office MCP | Open the repo as a workspace |
| GitHub CLI (`gh`) | Auth and resume-tailor PRs | `gh --version` |

If `python --version` (or `python3 --version` on macOS before the venv) does not match `.python-version`, install that interpreter and place it first on `PATH`. After the venv is active, use `python`.

---

## 1. Clone and virtual environment

macOS / Git Bash:

```bash
git clone https://github.com/atroberts06/job_forge.git
cd job_forge
python3 -m venv .venv
source .venv/bin/activate
python --version
```

Windows PowerShell:

```powershell
git clone https://github.com/atroberts06/job_forge.git
Set-Location job_forge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

`.venv/` is gitignored. Activate it in every new terminal before running project Python.

---

## 2. Install Python packages

```bash
python -m pip install --upgrade pip
python -m pip install -r scripts/ci/requirements.txt
python -m pip install -r scripts/resume-docx/requirements.txt
python -m pip install -r .github/scripts/job-search/common/requirements.txt
python -m pip install "mcp[cli]==1.29.1" "mcp-server-office==0.2.0"
```

Pin `mcp` to 1.x. Unbounded `pip install mcp-server-office` resolves MCP 2.x and breaks Office tools (`Server.list_tools` missing).

Confirm:

```bash
python -c "from mcp.server.lowlevel import Server; print(hasattr(Server('x'), 'list_tools'))"
```

The print must be `True`.

---

## 3. Git pre-commit hook

Copy the canonical POSIX hook and PowerShell wrapper into `.git/hooks/` (Git does not track this folder).

macOS / Git Bash:

```bash
./scripts/set-up-scripts/install-hooks.sh
```

Windows PowerShell:

```powershell
.\scripts\set-up-scripts\pre-commit-update-script.ps1
```

The hook rebuilds the README directory map on staged add, delete, or rename. Those installers copy `scripts/set-up-scripts/pre-commit` and `scripts/set-up-scripts/pre-commit.ps1`. Do not paste a second copy of the hook body.

If Windows PowerShell blocks the thin wrapper:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

---

## 4. GitHub CLI

```bash
gh auth login
gh auth status
```

Resume-tailor Step 5 requires an authenticated `gh` against `origin`.

---

## 5. Cursor Office MCP

Office MCP reads `locked-resume-template.docx`. Do not hardcode a user or global Python path.

1. Complete steps 1–2 so the venv Office binary exists (`mcp-server-office` on macOS, `mcp-server-office.exe` on Windows).
2. In Cursor: **Settings → MCP → Add new MCP server**.
3. Command (repository-relative from the workspace root):

macOS:

```text
.venv/bin/mcp-server-office
```

Windows:

```text
.venv\Scripts\mcp-server-office.exe
```

4. Reload the window: **Developer: Reload Window** (`Cmd+Shift+P` on macOS, `Ctrl+Shift+P` on Windows).
5. Confirm the Office tools appear (`read_docx`).

If tools fail with `list_tools`, reinstall the pinned MCP pair from step 2 inside `.venv`.

---

## 6. Locked identity files (human only)

Agents do not write [`.ai/guardrails/`](.ai/guardrails/) on a normal run. Fill instance files with real facts. Do not invent jobs, titles, dates, skills, or metrics.

Join contract: [`.ai/history/architectural-decisions/resume-data-model.json`](.ai/history/architectural-decisions/resume-data-model.json).

### Do not rewrite as identity

- `locked-job-data-model.json`
- `locked-job-search-data-model.json`
- `locked-agent-policies.json`

`locked-cover-letter-template.md` and `locked-linkedin-profile-template.md` are unused by current skills.

### Fill order

1. **Contact** — [`.ai/guardrails/locked-contact.json`](.ai/guardrails/locked-contact.json)

   Required: `id`, `first_name`, `last_name`, `email`, `phone`, `city`, `state`, `postal_code`, `country`, `links`, `education_id`, `skills_id`, `job_history_id`, `professional_summary_id`, `projects_id`. Optional FKs: `certifications_id`, `clearance_id`, `licenses_id`. Do not nest child objects.

2. **Children** (IDs must match the contact FKs)

   - Education: [`.ai/guardrails/locked-education.json`](.ai/guardrails/locked-education.json) — `id`, `institution`, `location`, `degree`, `end_date`
   - Skills: [`.ai/guardrails/locked-skills.json`](.ai/guardrails/locked-skills.json) — `id`, `selected_skills` (preferred ranking vocabulary), `all_skills` (full locked vocabulary)
   - Summary: [`.ai/guardrails/locked-professional-summary.json`](.ai/guardrails/locked-professional-summary.json) — `id`, `target_focus`, `summary`
   - Job history: [`.ai/guardrails/locked-job-history.json`](.ai/guardrails/locked-job-history.json) — envelope `id` plus digit keys `"1"`, `"2"`, … Each role needs `title`, `company`, `location`, `start_date`, `end_date`. Optional: `focus_narrative`, `mapped_skills`, `accomplishments`. Do not convert digit keys to a JSON array.
   - Projects: [`.ai/guardrails/locked-projects.json`](.ai/guardrails/locked-projects.json) — envelope `id` plus digit keys `"1"`, `"2"`, … Each entry needs `title` and `summary`, both null at deploy or both populated later by a reviewed locked-data change. `contact.projects_id` must equal `projects.id`. The Word template prints only key `"1"` (`{{PROJECTS_1_TITLE}}`, `{{PROJECTS_1_SUMMERY}}` → `summary`). When key `"1"` is unpopulated, `fill_resume.py` removes the entire Projects section.

3. **Master chronology** — [`.ai/guardrails/locked-resume-master-template.md`](.ai/guardrails/locked-resume-master-template.md)

   This markdown wins fact conflicts over job-history JSON. Role `##` headers must stay the locked titles in employment order (skills section last).

4. **Job-search filters** — [`.ai/guardrails/locked-job-search-criteria.json`](.ai/guardrails/locked-job-search-criteria.json)

   Multi-id envelope: `jsc_001` (Greenhouse titles/locations/arrangement/keywords) and `jsc_002` (SerpApi Google Jobs request fields). Puller-only. `fill_resume.py` and job-analysis must not read this file. SerpApi needs GitHub Environment `production` secret `SERPAPI_API_KEY`.

5. **Word layout** — [`.ai/guardrails/locked-resume-template.docx`](.ai/guardrails/locked-resume-template.docx)

   Layout and `{{TOKENS}}` only. Inspect with Office MCP `read_docx`. Token names follow ADR-021 (`{{CONTACT_FIRST_NAME}}`, `{{JOB_HISTORY_1_TITLE}}`, `{{SKILL_01}}`, …) plus the project-1 aliases `{{PROJECTS_1_TITLE}}` / `{{PROJECTS_1_SUMMERY}}` (ADR-052). Do not run `scripts/resume-docx/derive_template.py` as routine setup. That script is a one-time derivation from a sample resume.

6. **Optional envelopes** — [`.ai/guardrails/locked-certifications.json`](.ai/guardrails/locked-certifications.json), [`.ai/guardrails/locked-clearance.json`](.ai/guardrails/locked-clearance.json), [`.ai/guardrails/locked-licenses.json`](.ai/guardrails/locked-licenses.json)

   Envelope `id` required. Digit rows are optional. Empty clearance (`id` only) is valid.

After edits:

```bash
python scripts/ci/validate_guardrails_json.py
```

JSON that parses can still be unusable. Resume-tailor and job-analysis will not invent missing facts.

---

## 7. GitHub repository configuration

Create these on the GitHub repo (owner). They are required for PR merge and Drive deploy.

### Branch protection on `main`

**Settings → Branches → Branch protection rules**

- Pattern: `main`
- Require a pull request before merging
- Require approval from the repository owner
- Require status check: `validate` (job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml))
- Restrict force pushes and branch deletion

### Environment `production`

**Settings → Environments → New environment**

- Name: `production`
- Required reviewers: repository owner
- Deployment branches: `main` only
- Secrets:

| Secret | Purpose |
| --- | --- |
| `GDRIVE_CLIENT_ID` | OAuth client ID (Desktop app) |
| `GDRIVE_CLIENT_SECRET` | OAuth client secret |
| `GDRIVE_REFRESH_TOKEN` | User refresh token for Drive uploads |
| `GDRIVE_FOLDER_ID` | Root Drive folder ID |

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on PRs to `main`. [`.github/workflows/cd-main.yml`](.github/workflows/cd-main.yml) runs on **push to `main` after merge**. It uploads `John_Doe_Resume_*.docx`, `John_Doe_Cover_Letter_*.docx`, `tailored-resume.md`, `engineering-log.md`, and `tailored-outreach.md` under `{company}/{role}/` inside `GDRIVE_FOLDER_ID`. `job-description.md` and `tailored-cover-letter.md` stay in git.

---

## 8. Google Drive OAuth

CD uses a user OAuth refresh token (DEF-001), not a service account.

1. Create a GCP project and enable the **Google Drive API**.
2. Configure the OAuth consent screen. Add yourself as a test user if the app is in Testing.
3. Add scope `https://www.googleapis.com/auth/drive.file` (matches `scripts/ci/sync_gdrive.py` and `scripts/ci/obtain_gdrive_oauth_token.py`).
4. Create an OAuth client ID of type **Desktop app**. Copy client ID and secret.
5. Locally, with `.venv` active:

macOS / Git Bash:

```bash
export GDRIVE_CLIENT_ID="<client-id>"
export GDRIVE_CLIENT_SECRET="<client-secret>"
python scripts/ci/obtain_gdrive_oauth_token.py
```

Windows PowerShell:

```powershell
$env:GDRIVE_CLIENT_ID = "<client-id>"
$env:GDRIVE_CLIENT_SECRET = "<client-secret>"
python scripts/ci/obtain_gdrive_oauth_token.py
```

6. Create or choose a Drive folder. Copy the folder ID from the URL.
7. Store `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`, and `GDRIVE_FOLDER_ID` on the `production` environment.
8. Optional token smoke test:

macOS / Git Bash:

```bash
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "refresh_token=YOUR_REFRESH_TOKEN" \
  -d "grant_type=refresh_token"
```

```bash
curl -s "https://www.googleapis.com/drive/v3/files?pageSize=5" \
  -H "Authorization: Bearer YOUR_NEW_ACCESS_TOKEN"
```

Windows PowerShell:

```powershell
$body = @{
    client_id     = "YOUR_CLIENT_ID"
    client_secret = "YOUR_CLIENT_SECRET"
    refresh_token = "YOUR_REFRESH_TOKEN"
    grant_type    = "refresh_token"
}
$response = Invoke-RestMethod -Uri "https://oauth2.googleapis.com/token" -Method Post -Body $body
$response.access_token
```

```powershell
$token = "YOUR_NEW_ACCESS_TOKEN"
Invoke-RestMethod -Uri "https://www.googleapis.com/drive/v3/files?pageSize=5" -Headers @{ Authorization = "Bearer $token" }
```

9. After a successful test, publish the OAuth app to Production on the consent screen.
10. Do not commit client secrets or refresh tokens.

### Token rotation

If deploys fail with `invalid_grant` or revoked credentials:

1. Revoke the app under Google Account → Security → Third-party access if needed.
2. Re-run `python scripts/ci/obtain_gdrive_oauth_token.py`.
3. Update `GDRIVE_REFRESH_TOKEN` (and client values if rotated) on `production`.
4. Re-run the CD deploy job.

---

## 9. Setup complete

Local validation (no PR or Drive upload):

```bash
python scripts/ci/validate_guardrails_json.py
python -m pytest .github/scripts/job-search -q
python -m pytest .github/scripts/resume-tailor/tests -q
python -m pytest scripts/resume-docx/tests -q
python -m pytest scripts/ci/tests -q
```

Each command must pass. Run the pytest suites separately so each `conftest.py` loads in isolation. Operator workflows are in [README.md](README.md).
