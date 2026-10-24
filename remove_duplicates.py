# -*- coding: utf-8 -*-
"""Utility to find and delete duplicate files in the project.
Keeps the first encountered file for each identical content hash and removes the rest.
Skips version‑control metadata and the script itself.
"""

import hashlib
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

hash_map = {}
duplicates = []

for root, dirs, files in os.walk(PROJECT_ROOT):
    # Skip .git directory if present
    if ".git" in dirs:
        dirs.remove('.git')
    for name in files:
        p = Path(root) / name
        # Skip this script itself
        if p.samefile(Path(__file__)):
            continue
        # Compute hash
        try:
            h = file_hash(p)
        except Exception as e:
            print(f"[WARN] Could not hash {p}: {e}")
            continue
        if h in hash_map:
            # Duplicate found – schedule for removal
            duplicates.append(p)
        else:
            hash_map[h] = p

if not duplicates:
    print("No duplicate files found.")
else:
    print(f"Found {len(duplicates)} duplicate files. Removing...")
    for dup in duplicates:
        try:
            dup.unlink()
            print(f"Deleted: {dup}")
        except Exception as e:
            print(f"[ERROR] Could not delete {dup}: {e}")

print("Duplicate removal completed.")
