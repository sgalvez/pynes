"""Version helpers for installed packages and stamped CI builds."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any


def get_build_info() -> dict[str, Any]:
    """Return generated build metadata when it is packaged."""
    try:
        from . import _build_info
    except ImportError:
        return {}

    return {
        "version": getattr(_build_info, "version", ""),
        "base_version": getattr(_build_info, "base_version", ""),
        "commit_sha": getattr(_build_info, "commit_sha", ""),
        "short_commit_sha": getattr(_build_info, "short_commit_sha", ""),
        "branch_name": getattr(_build_info, "branch_name", ""),
        "build_number": getattr(_build_info, "build_number", ""),
        "build_timestamp_utc": getattr(_build_info, "build_timestamp_utc", ""),
    }


def get_version() -> str:
    """Return the generated build version or installed package version."""
    build_version = get_build_info().get("version")
    if build_version:
        return str(build_version)

    try:
        return version("pynes")
    except PackageNotFoundError:
        return "0+unknown"
