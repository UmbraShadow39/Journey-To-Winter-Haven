"""
collectibles.py — Seasonal collectibles, themed gear, event monsters, and bosses.

Created: v0.08 (August 2026)

Contains:
  * Seasonal detection — checks the real-world month to unlock content
  * Persistence — seasonal_data.json tracks unlocked collectibles across runs
  * August:   Birthday Cake 🎂 (consumable — full HP/AP + Sugar Rush ATK buff)
  * March:    Tome of Knowledge 📖 (consumable — ranks up one learned skill by 1)
  * October:  Haunted Armor 🎃 (wearable — fear-proc seasonal armor)
  * October:  Headless Horseman 🐴 (Tier 4 tournament boss)
  * December: Winter Solstice / Krampusnacht event 🎄
              - Elf on a Shelf (Tier 1) — Tattle debuff
              - Mutated Gingerbread Man (Tier 2) — Sugar Coat self-heal
              - Killer Frosty (Tier 3) — Blizzard Breath AP drain
              - Krampus (Tier 4) — Chains of Punishment multi-hit + stun

Integration points:
  - story.py:    grant_seasonal_starting_item() replaces hardcoded tonic grant;
                 elwyn_bookshelf_room() adds March bonus scene after tonic
  - hero.py:     add "birthday_cake" and "tome_of_knowledge" to hero.potions dict
  - combat.py:   add use_potion branches, tick_sugar_rush, check_fear_aura,
                 dread_charge_tick, blizzard_slow tick, krampus_rage tick,
                 roll_seasonal_collectable/equipment after loot
  - score.py:    get_seasonal_score_bonus() adds to multiplier stack
  - monsters.py: call inject_seasonal_monsters() after MONSTER_TYPES/TIER4_BOSSES
  - shared.py:   add seasonal special moves to SPECIAL_MOVE_NAMES dict
  - equipment.py: import HAUNTED_ARMOR for loot tables (October only)

Imports from shared.py to stay consistent with the existing module pattern.
"""

import random
import math
import json
import os
from datetime import datetime

from shared import (
    Monster, Equipment,
    wrap, space, clear_screen, continue_text, show_health,
    lvl_bonus, monster_math_breakdown, monster_deal_damage,
    WIDTH,
)
from combat_log import COMBAT_LOG, log



# ============================================================
# 🗓️ SEASONAL DETECTION
# ============================================================
# Checks the player's system clock to determine which seasonal
# content is available. Each season has an "active month" when
# its collectibles can drop and its monsters appear. Outside
# that month, the content exists in code but won't appear.
#
# NOTE: This is local time — no server sync. Players who change
# their system clock can access off-season content. That's fine;
# it's a single-player game and the fun of discovery matters
# more than enforcement.

def current_month():
    """Return the current month as an integer (1-12)."""
    return datetime.now().month

def is_august():
    """Birthday month — Nathan's birthday! 🎂"""
    return current_month() == 8

def is_march():
    """Birthday month — wife's birthday! 📖"""
    return current_month() == 3

def is_october():
    """Halloween season — spooky content! 🎃"""
    return current_month() == 10

def is_december():
    """Winter Solstice / Krampusnacht — holiday horrors! 🎄"""
    return current_month() == 12

def get_active_seasons():
    """
    Returns a list of currently active season tags.
    Used by loot tables, shops, and monster pools to filter availability.
    """
    active = []
    if is_august():
        active.append("august_birthday")
    if is_march():
        active.append("march_birthday")
    if is_october():
        active.append("halloween")
    if is_december():
        active.append("winter_solstice")
    return active

def is_season_active(season_tag):
    """Check if a specific season tag is currently active."""
    return season_tag in get_active_seasons()


# ============================================================
# 💾 SEASONAL PERSISTENCE — seasonal_data.json
# ============================================================
# Tracks which seasonal collectibles the player has found across
# runs so they can see their collection even when a season ends.
# Follows the same pattern as scores.json in leaderboard.py.
#
# File format:
# {
#     "discovered": {
#         "birthday_cake": {"first_found": "2026-08-11", "times_found": 3},
#         "haunted_armor": {"first_found": "2026-10-15", "times_found": 1},
#         ...
#     },
#     "bestiary": {
#         "Headless Horseman": {"first_seen": "2026-10-20", "times_defeated": 2},
#         "Elf on a Shelf":    {"first_seen": "2026-12-01", "times_defeated": 5},
#         ...
#     }
# }

SEASONAL_FILE = "seasonal_data.json"


def _load_seasonal_data():
    """Load the seasonal persistence file. Returns empty structure if missing."""
    if not os.path.exists(SEASONAL_FILE):
        return {"discovered": {}, "bestiary": {}}
    try:
        with open(SEASONAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"discovered": {}, "bestiary": {}}
        # Ensure both keys exist
        data.setdefault("discovered", {})
        data.setdefault("bestiary", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"discovered": {}, "bestiary": {}}


def _save_seasonal_data(data):
    """Write the seasonal persistence file."""
    try:
        with open(SEASONAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"⚠️  Could not save seasonal data: {e}")


def record_collectable_found(key):
    """
    Record that the player found a seasonal collectable.
    Called when a seasonal item drops or seasonal gear is looted.
    """
    data = _load_seasonal_data()
    today = datetime.now().strftime("%Y-%m-%d")

    if key in data["discovered"]:
        data["discovered"][key]["times_found"] += 1
    else:
        data["discovered"][key] = {
            "first_found": today,
            "times_found": 1,
        }
    _save_seasonal_data(data)


def record_seasonal_monster_defeated(monster_name):
    """
    Record that the player defeated a seasonal monster.
    Called after combat ends with a seasonal monster.
    """
    data = _load_seasonal_data()
    today = datetime.now().strftime("%Y-%m-%d")

    if monster_name in data["bestiary"]:
        data["bestiary"][monster_name]["times_defeated"] += 1
    else:
        data["bestiary"][monster_name] = {
            "first_seen": today,
            "times_defeated": 1,
        }
    _save_seasonal_data(data)


def show_seasonal_collection():
    """
    Display the player's seasonal collection — everything they've
    found across all runs, even out of season. Call from a menu option.
    """
    data = _load_seasonal_data()

    print("\n" + "=" * WIDTH)
    print("🗓️  SEASONAL COLLECTION".center(WIDTH))
    print("=" * WIDTH)

    # Active seasons
    active = get_active_seasons()
    if active:
        tags = ", ".join(s.replace("_", " ").title() for s in active)
        print(f"\n  Currently active: {tags}")
    else:
        print("\n  No seasonal events active right now.")

    # Discovered items
    discovered = data.get("discovered", {})
    if discovered:
        print(f"\n  📦 Collectibles Found ({len(discovered)}):")
        for key, info in discovered.items():
            name = key.replace("_", " ").title()
            print(f"     • {name} — first found {info['first_found']}, "
                  f"found {info['times_found']}x total")
    else:
        print("\n  📦 No collectibles found yet. Play during seasonal events!")

    # Seasonal bestiary
    bestiary = data.get("bestiary", {})
    if bestiary:
        print(f"\n  📖 Seasonal Bestiary ({len(bestiary)}):")
        for name, info in bestiary.items():
            print(f"     • {name} — first seen {info['first_seen']}, "
                  f"defeated {info['times_defeated']}x")
    else:
        print("\n  📖 No seasonal monsters encountered yet.")

    print("\n" + "=" * WIDTH)
    continue_text()


# ============================================================
# 🎂 AUGUST — BIRTHDAY CAKE
# ============================================================
# In August, Elwyn gives the hero a Birthday Cake INSTEAD of the
# Frostpine Tonic. The cake is the seasonal replacement for the
# tonic at the same story beat — same slot, different item.
#
# When used: Full HP restore + Full AP restore + Sugar Rush
# (temporary +2 ATK for 3 turns) + permanent +0.10 score multiplier.
#
# The +0.10 score multiplier is a birthday gift — a small, permanent
# bump to the run's final score. Stacks with quick-kill bonus and
# Nob's bet in the same additive multiplier line.
#
# Potion key: "birthday_cake"
# Add to hero.potions dict in hero.py:
#     "birthday_cake": 0,    # 🎂 August seasonal — replaces Frostpine in Aug

BIRTHDAY_CAKE = {
    "key":         "birthday_cake",
    "name":        "Birthday Cake",
    "icon":        "🎂",
    "description": "A beautifully frosted cake that appeared in your pack. "
                   "Eating it fills you with celebration and warmth.",
    "season":      "august_birthday",
    "effect":      "Full HP + Full AP restore. Sugar Rush (+20% ATK, min +2, 3 turns). "
                   "Permanent +0.10 score multiplier.",
    "in_combat":   True,
    "out_combat":  True,
    "drop_chance": 0.0,       # NOT a random drop — given by Elwyn in August
    "max_stack":   1,          # One per run, replaces the tonic
}

SUGAR_RUSH_ATK_PCT   = 0.20   # 20% ATK boost
SUGAR_RUSH_ATK_FLOOR = 2      # minimum +2 even at low levels
SUGAR_RUSH_TURNS     = 3
CAKE_SCORE_BONUS     = 0.10   # permanent +0.10 to run score multiplier
CAKE_SAVED_BONUS     = 50    # +50 flat score if you hold the cake all run


def grant_seasonal_starting_item(warrior):
    """
    Called from story.py in Elwyn's sendoff scene INSTEAD of the
    hardcoded Frostpine Tonic grant. Checks the month and gives
    the appropriate item.

    - August: Birthday Cake (replaces Frostpine Tonic)
    - March:  Tome of Knowledge (replaces Frostpine Tonic)
    - All other months: Frostpine Tonic (default behavior)

    Usage in story.py:
        from collectibles import grant_seasonal_starting_item
        grant_seasonal_starting_item(warrior)
    """
    warrior.potions["heal"] = 0   # remove basic heal in all cases

    if is_august():
        warrior.potions["birthday_cake"] = 1
        print(wrap(
            "Elwyn pauses at the gate. Instead of her usual flask, she holds "
            "out something wrapped in cloth. You unwrap it — a small frosted "
            "cake, still warm.",
            WIDTH
        ))
        space()
        print(wrap(
            "\"Happy birthday,\" she says softly. \"I know the timing is "
            "terrible. But your father always said a warrior fights best "
            "on a full stomach.\"",
            WIDTH
        ))
        space()
        print(wrap(
            "🎂 Birthday Cake added to your inventory. "
            "(Full HP + Full AP restore, Sugar Rush +20% ATK for 3 turns, "
            "+0.10 score multiplier. One use only.)",
            WIDTH
        ))
        print(wrap(
            "(It replaces the Frostpine Tonic she'd normally give you.)",
            WIDTH
        ))
        space()

        record_collectable_found("birthday_cake")
    
    elif is_march():
        warrior.potions["book_of_lost_secrets"] = 1
        print(wrap(
            "Elwyn pauses at the gate. Instead of her usual flask, she holds "
            "out a leather-bound book, its cover etched with a single rune "
            "that shifts as you watch.",
            WIDTH
        ))
        space()
        print(wrap(
            "\"Happy birthday,\" she says with a knowing smile. \"This one's "
            "been waiting for the right reader. The tonic can wait — knowledge "
            "is a far better gift.\"",
            WIDTH
        ))
        space()
        print(wrap(
            "📖 Book of Lost Secrets added to your inventory. "
            "(Learn any skill for free, or rank up a skill you already know. "
            "Use between battles.)",
            WIDTH
        ))
        print(wrap(
            "(It replaces the Frostpine Tonic she'd normally give you.)",
            WIDTH
        ))
        space()

        record_collectable_found("book_of_lost_secrets")
    
    
    
    else:
        # Default: Frostpine Tonic (original behavior)
        warrior.potions["frostpine_tonic"] = 1
        print(wrap(
            "✨ Elwyn's Frostpine Tonic added to your inventory. "
            "(Restores 40% HP, clears all status effects, and restores 2 AP. "
            "One use only.)",
            WIDTH
        ))
        print(wrap(
            "(It replaces the basic heal flask you'd packed for the trip.)",
            WIDTH
        ))
        space()

        # Halloween starting candy — a little treat to kick off October
    if is_october():
        warrior.halloween_candy += 1
        print(wrap(
            "🍬 A piece of candy tumbles from your pack — someone must "
            "have slipped it in. (+1 candy)",
            WIDTH
        ))
        space()


def apply_birthday_cake(hero, in_combat=False):
    """
    Consume a Birthday Cake. Full HP + AP restore, plus a
    temporary Sugar Rush ATK buff, plus a permanent +0.10
    score multiplier for the run.
    Returns True if consumed, False if cancelled/refunded.
    """
    print(f"\n🎂 You pull out the Birthday Cake and take a huge bite!")
    print(f"   Frosting, layers, pure joy — it's your day!")
    print()

    old_hp = hero.hp
    hero.hp = hero.max_hp
    print(f"   ❤️  HP fully restored! ({old_hp} → {hero.max_hp}/{hero.max_hp})")

    old_ap = hero.ap
    hero.ap = hero.max_ap
    print(f"   ⚡ AP fully restored! ({old_ap} → {hero.max_ap}/{hero.max_ap})")

    hero.sugar_rush_turns = SUGAR_RUSH_TURNS

    # Calculate 20% of current ATK range, minimum +2
    min_boost = max(SUGAR_RUSH_ATK_FLOOR, int(hero.min_atk * SUGAR_RUSH_ATK_PCT))
    max_boost = max(SUGAR_RUSH_ATK_FLOOR, int(hero.max_atk * SUGAR_RUSH_ATK_PCT))
    hero.sugar_rush_atk_min = min_boost
    hero.sugar_rush_atk_max = max_boost
    hero.min_atk += min_boost
    hero.max_atk += max_boost

    print(f"\n   🍬 SUGAR RUSH! +{min_boost}/{max_boost} ATK for {SUGAR_RUSH_TURNS} turns!")
    print(f"      ATK is now {hero.min_atk}-{hero.max_atk}")

    continue_text()
    space()
    return True


