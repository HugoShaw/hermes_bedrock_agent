"""One-shot migration: reorganize yangma_v2 parsed/ and evidence/ into type-aware subdirectories.

Run from project root:
    python3 scripts/migrate_yangma_v2_structure.py
"""

import json
import shutil
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path("outputs/yangma_v2")
PARSED_DIR = PROJECT_DIR / "parsed"
EVIDENCE_DIR = PROJECT_DIR / "evidence"
MANIFEST_PATH = PROJECT_DIR / "parsing_manifest.json"

TYPE_SUBDIR_MAP = {
    "docx": "docs",
    "doc_vlm": "docs",
    "pdf_vlm": "docs",
    "html": "docs",
    "text": "docs",
    "markdown": "docs",
    "csv": "csv",
    "image_vlm": "images",
    "code": "code",
    "excel_vlm": "excel",
    "mermaid": "mermaid",
    "mermaid_v2": "mermaid",
}


def get_type_subdir(parser_type: str) -> str:
    return TYPE_SUBDIR_MAP.get(parser_type, "docs")


def main():
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found")
        return

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    files = manifest["files"]
    moved_parsed = 0
    moved_evidence = 0
    skipped = 0
    errors = []
    type_counts = Counter()

    # Track which evidence dirs we've already moved (avoid double-moves from dupe entries)
    moved_evidence_dirs = set()

    for entry in files:
        if entry.get("state") != "parsed":
            skipped += 1
            continue

        parser_type = entry.get("parser_type", "")
        old_output_path = entry.get("parsed_output_path", "")
        if not old_output_path:
            skipped += 1
            continue

        old_path = Path(old_output_path)
        safe_name = old_path.stem  # filename without .md

        type_subdir = get_type_subdir(parser_type)
        type_counts[type_subdir] += 1

        # New parsed path
        new_parsed_dir = PARSED_DIR / type_subdir
        new_parsed_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_parsed_dir / old_path.name

        # Move parsed file
        if old_path.exists():
            if old_path != new_path:
                if new_path.exists():
                    # Duplicate target - skip (first one wins)
                    pass
                else:
                    shutil.move(str(old_path), str(new_path))
                    moved_parsed += 1
        else:
            # File might already be in new location (re-run safety)
            if not new_path.exists():
                errors.append(f"MISSING: {old_path}")

        # Update manifest entry
        new_relative = f"outputs/yangma_v2/parsed/{type_subdir}/{old_path.name}"
        entry["parsed_output_path"] = new_relative

    # Move evidence directories (all current evidence is from pdf_vlm/doc_vlm → docs/)
    evidence_type_subdir = "docs"
    new_evidence_dir = EVIDENCE_DIR / evidence_type_subdir
    new_evidence_dir.mkdir(parents=True, exist_ok=True)

    if EVIDENCE_DIR.exists():
        for child in sorted(EVIDENCE_DIR.iterdir()):
            if child.is_dir() and child.name != evidence_type_subdir:
                dest = new_evidence_dir / child.name
                if dest.exists():
                    # Already moved
                    continue
                shutil.move(str(child), str(dest))
                moved_evidence += 1

    # Create intermediates/downloads/ for future use
    intermediates = PROJECT_DIR / "intermediates" / "downloads"
    intermediates.mkdir(parents=True, exist_ok=True)

    # Save updated manifest
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Verification
    print("=" * 60)
    print("Migration complete: yangma_v2")
    print("=" * 60)
    print(f"  Parsed files moved: {moved_parsed}")
    print(f"  Evidence dirs moved: {moved_evidence}")
    print(f"  Entries skipped (not parsed): {skipped}")
    if errors:
        print(f"  ERRORS: {len(errors)}")
        for e in errors:
            print(f"    {e}")

    print("\n  Type distribution:")
    for t, c in sorted(type_counts.items()):
        print(f"    {t:10} → {c} files")

    # Post-migration verification
    print("\n  Verification:")
    total_md = list(PARSED_DIR.rglob("*.md"))
    print(f"    Total .md files under parsed/: {len(total_md)}")

    for subdir in ["docs", "csv", "images", "code", "excel", "mermaid"]:
        d = PARSED_DIR / subdir
        if d.exists():
            count = len(list(d.glob("*.md")))
            print(f"    parsed/{subdir}/: {count} files")

    # Check no stray files left at top level of parsed/
    stray = [f for f in PARSED_DIR.iterdir() if f.is_file()]
    if stray:
        print(f"    WARNING: {len(stray)} stray files at parsed/ top level:")
        for s in stray[:5]:
            print(f"      {s.name}")

    # Evidence check
    evidence_files = list(EVIDENCE_DIR.rglob("*.png"))
    print(f"    Total evidence .png files: {len(evidence_files)}")

    evidence_top_dirs = [d for d in EVIDENCE_DIR.iterdir() if d.is_dir()]
    print(f"    Evidence top-level dirs: {[d.name for d in evidence_top_dirs]}")


if __name__ == "__main__":
    main()
