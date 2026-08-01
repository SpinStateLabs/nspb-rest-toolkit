"""Build the distributable .mcpb (MCP Bundle) file for Claude Desktop.

    python scripts/build_mcpb.py

Assembles a staging directory (mcpb/manifest.json + server/main.py, plus a
copy of pyproject.toml/README.md/LICENSE/src/ from the repo root -- uv needs
those to resolve and run the package at install time) and packs it into
dist/nspb-rest-toolkit.mcpb via the official `mcpb` CLI (`npx
@anthropic-ai/mcpb pack`). Re-run this after every source change meant to
ship -- the staging copy is rebuilt from scratch each time, never hand-edited.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "dist" / "mcpb-staging"
OUTPUT_DIR = ROOT / "dist"
OUTPUT_FILE = OUTPUT_DIR / "nspb-rest-toolkit.mcpb"


_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def main() -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True, exist_ok=True)

    # MCPB-specific files (hand-maintained under mcpb/).
    shutil.copy2(ROOT / "mcpb" / "manifest.json", STAGING / "manifest.json")
    shutil.copytree(ROOT / "mcpb" / "server", STAGING / "server", ignore=_IGNORE)

    # Everything uv needs to resolve + run the package at install time.
    shutil.copy2(ROOT / "pyproject.toml", STAGING / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", STAGING / "README.md")
    shutil.copy2(ROOT / "LICENSE", STAGING / "LICENSE")
    shutil.copytree(ROOT / "src", STAGING / "src", ignore=_IGNORE)

    OUTPUT_DIR.mkdir(exist_ok=True)
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    result = subprocess.run(
        ["npx", "--yes", "--package=@anthropic-ai/mcpb", "mcpb", "pack", str(STAGING), str(OUTPUT_FILE)],
        cwd=ROOT,
        shell=(sys.platform == "win32"),
    )
    if result.returncode != 0:
        raise SystemExit(f"mcpb pack failed with exit code {result.returncode}")

    print(f"\nBuilt: {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
