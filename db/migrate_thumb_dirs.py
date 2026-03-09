#!/usr/bin/env python3
"""One-time migration: move thumbnails from 1-level to 2-level hash directory structure.

Old layout: /data/thumbs/{sha[:2]}/{sha}/
New layout: /data/thumbs/{sha[:2]}/{sha[2:4]}/{sha}/

Usage: python db/migrate_thumb_dirs.py [--dry-run] [--thumbs-path /data/thumbs]
"""
import argparse
import sys
from pathlib import Path


def migrate(base: Path, dry_run: bool = False) -> tuple[int, int]:
    moved = 0
    skipped = 0
    for prefix_dir in sorted(base.iterdir()):
        if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
            continue
        for sha_dir in list(prefix_dir.iterdir()):  # snapshot to avoid mutation
            sha = sha_dir.name
            if not sha_dir.is_dir() or len(sha) < 4:
                continue
            # Check if already in new layout (parent is a 2-char dir that is NOT the prefix)
            if len(prefix_dir.name) == 2 and sha_dir.parent.name == sha[:2]:
                # Still old layout — need to move
                new_parent = base / sha[:2] / sha[2:4]
                new_path = new_parent / sha
                if sha_dir == new_path:
                    skipped += 1
                    continue
                if dry_run:
                    print(f"  [DRY-RUN] {sha_dir} -> {new_path}")
                else:
                    new_parent.mkdir(parents=True, exist_ok=True)
                    sha_dir.rename(new_path)
                moved += 1
    return moved, skipped


def main():
    parser = argparse.ArgumentParser(description="Migrate thumbnail dirs to 2-level hash layout")
    parser.add_argument("--dry-run", action="store_true", help="Print moves without executing")
    parser.add_argument("--thumbs-path", default="/data/thumbs", help="Thumbnail base directory")
    args = parser.parse_args()

    base = Path(args.thumbs_path)
    if not base.exists():
        print(f"Thumbs path does not exist: {base}")
        sys.exit(1)

    print(f"Migrating thumbnails in {base} ({'DRY RUN' if args.dry_run else 'LIVE'})...")
    moved, skipped = migrate(base, args.dry_run)
    print(f"Done: {moved} moved, {skipped} skipped")


if __name__ == "__main__":
    main()
