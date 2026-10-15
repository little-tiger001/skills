#!/usr/bin/env python3
"""Check for element boundary violations in PPTX slides.

Usage:
    py -3 scripts/check_overlap.py output.pptx

Exits with code 1 if any element extends beyond slide boundaries, 0 otherwise.

This script only checks what code can reliably detect: elements that overflow
the slide edges. Overlapping elements (text-on-text, text-on-image) require
design intent judgment and are handled by visual QA instead.
"""

import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}

EMU_PER_INCH = 914400
DEFAULT_SLIDE_W = int(10 * EMU_PER_INCH)
DEFAULT_SLIDE_H = int(5.625 * EMU_PER_INCH)

# Allow elements to exceed slide bounds by up to 0.05" before flagging
BOUNDARY_TOLERANCE = int(0.05 * EMU_PER_INCH)


def emu_to_inches(emu):
    return emu / EMU_PER_INCH


def get_slide_size(z):
    """Read slide dimensions from presentation.xml."""
    try:
        root = ET.fromstring(z.read("ppt/presentation.xml"))
        sz = root.find(".//p:sldSz", NS)
        if sz is not None:
            return int(sz.get("cx", DEFAULT_SLIDE_W)), int(sz.get("cy", DEFAULT_SLIDE_H))
    except Exception:
        pass
    return DEFAULT_SLIDE_W, DEFAULT_SLIDE_H


def extract_elements(slide_bytes):
    """Extract all positioned elements with bounding boxes from a slide."""
    root = ET.fromstring(slide_bytes)
    sp_tree = root.find(".//p:cSld/p:spTree", NS)
    if sp_tree is None:
        return []

    elements = []
    _walk(sp_tree, elements)
    return elements


def _walk(node, elements):
    """Recursively collect elements, descending into groups."""
    for child in node:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "grpSp":
            _walk(child, elements)
            continue

        xfrm = child.find(".//{%s}xfrm" % NS["a"])
        if xfrm is None:
            continue

        off = xfrm.find("{%s}off" % NS["a"])
        ext = xfrm.find("{%s}ext" % NS["a"])
        if off is None or ext is None:
            continue

        x = int(off.get("x", "0"))
        y = int(off.get("y", "0"))
        w = int(ext.get("cx", "0"))
        h = int(ext.get("cy", "0"))

        if w == 0 or h == 0:
            continue

        # Resolve element name
        name = "unnamed"
        for nv in ["nvSpPr", "nvPicPr", "nvGrpSpPr", "nvGraphicFramePr", "nvCxnSpPr"]:
            nv_node = child.find("{%s}%s" % (NS["p"], nv))
            if nv_node is not None:
                cNvPr = nv_node.find("{%s}cNvPr" % NS["p"])
                if cNvPr is not None:
                    name = cNvPr.get("name", "unnamed")
                    break

        elements.append({"name": name, "x": x, "y": y, "w": w, "h": h})


def check_boundaries(elements, slide_w, slide_h):
    """Return a list of boundary violation messages."""
    issues = []
    for e in elements:
        right = e["x"] + e["w"]
        bottom = e["y"] + e["h"]

        if right > slide_w + BOUNDARY_TOLERANCE:
            over = emu_to_inches(right - slide_w)
            issues.append(f"'{e['name']}' extends {over:.2f}\" past right edge")
        if bottom > slide_h + BOUNDARY_TOLERANCE:
            over = emu_to_inches(bottom - slide_h)
            issues.append(f"'{e['name']}' extends {over:.2f}\" past bottom edge")
        if e["x"] < -BOUNDARY_TOLERANCE:
            over = emu_to_inches(abs(e["x"]))
            issues.append(f"'{e['name']}' extends {over:.2f}\" past left edge")
        if e["y"] < -BOUNDARY_TOLERANCE:
            over = emu_to_inches(abs(e["y"]))
            issues.append(f"'{e['name']}' extends {over:.2f}\" past top edge")

    return issues


def main(pptx_path):
    has_issues = False
    with zipfile.ZipFile(pptx_path, "r") as z:
        slide_w, slide_h = get_slide_size(z)
        slides = sorted(
            f for f in z.namelist()
            if f.startswith("ppt/slides/slide") and f.endswith(".xml")
        )
        for sf in slides:
            slide_label = sf.split("/")[-1].replace(".xml", "")
            elements = extract_elements(z.read(sf))
            issues = check_boundaries(elements, slide_w, slide_h)
            if issues:
                has_issues = True
                print(f"\n{slide_label}:")
                for msg in issues:
                    print(f"  [OVERFLOW] {msg}")

    if has_issues:
        print()
        sys.exit(1)
    else:
        print("No boundary issues detected.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: py -3 {sys.argv[0]} <file.pptx>")
        sys.exit(1)
    main(sys.argv[1])
