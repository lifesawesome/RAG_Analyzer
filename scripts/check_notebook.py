import argparse
import ast
from pathlib import Path

import nbformat


def main():
    parser = argparse.ArgumentParser(description="Validate notebook JSON/Python and optionally normalize non-code cell metadata.")
    parser.add_argument("--format", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "notebooks" / "01_databricks_rag.ipynb"
    notebook = nbformat.read(path, as_version=4)
    if args.format:
        for cell in notebook.cells:
            cell.metadata["language"] = "markdown" if cell.cell_type == "markdown" else "python"
            cell.metadata["id"] = cell.id
        nbformat.write(notebook, path)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        assert cell.metadata.get("language") in {"markdown", "python"}
        assert cell.metadata.get("id")
        if cell.cell_type == "code":
            ast.parse("\n".join(line for line in cell.source.splitlines() if not line.startswith("%")))
    print(f"PASS: {len(notebook.cells)} cells, required metadata and Python syntax. Cloud execution not verified.")


if __name__ == "__main__":
    main()