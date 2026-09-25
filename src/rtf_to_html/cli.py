"""Command line interface: ``rtf-to-html FILE [FILE ...]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, convert


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rtf-to-html",
        description="Render RTF files (e.g. rtflite tables) to HTML without LibreOffice.",
    )
    p.add_argument(
        "files", nargs="+", type=Path, metavar="FILE", help="RTF file(s) to convert"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output file for a single input ('-' for stdout)",
    )
    g.add_argument(
        "--outdir",
        type=Path,
        help="directory for the HTML files (default: next to each input)",
    )
    p.add_argument(
        "--fragment",
        action="store_true",
        help="emit an embeddable <div> instead of a full page",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output is not None and len(args.files) > 1:
        print(
            "error: --output can only be used with a single input file", file=sys.stderr
        )
        return 2
    status = 0
    for src in args.files:
        if not src.is_file():
            print(f"error: {src}: no such file", file=sys.stderr)
            status = 1
            continue
        try:
            html = convert(src, fragment=args.fragment)
        except Exception as exc:  # noqa: BLE001 - report and continue with the next file
            print(f"error: {src}: {exc}", file=sys.stderr)
            status = 1
            continue
        if args.output is not None and str(args.output) == "-":
            sys.stdout.write(html)
            continue
        if args.output is not None:
            dst = args.output
        elif args.outdir is not None:
            dst = args.outdir / src.with_suffix(".html").name
        else:
            dst = src.with_suffix(".html")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(html, encoding="utf-8")
        print(dst)
    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