def tick_sugar_rush(hero):
    """
    Call at the END of the hero's turn to count down Sugar Rush.
    When it expires, remove the ATK bonus (which was calculated
    as 20% of ATK at time of use, minimum +2).
    """
    if not hasattr(hero, "sugar_rush_turns") or hero.sugar_rush_turns <= 0:
        return

    hero.sugar_rush_turns -= 1

    if hero.sugar_rush_turns <= 0:
        min_bonus = getattr(hero, "sugar_rush_atk_min", SUGAR_RUSH_ATK_FLOOR)
        max_bonus = getattr(hero, "sugar_rush_atk_max", SUGAR_RUSH_ATK_FLOOR)
        hero.min_atk -= min_bonus
        hero.max_atk -= max_bonus
        hero.sugar_rush_atk_min = 0
        hero.sugar_rush_atk_max = 0
        print(f"\n   🍬 Sugar Rush fades... ATK returns to {hero.min_atk}-{hero.max_atk}")
    else:
        print(f"\n   🍬 Sugar Rush: {hero.sugar_rush_turns} turn(s) remaining")


# ============================================================
# 📖 MARCH — BOOK OF LOST SECRETS
# ============================================================
# A seasonal consumable given by Elwyn in March (replaces tonic).
# Powerful and rare — lets you learn ANY skill or rank up one
# you already have, your choice. No level requirement, no SP cost.
#
# Future plan: these will also be found on the world map as rare
# loot — powerful but scarce. For now, March-only via Elwyn.
#
# Potion key: "book_of_lost_secrets"
# Add to hero.potions dict in hero.py:
#     "book_of_lost_secrets": 0,  # 📖 March seasonal — free skill learn/rank up

BOOK_OF_LOST_SECRETS = {
    "key":         "book_of_lost_secrets",
    "name":        "Book of Lost Secrets",
    "icon":        "📖",
    "description": "A leather-bound book with a shifting rune on the cover. "
                   "Its pages reveal forgotten techniques — skills lost to time.",
    "season":      "march_birthday",
    "effect":      "Learn any skill for free, or rank up a skill you already know.",
    "in_combat":   False,
    "out_combat":  True,
    "drop_chance": 0.0,       # Given by Elwyn in March
    "max_stack":   1,
}


def apply_book_of_lost_secrets(hero):
    """
    Consume a Book of Lost Secrets. Player chooses ANY skill in the
    game to either learn (0→1) or rank up (+1). No level requirement,
    no SP cost. Out-of-combat only.

    Returns True if consumed, False if cancelled/refunded.
    """
    from hero import SKILL_DEFS

    # Build list of all skills that can be learned or ranked up
    available = []
    for key, data in SKILL_DEFS.items():
        rank     = hero.skill_ranks.get(key, 0)
        max_rank = data["max_rank"]
        if rank >= max_rank:
            continue    # already maxed — nothing to do
        available.append(key)

    if not available:
        hero.potions["book_of_lost_secrets"] += 1
        print("\n📖 You open the Book of Lost Secrets, but the pages are blank —")
        print("   every skill is already mastered. There's nothing left to learn.")
        print("   You close the book. Perhaps someone else will need it someday.")
        continue_text()
        space()
        return False

    print("\n📖 You open the Book of Lost Secrets. The shifting rune on the")
    print("   cover burns bright, and forgotten techniques bloom across the")
    print("   pages — skills lost to time, waiting to be rediscovered.")
    print("   Which secret do you study?\n")

    for i, key in enumerate(available, start=1):
        name     = SKILL_DEFS[key]["name"]
        rank     = hero.skill_ranks.get(key, 0)
        max_rank = SKILL_DEFS[key]["max_rank"]
        if rank == 0:
            # Unlearned — this would be learning it fresh
            desc = SKILL_DEFS[key]["rank_descs"].get(1, "")
            print(f"  {i}) ✨ LEARN: {name}  (New! → Rank 1 / {max_rank})")
            if desc:
                print(f"       {desc}")
        else:
            # Already learned — rank it up
            print(f"  {i}) ⬆️  RANK UP: {name}  (Rank {rank} → {rank + 1} / {max_rank})")
    print(f"  {len(available) + 1}) Close the book (don't read)")

    pick = input("\nChoose: ").strip()
    if pick == str(len(available) + 1) or not pick.isdigit():
        hero.potions["book_of_lost_secrets"] += 1
        print("\n📖 You close the Book. Its secrets will keep.")
        continue_text()
        space()
        return False

    idx = int(pick) - 1
    if idx < 0 or idx >= len(available):
        hero.potions["book_of_lost_secrets"] += 1
        print("\n📖 The pages flutter shut. Try again later.")
        continue_text()
        space()
        return False

    chosen_key = available[idx]
    old_rank   = hero.skill_ranks.get(chosen_key, 0)
    hero.skill_ranks[chosen_key] = old_rank + 1
    new_rank   = hero.skill_ranks[chosen_key]
    skill_name = SKILL_DEFS[chosen_key]["name"]

    # Make sure the skill is in the hero's active skill set
    hero.skills.add(chosen_key)

    if old_rank == 0:
        print(f"\n📖 Lost knowledge floods into your mind...")
        print(f"   ✨ You learned {skill_name}! (Rank 1)")
        print(f"   The book crumbles to dust, its secret passed on.")
    else:
        print(f"\n📖 The Book's wisdom deepens your understanding...")
        print(f"   ⬆️  {skill_name} advanced to Rank {new_rank}!")
        print(f"   The book crumbles to dust, its purpose fulfilled.")

    continue_text()
    space()
    return True

def award_halloween_candy(warrior, enemy):
    """Award candy after defeating a Halloween monster."""
    if enemy.name not in HALLOWEEN_DROPS:
        return 0
    tier = getattr(enemy, "tier", 1)
    level = getattr(enemy, "level", 1)
    candy = tier + (level - 1)
    warrior.halloween_candy += candy
    return candy
# ============================================================
# 🎃 OCTOBER — HALLOWEEN EVENT
# ============================================================
# Full seasonal event with 4 monsters (one per tier), unique loot
# drops from each, and a 4-piece Halloween Warrior set bonus.
#
# Monsters:
#   T1: Giant Animated Jack O'Lantern — drops Enchanted Seed Launcher (accessory)
#   T2: The Trickster (Sam-inspired) — drops Sharpened Sucker (accessory)
#   T3: Female Werewolf — drops Werewolf Pelt → crafted into Werewolf Cloak
#   T4: Headless Horseman — drops Jack O'Lantern Head (helm)
#
# Halloween Warrior Set (4 pieces — Candle, Sucker, Cloak, Head):
#   SET BONUS — DREAD AURA:
#     Enemy loses their FIRST turn automatically (guaranteed fear).
#     Every subsequent turn, 25% chance the enemy loses their turn.
#
# Loot drops are Equipment instances with the "halloween" set tag.
# The set bonus follows the same pattern as Wolf-Hide/Dire Wolf:
#   - halloween_set_active_pieces() counts equipped pieces
#   - apply_halloween_set_bonus() manages stat changes
#   - dread_aura_active() returns True if full 4-piece is worn
#   - check_dread_aura() handles the in-combat fear proc

# ── Halloween Loot Drops ──

# Enchanted Seed Launcher — rarity-scaled passive proc weapon/accessory.
# The seed mechanic mirrors the monster's Exploding Pumpkin Seeds:
# on proc, rolls a cascade of seeds that deal TRUE damage (ignores DEF).
# Rarity controls min/max seeds and damage per seed.
#
# Rarity table:
#   Poor:       1-2 seeds, 1-2 dmg/seed  (total 1-4)
#   Normal:     1-3 seeds, 1-2 dmg/seed  (total 1-6)
#   Uncommon:   1-3 seeds, 1-3 dmg/seed  (total 1-9)
#   Rare:       2-4 seeds, 2-3 dmg/seed  (total 4-12)
#   Epic:       2-5 seeds, 1-4 dmg/seed  (total 2-20)
#   Legendary:  3-5 seeds, 2-4 dmg/seed  (total 6-20)
#   Mythril:    4-6 seeds, 3-5 dmg/seed  (total 12-30)
#
# Proc chance: 33% per turn (flat across all rarities).
# Rarity is determined by roll_rarity() / difficulty gating as usual.

SEED_LAUNCHER_STATS = {
    "poor":      {"min_seeds": 1, "max_seeds": 2, "min_dmg": 1, "max_dmg": 2},
    "normal":    {"min_seeds": 1, "max_seeds": 3, "min_dmg": 1, "max_dmg": 2},
    "uncommon":  {"min_seeds": 1, "max_seeds": 3, "min_dmg": 1, "max_dmg": 3},
    "rare":      {"min_seeds": 2, "max_seeds": 4, "min_dmg": 2, "max_dmg": 3},
    "epic":      {"min_seeds": 2, "max_seeds": 5, "min_dmg": 1, "max_dmg": 4},
    "legendary": {"min_seeds": 3, "max_seeds": 5, "min_dmg": 2, "max_dmg": 4},
    "mythril":   {"min_seeds": 4, "max_seeds": 6, "min_dmg": 3, "max_dmg": 5},
}

SEED_LAUNCHER_PROC_CHANCE = 0.33  # 33% chance per turn

HALLOWEEN_SEED_LAUNCHER = Equipment(
    name="Enchanted Seed Launcher",
    slot="weapon",
    rarity="uncommon",
    tier=1,
    atk_min=0,
    atk_max=0,
    defence=0,
    max_hp=0,
    flavour="A hollowed pumpkin husk packed with enchanted seeds. "
            "In combat, seeds launch at your enemy and explode on "
            "impact. Higher-quality launchers hold more seeds and "
            "pack a bigger punch.",
)

# Sharpened Sucker — rarity-scaled T2 Halloween weapon.
# Three-tier unlock system:
#   Poor/Normal:        damage only (basic shiv)
#   Uncommon/Rare:      + bleed (1 turn)
#   Epic/Legendary:     + vampiric heal (% of bleed damage heals player)
#   Mythril:            + multi-strike (1-3 attacks per swing)
# Bleed lasts 1 turn (unlike Goblin War Blade which scales turns).
# Weaker base ATK than War Blade — value comes from bleed + heal + dual wield.
SHARPENED_SUCKER_STATS = {
    "poor":      {"atk_min": 2, "atk_max": 2, "bleed_turns": 0, "bleed_dmg": 0, "heal_pct": 0.0,  "multi_min": 1, "multi_max": 1},
    "normal":    {"atk_min": 3, "atk_max": 3, "bleed_turns": 0, "bleed_dmg": 0, "heal_pct": 0.0,  "multi_min": 1, "multi_max": 1},
    "uncommon":  {"atk_min": 3, "atk_max": 3, "bleed_turns": 1, "bleed_dmg": 1, "heal_pct": 0.0,  "multi_min": 1, "multi_max": 1},
    "rare":      {"atk_min": 4, "atk_max": 4, "bleed_turns": 1, "bleed_dmg": 2, "heal_pct": 0.0,  "multi_min": 1, "multi_max": 1},
    "epic":      {"atk_min": 5, "atk_max": 5, "bleed_turns": 1, "bleed_dmg": 3, "heal_pct": 0.25, "multi_min": 1, "multi_max": 1},
    "legendary": {"atk_min": 6, "atk_max": 6, "bleed_turns": 1, "bleed_dmg": 4, "heal_pct": 0.50, "multi_min": 1, "multi_max": 1},
    "mythril":   {"atk_min": 7, "atk_max": 7, "bleed_turns": 1, "bleed_dmg": 5, "heal_pct": 0.50, "multi_min": 1, "multi_max": 3},
}

SHARPENED_SUCKER = Equipment(
    name="Sharpened Sucker",
    slot="weapon",
    rarity="uncommon",
    tier=2,
    atk_min=3,
    atk_max=3,
    defence=0,
    max_hp=0,
    bleed_turns=1,
    bleed_dmg_min=1,
    bleed_dmg_max=1,
    flavour="A lollipop honed to a razor point. The enchanted sugar "
            "coating hides a wicked edge that draws blood on contact. "
            "Higher-quality versions absorb the blood and heal the wielder.",
)

WEREWOLF_CLOAK = Equipment(
    name="Werewolf Cloak",
    slot="cape",
    rarity="rare",
    tier=3,
    atk_min=0,
    atk_max=0,
    defence=2,
    max_hp=6,
    flavour="Thick silver-grey fur that still smells of moonlight "
            "and wet earth. Heavier and warmer than any dire wolf pelt.",
)

JACK_O_LANTERN_HEAD = Equipment(
    name="Jack O'Lantern Head",
    slot="helm",
    rarity="rare",
    tier=4,
    atk_min=0,
    atk_max=0,
    defence=2,
    max_hp=5,
    element="fire",
    element_damage=2,
    element_turns=2,
    flavour="The Horseman's severed pumpkin head, still flickering "
            "with spectral fire. Place a candle inside and its power "
            "surges — the flame becomes an inferno.",
)

# The four Halloween set piece names (for set detection)
HALLOWEEN_PIECE_NAMES = {
    "Enchanted Seed Launcher",
    "Sharpened Sucker",
    "Werewolf Cloak",
    "Jack O'Lantern Head",
}

# Which monster drops which piece (checked in roll_seasonal_equipment)
HALLOWEEN_DROPS = {
    "Giant Animated Jack O'Lantern": HALLOWEEN_SEED_LAUNCHER,
    "The Trickster":           SHARPENED_SUCKER,
    "Female Werewolf":         WEREWOLF_CLOAK,
    "Headless Horseman":       JACK_O_LANTERN_HEAD,
}

# ── Halloween Set Bonus — Dread Aura ──

