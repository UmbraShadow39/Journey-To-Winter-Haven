"""
bestiary.py — Per-difficulty monster bestiary with tiered display.

Tracks every monster the player has encountered on each difficulty,
including Hardened, Veteran, and Elite variants. Saves to bestiary.json.

v0.8.06 rewrite:
  - Three separate bestiaries: one per difficulty (noob/warrior/champion).
  - FULL_ROSTER defines every monster; stats auto-scaled per difficulty.
  - Undiscovered monsters show as ???, discovered show full stat block.
  - Completion titles: Noob Bestiary Master (50 pts), Warrior Bestiary
    Master (100 pts), Champion Bestiary Master (150 pts).
  - Fixed: AP/DEF now recorded from max_ap/base_defence, not mid-fight.

Integration:
  - combat.py: call record_monster(enemy) after each fight.
  - score.py:  call get_bestiary_score_bonus() for flat title points.
  - titles.py: add bestiary master title keys + SCORE_BONUSES entries.
  - main menu: bestiary option calls show_bestiary().
"""

import json
import math
import os
import sys
from shared import WIDTH, wrap, space, continue_text, clear_screen


# ============================================================
# 📋 FULL ROSTER — master list of every monster in the game
# ============================================================
# Stats are BASE values (pre-difficulty, pre-level-scaling).
# The viewer calculates difficulty-scaled versions on the fly.

