"""Writes manifest.json, the list the mod reads: every picture with its SHA-256. Run it after changing any picture, from this folder:

    python tools/make_manifest.py
"""
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = {}
for folder in ("islands", "maps"):
    for name in sorted(os.listdir(os.path.join(ROOT, folder))):
        if not name.endswith(".png"):
            continue
        if not re.fullmatch(r"[a-z0-9_]+\.png", name):
            raise SystemExit("The mod only accepts small letters, digits and _ in a name: " + name)
        with open(os.path.join(ROOT, folder, name), "rb") as f:
            files[folder + "/" + name] = hashlib.sha256(f.read()).hexdigest()
with open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump({"files": files}, f, indent=1)
print(len(files), "pictures listed")
