"""Shared test fixtures: a throwaway database, fixture paths, and the snapshot helper."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from t2e import store
from t2e.config import Settings, set_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
GOLDEN_DIR = Path(__file__).parent / "golden"

#: `tests/golden/test_cases.py` is a *generated artefact* that happens to look like a test module, so
#: pytest would otherwise collect and run it - against an agent adapter that does not exist here.
#: It is exercised properly, in a temp directory with a fake adapter, by test_generated_pytest_stub.py.
collect_ignore_glob = ["golden/*"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="rewrite snapshot and golden files instead of comparing against them",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Settings]:
    """A fresh SQLite database per test, under tmp_path. Never touches the developer's ./.t2e."""
    store.reset_engine()
    settings = Settings(db_path=tmp_path / "t2e.db")
    set_settings(settings)
    store.init_db(settings)
    try:
        yield settings
    finally:
        store.reset_engine()


@pytest.fixture
def session(db: Settings) -> Iterator[Any]:
    with store.session_scope() as sess:
        yield sess


# --- snapshot / golden helpers ------------------------------------------------------------------


def _write_if_updating(path: Path, text: str, request: pytest.FixtureRequest) -> bool:
    """Write the file when --snapshot-update is set, or when bootstrapping a brand-new snapshot."""
    updating = bool(request.config.getoption("--snapshot-update"))
    if updating or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if not updating:
            # Bootstrapping is convenient locally but must not look like a passing assertion in CI.
            request.node.add_report_section(
                "call", "snapshot", f"created new snapshot {path.name}; review and commit it"
            )
        return True
    return False


@pytest.fixture
def assert_snapshot(request: pytest.FixtureRequest) -> Callable[[str, Any], None]:
    """Compare JSON-serializable data against `tests/snapshots/<name>.json`."""

    def _assert(name: str, data: Any) -> None:
        path = SNAPSHOT_DIR / f"{name}.json"
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if _write_if_updating(path, text, request):
            return
        expected = path.read_text(encoding="utf-8")
        assert text == expected, (
            f"snapshot mismatch for {name}.\n"
            f"Run `uv run pytest --snapshot-update` and review the diff if this change is intended."
        )

    return _assert


@pytest.fixture
def assert_golden(request: pytest.FixtureRequest) -> Callable[[str, str], None]:
    """Compare generated text against `tests/golden/<name>`, byte for byte."""

    def _assert(name: str, text: str) -> None:
        path = GOLDEN_DIR / name
        if _write_if_updating(path, text, request):
            return
        expected = path.read_text(encoding="utf-8")
        assert text == expected, (
            f"golden mismatch for {name}.\n"
            f"Run `uv run pytest --snapshot-update` and review the diff if this change is intended."
        )

    return _assert
