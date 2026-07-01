"""Generate continuous build metadata for CI artifacts and packages."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_metadata import (
    DEFAULT_METADATA_PATH,
    DEFAULT_PACKAGE_INFO_PATH,
    collect_metadata,
    update_project_version,
    write_json,
    write_package_info,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--package-info", type=Path, default=DEFAULT_PACKAGE_INFO_PATH)
    parser.add_argument("--write-package-info", action="store_true")
    parser.add_argument("--update-project-version", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    metadata = collect_metadata()
    write_json(args.output, metadata)
    if args.write_package_info:
        write_package_info(args.package_info, metadata)
    if args.update_project_version:
        update_project_version(metadata["version"])
    print(metadata["version"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