FULL_ROSTER = [
    # ── Tier 1 — Common ──────────────────────────────────────
    {
        "name": "Green Slime", "tier": 1, "is_boss": False,
        "hp": 10, "min_atk": 1, "max_atk": 2, "def": 0, "ap": 1, "xp": 5,
        "special": "Poison Spit", "drop": "Poison Sac (accessory)",
    },
    {
        "name": "Young Goblin", "tier": 1, "is_boss": False,
        "hp": 8, "min_atk": 1, "max_atk": 3, "def": 1, "ap": 1, "xp": 7,
        "special": "Cheap Shot", "drop": "Goblin Dagger (weapon)",
    },
    {
        "name": "Imp", "tier": 1, "is_boss": False,
        "hp": 9, "min_atk": 2, "max_atk": 4, "def": 0, "ap": 1, "xp": 7,
        "special": "Sneak Attack", "drop": "Imp Trident (weapon)",
    },
    {
        "name": "Brittle Skeleton", "tier": 1, "is_boss": False,
        "hp": 12, "min_atk": 2, "max_atk": 5, "def": 1, "ap": 1, "xp": 9,
        "special": "Rot Thrust", "drop": "Rusted Sword (weapon)",
    },
    {
        "name": "Wolf Pup", "tier": 1, "is_boss": False,
        "hp": 13, "min_atk": 3, "max_atk": 5, "def": 2, "ap": 2, "xp": 13,
        "special": "Wolf Pup Bite", "drop": "Wolf Pelt (armor)",
    },
    {
        "name": "Giant Diseased Rat", "tier": 1, "is_boss": False,
        "hp": 16, "min_atk": 4, "max_atk": 6, "def": 3, "ap": 2, "xp": 15,
        "special": "Plague Bite", "drop": "Rat Fang (accessory)",
        "difficulty": "noob",  # Noob-exclusive T1 alpha
    },

    # ── Tier 2 — Uncommon ─────────────────────────────────────
    {
        "name": "Red Slime", "tier": 2, "is_boss": False,
        "hp": 21, "min_atk": 3, "max_atk": 5, "def": 2, "ap": 3, "xp": 18,
        "special": "Fire Spit", "drop": "Fire Sac (accessory)",
    },
    {
        "name": "Noob Ghost", "tier": 2, "is_boss": False,
        "hp": 21, "min_atk": 4, "max_atk": 7, "def": 1, "ap": 3, "xp": 15,
        "special": "Life Leech", "drop": "Soul Pendant (accessory)",
    },
    {
        "name": "Goblin Archer", "tier": 2, "is_boss": False,
        "hp": 20, "min_atk": 4, "max_atk": 6, "def": 2, "ap": 3, "xp": 19,
        "special": "Paralyzing Shot", "drop": "Goblin Shortbow (weapon)",
    },
    {
        "name": "Javelina", "tier": 2, "is_boss": False,
        "hp": 23, "min_atk": 4, "max_atk": 7, "def": 3, "ap": 3, "xp": 20,
        "special": "Impact Bite", "drop": "Javelina Tusk (accessory)",
    },
    {
        "name": "Dire Wolf Pup", "tier": 2, "is_boss": False,
        "hp": 21, "min_atk": 5, "max_atk": 7, "def": 4, "ap": 3, "xp": 21,
        "special": "Devouring Bite", "drop": "Dire Wolf Pelt (armor)",
    },

    # ── Tier 3 — Dangerous ────────────────────────────────────
    {
        "name": "Wolf Pup Rider", "tier": 3, "is_boss": False,
        "hp": 31, "min_atk": 5, "max_atk": 9, "def": 4, "ap": 4, "xp": 28,
        "special": "Blinding Charge", "drop": "Rider's Armor (armor)",
    },
    {
        "name": "Hydra Hatchling", "tier": 3, "is_boss": False,
        "hp": 35, "min_atk": 5, "max_atk": 8, "def": 4, "ap": 4, "xp": 33,
        "special": "Acid Spit", "drop": "Acid Sac (accessory)",
    },
    {
        "name": "Flayed One", "tier": 3, "is_boss": False,
        "hp": 33, "min_atk": 6, "max_atk": 8, "def": 3, "ap": 4, "xp": 30,
        "special": "Psychic Shred", "drop": "Charged Jagged Rock (trinket)",
    },
    {
        "name": "Drowned One", "tier": 3, "is_boss": False,
        "hp": 37, "min_atk": 6, "max_atk": 9, "def": 4, "ap": 5, "xp": 36,
        "special": "Psychic Drown", "drop": "Waterlogged Stone (trinket)",
    },
    {
        "name": "Goblin Warrior", "tier": 3, "is_boss": False,
        "hp": 40, "min_atk": 5, "max_atk": 9, "def": 5, "ap": 5, "xp": 40,
        "special": "Savage Slash", "drop": "Goblin War Blade (weapon)",
    },

    # ── Tier 4 — Boss ─────────────────────────────────────────
    {
        "name": "Fallen Warrior", "tier": 4, "is_boss": True,
        "hp": 65, "min_atk": 7, "max_atk": 11, "def": 6, "ap": 5, "xp": 75,
        "special": "Defence Warp", "drop": "Weapon Core (weapon)",
    },

    # ── Tier 5 — Final Boss ───────────────────────────────────
    {
        "name": "Young Chimera", "tier": 5, "is_boss": True,
        "hp": 80, "min_atk": 14, "max_atk": 18, "def": 8, "ap": 99, "xp": 0,
        "special": "Chimera Dispatcher", "drop": "Chunk of Sol Metal (material)",
    },
    {
        "name": "Patronus", "tier": 5, "is_boss": True,
        "hp": 162, "min_atk": 7, "max_atk": 12, "def": 10, "ap": 7, "xp": 0,
        "special": "Multi-skill AI", "drop": "Chunk of Sol Metal (material)",
    },
]

# Quick lookup: lowercase name -> roster name
_NAME_MAP = {e["name"].lower(): e["name"] for e in FULL_ROSTER}


# ============================================================
# 🏷️ TIER & DIFFICULTY DISPLAY
# ============================================================

TIER_HEADERS = {
    1: ("⚔️  Tier 1 — Common",    "The arena's warm-up act."),
    2: ("⚔️  Tier 2 — Uncommon",  "Tougher beasts with real specials."),
    3: ("⚔️  Tier 3 — Dangerous", "Veteran killers. Come prepared."),
    4: ("👑  Tier 4 — Boss",       "The arena's final test."),
    5: ("💀  Tier 5 — Final Boss", "Legends. Path-dependent."),
}

DIFF_LABELS = {
    "noob":     "🛡️  Noob",
    "warrior":  "⚔️  Warrior",
    "champion": "👑  Champion",
}

# Multipliers matching combat.py — regular and boss use different tables.
DIFF_MONSTER_MULT = {"noob": 0.80, "warrior": 1.00, "champion": 1.20}
DIFF_BOSS_MULT    = {"noob": 0.80, "warrior": 1.20, "champion": 1.50}