DREAD_AURA_PROC_CHANCE = 0.25   # 25% chance each turn after the first

def halloween_set_active_pieces(warrior):
    """Count how many Halloween set pieces the warrior has EQUIPPED."""
    return sum(1 for it in warrior.equipment.values()
               if it is not None and getattr(it, "name", "") in HALLOWEEN_PIECE_NAMES)

def dread_aura_active(warrior):
    """True iff the full 4-piece Halloween set is equipped."""
    return halloween_set_active_pieces(warrior) >= 4

def apply_halloween_set_bonus(warrior):
    """
    Recalculate the Halloween Warrior set bonus. Follows the same
    remove-old / apply-new pattern as Wolf-Hide and Dire Wolf.

    Bonuses (cumulative):
        2 pieces: +6 max HP
        3 pieces: +6 max HP, +1 max AP
        4 pieces: +6 max HP, +1 max AP, +2 DEF, +1/+1 ATK
                  + Dread Aura passive (handled in combat)

    Add a call to this in apply_all_set_bonuses() in crafter.py:
        from collectibles import apply_halloween_set_bonus
        apply_halloween_set_bonus(warrior)
    """
    pieces = halloween_set_active_pieces(warrior)

    new = {"max_hp": 0, "max_ap": 0, "defence": 0, "atk_min": 0, "atk_max": 0}
    if pieces >= 2:
        new["max_hp"] += 6
    if pieces >= 3:
        new["max_ap"] += 1
    if pieces >= 4:
        new["defence"] += 2
        new["atk_min"] += 1
        new["atk_max"] += 1

    # Remove OLD bonus
    old = getattr(warrior, "_halloween_bonus_applied", {
        "max_hp": 0, "max_ap": 0, "defence": 0, "atk_min": 0, "atk_max": 0
    })
    warrior.max_hp  -= old["max_hp"]
    warrior.hp       = min(warrior.hp, warrior.max_hp)
    warrior.max_ap  -= old["max_ap"]
    warrior.ap       = min(warrior.ap, warrior.max_ap)
    warrior.defence -= old["defence"]
    warrior.min_atk -= old["atk_min"]
    warrior.max_atk -= old["atk_max"]

    # Apply NEW bonus
    warrior.max_hp  += new["max_hp"]
    if new["max_hp"] > 0 and old["max_hp"] == 0:
        warrior.hp = min(warrior.max_hp, warrior.hp + new["max_hp"])
    warrior.max_ap  += new["max_ap"]
    warrior.defence += new["defence"]
    warrior.min_atk += new["atk_min"]
    warrior.max_atk += new["atk_max"]

    warrior.max_overheal = int(warrior.max_hp * 1.10)
    warrior._halloween_bonus_applied = new

    # Award "Spirit of Halloween" title on 4-piece
    if pieces >= 4:
        titles = getattr(warrior, "titles", [])
        if "spirit_of_halloween" not in titles:
            titles.append("spirit_of_halloween")
            print("\n  🎃💀 TITLE UNLOCKED: Spirit of Halloween!")
            print("       The full Halloween Warrior set empowers you with Dread Aura!")


def check_dread_aura(warrior, enemy, is_first_enemy_turn=False):
    """
    Called at the START of the enemy's turn if Dread Aura is active.
    - First turn: enemy ALWAYS loses their turn (guaranteed fear).
    - Every turn after: 25% chance to lose the turn.
    Returns True if enemy skips, False if they act normally.

    Usage in combat.py, before the enemy attacks:
        if dread_aura_active(hero):
            first = (enemy.rounds_in_combat <= 1)
            if check_dread_aura(hero, enemy, is_first_enemy_turn=first):
                continue  # enemy skips
    """
    if not dread_aura_active(warrior):
        return False

    if is_first_enemy_turn:
        print(f"\n   🎃💀 DREAD AURA!")
        print(f"      {enemy.display_name} is PARALYZED with fear!")
        print(f"      The Halloween Warrior's presence freezes them solid!")
        print(f"      {enemy.display_name} loses their first turn!")
        return True

    if random.random() < DREAD_AURA_PROC_CHANCE:
        print(f"\n   🎃 {enemy.display_name} falters in DREAD!")
        print(f"      The Halloween Warrior's aura overwhelms them!")
        print(f"      {enemy.display_name} skips their attack!")
        return True

    return False


# ── Halloween Monster Special Moves ──

