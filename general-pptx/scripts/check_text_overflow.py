#!/usr/bin/env python3
"""Estimate whether text fits inside its text box (CJK-aware).

Replaces the original LibreOffice round-trip check. That approach only works
with a Linux `soffice` on PATH, and even with the DSH bundled LibreOffice Kit
its pptx export never writes `fontScale`, so it reported "no overflow" for
every deck (verified 2026-10 on a 11-slide deck: 162 injected `normAutofit`
nodes survived, 0 `fontScale` attributes were emitted).

This checker instead measures geometry directly: for every text-bearing shape
it wraps the runs character by character at the shape's real width, sums the
line heights at the runs' real font sizes, and compares the result with the
shape's inner height. No external binaries, no network.

Usage:
    py -3 scripts/check_text_overflow.py deck.pptx
    py -3 scripts/check_text_overflow.py deck.pptx --slack 1.05

Exit code 1 when any risk is reported, 0 otherwise.

It is an ESTIMATE, not a renderer: word-wrap granularity, font substitution,
Asian line-breaking rules, autofit and vertical anchoring can all shift the
real result. A clean run does not prove the slide looks right — still inspect
rendered images (scripts/render_slides.py).
"""

from __future__ import annotations

import argparse
import math
import sys
import unicodedata
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

EMU_PT = 12700.0
DEFAULT_LINE_FACTOR = 1.32  # single-spacing line height of common CJK sans fonts
LATIN_W = 0.56  # advance width in em
CJK_W = 1.0
PUNCT_W = 0.5
SPACE_W = 0.30
BOLD_GAIN = 1.05
# OOXML defaults when <a:bodyPr> omits the insets.
DEFAULT_INSETS = {"l": 91440, "r": 91440, "t": 45720, "b": 45720}


def char_width(ch: str, bold: bool) -> float:
    if ch == " ":
        return SPACE_W
    if ch in "，。、；：！？（）《》“”‘’—…·":
        return PUNCT_W
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return CJK_W * (1.04 if bold else 1.0)
    width = LATIN_W
    if ch.isupper():
        width = 0.72
    if bold:
        width *= 1.06
    return width


def run_size_pt(run, paragraph, fallback: float) -> float:
    for size in (run.font.size, paragraph.font.size):
        if size is not None:
            return size.pt
    return fallback


def body_insets(text_frame) -> tuple[float, float, float, float]:
    def pick(value, key):
        if value is None:
            return DEFAULT_INSETS[key]
        return int(value)

    return (
        pick(text_frame.margin_left, "l"),
        pick(text_frame.margin_right, "r"),
        pick(text_frame.margin_top, "t"),
        pick(text_frame.margin_bottom, "b"),
    )


def paragraph_needs_pt(paragraph, default_size: float, avail_width_pt: float) -> tuple[float, float, str]:
    runs = [run for run in paragraph.runs if run.text]
    text = "".join(run.text for run in runs)
    sizes = [run_size_pt(run, paragraph, default_size) for run in runs] or [default_size]
    size = max(sizes)
    if not runs:
        return size * DEFAULT_LINE_FACTOR, size, ""

    pPr = paragraph._p.find(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}pPr"
    )
    marL = 0
    if pPr is not None and pPr.get("marL"):
        marL = int(pPr.get("marL"))
    indent = 0
    if pPr is not None and pPr.get("indent"):
        indent = int(pPr.get("indent"))
    hanging = abs(indent) if indent < 0 else 0
    usable_pt = max(avail_width_pt - (marL + hanging) / EMU_PT, 12.0)

    bold = any(run.font.bold for run in runs)
    em_width = sum(char_width(ch, bold) for ch in text)
    needed_pt = em_width * size
    lines = max(1, math.ceil(needed_pt / usable_pt - 1e-6))

    factor = DEFAULT_LINE_FACTOR
    if paragraph.line_spacing is not None:
        spacing = paragraph.line_spacing
        if isinstance(spacing, float) and spacing > 0:
            factor *= spacing
        elif not isinstance(spacing, float) and spacing.pt:
            factor = spacing.pt / size
    total = lines * size * factor
    if paragraph.space_after is not None:
        total += paragraph.space_after.pt
    if paragraph.space_before is not None:
        total += paragraph.space_before.pt
    preview = (text[:60] + "...") if len(text) > 60 else text
    return total, size, preview


def iter_text_frames(shapes, label_prefix: str = ""):
    """Yield (label, text_frame, width_emu, height_emu) for every text container."""
    for shape in shapes:
        if shape.shape_type == 6:  # GROUP
            yield from iter_text_frames(shape.shapes, f"{label_prefix}{shape.name}/")
        elif getattr(shape, "has_text_frame", False):
            yield f"{label_prefix}{shape.name or 'unnamed'}", shape.text_frame, shape.width, shape.height
        elif getattr(shape, "has_table", False):
            table = shape.table
            for row_index, row in enumerate(table.rows):
                for col_index, cell in enumerate(row.cells):
                    if not cell.text.strip():
                        continue
                    label = f"{label_prefix}{shape.name} r{row_index + 1}c{col_index + 1}"
                    yield label, cell.text_frame, table.columns[col_index].width, row.height


def check(path: Path, slack: float) -> int:
    presentation = Presentation(str(path))
    issues = 0
    checked = 0
    for index, slide in enumerate(presentation.slides, 1):
        for name, text_frame, width, height in iter_text_frames(slide.shapes):
            if not text_frame.text.strip():
                continue
            checked += 1
            left, right, top, bottom = body_insets(text_frame)
            box_w = (width or 0) - left - right
            box_h = (height or 0) - top - bottom
            avail_w_pt = max(box_w, 0.02 * 914400) / EMU_PT
            avail_h_pt = max(box_h, 0.02 * 914400) / EMU_PT

            needed = 0.0
            default_size = 18.0
            preview = ""
            for paragraph in text_frame.paragraphs:
                para_pt, default_size, para_preview = paragraph_needs_pt(
                    paragraph, default_size, avail_w_pt
                )
                needed += para_pt
                preview = preview or para_preview

            if needed > avail_h_pt * slack:
                issues += 1
                ratio = needed / avail_h_pt
                print(
                    f"[TEXT OVERFLOW RISK] slide{index} '{name}' "
                    f"({ratio * 100:.0f}% of box height): inner box "
                    f"{box_w / 914400:.2f}x{box_h / 914400:.2f}in, "
                    f"needs {needed / 72:.2f}in of height "
                    f'("{preview}")'
                )
    print(f"checked {checked} text shapes; {issues} risk(s) at slack {slack:g}")
    return 1 if issues else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pptx", help="Input .pptx file")
    parser.add_argument(
        "--slack",
        type=float,
        default=1.03,
        help="Report only above this ratio of needed/available height (default 1.03)",
    )
    args = parser.parse_args()
    path = Path(args.pptx)
    if not path.is_file():
        print(f"Error: {path} not found", file=sys.stderr)
        return 2
    return check(path, args.slack)


if __name__ == "__main__":
    sys.exit(main())
