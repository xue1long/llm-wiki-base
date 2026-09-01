import py_compile
from pathlib import Path


def test_ingest_module_compiles():
    py_compile.compile(
        str(Path(__file__).parents[2] / "src" / "pipeline" / "ingest.py"),
        doraise=True,
    )
