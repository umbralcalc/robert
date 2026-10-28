import os
import shutil
import sys
from pathlib import Path

import pytest

from robert.engine import Engine

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/logistic-growth"


def _have_stochadex() -> bool:
    e = Engine(REPO)
    return bool(e.bin and e.graph_bin)


needs_stochadex = pytest.mark.skipif(
    not _have_stochadex(),
    reason="stochadex and stochadex-graph not found (set STOCHADEX_BIN / put them on PATH)",
)


@pytest.fixture
def cli_env(monkeypatch):
    """Put this interpreter's `robert` on PATH, as an installed user would have it."""
    bindir = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", bindir + os.pathsep + os.environ.get("PATH", ""))
    assert shutil.which("robert"), "install robert into this environment (pip install -e .)"
    return os.environ
