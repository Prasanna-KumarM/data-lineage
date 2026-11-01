"""python -m par_fpl_lineage [--baseline metadata/PAR] [--output outputs/FPL/lineage.db] [--source CLO]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from par_fpl_lineage.api import extract
from par_fpl_lineage.config import settings
from par_fpl_lineage.errors import BaselineNotFound


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="par_fpl_lineage", description="Extract FPL-to-PAR lineage from the DB baseline scripts.")
    parser.add_argument("--baseline", default=settings.DEFAULT_BASELINE, help=f"checkout of the baseline repo (default: {settings.DEFAULT_BASELINE})")
    parser.add_argument("--output", default=settings.DEFAULT_OUTPUT, help=f"database to write (default: {settings.DEFAULT_OUTPUT})")
    parser.add_argument("--source", default=None, help="only this PAR_SOURCE (e.g. CLO)")
    args = parser.parse_args(argv)

    try:
        report = extract(args.baseline, args.output, args.source)
    except BaselineNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: extraction failed: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    (output.parent / "application").write_text(settings.PROJECT + "\n")
    (output.parent / "continuation_only").touch()

    print(f"wrote {output}")
    print(report.summary_line())
    return 0
