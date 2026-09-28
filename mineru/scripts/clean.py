#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 缓存清理脚本（仅用 Python 标准库）。

用途：
  源文件被改名/删除后，.mineru/ 里对应的 Markdown 与图片会变成「死文件」。
  本脚本扫描 .mineru/，找出没有对应源文件的缓存并清理。

命名规则（与 parse.py 一致）：
  源文件相对工作区根目录的路径，把 "/" 换成 "-"，去掉后缀，即为 .mineru/<stem>.md
  例如 相关论文/foo.pdf -> .mineru/相关论文-foo.md
  图片命名为 <stem>_<原图名>，存放在 .mineru/img/

用法：
  python clean.py                 # 只列出死文件（dry-run，默认）
  python clean.py --delete        # 实际删除死文件
  python clean.py --delete --yes  # 跳过确认，直接删除
  python clean.py --root <目录>   # 指定工作区根目录（默认当前目录）
"""

import argparse
import sys
from pathlib import Path

# 会被解析的源文件后缀（与 MinerU 支持格式一致）
SOURCE_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
}


def source_stem(file_path: Path, workspace_root: Path) -> str:
    """与 parse.py 的 output_stem 保持一致。"""
    try:
        rel = file_path.relative_to(workspace_root).as_posix()
    except ValueError:
        rel = file_path.name
    return Path(rel).with_suffix("").as_posix().replace("/", "-")


def collect_source_stems(workspace_root: Path) -> set:
    """扫描工作区，收集所有源文件对应的 stem。"""
    stems = set()
    for p in workspace_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SOURCE_EXTS:
            continue
        # 跳过 .mineru 自身
        try:
            p.relative_to(workspace_root / ".mineru")
            continue
        except ValueError:
            pass
        stems.add(source_stem(p, workspace_root))
    return stems


def find_orphans(out_dir: Path, valid_stems: set):
    """返回 (死 md 列表, 死图片列表)。"""
    orphan_mds = []
    orphan_imgs = []

    if not out_dir.exists():
        return orphan_mds, orphan_imgs

    for md in sorted(out_dir.glob("*.md")):
        if md.stem not in valid_stems:
            orphan_mds.append(md)

    img_dir = out_dir / "img"
    if img_dir.exists():
        for img in sorted(img_dir.iterdir()):
            if not img.is_file():
                continue
            # 图片名形如 <stem>_<原图名>，取最长匹配的 stem
            matched = any(img.name.startswith(f"{s}_") for s in valid_stems)
            if not matched:
                orphan_imgs.append(img)

    return orphan_mds, orphan_imgs


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    parser = argparse.ArgumentParser(description="清理 .mineru 死文件")
    parser.add_argument("--delete", action="store_true",
                        help="实际删除（默认只列出）")
    parser.add_argument("--yes", action="store_true",
                        help="删除时跳过确认")
    parser.add_argument("--root", default=None,
                        help="工作区根目录（默认当前目录）")
    args = parser.parse_args()

    workspace_root = Path(args.root).resolve() if args.root else Path.cwd()
    out_dir = workspace_root / ".mineru"

    if not out_dir.exists():
        print(f"未找到缓存目录: {out_dir}")
        return

    print(f"工作区根目录: {workspace_root}")
    print(f"缓存目录: {out_dir}")
    print("=" * 60)

    valid_stems = collect_source_stems(workspace_root)
    print(f"有效源文件: {len(valid_stems)} 个")

    orphan_mds, orphan_imgs = find_orphans(out_dir, valid_stems)

    total_size = sum(p.stat().st_size for p in orphan_mds + orphan_imgs)

    if not orphan_mds and not orphan_imgs:
        print("✓ 没有死文件，缓存干净。")
        return

    print(f"\n发现死文件: {len(orphan_mds)} 个 Markdown, "
          f"{len(orphan_imgs)} 张图片 (共 {human_size(total_size)})")
    print("-" * 60)
    for p in orphan_mds:
        print(f"  [MD ] {p.relative_to(workspace_root).as_posix()}")
    for p in orphan_imgs:
        print(f"  [IMG] {p.relative_to(workspace_root).as_posix()}")

    if not args.delete:
        print("-" * 60)
        print("这是预览模式（dry-run）。加 --delete 才会真正删除。")
        return

    if not args.yes:
        try:
            ans = input(f"\n确认删除以上 {len(orphan_mds) + len(orphan_imgs)} "
                        f"个文件? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("已取消。")
            return

    removed = 0
    for p in orphan_mds + orphan_imgs:
        try:
            p.unlink()
            removed += 1
        except OSError as e:
            print(f"  ✗ 删除失败 {p.name}: {e}")

    # 清理空的 img 目录
    img_dir = out_dir / "img"
    if img_dir.exists() and not any(img_dir.iterdir()):
        try:
            img_dir.rmdir()
            print("  已删除空的 img/ 目录")
        except OSError:
            pass

    print("=" * 60)
    print(f"✓ 已删除 {removed} 个死文件，释放 {human_size(total_size)}")


if __name__ == "__main__":
    main()
