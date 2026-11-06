"""Copies the game data the mod needs into this repository, so the mod depends only on this repository.

    python tools/sync_data.py

The daily job runs this. Each source is checked before anything is replaced: every JSON file must parse, the files the mod cannot do
without must be there, and a source that suddenly lost more than half its files is refused. A refused source keeps its last good copy,
the others still update, and the job then fails so you get told.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = {
    "skyhanni": {"url": "https://github.com/SkyHanniStudios/SkyHanni-REPO.git", "folder": "constants", "to": "data/skyhanni/constants", "required": ["regexesModern.json", "Warps.json"]},
    "neu": {"url": "https://github.com/NotEnoughUpdates/NotEnoughUpdates-REPO.git", "folder": "constants", "to": "data/neu/constants", "required": ["reforges.json", "george.json"]},
    "repo": {"url": "https://github.com/SkyblockAPI/Repo.git", "folder": "cloudflare", "to": "data/repo", "required": ["shas.json", "1_21_5/items.min.json", "1_21_5/pets.min.json", "1_21_5/recipes.min.json", "1_21_5/mobs.min.json"],
             "only": ["shas.json", "1_21_5/items.min.json", "1_21_5/pets.min.json", "1_21_5/recipes.min.json", "1_21_5/mobs.min.json"]},
    "maps": {"url": "https://github.com/meowdding/meowdding-repo.git", "folder": "repo/skycubed/maps", "to": "data/maps", "required": ["main.json", "LICENSE.txt"]},
}


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def files_in(folder):
    out = []
    for d, _, names in os.walk(folder):
        for n in names:
            out.append(os.path.relpath(os.path.join(d, n), folder).replace("\\", "/"))
    return sorted(out)


def check(folder, source, have):
    missing = [r for r in source["required"] if not os.path.isfile(os.path.join(folder, r))]
    if missing:
        raise ValueError("missing " + ", ".join(missing))
    for f in files_in(folder):
        if f.endswith(".json"):
            with open(os.path.join(folder, f), encoding="utf-8") as h:
                json.load(h)
    count = len(files_in(folder))
    if count * 2 < have:
        raise ValueError(f"only {count} files, there were {have}")
    return count


def sync(name, source, work):
    clone = os.path.join(work, name)
    run("git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse", source["url"], clone)
    run("git", "sparse-checkout", "set", source["folder"], cwd=clone)
    fresh = os.path.join(clone, source["folder"].replace("/", os.sep))
    if "only" in source:
        picked = os.path.join(work, name + "_only")
        for f in source["only"]:
            os.makedirs(os.path.dirname(os.path.join(picked, f)), exist_ok=True)
            shutil.copy2(os.path.join(fresh, f), os.path.join(picked, f))
        fresh = picked
    to = os.path.join(ROOT, source["to"].replace("/", os.sep))
    have = len(files_in(to)) if os.path.isdir(to) else 0
    count = check(fresh, source, have)
    if os.path.isdir(to):
        shutil.rmtree(to)
    shutil.copytree(fresh, to, ignore=shutil.ignore_patterns(".git"))
    return count, run("git", "rev-parse", "HEAD", cwd=clone)


def sync_collections():
    """Hypixel's public collections list, which needs no key. It is checked like the others, and a bad answer keeps the last good copy."""
    url = "https://api.hypixel.net/v2/resources/skyblock/collections"
    request = urllib.request.Request(url, headers={"User-Agent": "SkyBlock-Companion-data"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        data = json.load(reply)
    if data.get("success") is not True:
        raise ValueError("Hypixel did not answer with success")
    collections = data["collections"]
    count = sum(len(c["items"]) for c in collections.values())
    if len(collections) < 5 or count < 50:
        raise ValueError(f"only {len(collections)} categories and {count} collections")
    for category in collections.values():
        for item in category["items"].values():
            if not item["name"] or not all("amountRequired" in tier for tier in item["tiers"]):
                raise ValueError("a collection without a name or an amount")
    to = os.path.join(ROOT, "data", "hypixel")
    os.makedirs(to, exist_ok=True)
    # no times in the file, so a day without changes publishes nothing
    with open(os.path.join(to, "collections.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"collections": collections}, f, indent=1, sort_keys=False)
        f.write("\n")
    return count


def main():
    status = {}
    path = os.path.join(ROOT, "data", "sources.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            status = json.load(f)
    failed = []
    with tempfile.TemporaryDirectory() as work:
        for name, source in SOURCES.items():
            try:
                count, commit = sync(name, source, work)
                status[name] = {"from": source["url"].removesuffix(".git"), "commit": commit}
                print(f"{name}: {count} files at {commit[:7]}")
            except Exception as e:
                detail = getattr(e, "stderr", "") or ""
                failed.append(name)
                print(f"{name}: REFUSED, keeping the last good copy: {e} {detail}")
    try:
        count = sync_collections()
        status["hypixel"] = {"from": "https://api.hypixel.net/v2/resources/skyblock/collections"}
        print(f"hypixel: {count} collections")
    except Exception as e:
        failed.append("hypixel")
        print(f"hypixel: REFUSED, keeping the last good copy: {e}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, indent=1, sort_keys=True)
        f.write("\n")
    if failed:
        sys.exit("Refused: " + ", ".join(failed))


if __name__ == "__main__":
    main()