def _scale_stats(entry, difficulty):
    """Return (hp, atk_str, def, ap) scaled for the given difficulty."""
    mult = DIFF_BOSS_MULT[difficulty] if entry["is_boss"] else DIFF_MONSTER_MULT[difficulty]
    hp   = max(1, round(entry["hp"] * mult))
    s_min = max(1, round(entry["min_atk"] * mult))
    s_max = max(s_min, round(entry["max_atk"] * mult))
    d     = max(1, round(entry["def"] * mult)) if entry["def"] > 0 else 0
    # AP and XP don't scale with difficulty
    ap    = entry["ap"]
    xp    = entry["xp"]
    return hp, f"{s_min}-{s_max}", d, ap, xp


# ============================================================
# 🏆 BESTIARY COMPLETION — titles & score
# ============================================================

BESTIARY_TITLES = {
    "noob":     "noob_bestiary_master",
    "warrior":  "warrior_bestiary_master",
    "champion": "champion_bestiary_master",
}

BESTIARY_SCORE_BONUS = {
    "noob_bestiary_master":     50,
    "warrior_bestiary_master":  100,
    "champion_bestiary_master": 150,
}


def _roster_for_difficulty(difficulty):
    """Return only FULL_ROSTER entries that can appear on this difficulty.
    Entries with no 'difficulty' key appear everywhere; entries with a
    specific difficulty only appear on that one."""
    return [
        e for e in FULL_ROSTER
        if e.get("difficulty") is None or e.get("difficulty") == difficulty
    ]


def is_bestiary_complete(difficulty):
    """True if every monster available on this difficulty has been encountered."""
    data = _load_bestiary()
    diff_data = data.get(difficulty, {})
    for entry in _roster_for_difficulty(difficulty):
        if entry["name"] not in diff_data:
            return False
    return True


def check_bestiary_completion(hero):
    """
    Check if the current difficulty's bestiary is complete and award the title.
    Call at end of each fight (after record_monster).
    Returns the title key if just completed, None otherwise.
    """
    main = sys.modules.get("__main__")
    diff = getattr(main, "DIFFICULTY", "warrior") if main else "warrior"

    title_key = BESTIARY_TITLES.get(diff)
    if not title_key:
        return None

    # Already have the title?
    if title_key in getattr(hero, "achievements", set()):
        return None

    if is_bestiary_complete(diff):
        if not hasattr(hero, "achievements"):
            hero.achievements = set()
        hero.achievements.add(title_key)

        label = {
            "noob_bestiary_master":     "Noob Bestiary Master",
            "warrior_bestiary_master":  "Warrior Bestiary Master",
            "champion_bestiary_master": "Champion Bestiary Master",
        }.get(title_key, title_key)
        bonus = BESTIARY_SCORE_BONUS.get(title_key, 0)

        print(f"\n🏆 BESTIARY COMPLETE!")
        print(f"   You've encountered every monster on {diff.title()} difficulty!")
        print(f"   Title earned: {label}  (+{bonus} score)")
        return title_key

    return None


def get_bestiary_score_bonus(hero):
    """
    Return total flat score bonus from bestiary completion titles.
    Called from score.py during show_run_score().
    """
    total = 0
    achievements = getattr(hero, "achievements", set())
    for title_key, bonus in BESTIARY_SCORE_BONUS.items():
        if title_key in achievements:
            total += bonus
    return total


# ============================================================
# 💾 PERSISTENCE — bestiary.json (per-difficulty)
# ============================================================
# Format:
# {
#     "noob": {
#         "Green Slime": {
#             "base": {"hp": 8, "atk": "1-2", "def": 0, "ap": 1, "xp": 5},
#             "variants": {"Hardened": {...}},
#             "times_defeated": 3,
#             "first_seen": "2026-08-18"
#         },
#         ...
#     },
#     "warrior": { ... },
#     "champion": { ... }
# }

BESTIARY_FILE = "bestiary.json"


