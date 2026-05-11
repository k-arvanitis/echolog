from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

_PACKAGE = "meeting_intelligence_engine"


def _package_module_names() -> list[str]:
    return [name for name in sys.modules if name == _PACKAGE or name.startswith(_PACKAGE + ".")]


def _drop_package_modules() -> None:
    for name in _package_module_names():
        del sys.modules[name]


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Callable[..., ModuleType]]:
    """Build a fresh, fully-mocked FastAPI app module against a temp SQLite DB.

    Re-imports the whole package so module-level Settings/engine pick up the test
    environment, then restores ``sys.modules`` afterwards so other test files keep
    the modules they imported at collection time.
    """
    snapshot = {name: sys.modules[name] for name in _package_module_names()}

    def _build(
        *,
        rag_enabled: bool = False,
        db_name: str = "test.db",
        extra_env: dict[str, str] | None = None,
    ) -> ModuleType:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / db_name}")
        monkeypatch.setenv("REDIS_URL", "memory://")
        monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
        monkeypatch.setenv("MIE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("GROQ_API_KEY", "test")
        monkeypatch.setenv("HF_TOKEN", "test")
        monkeypatch.setenv("MIE_RAG_ENABLED", "true" if rag_enabled else "false")
        for key, value in (extra_env or {}).items():
            monkeypatch.setenv(key, value)
        _drop_package_modules()
        return importlib.import_module(f"{_PACKAGE}.api.main")

    yield _build

    _drop_package_modules()
    sys.modules.update(snapshot)
