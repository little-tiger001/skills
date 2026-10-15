#!/usr/bin/env python3
"""Render PPTX slides to PNG for visual QA.

Replaces the original `soffice` + `pdftoppm` pipeline, which does not exist on
this host. Two engines:

  wps            WPS / PowerPoint COM export (Windows only, needs WPS or Office).
                 Default, because it is faithful for every deck size tested.
  kit            DSH's bundled LibreOffice Kit CLI, driven by its bundled Node.

Measured on this host (2026-10, LibreOffice Kit 0.1.2): for 13.333x7.5in
(LAYOUT_WIDE) decks the kit emits a page-sized PNG whose *content* is drawn
larger than the page — right and bottom are cut off, on decks from both
PptxGenJS and python-pptx. WPS COM renders the same files correctly, so `auto`
prefers it and keeps the kit only as a fallback.

Usage:
    py -3 scripts/render_slides.py deck.pptx --out preview-v1
    py -3 scripts/render_slides.py deck.pptx --out preview-v1 --pages 1,3,5 --dpi 144
    py -3 scripts/render_slides.py deck.pptx --out preview-v1 --engine kit

Always writes into a NEW directory. Prints one PNG path per line, then the
manifest path. Exit code 0 only when at least one image was produced.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT_CLI_TAIL = Path("libreoffice-kit") / "lib" / "cli.js"


def _candidate_roots() -> list[Path]:
    roots = []
    for env in ("DSH_PRIMARY_RUNTIME", "DSH_RESOURCES"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs" / "TokenWorks" / "resources")
    pf = os.environ.get("ProgramFiles")
    if pf:
        roots.append(Path(pf) / "TokenWorks" / "resources")
    return [r for r in roots if r.exists()]


def find_kit_cli() -> Path | None:
    override = os.environ.get("DSH_LIBREOFFICE_KIT_CLI")
    if override and Path(override).is_file():
        return Path(override)
    patterns = (
        "*/node_modules/@deepseek-ai/" + KIT_CLI_TAIL.as_posix(),
        "*/*/node_modules/@deepseek-ai/" + KIT_CLI_TAIL.as_posix(),
        "*/*/*/node_modules/@deepseek-ai/" + KIT_CLI_TAIL.as_posix(),
    )
    for root in _candidate_roots():
        for pattern in patterns:
            for hit in sorted(root.glob(pattern)):
                if hit.is_file():
                    return hit
    return None


def find_node(kit_cli: Path) -> str | None:
    override = os.environ.get("DSH_NODE")
    if override and Path(override).is_file():
        return override
    # node.exe sits beside the `product` directory in the desktop layout.
    for parent in list(kit_cli.parents)[:8]:
        candidate = parent / "node.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("node")


def render_with_kit(pptx: Path, out_dir: Path, pages: str | None, dpi: int) -> int:
    cli = find_kit_cli()
    if cli is None:
        print(
            "kit engine unavailable: LibreOffice Kit CLI not found. "
            "Set DSH_LIBREOFFICE_KIT_CLI, or rerun with --engine wps.",
            file=sys.stderr,
        )
        return 2
    node = find_node(cli)
    if node is None:
        print("kit engine unavailable: no node executable found.", file=sys.stderr)
        return 2

    # The kit CLI creates the output directory itself and refuses an existing one.
    cmd = [node, str(cli), "render", "--input", str(pptx), "--output-dir", str(out_dir), "--dpi", str(dpi)]
    if pages:
        cmd += ["--pages", pages]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL)
    if result.returncode != 0:
        print(f"kit render failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode

    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        print("kit render produced no manifest.json", file=sys.stderr)
        return 3
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images") or []
    missing = manifest.get("missingFonts") or []
    for image in images:
        index = image["page"] if "page" in image else image["index"]
        print(f"slide {index}: {image['path']}")
    print(f"manifest: {manifest_path}")
    if missing:
        print(f"missing fonts: {', '.join(sorted(set(missing)))}", file=sys.stderr)
    return 0 if images else 3


def render_with_wps(pptx: Path, out_dir: Path, pages: str | None, dpi: int) -> int:
    script = HERE / "render_wps.ps1"
    if not script.is_file():
        print(f"wps engine unavailable: {script} not found", file=sys.stderr)
        return 2
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        print("wps engine unavailable: no PowerShell found", file=sys.stderr)
        return 2
    # 96 dpi base: WPS exports at pixel dimensions, so scale the 13.333in wide default.
    height = max(240, int(dpi * 0.75 * 9 / 12 * 10))
    width = int(height * 16 / 9)
    # Render a shadow copy: WPS holds a share lock on whatever it opens, which
    # would block the build script from rewriting the deck afterwards.
    shadow_dir = tempfile.mkdtemp(prefix="gpq-render-")
    shadow = Path(shadow_dir) / pptx.name
    shutil.copy2(pptx, shadow)
    cmd = [
        shell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Source",
        str(shadow),
        "-OutputDir",
        str(out_dir),
        "-Width",
        str(width),
        "-Height",
        str(height),
    ]
    if pages:
        cmd += ["-Pages", pages]
    # The script prints the paths it wrote; we print our own list below.
    code = subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode
    shutil.rmtree(shadow_dir, ignore_errors=True)
    if code != 0:
        return 4
    produced = sorted(out_dir.glob("slide-*.png"))
    for path in produced:
        print(str(path))
    return 0 if produced else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Render PPTX slides to PNG.")
    parser.add_argument("input", help="Input .pptx file")
    parser.add_argument("--out", required=True, help="New output directory for the PNGs")
    parser.add_argument("--pages", help='One-based pages, e.g. "1,3-5"; default all')
    parser.add_argument("--dpi", type=int, default=144, help="Render resolution (default 144)")
    parser.add_argument("--engine", choices=("auto", "kit", "wps"), default="auto")
    args = parser.parse_args()

    pptx = Path(args.input).resolve()
    if not pptx.is_file():
        print(f"Error: {pptx} not found", file=sys.stderr)
        return 1
    out_dir = Path(args.out).resolve()
    if out_dir.exists():
        print(f"Error: {out_dir} already exists; use a new directory", file=sys.stderr)
        return 1

    if args.engine == "wps":
        return render_with_wps(pptx, out_dir, args.pages, args.dpi)
    if args.engine == "kit":
        return render_with_kit(pptx, out_dir, args.pages, args.dpi)

    # auto: prefer the faithful COM engine, fall back to the bundled kit.
    code = render_with_wps(pptx, out_dir, args.pages, args.dpi)
    if code == 0:
        return 0
    if out_dir.exists():
        shutil.rmtree(out_dir)
    print("wps engine unavailable; falling back to kit", file=sys.stderr)
    return render_with_kit(pptx, out_dir, args.pages, args.dpi)


if __name__ == "__main__":
    sys.exit(main())
