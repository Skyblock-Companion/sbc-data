"""Builds the shared price file from Hypixel's public auctions, so each player's game does not have to read every page itself.

    python tools/build_prices.py <file to write>

The same rule as the mod's own scan (AuctionPrices.key): each kind of item has its own price, per piece for stacks, so a Sharpness V book is
not a Smite I book. Pets go by type, rarity and whether they are at max level. The few cheapest listings of each item are kept with their ids, so when one sells the mod moves to the next.
If the scan looks wrong, nothing is written and the job fails, and the last good file stays online.
"""
import base64
import concurrent.futures
import gzip
import io
import json
import re
import struct
import sys
import time
import urllib.request

URL = "https://api.hypixel.net/v2/skyblock/auctions?page="
HEADERS = {"User-Agent": "SkyBlockCompanion-data (price file for the mod)"}
MIN_BIN_AUCTIONS, MIN_ITEMS = 1000, 500
KEEP = 5
HIGH_LEVEL_PETS = {"GOLDEN_DRAGON", "JADE_DRAGON", "ROSE_DRAGON"}


def get(page):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL + str(page), headers=HEADERS), timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def nbt(data):
    """The compound in a gzipped NBT file."""
    s = io.BytesIO(gzip.decompress(data))

    def text():
        return s.read(struct.unpack(">H", s.read(2))[0]).decode("utf-8", "replace")

    def value(t):
        if t == 1: return struct.unpack(">b", s.read(1))[0]
        if t == 2: return struct.unpack(">h", s.read(2))[0]
        if t == 3: return struct.unpack(">i", s.read(4))[0]
        if t == 4: return struct.unpack(">q", s.read(8))[0]
        if t == 5: return struct.unpack(">f", s.read(4))[0]
        if t == 6: return struct.unpack(">d", s.read(8))[0]
        if t == 7: return s.read(struct.unpack(">i", s.read(4))[0])
        if t == 8: return text()
        if t == 9:
            kind = s.read(1)[0]
            return [value(kind) for _ in range(struct.unpack(">i", s.read(4))[0])]
        if t == 10:
            out = {}
            while True:
                kind = s.read(1)[0]
                if kind == 0:
                    return out
                name = text()
                out[name] = value(kind)
        if t == 11: return s.read(4 * struct.unpack(">i", s.read(4))[0]) and None
        if t == 12: return s.read(8 * struct.unpack(">i", s.read(4))[0]) and None
        raise ValueError(t)

    s.read(1)
    text()
    return value(10)


def single(tag):
    """The one name and value of a compound that must hold exactly one; None otherwise."""
    return next(iter(tag.items())) if len(tag) == 1 else None


def kind_of(item_id, extra):
    """The key of an item with kinds under one id. False when this id has no kinds; None when this one has no single price."""
    upper = lambda key: str(extra.get(key, "")).upper()
    if item_id == "ENCHANTED_BOOK":
        one = single(extra.get("enchantments", {}))
        return f"ENCHANTMENT_{one[0].upper()}_{one[1]}" if one else None
    if item_id in ("RUNE", "UNIQUE_RUNE"):
        one = single(extra.get("runes", {}))
        return f"{one[0].upper()}_RUNE;{one[1]}" if one else None
    if item_id == "ATTRIBUTE_SHARD":
        one = single(extra.get("attributes", {}))
        return f"ATTRIBUTE_SHARD_{one[0].upper()};{one[1]}" if one else None
    if item_id == "POTION":
        level = extra.get("potion_level", 0)
        name = str(extra.get("potion_name", "")).replace(" ", "_").upper()
        if name:
            return f"POTION_{name};{level}"
        if extra.get("potion"):
            return f"POTION_{upper('potion')};{level}"
        return f"POTION_{upper('potion_type')}" if extra.get("potion_type") else "WATER_BOTTLE"
    if item_id in ("PARTY_HAT_CRAB", "PARTY_HAT_CRAB_ANIMATED"):
        return f"PARTY_HAT_CRAB_{upper('party_hat_color')}" + ("_ANIMATED" if extra.get("party_hat_year") == 2022 else "")
    if item_id in ("BALLOON_HAT_2024", "BALLOON_HAT_2025"):
        return f"BALLOON_HAT_{extra.get('party_hat_year', 0)}_{upper('party_hat_color')}"
    if item_id == "CAKE_HAT_2026":
        return f"CAKE_HAT_2026_{upper('party_hat_color')}"
    if item_id == "PARTY_HAT_SLOTH":
        return f"PARTY_HAT_SLOTH_{upper('party_hat_emoji')}"
    if item_id == "ABICASE":
        return f"ABICASE_{upper('model')}"
    if item_id == "FACTION_RABBIT":
        return f"FACTION_RABBIT_{upper('faction_rabbit_id')}"
    if item_id == "NEW_YEAR_CAKE":
        return f"NEW_YEAR_CAKE_{extra.get('new_years_cake', 0)}"
    if item_id == "MIDAS_SWORD":
        return "MIDAS_SWORD_50M" if extra.get("winning_bid", 0) >= 50_000_000 else item_id
    if item_id == "MIDAS_STAFF":
        return "MIDAS_STAFF_100M" if extra.get("winning_bid", 0) >= 100_000_000 else item_id
    return False


def key_and_count(auction):
    """What the item is priced under, and how many are in the stack. None when it has no price key."""
    item = nbt(base64.b64decode(auction["item_bytes"]))["i"][0]
    extra = item.get("tag", {}).get("ExtraAttributes", {})
    item_id = extra.get("id", "")
    if not item_id:
        return None
    count = max(1, item.get("Count", 1))
    if "is_shiny" in extra:
        return "SHINY_" + item_id, count
    variant = kind_of(item_id, extra)
    if variant is not False:
        return (variant, count) if variant else None
    if item_id == "PET":
        info = json.loads(extra.get("petInfo", "{}"))
        kind, tier = info.get("type", ""), info.get("tier", "")
        level = re.match(r"\[Lvl (\d+)\]", re.sub("§.", "", auction.get("item_name", "")))
        if not kind or not level:
            return None
        top = 200 if kind in HIGH_LEVEL_PETS else 100
        return f"PET:{kind}:{tier}:{'MAX' if int(level.group(1)) >= top else 'LOW'}", 1
    return item_id, count


def main():
    first = get(0)
    pages = first["totalPages"]
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        results = [first] + list(pool.map(get, range(1, pages)))
    listings, seen, bad = {}, 0, 0
    for r in results:
        for a in r["auctions"]:
            if not a.get("bin"):
                continue
            try:
                found = key_and_count(a)
            except Exception:
                bad += 1
                continue
            if not found:
                continue
            seen += 1
            listings.setdefault(found[0], []).append((a["starting_bid"] / found[1], a["uuid"]))
    print(f"{pages} pages, {seen} BIN auctions, {len(listings)} items, {bad} unreadable")
    if seen < MIN_BIN_AUCTIONS or len(listings) < MIN_ITEMS:
        sys.exit("The scan looks wrong, not writing a price file")
    with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
        cheapest = {key: [list(x) for x in sorted(found)[:KEEP]] for key, found in listings.items()}
        json.dump({"updated": int(time.time() * 1000), "items": cheapest}, f, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    main()
