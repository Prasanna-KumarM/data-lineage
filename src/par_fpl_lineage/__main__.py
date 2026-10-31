"""CLI: python -m par_fpl_lineage [--baseline metadata/PAR] [--output outputs/FPL/lineage.db] [--source CLO]"""
import argparse
from pathlib import Path

from par_fpl_lineage.build import PROJECT, build


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract FPL-to-PAR lineage from the DB baseline scripts.")
    parser.add_argument("--baseline", default="metadata/PAR", help="checkout of the baseline repo (default: metadata/PAR)")
    parser.add_argument("--output", default="outputs/FPL/lineage.db", help="database to write (default: outputs/FPL/lineage.db)")
    parser.add_argument("--source", default=None, help="only this PAR_SOURCE (e.g. CLO)")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stats = build(Path(args.baseline), output, args.source)

    # UI markers: application name and continuation-only.
    (output.parent / "application").write_text(PROJECT + "\n")
    (output.parent / "continuation_only").touch()

    print(f"wrote {output}")
    print(f"loader entries: {stats['loaders']}, relations: {stats['relations']}, "
          f"views missing: {stats['views_missing']}, issues: {stats['issues']}")


if __name__ == "__main__":
    main()
