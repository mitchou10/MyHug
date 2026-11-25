"""Generates `myhug/_models.py` (the Pydantic models of what the API sends and takes) from `openapi.json`.

    uv run python scripts/generate.py          # write it
    uv run python scripts/generate.py --check  # fail when the committed file is not what the schema gives

`openapi.json` at the root of the repository comes from the backend (`backend/scripts/export_openapi.py`).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "openapi.json"
OUTPUT = Path(__file__).resolve().parents[1] / "myhug" / "_models.py"


def render() -> str:
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "models.py"
        subprocess.run(
            [
                sys.executable, "-m", "datamodel_code_generator",
                "--input", str(SCHEMA),
                "--input-file-type", "openapi",
                "--output", str(target),
                "--output-model-type", "pydantic_v2.BaseModel",
                "--target-python-version", "3.13",
                "--use-annotated",
                "--use-union-operator",
                "--use-standard-collections",
                "--use-double-quotes",
                "--field-constraints",
                "--set-default-enum-member",
                "--collapse-root-models",
                "--disable-timestamp",
                "--formatters", "ruff-format", "ruff-check",
            ],
            check=True,
        )  # fmt: skip
        return target.read_text()


if __name__ == "__main__":
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text() != render():
            sys.exit("myhug/_models.py is not up to date: run `uv run python scripts/generate.py` in sdk/")
    else:
        OUTPUT.write_text(render())
        print(OUTPUT.relative_to(OUTPUT.parents[1]))
