from __future__ import annotations

import shutil
from pathlib import Path


def init_project(template: str, output_dir: str | Path) -> Path:
    if template != "incremental-basic":
        raise ValueError(f"Unknown template: {template}")
    output_dir = Path(output_dir)
    source = Path(__file__).resolve().parents[2] / "examples" / "shelldiver_v0"
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "economy.yaml", output_dir / "economy.yaml")
    shutil.copytree(source / "luban_exports", output_dir / "luban_exports", dirs_exist_ok=True)
    (output_dir / "README.md").write_text(
        "# IGESS Economy Project\n\n"
        "Run `igess lint --config economy.yaml --tables luban_exports` to validate this project.\n",
        encoding="utf-8",
        newline="\n",
    )
    return output_dir
