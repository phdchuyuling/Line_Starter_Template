"""CLI entrypoint for line_sticker_tool.

Usage:
    python -m line_sticker_tool --input ./images --output stickers.zip
    line-sticker-tool --input ./images --output stickers.zip --count 16 --report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import ProcessingOptions, StickerProcessor, VALID_COUNTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="line-sticker-tool",
        description="Automated LINE sticker cropping, validation, and packaging tool.",
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="FOLDER",
        help="Input folder containing source images (PNG/JPG).",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="ZIP",
        help="Output ZIP file path.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=16,
        choices=list(VALID_COUNTS),
        metavar="{8,16,24,32,40}",
        help="Number of sticker images to include (default: 16).",
    )
    parser.add_argument(
        "--main",
        metavar="FILE",
        help="Optional path to a specific image to use as the main (240×240) image.",
    )
    parser.add_argument(
        "--tab",
        metavar="FILE",
        help="Optional path to a specific image to use as the tab (96×74) image.",
    )
    parser.add_argument(
        "--no-rembg",
        action="store_true",
        default=False,
        help="Disable automatic background removal (rembg).",
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        help="Write a JSON validation report to FILE (use '-' for stdout).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_folder = Path(args.input)
    if not input_folder.is_dir():
        print(f"[ERROR] Input folder not found: {input_folder}", file=sys.stderr)
        return 1

    output_zip = Path(args.output)

    opts = ProcessingOptions(
        count=args.count,
        use_rembg=not args.no_rembg,
        main_path=Path(args.main) if args.main else None,
        tab_path=Path(args.tab) if args.tab else None,
    )

    processor = StickerProcessor(opts)

    print(f"[INFO] Processing images from: {input_folder}")
    print(f"[INFO] Sticker count: {opts.count}")
    print(f"[INFO] Background removal: {'enabled' if opts.use_rembg else 'disabled'}")

    try:
        validations = processor.process_folder(input_folder, output_zip)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Print summary
    passed = sum(1 for v in validations if v.ok)
    failed = len(validations) - passed
    print(f"[INFO] Processed {len(validations)} output images: {passed} OK, {failed} with errors.")

    for v in validations:
        status = "OK" if v.ok else "FAIL"
        print(f"  [{status}] {v.filename}")
        for e in v.errors:
            print(f"         ERROR: {e}")
        for w in v.warnings:
            print(f"         WARN:  {w}")

    print(f"[INFO] ZIP written to: {output_zip}")

    # Optional JSON report
    if args.report:
        report_json = processor.build_report(validations)
        if args.report == "-":
            print(report_json)
        else:
            Path(args.report).write_text(report_json, encoding="utf-8")
            print(f"[INFO] Report written to: {args.report}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
