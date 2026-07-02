from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from nes_py.cli import main
from nes_py.version import get_build_info, get_version


def test_version_returns_non_empty_string() -> None:
    assert get_version()


def test_build_info_is_empty_when_metadata_is_absent() -> None:
    sys.modules.pop("nes_py._build_info", None)

    assert get_build_info() == {}


def test_cli_version_uses_generated_build_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("nes_py.cli.get_version", lambda: "1.0.3.dev42+gabc1234")

    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert "nes-py 1.0.3.dev42+gabc1234" in capsys.readouterr().out


def test_build_info_reads_generated_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = SimpleNamespace(
        version="1.0.3.dev42+gabc1234",
        base_version="1.0.3",
        commit_sha="abc1234def",
        short_commit_sha="abc1234",
        branch_name="main",
        build_number="42",
        build_timestamp_utc="2026-07-01T13:00:00Z",
    )
    monkeypatch.setitem(sys.modules, "nes_py._build_info", metadata)

    assert get_build_info()["version"] == "1.0.3.dev42+gabc1234"
    assert get_version() == "1.0.3.dev42+gabc1234"
