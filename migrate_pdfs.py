#!/usr/bin/env python3
"""
PDF Migration Script - Phase 1
Migrates PDF files from various locations to unified structure: literature/pdfs/{id}/main.pdf
"""

import os
import shutil
import sqlite3
from pathlib import Path
from typing import List, Tuple, Optional

# Migration mapping: (literature_id, source_path, target_filename)
MIGRATION_MAP = [
    # Literature 1-10 from old project
    (1, "/mnt/d/script/agent/literature_agent/literature/pdfs/s41586-021-03197-9.pdf", "main.pdf"),
    (2, "/mnt/d/script/agent/literature_agent/literature/pdfs/sciadv.adv8257.pdf", "main.pdf"),
    (3, "/mnt/d/script/agent/literature_agent/literature/pdfs/s41422-025-01135-2.pdf", "main.pdf"),
    (4, "/mnt/d/script/agent/literature_agent/literature/pdfs/science.abl4732.pdf", "main.pdf"),
    (5, "/mnt/d/script/agent/literature_agent/literature/pdfs/s41467-021-27147-1.pdf", "main.pdf"),
    (6, "/mnt/d/script/agent/literature_agent/literature/pdfs/s41467-024-52584-z.pdf", "main.pdf"),
    (7, "/mnt/d/script/agent/literature_agent/literature/pdfs/wang-et-al-2025-cryo-em-structures-reveal-the-acetylation-process-of-piccolo-nua4.pdf", "main.pdf"),
    (8, "/mnt/d/script/agent/literature_agent/literature/pdfs/s41586-024-07439-4.pdf", "main.pdf"),
    (9, "/mnt/d/script/agent/literature_agent/literature/pdfs/1-s2.0-S009286742200530X-main.pdf", "main.pdf"),
    (10, "/mnt/d/script/agent/literature_agent/literature/pdfs/PIIS0092867423008528.pdf", "main.pdf"),
    # Literature 11 from V2 project
    (11, "/mnt/d/script/agent/literature_agent-V2/literature/pdfs/s42004-025-01825-3_reference (1).pdf", "main.pdf"),
    # Literature 12 from V2-test project
    (12, "/mnt/d/script/agent/literature_agent-V2-test/literature/pdfs/PIIS0092867424007736.pdf", "main.pdf"),
]

# Base directory
BASE_DIR = Path(__file__).parent.absolute()
LITERATURE_PDFS_DIR = BASE_DIR / "literature" / "pdfs"
DB_PATH = BASE_DIR / "data" / "literature.db"


def ensure_dir(path: Path) -> None:
    """Ensure directory exists"""
    path.mkdir(parents=True, exist_ok=True)


def migrate_file(lit_id: int, source_path: str, target_filename: str) -> Tuple[bool, Optional[str]]:
    """
    Migrate a single file to the new structure

    Returns: (success, new_path or error_message)
    """
    source = Path(source_path)
    target_dir = LITERATURE_PDFS_DIR / str(lit_id)
    target = target_dir / target_filename

    # Check if source exists
    if not source.exists():
        return False, f"Source file not found: {source}"

    # Create target directory
    ensure_dir(target_dir)

    try:
        # Copy file (preserve original until verification is complete)
        shutil.copy2(str(source), str(target))
        return True, str(target)
    except Exception as e:
        return False, f"Copy failed: {e}"


def update_database_path(lit_id: int, new_path: str) -> bool:
    """Update database with new PDF path"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE literature_entries SET main_pdf_path = ? WHERE id = ?",
            (new_path, lit_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"  ❌ Database update failed for ID {lit_id}: {e}")
        return False


def get_uploads_file_for_lit_id(lit_id: int) -> Optional[Path]:
    """Find a file in uploads that belongs to a specific literature entry"""
    uploads_dir = BASE_DIR / "uploads"
    if not uploads_dir.exists():
        return None

    # Get filename from database
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT main_pdf_filename FROM literature_entries WHERE id = ?",
            (lit_id,)
        )
        result = cursor.fetchone()
        conn.close()

        if result and result[0]:
            filename = result[0]
            # Search in uploads directory
            for file in uploads_dir.iterdir():
                if file.name == filename or file.name.endswith(filename):
                    return file
                # Also check if filename contains the UUID pattern
                if filename in file.name:
                    return file
    except Exception as e:
        print(f"  ⚠️ Could not query database for ID {lit_id}: {e}")

    return None


def migrate_uploads_files():
    """Migrate files 14-17 from uploads directory"""
    print("\n=== Migrating files from uploads directory ===")

    # Get all entries with paths containing 'uploads'
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, main_pdf_path, main_pdf_filename FROM literature_entries WHERE main_pdf_path LIKE '%uploads%'"
        )
        entries = cursor.fetchall()
        conn.close()

        for lit_id, current_path, filename in entries:
            print(f"\nProcessing ID {lit_id}...")

            # Find the file
            source = get_uploads_file_for_lit_id(lit_id)
            if not source:
                print(f"  ⚠️ Could not find file for ID {lit_id}")
                continue

            # Migrate
            success, result = migrate_file(lit_id, str(source), "main.pdf")
            if success:
                # Update database
                if update_database_path(lit_id, result):
                    print(f"  ✅ Migrated: {source.name} -> {result}")
                else:
                    print(f"  ⚠️ File copied but database update failed")
            else:
                print(f"  ❌ Failed: {result}")

    except Exception as e:
        print(f"  ❌ Error migrating uploads files: {e}")


def main():
    """Main migration function"""
    print("=" * 60)
    print("PDF Migration Script - Phase 1")
    print("=" * 60)
    print(f"Target directory: {LITERATURE_PDFS_DIR}")
    print(f"Database: {DB_PATH}")
    print()

    # Verify database exists
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return

    success_count = 0
    failed_count = 0

    # Migrate files from external locations (1-12)
    print("=== Migrating files from external locations ===")
    for lit_id, source_path, target_filename in MIGRATION_MAP:
        print(f"\nProcessing ID {lit_id}...")
        success, result = migrate_file(lit_id, source_path, target_filename)

        if success:
            # Update database
            if update_database_path(lit_id, result):
                print(f"  ✅ Migrated: {Path(source_path).name} -> {result}")
                success_count += 1
            else:
                print(f"  ⚠️ File copied but database update failed")
                failed_count += 1
        else:
            print(f"  ❌ Failed: {result}")
            failed_count += 1

    # Migrate files from uploads (14-17)
    migrate_uploads_files()

    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")

    # Verify new structure
    print("\n=== New directory structure ===")
    for lit_id in range(1, 18):
        lit_dir = LITERATURE_PDFS_DIR / str(lit_id)
        if lit_dir.exists():
            files = list(lit_dir.iterdir())
            if files:
                print(f"  literature/pdfs/{lit_id}/: {len(files)} file(s)")


if __name__ == "__main__":
    main()
