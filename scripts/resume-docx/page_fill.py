#!/usr/bin/env python3
"""Advisory last-page fill estimator for tailored resume .docx files (ADR-051).

Deterministic, approximate. Given a filled resume `.docx`, read the template
page geometry (`page_height` minus top/bottom margins) and the body table's
row/cell widths, estimate each paragraph's wrapped-line height, sum the content
height, and report `(page_count, last_page_fill_ratio)`.

The accordion page-fill re-evaluation (resume-tailor SKILL.md) uses this to
decide whether an N>5 resume leaves its last page too sparse. This module is
**advisory only**: it never edits the document and never hard-fails CI or the
filler. See ADR-051 (extends ADR-049).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

_DOCX_DIR = Path(__file__).resolve().parent
if str(_DOCX_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCX_DIR))

import fill_resume as filler  # noqa: E402  (sibling module; run/imported from this dir)

# --- Unit helpers -----------------------------------------------------------
EMU_PER_TWIP = 635.0
TWIPS_PER_POINT = 20.0
# Word default single-spacing multiplier when no explicit line rule is present.
DEFAULT_LINE_FACTOR = 1.15
# Approximate left+right cell inset (Word default is 108 twips per side).
CELL_PAD_TWIPS = 108.0
# Target fill of the usable last-page height (accordion contract, ADR-051).
TARGET_FILL_RATIO = 0.75
# Only re-evaluate when the estimate falls below this (tolerance band).
TRIGGER_FILL_RATIO = 0.65

# Palatino Linotype 10pt regular advance widths in twips (Windows GDI @ 96 DPI).
# Body bullets/skills render regular weight; job headers use the bold map in
# fill_resume.PALATINO_10PT_BOLD_TWIPS. Unknown glyphs fall back to regular "n".
PALATINO_10PT_REGULAR_TWIPS = {
    " ": 45.0, "a": 105.0, "b": 120.0, "c": 90.0, "d": 120.0, "e": 105.0,
    "f": 60.0, "g": 105.0, "h": 120.0, "i": 60.0, "j": 60.0, "k": 105.0,
    "l": 60.0, "m": 180.0, "n": 120.0, "o": 120.0, "p": 120.0, "q": 120.0,
    "r": 75.0, "s": 90.0, "t": 60.0, "u": 120.0, "v": 105.0, "w": 165.0,
    "x": 105.0, "y": 105.0, "z": 90.0, "A": 150.0, "B": 135.0, "C": 135.0,
    "D": 165.0, "E": 120.0, "F": 120.0, "G": 150.0, "H": 165.0, "I": 75.0,
    "J": 75.0, "K": 150.0, "L": 120.0, "M": 195.0, "N": 165.0, "O": 165.0,
    "P": 120.0, "Q": 165.0, "R": 135.0, "S": 105.0, "T": 120.0, "U": 150.0,
    "V": 150.0, "W": 210.0, "X": 135.0, "Y": 135.0, "Z": 120.0, "0": 120.0,
    "1": 120.0, "2": 120.0, "3": 120.0, "4": 120.0, "5": 120.0, "6": 120.0,
    "7": 120.0, "8": 120.0, "9": 120.0, "/": 60.0, "-": 75.0, ".": 60.0,
    ",": 60.0, "'": 45.0, "&": 165.0, "(": 75.0, ")": 75.0, "[": 60.0,
    "]": 60.0, ":": 60.0, ";": 60.0, "\u00a0": 45.0,
}


@dataclass(frozen=True)
class FillEstimate:
    """Result of a deterministic last-page fill estimate."""

    page_count: int
    last_page_fill_ratio: float
    content_twips: float
    usable_twips: float

    @property
    def below_trigger(self) -> bool:
        return self.last_page_fill_ratio < TRIGGER_FILL_RATIO

    def summary_line(self) -> str:
        pct = round(self.last_page_fill_ratio * 100)
        target = round(TARGET_FILL_RATIO * 100)
        return (
            f"last page ~{pct}% full across {self.page_count} page(s) "
            f"(target >={target}% usable)"
        )


# --- Glyph width ------------------------------------------------------------
def _char_width_twips(text: str, size_pt: float, bold: bool) -> float:
    table = (
        filler.PALATINO_10PT_BOLD_TWIPS if bold else PALATINO_10PT_REGULAR_TWIPS
    )
    fallback = table["n"]
    scale = size_pt / 10.0
    return sum(table.get(ch, fallback) for ch in text) * scale


def _run_is_bold(run) -> bool:
    r_pr = run._r.find(qn("w:rPr"))
    if r_pr is None:
        return False
    b = r_pr.find(qn("w:b"))
    if b is None:
        return False
    return (b.get(qn("w:val")) or "true") not in ("0", "false", "none")


def _run_size_pt(run, para_pt: float) -> float:
    size = run.font.size
    if size is not None:
        return float(size.pt)
    from_rpr = filler._rpr_sz_pt(run._r)
    return from_rpr if from_rpr is not None else para_pt


def _paragraph_text_width_twips(paragraph: Paragraph) -> float:
    para_pt = filler.paragraph_font_pt(paragraph)
    total = 0.0
    for run in filler._text_runs(paragraph):
        text = run.text or ""
        if not text:
            continue
        total += _char_width_twips(text, _run_size_pt(run, para_pt), _run_is_bold(run))
    return total


# --- Spacing resolution -----------------------------------------------------
def _spacing_sources(paragraph: Paragraph) -> list:
    sources = []
    p_pr = paragraph._p.find(qn("w:pPr"))
    if p_pr is not None:
        sources.append(p_pr)
    style = paragraph.style
    seen: set[int] = set()
    while style is not None and id(style) not in seen:
        seen.add(id(style))
        s_pr = style.element.find(qn("w:pPr"))
        if s_pr is not None:
            sources.append(s_pr)
        style = style.base_style
    return sources


def _resolve_spacing(paragraph: Paragraph) -> tuple[int | None, str | None, int, int]:
    line: int | None = None
    line_rule: str | None = None
    before: int | None = None
    after: int | None = None
    for src in _spacing_sources(paragraph):
        sp = src.find(qn("w:spacing"))
        if sp is None:
            continue
        if line is None and sp.get(qn("w:line")):
            try:
                line = int(sp.get(qn("w:line")))
                line_rule = sp.get(qn("w:lineRule")) or "auto"
            except ValueError:
                pass
        if before is None and sp.get(qn("w:before")):
            try:
                before = int(sp.get(qn("w:before")))
            except ValueError:
                pass
        if after is None and sp.get(qn("w:after")):
            try:
                after = int(sp.get(qn("w:after")))
            except ValueError:
                pass
    return line, line_rule, before or 0, after or 0


def _line_height_twips(paragraph: Paragraph, font_pt: float) -> float:
    line, rule, _before, _after = _resolve_spacing(paragraph)
    if line is not None:
        if rule in ("atLeast", "exact"):
            height = float(line)
            if rule == "atLeast":
                return max(height, font_pt * TWIPS_PER_POINT)
            return height
        # "auto": value is in 240ths of a line.
        return font_pt * TWIPS_PER_POINT * (line / 240.0)
    return font_pt * TWIPS_PER_POINT * DEFAULT_LINE_FACTOR


# --- Widths -----------------------------------------------------------------
def _cell_width_twips(cell) -> float:
    tc_pr = cell._tc.find(qn("w:tcPr"))
    if tc_pr is not None:
        tc_w = tc_pr.find(qn("w:tcW"))
        if tc_w is not None and tc_w.get(qn("w:w")):
            try:
                return float(tc_w.get(qn("w:w")))
            except ValueError:
                pass
    width = cell.width
    if width is not None:
        return float(width) / EMU_PER_TWIP
    return 6720.0


# --- Height accumulation ----------------------------------------------------
def _paragraph_height_twips(paragraph: Paragraph, avail_twips: float) -> float:
    font_pt = filler.paragraph_font_pt(paragraph)
    line_h = _line_height_twips(paragraph, font_pt)
    text_w = _paragraph_text_width_twips(paragraph)
    if text_w <= 0 or avail_twips <= 0:
        lines = 1
    else:
        lines = max(1, math.ceil(text_w / avail_twips))
    _line, _rule, before, after = _resolve_spacing(paragraph)
    return lines * line_h + before + after


def _table_height_twips(table: Table) -> float:
    total = 0.0
    for row in table.rows:
        seen: set[int] = set()
        row_height = 0.0
        for cell in row.cells:
            tc_id = id(cell._tc)
            if tc_id in seen:
                continue
            seen.add(tc_id)
            avail = max(1.0, _cell_width_twips(cell) - 2 * CELL_PAD_TWIPS)
            row_height = max(row_height, _block_height_twips(cell._tc, cell, avail))
        total += row_height
    return total


def _block_height_twips(parent_elm, parent, avail_twips: float) -> float:
    total = 0.0
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            total += _paragraph_height_twips(Paragraph(child, parent), avail_twips)
        elif child.tag == qn("w:tbl"):
            total += _table_height_twips(Table(child, parent))
    return total


# --- Public API -------------------------------------------------------------
def estimate_fill(source) -> FillEstimate:
    """Estimate `(page_count, last_page_fill_ratio)` for a filled resume docx.

    `source` may be a path (str/Path) or an open python-docx Document.
    """
    doc = source if hasattr(source, "sections") else Document(str(source))
    section = doc.sections[0]
    page_h = float(section.page_height) / EMU_PER_TWIP
    top = float(section.top_margin) / EMU_PER_TWIP
    bottom = float(section.bottom_margin) / EMU_PER_TWIP
    left = float(section.left_margin) / EMU_PER_TWIP
    right = float(section.right_margin) / EMU_PER_TWIP
    usable = max(1.0, page_h - top - bottom)
    text_width = max(1.0, float(section.page_width) / EMU_PER_TWIP - left - right)

    content = _block_height_twips(doc.element.body, doc, text_width)
    page_count = max(1, math.ceil(content / usable))
    last_page = content - (page_count - 1) * usable
    ratio = max(0.0, min(1.0, last_page / usable))
    return FillEstimate(
        page_count=page_count,
        last_page_fill_ratio=ratio,
        content_twips=content,
        usable_twips=usable,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Estimate last-page fill for a tailored resume .docx (advisory)."
    )
    parser.add_argument("docx", help="Path to a filled John_Doe_Resume_*.docx")
    args = parser.parse_args(argv)
    path = Path(args.docx)
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1
    estimate = estimate_fill(path)
    print(estimate.summary_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
