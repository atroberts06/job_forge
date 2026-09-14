"""Cover letter fill: 8-theme mapping and output name."""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document

_DOCX_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DOCX_DIR))

import fill_cover_letter as filler

OPENER = (
    "As an accomplished professional I am interested in the Solution Architect "
    "opportunity with LTS."
)
BODY_1 = "I have honed Salesforce Education Cloud and Systems Integration skills."
BODY_2 = "I offer Enterprise Architecture Governance and Cross-functional Team Leadership."
CTA = "I am eager to discuss joining LTS."


def _sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "lts" / "solution-architect-100"
    sandbox.mkdir(parents=True)
    (sandbox / "job-id.txt").write_text("greenhouse:lts:100\n", encoding="utf-8")
    (sandbox / "job-description.md").write_text(
        "# LTS - Solution Architect\n\n- **Location:** New York, NY\n",
        encoding="utf-8",
    )
    (sandbox / "tailored-cover-letter.md").write_text(
        "\n".join(
            [
                "# Cover Letter: LTS - Solution Architect",
                "",
                "- **Date:** September 11, 2026",
                "- **Recipient:** Hiring Team",
                "- **Subject:** RE: Solution Architect, Req #100, September 11, 2026",
                "- **Greeting:** Dear Hiring Team,",
                "",
                "## Opener",
                "",
                OPENER,
                "",
                "## Body 1",
                "",
                BODY_1,
                "",
                "## Body 2",
                "",
                BODY_2,
                "",
                "## Call to Action",
                "",
                CTA,
                "",
                "## Closing",
                "",
                "Sincerely,",
                "John Doe",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return sandbox


def test_fill_maps_eight_themes_and_writes_named_docx(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    dest = filler.gather_and_fill(sandbox)
    assert dest == sandbox / "John_Doe_Cover_Letter_Lts.docx"
    texts = [para.text.strip() for para in Document(str(dest)).paragraphs if para.text.strip()]
    joined = "\n".join(texts)
    assert "{{" not in joined
    assert "John Doe" in texts
    assert "September 11, 2026" in texts
    assert "RE: Solution Architect, Req #100, September 11, 2026" in texts
    assert "Dear Hiring Team," in texts
    assert OPENER in texts
    assert BODY_1 in texts
    assert BODY_2 in texts
    assert CTA in texts
    assert "Sincerely," in texts