def exploding_pumpkin_seeds(enemy, warrior):
    """
    Giant Animated Jack O'Lantern's special — Exploding Pumpkin Seeds.
    Follows T1 special pattern: guaranteed turn 1, 66% on later turns.
    Costs 1 AP per use (max 2 uses per fight at base AP 2).

    Mechanic:
      1) Normal ATK swing (2-4, defence applies)
      2) Cascading seed volley (TRUE damage, ignores defence):
         - Seed 1: 100% chance to fire
         - Seed 2: only rolls if seed 1 hit, 66% chance
         - Seed 3: only rolls if seed 2 hit, 33% chance
         Each seed does 1-2 true damage.

    Probability breakdown:
      1 seed:  34%  (seed 2 missed)
      2 seeds: 44%  (seed 2 hit, seed 3 missed)
      3 seeds: 22%  (full chain)
    """
    if enemy.ap < 1:
        return None

    enemy.ap -= 1

    # --- 1) Normal ATK swing (defence applies) ---
    raw_dmg = random.randint(enemy.min_atk, enemy.max_atk)
    actual = warrior.apply_defence(raw_dmg, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    print(f"\n   🎃💥 EXPLODING PUMPKIN SEEDS!")
    print(f"      The giant pumpkin shudders and launches seeds!")
    print(f"      Basic attack hits for {actual} damage!")

    # --- 2) Cascading seed volley (TRUE damage) ---
    total_seed_damage = 0
    seeds_hit = 0

    # Seed 1: always fires
    seed_dmg = random.randint(1, 2)
    total_seed_damage += seed_dmg
    seeds_hit += 1
    print(f"      💥 Seed 1 explodes for {seed_dmg} true damage!")

    # Seed 2: 66% chance (only if seed 1 hit — it always does)
    if random.randint(1, 3) <= 2:  # 66%
        seed_dmg = random.randint(1, 2)
        total_seed_damage += seed_dmg
        seeds_hit += 1
        print(f"      💥 Seed 2 explodes for {seed_dmg} true damage!")

        # Seed 3: 33% chance (only if seed 2 hit)
        if random.randint(1, 3) == 1:  # 33%
            seed_dmg = random.randint(1, 2)
            total_seed_damage += seed_dmg
            seeds_hit += 1
            print(f"      💥 Seed 3 explodes for {seed_dmg} true damage!")

    warrior.hp = max(0, warrior.hp - total_seed_damage)

    total_damage = actual + total_seed_damage
    print(f"      🎃 {seeds_hit} seed{'s' if seeds_hit != 1 else ''} hit! "
          f"Total: {total_damage} damage (HP: {warrior.hp}/{warrior.max_hp})")

    log(f"  [SPECIAL] Exploding Pumpkin Seeds — {total_damage} total damage ({seeds_hit} seeds)")
    return total_damage


def lollipop_flurry(enemy, warrior):
    """
    The Trickster's special — Lollipop Flurry.
    Follows T2 special pattern: guaranteed turn 1 via initiative,
    percentage chance after. Costs 1 AP per use.

    Mechanic:
      1) Basic attack lands first (ATK 3-5, defence applies)
      2) Cascading lollipop jabs (defence applies to each):
         - Jab 1: 100% chance
         - Jab 2: 66% chance (only if jab 1 hit)
         - Jab 3: 33% chance (only if jab 2 hit)
         Each jab does 1-3 damage (defence applies)
         Each jab applies a bleed stack: 2-3 damage, 1 turn
         Bleeds tagged "trickster" so heal triggers on tick

    Lollipop Lick (passive, instant):
      When trickster-tagged bleeds tick on the player, the Trickster
      heals 50% of that bleed damage immediately. Can overheal to
      150% max HP.
    """
    if enemy.ap < 1:
        return None

    enemy.ap -= 1

    # --- 1) Basic attack (defence applies) ---
    raw_dmg = random.randint(enemy.min_atk, enemy.max_atk)
    actual = warrior.apply_defence(raw_dmg, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    print(f"\n   🍭💥 LOLLIPOP FLURRY!")
    print(f"      The Trickster lunges with its sharpened lollipop!")
    print(f"      Basic strike hits for {actual} damage!")

    # --- 2) Cascading jabs with bleed ---
    total_jab_damage = 0
    jabs_hit = 0
    bleeds_applied = 0

    # Jab 1: always fires
    jab_raw = random.randint(1, 3)
    jab_actual = warrior.apply_defence(jab_raw, attacker=enemy)
    warrior.hp = max(0, warrior.hp - jab_actual)
    total_jab_damage += jab_actual
    jabs_hit += 1

    # Apply bleed stack (1 turn, 2-3 damage, tagged as trickster)
    bleed_dmg = random.randint(2, 3)
    if not hasattr(warrior, "bleed_stacks"):
        warrior.bleed_stacks = []
    warrior.bleed_stacks.append({
        "damage": bleed_dmg, "turns_left": 1, "source": "trickster"
    })
    bleeds_applied += 1
    print(f"      🍭 Jab 1 hits for {jab_actual} + 🩸 bleed ({bleed_dmg}/1t)!")

    # Jab 2: 66% chance
    if random.randint(1, 3) <= 2:
        jab_raw = random.randint(1, 3)
        jab_actual = warrior.apply_defence(jab_raw, attacker=enemy)
        warrior.hp = max(0, warrior.hp - jab_actual)
        total_jab_damage += jab_actual
        jabs_hit += 1

        bleed_dmg = random.randint(2, 3)
        warrior.bleed_stacks.append({
            "damage": bleed_dmg, "turns_left": 1, "source": "trickster"
        })
        bleeds_applied += 1
        print(f"      🍭 Jab 2 hits for {jab_actual} + 🩸 bleed ({bleed_dmg}/1t)!")

        # Jab 3: 33% chance
        if random.randint(1, 3) == 1:
            jab_raw = random.randint(1, 3)
            jab_actual = warrior.apply_defence(jab_raw, attacker=enemy)
            warrior.hp = max(0, warrior.hp - jab_actual)
            total_jab_damage += jab_actual
            jabs_hit += 1

            bleed_dmg = random.randint(2, 3)
            warrior.bleed_stacks.append({
                "damage": bleed_dmg, "turns_left": 1, "source": "trickster"
            })
            bleeds_applied += 1
            print(f"      🍭 Jab 3 hits for {jab_actual} + 🩸 bleed ({bleed_dmg}/1t)!")

    total_damage = actual + total_jab_damage
    print(f"      🍬 {jabs_hit} jab{'s' if jabs_hit != 1 else ''} landed! "
          f"Total: {total_damage} damage + {bleeds_applied} bleed stacks "
          f"(HP: {warrior.hp}/{warrior.max_hp})")

    log(f"  [SPECIAL] Lollipop Flurry — {total_damage} damage + {bleeds_applied} bleeds")
    return total_damage


def maul(enemy, warrior):
    """
    The Female Werewolf's special — Maul.
    A savage opening swing followed by 2-4 cascading claw strikes.
    Each claw does 5-8 damage. Defence is treated as an armor pool
    that gets shredded across the claws (unique to this monster).
    Cascade: claw 1 = 100%, claw 2 = 75%, claw 3 = 50%, claw 4 = 25%.
    All damage feeds the lycanthropy conversion meter (handled in combat.py).
    """
    if enemy.ap <= 0:
        return None
    enemy.ap -= 1

    total_damage = 0

    # --- Opening swing (full ATK roll, normal defence) ---
    raw_swing = random.randint(enemy.min_atk, enemy.max_atk)
    actual_swing = max(1, raw_swing - warrior.defence)
    warrior.hp = max(0, warrior.hp - actual_swing)
    total_damage += actual_swing

    print(f"\n   🐺💥 MAUL!")
    print(f"      The Werewolf lunges with supernatural speed!")
    print(f"      Opening strike hits for {actual_swing} damage!")

    if not warrior.is_alive():
        print(f"      (HP: {warrior.hp}/{warrior.max_hp})")
        log(f"  [SPECIAL] Maul — {total_damage} damage")
        return {"damage": total_damage, "special": True}

    # --- Cascading claw strikes (armor pool mechanic) ---
    claw_chances = [1.0, 0.75, 0.50, 0.25]
    armor_pool = warrior.defence  # temporary pool, resets after maul
    claws_landed = 0
    claw_damage = 0

    for i, chance in enumerate(claw_chances):
        if random.random() > chance:
            break
        if not warrior.is_alive():
            break

        raw = random.randint(5, 8)
        absorbed = min(raw, armor_pool)
        actual = raw - absorbed
        armor_pool -= absorbed

        # Always deal at least 1 even if armor absorbs everything
        actual = max(1, actual)
        warrior.hp = max(0, warrior.hp - actual)
        claws_landed += 1
        claw_damage += actual
        total_damage += actual

        if absorbed > 0 and actual > absorbed:
            print(f"      🐺 Claw {claws_landed} tears through armor for {actual} damage! (Armor shredded: {absorbed})")
        elif absorbed > 0:
            print(f"      🐺 Claw {claws_landed} scrapes armor for {actual} damage! (Armor absorbed: {absorbed})")
        else:
            print(f"      🐺 Claw {claws_landed} rips flesh for {actual} damage!")

    # --- Summary ---
    print(f"      🐺 {claws_landed} claw{'s' if claws_landed != 1 else ''} landed! "
          f"Total: {total_damage} damage (HP: {warrior.hp}/{warrior.max_hp})")

    log(f"  [SPECIAL] Maul — {total_damage} damage ({actual_swing} swing + {claw_damage} claws x{claws_landed})")

    # Lycanthropy conversion — all maul damage feeds the meter
    if hasattr(warrior, "lycanthropy_charge") or warrior.is_alive():
        from combat import _lycanthropy_tick
        _lycanthropy_tick(warrior, total_damage)

    return {"damage": total_damage, "special": True}


def headless_cleave(enemy, warrior):
    """
    Headless Horseman's signature move. Massive swing that
    bypasses 50% of the target's DEF. Fires every 3rd turn.
    """
    if not hasattr(enemy, "cleave_cooldown"):
        enemy.cleave_cooldown = 0

    enemy.cleave_cooldown += 1
    if enemy.cleave_cooldown < 3:
        return None

    enemy.cleave_cooldown = 0

    raw_dmg = random.randint(enemy.min_atk, enemy.max_atk)
    bonus   = int(raw_dmg * 0.5)
    total   = raw_dmg + bonus
    effective_def = max(0, warrior.defence // 2)
    actual = max(1, total - effective_def)
    warrior.hp = max(0, warrior.hp - actual)

    print(f"\n   🐴💀 HEADLESS CLEAVE!")
    print(f"      The Horseman swings a massive spectral blade!")
    print(f"      It cuts through your guard, bypassing half your armor!")
    print(f"      You take {actual} damage! (HP: {warrior.hp}/{warrior.max_hp})")

    log(f"  [SPECIAL] Headless Cleave — {actual} damage")
    return {"damage": actual, "special": True}


def dread_charge_tick(enemy):
    """
    Passive: Every 3 turns, the Horseman's ATK grows.
    Rewards aggressive play, punishes turtling.
    """
    if not hasattr(enemy, "dread_charge_counter"):
        enemy.dread_charge_counter = 0

    enemy.dread_charge_counter += 1
    if enemy.dread_charge_counter >= 3:
        enemy.dread_charge_counter = 0
        enemy.min_atk += 1
        enemy.max_atk += 1
        print(f"\n   🔥💀 DREAD CHARGE! The Horseman's fury intensifies!")
        print(f"      ATK increased to {enemy.min_atk}-{enemy.max_atk}!")


# ── Halloween Monster Classes ──

class Giant_Animated_Jack_O_Lantern(Monster):
    """
    Tier 1 Alpha Halloween monster (October only).
    A massive carved pumpkin brought to life by dark magic.
    Tougher than a regular T1 — thick rind gives it high HP
    and DEF for its tier, but low ATK. The danger comes from
    Exploding Pumpkin Seeds, not basic attacks.
    Stats: HP 18, ATK 2-4, DEF 2, AP 2, XP 15
    Drops: Enchanted Seed Launcher (accessory/weapon)
    """
    def __init__(self):
        super().__init__(
            name="Giant Animated Jack O'Lantern",
            hp=18,
            min_atk=2,
            max_atk=4,
            gold=0,
            xp=15,
            essence=["jack o'lantern essence"],
            defence=2,
            ap=2
        )
        self.special_move = exploding_pumpkin_seeds
        self.alpha_special = True


class The_Trickster(Monster):
    """
    Tier 2 Alpha Halloween monster (October only).
    A small, unsettling childlike figure in a stitched mask.
    Inspired by Sam from Trick 'r Treat. Moves with eerie silence.
    Its sharpened lollipop jabs apply stacking bleeds, and it
    heals from the blood absorbed by its enchanted candy.
    Stats: HP 25, ATK 3-5, DEF 2, AP 3, XP 22
    Drops: Sharpened Sucker (weapon, bleed + heal at higher rarities)
    """
    def __init__(self):
        super().__init__(
            name="The Trickster",
            hp=25,
            min_atk=3,
            max_atk=5,
            gold=0,
            xp=22,
            essence=["trickster essence"],
            defence=2,
            ap=3
        )
        self.special_move = lollipop_flurry
        self.alpha_special = True
        self.max_overheal = int(self.max_hp * 1.5)


class Female_Werewolf(Monster):
    """
    Tier 3 Halloween monster. A cursed woman trapped between
    forms — half-Teraan, half-wolf. Faster than any natural
    beast, her claws tear through armor before you can react.
    Stat band: T3 (HP 33, ATK 7-11, DEF 3, AP 4)
    Drops: Werewolf Cloak (cape)
    """
    def __init__(self):
        super().__init__(
            name="Female Werewolf",
            hp=33,
            min_atk=7,
            max_atk=11,
            gold=0,
            xp=35,
            essence=["werewolf cloak"],
            defence=3,
            ap=4
        )
        self.special_move   = maul
        self.alpha_special  = True


class Headless_Horseman(Monster):
    """
    Tier 4 Halloween boss. Only in the boss pool during October.
    Drops: Jack O'Lantern Head (helm, fire damage 2)
    """
    def __init__(self):
        super().__init__(
            name="Headless Horseman",
            hp=80,
            min_atk=9,
            max_atk=14,
            gold=0,
            xp=90,
            essence=["horseman essence"],
            defence=7,
            ap=6
        )
        self.special_move        = headless_cleave
        self.cleave_cooldown     = 0
        self.dread_charge_counter = 0


# ── Halloween Loot Drop Helper ──

def roll_halloween_drop(hero, defeated_monster_name):
    """
    Called after defeating a Halloween monster. Checks if their
    unique gear drops. Each piece drops once per run (check inventory
    and equipped slots).

    Drop chances:
        T1 Seed Launcher: 30% (common drop from a weak monster)
        T2 Sucker:        25%
        T3 Cloak:         20% (rarer from a tougher monster)
        T4 Head:          40% (boss drop — reward for the fight)

    Rarity is determined by roll_rarity() from equipment.py, which
    respects difficulty gating (noob caps at uncommon, warrior at
    rare, champion can roll epic). For the Seed Launcher specifically,
    the rolled rarity also sets the seed count and damage ranges.

    Returns the Equipment instance if dropped, None otherwise.
    """
    import copy
    from equipment import roll_rarity

    drop_chances = {
        "Giant Animated Jack O'Lantern": 1.00,
        "The Trickster":           1.00,
        "Female Werewolf":         1.00,
        "Headless Horseman":       1.00,
    }

    equip = HALLOWEEN_DROPS.get(defeated_monster_name)
    if equip is None:
        return None

    chance = drop_chances.get(defeated_monster_name, 0.0)

    if random.random() < chance:
        dropped = copy.deepcopy(equip)

        # Roll rarity using the standard difficulty-gated system
        rarity = roll_rarity(monster_level=1, round_num=0)
        dropped.rarity = rarity

        # If this is the Seed Launcher, attach rarity-scaled seed stats
        if dropped.name == "Enchanted Seed Launcher":
            stats = SEED_LAUNCHER_STATS.get(rarity, SEED_LAUNCHER_STATS["normal"])
            dropped.seed_min_count = stats["min_seeds"]
            dropped.seed_max_count = stats["max_seeds"]
            dropped.seed_min_dmg   = stats["min_dmg"]
            dropped.seed_max_dmg   = stats["max_dmg"]
            dropped.flavour = (
                f"A hollowed pumpkin husk packed with enchanted seeds. "
                f"Seeds: {stats['min_seeds']}-{stats['max_seeds']}, "
                f"Dmg/seed: {stats['min_dmg']}-{stats['max_dmg']}. "
                f"33% proc chance per turn."
            )

        # If this is the Sharpened Sucker, apply rarity-scaled stats
        elif dropped.name == "Sharpened Sucker":
            stats = SHARPENED_SUCKER_STATS.get(rarity, SHARPENED_SUCKER_STATS["normal"])
            dropped.atk_min     = stats["atk_min"]
            dropped.atk_max     = stats["atk_max"]
            dropped.bleed_turns = stats["bleed_turns"]
            dropped.bleed_dmg_min = stats["bleed_dmg"]
            dropped.bleed_dmg_max = stats["bleed_dmg"]
            dropped.sucker_heal_pct = stats["heal_pct"]
            dropped.sucker_multi_min = stats["multi_min"]
            dropped.sucker_multi_max = stats["multi_max"]
            # Build flavour based on unlocked mechanics
            parts = [f"ATK {stats['atk_min']}"]
            if stats["bleed_dmg"] > 0:
                parts.append(f"Bleed {stats['bleed_dmg']}/1t")
            if stats["heal_pct"] > 0:
                parts.append(f"Heal {int(stats['heal_pct']*100)}% of bleed")
            if stats["multi_max"] > 1:
                parts.append(f"Multi-strike {stats['multi_min']}-{stats['multi_max']}")
            dropped.flavour = (
                f"A lollipop honed to a razor point. "
                f"{'. '.join(parts)}."
            )

        hero.inventory.append(dropped)
        print(f"\n   🎃 HALLOWEEN DROP: {dropped.name} ({rarity.title()})!")
        print(f"      \"{dropped.flavour}\"")

        record_collectable_found(dropped.name.lower().replace(" ", "_"))
        return dropped

    return None


# ============================================================
# 🎄 DECEMBER — WINTER SOLSTICE / KRAMPUSNACHT
# ============================================================
# Lore tie-in: The Winter Solstice in JTWH marks when the veil
# between the mortal realm and the spirit world thins. Ancient
# creatures from Solerian myth emerge — twisted versions of
# holiday folklore filtered through the game's Beast God / Divine
# mythology. These aren't jolly — they're what happens when old
# magic goes wrong.
#
# Four-tier seasonal encounter pool that injects into the regular
# monster tables during December. Each tier matches the existing
# stat bands so seasonal monsters slot in cleanly alongside the
# base roster.

# ---------- Tier 1: Elf on a Shelf ----------
# A small, creepy animated figurine. Watches you. Reports back.
# Special: Tattle — marks the hero, reducing DEF by 1 for 2 turns.
# Low damage, low HP. The debuff is the threat, not the Elf itself.

def elf_tattle(enemy, warrior):
    """
    Elf on a Shelf's special move — Tattle.
    Marks the hero for 2 turns, reducing their DEF by 1.
    Only fires once per fight (the Elf reports to its master).
    """
    if getattr(enemy, "has_tattled", False):
        return None

    enemy.has_tattled = True

    # Apply DEF debuff
    warrior.defence = max(0, warrior.defence - 1)

    # Track so we can restore later
    if not hasattr(warrior, "tattle_turns"):
        warrior.tattle_turns = 0
        warrior.tattle_def_lost = 0
    warrior.tattle_turns += 2
    warrior.tattle_def_lost += 1

    print(f"\n   🧝 TATTLE!")
    print(f"      The Elf's eyes glow red — it's reporting your weaknesses!")
    print(f"      Your guard falters... DEF reduced by 1 for 2 turns!")
    print(f"      (DEF: {warrior.defence})")

    log(f"  [SPECIAL] Tattle — {0} damage")
    return {"damage": 0, "special": True, "debuff": "tattle"}


def tick_tattle(warrior):
    """
    Tick down the Tattle DEF debuff at end of hero's turn.
    Restore DEF when it expires.
    """
    if not hasattr(warrior, "tattle_turns") or warrior.tattle_turns <= 0:
        return

    warrior.tattle_turns -= 1
    if warrior.tattle_turns <= 0:
        warrior.defence += warrior.tattle_def_lost
        print(f"\n   🧝 The Elf's mark fades... DEF restored to {warrior.defence}")
        warrior.tattle_def_lost = 0


class Elf_On_A_Shelf(Monster):
    """
    Tier 1 Winter Solstice monster. Creepy animated figurine.
    Stat band: T1 (HP 8-13, ATK 1-5, DEF 0-1, AP 1)
    """
    def __init__(self):
        super().__init__(
            name="Elf on a Shelf",
            hp=9,
            min_atk=1,
            max_atk=3,
            gold=0,
            xp=6,
            essence=["elf figurine essence"],
            defence=0,
            ap=1
        )
        self.special_move = elf_tattle
        self.has_tattled  = False


# ---------- Tier 2: Mutated Gingerbread Man ----------
# A cookie that should NOT be alive. Frosting oozes, gumdrop eyes
# blink. It's fast and it heals.
# Special: Sugar Coat — heals self for 15-25% max HP. One use.

def sugar_coat(enemy, warrior):
    """
    Mutated Gingerbread Man's special — Sugar Coat.
    Self-heal by re-frosting. 15-25% of max HP restored.
    Fires once when the Gingerbread Man drops below 60% HP.
    """
    if getattr(enemy, "has_sugar_coated", False):
        return None

    # Only triggers when hurt
    if enemy.hp > enemy.max_hp * 0.60:
        return None

    enemy.has_sugar_coated = True

    heal_pct = random.uniform(0.15, 0.25)
    heal_amt = max(1, int(enemy.max_hp * heal_pct))
    enemy.hp = min(enemy.max_hp, enemy.hp + heal_amt)

    print(f"\n   🍪 SUGAR COAT!")
    print(f"      The Gingerbread Man slathers on fresh frosting!")
    print(f"      It heals for {heal_amt} HP! (HP: {enemy.hp}/{enemy.max_hp})")

    log(f"  [SPECIAL] Sugar Coat — {0} damage")
    return {"damage": 0, "special": True, "heal": heal_amt}


class Mutated_Gingerbread_Man(Monster):
    """
    Tier 2 Winter Solstice monster. A living cookie abomination.
    Stat band: T2 (HP 20-23, ATK 3-7, DEF 2-3, AP 3)
    """
    def __init__(self):
        super().__init__(
            name="Mutated Gingerbread Man",
            hp=22,
            min_atk=4,
            max_atk=6,
            gold=0,
            xp=19,
            essence=["gingerbread essence"],
            defence=2,
            ap=3
        )
        self.special_move    = sugar_coat
        self.has_sugar_coated = False


# ---------- Tier 3: Killer Frosty ----------
# A snowman animated by dark solstice magic. Coal eyes burn with
# malice. Top hat hides something unspeakable.
# Special: Blizzard Breath — cold damage + slows hero (AP drain).

BLIZZARD_SLOW_TURNS = 2
BLIZZARD_AP_DRAIN   = 1

def blizzard_breath(enemy, warrior):
    """
    Killer Frosty's special — Blizzard Breath.
    Deals cold damage and drains 1 AP per turn for 2 turns.
    Fires every 4th turn (building up cold).
    """
    if not hasattr(enemy, "blizzard_cooldown"):
        enemy.blizzard_cooldown = 0

    enemy.blizzard_cooldown += 1
    if enemy.blizzard_cooldown < 4:
        return None

    enemy.blizzard_cooldown = 0

    # Cold damage — slightly above normal ATK
    raw_dmg = random.randint(enemy.min_atk, enemy.max_atk)
    bonus   = int(raw_dmg * 0.3)   # 30% cold bonus
    total   = raw_dmg + bonus
    actual  = max(1, total - warrior.defence)
    warrior.hp = max(0, warrior.hp - actual)

    # Apply AP slow
    if not hasattr(warrior, "blizzard_slow_turns"):
        warrior.blizzard_slow_turns = 0
    warrior.blizzard_slow_turns = BLIZZARD_SLOW_TURNS

    print(f"\n   ☃️❄️ BLIZZARD BREATH!")
    print(f"      Killer Frosty exhales a wave of supernatural cold!")
    print(f"      You take {actual} cold damage! (HP: {warrior.hp}/{warrior.max_hp})")
    print(f"      The cold slows you — lose {BLIZZARD_AP_DRAIN} AP per turn "
          f"for {BLIZZARD_SLOW_TURNS} turns!")

    log(f"  [SPECIAL] Blizzard Breath — {actual} damage")
    return {"damage": actual, "special": True, "debuff": "blizzard_slow"}


def tick_blizzard_slow(warrior):
    """
    Tick the Blizzard Breath AP drain at the START of the hero's turn.
    Drains 1 AP per turn while active. Restore nothing on expiry —
    the AP is gone (you have to earn it back or potion it).
    """
    if not hasattr(warrior, "blizzard_slow_turns") or warrior.blizzard_slow_turns <= 0:
        return

    drain = min(BLIZZARD_AP_DRAIN, warrior.ap)
    if drain > 0:
        warrior.ap -= drain
        print(f"\n   ❄️ The cold saps your energy... −{drain} AP! "
              f"(AP: {warrior.ap}/{warrior.max_ap})")

    warrior.blizzard_slow_turns -= 1
    if warrior.blizzard_slow_turns <= 0:
        print(f"   ❄️ The chill finally breaks. You can move freely again.")


class Killer_Frosty(Monster):
    """
    Tier 3 Winter Solstice monster. A malevolent living snowman.
    Stat band: T3 (HP 33-40, ATK 5-9, DEF 4-5, AP 4-5)
    """
    def __init__(self):
        super().__init__(
            name="Killer Frosty",
            hp=38,
            min_atk=6,
            max_atk=9,
            gold=0,
            xp=35,
            essence=["frosty essence"],
            defence=4,
            ap=5
        )
        self.special_move     = blizzard_breath
        self.blizzard_cooldown = 0


# ---------- Tier 4: Krampus ----------
# The anti-Claus of Winter Solstice lore. In JTWH mythology,
# Krampus is a lesser Beast God — one of the old spirits the
# Beast Gods created to enforce obedience. During the Solstice,
# when the veil thins, he slips through to punish the unworthy.
#
# Design: Heavy hitter with a multi-phase fight.
# Special: Chains of Punishment — two-hit combo attack.
#          First hit wraps chains (damage + stun setup),
#          second hit drags hero into the bag (bonus damage if stunned).
# Passive: Krampus Rage — gains +2 ATK every time he drops below
#          a 25% HP threshold (fires at 75%, 50%, 25%).

def chains_of_punishment(enemy, warrior):
    """
    Krampus's signature special — Chains of Punishment.
    Two-hit combo: chain wrap (damage + marks) then bag drag
    (bonus damage). Fires every 4th turn.
    """
    if not hasattr(enemy, "chains_cooldown"):
        enemy.chains_cooldown = 0

    enemy.chains_cooldown += 1
    if enemy.chains_cooldown < 4:
        return None

    enemy.chains_cooldown = 0

    # Hit 1: Chain Wrap
    raw1 = random.randint(enemy.min_atk, enemy.max_atk)
    actual1 = max(1, raw1 - warrior.defence)
    warrior.hp = max(0, warrior.hp - actual1)

    print(f"\n   ⛓️😈 CHAINS OF PUNISHMENT!")
    print(f"      Krampus lashes out with rusted chains!")
    print(f"      Chain Wrap deals {actual1} damage! (HP: {warrior.hp}/{warrior.max_hp})")

    if warrior.hp <= 0:
        return {"damage": actual1, "special": True}

    # Hit 2: Bag Drag — bonus damage (50% of base)
    raw2 = random.randint(enemy.min_atk, enemy.max_atk)
    bonus = int(raw2 * 0.5)
    actual2 = max(1, (raw2 + bonus) - warrior.defence)
    warrior.hp = max(0, warrior.hp - actual2)

    total = actual1 + actual2
    print(f"      He drags you toward his bag — {actual2} more damage!")
    print(f"      Total: {total} damage! (HP: {warrior.hp}/{warrior.max_hp})")

    # Stun for 1 turn (hero loses next turn)
    warrior.krampus_stunned = True
    print(f"      You're tangled in chains — STUNNED for 1 turn!")

    log(f"  [SPECIAL] Chains of Punishment — {total} damage")
    return {"damage": total, "special": True, "debuff": "stun"}


def check_krampus_stun(warrior):
    """
    Check at the START of the hero's turn if they're Krampus-stunned.
    Returns True if stunned (skip the hero's turn), False otherwise.
    Clears after one turn.
    """
    if getattr(warrior, "krampus_stunned", False):
        warrior.krampus_stunned = False
        print(f"\n   ⛓️ You struggle free of Krampus's chains!")
        print(f"      You lost your turn breaking loose!")
        return True
    return False


def krampus_rage_check(enemy):
    """
    Passive: Krampus rages at HP thresholds.
    Gains +2/+2 ATK when crossing 75%, 50%, and 25% HP.
    Each threshold only fires once.
    """
    if not hasattr(enemy, "rage_thresholds"):
        enemy.rage_thresholds = {
            75: False,
            50: False,
            25: False,
        }

    hp_pct = (enemy.hp / enemy.max_hp) * 100

    for threshold, triggered in sorted(enemy.rage_thresholds.items(), reverse=True):
        if triggered:
            continue
        if hp_pct <= threshold:
            enemy.rage_thresholds[threshold] = True
            enemy.min_atk += 2
            enemy.max_atk += 2
            print(f"\n   😈🔥 KRAMPUS RAGE!")
            print(f"      Krampus roars as his wounds fuel his fury!")
            print(f"      ATK surges to {enemy.min_atk}-{enemy.max_atk}!")
            break   # Only one threshold per check


class Krampus(Monster):
    """
    Tier 4 Winter Solstice boss. A lesser Beast God who punishes
    the unworthy during the thinning of the veil.

    Tougher than Headless Horseman. Krampus is the December
    equivalent of the Fallen Warrior — a proper Tier 4 threat.

    Special: Chains of Punishment (two-hit combo + stun)
    Passive: Krampus Rage (+2/+2 ATK at 75%, 50%, 25% HP)
    """
    def __init__(self):
        super().__init__(
            name="Krampus",
            hp=90,
            min_atk=10,
            max_atk=15,
            gold=0,
            xp=100,
            essence=["krampus essence"],
            defence=8,
            ap=7
        )
        self.special_move    = chains_of_punishment
        self.chains_cooldown = 0
        self.rage_thresholds = {75: False, 50: False, 25: False}


# ============================================================
# 🔌 SEASONAL MONSTER INJECTION
# ============================================================
# Call inject_seasonal_monsters() from monsters.py AFTER
# MONSTER_TYPES and TIER4_BOSSES are defined. This appends
# seasonal monsters into the existing pools only when their
# season is active. Clean — no permanent modification.

# Seasonal encounter pool: (class, weight, season_tag)
SEASONAL_MONSTERS = [
    # Halloween (October) — full T1-T3 roster
    (Giant_Animated_Jack_O_Lantern, 1, "halloween"),   # Tier 1 (weight 1)
    (The_Trickster,           2, "halloween"),   # Tier 2 (weight 2)
    (Female_Werewolf,         3, "halloween"),   # Tier 3 (weight 3)

    # Winter Solstice (December)
    (Elf_On_A_Shelf,          1, "winter_solstice"),   # Tier 1 (weight 1)
    (Mutated_Gingerbread_Man, 2, "winter_solstice"),   # Tier 2 (weight 2)
    (Killer_Frosty,           3, "winter_solstice"),   # Tier 3 (weight 3)
]

# Seasonal Tier 4 bosses: (class, weight, season_tag)
SEASONAL_BOSSES = [
    (Headless_Horseman, 3, "halloween"),        # October
    (Krampus,           3, "winter_solstice"),   # December
]


def inject_seasonal_monsters(monster_types_list, tier4_bosses_list):
    """
    Append seasonal monsters into the game's live pools.
    Call ONCE at import time from monsters.py:

        from collectibles import inject_seasonal_monsters
        inject_seasonal_monsters(MONSTER_TYPES, TIER4_BOSSES)

    Only adds monsters whose season is currently active.
    Safe to call multiple times — checks for duplicates.
    """
    active = get_active_seasons()
    if not active:
        return

    # Inject T1-T3 seasonal monsters
    existing_classes = {cls for cls, _ in monster_types_list}
    for cls, weight, season in SEASONAL_MONSTERS:
        if season in active and cls not in existing_classes:
            monster_types_list.append((cls, weight))

    # Inject Tier 4 seasonal bosses
    existing_bosses = {cls for cls, _ in tier4_bosses_list}
    for cls, weight, season in SEASONAL_BOSSES:
        if season in active and cls not in existing_bosses:
            tier4_bosses_list.append((cls, weight))


def is_seasonal_monster(monster):
    """
    Check if a monster instance is a seasonal creature.
    Used by combat.py to trigger record_seasonal_monster_defeated().
    """
    seasonal_names = {
        # Halloween
        "Animated Jack O'Lantern", "The Trickster",
        "Female Werewolf", "Headless Horseman",
        # Winter Solstice
        "Elf on a Shelf", "Mutated Gingerbread Man",
        "Killer Frosty", "Krampus",
    }
    return monster.name in seasonal_names


# ============================================================
# 🎁 SEASONAL LOOT HELPERS
# ============================================================

# ============================================================
# 📊 SEASONAL SCORE BONUSES
# ============================================================
# Two scoring hooks for the Birthday Cake:
#
# 1) MULTIPLIER BONUS (+0.10): Granted when the cake is CONSUMED.
#    Additive with quick-kill bonus and Nob's bet. Tracked on
#    hero.seasonal_score_bonus, read by get_seasonal_score_bonus().
#
# 2) SAVED BONUS (+100 flat): Granted if the cake is still in
#    inventory at end of run — you held onto it through every
#    fight instead of eating it. Separate from the potion cap,
#    same slot as the Frostpine Tonic saved bonus but worth 4x.
#    You get ONE or the OTHER, never both: eat it for the
#    multiplier, or save it for the flat 100.

def get_seasonal_score_bonus(warrior):
    """
    Return the accumulated seasonal score multiplier bonus.
    Called from score.py's show_run_score() to add into the
    multiplier stack alongside quick-kill and Nob bonuses.

    Usage in score.py (around line 595, after nob_hardship):
        from collectibles import get_seasonal_score_bonus
        seasonal_bonus = get_seasonal_score_bonus(warrior)
        multiplier = round(base_multiplier + qk_bonus + nob_hardship + seasonal_bonus, 2)

    And in the display section (around line 682, in bonus_parts):
        if seasonal_bonus > 0:
            bonus_parts.append(f"+{seasonal_bonus:.2f} (🎂 seasonal)")
    """
    return float(getattr(warrior, "seasonal_score_bonus", 0.0) or 0.0)


def compute_cake_saved_score(warrior):
    """
    Return the flat score bonus for holding the Birthday Cake
    through the entire run without eating it.

    Called from score.py's _compute_potion_score() or alongside it.
    Returns (cake_score, cake_count) matching the frostpine pattern.

    Usage in score.py, in _compute_potion_score() after the frostpine block:
        from collectibles import compute_cake_saved_score, CAKE_SAVED_BONUS
        cake_count = potions.get("birthday_cake", 0)
        cake_score = CAKE_SAVED_BONUS if cake_count > 0 else 0

    Then add cake_score to the subtotal (line ~573) alongside frostpine_score.

    Display in the score breakdown (after the Frostpine row):
        if cake_count > 0:
            _row("🎂 Birthday Cake Saved", f"+{cake_score}")
    """
    potions = getattr(warrior, "potions", {}) or {}
    count = potions.get("birthday_cake", 0)
    score = CAKE_SAVED_BONUS if count > 0 else 0
    return score, count


SEASONAL_COLLECTIBLES = {
    "august_birthday": BIRTHDAY_CAKE,
    "march_birthday":  BOOK_OF_LOST_SECRETS,
}

SEASONAL_EQUIPMENT = {
    # Halloween gear drops are handled per-monster via roll_halloween_drop()
    # rather than the generic roll_seasonal_equipment() — each monster drops
    # its own specific piece. This dict is for seasons with a single generic
    # gear drop (none currently).
}


# ============================================================
# 📚 COLLECTION BOOK — Permanent Score Multipliers
# ============================================================
# Completing a seasonal collection earns a PERMANENT score
# multiplier bonus that applies to every future run. This
# rewards long-term play across multiple seasonal events.
#
# Collections are tracked in seasonal_data.json under "discovered".
# A collection is complete when ALL of its required pieces have
# been found at least once (across any number of runs).
#
# Design: permanent once earned, but easy to adjust later if
# feedback says it's too strong or too weak.

COLLECTIONS = {
    "august_birthday": {
        "name":       "Birthday Celebration",
        "icon":       "🎂",
        "pieces":     ["birthday_cake"],
        "multiplier": 0.10,
        "description": "Found the Birthday Cake during August.",
    },
    "march_birthday": {
        "name":       "Scholar's Discovery",
        "icon":       "📖",
        "pieces":     ["book_of_lost_secrets"],
        "multiplier": 0.10,
        "description": "Found the Book of Lost Secrets during March.",
    },
    "halloween": {
        "name":       "Halloween Warrior",
        "icon":       "🎃",
        "pieces":     [
            "enchanted_seed_launcher",
            "sharpened_sucker",
            "werewolf_cloak",
            "jack_o'lantern_head",
        ],
        "multiplier": 0.25,
        "description": "Collected all 4 Halloween set pieces.",
    },
    "winter_solstice": {
        "name":       "Solstice Survivor",
        "icon":       "🎄",
        "pieces":     [
            # Defeated all 4 Winter Solstice monsters at least once
            "Elf on a Shelf",
            "Mutated Gingerbread Man",
            "Killer Frosty",
            "Krampus",
        ],
        "multiplier": 0.25,
        "description": "Defeated all 4 Winter Solstice monsters.",
    },
}


def get_completed_collections():
    """
    Check seasonal_data.json to see which collections are complete.
    Returns a list of (collection_key, collection_dict) for completed ones.
    """
    data = _load_seasonal_data()
    discovered = data.get("discovered", {})
    bestiary   = data.get("bestiary", {})

    # Merge discovered items and bestiary monsters into one lookup
    all_found = set(discovered.keys()) | set(bestiary.keys())

    completed = []
    for key, collection in COLLECTIONS.items():
        if all(piece in all_found for piece in collection["pieces"]):
            completed.append((key, collection))

    return completed


def get_collection_multiplier():
    """
    Return the TOTAL permanent score multiplier from all completed
    collections. Called from score.py alongside other multiplier bonuses.

    This is PERMANENT — once earned, it applies every run forever.
    Easy to change: flip to month-only by wrapping in is_season_active().
    """
    completed = get_completed_collections()
    return sum(c["multiplier"] for _, c in completed)


def show_collection_book():
    """
    Display the Collection Book — all seasonal collections with
    checkmark status for each piece and multiplier unlock status.
    Call from a menu option.
    """
    data = _load_seasonal_data()
    discovered = data.get("discovered", {})
    bestiary   = data.get("bestiary", {})
    all_found  = set(discovered.keys()) | set(bestiary.keys())

    print("\n" + "=" * WIDTH)
    print("📚 COLLECTION BOOK".center(WIDTH))
    print("=" * WIDTH)

    # Show total permanent multiplier
    total_mult = get_collection_multiplier()
    if total_mult > 0:
        print(f"\n  🏆 Total Collection Bonus: +{total_mult:.2f} score multiplier")
    else:
        print(f"\n  Complete collections to earn permanent score bonuses!")

    for key, collection in COLLECTIONS.items():
        name    = collection["name"]
        icon    = collection["icon"]
        pieces  = collection["pieces"]
        mult    = collection["multiplier"]
        found   = sum(1 for p in pieces if p in all_found)
        total   = len(pieces)
        complete = (found == total)

        status = "✅ COMPLETE" if complete else f"{found}/{total}"
        mult_str = f"+{mult:.2f}" if complete else "🔒 locked"

        print(f"\n  {icon} {name}  [{status}]  (Multiplier: {mult_str})")
        print(f"     {collection['description']}")

        for piece in pieces:
            check = "✅" if piece in all_found else "⬜"
            display_name = piece.replace("_", " ").title()
            print(f"       {check} {display_name}")

    print("\n" + "=" * WIDTH)
    continue_text()


def roll_seasonal_collectable(hero):
    """
    Called after a fight to check if a seasonal collectable drops.
    Returns the collectable dict if one drops, None otherwise.
    """
    active = get_active_seasons()
    if not active:
        return None

    for season in active:
        collectable = SEASONAL_COLLECTIBLES.get(season)
        if collectable is None:
            continue

        key = collectable["key"]
        current = hero.potions.get(key, 0)
        if current >= collectable["max_stack"]:
            continue

        if random.random() < collectable["drop_chance"]:
            hero.potions[key] = current + 1
            icon = collectable["icon"]
            name = collectable["name"]
            desc = collectable["effect"]
            print(f"\n   {icon} SEASONAL DROP: {name}!")
            print(f"      {desc}")

            # Persist to seasonal_data.json
            record_collectable_found(key)
            return collectable

    return None


def roll_seasonal_equipment(hero):
    """
    Called during loot generation to check if seasonal equipment drops.
    8% flat chance from any fight during the active season.
    """
    active = get_active_seasons()
    if not active:
        return None

    for season in active:
        equip = SEASONAL_EQUIPMENT.get(season)
        if equip is None:
            continue

        # Don't drop duplicates
        if any(item.name == equip.name for item in hero.inventory):
            continue
        armor = hero.equipment.get("armor")
        if armor and armor.name == equip.name:
            continue

        if random.random() < 0.08:
            import copy
            dropped = copy.deepcopy(equip)
            hero.inventory.append(dropped)
            print(f"\n   🎃 SEASONAL GEAR: {dropped.name}!")
            print(f"      \"{dropped.flavour}\"")
            record_collectable_found(equip.name.lower().replace(" ", "_"))
            return dropped

    return None


# ============================================================
# 🎃 TOM — HALLOWEEN VENDOR  ("Darkness Incarnate")
# ============================================================
# A corrupted Teraan with trace divine blood (many generations
# diluted). Turned to dark magic to compensate and it warped him.
# Delusional — fully believes he IS Darkness Incarnate. Fat,
# balding, theatrically dramatic. Uses mana potions to constantly refill
# his tiny mana supply so he can cast his illusion spell.
#
# He is the single hub for ALL Halloween commerce:
#
# He is the single hub for ALL Halloween commerce:
#   1) Candy Shop       — buy gear/consumables for candy
#   2) Upgrade gear     — raise rarity of Halloween items for candy
#   3) Candy exchange   — 10 gold ↔ 1 candy (moved from merchant)
#   4) Premium buyback  — sell premium magic items for extra gold
# ============================================================

# Candy shop item catalog: (name, candy_cost, description, builder_func)
# Builder functions return an Equipment instance at the appropriate rarity.

CANDY_UPGRADE_COSTS = {
    # current_rarity → candy cost to upgrade one tier
    "poor":      5,
    "normal":    8,
    "uncommon":  12,
    "rare":      18,
    "epic":      25,
    "legendary": 35,
    # mythril cannot be upgraded further
}

# Premium items Tom will buy — pays 1.5× the merchant's sell price
PREMIUM_BUYBACK_NAMES = {
    "Soul Pendant",
    "Charged Jagged Rock",
    "Waterlogged Stone",
}

PREMIUM_BUYBACK_RATE = 1.5  # 150% of normal merchant sell-back


def _build_pumpkin_helm(rarity="normal"):
    """Create a Pumpkin Helm at the given rarity."""
    from equipment import PUMPKIN_HELM_STATS
    stats = PUMPKIN_HELM_STATS[rarity]
    return Equipment(
        name="Pumpkin Helm",
        slot="helm",
        rarity=rarity,
        tier=2,
        defence=stats["defence"],
        max_hp=stats["max_hp"],
        magic_res=stats["magic_res"],
        flavour="A carved pumpkin helm that smells faintly of harvest "
                "and dark magic. Sturdy, warm, and unsettling to look at.",
    )


def _build_vine_totem(rarity="normal"):
    """Create a Pumpkin Vine Totem accessory at the given rarity."""
    from equipment import PUMPKIN_VINE_TOTEM_STATS
    stats = PUMPKIN_VINE_TOTEM_STATS[rarity]
    return Equipment(
        name="Pumpkin Vine Totem",
        slot="accessory",
        rarity=rarity,
        tier=2,
        vine_dc=stats["dc"],
        vine_dmg=stats["vine_dmg"],
        vine_max_turns=stats["max_turns"],
        vine_max_charges=stats["max_charges"],
        vine_charges=stats["max_charges"],  # starts fully charged
        flavour="A totem carved from cursed pumpkin vine. In combat, "
                "squeeze it to send vines erupting from the ground, "
                "entangling your foe.",
    )


def _build_jack_o_lantern_head(rarity="rare"):
    """Create a Jack O'Lantern Head helm at the given rarity."""
    return Equipment(
        name="Jack O'Lantern Head",
        slot="helm",
        rarity=rarity,
        tier=4,
        defence=2,
        max_hp=5,
        element="fire",
        element_damage=2,
        element_turns=2,
        dread_aura_chance=0.15,
        flavour="The Horseman's severed pumpkin head, still flickering "
                "with spectral fire. Place a candle inside and its power "
                "surges — the flame becomes an inferno.",
    )


def _build_seed_launcher(rarity="normal"):
    """Create an Enchanted Seed Launcher weapon at the given rarity."""
    return Equipment(
        name="Enchanted Seed Launcher",
        slot="weapon",
        rarity=rarity,
        tier=1,
        atk_min=0,
        atk_max=0,
        flavour="A hollowed pumpkin husk packed with enchanted seeds. "
                "In combat, seeds launch at your enemy and explode on "
                "impact.",
    )


def _build_sharpened_sucker(rarity="normal"):
    """Create a Sharpened Sucker weapon at the given rarity."""
    stats = SHARPENED_SUCKER_STATS[rarity]
    return Equipment(
        name="Sharpened Sucker",
        slot="weapon",
        rarity=rarity,
        tier=2,
        atk_min=stats["atk_min"],
        atk_max=stats["atk_max"],
        bleed_turns=stats["bleed_turns"],
        bleed_dmg_min=stats["bleed_dmg"],
        bleed_dmg_max=stats["bleed_dmg"],
        sucker_heal_pct=stats["heal_pct"],
        sucker_multi_min=stats["multi_min"],
        sucker_multi_max=stats["multi_max"],
        flavour="A lollipop honed to a razor point. The enchanted sugar "
                "coating hides a wicked edge that draws blood on contact.",
    )


# ── Shop catalog ──

CANDY_SHOP_ITEMS = [
    # (display_name, candy_cost, description, builder_key)
    # Consumables — always available
    ("🐺 Silver Tonic",        3,  "Cure Lycanthropy",              "silver_tonic"),
    ("👹 Monster Candy",        5,  "Fear throwable (1 use)",        "monster_candy"),
    ("💚 Full Heal",            7,  "Restore all HP",                "full_heal"),
    ("🍬 Enchanted Candy Corn", 8,  "Trick-or-Treat buff/debuff",   "candy_corn"),
    ("🍎 Caramel Apple",        15, "Guaranteed +1 primary & +1 secondary stat (limit 1)", "caramel_apple"),
]


def _buy_shop_item(warrior, idx):
    """Process a candy shop purchase. Returns True if successful."""
    name, cost, desc, key = CANDY_SHOP_ITEMS[idx]

    if warrior.halloween_candy < cost:
        print(f"\n  'You lack the candy, mortal. {cost} candy required.'")
        input("  Press Enter...")
        return False

    # Confirm purchase
    confirm = input(
        f"\n  Buy {name} for {cost} candy? (y/n): "
    ).strip().lower()
    if confirm != "y":
        print("\n  'Changed your mind? Mortals are so indecisive.'")
        input("  Press Enter...")
        return False

    warrior.halloween_candy -= cost

    if key == "silver_tonic":
        warrior.potions["silver_tonic"] = warrior.potions.get("silver_tonic", 0) + 1
        print(f"\n  🐺 Silver Tonic added to your potions!")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    elif key == "monster_candy":
        warrior.potions["monster_candy"] = warrior.potions.get("monster_candy", 0) + 1
        print(f"\n  👹 Monster Candy added to your potions!")
        print(f"     Throw it at an enemy to fear them for 1 turn.")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    elif key == "full_heal":
        healed = warrior.max_hp - warrior.hp
        warrior.hp = warrior.max_hp
        if healed > 0:
            print(f"\n  💚 Warmth floods through you! Restored {healed} HP!")
        else:
            print(f"\n  💚 You feel a warm glow... but you're already at full health!")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    elif key == "candy_corn":
        # Trick-or-Treat: 60% chance buff, 40% chance debuff
        roll = random.random()
        if roll < 0.60:
            # TREAT — random buff
            buff_type = random.choice(["atk", "def", "hp", "ap"])
            if buff_type == "atk":
                warrior.min_atk += 1
                warrior.max_atk += 1
                print(f"\n  🍬 TREAT! The candy surges with power!")
                print(f"     +1 ATK permanently! ({warrior.min_atk}-{warrior.max_atk})")
            elif buff_type == "def":
                warrior.defence += 1
                print(f"\n  🍬 TREAT! The candy hardens your skin!")
                print(f"     +1 DEF permanently! (DEF: {warrior.defence})")
            elif buff_type == "hp":
                bonus = random.randint(3, 5)
                warrior.max_hp += bonus
                warrior.hp += bonus
                print(f"\n  🍬 TREAT! The candy fills you with vitality!")
                print(f"     +{bonus} Max HP! (HP: {warrior.hp}/{warrior.max_hp})")
            elif buff_type == "ap":
                warrior.max_ap += 1
                warrior.ap = min(warrior.ap + 1, warrior.max_ap)
                print(f"\n  🍬 TREAT! Energy crackles through your body!")
                print(f"     +1 Max AP! (AP: {warrior.ap}/{warrior.max_ap})")
        else:
            # TRICK — random debuff
            trick_type = random.choice(["atk", "def", "hp"])
            if trick_type == "atk" and warrior.min_atk > 1:
                warrior.min_atk = max(1, warrior.min_atk - 1)
                warrior.max_atk = max(1, warrior.max_atk - 1)
                print(f"\n  🎃 TRICK! The candy saps your strength!")
                print(f"     -1 ATK! ({warrior.min_atk}-{warrior.max_atk})")
            elif trick_type == "def" and warrior.defence > 0:
                warrior.defence = max(0, warrior.defence - 1)
                print(f"\n  🎃 TRICK! The candy weakens your armor!")
                print(f"     -1 DEF! (DEF: {warrior.defence})")
            elif trick_type == "hp":
                loss = random.randint(2, 4)
                warrior.max_hp = max(5, warrior.max_hp - loss)
                warrior.hp = min(warrior.hp, warrior.max_hp)
                print(f"\n  🎃 TRICK! The candy drains your vitality!")
                print(f"     -{loss} Max HP! (HP: {warrior.hp}/{warrior.max_hp})")
            else:
                # Fallback if stats too low — minor HP loss
                warrior.hp = max(1, warrior.hp - 2)
                print(f"\n  🎃 TRICK! The candy gives you a stomachache!")
                print(f"     -2 HP! (HP: {warrior.hp}/{warrior.max_hp})")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    elif key == "caramel_apple":
        # Limit 1 per run
        if getattr(warrior, "_caramel_apple_used", False):
            warrior.halloween_candy += cost  # refund
            print(f"\n  🍎 'You've already had one, mortal. Even dark magic")
            print(f"     has limits — your body can only absorb one.'")
            input("  Press Enter...")
            return False

        warrior._caramel_apple_used = True

        # Primary stat — guaranteed random buff
        primary = random.choice(["atk", "def", "hp", "ap"])
        if primary == "atk":
            warrior.min_atk += 1
            warrior.max_atk += 1
            print(f"\n  🍎 The caramel apple surges with power!")
            print(f"     +1 ATK! ({warrior.min_atk}-{warrior.max_atk})")
        elif primary == "def":
            warrior.defence += 1
            print(f"\n  🍎 The caramel coating hardens your skin!")
            print(f"     +1 DEF! (DEF: {warrior.defence})")
        elif primary == "hp":
            bonus = random.randint(3, 5)
            warrior.max_hp += bonus
            warrior.hp += bonus
            print(f"\n  🍎 Warm energy floods through you!")
            print(f"     +{bonus} Max HP! (HP: {warrior.hp}/{warrior.max_hp})")
        elif primary == "ap":
            warrior.max_ap += 1
            warrior.ap = min(warrior.ap + 1, warrior.max_ap)
            print(f"\n  🍎 Your reflexes sharpen!")
            print(f"     +1 Max AP! (AP: {warrior.ap}/{warrior.max_ap})")

        # Secondary stat — rarer buffs
        secondary = random.choice(["magic_res", "berserk", "adrenaline"])
        if secondary == "magic_res":
            mr = getattr(warrior, "magic_resistance", 0)
            warrior.magic_resistance = mr + 1
            print(f"     🔮 +1 Magic Resistance! (RES: {warrior.magic_resistance})")
        elif secondary == "berserk":
            old_max = getattr(warrior, "berserk_max_charges", 3)
            warrior.berserk_max_charges = old_max + 1
            print(f"     💢 +1 Berserk Max Charge! ({warrior.berserk_max_charges} max)")
        elif secondary == "adrenaline":
            old_bonus = getattr(warrior, "current_bonus_damage", 0)
            warrior.current_bonus_damage = old_bonus + 1
            print(f"     💥 +1 Adrenaline Bonus! (+{warrior.current_bonus_damage} bonus dmg)")

        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    return False


def _buy_rare_item(warrior, item_tuple):
    """Process a rare stock candy shop purchase."""
    name, cost, desc, key = item_tuple

    if warrior.halloween_candy < cost:
        print(f"\n  'You lack the candy, mortal. {cost} candy required.'")
        input("  Press Enter...")
        return False

    confirm = input(
        f"\n  Buy {name} for {cost} candy? (y/n): "
    ).strip().lower()
    if confirm != "y":
        print("\n  'Changed your mind? Mortals are so indecisive.'")
        input("  Press Enter...")
        return False

    warrior.halloween_candy -= cost

    builders = {
        "seed_launcher":    ("normal", _build_seed_launcher),
        "vine_totem":       ("normal", _build_vine_totem),
        "sharpened_sucker": ("normal", _build_sharpened_sucker),
        "pumpkin_helm":     ("normal", _build_pumpkin_helm),
        "jack_head":        ("rare",   _build_jack_o_lantern_head),
    }

    if key in builders:
        rarity, builder = builders[key]
        item = builder(rarity)
        warrior.inventory.append(item)
        print(f"\n  🎃 {item.name} ({rarity.title()}) added to inventory!")
        print(f"     \"{item.flavour}\"")
        if key == "jack_head":
            print(f"\n  ✨ 'A piece of the Horseman himself... guard it well.'")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")
        input("  Press Enter...")
        return True

    return False


# ── Upgrade Halloween gear ──

# Items that can be upgraded via candy
UPGRADEABLE_HALLOWEEN_NAMES = (
    HALLOWEEN_PIECE_NAMES | {"Pumpkin Helm", "Pumpkin Vine Totem"}
)


def _upgrade_menu(warrior):
    """Let the player spend candy to raise rarity of Halloween gear."""
    from equipment import RARITY_ORDER

    while True:
        clear_screen()
        print("=" * 52)
        print(f"  🔮 Dark Ritual — Upgrade Halloween Gear")
        print(f"  🍬 Candy: {warrior.halloween_candy}")
        print("=" * 52)
        print()
        print(wrap(
            "'Bring me your Halloween treasures and enough candy... "
            "I shall channel the dark arts to strengthen them. "
            "DO NOT question my methods.'"
        ))
        print()

        # Gather upgradeable items from inventory + equipped
        candidates = []
        for item in warrior.inventory:
            if getattr(item, "name", "") in UPGRADEABLE_HALLOWEEN_NAMES:
                r_idx = RARITY_ORDER.index(item.rarity) if item.rarity in RARITY_ORDER else -1
                if r_idx < len(RARITY_ORDER) - 1:  # not already mythril
                    candidates.append(("bag", item))

        for slot_name, item in warrior.equipment.items():
            if item is not None and getattr(item, "name", "") in UPGRADEABLE_HALLOWEEN_NAMES:
                r_idx = RARITY_ORDER.index(item.rarity) if item.rarity in RARITY_ORDER else -1
                if r_idx < len(RARITY_ORDER) - 1:
                    candidates.append(("equipped", item))

        if not candidates:
            print("  You have no Halloween gear that can be upgraded.")
            input("\n  Press Enter...")
            return

        for i, (loc, item) in enumerate(candidates, 1):
            cost = CANDY_UPGRADE_COSTS.get(item.rarity, 99)
            next_rarity = RARITY_ORDER[RARITY_ORDER.index(item.rarity) + 1]
            tag = " (equipped)" if loc == "equipped" else ""
            print(f"  {i}) {item.name} [{item.rarity.title()} → {next_rarity.title()}]"
                  f"  ({cost} candy){tag}")

        print(f"  0) Back")
        print()

        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return

        try:
            idx = int(choice) - 1
            loc, item = candidates[idx]
        except (ValueError, IndexError):
            print("  Invalid choice.")
            input("  Press Enter...")
            continue

        cost = CANDY_UPGRADE_COSTS.get(item.rarity, 99)
        if warrior.halloween_candy < cost:
            print(f"\n  'Not enough candy! I need {cost}.'")
            input("  Press Enter...")
            continue

        next_rarity = RARITY_ORDER[RARITY_ORDER.index(item.rarity) + 1]
        confirm = input(
            f"\n  Upgrade {item.name} to {next_rarity.title()} for {cost} candy? (y/n): "
        ).strip().lower()
        if confirm != "y":
            continue

        warrior.halloween_candy -= cost
        old_rarity = item.rarity

        # Rebuild the item at the new rarity, preserving identity
        if item.name == "Pumpkin Helm":
            from equipment import PUMPKIN_HELM_STATS
            stats = PUMPKIN_HELM_STATS[next_rarity]
            item.rarity = next_rarity
            item.defence = stats["defence"]
            item.max_hp = stats["max_hp"]
            item.magic_res = stats["magic_res"]

        elif item.name == "Pumpkin Vine Totem":
            from equipment import PUMPKIN_VINE_TOTEM_STATS
            stats = PUMPKIN_VINE_TOTEM_STATS[next_rarity]
            item.rarity = next_rarity
            item.vine_dc = stats["dc"]
            item.vine_dmg = stats["vine_dmg"]
            item.vine_max_turns = stats["max_turns"]
            item.vine_max_charges = stats["max_charges"]
            # Refill charges on upgrade
            item.vine_charges = stats["max_charges"]

        elif item.name == "Enchanted Seed Launcher":
            stats = SEED_LAUNCHER_STATS[next_rarity]
            item.rarity = next_rarity
            # Seed stats are looked up dynamically from the table at combat time

        elif item.name == "Sharpened Sucker":
            stats = SHARPENED_SUCKER_STATS[next_rarity]
            item.rarity = next_rarity
            item.atk_min = stats["atk_min"]
            item.atk_max = stats["atk_max"]
            item.bleed_turns = stats["bleed_turns"]
            item.bleed_dmg_min = stats["bleed_dmg"]
            item.bleed_dmg_max = stats["bleed_dmg"]
            item.sucker_heal_pct = stats["heal_pct"]
            item.sucker_multi_min = stats["multi_min"]
            item.sucker_multi_max = stats["multi_max"]

        elif item.name == "Werewolf Cloak":
            # Werewolf cloak stats are read dynamically; just bump rarity
            item.rarity = next_rarity

        elif item.name == "Jack O'Lantern Head":
            # Boss drop — bump rarity, stats scale dynamically
            item.rarity = next_rarity

        else:
            item.rarity = next_rarity

        print(f"\n  ✨ Dark energy crackles...")
        print(f"  🎃 {item.name} upgraded: {old_rarity.title()} → {next_rarity.title()}!")
        print(f"  🍬 Candy remaining: {warrior.halloween_candy}")

        # Re-apply stats if equipped
        if loc == "equipped":
            print("     (Equipped stats updated)")

        input("\n  Press Enter...")


# ── Candy Exchange (moved from merchant) ──

def _tom_candy_exchange(warrior):
    """10 gold ↔ 1 candy exchange at Tom's stall."""
    while True:
        print()
        print("=" * 52)
        print(f"  🍬 Candy Exchange   |   Gold: {warrior.gold}g   Candy: {warrior.halloween_candy}")
        print("=" * 52)
        print()
        print(wrap(
            "'Gold is merely mortal currency. Candy... candy holds "
            "TRUE power. Ten gold for one candy. Or I shall buy yours "
            "back — Darkness Incarnate is nothing if not fair.'"
        ))
        print()
        print(f"  1) Buy candy   (10g → 1 candy)")
        print(f"  2) Sell candy  (1 candy → 10g)")
        print(f"  0) Back")
        print()
        choice = input("  > ").strip()

        if choice == "0" or choice == "":
            return

        if choice == "1":
            if warrior.gold < 10:
                print("\n  'Even Darkness Incarnate cannot conjure candy from nothing. "
                      "Bring more gold.'")
                input("  Press Enter...")
                continue
            warrior.gold -= 10
            warrior.halloween_candy += 1
            print(f"\n  🍬 +1 candy! Gold: {warrior.gold}g  Candy: {warrior.halloween_candy}")
            input("  Press Enter...")

        elif choice == "2":
            if warrior.halloween_candy < 1:
                print("\n  'You have no candy to offer? Pathetic.'")
                input("  Press Enter...")
                continue
            warrior.halloween_candy -= 1
            warrior.gold += 10
            print(f"\n  🪙 +10 gold! Gold: {warrior.gold}g  Candy: {warrior.halloween_candy}")
            input("  Press Enter...")


# ── Premium Buyback ──

def _tom_premium_buyback(warrior):
    """Tom buys premium magic items at 1.5× the normal merchant rate."""
    # Import merchant pricing
    from merchant import _sell_price

    while True:
        clear_screen()
        print("=" * 52)
        print(f"  🔮 Sell Magical Artifacts   |   Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(wrap(
            "'I hunger for artifacts of power. Soul Pendants... "
            "Psychic Stones... Waterlogged relics... Bring them to me "
            "and I shall pay FAR more than that fool merchant ever would.'"
        ))
        print()

        # Gather premium items from inventory
        sellable = []
        for item in warrior.inventory:
            if getattr(item, "name", "") in PREMIUM_BUYBACK_NAMES:
                base_price = _sell_price(item)
                tom_price = max(1, int(base_price * PREMIUM_BUYBACK_RATE))
                sellable.append((item, tom_price))

        if not sellable:
            print("  You have no magical artifacts Tom wants.")
            input("\n  Press Enter...")
            return

        for i, (item, price) in enumerate(sellable, 1):
            print(f"  {i}) {item.name} ({item.rarity.title()})  — {price}g")

        print(f"  0) Back")
        print()

        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return

        try:
            idx = int(choice) - 1
            item, price = sellable[idx]
        except (ValueError, IndexError):
            print("  Invalid choice.")
            input("  Press Enter...")
            continue

        confirm = input(
            f"\n  Sell {item.name} ({item.rarity.title()}) for {price}g? (y/n): "
        ).strip().lower()
        if confirm != "y":
            continue

        warrior.inventory.remove(item)
        warrior.gold += price
        print(f"\n  🔮 'YES! More power for Darkness Incarnate!'")
        print(f"  🪙 +{price}g! Gold: {warrior.gold}g")
        input("\n  Press Enter...")


# ── Tom's main scene ──

def halloween_vendor_scene(warrior, first_visit=True):
    """
    Tom, Darkness Incarnate — the Halloween seasonal vendor.
    Shows a dramatic illusion entrance on first visit that crumbles.
    Return visits get a shorter version the player shuts down.
    """
    clear_screen()

    if first_visit:
        # ── First visit: full illusion sequence ──
        print(wrap(
            "A chill runs down your spine. The air behind you grows heavy "
            "with dark energy. You spin around."
        ))
        space()
        print(wrap(
            "A towering demonic figure looms over you, wreathed in shadow. "
            "Eyes like burning coals bore into your soul. A massive portal "
            "of swirling darkness tears open behind the creature, revealing "
            "an endless void."
        ))
        space()
        print(wrap(
            "\"AT LAST,\" the demon booms, its voice shaking the walls. "
            "\"A WARRIOR WORTHY OF MY PRESENCE. WELCOME... TO TOM'S "
            "EMPORIUM OF DARKNESS.\""
        ))
        space()
        print(wrap(
            "The demon spreads its arms wide."
        ))
        space()
        print(wrap(
            "\"I... AM DARKNESS INCAR—\""
        ))
        space()
        print(wrap(
            "There is a faint pop, like a soap bubble bursting."
        ))
        space()
        print(wrap(
            "The demon shimmers, flickers, and collapses inward. The "
            "massive portal shrinks with a sad wheeze until it's just... "
            "a broom closet. A mop falls over inside with a clatter. "
            "You notice one of the arena torches is missing from its "
            "bracket on the wall."
        ))
        space()
        print(wrap(
            "Standing where the demon was is a pudgy, balding man in a "
            "tattered black robe. He blinks at you. A half-eaten apple "
            "sits on a crate behind him."
        ))
        space()
        print(wrap(
            "\"...Curses,\" he mutters."
        ))
        space()
        print(wrap(
            "He whips around toward the merchant's stall."
        ))
        space()
        print(wrap(
            "\"I NEED MORE MANA POTIONS!\" he screams across the room."
        ))
        space()
        print(wrap(
            "The merchant doesn't even look up. \"You still owe me for "
            "the last batch, Tom.\""
        ))
        space()
        print(wrap(
            "\"IT'S DARKNESS INCARNATE!\""
        ))
        space()
        print(wrap(
            "He takes a breath, smooths his robe, and turns back to you "
            "with what he clearly believes is a terrifying smile."
        ))
        space()
        print(wrap(
            "\"...You may browse my wares.\""
        ))
        space()
        continue_text()

    else:
        # ── Return visit: player shuts it down ──
        clear_screen()
        print(wrap(
            "The air behind you shimmers. Dark energy begins to gather. "
            "The outline of a demonic figure starts to form—"
        ))
        space()
        print(wrap(
            "\"Tom, stop.\""
        ))
        space()
        print(wrap(
            "Pop. The illusion fizzles. Tom stands there, robe slightly "
            "askew, looking deeply offended."
        ))
        space()
        print(wrap(
            "\"I'M DARKNESS INCARNATE!\" he sputters."
        ))
        space()
        print(wrap(
            "\"...\""
        ))
        space()
        print(wrap(
            "He crosses his arms and huffs. \"Fine. What do you want?\""
        ))
        space()
        continue_text()

    # ── Main shop menu loop ──
    while True:
        clear_screen()
        print("=" * 52)
        print(f"  🎃 Tom's Emporium of Darkness")
        print(f"  🍬 Candy: {warrior.halloween_candy}   |   💰 Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(f"  1) 🛒 Browse wares          (spend candy)")
        print(f"  2) 🔮 Upgrade Halloween gear (raise rarity)")
        print(f"  3) 🍬 Candy exchange         (10g ↔ 1 candy)")
        print(f"  4) 💎 Sell magical artifacts  (premium price)")
        print(f"  0) Leave")
        print()
        choice = input("  > ").strip()

        if choice == "0" or choice == "":
            print()
            print(wrap(
                "\"You walk away from DARKNESS INCARNATE? "
                "You will regret this... probably.\""
            ))
            print()
            input("  Press Enter...")
            return

        elif choice == "1":
            _tom_browse_wares(warrior)

        elif choice == "2":
            _upgrade_menu(warrior)

        elif choice == "3":
            _tom_candy_exchange(warrior)

        elif choice == "4":
            _tom_premium_buyback(warrior)

        else:
            print("  Invalid choice.")
            input("  Press Enter...")


# Rare stock — items with a % chance of appearing each visit
RARE_STOCK_ITEMS = [
    # (display_name, candy_cost, description, builder_key, appear_chance)
    ("🎃 Seed Launcher",       10, "Weapon — Exploding Seeds",           "seed_launcher",     0.50),
    ("🎃 Pumpkin Vine Totem",  12, "Entangle accessory (charged)",       "vine_totem",        0.50),
    ("🗡️ Sharpened Sucker",    15, "Weapon — Bleed, Vampiric",           "sharpened_sucker",  0.40),
    ("🎃 Pumpkin Helm",        20, "Helm — DEF, HP, Magic Res",          "pumpkin_helm",      0.35),
    ("🎃 Jack O'Lantern Head", 25, "Set Helm — Fire, Dread Aura",        "jack_head",         0.25),
]


def _tom_browse_wares(warrior):
    """Display the candy shop catalog and handle purchases."""
    # Roll rare stock for this visit
    rare_available = []
    for item in RARE_STOCK_ITEMS:
        if random.random() < item[4]:
            rare_available.append(item[:4])  # strip the chance field

    while True:
        clear_screen()
        print("=" * 52)
        print(f"  🛒 Candy Shop   |   🍬 Candy: {warrior.halloween_candy}")
        print("=" * 52)
        print()
        print(wrap(
            "'Behold the artifacts of DARKNESS. Each one forged with "
            "forbidden power. ...They accept candy as payment.'"
        ))
        print()

        for i, (name, cost, desc, key) in enumerate(CANDY_SHOP_ITEMS, 1):
            print(f"  {i}) {name:<26} ({cost:>2} candy)  — {desc}")

        if rare_available:
            print()
            print("  ✨ RARE STOCK — 'These do not appear often...'")
            for j, (name, cost, desc, key) in enumerate(rare_available):
                num = len(CANDY_SHOP_ITEMS) + j + 1
                print(f"  {num}) {name:<26} ({cost:>2} candy)  — {desc}")

        print(f"  0) Back")
        print()

        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return

        try:
            idx = int(choice) - 1
            total_items = len(CANDY_SHOP_ITEMS) + len(rare_available)
            if 0 <= idx < len(CANDY_SHOP_ITEMS):
                _buy_shop_item(warrior, idx)
            elif idx < total_items:
                rare_idx = idx - len(CANDY_SHOP_ITEMS)
                _buy_rare_item(warrior, rare_available[rare_idx])
            else:
                print("  Invalid choice.")
                input("  Press Enter...")
        except (ValueError, IndexError):
            print("  Invalid choice.")
            input("  Press Enter...")


# ============================================================
# 📋 INTEGRATION GUIDE
# ============================================================
# Every change needed in other files to hook up the system.
#
# ── hero.py ──
# In the potions dict (around line 228), add after skill_point:
#
#     # ── Seasonal collectibles ──
#     "birthday_cake": 0,         # 🎂 August seasonal — replaces tonic in Aug
#     "tome_of_knowledge": 0,     # 📖 March seasonal — found on bookshelf
#
# ── story.py ──
# 1) REPLACE the hardcoded Frostpine Tonic grant (lines ~859-873)
#    with a single call to the seasonal starting item helper:
#
#     from collectibles import grant_seasonal_starting_item
#     grant_seasonal_starting_item(warrior)
#
#    This gives the Birthday Cake in August, Frostpine Tonic
#    in all other months. Same Elwyn scene, different item.
#
# 2) RIGHT AFTER that grant, add the March bookshelf room:
#
#     from collectibles import elwyn_bookshelf_room
#     elwyn_bookshelf_room(warrior)    # only triggers in March
#
#    In March the hero gets the Tonic AND can explore a bookshelf
#    to find the Tome of Knowledge. Both items, one run.
#
# ── combat.py ──
# 1) At the top, add import:
#     from collectibles import (
#         apply_birthday_cake, tick_sugar_rush,
#         apply_tome_of_knowledge,
#         check_fear_aura, dread_charge_tick,
#         tick_tattle, tick_blizzard_slow,
#         check_krampus_stun, krampus_rage_check,
#         roll_seasonal_collectable, roll_seasonal_equipment,
#         is_seasonal_monster, record_seasonal_monster_defeated,
#     )
#
# 2) In use_potion(), add two new elif branches (after skill_rank_up):
#
#     elif potion_type == "birthday_cake":
#         return apply_birthday_cake(hero, in_combat)
#
#     elif potion_type == "tome_of_knowledge":
#         if in_combat:
#             hero.potions[potion_type] += 1
#             if is_bonus:
#                 hero.bonus_action_used = False
#             print("\n📖 You can't study a Tome in the middle of a fight.")
#             print("    Save it for between battles.")
#             continue_text()
#             space()
#             return False
#         return apply_tome_of_knowledge(hero)
#
# 3) In hero's turn resolution, after actions resolve:
#     tick_sugar_rush(hero)
#     tick_tattle(hero)
#
# 4) At START of hero's turn (before action menu):
#     tick_blizzard_slow(hero)    # AP drain happens before you choose
#     if check_krampus_stun(hero):
#         continue  # skip hero's turn entirely
#
# 5) In the enemy's attack phase, before attack rolls:
#     if check_fear_aura(hero, enemy):
#         # skip enemy attack this turn (Haunted Armor proc)
#         pass  # or continue depending on loop structure
#
# 6) At end of enemy's turn:
#     if enemy.name == "Headless Horseman":
#         dread_charge_tick(enemy)
#     if enemy.name == "Krampus":
#         krampus_rage_check(enemy)
#
# 7) After regular loot is awarded post-fight:
#     roll_seasonal_collectable(hero)
#     roll_seasonal_equipment(hero)
#
# 8) After enemy is defeated:
#     if is_seasonal_monster(enemy):
#         record_seasonal_monster_defeated(enemy.name)
#
# ── score.py ──
# 1) Import the seasonal score helpers:
#     from collectibles import (
#         get_seasonal_score_bonus, CAKE_SAVED_BONUS,
#         compute_cake_saved_score,
#     )
#
# 2) In _compute_potion_score(), after the frostpine block (line ~476):
#     cake_count = potions.get("birthday_cake", 0)
#     cake_score = CAKE_SAVED_BONUS if cake_count > 0 else 0
#     return regular_score, regular_count, frostpine_score, frostpine_count, cake_score, cake_count
#
#    (Update the unpacking at line ~555 to match the new 6-tuple.)
#
# 3) Add cake_score to the subtotal (line ~573):
#     subtotal = (dmg_score + block_score + ... + frostpine_score + cake_score)
#
# 4) In the score display, after the Frostpine row (line ~650):
#     if cake_count > 0:
#         _row("🎂 Birthday Cake Saved", f"+{cake_score}")
#
# 5) Around line 595, after nob_hardship, add seasonal multiplier
#    bonus (only granted if cake was EATEN, not saved):
#
#     seasonal_bonus = get_seasonal_score_bonus(warrior)
#     multiplier = round(base_multiplier + qk_bonus + nob_hardship + seasonal_bonus, 2)
#
# 6) Around line 682, in the bonus_parts display list:
#     if seasonal_bonus > 0:
#         bonus_parts.append(f"+{seasonal_bonus:.2f} (🎂 seasonal)")
#
# DESIGN NOTE: The cake gives EITHER the +0.10 multiplier (if eaten)
# OR the +100 flat score (if saved). Never both. Eating it sets
# hero.seasonal_score_bonus but removes it from potions. Saving it
# keeps it in potions but seasonal_score_bonus stays 0.
#
# ── monsters.py ──
# At the BOTTOM of the file, after TIER4_BOSSES and all helpers:
#
#     from collectibles import inject_seasonal_monsters
#     inject_seasonal_monsters(MONSTER_TYPES, TIER4_BOSSES)
#
# ── shared.py ──
# In SPECIAL_MOVE_NAMES dict, add:
#     "headless_cleave":        "Headless Cleave",
#     "exploding_pumpkin_seeds": "Exploding Pumpkin Seeds",
#     "lollipop_flurry":          "Lollipop Flurry",
#     "moonlight_frenzy":       "Moonlight Frenzy",
#     "elf_tattle":             "Tattle",
#     "sugar_coat":             "Sugar Coat",
#     "blizzard_breath":        "Blizzard Breath",
#     "chains_of_punishment":   "Chains of Punishment",
#
# ── Inventory display (equipment.py or ui.py) ──
# To show seasonal items in the potion menu, add display names:
#     "birthday_cake":      "🎂 Birthday Cake",
#     "tome_of_knowledge":  "📖 Tome of Knowledge",
#
# ── crafter.py ──
# In apply_all_set_bonuses(), add:
#     from collectibles import apply_halloween_set_bonus
#     apply_halloween_set_bonus(warrior)
#
# ── combat.py (Halloween-specific additions) ──
# 9) After defeating a Halloween monster, roll for gear drop:
#     from collectibles import roll_halloween_drop, is_october
#     if is_october() and is_seasonal_monster(enemy):
#         roll_halloween_drop(hero, enemy.name)
#
# 10) Dread Aura (4-piece Halloween set) — before enemy attack:
#     from collectibles import dread_aura_active, check_dread_aura
#     if dread_aura_active(hero):
#         first = (enemy.rounds_in_combat <= 1)
#         if check_dread_aura(hero, enemy, is_first_enemy_turn=first):
#             continue  # enemy skips their turn
#
# ── Main menu (optional) ──
# Replace "Seasonal Collection" with "Collection Book":
#     from collectibles import show_collection_book
#     show_collection_book()
