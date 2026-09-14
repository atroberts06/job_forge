"""Shared helpers for CI/CD validation and build scripts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from html import unescape
from pathlib import Path

RESUME_TAILOR_ROOT = Path(".ai/history/resume-tailor")
# Sibling of {company}/{position}/ sandboxes (ADR-028). Not a tailor sandbox.
RESERVED_RESUME_TAILOR_DIRS = frozenset({"queue"})
MASTER_RESUME = Path(".ai/guardrails/locked-resume-master-template.md")
JOB_HISTORY = Path(".ai/guardrails/locked-job-history.json")
MIN_PRINTED_ROLES = 5
MAX_PRINTED_ROLES = 10
EXCLUDED_JOB_KEYS = ("11", "12")
REQUIRED_RESUME_TAILOR_FILES = (
    "job-description.md",
    "engineering-log.md",
    "tailored-resume.md",
    "tailored-cover-letter.md",
    "tailored-outreach.md",
)
SANDBOX_DOCX_GLOB = "John_Doe_Resume_*.docx"
SANDBOX_COVER_LETTER_DOCX_GLOB = "John_Doe_Cover_Letter_*.docx"
PLACEHOLDER_TOKEN = "{{"
SKILLS_HEADER = "## Skills"
_DOCX_XML_PREFIXES = ("word/", "customxml/")


def repo_root() -> Path:
    return Path.cwd()


def kebab_case(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def source_job_id_suffix(source_job_id: str) -> str:
    """Last 10 characters of source_job_id when longer than 10; otherwise the full value.

    Queue-invoked position slugs use this token (ADR-045). Never Workday R*.
    """
    value = str(source_job_id or "").strip()
    if not value:
        raise ValueError("source_job_id is required")
    return value[-10:] if len(value) > 10 else value


def tailor_queue_slugs(company: str, title: str, source_job_id: str) -> tuple[str, str]:
    """Always-suffix queue identity: kebab(company), kebab(title)-{source_job_id suffix}."""
    company_slug = kebab_case(company)
    title_slug = kebab_case(title)
    if not company_slug:
        raise ValueError("company slug is empty")
    if not title_slug:
        raise ValueError("title slug is empty")
    return company_slug, f"{title_slug}-{source_job_id_suffix(source_job_id)}"


def unresolved_docx_placeholders(docx_path: Path) -> list[str]:
    """Return OOXML part names whose visible text still contains '{{'.

    Inspects XML under word/ and customXml/ after stripping tags. Embedded
    fonts and other binary parts are ignored; they can contain the two-byte
    sequence '{{' without any template placeholder.
    """
    hits: list[str] = []
    with zipfile.ZipFile(docx_path) as archive:
        for name in archive.namelist():
            lower = name.replace("\\", "/").lower()
            if not lower.endswith(".xml"):
                continue
            if not lower.startswith(_DOCX_XML_PREFIXES):
                continue
            raw = archive.read(name).decode("utf-8")
            visible = unescape(re.sub(r"<[^>]+>", "", raw))
            if PLACEHOLDER_TOKEN in visible:
                hits.append(name)
    return hits


def excluded_resume_role_titles(job_history_path: Path | None = None) -> list[str]:
    path = job_history_path or JOB_HISTORY
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    titles: list[str] = []
    for key in EXCLUDED_JOB_KEYS:
        role = data.get(key)
        if isinstance(role, dict) and role.get("title"):
            titles.append(str(role["title"]))
    return titles


def validate_printed_role_prefix(
    master_headers: list[str],
    tailored_headers: list[str],
    excluded_titles: list[str] | None = None,
) -> str | None:
    """Return an error string if tailored headers are not a 5-10 master prefix."""
    count = len(tailored_headers)
    if count < MIN_PRINTED_ROLES or count > MAX_PRINTED_ROLES:
        return (
            f"role header count {count} is outside {MIN_PRINTED_ROLES}-{MAX_PRINTED_ROLES}.\n"
            f"  expected prefix of master ({len(master_headers)}): "
            f"{master_headers[:MAX_PRINTED_ROLES]}\n"
            f"  actual   ({count}): {tailored_headers}"
        )
    expected = master_headers[:count]
    if tailored_headers != expected:
        return (
            f"role header chronology must match consecutive master prefix 1..{count}.\n"
            f"  expected ({count}): {expected}\n"
            f"  actual   ({count}): {tailored_headers}"
        )
    blocked = [
        header
        for header in tailored_headers
        if header.casefold()
        in {title.casefold() for title in (excluded_titles or [])}
    ]
    if blocked:
        return (
            "excluded locked keys 11-12 must not appear on the resume: "
            + ", ".join(blocked)
        )
    return None


def parse_role_headers(markdown_path: Path) -> list[str]:
    headers: list[str] = []
    if not markdown_path.is_file():
        return headers

    for line in markdown_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        header = stripped[3:].strip()
        if header.lower() == "skills":
            break
        headers.append(header)
    return headers


def _is_filename_segment(segment: str) -> bool:
    """True if a path segment looks like a file, including extensionless dotfiles.

    pathlib treats names like ``.gitkeep`` as a stem with an empty suffix, so
    a suffix-only check would misclassify them as a position slug.
    """
    if Path(segment).suffix:
        return True
    return segment.startswith(".")


def resume_tailor_dir_from_path(path: str) -> Path | None:
    """Resolve a nested company/position sandbox from a changed file path.

    Valid sandboxes are two segments under `.ai/history/resume-tailor/`
    (company + position). Single-segment legacy dirs (e.g. Deloitte/) and
    files sitting directly under a company folder are ignored. Reserved
    first segments such as ``queue/`` are not sandboxes.
    """
    normalized = path.replace("\\", "/")
    prefix = ".ai/history/resume-tailor/"
    if prefix not in normalized:
        return None
    remainder = normalized.split(prefix, 1)[1]
    parts = [part for part in remainder.split("/") if part]
    if len(parts) < 2:
        return None

    company, position = parts[0], parts[1]
    if company in RESERVED_RESUME_TAILOR_DIRS:
        return None
    # Legacy flat layout: company/file.md (second segment is a filename)
    if len(parts) == 2 and _is_filename_segment(position):
        return None
    if not company or not position:
        return None
    return RESUME_TAILOR_ROOT / company / position


def resume_tailor_identity(resume_tailor_dir: Path) -> tuple[str, str]:
    """Return (company_slug, position_slug) from nested sandbox folders."""
    position = resume_tailor_dir.name
    company = resume_tailor_dir.parent.name
    return company, position


def git_changed_files(base: str, head: str = "HEAD") -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, head],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        print(f"ERROR: git diff failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_resume_tailor_dirs(base: str, head: str = "HEAD") -> list[Path]:
    resume_tailor_dirs: dict[str, Path] = {}
    for changed in git_changed_files(base, head):
        resume_tailor_dir = resume_tailor_dir_from_path(changed)
        if resume_tailor_dir is not None:
            resume_tailor_dirs[str(resume_tailor_dir)] = resume_tailor_dir
    return sorted(resume_tailor_dirs.values(), key=lambda p: str(p))


def extract_role_title(job_description_path: Path) -> str:
    if not job_description_path.is_file():
        return "unknown-role"
    first_line = job_description_path.read_text(encoding="utf-8").splitlines()[0].strip()
    return first_line or "unknown-role"
