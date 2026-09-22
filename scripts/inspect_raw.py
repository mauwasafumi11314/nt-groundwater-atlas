#!/usr/bin/env python
"""Report what is actually in data/raw/, so mappings can be written against it.

    python scripts/inspect_raw.py [path] [--no-values] [--out FILE]

Reads nothing into the repository; --out writes under outputs/, which is
gitignored. See ntgw.inspect for the logic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ntgw.inspect import inspect_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/raw", type=Path)
    parser.add_argument(
        "--no-values", action="store_true", help="omit sample values, report structure only"
    )
    parser.add_argument("--out", type=Path, help="also write the report here")
    args = parser.parse_args()

    lines = inspect_path(args.path, show_values=not args.no_values)
    report = "\n".join(lines)
    print(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report)
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