def _load_bestiary():
    """Load bestiary from disk. Returns dict with difficulty keys."""
    if not os.path.exists(BESTIARY_FILE):
        return {}
    try:
        with open(BESTIARY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        # Migration: if the old format (flat, no difficulty keys), wrap it
        # under "warrior" so existing data isn't lost.
        if data and list(data.keys())[0] not in ("noob", "warrior", "champion"):
            return {"warrior": data}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def _save_bestiary(data):
    """Write bestiary to disk."""
    try:
        with open(BESTIARY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"⚠️  Could not save bestiary: {e}")


# ============================================================
# 📝 RECORDING — Called after each fight
# ============================================================

def _normalise_name(name):
    """Normalise monster name for lookup (handles 'red slime' vs 'Red Slime')."""
    return _NAME_MAP.get(name.lower(), name)


def record_monster(enemy):
    """
    Record a defeated monster in the bestiary under the current difficulty.
    Call from combat.py after each fight.

    Fixed v0.8.06: AP uses max_ap (not current ap after spending).
                   DEF uses base_defence (not mid-fight reduced value).
    """
    from datetime import datetime

    # Get current difficulty
    main = sys.modules.get("__main__")
    diff = getattr(main, "DIFFICULTY", "warrior") if main else "warrior"

    data  = _load_bestiary()
    today = datetime.now().strftime("%Y-%m-%d")

    base_name = _normalise_name(enemy.name)
    variant   = getattr(enemy, "variant_title", None) or ""
    tier      = getattr(enemy, "tier", 1)

    # Build stat snapshot — use MAX values, not mid-fight leftovers
    stats = {
        "hp":  int(getattr(enemy, "max_hp", enemy.hp)),
        "atk": f"{enemy.min_atk}-{enemy.max_atk}",
        "def": int(getattr(enemy, "base_defence", enemy.defence)),
        "ap":  int(getattr(enemy, "max_ap", enemy.ap)),
        "xp":  int(enemy.xp),
    }

    # Ensure difficulty bucket exists
    if diff not in data:
        data[diff] = {}

    diff_data = data[diff]

    # Create entry if new
    if base_name not in diff_data:
        diff_data[base_name] = {
            "base":           {},
            "variants":       {},
            "times_defeated": 0,
            "first_seen":     today,
            "tier":           tier,
        }

    entry = diff_data[base_name]
    entry["times_defeated"] += 1

    if "tier" not in entry:
        entry["tier"] = tier

    # File stats under base or variant
    if variant == "" or variant is None:
        entry["base"] = stats
    else:
        entry["variants"][variant] = stats
        if not entry["base"]:
            entry["base"] = {
                "hp": "?", "atk": "?",
                "def": "?", "ap": "?", "xp": "?",
            }

    _save_bestiary(data)


# ============================================================
# 📖 DISPLAY — Tiered Bestiary Viewer with Difficulty Tabs
# ============================================================

def _print_monster_card(entry_data, roster_entry, difficulty, discovered):
    """Print a single monster's bestiary card."""
    if not discovered:
        print(f"\n    🔒  ???")
        print(f"        {'─' * 30}")
        print(f"        HP: ???  ATK: ???  DEF: ???  AP: ???")
        print(f"        Special: ???")
        print(f"        Drop: ???")
        return

    name = roster_entry["name"]
    hp, atk, def_, ap, xp = _scale_stats(roster_entry, difficulty)
    defeats    = entry_data.get("times_defeated", 0)
    first_seen = entry_data.get("first_seen", "?")

    # AP display — Chimera's 99 shows as ∞
    ap_str = "∞" if ap >= 99 else str(ap)

    print(f"\n    📖  {name}")
    print(f"        {'─' * 30}")
    print(f"        HP: {hp}  ATK: {atk}  DEF: {def_}  AP: {ap_str}  XP: {xp}")
    print(f"        Special: {roster_entry['special']}")
    print(f"        Drop: {roster_entry['drop']}")
    print(f"        Defeated: {defeats}x  |  First seen: {first_seen}")

    # Show variant stat blocks if encountered
    variants = entry_data.get("variants", {})
    for v_name in ["Hardened", "Veteran", "Elite"]:
        if v_name in variants:
            v = variants[v_name]
            print(f"        ⚔️  {v_name}: HP: {v['hp']}  ATK: {v['atk']}  "
                  f"DEF: {v['def']}  AP: {v['ap']}  XP: {v['xp']}")


def show_bestiary():
    """
    Display the bestiary with difficulty tabs and tiered monster pages.
    Player picks a difficulty to view, then pages through tiers.
    """
    data = _load_bestiary()
    difficulties = ["noob", "warrior", "champion"]
    diff_index = 1  # default to warrior

    while True:
        # ---- Difficulty selector ----
        current_diff = difficulties[diff_index]
        diff_data = data.get(current_diff, {})

        # Build lookup for this difficulty
        save_lookup = {}
        for saved_name, saved_entry in diff_data.items():
            normed = _normalise_name(saved_name)
            save_lookup[normed] = saved_entry

        # Filter roster to only monsters available on this difficulty
        diff_roster = _roster_for_difficulty(current_diff)
        total_monsters = len(diff_roster)
        discovered = sum(1 for e in diff_roster if e["name"] in save_lookup)

        # Group roster by tier
        by_tier = {}
        for entry in diff_roster:
            by_tier.setdefault(entry["tier"], []).append(entry)

        tiers = sorted(by_tier.keys())
        page = 0

        while True:
            tier = tiers[page]
            tier_monsters = by_tier[tier]
            tier_header, tier_desc = TIER_HEADERS.get(tier, (f"Tier {tier}", ""))

            tier_discovered = sum(
                1 for m in tier_monsters if m["name"] in save_lookup
            )

            clear_screen()
            print()
            print("═" * WIDTH)
            print("📖 BESTIARY".center(WIDTH))
            print("═" * WIDTH)

            # Difficulty tabs
            tabs = []
            for i, d in enumerate(difficulties):
                label = DIFF_LABELS[d]
                if i == diff_index:
                    tabs.append(f"[{label}]")
                else:
                    tabs.append(f" {label} ")
            print("  " + "  ".join(tabs))

            # Completion status
            complete_str = " ✅ COMPLETE!" if discovered == total_monsters else ""
            print(f"  Discovered: {discovered}/{total_monsters}{complete_str}")
            print()
            print(f"  {tier_header}  ({tier_discovered}/{len(tier_monsters)})")
            if tier_desc:
                print(f"  {tier_desc}")
            print(f"  {'━' * (WIDTH - 4)}")

            # Print each monster in this tier
            for roster_entry in tier_monsters:
                name = roster_entry["name"]
                is_disc = name in save_lookup
                edata = save_lookup.get(name, {})
                _print_monster_card(edata, roster_entry, current_diff, is_disc)

            # Navigation
            print()
            print("═" * WIDTH)
            nav = []
            if page > 0:
                nav.append("[P] Prev tier")
            if page < len(tiers) - 1:
                nav.append("[N] Next tier")
            nav.append("[D] Switch difficulty")
            nav.append("[Q] Back")
            print("  " + "  |  ".join(nav))

            choice = input("  > ").strip().lower()
            if choice in ("n", "next") and page < len(tiers) - 1:
                page += 1
            elif choice in ("p", "prev") and page > 0:
                page -= 1
            elif choice in ("d", "diff"):
                diff_index = (diff_index + 1) % len(difficulties)
                break  # break inner loop to refresh with new difficulty
            elif choice in ("q", "quit", "b", "back", ""):
                return


# ============================================================
# 🎁 MAIN MENU HELPERS
# ============================================================

def bestiary_count(difficulty=None):
    """Return how many unique monsters have been recorded on a difficulty."""
    if difficulty is None:
        main = sys.modules.get("__main__")
        difficulty = getattr(main, "DIFFICULTY", "warrior") if main else "warrior"
    data = _load_bestiary()
    return len(data.get(difficulty, {}))


def bestiary_total(difficulty=None):
    """Return total number of monsters available on a difficulty."""
    if difficulty is None:
        main = sys.modules.get("__main__")
        difficulty = getattr(main, "DIFFICULTY", "warrior") if main else "warrior"
    return len(_roster_for_difficulty(difficulty))


def has_bestiary_entries(difficulty=None):
    """True if the player has encountered at least one monster on this difficulty."""
    return bestiary_count(difficulty) > 0
