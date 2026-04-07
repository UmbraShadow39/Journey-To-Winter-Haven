import textwrap
import os
import random
import time
import math

from colorama import init

# Local modules
from combat_log import COMBAT_LOG, log, view_combat_log


init(autoreset=True, convert=True, strip=False)

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# === Color Constants for HP Bar ===
WHITE   = "\033[97m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"
CYAN    = "\033[96m"
RESET   = "\033[0m"


# ============================================================
#  UNIVERSAL INPUT OVERRIDE  (enables M anywhere in the game)
# ============================================================

DEBUG = False

ALLOW_MONSTER_SELECT = False   # declared here; battle_inner sets True/False

_real_input = input

def input(prompt=""):
    raw = _real_input(prompt)

    if not isinstance(raw, str):
        return raw

    cleaned = raw.strip().lower()

    if cleaned in ("m", "monster"):
        monster = monster_select_menu()
        if monster:
            print(wrap("\n⚔️ Debug: Starting a custom battle...\n") if "wrap" in globals() else "\n⚔️ Debug: Starting a custom battle...\n")
            battle(GAME_WARRIOR, monster)
        # IMPORTANT: return "" so story “press enter” continues,
        # and yes/no menus will just reprompt without crashing
        return ""

    return raw

def handle_monster_select_shortcut(raw, *, warrior=None, in_combat=False):
    """
    Handles global monster-select shortcut safely.

    Returns:
        (handled: bool, payload: any)
    """

    if not isinstance(raw, str):
        return False, raw

    if raw != "__MONSTER_SELECT__":
        return False, raw

    monster = monster_select_menu()

    if not monster:
        return True, None

    # Combat mode = swap enemy
    if in_combat:
        return True, ("monster_select", monster)

    # Outside combat = start debug fight
    print("\n⚔️ Debug: starting a fight...\n")
    battle(warrior if warrior else GAME_WARRIOR, monster)

    return True, None

# ============================================================
# GLOBAL DAMAGE BONUS POLICY (single source of truth)
# Drop this near your combat helpers (same area as adrenaline/berserk helpers)
# ============================================================

BONUS_POLICY_MODE = "STATIC"  # later you can switch to "SCALE"/"SOFTCAP" etc.

def get_damage_bonuses(attacker, context="general", *, ps_rank: int = 1):
    parts = {
        "adrenaline": 0,
        "berserk": 0,
        "war_cry": 0,
        "equipment": 0,
    }

    # ✅ CHANGE: Pull from the new universal container
    # This automatically uses the Warrior's Adrenaline or a Mage's Surge
    parts["adrenaline"] = int(getattr(attacker, "total_special", 0))

    if getattr(attacker, "berserk_active", False):
        parts["berserk"] = int(getattr(attacker, "berserk_bonus", 0))

    if getattr(attacker, "war_cry_turns", 0) > 0:
        parts["war_cry"] = int(getattr(attacker, "war_cry_bonus", 0))

    parts["equipment"] = int(getattr(attacker, "equipment_bonus_damage", 0))

    # --- Context rules (where we prevent broken stacking) -------
    if context == "power_strike_scaling":
        # Never let Berserk participate in the scaling base
        parts["berserk"] = 0

        # For NOW: while Berserk is active, force adrenaline contribution to 3.
        # Later: replace this with level/rank scaling or softcap logic.
        if getattr(attacker, "berserk_active", False):
            parts["adrenaline"] = 3

        # Optional: if War Cry / equipment ever become a PS scaling problem,
        # you can disable them for scaling too by uncommenting:
        # parts["war_cry"] = 0
        # parts["equipment"] = 0

    # --- Future hook (not used yet) -----------------------------
    # if BONUS_POLICY_MODE == "SCALE":
    #     lvl = int(getattr(attacker, "level", 1))
    #     # example: slowly scale berserk
    #     if getattr(attacker, "berserk_active", False):
    #         parts["berserk"] += lvl // 4
    #     # example: scale adrenaline investment
    #     adr_rank = int(getattr(attacker, "adrenaline_rank", 0))
    #     parts["adrenaline"] += adr_rank

    total = sum(parts.values())
    return total, parts


def bonus_parts_to_text(parts: dict):
    """Turns the parts dict into your UI-style list for print lines."""
    out = []
    if parts.get("adrenaline", 0):
        out.append(f"Adrenaline {parts['adrenaline']}")
    if parts.get("berserk", 0):
        out.append(f"Berserk {parts['berserk']}")
    if parts.get("war_cry", 0):
        out.append(f"War Cry {parts['war_cry']}")
    if parts.get("equipment", 0):
        out.append(f"Equipment {parts['equipment']}")
    return out

def monster_math_breakdown(attacker, defender, raw_roll, actual_physical, *,
                             extra_parts=None, tag=None):
    """
    Prints one clear line that includes:
      - Physical impact (roll -> actual)
      - Blocked amount (from the physical roll)
      - Extra/true damage parts (poison/fire/acid/etc.) that bypass defence
      - Total immediate damage

    extra_parts: list of tuples like [("Poison", 2), ("Fire", 3)]
    """
    extra_parts = extra_parts or []

    blocked = max(0, int(raw_roll) - int(actual_physical))
    extra_total = sum(int(x) for _, x in extra_parts)
    total = int(actual_physical) + extra_total

    # Build equation text: "Physical 2 + Poison 2 + Fire 3"
    eq_parts = [f"Hit {actual_physical}"]
    for name, amt in extra_parts:
        eq_parts.append(f"{name} {amt}")

    line = f"{attacker.name} hits you for {total} damage! (Roll {raw_roll} → " + " + ".join(eq_parts) + ")"
    if blocked > 0:
        line += f" [Blocked {blocked}]"
    if tag:
        line += f"  [{tag}]"

    print(wrap(line) if "wrap" in globals() else line)

def monster_deal_damage(attacker, defender,
                        raw_roll,
                        *,
                        extra_parts=None,
                        tag=None):
    """
    Universal monster damage handler.

    Handles:
    - defence calculation
    - HP subtraction
    - true damage parts
    - math breakdown output
    """

    extra_parts = extra_parts or []

   # 1) Physical damage (defence applies)
    if raw_roll and raw_roll > 0:
        actual_physical = defender.apply_defence(raw_roll, attacker=attacker)
    else:
        actual_physical = 0

    # 2) Extra true damage
    extra_total = sum(int(x) for _, x in extra_parts)

    # 3) TOTAL DAMAGE
    total = actual_physical + extra_total

    # 4) Apply HP ONCE (single source of truth)
    defender.hp = max(0, defender.hp - total)

    # 5) Print math line
    monster_math_breakdown(
        attacker,
        defender,
        raw_roll,
        actual_physical,
        extra_parts=extra_parts,
        tag=tag
    )

    return total

def collect_dot_ticks(hero, is_player=False):
    """
    Returns (total_dot:int, parts:list[tuple[str,int]])
    Also updates duration/stack lists (burns/acid) and expires poison.

    IMPORTANT: This does NOT subtract HP.
    Caller subtracts once.
    """
    parts = []
    total = 0
    fade_msgs = []  # Collected fade messages — printed AFTER damage line

    # ==========================
    # POISON (flat)
    # ==========================
    if getattr(hero, "poison_active", False):
        if getattr(hero, "poison_skip_first_tick", False):
            hero.poison_skip_first_tick = False
        else:
            dmg = int(getattr(hero, "poison_amount", 0))
            if dmg > 0:
                parts.append(("Poison", dmg))
                total += dmg
            hero.poison_turns -= 1
            if hero.poison_turns <= 0:
                hero.poison_active = False
                if is_player:
                    fade_msgs.append("💨 The poison fades from your body.")
                else:
                    fade_msgs.append(f"💨 The poison fades from {hero.name}.")

    # ==========================
    # EXTRA POISON DOTS (rare+ sac multi-dot)
    # ==========================
    poison_dots = getattr(hero, "poison_dots", [])
    if poison_dots:
        new_pdots = []
        for idx, dot in enumerate(poison_dots, start=1):
            if dot.get("skip", False):
                dot["skip"] = False
                new_pdots.append(dot)
                continue
            ddmg = int(dot.get("dmg", 0))
            if ddmg > 0:
                parts.append((f"Poison dot {idx}", ddmg))
                total += ddmg
            dot["turns_left"] -= 1
            if dot["turns_left"] > 0:
                new_pdots.append(dot)
        hero.poison_dots = new_pdots
        if not new_pdots and poison_dots:
            if is_player:
                fade_msgs.append("💨 The extra poison fades.")
            else:
                fade_msgs.append(f"💨 The extra poison fades from {hero.name}.")

    # ==========================
    # BURN STACKS (show ticks)
    # ==========================
    burns = getattr(hero, "burns", [])
    if burns:
        new_burns = []

        for idx, burn in enumerate(burns, start=1):
            if burn.get("skip", False):
                burn["skip"] = False
                new_burns.append(burn)
                continue

            tick = int(burn.get("bonus", 0)) if burn.get("flat", False) else random.randint(1, 3) + int(burn.get("bonus", 0))

            # ✅ record each tick separately
            parts.append((f"Burn tick {idx}", tick))
            total += tick

            burn["turns_left"] -= 1
            if burn["turns_left"] > 0:
                new_burns.append(burn)

        hero.burns = new_burns
        hero.fire_stacks = len(new_burns)

        if not new_burns and burns:
            expired_count = len(burns)
            verb = "fade" if expired_count != 1 else "fades"
            fade_msgs.append(f"💨 The flames finally die out ({expired_count} burn stack{'s' if expired_count != 1 else ''} {verb}).")

    # ==========================
    # ACID STACKS (show ticks)
    # ==========================
    acid_stacks = getattr(hero, "acid_stacks", [])
    if acid_stacks:
        new_acid = []

        # Your existing “effective_def is gone → tick harder” logic
        acid_loss = getattr(hero, "acid_defence_loss", 0)
        effective_def = max(0, hero.defence - acid_loss)

        for idx, stack in enumerate(acid_stacks, start=1):
            if stack.get("skip", False):
                stack["skip"] = False
                new_acid.append(stack)
                continue

            # Flat tick (player sac) vs random tick (monster acid)
            if stack.get("flat", False):
                tick = int(stack.get("bonus", acid_loss))
            else:
                tick = random.randint(3, 5) if effective_def == 0 else random.randint(3, 5)

            parts.append((f"Acid tick {idx}", tick))
            total += tick

            stack["turns_left"] -= 1

            # Handle restore_in countdown (player sac defence restore)
            if "restore_in" in stack:
                stack["restore_in"] -= 1
                if stack["restore_in"] <= 0:
                    restored = getattr(hero, "acid_defence_loss", 0)
                    hero.defence           = hero.defence + restored
                    hero.acid_defence_loss = 0
                    if is_player:
                        fade_msgs.append("\U0001f9ea The acid dissolves \u2014 your defence recovers!")
                    else:
                        fade_msgs.append(f"\U0001f9ea The acid dissolves \u2014 {hero.name}'s defence recovers!")

            if stack["turns_left"] > 0:
                new_acid.append(stack)

        hero.acid_stacks = new_acid

        if not new_acid and acid_stacks:
            expired_count = len(acid_stacks)
            fade_msgs.append(f"💨 The sizzling finally stops ({expired_count} acid stack{'s' if expired_count > 1 else ''} fade).")

    # ==========================
    # BLEED (flat 2 dmg/turn, ignores defence, no stacking)
    # ==========================
    bleed = getattr(hero, "bleed_turns", 0)
    if bleed > 0:
        bleed_dmg = 2
        parts.append(("Bleed", bleed_dmg))
        total += bleed_dmg
        hero.bleed_turns -= 1
        if hero.bleed_turns <= 0:
            if is_player:
                fade_msgs.append("🩸 Your wound stops bleeding.")
            else:
                fade_msgs.append(f"🩸 {hero.name}'s wound stops bleeding.")

    return total, parts, fade_msgs

DMG_EMOJI = {
    "Hit": "🗡️",
    "Physical": "🗡️",   # optional alias
    "Fire": "🔥",
    "Burn": "🔥",
    "Poison": "☠️",
    "Acid": "🧪",
    "Bleed": "🩸",
    "DOT": "🩸",        # fallback
}

def fmt_part(name, amt):
    """
    Clean readable damage formatting.
    Example:
        Burn tick 1 -> 🔥 Burn #1: 2
        Acid tick 2 -> 🧪 Acid #2: 3
        Poison -> ☠️ Poison: 2
    """
    words = name.split()

    base = words[0]
    emo = DMG_EMOJI.get(base, "💥")

    # Convert "Burn tick 2" -> "Burn #2"
    if len(words) >= 3 and words[1].lower() == "tick":
        label = f"{base} #{words[2]}"
    else:
        label = base

    return f"{emo} {label}: {amt} dmg"

def dot_math_breakdown(defender, parts, tag="DoT"):
    if not parts:
        return

    total = sum(int(v) for _, v in parts)
    eq = " + ".join(fmt_part(name, amt) for name, amt in parts)

    # Pick an icon for the front based on first part type
    base0 = parts[0][0].split()[0]
    icon = DMG_EMOJI.get(base0, DMG_EMOJI.get("DOT", "🩸"))

    # If the defender is the enemy (has display_name but not burns on player),
    # say "hits <enemy>" instead of "hits you"
    is_enemy = hasattr(defender, "display_name") and not hasattr(defender, "inventory")
    if is_enemy:
        line = f"{icon} {tag} hits {defender.display_name} for {total} damage! ({eq})"
    else:
        line = f"{icon} {tag} hits you for {total} damage! ({eq})"
    print(wrap(line) if "wrap" in globals() else line)
# ===============================
# Config / Globals
# ===============================
WIDTH = 65

ARENA_LEVEL_CAP = 5

GAME_WARRIOR = None  # Global reference to current warrior
# ===============================
# Utility Functions
# ===============================
def clear_screen():
    """Clear the console screen (Windows / Mac / Linux)."""
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

def continue_text():
    """
    Story continue prompt that supports universal monster debug.

    - ENTER = continue story
    - 'monster' = developer battle, then return to continue point
    - 'm' = treated as normal input (ignored)
    """
    global GAME_WARRIOR

    while True:
        raw = input("\n(Press ENTER to continue)\n> ")

        # ----------------------------------------------------
        # 🧬 Story-mode monster select (NEW sentinel system)
        # ----------------------------------------------------
        handled, _ = handle_monster_select_shortcut(
            raw,
            warrior=GAME_WARRIOR,
            in_combat=False
        )
        if handled:
            continue  # after debug fight (or cancel), return to same prompt

        # ----------------------------------------------------
        # Normal ENTER handling
        # ----------------------------------------------------
        if isinstance(raw, str) and raw.strip() == "":
            return  # continue story

        print("Just press ENTER to continue.")


def check(prompt, options=None):
    """
    Story-mode input handler.

    - 'monster' → open monster select (debug dev battle)
    - 'm' → treated as normal text (safe for names and story options)
    - normal choices validated against 'options'
    - dev shortcuts:
        q → restart intro
        c / combat → jump to arena
    """
    global GAME_WARRIOR

    # Normalize options once (if provided)
    normalized_options = None
    if options is not None:
        normalized_options = [str(opt).lower() for opt in options]

    while True:
        raw = input(prompt)

        # ----------------------------------------------------
        # 🧬 Universal Monster Select: story-mode behavior
        # ----------------------------------------------------
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            # This only fires correctly when user typed "monster"
            monster = raw[1]
            if monster:
                print(wrap("⚔️ Debug: Starting a story-mode custom battle..."))
                battle(GAME_WARRIOR, monster)
            continue  # return to the same story question afterward

        # ----------------------------------------------------
        # Everything below expects a normal string
        # ----------------------------------------------------
        if not isinstance(raw, str):
            print("Invalid choice, try again.")
            continue

        cleaned = raw.lower().strip()

        # ----------------------------------------------------
        # Developer shortcuts (story-safe)
        # ----------------------------------------------------

        # Restart game
        if cleaned == "q":
            raise RestartException

        # Quick combat jump
        if cleaned in ("c", "combat"):
            if GAME_WARRIOR is None:
                print(wrap("⚔️ Cannot start combat yet — no warrior exists."))
                continue
            # Sanitize warrior before jumping into combat —
            # the shortcut can fire before the intro sets a name or story flags
            if not GAME_WARRIOR.name or GAME_WARRIOR.name.strip().lower() == "warrior":
                GAME_WARRIOR.name = "Debug Warrior"
            raise QuickCombatException

        # Debug menu
        if cleaned == "debug":
            if GAME_WARRIOR:
                debug_menu(GAME_WARRIOR)
            else:
                print("Debug unavailable — warrior not created yet.")
            continue

        # Empty input
        if cleaned == "":
            print("Please enter a choice.")
            continue

        # ----------------------------------------------------
        # Validate against allowed options (if provided)
        # ----------------------------------------------------
        if normalized_options is not None:
            if cleaned not in normalized_options:
                # Friendly message showing what *is* allowed
                readable = ", ".join(normalized_options)
                print(f"Please enter one of: {readable}.")
                continue

        # All good – return the cleaned input
        return cleaned


def get_name_input(prompt="\nWhat is your name, adventurer?\n> "):
    """
    Safe name prompt:
    - Ignores the universal 'm' / 'monster' debug inputs.
    - Always returns a proper string name.
    """
    global GAME_WARRIOR

    while True:
        # Use _real_input to bypass the overridden input() that triggers debug
        raw = _real_input(prompt)

        # Ensure raw is a string
        if isinstance(raw, str):
            cleaned = raw.strip()
            if cleaned != "":
                return cleaned  # valid name entered

        # Default if input is empty
        return "Umbra"

        


def intro_story(warrior):
    """
    Wrapper for the intro story.
    This catches developer shortcut exceptions
    and cleanly restarts or jumps into combat.
    """
    try:
        return intro_story_inner(warrior)
    except RestartException:
        clear_screen()
        print(wrap("🔄 Restarting game..."))
        return intro_story(warrior)
    except QuickCombatException:
        clear_screen()
        print(wrap("⚔️ Quick Combat Mode Activated!"))
        return arena_battle(GAME_WARRIOR)
    
def berserk_meter(warrior, width=10):
    # Uses global colors: WHITE, RED, RESET

    # FULL BERSERK MODE
    if getattr(warrior, "berserk_active", False):
        return f"{RED}🩸🔥 BERSERK MODE ACTIVE! (+{warrior.berserk_bonus} dmg){RESET}"

    hp_percent = warrior.hp / warrior.max_hp
    fill_percent = 1 - hp_percent

    filled = int(fill_percent * width)
    empty = width - filled

    bar = "█" * filled + "░" * empty

    # LOW HP GLOW
    if hp_percent <= 0.10:
        return f"{RED}Berserk: [{bar}] ⚠️ On the brink…{RESET}"

    if hp_percent <= 0.25:
        return f"{RED}Berserk: [{bar}] 🔥 Blood rising…{RESET}"

    return f"{WHITE}Berserk: [{bar}]{RESET}"


    
def hp_bar(current, maximum, size=12, max_overheal=None):
    """
    HP bar with overheal shown as a red extension on the right.

    - The bar always represents 0 → max_overheal.
    - The portion that corresponds to normal HP (0 → maximum) is white.
    - Any HP beyond 'maximum' is shown as red segments to the right of the white.
    - Empty space is '░'.
    """

    if max_overheal is None or max_overheal < maximum:
        max_overheal = maximum

    # Clamp current HP into [0, max_overheal]
    current = max(0, min(current, max_overheal))

    # How many slots represent the *normal* HP region?
    base_slots = int(round((maximum / max_overheal) * size))
    base_slots = max(0, min(base_slots, size))

    # How many slots are filled at the current HP?
    filled_slots = int(round((current / max_overheal) * size))
    filled_slots = max(0, min(filled_slots, size))

    bar = []

    for i in range(size):
        if i < filled_slots:
            # Inside the filled part of the bar
            if i < base_slots:
                # This part is within normal HP range → white
                bar.append(WHITE + "█" + RESET)
            else:
                # This part is overheal → red
                bar.append(RED + "█" + RESET)
        else:
            # Not filled yet → empty
            bar.append("░")

    return "".join(bar)

def xp_bar(current, needed, size=20):
    needed = max(1, int(needed))
    current = max(0, min(int(current), needed))
    filled = int(round((current / needed) * size))
    empty = size - filled
    return "█" * filled + "░" * empty




def animate_xp_results(hero, gained_xp, size=22, duration=0.8):
    if gained_xp <= 0:
        return

    old_level = hero.level
    remaining = gained_xp
    print(f"\nXP +{gained_xp}")

    while remaining > 0:
        need = max(1, int(hero.xp_to_lvl))
        start = int(hero.xp)
        to_next = need - start
        chunk = min(remaining, to_next)

        # 1) Animate the bar filling
        frames = max(12, int(duration / 0.02))
        for i in range(1, frames + 1):
            t = i / frames
            virtual = int(round(start + chunk * t))
            bar = xp_bar(virtual, need, size=size)
            sys.stdout.write(f"\rXP: [{bar}] {virtual}/{need}")
            sys.stdout.flush()
            time.sleep(duration / frames)

        # 2) Update actual hero XP
        hero.xp += chunk
        remaining -= chunk

        # 3) Handle Level Up
        if hero.xp >= need:
            # Flash effect
            sys.stdout.write(f"\rXP: [{WHITE + ('█' * size) + RESET}] {need}/{need}")
            sys.stdout.flush()
            time.sleep(0.12)

            # Reset XP to 0 for the NEXT level before calling level_up
            hero.xp = 0

            # Level up (adds points, heals, etc.)
            hero.level_up()

            sys.stdout.write("\n")
            print(f"✨ Level {hero.level} acquired! ✨")

            # Cap Check: If we hit max, kill remaining XP
            if getattr(hero, "level_cap", None) and hero.level >= hero.level_cap:
                remaining = 0
                hero.xp = 0
        else:
            if remaining <= 0:
                sys.stdout.write("\n")

    # ✅ Pause ONCE after ALL bars/levels from this XP award are done
    print(f"XP complete. Level {hero.level} | XP {hero.xp}/{int(hero.xp_to_lvl)}")
    #input("Press ENTER to continue...")

    # 4) FINAL ACT: The point menu (Only once!)
    if hero.level > old_level:
        sys.stdout.write("\n")
        time.sleep(0.2)
        if getattr(hero, "stat_points", 0) > 0 or getattr(hero, "skill_points", 0) > 0:
            spend_points_menu(hero)

    
def refresh_special_state(hero):
    """Universal state refresher for all Hero classes."""
    # 1. Calculate HP-based spike (Intensity 0-3)
    hp_percent = hero.hp / hero.max_hp
    if hp_percent <= 0.25:
        hero.temp_special = 3
    elif hp_percent <= 0.50:
        hero.temp_special = 2
    elif hp_percent <= 0.75:
        hero.temp_special = 1
    else:
        hero.temp_special = 0

    # 2. Update the Hero's containers
    hero.total_special = hero.perm_special + hero.temp_special
    
    # 3. Mirror to current_bonus_damage so your current combat code doesn't break
    hero.current_bonus_damage = hero.total_special
    
    # 4. Update Rage State (for UI bars/visuals)
    hero.rage_state = hero.temp_special

def equip_item(hero, item):
    """
    Moves an item from inventory into the correct equipment slot.
    If something is already in that slot, swaps it back to inventory.
    """
    slot = item.slot

    # If something is already equipped in that slot, unequip it first
    current = hero.equipment[slot]
    if current is not None:
        unequip_item(hero, current)

    # Place new item in slot
    hero.equipment[slot] = item

    # Remove from inventory
    if item in hero.inventory:
        hero.inventory.remove(item)

    # Apply stat bonuses
    hero.min_atk  += item.atk_min
    hero.max_atk  += item.atk_max
    hero.defence  += item.defence
    if item.max_hp:
        hero.max_hp += item.max_hp
        hero.hp     += item.max_hp
        hero.max_overheal = int(hero.max_hp * 1.10)

    # Keep combat damage hook updated
    weapon = hero.equipment.get("weapon")
    hero.equipment_bonus_damage = weapon.atk_min if weapon else 0

    print(f"\n✅ Equipped: {item.short_label()}")

def unequip_item(hero, item):
    """
    Removes an item from its equipment slot and puts it back in inventory.
    Reverses all stat bonuses that were applied on equip.
    """
    slot = item.slot

    # Remove from slot
    hero.equipment[slot] = None

    # Put back in inventory
    hero.inventory.append(item)

    # Reverse stat bonuses
    hero.min_atk  -= item.atk_min
    hero.max_atk  -= item.atk_max
    hero.defence  -= item.defence
    if item.max_hp:
        hero.max_hp -= item.max_hp
        hero.hp      = min(hero.hp, hero.max_hp)  # clamp, don't kill the player
        hero.max_overheal = int(hero.max_hp * 1.10)

    # Keep combat damage hook updated
    weapon = hero.equipment.get("weapon")
    hero.equipment_bonus_damage = weapon.atk_min if weapon else 0

    print(f"\n🔄 Unequipped: {item.name} — returned to inventory")

def inventory_menu(hero):
    """
    Shows the player's equipped gear and unequipped inventory.
    Allows equipping, unequipping, and inspecting items.
    """
    while True:
        clear_screen()
        print("🎒 Inventory & Equipment\n")

        # --- Currently Equipped ---
        print("── Equipped ──")
        for slot in ("weapon", "armor", "accessory"):
            item = hero.equipment[slot]
            if item:
                print(f"  {slot.title():<12} {item.short_label()}")
            else:
                print(f"  {slot.title():<12} (empty)")

        print()

        # --- Unequipped Items ---
        print("── Bag ──")
        if not hero.inventory:
            print("  (nothing)")
        else:
            for i, item in enumerate(hero.inventory, start=1):
                print(f"  {i}) {item.short_label()}")

        print("\n0) Back")

        choice = input("\nEnter item number to equip, or slot name to unequip: ").strip().lower()

        if choice == "0":
            return

        # --- Equip from bag ---
        if choice.isdigit():
            idx = int(choice) - 1
            if idx < 0 or idx >= len(hero.inventory):
                print("Invalid choice.")
                input("\nPress Enter...")
                continue
            item = hero.inventory[idx]
            equip_item(hero, item)
            input("\nPress Enter...")

        # --- Unequip by slot name ---
        elif choice in ("weapon", "armor", "accessory"):
            item = hero.equipment[choice]
            if item is None:
                print(f"Nothing equipped in {choice} slot.")
                input("\nPress Enter...")
            else:
                unequip_item(hero, item)
                input("\nPress Enter...")

        else:
            print("Enter a number to equip, a slot name to unequip, or 0 to go back.")
            input("\nPress Enter...")


# 🎭 RANDOM REST EVENTS
# ----------------------------------------------------------
REST_EVENTS = [
    "Two goblins in the stands start arguing about their bets. One throws a mug at the other.",
    "A tired ogre janitor sweeps monster guts off the sand. He gives you a respectful nod.",
    "A hooded creature whispers: 'You're lasting longer than most... interesting.'",
    "A kobold courier rushes by carrying a sack of coins twice his size.",
    "The crowd chants your name… mixed with loud booing.",
    "A medic monster offers you foul-smelling herbs, then shrugs and eats them himself.",
    "The arena floor rumbles faintly. Something ancient stirs beneath the sand."
]


# ----------------------------------------------------------
# 🧪 USE POTION MENU
# ----------------------------------------------------------
def heal_percent(hero, percent):
    heal_amount = math.ceil(hero.max_hp * percent)
    old_hp = hero.hp
    hero.hp = min(hero.max_hp, hero.hp + heal_amount)
    actual = hero.hp - old_hp
    print(f"You recover {actual} HP! ({int(percent*100)}% heal)")

def ap_percent(hero, percent):
    amount = max(1, int(hero.max_ap * percent))
    old_ap = hero.ap
    hero.ap = min(hero.max_ap, hero.ap + amount)
    return hero.ap - old_ap

def mana_percent(hero, percent):
    if not hasattr(hero, "mana") or hero.max_mana == 0:
        print("You don't have a mana pool yet.")
        return

    mana_amount = math.ceil(hero.max_mana * percent)
    old_mana = hero.mana
    hero.mana = min(hero.max_mana, hero.mana + mana_amount)
    actual = hero.mana - old_mana
    print(f"You restore {actual} MP! ({int(percent * 100)}% mana)")


def use_potion_menu(hero):
    clear_screen()
    print("🧪 Potion Bag\n")

    # Count all potions
    total_potions = sum(hero.potions.values())
    if total_potions == 0:
        print("🧪 You reach for your potion bag… but it's empty.")
        print("You have no potions left to use.")
        space()
        input("\n(Press ENTER to continue)")
        return False


    # Build dynamic menu showing ONLY potions you actually have
    available_potions = [
        (name, count) for name, count in hero.potions.items() if count > 0
    ]

    

    for i, (potion, count) in enumerate(available_potions, start=1):
        label = potion.replace("_", " ").title()

        # Rename only for display
        if potion == "heal":
            label = "Potion"

        print(f"{i}) {label} x{count}")
    print(f"{len(available_potions) + 1}) Go back")

    # Choose potion
    choice = input("\nChoose: ").strip()

    # Exit
    if choice == str(len(available_potions) + 1):
        print("You close your potion bag.")
        space()
        return False

    # Validate input
    if not choice.isdigit():
        print("Invalid choice.")
        space()
        return False
        

    index = int(choice) - 1
    if index < 0 or index >= len(available_potions):
        print("Invalid choice.")
        space()
        return False

    # Identify potion
    potion_type, _ = available_potions[index]

    # Consume potion ONCE
    hero.potions[potion_type] -= 1


    # ---------- Potion Effects ----------
        
    if potion_type == "heal":       
        heal_percent(hero, 0.25)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return True

    elif potion_type == "super_potion":  # 50% heal
        heal_percent(hero, 0.50)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return True
    
    elif potion_type == "mega_potion":
        heal_percent(hero, 0.75)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return True

    elif potion_type == "full_potion":
        heal_percent(hero, 1.00)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return True

    elif potion_type == "ap":
        recovered = ap_percent(hero, 0.25)
        print(f"\n⚡ You drink an AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return True

    elif potion_type == "super_ap":
        recovered = ap_percent(hero, 0.50)
        print(f"\n⚡ You drink a Super AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return True

    elif potion_type == "mega_ap":
        recovered = ap_percent(hero, 0.75)
        print(f"\n⚡ You drink a Mega AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return True

    elif potion_type == "full_ap":
        recovered = ap_percent(hero, 1.00)
        print(f"\n⚡ You drink a Full AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return True
    
    # 🔵 Weak Mana Potion (+5 MP)
    elif potion_type == "mana":
        if hasattr(hero, "mana"):
            old = hero.mana
            hero.mana = min(hero.max_mana, hero.mana + 5)
            print(f"\n🔵 You drink a mana potion and restore {hero.mana - old} MP!")
        else:
            print("\n🔵 You drink a mana potion... but you have no mana pool yet.")
        continue_text()
        space()
        return True

    # 🔵 Greater Mana Potion (25%)
    elif potion_type == "greater_mana":
        mana_percent(hero, 0.25)
        print(f"Current MP: {hero.mana}/{hero.max_mana}")
        continue_text()
        space()
        return True

    # 💧 Antidote (cure poison)
    elif potion_type == "antidote":
        if hero.poison_active:
            hero.poison_active = False
            hero.poison_amount = 0
            hero.poison_turns = 0
            hero.poison_skip_first_tick = False
            print("\n💧 You drink an antidote — poison cured!")
        else:
            print("\n💧 You drink an antidote... but you're not poisoned.")
        continue_text()
        space()
        return True


    # 🔥🧴 Burn cream (cure fire stacks)
    elif potion_type == "burn_cream":
        if hasattr(hero, "fire_stacks") and hero.fire_stacks > 0:
            hero.burns = []
            hero.fire_stacks = 0
            print("\n🔥🧴 You apply burn cream — all fire stacks removed!")
        else:
            print("\n🔥🧴 You apply burn cream... but you're not burning.")
        continue_text()
        space()
        return True

    else:
        print(f"\nYou used {potion_type}, but its effect isn't implemented yet.")
        space()



# ----------------------------------------------------------
# 📈 LEVEL-UP MENU
# ----------------------------------------------------------
def level_up_menu(hero):
    clear_screen()
    print("📈 Level-Up Menu\n")

    if hero.stat_points <= 0:
        print("You have no stat points to spend.")
        space()
        return

    # Determine the cap: 2 points per stat at Lv 5, otherwise 1 point per stat.
    stat_cap = 999 if getattr(hero, "debug_mode", False) else (2 if hero.level ==5 else 1)

    while hero.stat_points > 0:
        clear_screen()

        # Live stat block — shows in debug mode now, full game in v5
        if getattr(hero, "debug_mode", False):
            eq = hero.equipment
            w   = eq.get("weapon");  a = eq.get("armor");  acc = eq.get("accessory")
            print("=" * 38)
            print(f"  📊 STATS (Level {hero.level})")
            print("=" * 38)
            print(f"  ❤️  HP  : {hero.hp}/{hero.max_hp}")
            print(f"  ⚡ AP  : {hero.ap}/{hero.max_ap}")
            print(f"  ⚔️  ATK : {hero.min_atk} - {hero.max_atk}")
            print(f"  🛡️  DEF : {hero.defence}")
            print(f"  ⚔️  Weapon   : {w.short_label() if w else '(none)'}")
            print(f"  🛡️  Armor    : {a.short_label() if a else '(none)'}")
            print(f"  💍 Accessory: {acc.short_label() if acc else '(none)'}")
            print("=" * 38 + "\n")

        print(f"You have {hero.stat_points} stat point(s) remaining.")

        # We show (Spent/Cap) so the player knows their limits
        print(f"1) +5 Max HP   ({hero.spent_stats_this_level['hp']}/{stat_cap})")
        print(f"2) +1 Attack   ({hero.spent_stats_this_level['atk']}/{stat_cap})")
        print(f"3) +1 Defense  ({hero.spent_stats_this_level['def']}/{stat_cap})")
        print(f"4) +1 Max AP   ({hero.spent_stats_this_level['ap']}/{stat_cap})")
        print("5) Done")

        choice = input("\nChoose: ").strip()

        if choice == "1":
            if hero.spent_stats_this_level["hp"] >= stat_cap:
                print(f"❌ You can only increase HP {stat_cap} time(s) at this level.")
            else:
                hero.max_hp += 5
                hero.hp += 5
                hero.max_overheal = int(hero.max_hp * 1.10)
                hero.stat_points -= 1
                hero.spent_stats_this_level["hp"] += 1
                print("Max HP increased!")

        elif choice == "2":
            if hero.spent_stats_this_level["atk"] >= stat_cap:
                print(f"❌ You can only increase Attack {stat_cap} time(s) at this level.")
            else:
                hero.min_atk += 1
                hero.max_atk += 1
                hero.stat_points -= 1
                hero.spent_stats_this_level["atk"] += 1
                print("Attack increased!")

        elif choice == "3":
            if hero.spent_stats_this_level["def"] >= stat_cap:
                print(f"❌ You can only increase Defense {stat_cap} time(s) at this level.")
            else:
                hero.defence += 1
                hero.stat_points -= 1
                hero.spent_stats_this_level["def"] += 1
                print("Defense increased!")

        elif choice == "4":
            if hero.spent_stats_this_level["ap"] >= stat_cap:
                print(f"❌ You can only increase Max AP {stat_cap} time(s) at this level.")
            else:
                hero.max_ap += 1
                hero.ap = min(hero.ap + 1, hero.max_ap)
                hero.stat_points -= 1
                hero.spent_stats_this_level["ap"] += 1
                print("AP increased!")

        elif choice == "5":
            print("You finish allocating stat points.")
            break

        else:
            print("Invalid choice.")
            clear_screen()

def spend_points_menu(hero):
    """
    Combined menu: spend Stat Points and Skill Points in one place.
    Auto-exits when all points are spent (no back-button spam).
    """
    while True:
        # ✅ If everything is spent, give a clean continue and exit
        if hero.stat_points <= 0 and hero.skill_points <= 0:
            print("\n✅ All points spent.")
            
            return

        
        print("📈 Spend Points\n")
        print(f"Stat Points:  {hero.stat_points}")
        print(f"Skill Points: {hero.skill_points}\n")

        # Only show options that are actually usable
        if hero.stat_points > 0:
            print("1) Spend Stat Points")
        if hero.skill_points > 0:
            print("2) Spend Skill Points")
        print("0) Back")

        choice = input("> ").strip()

        if choice == "0":
            return

        elif choice == "1" and hero.stat_points > 0:
            level_up_menu(hero)

        elif choice == "2" and hero.skill_points > 0:
            show_skill_tree(hero)

        else:
            print("\nInvalid choice.")
            input("\nPress Enter...")

def has_unspent_points(hero) -> bool:
    return (getattr(hero, "stat_points", 0) + getattr(hero, "skill_points", 0)) > 0


def rest_phase(hero):
    clear_screen()
    print("🏟️ INTERMISSION — A Brief Respite\n")

    # ------------------------------------
    # 💖 10% HEAL USING round()
    # ------------------------------------
    round_heal = max(1, round(hero.max_hp * 0.10))
    hero.hp = min(hero.max_overheal, hero.hp + round_heal)

    print(wrap(
        f"You are allowed a brief respite in between rounds. "
        f"You recover {round_heal} HP.\n"
        f"Your HP is now {hero.hp}/{hero.max_hp}."
    ))
    space(2)

    # ------------------------------------
    # 🔵 AP RESTORATION LOGIC (Arena Rules)
    # ------------------------------------
    old_ap = hero.ap
    hero.ap = min(hero.max_ap, hero.ap + 1)
    print(f"🔵 You recover {hero.ap - old_ap} AP from resting.")
    print(f"Current AP: {hero.ap}/{hero.max_ap}")

    reset_between_rounds(hero)

    space(2)

    # ------------------------------------
    # 🎭 RANDOM REST EVENT
    # ------------------------------------
    event = random.choice(REST_EVENTS)
    print("🔸 During your rest…")
    print(wrap(event))
    space(2)

    # ------------------------------------
    # 🧭 REST MENU LOOP
    # ------------------------------------
    while True:
        clear_screen()
        print("What would you like to do before the next fight?")
        print("1) Use a potion")

        heal_rank = hero.skill_ranks.get("heal", 0)
        has_points = has_unspent_points(hero)

        option = 2
        heal_option = None
        spend_option = None
        status_option = None
        stats_option = None
        equip_option = None
        cont_option = None

        # Only show Heal if learned
        if heal_rank > 0:
            print(f"{option}) Use First Aid")
            heal_option = str(option)
            option += 1

        if has_points:
            print(f"{option}) Spend points (stats & skills)")
            spend_option = str(option)
            option += 1

        print(f"{option}) Check Status")
        status_option = str(option)
        option += 1

        print(f"{option}) View all game stats")
        stats_option = str(option)
        option += 1

        print(f"{option}) Inventory & Equipment")
        equip_option = str(option)
        option += 1

        log_option = None
        if COMBAT_LOG:
            print(f"{option}) Review Combat Log")
            log_option = str(option)
            option += 1

        print(f"{option}) Continue to next opponent")
        cont_option = str(option)

        raw = input("\nChoose: ")
        if isinstance(raw, tuple):
            print("Debug input ignored here.")
            continue

        # --- Dev command: debug (rest version) ---
        if isinstance(raw, str) and raw.strip().lower() == "debug":
            debug_menu(hero, None)
            continue

        choice = raw.strip()

        if choice == "1":
            use_potion_menu(hero)
            continue

        if heal_option and choice == heal_option:
            if hero.hp >= hero.max_hp:
                print("You're already at full health.")
                continue_text()
            else:
                heal(hero)
                continue_text()
            continue

        if spend_option and choice == spend_option:
            spend_points_menu(hero)
            continue

        if choice == status_option:
            hero.show_combat_stats()
            input("\nPress Enter...")
            continue

        if choice == stats_option:
            hero.show_all_game_stats()
            input("\nPress Enter...")
            continue

        if choice == equip_option:
            inventory_menu(hero)
            space()
            continue

        if log_option and choice == log_option:
            view_combat_log()
            continue

        if choice == cont_option:
            if has_unspent_points(hero) and not confirm_continue_if_points_left(hero):
                spend_points_menu(hero)
                continue

            print("You steel yourself for the next battle...")
            space()
            break

        print("Invalid choice.\n")
        space()






       
            

def goblin_bookie_payout(warrior, base_gold):
    """
    Goblin bookie payout mini-game (WIP).
    base_gold will come from arena payout later.
    """
    import random, math

    print(wrap(f"The goblin bookie counts out your winnings: {base_gold} gold."))
    space()

    roll1 = random.randint(1, 5)

    if roll1 <= 2:
        print(wrap("He flashes a sharp grin. 'Pleasure doin’ business.'"))
        return base_gold

    print(wrap("Something feels… off. The goblin’s fingers move a little too fast."))
    space()

    roll2 = random.randint(1, 5)
    bonus = 0

    if roll2 == 4:
        bonus = math.floor(base_gold * 0.10)
        print(wrap("You catch him shaving coins off the stack. He sighs and adds a little more."))
    elif roll2 == 5:
        bonus = math.ceil(base_gold * 0.20)
        print(wrap("You slap his wrist mid-skim. He panics and coughs up extra gold."))
    else:
        print(wrap("He laughs it off. 'You accusing me? I’m hurt.'"))

    paid = base_gold + bonus
    print(wrap(f"You would receive {paid} gold."))

    return paid

def nob_interlude_scene(warrior):
    """
    One-time scene in the arena quarters where Nob offers to boost one skill rank.
    - Unique opening line based on story flags.
    - Player chooses any skill they have learned (rank > 0), capped at rank 5.
    - Tracked via trainer_seen so it only fires once.
    """

    # Repeat visit — scene already happened
    if "nob_interlude" in warrior.trainer_seen:
        print(wrap("Nob grins. 'To think you ran from Bo...' he chuckles. 'Now go out there and make me some gold.'"))
        return

    # --- Path-based opening dialogue ---
    if "warrior_arena_escape" in warrior.story_flags:
        print(wrap(
            "Nob crosses his arms and looks you up and down. "
            "'I don't see why you ran from Bo — you've been dominating out there.' "
            "He lets out a short laugh. 'Maybe you're smarter than you look. Or just lucky.'"
        ))
    else:
        print(wrap(
            "Nob steps over to you, arms crossed. "
            "'You made it this far. Not many do. "
            "I'm going to sharpen one thing before you go back out there.'"
        ))

    space()
    continue_text()
    clear_screen()
    print(wrap(
        "'Pick a skill. I'll push your rank up one notch. "
        "Don't expect miracles — rank 5 is the ceiling and that's where it stays.'"
    ))
    space()
    continue_text()

    # --- Build list of eligible skills ---
    eligible = []
    for key, data in SKILL_DEFS.items():
        rank = warrior.skill_ranks.get(key, 0)
        if rank > 0 and rank < 5:
            eligible.append((key, data["name"], rank))

    if not eligible:
        print(wrap(
            "Nob looks you over and grunts. "
            "'Every skill you know is already maxed. Nothing left for me to teach you.'"
        ))
        warrior.trainer_seen.add("nob_interlude")
        space()
        return

    # --- Skill choice menu ---
    while True:
        clear_screen()
        print("🏋️ Nob's Offer — Choose a skill to rank up:\n")
        for i, (key, name, rank) in enumerate(eligible, start=1):
            print(f"  {i}) {name:<16} Rank {rank} → {rank + 1}")
        print()

        choice = _real_input("> ").strip()
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(eligible):
            continue

        key, name, rank = eligible[idx]
        warrior.skill_ranks[key] = rank + 1
        warrior.trainer_seen.add("nob_interlude")

        clear_screen()
        print(wrap(
            f"Nob puts you through a focused drill. "
            f"By the end of it your {name} has sharpened noticeably."
        ))
        print(f"\n✨ {name} is now Rank {rank + 1}.")
        space()
        continue_text()
        return

def arena_quarters_interlude(warrior):
    """
    Called after the initial arena rounds are won.
    - Full heal + AP restore
    - Clears nasty status effects
    - Short hub where you can add custom dialogue later
    """
    clear_screen()

    # --- Basic placeholder intro text (you can rewrite this later) ---
    print(wrap(
        "You are escorted to a quieter room to rest between arena rounds."
    ))
    space()

    # -------- FULL HEAL & AP RESET --------
    warrior.hp = warrior.max_hp
    warrior.max_overheal = int(warrior.max_hp * 1.10)
    warrior.ap = warrior.max_ap

    # Clear combat stats
    reset_between_rounds(warrior)
    # Reset Death Defier for the new stage
   
   
    


    print(f"\n❤️ You are fully healed: {warrior.hp}/{warrior.max_hp} HP")
    print(f"🔵 AP restored: {warrior.ap}/{warrior.max_ap}")
    space(2)

    # -------- SMALL HUB LOOP (all dialogue is placeholder) --------
    talked_goblin = False
    talked_orc = False
    talked_hooded = False
    talked_crafter = False
    talked_merchant = False
    
    talked_bo = False

    while True:
        print("What would you like to do before the next stage of the tournament?")
        print("1) Talk to the goblin bookie (wip)")
        print("2) Talk to the orc guard (wip)")
        print("3) Talk to the hooded figure (wip)")
        print("4) Talk to crafter (wip)")
        print("5) Talk to merchant (wip)")
        print("6) Talk to Nob (trainer)")
        print("7) Talk to Bo (wip)")
        print("8) Rest until you’re called")
        print("9) Check your status")
        if has_unspent_points(warrior):
            print("10) Spend points (stats & skills)")
        print("11) View all game stats")
        print("12) Inventory & Equipment")
        if COMBAT_LOG:
            print("13) Review Combat Log")

        raw = input("\nChoose: ")

        # Allow monster debug here too
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            monster = raw[1]
            if monster:
                battle(warrior, monster)
            clear_screen()
            continue

        choice = str(raw).strip()

        if choice == "1":
            clear_screen()
            # TODO: add goblin bookie dialogue here
            if not talked_goblin:
                talked_goblin = True
                print(wrap("(The goblin holds up an empty coin purse and glances upward impatiently.)"))

               
            else:
                print("(You get the feeling he’s far more excited about future winnings than you are.)")
            space(2)

        elif choice == "2":
            clear_screen()
            # TODO: add orc guard dialogue here
            if not talked_orc:
                talked_orc = True
                print("(The guard makes a low annoyed grunt)")
            else:
                print("(The guard glares at you. What!)")
            space(2)

        elif choice == "3":
            clear_screen()
            # TODO: add hooded figure dialogue here
            if not talked_hooded:
                talked_hooded = True
                print(wrap(
    "The hooded figure studies you intently. "
    "You feel as though a choice has already been seen — "
    "even if you have not yet made it."
))

            else:
                print(wrap("The hooded figure remains still, lost in quiet contemplation."
                ))
            space(2)

        elif choice == "4":
            clear_screen()
            if not talked_crafter:
                talked_crafter = True
                print("I'm working on it. These things take time.")
            else:
               print("(He mutters something about 'days' and 'deadlines'.)")
        
        elif choice == "5":
            clear_screen()
            if not talked_merchant:
                talked_merchant = True
                print(wrap(
                    "The merchant stands behind an empty stall, hands folded patiently."
                ))
            else:
                print(wrap(
                    "(You get the sense he wishes he had more to sell.)"
                ))
            space(2)

        elif choice == "6":
            clear_screen()
            nob_interlude_scene(warrior)
           
            space(2)

        elif choice == "7":
            clear_screen()
            if not talked_bo:
                talked_bo = True
                print(wrap("Bo glances at you and says, 'I knew you were a good choice for the tournament.'"))

            else: 
                print(wrap("Bo gives you a slow confident grin. 'Win this thing and I'll give you something special.'"))

        elif choice == "8":
            confirm = input(
                "\n⚠️ This rest will send you directly into the championship fight.\n"
                "Are you sure you want to rest now? (y/n): "
            ).strip().lower()

            if confirm != "y":
                clear_screen()
                print(wrap(
                    "You decide to stay awake a little longer."
                ))
                space()
                continue  # back to hub menu

            clear_screen()
            print(wrap(
                "You rest for the day, gathering your strength for the coming championship fight."
            ))
            space()
            print(wrap(
                "Eventually, you are summoned back toward the arena."
            ))
            space()
            return  # back to caller (arena_battle)

        elif choice == "9":
            clear_screen()
            warrior.show_combat_stats()
            space()

        elif choice == "10":
            if has_unspent_points(warrior):
                spend_points_menu(warrior)
            else:
                print("Invalid choice.\n")

        elif choice == "11":
            clear_screen()
            warrior.show_all_game_stats()
            space()

        elif choice == "12":
            clear_screen()
            inventory_menu(warrior)

        elif choice == "13":
            if COMBAT_LOG:
                view_combat_log()

        else:
            print("Invalid choice.\n")





def _debug_ensure_skill_dicts(hero):
    # Make sure skill_ranks exists and includes every skill in SKILL_DEFS
    if not hasattr(hero, "skill_ranks") or not isinstance(hero.skill_ranks, dict):
        hero.skill_ranks = {}

    for key in SKILL_DEFS.keys():
        hero.skill_ranks.setdefault(key, 0)

    # Optional: if you track partial investment
    if not hasattr(hero, "skill_progress") or not isinstance(getattr(hero, "skill_progress", None), dict):
        hero.skill_progress = {}


def _debug_skill_editor(hero):
    _debug_ensure_skill_dicts(hero)

    while True:
        clear_screen()
        print("===== DEBUG: SKILL EDITOR =====\n")

        keys = list(SKILL_DEFS.keys())
        for i, k in enumerate(keys, start=1):
            name = SKILL_DEFS[k]["name"]
            cur = hero.skill_ranks.get(k, 0)
            mx = SKILL_DEFS[k].get("max_rank", 10)
            print(f"{i}) {name:<18} Rank {cur}/{mx}")

        print("\nA) Set ALL skills to a rank")
        print("Z) Reset ALL skills to 0")
        print("0) Back")

        c = _real_input("> ").strip().lower()
        if c == "0":
            return

        if c == "a":
            r = _real_input("Set all skills to rank (0-10): ").strip()
            if r.isdigit():
                r = int(r)
                for k in keys:
                    mx = SKILL_DEFS[k].get("max_rank", 10)
                    hero.skill_ranks[k] = max(0, min(r, mx))
            continue

        if c == "z":
            for k in keys:
                hero.skill_ranks[k] = 0
            hero.skill_progress = {}
            continue

        if not c.isdigit():
            continue

        idx = int(c) - 1
        if idx < 0 or idx >= len(keys):
            continue

        key = keys[idx]
        name = SKILL_DEFS[key]["name"]
        mx = SKILL_DEFS[key].get("max_rank", 10)

        new_rank = _real_input(f"Set {name} rank (0-{mx}): ").strip()
        if new_rank.isdigit():
            hero.skill_ranks[key] = max(0, min(int(new_rank), mx))
            # wipe partial bank to avoid weird upgrade states
            hero.skill_progress.pop(key, None)


def debug_menu(warrior, enemy=None):
    while True:
        clear_screen()
        print("===== DEBUG MENU =====")
        print("1)  Force Berserk")
        print("2)  Clear Berserk")
        print("3)  Apply Blindness")
        print("4)  Apply Burn (1 stack)")
        print("5)  Apply Poison (2 dmg)")
        print("6)  Apply Acid (1 stack)")
        print("7)  Acid Full Test (3 stacks + max erosion)")
        print("8)  Clear Acid")
        print("9)  Heal to Full")
        print("10) Grant Death Defier Skill")
        print("11) Trigger Death Defier (test)")
        print("12) Level Up")
        print("13) Defence Break")
        print("14) Skill Editor (set any skill rank)")
        print("15) Loot Manager (give / equip / unequip)")
        print("16) View Combat Log")
        print("17) Restore AP to Full")
        print("18) Debug Potion Menu")
        print("---------------------")
        print("19) Exit Current Run")
        print("20) Exit Debug Menu")
        print("======================")

        choice = _real_input("> ").strip()

        if choice == "":
            continue

        # --- 1) Berserk ---
        if choice == "1":
            warrior.hp = max(1, int(warrior.max_hp * 0.60))
            warrior.berserk_active = True
            warrior.berserk_bonus = 6 + getattr(warrior, "max_rage", 0)
            warrior.berserk_turns = 2
            warrior.berserk_used = True
            warrior.berserk_pending = False
            print("⚡ Debug: Berserk forced ON at safe HP (2 turns).")
            input("\nPress Enter...")

        elif choice == "2":
            # use your existing helper if it exists
            if "deactivate_berserk" in globals():
                deactivate_berserk(warrior)
            else:
                warrior.berserk_active = False
                warrior.berserk_turns = 0
                warrior.berserk_bonus = 0
                warrior.berserk_pending = False
            print("🧊 Debug: Berserk cleared.")
            input("\nPress Enter...")

        # --- 3) Blindness ---
        elif choice == "3":
            warrior.blind_turns = 3
            warrior.blind_long = True
            print("👁️ Debug: Blindness applied (3 turns).")
            input("\nPress Enter...")

        # --- 4) Burn ---
        elif choice == "4":
            if not hasattr(warrior, "burns"):
                warrior.burns = []
            warrior.burns.append({"turns_left": 2, "skip": True})
            warrior.fire_stacks = len(warrior.burns)
            print("🔥 Debug: Burn stack applied (2 turns).")
            input("\nPress Enter...")


        # --- 5) Poison ---
        elif choice == "5":
            warrior.poison_active = True
            warrior.poison_amount = 2
            warrior.poison_turns = 3
            warrior.poison_skip_first_tick = False
            print("☠️ Debug: Poison applied (2 dmg, 3 turns).")
            input("\nPress Enter...")

                # --- 6) Acid (1 stack) ---
        elif choice == "6":
            if not hasattr(warrior, "acid_stacks"):
                warrior.acid_stacks = []
            warrior.acid_stacks.append({"turns_left": 3, "skip": True})
            print("🧪 Debug: Acid stack applied (3 turns).")
            input("\nPress Enter...")

        # --- 7) Acid Full Test ---
        elif choice == "7":
            warrior.acid_stacks = [{"turns_left": 3, "skip": True} for _ in range(3)]
            warrior.acid_defence_loss = 3
            eff = max(0, warrior.defence - warrior.acid_defence_loss)
            print(f"🧪 Debug: 3 acid stacks + max erosion applied. (Effective DEF: {eff})")
            input("\nPress Enter...")

        # --- 8) Clear Acid ---
        elif choice == "8":
            warrior.acid_stacks = []
            warrior.acid_defence_loss = 0
            print("🧪 Debug: Acid cleared.")
            input("\nPress Enter...")


        # --- 9) Heal ---
        elif choice == "9":
            warrior.hp = warrior.max_hp
            print("💖 Debug: Healed to full.")
            input("\nPress Enter...")

        # --- 10) Grant Death Defier Skill (without auto-activating) ---
        elif choice == "10":
            warrior.death_defier = True
            warrior.death_defier_river = True  # debug = free version (0 AP)
            warrior.death_defier_active = False
            warrior.death_defier_used = False
            print("💀 Debug: Death Defier skill granted. Activate it in combat via the skill menu.")
            input("\nPress Enter...")

        # --- 11) Trigger Death Defier test ---
        elif choice == "11":
            # This simulates a death to verify the hook works
            if "try_death_defier" in globals():
                warrior.hp = 0
                try_death_defier(warrior, source="debug")
            else:
                print("⚠️ try_death_defier() not found in globals().")
            input("\nPress Enter...")

        # --- 12) Level up ---
        elif choice == "12":
            raw = _real_input("How many levels to grant? [default 1]:").strip()
            try:
                levels = max(1, int(raw)) if raw else 1
            except ValueError:
                levels = 1
            warrior.debug_mode = True
            for _ in range(levels):
                if hasattr(warrior, "level_up"):
                    warrior.level_up()
                else:
                    warrior.level += 1
            print(f"📈 Debug: Granted {levels} level(s). Now level {warrior.level}.")

            # Stat snapshot so player knows what they're working with
            print("\n" + "─" * 38)
            print(f"  📊 CURRENT STATS (Level {warrior.level})")
            print("─" * 38)
            print(f"  ❤️  HP      : {warrior.hp}/{warrior.max_hp}")
            print(f"  ⚡ AP      : {warrior.ap}/{warrior.max_ap}")
            print(f"  ⚔️  ATK     : {warrior.min_atk} – {warrior.max_atk}")
            print(f"  🛡️  DEF     : {warrior.defence}")
            print(f"  📈 XP Next  : {warrior.xp}/{int(warrior.xp_to_lvl)}")

            # Equipped gear summary
            eq = warrior.equipment
            w  = eq.get("weapon");    a = eq.get("armor");    acc = eq.get("accessory")
            print(f"  ⚔️  Weapon   : {w.short_label() if w else '(none)'}")
            print(f"  🛡️  Armor    : {a.short_label() if a else '(none)'}")
            print(f"  💍 Accessory: {acc.short_label() if acc else '(none)'}")
            print("─" * 38)

            # Prompt to spend accumulated stat/skill points right now
            if has_unspent_points(warrior):
                print(f"\n  Stat Points : {warrior.stat_points}")
                print(f"  Skill Points: {warrior.skill_points}")
                go = _real_input("\nSpend points now? (y/n) [default y]: ").strip().lower()
                if go in ("", "y", "yes"):
                    spend_points_menu(warrior)
            else:
                input("\nPress Enter...")

        # --- 13) Defence Break ---
        elif choice == "13":
            warrior.defence_broken = True
            warrior.defence_break_turns = 2
            print("🛡️ Debug: Defence break applied (2 turns).")
            input("\nPress Enter...")

        # --- 14) Skill editor (NEW) ---
        elif choice == "14":
            _debug_skill_editor(warrior)

        # --- 15) Loot Manager ---
        elif choice == "15":
            _debug_loot_menu(warrior)

        elif choice == "16":
            view_combat_log()

        # --- 17) Restore AP to Full ---
        elif choice == "17":
            old_ap = warrior.ap
            warrior.ap = warrior.max_ap
            restored = warrior.ap - old_ap
            print(f"⚡ Debug: AP fully restored! ({old_ap} → {warrior.ap}/{warrior.max_ap})")
            input("\nPress Enter...")

        # --- 18) Debug Potion Menu ---
        elif choice == "18":
            _debug_potion_menu(warrior)

        # --- 19) Exit run ---
        elif choice == "19":
            sys.exit(0)

        # --- 20) Exit debug menu ---
        elif choice == "20":
            return


def _debug_loot_menu(warrior):
    """
    Debug Loot Manager — three modes in one:
      A) Give to Inventory  (consumables via make_loot, monster drop sims)
      B) Equip Directly     (equippable gear, pick rarity, instant equip)
      C) Unequip Slot       (clear weapon / armor / accessory)
    """

    RARITY_MAP = {
        "1": "poor", "2": "normal", "3": "uncommon",
        "4": "rare",  "5": "epic",   "6": "legendary",
    }

    def _pick_rarity():
        print("\n  Rarity:")
        print("    1) ⬜ Poor      2) 🟦 Normal    3) 🟩 Uncommon")
        print("    4) 🟨 Rare      5) 🟪 Epic       6) 🟥 Legendary")
        r = _real_input("  Pick rarity > ").strip()
        return RARITY_MAP.get(r)

    # Every loot item in the game keyed to its make_loot monster key
    ALL_LOOT = [
        ("1",  "Poison Sac        (accessory) — Green Slime",      "Green Slime"),
        ("2",  "Fire Sac          (accessory) — Red Slime",         "red slime"),
        ("3",  "Acid Sac          (accessory) — Hydra Hatchling",   "Hydra Hatchling"),
        ("4",  "Wolf Pelt         (armor)     — Wolf Pup",          "Wolf Pup"),
        ("5",  "Dire Wolf Pelt    (armor)     — Dire Wolf Pup",     "Dire Wolf Pup"),
        ("6",  "Rusted Sword      (weapon)    — Brittle Skeleton",  "Brittle Skeleton"),
        ("7",  "Imp Trident       (weapon)    — Imp",               "Imp"),
        ("8",  "Goblin Dagger     (weapon)    — Young Goblin",      "Young Goblin"),
        ("9",  "Paralyzing Arrow  (accessory) — Goblin Archer",     "Goblin Archer"),
        ("10", "Javelina Tusk     (weapon)    — Javelina",          "Javelina"),
        ("11", "Soul Pendant      (accessory) — Noob Ghost",        "Noob Ghost"),
        ("12", "Rider's Armor     (armor)     — Wolf Pup Rider",    "Wolf Pup Rider"),
        ("13", "Weapon Core       (weapon)    — Fallen Warrior",    "Fallen Warrior"),
        ("14", "Chimera Scale     (armor)     — Young Chimera",     "Young Chimera"),
    ]

    while True:
        clear_screen()
        print("===== DEBUG: LOOT MANAGER =====\n")

        # Show currently equipped gear at a glance
        eq = warrior.equipment
        print("  Currently equipped:")
        print(f"    ⚔️  Weapon   : {eq.get('weapon').short_label() if eq.get('weapon') else '(none)'}")
        print(f"    🛡️  Armor    : {eq.get('armor').short_label() if eq.get('armor') else '(none)'}")
        print(f"    💍 Accessory: {eq.get('accessory').short_label() if eq.get('accessory') else '(none)'}")
        print(f"  Stats: ATK {warrior.min_atk}-{warrior.max_atk}  DEF {warrior.defence}  HP {warrior.hp}/{warrior.max_hp}\n")

        print("  A) Give / Equip item       (pick any loot, choose rarity)")
        print("  C) Unequip a slot          (removes item, reverses stats)")
        print("  0) Back")

        mode = _real_input("\n  Choose mode > ").strip().upper()

        # ── A: Give or Equip ─────────────────────────────────────────────
        if mode == "A":
            while True:
                clear_screen()
                print("===== GIVE / EQUIP LOOT =====\n")

                # Show current loadout at top so you know what slots are free
                eq = warrior.equipment
                print(f"  ⚔️  Weapon   : {eq.get('weapon').short_label() if eq.get('weapon') else '(none)'}")
                print(f"  🛡️  Armor    : {eq.get('armor').short_label() if eq.get('armor') else '(none)'}")
                print(f"  💍 Accessory: {eq.get('accessory').short_label() if eq.get('accessory') else '(none)'}")
                print(f"  Stats: ATK {warrior.min_atk}-{warrior.max_atk}  DEF {warrior.defence}  HP {warrior.hp}/{warrior.max_hp}\n")

                for num, label, _ in ALL_LOOT:
                    print(f"  {num:>2}) {label}")
                print("   0) Done")
                item_choice = _real_input("\n  Pick item > ").strip()
                if item_choice == "0":
                    break

                monster_key = None
                for num, label, key in ALL_LOOT:
                    if item_choice == num:
                        monster_key = key
                        break
                if not monster_key:
                    print("Invalid choice.")
                    _real_input("\nPress Enter...")
                    continue

                chosen_rarity = _pick_rarity()
                if not chosen_rarity:
                    print("Invalid rarity.")
                    _real_input("\nPress Enter...")
                    continue

                original_roll = globals().get("roll_rarity")
                globals()["roll_rarity"] = lambda *a, **kw: chosen_rarity
                item = make_loot(monster_key)
                globals()["roll_rarity"] = original_roll

                if not item:
                    print("⚠️ Could not create item.")
                    _real_input("\nPress Enter...")
                    continue

                # Ask give or equip
                print(f"\n  Created: {item.short_label()}")
                print("  1) Add to inventory")
                print("  2) Equip directly")
                dest = _real_input("  Choose > ").strip()
                if dest == "2":
                    equip_item(warrior, item)
                    print(f"\n  Stats after equip — ATK: {warrior.min_atk}-{warrior.max_atk}  "
                          f"DEF: {warrior.defence}  HP: {warrior.hp}/{warrior.max_hp}")
                else:
                    warrior.inventory.append(item)
                    print(f"\n✅ Added to inventory: {item.short_label()}")
                _real_input("\nPress Enter...")

        # ── C: Unequip a Slot ────────────────────────────────────────────
        elif mode == "C":
            while True:
                clear_screen()
                print("===== UNEQUIP SLOT =====\n")
                slots = ["weapon", "armor", "accessory"]
                for i, slot in enumerate(slots, 1):
                    current = warrior.equipment.get(slot)
                    label = current.short_label() if current else "(empty)"
                    print(f"  {i}) {slot.title():<12} {label}")
                print("  0) Done")

                slot_choice = _real_input("\n  Pick slot to unequip > ").strip()
                if slot_choice == "0":
                    break

                slot_map = {"1": "weapon", "2": "armor", "3": "accessory"}
                target_slot = slot_map.get(slot_choice)
                if not target_slot:
                    print("Invalid choice.")
                    _real_input("\nPress Enter...")
                    continue

                current = warrior.equipment.get(target_slot)
                if not current:
                    print(f"  Nothing equipped in {target_slot} slot.")
                else:
                    unequip_item(warrior, current)
                    print(f"\n  🗑️  Unequipped: {current.short_label()}")
                    print(f"  Stats after — ATK: {warrior.min_atk}-{warrior.max_atk}  "
                          f"DEF: {warrior.defence}  HP: {warrior.hp}/{warrior.max_hp}")
                _real_input("\nPress Enter...")

        elif mode == "0":
            return



def _debug_potion_menu(warrior):
    """Debug helper: add any potion type to the player's potion bag."""
    POTION_LIST = [
        ("1",  "heal",         "Potion           (25% HP)"),
        ("2",  "super_potion", "Super Potion      (50% HP)"),
        ("3",  "mega_potion",  "Mega Potion       (75% HP)"),
        ("4",  "full_potion",  "Full Potion       (100% HP)"),
        ("5",  "ap",           "AP Potion         (25% AP)"),
        ("6",  "super_ap",     "Super AP Potion   (50% AP)"),
        ("7",  "mega_ap",      "Mega AP Potion    (75% AP)"),
        ("8",  "full_ap",      "Full AP Potion    (100% AP)"),
        ("9",  "mana",         "Mana Potion       (+5 MP flat)"),
        ("10", "greater_mana", "Greater Mana Pot  (25% MP)"),
        ("11", "antidote",     "Antidote          (cure poison)"),
        ("12", "burn_cream",   "Burn Cream        (clear fire stacks)"),
    ]

    while True:
        clear_screen()
        print("===== DEBUG: POTION MENU =====\n")
        print("Current stock:")
        for key, count in warrior.potions.items():
            if count > 0:
                print(f"  {key.replace('_',' ').title()}: x{count}")
        if not any(warrior.potions.values()):
            print("  (none)")
        print()

        for num, key, label in POTION_LIST:
            print(f"  {num:>2}) {label}")
        print()
        print("  13) Add ALL potions x3 (quick fill)")
        print("   0) Back")

        choice = _real_input("\nPick potion to add > ").strip()

        if choice == "0":
            return

        if choice == "13":
            for _, key, _ in POTION_LIST:
                if key in warrior.potions:
                    warrior.potions[key] += 3
                else:
                    warrior.potions[key] = 3
            print("✅ Added x3 of every potion to your bag!")
            _real_input("\nPress Enter...")
            continue

        matched = None
        for num, key, label in POTION_LIST:
            if choice == num:
                matched = (key, label)
                break

        if not matched:
            print("Invalid choice.")
            _real_input("\nPress Enter...")
            continue

        potion_key, potion_label = matched
        amt_raw = _real_input(f"How many {potion_label.split('(')[0].strip()} to add? [default 1]: ").strip()
        try:
            amt = max(1, int(amt_raw)) if amt_raw else 1
        except ValueError:
            amt = 1

        if potion_key in warrior.potions:
            warrior.potions[potion_key] += amt
        else:
            warrior.potions[potion_key] = amt

        print(f"✅ Added x{amt} {potion_label.split('(')[0].strip()} — "
              f"Total: {warrior.potions[potion_key]}")
        _real_input("\nPress Enter...")


def monster_select_menu():
    clear_screen()
    print("===== MONSTER SELECT (DEBUG) =====")
    print("Choose a monster to fight:")
    print("1) Green Slime")
    print("2) Red Slime")
    print("3) Young Goblin")
    print("4) Wolf Pup")
    print("5) Skeleton")
    print("6) Imp")
    print("7) Fallen Warrior")
    print("8) Wolf Pup Rider")
    print("9) Javelina")
    print("10) Goblin Archer")
    print("11) Noob Ghost")
    print("12) Dire Wolf Pup")
    print("13) Hydra Hatchling")
    print ("14 Young Chimera Hidden Boss" )
    print("0) Cancel")
    print("==========================")

    choice = _real_input("> ").strip()

    monster_map = {
        "1": Green_Slime,
        "2": Red_Slime,
        "3": Young_Goblin,
        "4": Wolf_Pup,
        "5": Brittle_Skeleton,
        "6": Imp,
        "7": Fallen_Warrior,
        "8": Wolf_Pup_Rider,
        "9": Javelina,
        "10": Goblin_Archer,
        "11": Noob_Ghost,
        "12": Dire_Wolf_Pup,
        "13": Hydra_Hatchling,
        "14": Young_Chimera
    }

    # NEW — tier lookup (logic only)
    tier_map = {
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 1,
        "5": 1,
        "6": 1,
        "7": 4,
        "8": 3,   # Wolf Pup Rider = Tier 3
        "9": 2,
        "10": 2,
        "11": 2,
        "12": 2,
        "13": 3,
        "14": 5,
    }

    if choice == "0":
        return None

    if choice not in monster_map:
        print("Invalid choice.")
        input("\nPress Enter")
        return None

    monster = monster_map[choice]()
    monster.tier = tier_map.get(choice, 3)   # ⭐ REQUIRED

    print(f"⚔️ You selected: {monster.display_name}")

    raw_lvl = _real_input("Set monster level (rank) [default 1]: ").strip()
    if raw_lvl == "":
        lvl = 1
    else:
        try:
            lvl = max(1, int(raw_lvl))
        except ValueError:
            lvl = 1

    apply_level_scaling_debug_any(monster, level=lvl)

    print(f"✅ Spawned: {monster.display_name} (Level {monster.level})")
    input("\nPress Enter")
    return monster

def show_health(hero):
    bar = hp_bar(hero.hp, hero.max_hp)
    print(f"❤️ HP [{bar}] {hero.hp}/{hero.max_hp}")


def apply_turn_stop(hero, turns=1, reason="Stunned"):
    """
    Apply a turn-stopping status (stun/freeze/paralyze/etc.).
    Does not handle anti-chain logic; the combat loop does.
    """
    hero.turn_stop = max(getattr(hero, "turn_stop", 0), turns)
    hero.turn_stop_reason = reason
    if reason == "Paralyzed":
        hero.paralyzed = True   # lets First Aid R4+ detect and cure this


def resolve_player_turn_stop(hero):
    """
    Returns True if the player's action is blocked this turn.

    Paralyze rules:
      - Multi-turn paralyze (chimera): consecutive Lost turns with no breathe
        between them. Breathe turn only granted after ALL turns expire.
      - After the breathe turn, post_paralyze_guard = True so the enemy cannot
        re-paralyze until the player has landed one full free attack.

    Non-paralyze stuns: original behavior - max 1 consecutive lost turn.
    """
    # Backward safety
    if not hasattr(hero, "turn_stop"):
        hero.turn_stop = 0
    if not hasattr(hero, "turn_stop_reason"):
        hero.turn_stop_reason = ""
    if not hasattr(hero, "turn_stop_chain_guard"):
        hero.turn_stop_chain_guard = False
    if not hasattr(hero, "post_paralyze_guard"):
        hero.post_paralyze_guard = False

    if hero.turn_stop <= 0:
        hero.turn_stop_chain_guard = False
        return False

    is_paralyze = (hero.turn_stop_reason == "Paralyzed")

    # --- Breathe turn (chain guard fired last lost turn) ---
    if hero.turn_stop_chain_guard:
        if is_paralyze:
            # True consecutive lockdown: only grant breathe when all turns gone
            if hero.turn_stop > 0:
                # Still turns remaining - lock again, no breathe yet
                hero.turn_stop -= 1
                return True
            else:
                # All turns expired - grant breathe turn now
                # post_paralyze_guard blocks re-paralysis until player acts
                hero.turn_stop_chain_guard = False
                hero.paralyzed = False
                hero.turn_stop_reason = ""
                hero.post_paralyze_guard = True
        else:
            # Non-paralyze: original wipe behavior
            hero.turn_stop = 0
            hero.turn_stop_reason = ""
            hero.turn_stop_chain_guard = False
        return False

    # --- First lost turn ---
    hero.turn_stop -= 1
    hero.turn_stop_chain_guard = True
    return True

def simple_trainer_reaction_stub(hero):
    # NOTE: full implementation below near trainer_stat_point_scene
    pass

def tick_war_cry(hero):
    if getattr(hero, "war_cry_turns", 0) > 0:

        # ✅ Do not tick on the same turn it was applied
        if getattr(hero, "war_cry_skip_first_tick", False):
            hero.war_cry_skip_first_tick = False
            return

        hero.war_cry_turns -= 1
        if hero.war_cry_turns == 0:
            hero.war_cry_bonus = 0
            print("🗣️ Your War Cry fades.")


def trainer_prep_menu(hero):
    while True:
        clear_screen()
        print("🏋️ Trainer Prep\n")
        print(f"Stat Points:  {hero.stat_points}")
        print(f"Skill Points: {hero.skill_points}")
        print(f"AP: {hero.ap}/{hero.max_ap}\n")

        print("1) Spend points (stats & skills)")
        print("2) Use a potion")
        print("3) Check your status")
        print("4) I'm ready now")
        print("0) Leave")

        choice = input("> ").strip()

        if choice == "1":
            spend_points_menu(hero)   # you already have this
        elif choice == "2":
            use_potion_menu(hero)     # you already have this
        elif choice == "3":
            hero.show_game_stats()
            input("\nPress Enter...")
        elif choice == "4":
            if confirm_continue_if_points_left(hero, "Enter the next fight without spending them?"):
                return "ready"
            else:
                continue

        elif choice == "0":
            return "leave"
# this function isnt curently being used
def get_active_combat_bonuses(warrior):
    bonus = getattr(warrior, "current_bonus_damage", 0)   # adrenaline

    if getattr(warrior, "berserk_active", False):
        bonus += getattr(warrior, "berserk_bonus", 0)

    # War Cry only if actually active
    if getattr(warrior, "war_cry_turns", 0) > 0:
        bonus += getattr(warrior, "war_cry_bonus", 0)

    return bonus




def confirm_continue_if_points_left(hero, prompt="Continue to the next fight?"):
    """
    Returns True if the player should continue.
    If points remain, ask once. If none remain, just continue.
    """
    while True:
        stat = getattr(hero, "stat_points", 0)
        skill = getattr(hero, "skill_points", 0)

        if stat <= 0 and skill <= 0:
            return True

        print(f"\nYou still have points left to spend: Stat={stat}, Skill={skill}")
        ans = input(f"{prompt} (y/n): ").strip().lower()

        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False

        print("Please type y or n.")



def deactivate_berserk(hero):
    hero.berserk_active = False
    hero.berserk_bonus = 0
    hero.berserk_turns = 0
    hero.berserk_pending = False  # if you use it anywhere

def clear_all_burns(hero):
    hero.burns = []
    hero.fire_stacks = 0
    hero.fire_turns = 0
    hero.fire_skip_first_tick = False

def clear_all_status_effects(hero):
    """Clears all harmful status effects"""
    clear_all_burns(hero)

    hero.poison_active = False
    hero.poison_amount = 0
    hero.poison_turns = 0
    hero.poison_skip_first_tick = False
    hero.poison_dots = []

    hero.blind_turns = 0
    hero.blind_long = False

    hero.paralyzed = False
    hero.paralyze_turns = 0

    hero.acid_stacks = []
    hero.acid_defence_loss = 0

def reset_between_rounds(hero):
    # DoTs / debuffs that should not persist between fights
    clear_all_burns(hero)

    hero.poison_active = False
    hero.poison_amount = 0
    hero.poison_turns = 0
    hero.poison_skip_first_tick = False   # ✅ add

    hero.fire_stacks = 0                  # ✅ add (if HUD uses it)

    hero.war_cry_bonus = 0
    hero.war_cry_turns = 0

    hero.blind_turns = 0
    hero.blind_long = False

    hero.turn_stop = 0
    hero.turn_stop_reason = ""
    hero.turn_stop_chain_guard = False
    hero.paralyze_vulnerable = False
    hero.paralyzed = False
    hero.post_paralyze_guard = False

    hero.acid_stacks = []
    hero.acid_defence_loss = 0


    # --- Fallen Warrior: Defence Warp cleanup (boss-only debuff) ---
    if hasattr(hero, "defence_warp_phase"):
        del hero.defence_warp_phase
    if hasattr(hero, "defence_warp_original_defence"):
        del hero.defence_warp_original_defence

    # Optional: clear “one-fight only” flags here if you have them
    # hero.defense_break = False   # example if you store something like this

def blind_damage_multiplier(hero):
    if hero.blind_turns >= 3:
        return 0.5
    elif hero.blind_turns == 2:
        return 0.25
    return 1.0




def space(line=1):
    for _ in range(line):
        print()

def wrap(text, width=WIDTH):
    # Bug-crush: Ensure we are dealing with a string to avoid AttributeErrors
    if not isinstance(text, str):
        text = str(text)
        
    return textwrap.fill(text, 
                         width=width, 
                         break_long_words=False, 
                         replace_whitespace=False
                         )
 # this is a very safe way to stop just about every possible textwrapping issue

#Defencive Block Flavor text

def weak_defensive_block(attacker, defender):
    messages = [
        f"{attacker.name} powers through {defender.name}'s guard.",
        f"{defender.name} barely raises a defense in time.",
        f"{attacker.name}'s blow crashes into {defender.name}.",
        f"{defender.name} takes the brunt of the strike.",
        f"{attacker.name} overwhelms the guard.",
        f"{defender.name}'s defense falters under the hit.",
        f"{attacker.name} slips past the guard easily.",
        f"{defender.name} misjudges the timing and gets hit.",
        f"{attacker.name}'s strike lands solidly.",
        f"{defender.name} blocks too late to stop much."
    ]
    return wrap(random.choice(messages))

def solid_defensive_block(attacker, defender, reduced_amount):
    messages = [
        f"{defender.name} absorbs part of the blow.",
        f"{defender.name} braces and reduces the impact.",
        f"{attacker.name}'s strike is partially deflected.",
        f"{defender.name} blocks with practiced form.",
        f"{defender.name} steadies and holds the line.",
        f"{defender.name} turns aside some of the force.",
        f"{attacker.name} struggles to break through the guard.",
        f"{defender.name} meets the blow head-on.",
        f"{defender.name} blocks most of the attack.",
        f"{defender.name} absorbs the hit without faltering."
    ]
    return wrap(random.choice(messages) + f" ({reduced_amount} damage blocked)")

def strong_defensive_block(attacker, defender):
    messages = [
        f"{defender.name} deflects most of the strike with expert timing.",
        f"{defender.name} turns the blow aside at the last moment.",
        f"{attacker.name}'s attack is nearly shut down.",
        f"{defender.name} reads the attack and redirects it.",
        f"{defender.name} absorbs the hit with effortless control.",
        f"{attacker.name}'s blow glances off the guard.",
        f"{defender.name} smothers the attack before it lands.",
        f"{attacker.name} fails to find an opening.",
        f"{defender.name} dominates the exchange defensively.",
        f"{attacker.name}'s strike barely makes contact."
    ]
    return wrap(random.choice(messages))

def full_defensive_block(attacker, defender):
    messages = [
        f"{defender.name} completely shuts down the attack!",
        f"{defender.name} blocks flawlessly, taking no damage!",
        f"{attacker.name}'s strike is utterly nullified!",
        f"{defender.name} moves with perfect precision, unharmed.",
        f"{defender.name} reads the attack and denies it entirely!",
        f"{attacker.name} cannot break through {defender.name}'s defense!",
        f"{defender.name} stands unshaken as the attack fails!",
        f"{defender.name} negates the strike with absolute control!",
        f"{defender.name}'s defense is impenetrable!",
        f"{attacker.name}'s attack is rendered meaningless!"
    ]
    return wrap(random.choice(messages))

# ===============================
# Monster AI Helpers
# ===============================

def monster_ai_check(monster, turn_number):
    """
    Handles special move logic for all monster tiers:
    Tier 1: 100% on Turn 1, then 50%
    Tier 2: 50% every turn
    Tier 3: 33% every turn
    Tier 4: 33% every turn (Bosses/Fallen Warrior)
    """
    # Safety: Ensure tier exists and monster has AP
    tier = getattr(monster, "tier", 1)
    if monster.ap <= 0:
        return False

    if tier == 1:
        # Guaranteed special on first enemy action
        if turn_number == 1:
            return True
        return random.random() < 0.50

    elif tier == 2:
        # Flat 50% chance
        return random.random() < 0.50

    elif tier == 3:
        # Flat 33% chance
        return random.random() < 0.33
    
    elif tier == 4:
        # Flat 33% chance (Fallen Bosses)
        return random.random() < 0.33

    elif tier == 5:
        # Young Chimera — 50% every turn (more unpredictable than tier 4)
        return random.random() < 0.50

    return False




# ===============================
# Monster Special Moves
# ===============================
def slime_poison_spit(slime, hero):
    if slime.ap <= 0:
        return None

    slime.ap -= 1

    b = lvl_bonus(slime)

    # ---- Physical hit ONLY (defence applies) ----
    roll = random.randint(1 + b, 3 + b)
    actual = hero.apply_defence(roll, attacker=slime)
    hero.hp = max(0, hero.hp - actual)
    

    # ---- Apply poison (NO damage yet) ----
    hero.poison_active = True
    hero.poison_amount = 2 + b       # flat, ignores defence
    hero.poison_turns = 2
    hero.poison_skip_first_tick = True

    print(wrap(f"{slime.name} spits corrosive slime!"))
    monster_math_breakdown(slime, hero, roll, actual, tag="Poison Spit")
    print(wrap("🟢 You are poisoned!"))

    show_health(hero)

    return actual

   

def red_slime_fire_spit(slime, hero):
    """
    Red Slime Fire Spit
    50% chance to trigger each turn.
    Costs 1 AP (only on success).
    Deals normal physical attack + TRUE fire damage.
    Applies 1 burn stack (max 2).
    Burn ticks start on hero's next turn.
    """

    # Not enough AP = can't fire spit
    if slime.ap < 1:
        return None
    b = lvl_bonus(slime)

    

    # Successful Fire Spit consumes AP
    slime.ap -= 1

    print(f"🔥 {slime.name} spits burning slime at you!")

    # --------------------------------
    # 1) PHYSICAL IMPACT (defense applies)
    # --------------------------------
    normal_roll = random.randint(slime.min_atk, slime.max_atk)
    normal_actual = hero.apply_defence(normal_roll, attacker=slime)
    hero.hp = max(0, hero.hp - normal_actual)

    

    # --------------------------------
    # 2) FIRE DAMAGE (TRUE damage, ignores defence)
    # --------------------------------
    fire_damage = random.randint(2 + b, 3 + b)
    hero.hp = max(0, hero.hp - fire_damage)
    # ✅ One unified math line (physical + fire)

    monster_math_breakdown(
        slime, hero,
        normal_roll, normal_actual,
        extra_parts=[("Fire", fire_damage)],
        tag="Fire Spit"
)

    print("🔥 Burning slime scorches your skin!")

    # --------------------------------
    # 3) APPLY BURN STACK (DoT) — per-stack timers
    # --------------------------------
    if not hasattr(hero, "burns"):
        hero.burns = []

    if len(hero.burns) < 2:
        hero.burns.append({"turns_left": 2, "skip": True, "bonus": b})
    else:
        weakest_idx = min(
            range(len(hero.burns)),
            key=lambda i: hero.burns[i]["turns_left"]
        )
        hero.burns[weakest_idx] = {"turns_left": 2, "skip": True, "bonus": b}

    hero.fire_stacks = len(hero.burns)
    stack_text = "stack" if hero.fire_stacks == 1 else "stacks"
    print(f"🔥 Burning slime clings to your skin! ({hero.fire_stacks} burn {stack_text})")

    show_health(hero)

    # Return total immediate damage
    return normal_actual + fire_damage





def goblin_cheap_shot(enemy, warrior):
    """Goblin special move: 3-stage blind (Miss -> 50% -> 75%)"""
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    # Apply blindness flags
    warrior.blind_turns = 3
    warrior.blind_long = True
    warrior.is_blinded = True
    warrior.blind_type = "goblin_dust" # Tells the game to use the 3-stage logic

    print("\n🗡️ The goblin gets close and blows dust into your eyes!")
    print("😵 You are BLINDED! Your vision is completely obscured!")

    # Max-damage attack
    actual = enemy.max_atk + b
    warrior.hp = max(0, warrior.hp - actual)

    print(f"👁️ The goblin strikes while you're vulnerable for {actual} MAX DAMAGE!")
    return actual

def paralyzing_shot(enemy, warrior, paralyze_turns=1):
    if enemy.ap <= 0:
        return None

    # Don't waste AP trying to paralyze if it can't meaningfully stick
    # (already turn-stopped, chain guard active, or player hasn't had their
    #  free attack yet after last paralyze expired)
    if (getattr(warrior, "turn_stop", 0) > 0
            or getattr(warrior, "turn_stop_chain_guard", False)
            or getattr(warrior, "post_paralyze_guard", False)):
        return None

    

    enemy.ap -= 1
    b = lvl_bonus(enemy)
    print("\n🏹 The goblin archer fires a coated arrow!")
    print("🧪 A paralytic resin glistens on the tip...")

    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    # Unified turn-stop system (prevents chaining turn-loss)
    apply_turn_stop(warrior, turns=paralyze_turns, reason="Paralyzed")

    # Your existing "punish window" can stay if you like
    warrior.paralyze_vulnerable = True

    monster_math_breakdown(enemy, warrior, roll, actual, tag="Paralyzing Shot")
    turns_word = f"{paralyze_turns} turn{'s' if paralyze_turns != 1 else ''}"
    print(f"🧊⚡ You are PARALYZED! You will lose your next {turns_word}!")
    show_health(warrior)
    return actual



def imp_sneak_attack(enemy, warrior):
    """
    Imp special move:
    Teleports behind the warrior and strikes for max damage on first turn.
    Deals +1 damage if the warrior has no defence.
    """

    if enemy.ap <= 0:
        return None

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print("\n👿 The imp vanishes in a puff of smoke!")
    print("⚡ It reappears behind you, striking before you can react!")

    # Guaranteed max base damage
    damage = enemy.max_atk + b  # 4

    # Bonus damage if no defence
    if warrior.defence == 0:
        damage += 1 + b
        print("🩸 Your lack of defense leaves you wide open!")

    # Apply damage directly
    warrior.hp = max(0, warrior.hp - damage)

    print(f"🗡️ The imp deals {damage} damage!")

    return damage

def brittle_skeleton_thrust(enemy, target):
    if enemy.ap <= 0:
        return 0

    b = lvl_bonus(enemy)

    damage = 6 + b
    if target.defence == 0:
        damage += 1 + b

    print("The skeleton lunges with a precise thrust!")

    enemy.ap -= 1
    target.hp = max(0, target.hp - damage)

    print(f"You take {damage} damage!")
    return damage

def wolf_pup_bite(enemy, warrior):
    if enemy.ap <= 0:
        return None
    
    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print("🐺 The wolf pup lunges forward and viciously bites you!")

    # Base attack (defence applies)
    roll = random.randint(2 + b, 5 + b)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)


    # Bite bonus (ignores defence)
    bite_bonus = random.randint(1 + b, 5 + b)
    warrior.hp = max(0, warrior.hp - bite_bonus)

    monster_math_breakdown(enemy, warrior, roll, actual, extra_parts=[("Bite", bite_bonus)], tag="Bite")
    print(f"🩸 The bite rips flesh for {bite_bonus} extra damage!")

    # One-turn bleed
    show_health(warrior)
    

    return actual + bite_bonus

def devouring_bite(enemy, warrior):
    """
    Dire Wolf Pup special:
    - Costs 1 AP
    - 50% chance to trigger
    - Only used if the dire wolf pup is missing HP
    - Deals physical damage (defence applies)
    - Heals the wolf for HALF the damage actually dealt
    """
    # Needs AP
    if enemy.ap <= 0:
        return None

    # SAFEGUARD: only use if missing health
    if enemy.hp >= enemy.max_hp:
        return None

    
    

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print("\n🐺 The dire wolf pup lunges with a DEVOURING BITE!")

    # Normal physical bite (defence applies)
    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    monster_math_breakdown(enemy, warrior, roll, actual, tag="Devouring Bite")

    # Lifesteal heal: half the damage dealt (rounded down)
    heal = actual // 2
    if heal > 0:
        before = enemy.hp
        enemy.hp = min(enemy.max_hp, enemy.hp + heal)
        gained = enemy.hp - before
        print(f"🧶 The dire wolf pup devours flesh and regains {gained} HP!")
    else:
        print("🛡️ Your defence denies the wolf its meal!")

    show_health(warrior)
    return actual


def ghost_life_leech(enemy, warrior):
    """
    Ghost special move:
    1) Normal physical strike (defence applies)
    2) Extra life drain equal to HALF the original roll (ignores defence),
       and the ghost heals by the drained amount (can overheal).
    """
    if enemy.ap <= 0:
        return None

    

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print(wrap("\n👻 The ghost's claws pass through your flesh, chilling your soul!"))

    # ---------- Step 1: physical hit (defence applies) ----------
    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    physical = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - physical)

    monster_math_breakdown(enemy, warrior, roll, physical, tag="Life Leech (Hit)")

    # ---------- Step 2: life drain (ignores defence) ----------
    # drain is based on the *original* roll, not reduced damage
    drain = max(1, roll // 2)  # e.g. 6 → 3, 5 → 2
    before = warrior.hp
    warrior.hp = max(0, warrior.hp - drain)
    actual_drain = before - warrior.hp  # prevents healing more than was actually lost

    # Make sure ghost has an overheal cap
    if not hasattr(enemy, "max_overheal"):
        enemy.max_overheal = int(enemy.max_hp * 1.5)

    enemy.hp = min(enemy.max_overheal, enemy.hp + actual_drain)

    print(
        f"💀 Life Leech drains an additional {actual_drain} HP "
        f"(ignores defence) and empowers the ghost!"
    )
    show_health(warrior)
    # If you ever add an enemy HP HUD, it will reflect overheal too.

    # Total damage to the hero this turn
    return physical + actual_drain

def blinding_charge(self, hero):
    if self.ap <= 0:
        return None
    

    self.ap -= 1

    print("\n👺 The goblin blinds you as the wolf pup charges!")

    damage = random.randint(4, 8)
    hero.hp = max(0, hero.hp - damage)

    # Only apply blind + turn-stop if the hero is NOT already blinded
    if getattr(hero, "blind_turns", 0) > 0:
        print(wrap("👁️‍🗨️ You're already blinded — the charge just hits HARD!"))
    else:
        # Apply blind (your existing system)
        hero.blind_turns = 1
        hero.blind_long = False

        # NEW: costs the player's next action, but cannot chain (your loop handles that)
        apply_turn_stop(hero, turns=1, reason="Blinded")

    print(f"🐺 You take {damage} damage!")
    show_health(hero)
    return damage


def impact_bite(enemy, hero):
    if enemy.ap <= 0:
        return None
    
    
        
    enemy.ap -= 1
    b = lvl_bonus(enemy)
    print("\n🐗 The javelina barrels into you and snaps its jaws!")

    # 1. CALCULATE TOTAL POTENTIAL POWER
    impact_roll = random.randint(4 + b, 6 + b)
    bite_roll = random.randint(2 + b, 4 + b)
    total_power = impact_roll + bite_roll # Range: 6 to 10

    # 2. APPLY DEFENCE ONCE TO THE WHOLE COMBO
    # This way, if total is 6 and defence is 2, you take 4.
    actual_damage = hero.apply_defence(total_power, attacker=enemy)
    
    hero.hp = max(0, hero.hp - actual_damage)

    # 3. PRINT THE RESULTS
    # We can still describe the bite, but the math is unified
    print(f"💥 Combo Hit! Impact ({impact_roll}) + Bite ({bite_roll})")
    print(f"🛡️ Your defence mitigated the force, but you still take {actual_damage} damage!")

    show_health(hero)
    return actual_damage

def fallen_defence_warp(enemy, warrior):
    """
    Fallen Warrior special: Defence Warp

    - 33% chance when he attacks
    - Costs 1 AP when it goes off
    - Heavy hit, 9–11 damage with current stats (6–10 base)
    - Hit itself uses NORMAL defence rules
    - THEN, if damage actually gets through and the hero has defence:
        * 1st warped enemy turn: defence = 0
        * 2nd warped enemy turn: defence = 50% of original
        * After that: defence fully restores
    """

    # No AP? No special.
    if enemy.ap <= 0:
        return None

    

    enemy.ap -= 1

    print(f"\n💀 {enemy.name} twists his blade with a warped defence-breaking technique!")
    print("🌀 Your armour shudders as the strike slips past your guard!")

    # With min_atk=5 and max_atk=9, this gives 9–11 damage BEFORE defence
    roll = random.randint(enemy.max_atk, enemy.max_atk + 3)

    # ⭐ IMPORTANT: NORMAL defence applies here
    # e.g. roll = 7, defence = 2 → 2 blocked, 5 damage taken
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    monster_math_breakdown(enemy, warrior, roll, actual, tag="Defence Warp")
    show_health(warrior)

    # If no damage got through OR you have no defence, there is nothing to warp.
    if actual <= 0:
        return actual
    warp_active = hasattr(warrior, "defence_warp_phase")
    
    if warrior.defence <= 0 and not warp_active:
        return actual

    # Store original defence and start (or refresh) the warp phase sequence.
    # If the hero is already warped, DO NOT let the sequence "stabilise"—reset it.
    if warp_active:
        warrior.defence_warp_phase = 0
        print(wrap("🌀 The warped curse tightens again — your armour cannot stabilise yet."))
    else:
        warrior.defence_warp_original_defence = warrior.defence
        warrior.defence_warp_phase = 0


    print(wrap(
        "You feel your armour and body destabilising — seams creak and plates rattle. Your muscles warp and contort "
        "Your defence is coming apart. You no longer feel protected."
    ))

    return actual

def try_death_defier(hero, reason=""):
    # Only triggers if you'd die right now
    if hero.hp > 0:
        return False

    if hero.death_defier and hero.death_defier_active and not hero.death_defier_used:
        hero.hp = 1
        hero.death_defier_used = True
        hero.death_defier_active = False

        print()
        print(wrap("💀✨ Death Defier surges — you refuse to die!"))
        if reason:
            print(wrap(f"(Saved from: {reason})"))
        show_health(hero)
        return True

    return False

def hydra_hatchling_acid_spit(enemy, warrior):
    if enemy.ap <= 0:
        return None

    

    enemy.ap -= 1
    print(wrap("\n🐍 The Hydra Hatchling spits corrosive acid at you! Your defense is reduced!"))

    # -----------------------------
    # 1) Physical impact (defence applies) — NO bonus here
    # -----------------------------
    roll = random.randint(enemy.min_atk, enemy.max_atk)

    # Deal normal physical damage through your unified handler
    # (no extra_parts: the spit itself doesn't do acid damage on hit)
    dealt = monster_deal_damage(
        enemy,
        warrior,
        roll,
        extra_parts=[],
        tag="Acid Spit"
    )

    # -----------------------------
    # 2) Apply Acid Stack (3 turns) + Defence Erosion
    # -----------------------------
    if not hasattr(warrior, "acid_stacks"):
        warrior.acid_stacks = []
    if not hasattr(warrior, "acid_defence_loss"):
        warrior.acid_defence_loss = 0

    # Add a NEW stack if under cap (keep your cap 3)
    if len(warrior.acid_stacks) < 3:
        warrior.acid_stacks.append({"turns_left": 3, "skip": True})
    else:
        print("🧪 The acid is already eating at you as much as it can!")

    # Determine effective defence AFTER current erosion
    effective_def = max(0, warrior.defence - warrior.acid_defence_loss)

    # If player has defence remaining, melt 1 (fight-only, cap 3)
    if effective_def > 0:
        if warrior.acid_defence_loss < 3:
            warrior.acid_defence_loss += 1
        print("🧪 The acid sizzles into your body — you feel weaker!")
    else:
        # Edge case: no defence left → +2 immediate damage
        warrior.hp = max(0, warrior.hp - 2)
        print("🧪 With no defenses left, the acid bites deep! (+2)")
        show_health(warrior)

    return dealt


    

# =============================
# CHIMERA SPECIAL MOVE
# =============================

def chimera_elemental_strike(enemy, warrior):
    """
    Chimera's unique move — a powerful physical strike with a full elemental DoT.
    The element (fire/poison/acid/paralyze) is rolled on chimera spawn and stored
    as enemy.strike_element. Physical roll uses max_atk as minimum (hits hard).
    Costs 1 AP.
    """
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    element = getattr(enemy, "strike_element", "fire")

    # Element display names and flavour
    ELEMENT_FLAVOUR = {
        "fire":     ("🔥", "wreathed in flames",    "scorching"),
        "poison":   ("🟢", "dripping with venom",   "toxic"),
        "acid":     ("🧪", "coated in acid",        "corrosive"),
        "paralyze": ("⚡", "crackling with energy", "paralytic"),
    }
    icon, flavour, adj = ELEMENT_FLAVOUR.get(element, ("💥", "glowing", "elemental"))

    print(f"\n{icon} The Young Chimera lunges — its claws {flavour}!")
    print(f"💥 CHIMERA'S ELEMENTAL STRIKE!")

    # Physical roll: max_atk as floor (higher base, no crit ceiling bonus)
    raw_roll = random.randint(enemy.max_atk + b, enemy.max_atk + b + 2)
    dealt = monster_deal_damage(enemy, warrior, raw_roll, tag="Elemental Strike")

    # Apply full DoT matching the element
    if element == "fire":
        if not hasattr(warrior, "burns"):
            warrior.burns = []
        if len(warrior.burns) < 2:
            warrior.burns.append({"turns_left": 2, "skip": True, "bonus": b})
        else:
            weakest_idx = min(range(len(warrior.burns)),
                              key=lambda i: warrior.burns[i]["turns_left"])
            warrior.burns[weakest_idx] = {"turns_left": 2, "skip": True, "bonus": b}
        warrior.fire_stacks = len(warrior.burns)
        print(f"🔥 The {adj} blow ignites you! ({warrior.fire_stacks} burn stack{'s' if warrior.fire_stacks != 1 else ''})")

    elif element == "poison":
        warrior.poison_active = True
        warrior.poison_amount = 2 + b
        warrior.poison_turns  = 3          # slightly longer than slime (boss tier)
        warrior.poison_skip_first_tick = True
        print(f"🟢 The {adj} blow poisons you! (3 turns, {warrior.poison_amount}/turn)")

    elif element == "acid":
        if not hasattr(warrior, "acid_stacks"):
            warrior.acid_stacks = []
        if not hasattr(warrior, "acid_defence_loss"):
            warrior.acid_defence_loss = 0
        if len(warrior.acid_stacks) < 3:
            warrior.acid_stacks.append({"turns_left": 3, "skip": True})
        effective_def = max(0, warrior.defence - warrior.acid_defence_loss)
        if effective_def > 0 and warrior.acid_defence_loss < 3:
            warrior.acid_defence_loss += 1
            print(f"🧪 The {adj} blow eats at your armour!")
        else:
            warrior.hp = max(0, warrior.hp - 2)
            print(f"🧪 With no defence left the acid bites deep! (+2)")

    elif element == "paralyze":
        # Uses 2-turn paralyze — chimera tier
        if not (getattr(warrior, "turn_stop", 0) > 0
                or getattr(warrior, "turn_stop_chain_guard", False)
                or getattr(warrior, "post_paralyze_guard", False)):
            apply_turn_stop(warrior, turns=2, reason="Paralyzed")
            warrior.paralyze_vulnerable = True
            print(f"⚡ The {adj} blow seizes your muscles — PARALYZED for 2 turns!")
        else:
            print(f"⚡ The {adj} blow crackles over you but you shake it off!")

    show_health(warrior)
    return dealt


# =============================
# HERO MOVES
# =============================

def activate_death_defier(hero):
    """
    Uses the hero's turn to activate Death Defier.
    Costs 0 AP if unlocked from the river.
    Costs 1 AP if unlocked later by level.
    Does no damage, just sets the passive.
    """
    # Already primed or spent?
    if hero.death_defier_used:
        print("You've already used Death Defier this tournament.")
        return False

    if hero.death_defier_active:
        print("Death Defier is already active.")
        return False

    if not hero.death_defier:
        print("You don't have that ability.")
        return False

    # Cost based on how it was unlocked
    cost = 0 if hero.death_defier_river else 1

    if hero.ap < cost:
        print("You don't have enough AP.")
        return False

    hero.ap -= cost
    hero.death_defier_active = True

    print()
    print(wrap(
        "You close your eyes and chant, grounding your body and spirit to the land of the living."
        " You will not so easily succumb to death now."
    ))
    print(f"(Death Defier is now active. AP remaining: {hero.ap})")
    return True

def heal_ap_cost(rank: int) -> int:
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3
HEAL_PERCENTS = {
    1: 0.10,
    2: 0.15,
    3: 0.20,
    4: 0.25,
    5: 0.40,
}

def choose_heal_rank_smart(hero, learned_rank: int):
    learned_rank = min(learned_rank, 5)

    affordable = [
        r for r in range(1, learned_rank + 1)
        if hero.ap >= heal_ap_cost(r)
    ]

    if not affordable:
        print("You don't have enough AP for First Aid.")
        return None

    if len(affordable) == 1:
        return affordable[0]

    while True:
        print("\n🩹 Choose First Aid rank:")
        print(f"🔵 AP: {hero.ap}")
        print("0) Back")

        for r in range(learned_rank, 0, -1):
            cost = heal_ap_cost(r)
            label = f"Rank {r} ({int(HEAL_PERCENTS[r]*100)}%, Cost {cost} AP)"
            if hero.ap >= cost:
                print(f"  {r}) {label}")
            else:
                print(f"  {r}) {label} [NOT ENOUGH AP]")

        pick = input("> ").strip()
        if pick == "0":
            return None
        if pick.isdigit():
            r = int(pick)
            if 1 <= r <= learned_rank and hero.ap >= heal_ap_cost(r):
                return r
        print("Invalid choice.")

def heal(hero, chosen_rank=None, mode="rest"):
    learned = hero.skill_ranks.get("heal", 0)

    if learned <= 0:
        print("You haven't learned First Aid.")
        return False

    if hero.hp >= hero.max_hp:
        print("You're already at full health.")
        if mode != "combat":
            continue_text()
        return False

    learned = min(learned, 5)

    # Choose rank
    if chosen_rank is None:
        if mode == "combat":
            affordable = [r for r in range(1, learned + 1) if hero.ap >= heal_ap_cost(r)]
            if not affordable:
                print("You don't have enough AP for First Aid.")
                return False

            chosen_rank = max(affordable)
            cost = heal_ap_cost(chosen_rank)

            if cost == 3:
                pct = int(HEAL_PERCENTS[chosen_rank] * 100)
                ans = input(
                    f"\n🩹 First Aid will use Rank {chosen_rank} ({pct}%) for {cost} AP. Use it? (y/n): "
                ).strip().lower()
                if ans not in ("y", "yes"):
                    print("You hold off for now.")
                    return False
        else:
            chosen_rank = choose_heal_rank_smart(hero, learned)
            if chosen_rank is None:
                return False

    # Sanitize chosen rank
    chosen_rank = max(1, min(int(chosen_rank), learned))

    # Spend AP
    ap_cost = heal_ap_cost(chosen_rank)
    if hero.ap < ap_cost:
        print("Not enough AP!")
        return False
    hero.ap -= ap_cost

    # Apply heal (no overheal)
    percent = HEAL_PERCENTS[chosen_rank]
    heal_amount = math.ceil(hero.max_hp * percent)

    before = hero.hp
    hero.hp = min(hero.max_hp, hero.hp + heal_amount)
    actual = hero.hp - before

    print()
    print(wrap(
        f"🩹 You apply first aid, tending to your wounds. "
        f"You recover {actual} HP "
        f"({int(percent * 100)}%, Rank {chosen_rank})."
    ))

    # --- Status curing by rank ---
    cured = []

    # Rank 2+: cure Blind and Poison
    if chosen_rank >= 2:
        if getattr(hero, "blind_turns", 0) > 0:
            hero.blind_turns = 0
            hero.blind_long = False
            cured.append("Blind")
        if getattr(hero, "poison_active", False):
            hero.poison_active = False
            hero.poison_turns = 0
            hero.poison_amount = 0
            cured.append("Poison")

    # Rank 4+: also cure Paralyze and Burn
    if chosen_rank >= 4:
        if getattr(hero, "paralyzed", False):
            hero.paralyzed = False
            hero.paralyze_turns = 0
            cured.append("Paralyze")
        if getattr(hero, "burns", None):
            hero.burns = []
            hero.fire_stacks = 0
            cured.append("Burn")

    # Rank 5: also cure all status affects

    if chosen_rank >= 5:
        clear_all_status_effects(hero)
        cured.append("all statuses")
    if cured:
        print(wrap(f"✨ First Aid cures: {', '.join(cured)}!"))

    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    show_health(hero)

    return True

def war_cry_ap_cost(rank: int) -> int:
    # Match your “tiered” AP pattern:
    # R1-2: 1 AP, R3-4: 2 AP, R5: 3 AP
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3


WAR_CRY_EFFECTS = {
    1: (1, 3),  # +1 for 3 turns
    2: (2, 3),  # +2 for 3 turns
    3: (3, 3),  # +3 for 3 turns
    4: (3, 4),  # +3 for 4 turns
    5: (5, 3),  # +5 for 3 turns (special burst)
}

def war_cry(hero, chosen_rank=None):
    learned = hero.skill_ranks.get("war_cry", 0)
    if learned <= 0:
        print("You haven't learned War Cry.")
        return False

    learned = min(learned, 5)

    # Pick rank: in combat we auto-pick highest affordable (like your Heal/PS pattern)
    if chosen_rank is None:
        affordable = [r for r in range(1, learned + 1) if hero.ap >= war_cry_ap_cost(r)]
        if not affordable:
            print("You don't have enough AP for War Cry.")
            return False
        chosen_rank = max(affordable)
    else:
        chosen_rank = max(1, min(int(chosen_rank), learned))

    cost = war_cry_ap_cost(chosen_rank)
    if hero.ap < cost:
        print("Not enough AP!")
        return False

    bonus, turns = WAR_CRY_EFFECTS[chosen_rank]

    hero.ap -= cost

    # Re-cast friendly: overwrite bonus & reset duration
    hero.war_cry_bonus = bonus
    hero.war_cry_turns = turns
    hero.war_cry_skip_first_tick = True

    print()
    print(wrap(
        f"🗣️ You unleash a WAR CRY! "
        f"(Rank {chosen_rank}, Cost {cost} AP)\n"
        f"Your attacks surge with power: +{bonus} to attack rolls for {turns} turns."
    ))
    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    return True



def power_strike_ap_cost(rank: int) -> int:
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3


def power_strike_scaled_base(base_roll, rank):
    """
    Returns the Power Strike 'impact' amount based on the base_roll and rank.
    Ensures impact is always at least 1.
    """
    rank = int(rank)

    if rank <= 1:
        scaled = base_roll // 2              # half down
    elif rank == 2:
        scaled = (base_roll + 1) // 2        # half up
    elif rank == 3:
        scaled = (base_roll * 3) // 4        # 3/4 down
    elif rank == 4:
        scaled = (base_roll * 3 + 3) // 4    # 3/4 up (ceil)
    else:
        scaled = base_roll                   # full roll (rank 5+)

    return max(1, scaled)



def choose_power_strike_rank_smart(warrior, learned_rank: int):
    '''Chose power rank level to use if insufficient AP notify player'''
    learned_rank = min(learned_rank, 5)

    affordable = [r for r in range(1, learned_rank + 1) if warrior.ap >= power_strike_ap_cost(r)]
    if not affordable:
        print("You don't have enough AP!")
        return None

    

    # Only one usable option → no prompt
    if len(affordable) == 1:
        return affordable[0]
    
    while True:
        print("\n💥 Choose Power Strike rank:")
        print(f"🔵 AP: {warrior.ap}")
        print("0) Back")
        # Show all ranks that can be afforded
        for r in range(learned_rank, 0, -1):
            cost = power_strike_ap_cost(r)
            if warrior.ap >= cost:
                print(f"  {r}) Rank {r} (Cost {cost} AP)")
            else:
                print(f"  {r}) Rank {r} (Cost {cost} AP, [NOT ENOUGH AP])")
        pick = input("> ").strip()
        if pick == "0":
            return None
        if not pick.isdigit():
            print("Please enter a number")
            continue
        chosen = int(pick)
        if chosen < 1 or chosen > learned_rank:
            print("Invalid rank.")
            continue

        cost = power_strike_ap_cost(chosen)
        if warrior.ap < cost:
            print("Not enough AP for that rank.")
            continue
        return chosen

def get_power_strike_bonus(warrior):
    """
    Returns the flat bonus Power Strike is allowed to use.
    """
    if getattr(warrior, "berserk_active", False):
        # Berserk active → cap bonus
        return 3  # fixed adrenaline-style bonus
    return getattr(warrior, "current_bonus_damage", 0)



   
   

# ============================================================
# POWER STRIKE (split HIT vs SCALING, both via the same policy)
# ============================================================

def power_strike(warrior, enemy, chosen_rank=None):
    learned = warrior.skill_ranks.get("power_strike", 0)
    if learned <= 0:
        print("You haven't learned Power Strike.")
        return False

    max_rank = min(learned, 5)

    # Choose rank (keep your existing behavior)
    if chosen_rank is not None:
        chosen_rank = max(1, min(int(chosen_rank), max_rank))
    else:
        chosen_rank = choose_power_strike_rank_smart(warrior, learned)
        if chosen_rank is None:
            return False
        chosen_rank = max(1, min(int(chosen_rank), max_rank))

    ap_cost = power_strike_ap_cost(chosen_rank)
    if warrior.ap < ap_cost:
        print("Not enough AP!")
        return False
    warrior.ap -= ap_cost

    base_roll = warrior_attack_roll(warrior)

    # --------------------------
    # A) HIT portion (Berserk applies here)
    # --------------------------
    hit_bonus, hit_parts = get_damage_bonuses(warrior, "power_strike_hit", ps_rank=chosen_rank)
    hit_parts_txt = bonus_parts_to_text(hit_parts)

    # Keep current_bonus_damage consistent for anything else that reads it:
    # (we keep it meaning "adrenaline shown on HUD", not the capped PS value)
    warrior.current_bonus_damage = hit_parts.get("adrenaline", 0)

    roll_total = base_roll + hit_bonus  # <-- berserk affects the hit

    # --------------------------
    # B) SCALING base (Berserk does NOT apply here; adrenaline controlled here)
    # --------------------------
    scale_bonus, _scale_parts = get_damage_bonuses(warrior, "power_strike_scaling", ps_rank=chosen_rank)
    impact_base = base_roll + scale_bonus  # <-- no berserk here

    impact = power_strike_scaled_base(impact_base, chosen_rank)

    total_raw = roll_total + impact

    # --------------------------
    # BLINDNESS scaling (keep your existing behavior)
    # --------------------------
    raw_for_defence = total_raw
    if getattr(warrior, "blind_turns", 0) > 0:
        mult = 0.5 if warrior.blind_turns >= 2 else 0.75
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"👁️ Blinded! Power Strike hits at {int(mult * 100)}% power.")

    final = enemy.apply_defence(raw_for_defence, attacker=warrior)
    enemy.hp = max(0, enemy.hp - final)

    blocked = raw_for_defence - final

    # --------------------------
    # One-line breakdown
    # --------------------------
    print(f"\nPOWER STRIKE! (Rank {chosen_rank}, Cost {ap_cost} AP)")

    parts = [f"Roll {base_roll}"] + hit_parts_txt + [f"Power Strike {impact}"]
    if raw_for_defence != total_raw:
        mult = 0.5 if warrior.blind_turns >= 2 else 0.75
        pct = int(mult * 100)
        parts.append(f"→ Blinded ({pct}% power) → {raw_for_defence}")

    # this is where damage is calculated
    line = f"You smash {enemy.display_name} for {final} damage! (" + " + ".join(parts) + ")"
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))

    # --------------------------
    # Berserk timing rules (keep your existing behavior)
    # --------------------------
    if getattr(warrior, "berserk_active", False):
        if enemy.hp <= 0:
            warrior.berserk_turns += 1
            print("The kill feeds your frenzy! Berserk extended by 1 turn!")

        warrior.berserk_turns -= 1
        if warrior.berserk_turns <= 0:
            deactivate_berserk(warrior)
            print("Your berserk fury subsides...")

    if DEBUG:
        print(
            f"[DEBUG] base_roll={base_roll}, hit_bonus={hit_bonus}, roll_total={roll_total}, "
            f"scale_bonus={scale_bonus}, impact_base={impact_base}, impact={impact}, "
            f"total_raw={total_raw}, raw_for_defence={raw_for_defence}, final={final}"
        )

    return True




# ===============================
# Base Classes
# ===============================
# we are creating a better way to incorperate dev shortcuts
class RestartException(Exception):
    pass

class QuickCombatException(Exception):
    pass

class GameOverException(Exception):
    pass

class Equipment:
    def __init__(
        self,
        name,
        slot,
        rarity="poor",
        tier=1,
        atk_min=0,
        atk_max=0,
        defence=0,
        max_hp=0,
        element=None,
        element_damage=0,
        element_turns=0,
        element_restore=0,
        recipe=None,
        gold_cost=0,
        proc_chance=0.0,      # weapon proc: chance to trigger bonus effect on hit
        proc_bonus=0,         # weapon proc: flat bonus damage (Imp Trident)
        blind_chance=0.0,     # weapon proc: chance to blind on hit (Goblin Dagger)
        element_max_dots=1,   # max simultaneous DoT stacks (rare+ sacs allow >1)
        paralyze_chance=0.0,  # accessory proc: chance to paralyze on hit (Paralyzing Arrow)
        paralyze_turns=0,     # accessory proc: how many turns paralyze lasts
        drain_bonus=0,        # accessory proc: bonus damage + heal (Soul Pendant)
        drain_heal_min=0,     # accessory proc: min HP recovered on drain hit
        drain_heal_max=0,     # accessory proc: max HP recovered on drain hit
        bleed_turns=0,        # weapon proc: bleed duration (Javelina Tusk)
        element_erosion=0,    # accessory proc: immediate DEF reduction on acid hit (Acid Sac normal+)
    ):
        self.name             = name
        self.slot             = slot
        self.rarity           = rarity
        self.tier             = tier
        self.atk_min          = atk_min
        self.atk_max          = atk_max
        self.defence          = defence
        self.max_hp           = max_hp
        self.element          = element
        self.element_damage   = element_damage
        self.element_turns    = element_turns
        self.element_restore  = element_restore
        self.element_max_dots = element_max_dots
        self.element_erosion  = element_erosion
        self.recipe           = recipe
        self.gold_cost        = gold_cost
        self.proc_chance      = proc_chance
        self.proc_bonus       = proc_bonus
        self.blind_chance     = blind_chance
        self.paralyze_chance  = paralyze_chance
        self.paralyze_turns   = paralyze_turns
        self.drain_bonus      = drain_bonus
        self.drain_heal_min   = drain_heal_min
        self.drain_heal_max   = drain_heal_max
        self.bleed_turns      = bleed_turns

    def stat_lines(self):
        RARITY_COLORS = {
            "poor":     "⬜",       # white square
            "normal":   "🟦",   # blue square
            "uncommon": "🟩",   # green square
            "rare":     "🟨",   # yellow square
            "epic":     "🟪",   # purple square
            "legendary":"🟥",   # red square
        }
        icon = RARITY_COLORS.get(self.rarity, "⬜")
        lines = [f"{icon} {self.rarity.title()} | {self.name}"]
        if self.atk_min or self.atk_max:
            lines.append(f"  ⚔️  ATK +{self.atk_min}/+{self.atk_max}")
        if self.defence:
            lines.append(f"  🛡️  DEF +{self.defence}")
        if self.max_hp:
            lines.append(f"  ❤️  HP +{self.max_hp}")
        if self.element:
            dots = getattr(self, "element_max_dots", 1)
            dot_txt = f", max {dots} stacks" if dots > 1 else ""
            lines.append(f"  ✨ {self.element.title()} {self.element_damage} dmg ({self.element_turns} turns{dot_txt})")
        if self.proc_chance > 0:
            lines.append(f"  ⚡ {int(self.proc_chance*100)}% chance +{self.proc_bonus} bonus dmg")
        if self.blind_chance > 0:
            lines.append(f"  👁️  {int(self.blind_chance*100)}% chance to blind")
        if self.drain_bonus > 0:
            lines.append(f"  🩸 Drain: +{self.drain_bonus} dmg, heals {self.drain_heal_min}–{self.drain_heal_max} HP")
        return lines
    
    def short_label(self):
        RARITY_COLORS = {
            "poor":     "⬜",       # white square
            "normal":   "🟦",   # blue square
            "uncommon": "🟩",   # green square
            "rare":     "🟨",   # yellow square
            "epic":     "🟪",   # purple square
            "legendary":"🟥",   # red square
        }
        icon        = RARITY_COLORS.get(self.rarity, "⬜")
        rarity_word = self.rarity.title()
        header      = f"{icon} {rarity_word} {self.name}"
        stat_rows   = self.stat_lines()[1:]   # everything after the name/rarity header
        if stat_rows:
            return header + "\n" + "\n".join(stat_rows)
        return header

# ================================================================
# LOOT TABLE
# ================================================================

# ----------------------------------------------------------------
# RARITY LADDER (low → high)
# poor < normal < uncommon < rare < epic < legendary
#
# Drop odds table (normal play — rare/epic/legendary are debug-only for now):
#   Level 1:   65% poor / 25% normal / 10% uncommon
#   Level 2:   40% poor / 45% normal / 15% uncommon
#   Level 3:   15% poor / 50% normal / 35% uncommon
#   Round 1:   30% poor / 50% normal / 20% uncommon  (first kill bonus)
#
# When higher-tier enemies are added in future, pass force_rarity="rare" etc.
# to make_loot() to bypass the roll entirely.
# ----------------------------------------------------------------
RARITY_ORDER = ["poor", "normal", "uncommon", "rare", "epic", "legendary"]

def roll_rarity(monster_level=1, round_num=0):
    """Returns a rarity string based on monster level and round.
    rare/epic/legendary are not yet on the natural drop table —
    they can be granted via debug menu or future high-tier monsters."""
    if round_num == 1:
        thresholds = (30, 80)   # <=30 poor, <=80 normal, else uncommon
    elif monster_level >= 3:
        thresholds = (15, 65)
    elif monster_level == 2:
        thresholds = (40, 85)
    else:
        thresholds = (65, 90)

    r = random.randint(1, 100)
    if r <= thresholds[0]:
        return "poor"
    elif r <= thresholds[1]:
        return "normal"
    else:
        return "uncommon"


# Stat tables per rarity for each sac.
# Stored as plain dicts so adding a new rarity tier later is one line.
# Format: rarity -> (element_damage, element_turns, def_restore_turns)
# def_restore_turns only used by acid — ignored by poison/fire.

POISON_SAC_STATS = {
    # Format: (element_damage, element_turns, def_restore_turns, max_dots)
    "poor":     (1, 1, 0, 1),
    "normal":   (1, 2, 0, 1),
    "uncommon": (2, 3, 0, 1),
    "rare":     (3, 4, 0, 2),   # 2 stacks, 4 turns each
    "epic":     (3, 5, 0, 2),   # 2 stacks, 5 turns each
    "legendary":(4, 6, 0, 3),   # 3 stacks, 6 turns each
}

FIRE_SAC_STATS = {
    # Format: (element_damage, element_turns, def_restore_turns, max_dots)
    "poor":     (2, 1, 0, 1),
    "normal":   (2, 2, 0, 1),
    "uncommon": (3, 3, 0, 1),
    "rare":     (4, 4, 0, 2),   # 2 stacks, 4 turns each
    "epic":     (4, 5, 0, 2),   # 2 stacks, 5 turns each
    "legendary":(5, 6, 0, 3),   # 3 stacks, 6 turns each
}

ACID_SAC_STATS = {
    # Format: (element_damage, element_turns, def_restore_turns, max_dots, def_erosion)
    # def_restore_turns = how many turns until DEF restores (0 = no erosion)
    # def_erosion       = how much DEF is immediately reduced on hit (0 = none)
    "poor":     (3, 1, 0, 1, 0),   # 3 dmg, 1 turn,  no DEF erosion
    "normal":   (3, 2, 2, 1, 1),   # 3 dmg, 2 turns, -1 DEF immediately, restores after 2 turns
    "uncommon": (4, 2, 2, 1, 2),   # 4 dmg, 2 turns, -2 DEF immediately, restores after 2 turns (no stack, clock resets)
    "rare":     (4, 3, 3, 2, 2),   # 2 stacks, 3 turns each, -2 DEF
    "epic":     (5, 4, 4, 2, 3),   # 2 stacks, 4 turns each, -3 DEF
    "legendary":(6, 5, 5, 3, 4),   # 3 stacks, 5 turns each, -4 DEF
}

# ----------------------------------------------------------------
# Wolf Pelt  (armor)
# poor:     +1 def
# normal:   +1 def, +1 max_hp
# uncommon: +2 def, +1 max_hp
# ----------------------------------------------------------------
WOLF_PELT_STATS = {
    "poor":     {"defence": 1, "max_hp": 0},
    "normal":   {"defence": 1, "max_hp": 1},
    "uncommon": {"defence": 2, "max_hp": 1},
    "rare":     {"defence": 2, "max_hp": 2},
    "epic":     {"defence": 3, "max_hp": 2},
    "legendary":{"defence": 3, "max_hp": 3},
}

# ----------------------------------------------------------------
# Dire Wolf Pelt  (armor)
# poor:     +2 def
# normal:   +2 def, +2 max_hp
# uncommon: +3 def, +2 max_hp
# ----------------------------------------------------------------
DIRE_WOLF_PELT_STATS = {
    "poor":     {"defence": 2, "max_hp": 0},
    "normal":   {"defence": 2, "max_hp": 2},
    "uncommon": {"defence": 3, "max_hp": 2},
    "rare":     {"defence": 3, "max_hp": 3},
    "epic":     {"defence": 4, "max_hp": 3},
    "legendary":{"defence": 4, "max_hp": 4},
}

# ----------------------------------------------------------------
# Bone Sword  (weapon)
# poor:     +1 atk min/max
# normal:   +1 atk, +1 def
# uncommon: +2 atk, +1 def
# ----------------------------------------------------------------
RUSTED_SWORD_STATS = {
    "poor":     {"atk_min": 1, "atk_max": 1, "defence": 0},
    "normal":   {"atk_min": 1, "atk_max": 1, "defence": 1},
    "uncommon": {"atk_min": 2, "atk_max": 2, "defence": 1},
    "rare":     {"atk_min": 2, "atk_max": 3, "defence": 1},
    "epic":     {"atk_min": 3, "atk_max": 3, "defence": 2},
    "legendary":{"atk_min": 3, "atk_max": 4, "defence": 2},
}

# ----------------------------------------------------------------
# Imp Trident  (weapon)
# poor:     +1 atk
# normal:   +1 atk, 25% chance +1 bonus damage on hit  (proc_chance / proc_bonus)
# uncommon: +2 atk, 50% chance +1 bonus damage on hit
# ----------------------------------------------------------------
IMP_TRIDENT_STATS = {
    "poor":     {"atk_min": 1, "atk_max": 1, "proc_chance": 0.0,  "proc_bonus": 0},
    "normal":   {"atk_min": 1, "atk_max": 1, "proc_chance": 0.25, "proc_bonus": 1},
    "uncommon": {"atk_min": 2, "atk_max": 2, "proc_chance": 0.50, "proc_bonus": 1},
    "rare":     {"atk_min": 2, "atk_max": 2, "proc_chance": 0.50, "proc_bonus": 2},
    "epic":     {"atk_min": 3, "atk_max": 3, "proc_chance": 0.60, "proc_bonus": 2},
    "legendary":{"atk_min": 3, "atk_max": 4, "proc_chance": 0.75, "proc_bonus": 3},
}

# ----------------------------------------------------------------
# Goblin Dagger  (weapon)
# poor:     +1 atk
# normal:   +1 atk, 25% chance to blind on hit
# uncommon: +2 atk, 50% chance to blind on hit
# Blind uses the existing goblin_dust system:
#   turn 1 → lose action, turns 2-3 → reduced damage, turn 4 → full damage
# Blind cannot be reapplied until the current blind has fully expired.
# ----------------------------------------------------------------
GOBLIN_DAGGER_STATS = {
    "poor":     {"atk_min": 1, "atk_max": 1, "blind_chance": 0.0},
    "normal":   {"atk_min": 1, "atk_max": 1, "blind_chance": 0.25},
    "uncommon": {"atk_min": 2, "atk_max": 2, "blind_chance": 0.50},
    "rare":     {"atk_min": 2, "atk_max": 2, "blind_chance": 0.65},
    "epic":     {"atk_min": 3, "atk_max": 3, "blind_chance": 0.75},
    "legendary":{"atk_min": 3, "atk_max": 4, "blind_chance": 0.90},
}

PARALYZING_ARROW_STATS = {
    "poor":     {"atk_min": 2, "atk_max": 2, "paralyze_chance": 0.25, "paralyze_turns": 1},
    "normal":   {"atk_min": 2, "atk_max": 2, "paralyze_chance": 0.35, "paralyze_turns": 2},
    "uncommon": {"atk_min": 3, "atk_max": 3, "paralyze_chance": 0.50, "paralyze_turns": 3},
    "rare":     {"atk_min": 3, "atk_max": 3, "paralyze_chance": 0.60, "paralyze_turns": 3},
    "epic":     {"atk_min": 4, "atk_max": 4, "paralyze_chance": 0.70, "paralyze_turns": 4},
    "legendary":{"atk_min": 4, "atk_max": 5, "paralyze_chance": 0.85, "paralyze_turns": 5},
}


# ----------------------------------------------------------------
# Javelina Tusk  (weapon)
# poor:     +2 atk, bleed 1 turn
# normal:   +2 atk, bleed 2 turns
# uncommon: +3 atk, bleed 3 turns
# Bleed deals 2 damage per turn (flat, ignores defence)
# ----------------------------------------------------------------
JAVELINA_TUSK_STATS = {
    "poor":     {"atk_min": 2, "atk_max": 2, "bleed_turns": 1},
    "normal":   {"atk_min": 2, "atk_max": 2, "bleed_turns": 2},
    "uncommon": {"atk_min": 3, "atk_max": 3, "bleed_turns": 3},
    "rare":     {"atk_min": 3, "atk_max": 4, "bleed_turns": 3},
    "epic":     {"atk_min": 4, "atk_max": 4, "bleed_turns": 4},
    "legendary":{"atk_min": 4, "atk_max": 5, "bleed_turns": 5},
}

# ----------------------------------------------------------------
# Soul Pendant  (accessory) — Ghost drop
# Hits enemy for bonus true damage and heals the player
# poor:     +2 bonus dmg, heal 1
# normal:   +2 bonus dmg, heal 1-2
# uncommon: +3 bonus dmg, heal 2-3
# ----------------------------------------------------------------
SOUL_PENDANT_STATS = {
    "poor":     {"drain_bonus": 2, "drain_heal_min": 1, "drain_heal_max": 1},
    "normal":   {"drain_bonus": 2, "drain_heal_min": 1, "drain_heal_max": 2},
    "uncommon": {"drain_bonus": 3, "drain_heal_min": 2, "drain_heal_max": 3},
    "rare":     {"drain_bonus": 3, "drain_heal_min": 2, "drain_heal_max": 4},
    "epic":     {"drain_bonus": 4, "drain_heal_min": 3, "drain_heal_max": 5},
    "legendary":{"drain_bonus": 5, "drain_heal_min": 3, "drain_heal_max": 6},
}

# ----------------------------------------------------------------
# Rider's Armor  (armor) — Wolf Pup Rider drop
# poor:     +3 def
# normal:   +3 def, +2 max_hp
# uncommon: +4 def, +2 max_hp
# ----------------------------------------------------------------
RIDERS_ARMOR_STATS = {
    "poor":     {"defence": 3, "max_hp": 0},
    "normal":   {"defence": 3, "max_hp": 2},
    "uncommon": {"defence": 4, "max_hp": 2},
    "rare":     {"defence": 4, "max_hp": 3},
    "epic":     {"defence": 5, "max_hp": 3},
    "legendary":{"defence": 5, "max_hp": 4},
}

# ----------------------------------------------------------------
# Weapon Core  (weapon) — Fallen Warrior drop
# A mysterious nano-tech artifact that adapts to its wielder.
# Tier 4 item.  Player chooses form immediately on drop.
# Core reverts to a cube after the final fight and is passed to the
# player's son — the form choice here shapes the son's weapon.
#
# Defensive Form — One-Handed Sword (balanced atk + def):
#   poor:     +3 atk, +2 def
#   normal:   +3 atk, +3 def
#   uncommon: +4 atk, +4 def
#   rare:     +4 atk, +5 def
#   epic:     +5 atk, +5 def
#   legendary:+5 atk, +6 def
#
# Offensive Form — Two-Handed Sword (raw power, minimal def):
#   poor:     +4 atk, +1 def
#   normal:   +5 atk, +1 def
#   uncommon: +6 atk, +2 def
#   rare:     +7 atk, +2 def
#   epic:     +8 atk, +3 def
#   legendary:+9 atk, +3 def
# ----------------------------------------------------------------
WEAPON_CORE_DEFENSIVE_STATS = {
    "poor":     {"atk_min": 3, "atk_max": 3, "defence": 2},
    "normal":   {"atk_min": 3, "atk_max": 3, "defence": 3},
    "uncommon": {"atk_min": 4, "atk_max": 4, "defence": 4},
    "rare":     {"atk_min": 4, "atk_max": 4, "defence": 5},
    "epic":     {"atk_min": 5, "atk_max": 5, "defence": 5},
    "legendary":{"atk_min": 5, "atk_max": 5, "defence": 6},
}

WEAPON_CORE_OFFENSIVE_STATS = {
    "poor":     {"atk_min": 4, "atk_max": 4, "defence": 1},
    "normal":   {"atk_min": 5, "atk_max": 5, "defence": 1},
    "uncommon": {"atk_min": 6, "atk_max": 6, "defence": 2},
    "rare":     {"atk_min": 7, "atk_max": 7, "defence": 2},
    "epic":     {"atk_min": 8, "atk_max": 8, "defence": 3},
    "legendary":{"atk_min": 9, "atk_max": 9, "defence": 3},
}

# ----------------------------------------------------------------
# Chimera Scale  (armor) — Young Chimera drop
# Debug-only placeholder for now. Rarity locked to poor.
# Stats may change when the son's story is developed.
# poor:     +5 def
# ----------------------------------------------------------------
CHIMERA_SCALE_STATS = {
    "poor":     {"defence": 5, "max_hp": 0},
    "normal":   {"defence": 6, "max_hp": 1},
    "uncommon": {"defence": 7, "max_hp": 2},
    "rare":     {"defence": 8, "max_hp": 2},
    "epic":     {"defence": 9, "max_hp": 3},
    "legendary":{"defence": 10, "max_hp": 3},
}

def _make_weapon_core(rarity):
    """
    Called when the Fallen Warrior drops the Weapon Core.
    Player chooses Defensive (balanced) or Offensive (raw power) form.
    The choice is permanent for this run — the core adapts on the spot.
    """
    print("\n" + "═" * 50)
    print("   ⚙️  THE WEAPON CORE STIRS")
    print("═" * 50)
    print(wrap(
        "The Fallen Warrior's weapon dissolves into a dense, humming cube "
        "that floats into your palm. It pulses faintly — waiting. "
        "You feel it reading you, deciding what to become."
    ))
    print()
    print(wrap("It can take one of two forms. Choose carefully — it will not change again."))
    print()

    d = WEAPON_CORE_DEFENSIVE_STATS[rarity]
    o = WEAPON_CORE_OFFENSIVE_STATS[rarity]

    print(f"  1) Defensive Form  — One-Handed Sword")
    print(f"       ⚔️  ATK +{d['atk_min']}   🛡️  DEF +{d['defence']}")
    print(f"       Balanced. Lets you keep a shield or accessory.")
    print()
    print(f"  2) Offensive Form  — Two-Handed Sword")
    print(f"       ⚔️  ATK +{o['atk_min']}   🛡️  DEF +{o['defence']}")
    print(f"       Raw power. Leaves no room for accessories.")
    print()

    while True:
        choice = _real_input("Choose a form (1 or 2): ").strip()
        if choice == "1":
            stats = d
            form_name = "Weapon Core [Defensive Form]"
            print(wrap("\nThe cube flattens and elongates into a sleek one-handed blade. "
                       "Its edge gleams with quiet authority."))
            break
        elif choice == "2":
            stats = o
            form_name = "Weapon Core [Offensive Form]"
            print(wrap("\nThe cube unfolds into a massive two-handed sword. "
                       "The weight of it is immense — and perfectly balanced for destruction."))
            break
        else:
            print("Enter 1 or 2.")

    print()
    return Equipment(
        name    = form_name,
        slot    = "weapon",
        rarity  = rarity,
        atk_min = stats["atk_min"],
        atk_max = stats["atk_min"],   # atk_min == atk_max in both tables
        defence = stats["defence"],
    )


def make_loot(monster_name, monster_level=1, round_num=0):
    rarity = roll_rarity(monster_level=monster_level, round_num=round_num)

    table = {
        # ── Tier 1 accessories (already done) ──────────────────
        "Green Slime": lambda: Equipment(
            name             = "Poison Sac",
            slot             = "accessory",
            rarity           = rarity,
            element          = "poison",
            element_damage   = POISON_SAC_STATS[rarity][0],
            element_turns    = POISON_SAC_STATS[rarity][1],
            element_max_dots = POISON_SAC_STATS[rarity][3],
        ),
        "red slime": lambda: Equipment(
            name             = "Fire Sac",
            slot             = "accessory",
            rarity           = rarity,
            element          = "fire",
            element_damage   = FIRE_SAC_STATS[rarity][0],
            element_turns    = FIRE_SAC_STATS[rarity][1],
            element_max_dots = FIRE_SAC_STATS[rarity][3],
        ),
        "Hydra Hatchling": lambda: Equipment(
            name             = "Acid Sac",
            slot             = "accessory",
            rarity           = rarity,
            element          = "acid",
            element_damage   = ACID_SAC_STATS[rarity][0],
            element_turns    = ACID_SAC_STATS[rarity][1],
            element_restore  = ACID_SAC_STATS[rarity][2],
            element_max_dots = ACID_SAC_STATS[rarity][3],
            element_erosion  = ACID_SAC_STATS[rarity][4],
        ),

        # ── Tier 1 new drops ───────────────────────────────────
        "Wolf Pup": lambda: Equipment(
            name    = "Wolf Pelt",
            slot    = "armor",
            rarity  = rarity,
            defence = WOLF_PELT_STATS[rarity]["defence"],
            max_hp  = WOLF_PELT_STATS[rarity]["max_hp"],
        ),

        "Dire Wolf Pup": lambda: Equipment(
            name    = "Dire Wolf Pelt",
            slot    = "armor",
            rarity  = rarity,
            defence = DIRE_WOLF_PELT_STATS[rarity]["defence"],
            max_hp  = DIRE_WOLF_PELT_STATS[rarity]["max_hp"],
        ),

        "Brittle Skeleton": lambda: Equipment(
            name    = "Rusted Sword",
            slot    = "weapon",
            rarity  = rarity,
            atk_min = RUSTED_SWORD_STATS[rarity]["atk_min"],
            atk_max = RUSTED_SWORD_STATS[rarity]["atk_max"],
            defence = RUSTED_SWORD_STATS[rarity]["defence"],
        ),

        "Imp": lambda: Equipment(
            name        = "Imp Trident",
            slot        = "weapon",
            rarity      = rarity,
            atk_min     = IMP_TRIDENT_STATS[rarity]["atk_min"],
            atk_max     = IMP_TRIDENT_STATS[rarity]["atk_max"],
            proc_chance = IMP_TRIDENT_STATS[rarity]["proc_chance"],
            proc_bonus  = IMP_TRIDENT_STATS[rarity]["proc_bonus"],
        ),

        "Young Goblin": lambda: Equipment(
            name        = "Goblin Dagger",
            slot        = "weapon",
            rarity      = rarity,
            atk_min     = GOBLIN_DAGGER_STATS[rarity]["atk_min"],
            atk_max     = GOBLIN_DAGGER_STATS[rarity]["atk_max"],
            blind_chance = GOBLIN_DAGGER_STATS[rarity]["blind_chance"],
        ),
        "Goblin Archer": lambda: Equipment(
            name            = "Paralyzing Arrow",
            slot            = "accessory",
            rarity          = rarity,
            atk_min         = PARALYZING_ARROW_STATS[rarity]["atk_min"],
            atk_max         = PARALYZING_ARROW_STATS[rarity]["atk_max"],
            paralyze_chance = PARALYZING_ARROW_STATS[rarity]["paralyze_chance"],
            paralyze_turns  = PARALYZING_ARROW_STATS[rarity]["paralyze_turns"],
        ),

        # ── Tier 2 new drops ───────────────────────────────────
        "Javelina": lambda: Equipment(
            name        = "Javelina Tusk",
            slot        = "weapon",
            rarity      = rarity,
            atk_min     = JAVELINA_TUSK_STATS[rarity]["atk_min"],
            atk_max     = JAVELINA_TUSK_STATS[rarity]["atk_max"],
            bleed_turns = JAVELINA_TUSK_STATS[rarity]["bleed_turns"],
        ),

        "Noob Ghost": lambda: Equipment(
            name          = "Soul Pendant",
            slot          = "accessory",
            rarity        = rarity,
            drain_bonus   = SOUL_PENDANT_STATS[rarity]["drain_bonus"],
            drain_heal_min= SOUL_PENDANT_STATS[rarity]["drain_heal_min"],
            drain_heal_max= SOUL_PENDANT_STATS[rarity]["drain_heal_max"],
        ),

        "Wolf Pup Rider": lambda: Equipment(
            name    = "Rider's Armor",
            slot    = "armor",
            rarity  = rarity,
            defence = RIDERS_ARMOR_STATS[rarity]["defence"],
            max_hp  = RIDERS_ARMOR_STATS[rarity]["max_hp"],
        ),

        "Fallen Warrior": lambda: _make_weapon_core(rarity),

        # ── Debug-only drops ───────────────────────────────────
        "Young Chimera": lambda: Equipment(
            name    = "Chimera Scale",
            slot    = "armor",
            rarity  = "poor",   # locked to poor placeholder
            defence = CHIMERA_SCALE_STATS["poor"]["defence"],
            max_hp  = CHIMERA_SCALE_STATS["poor"]["max_hp"],
        ),
    }
    
    factory = table.get(monster_name)
    return factory() if factory else None


# =============================================================================
# CLASS HIERARCHY & ATTRIBUTE REFERENCE
# =============================================================================
#
# Creator  (base — shared by BOTH Monster and Hero)
#   .name, .hp, .max_hp
#   .min_atk, .max_atk      <- ALWAYS use these names, never .attack/.max_attack
#   .gold, .xp, .defence
#   .is_alive()  .take_damage()  .attack_roll()  .apply_defence()
#
# Monster(Creator)
#   .essence, .ap, .special_move, .rounds_in_combat
#   .level, .variant_title, .display_name (property)
#   .turns_survived          <- set during chimera fight
#
# Hero(Creator)              <- template for ALL playable classes
#   COMBAT:     .ap/.max_ap, .max_overheal, .current_bonus_damage
#   GEAR:       .inventory, .equipment, .equipment_bonus_damage
#   POTIONS:    .potions (dict)
#   PROGRESS:   .level, .xp_to_lvl, .level_cap, .stat_points, .skill_points
#               .spent_stats_this_level, .spent_skills_this_level
#   SKILLS:     .skills (set), .skill_ranks (dict), .skill_progress
#   STORY:      .titles, .achievements, .bestiary, .endings
#               .monster_essence, .story_flags, .trainer_seen, .death_reason
#   STATUS FX:  .poison_active/.amount/.turns/.skip_first_tick
#               .is_blinded, .blind_type, .blind_turns, .blind_long
#               .burns, .fire_stacks
#               .acid_stacks, .acid_defence_loss
#               .paralyzed, .paralyze_turns, .paralyze_vulnerable, .post_paralyze_guard
#               .turn_stop, .turn_stop_reason, .turn_stop_chain_guard
#               .bleed_turns    <- reserved for Thief / future content
#               .skip_turns     <- paralyze application
#   FUTURE:     .mana/.max_mana  <- Mage placeholder (0 on Warrior, real on Mage)
#               Thief section reserved
#
# Warrior(Hero)              <- current playable class
#   ADRENALINE: .perm_special, .temp_special, .total_special, .special_name
#   RAGE:       .max_rage, .rage_state
#   BERSERK:    .berserk_active, .berserk_pending, .berserk_used
#               .berserk_turns, .berserk_bonus
#   WAR CRY:    .war_cry_bonus, .war_cry_turns, .war_cry_skip_first_tick
#   DEATH DEF:  .death_defier, .death_defier_river
#               .death_defier_active, .death_defier_used
#
# SAFE ACCESS PATTERN — use when attribute may not exist on a given object:
#   getattr(warrior, "berserk_active", False)
#   getattr(enemy,   "defence",        0)
# =============================================================================
class Creator:
    def __init__(self, name, hp, min_atk, max_atk, gold=0, xp=0, defence=0):
        self.name = name
        self.hp = hp
        self.max_hp = hp   # track max HP for heals / level ups
        self.min_atk = min_atk
        self.max_atk = max_atk
        self.gold = gold
        self.xp = xp
        self.defence = defence  # currently informational (not reducing damage)

    def is_alive(self):
        return self.hp > 0

    def take_damage(self, amount):
        """Apply damage and clamp HP at 0."""
        self.hp = max(self.hp - amount, 0)

    def attack_roll(self):
        """Basic attack roll within min/max."""
        return random.randint(self.min_atk, self.max_atk)
    
    def apply_defence(self, damage, attacker=None, defence_break=False, true_block=False):
        """Return final damage after defence rules and print appropriate block text.
        IMPORTANT: This function does NOT subtract HP. Caller subtracts HP.
        """

        attacker_name = attacker.name if attacker else "The attacker"

        # ---------------------------------------------
        # 🛡️ True full block (explicit only: Block skill, special Berserk logic, etc.)
        # ---------------------------------------------
        if true_block:
            print(full_defensive_block(attacker, self))
            return 0

        # ---------------------------------------------
        # 💥 Berserk damage reduction (take half damage)
        # This uses getattr so Creator has no hard dependency on
        # Warrior-specific attributes — any subclass that sets
        # berserk_active=True will automatically get the reduction.
        # ---------------------------------------------
        if getattr(self, "berserk_active", False):
            damage = max(1, damage // 2)

        # ---------------------------------------------
        # 🔥 Defence-break attacks bypass armour reduction
        # ---------------------------------------------
        if defence_break:
            print(wrap(f"{attacker_name}'s brutal strike shatters your defenses!"))
            print(wrap(f"{self.name} is knocked backwards by the impact!"))
            # defence_break ignores armour, but still respects minimum 1 damage
            return max(1, damage)
        # ---------------------------------------------
        # 🧪 Acid erosion (fight-only): reduce effective defence
        # ---------------------------------------------
        effective_def = max(0, self.defence - getattr(self, "acid_defence_loss", 0))


        # ---------------------------------------------
        # 🧮 Compute block ratio for flavor (BEFORE minimum damage rule)
        # ---------------------------------------------
        blocked_amount = min(effective_def, damage)
        block_ratio = (blocked_amount / damage) if damage > 0 else 0

        # ---------------------------------------------
        # 📝 Flavor tiers (based on % blocked, NOT on final damage)
        # ---------------------------------------------
        if block_ratio >= 0.75:
            print(strong_defensive_block(attacker, self))
        elif block_ratio >= 0.50:
            print(solid_defensive_block(attacker, self, blocked_amount))
        elif block_ratio > 0:
            print(weak_defensive_block(attacker, self))
        # else: optionally print nothing (cleaner), or add a "clean hit" message elsewhere

        # ---------------------------------------------
        # ✅ Final damage (minimum 1 damage rule)
        # ---------------------------------------------
        actual = damage - effective_def
        actual = max(1, actual)

        return actual




class Monster(Creator):
    def __init__(
        self,
        name,
        hp,
        min_atk,
        max_atk,
        gold,
        xp,
        essence,
        defence=0,
        ap=0,
        special_move=None,
        level=1,
        variant_title=None
    ):
        super().__init__(
            name=name,
            hp=hp,
            min_atk=min_atk,
            max_atk=max_atk,
            gold=gold,
            xp=xp,
            defence=defence
        )

        self.essence = essence
        self.ap = ap
        self.special_move = special_move

         # REQUIRED for Green Slime turn 1 special
        self.rounds_in_combat = 0
        self.level = level
        self.variant_title = variant_title

    @property
    def display_name(self):
        title = getattr(self, "variant_title", "")
        if title:
            return f"{title} {self.name}"
        return self.name

    def attack(self, target):
        """Normal monster attack.
    Special moves are handled in enemy_attack().
    """
        damage = random.randint(self.min_atk, self.max_atk)
        actual = target.apply_defence(damage, attacker=self)
        target.hp = max(0, target.hp - actual)
        return actual
    

                    
                                
        
class Hero(Creator):
    """
    Base class for all playable characters (Warrior, Mage, Thief, etc.).
    Contains only attributes that EVERY hero class shares.
    Class-specific systems (berserk, spells, stealth) live in their subclass.
    """
    def __init__(self, name, hp, min_atk, max_atk,
                 gold=0, xp=0, defence=0, potions=None):
        super().__init__(name, hp, min_atk, max_atk, gold, xp, defence)

        # ------------------------------------------------------------------
        # CORE COMBAT RESOURCES
        # ------------------------------------------------------------------
        self.ap = 3
        self.max_ap = 3
        self.max_overheal = int(self.max_hp * 1.10)  # 10% overheal cap

        # Universal damage bonus hook — each subclass drives this differently:
        #   Warrior  -> adrenaline system
        #   Mage     -> spell power (future)
        #   Thief    -> crit/combo system (future)
        self.current_bonus_damage = 0

        # ------------------------------------------------------------------
        # INVENTORY & EQUIPMENT
        # ------------------------------------------------------------------
        self.inventory = []
        self.equipment = {
            "weapon":    None,
            "armor":     None,
            "accessory": None
        }
        self.equipment_bonus_damage = 0

        # ------------------------------------------------------------------
        # POTIONS
        # ------------------------------------------------------------------
        if potions is None:
            self.potions = {
                "heal": 0,
                "super_potion": 0,
                "mega_potion": 0,
                "full_potion": 0,
                "ap": 0,
                "super_ap": 0,
                "mega_ap": 0,
                "full_ap": 0,
                "mana": 0,
                "greater_mana": 0,
                "antidote": 0,
                "burn_cream": 0
            }
        else:
            self.potions = potions

        # ------------------------------------------------------------------
        # PROGRESSION
        # ------------------------------------------------------------------
        self.level = 1
        self.xp_to_lvl = 10
        self.level_cap = None
        self._level_cap_notified = False
        self.stat_points = 0
        self.skill_points = 0
        self.spent_stats_this_level  = {"hp": 0, "atk": 0, "def": 0, "ap": 0}
        self.spent_skills_this_level = {}

        # ------------------------------------------------------------------
        # SKILLS
        # ------------------------------------------------------------------
        self.skills = set()
        self.skill_ranks = {
            "heal":         0,
            "power_strike": 0,
            "war_cry":      0,
        }
        self.skill_progress = {}

        # ------------------------------------------------------------------
        # TRACKING & STORY
        # ------------------------------------------------------------------
        self.titles          = set()
        self.achievements    = set()
        self.bestiary        = set()
        self.endings         = set()
        self.monster_essence = []
        self.story_flags     = set()
        self.trainer_seen    = set()
        self.death_reason    = None

        # ------------------------------------------------------------------
        # STATUS EFFECTS  (universal — any class can be hit by these)
        # ------------------------------------------------------------------

        # Poison
        self.poison_active          = False
        self.poison_amount          = 0
        self.poison_turns           = 0
        self.poison_skip_first_tick = False

        # Blindness
        self.is_blinded  = False
        self.blind_type  = ""
        self.blind_turns = 0
        self.blind_long  = False

        # Fire (per-stack tracking)
        self.burns       = []
        self.fire_stacks = 0

        # Acid
        self.acid_stacks       = []
        self.acid_defence_loss = 0

        # Paralyze
        self.paralyzed           = False
        self.paralyze_turns      = 0
        self.paralyze_vulnerable = False
        self.post_paralyze_guard = False

        # Turn stop (stun / freeze / misc lockout)
        self.turn_stop             = 0
        self.turn_stop_reason      = ""
        self.turn_stop_chain_guard = False

        # Bleed — reserved for Thief enemies / future content
        self.bleed_turns = 0

        # Skip turns — used by paralyze application on any target
        self.skip_turns = 0

        # ------------------------------------------------------------------
        # FUTURE CLASS PLACEHOLDERS
        # ------------------------------------------------------------------

        # Mage — spell resource (Mage subclass will set real values)
        self.mana     = 0
        self.max_mana = 0

        # Thief — placeholder section reserved here

    # ---------- Display ----------
    def show_game_stats(self, enemy=None):
        """Two-column HUD: left = name/HP, right = AP/bonuses/berserk/gear.
        Combat log (damage lines) prints below the divider naturally."""

        hero_bar = hp_bar(
            self.hp,
            self.max_hp,
            size=10,
            max_overheal=getattr(self, "max_overheal", self.max_hp)
        )

        # --- Build right-column content ---
        adr         = getattr(self, "current_bonus_damage", 0)
        wc          = getattr(self, "war_cry_bonus", 0)
        bers        = getattr(self, "berserk_bonus", 0) if getattr(self, "berserk_active", False) else 0
        equip_bonus = getattr(self, "equipment_bonus_damage", 0)
        total       = adr + wc + bers + equip_bonus

        bonus_parts = []
        if adr:         bonus_parts.append(f"Adrenaline {adr}")
        if wc:          bonus_parts.append(f"War Cry {wc}")
        if bers:        bonus_parts.append(f"Berserk {bers}")
        if equip_bonus: bonus_parts.append(f"Equip +{equip_bonus}")
        bonus_str = f"💥 Bonus: {total}" + (f" ({' | '.join(bonus_parts)})" if bonus_parts else "")

        right_lines = [
            f"🔵 AP: {self.ap}/{self.max_ap}   {bonus_str}",
            berserk_meter(self),
        ]

        # Death Defier — always show when active, not buried inside bonus check
        if getattr(self, "death_defier", False):
            if getattr(self, "death_defier_used", False):
                right_lines.append("💀 Death Defier: USED")
            elif getattr(self, "death_defier_active", False):
                right_lines.append("💀 Death Defier: READY")
            else:
                right_lines.append("💀 Death Defier: available")

        # Gear — short names on one line separated by pipes
        equipped = getattr(self, "equipment", {})
        gear_names = []
        for slot in ("weapon", "armor", "accessory"):
            item = equipped.get(slot)
            if item:
                gear_names.append(f"{item.rarity.title()} {item.name}")
        if gear_names:
            right_lines.append("🎒 " + "  |  ".join(gear_names))

        # --- Left column strings ---
        left_name = f"🧝 {self.name.title()}"
        left_hp   = f"   ❤️  [{hero_bar}] {self.hp}/{self.max_hp}"

        print("\n" + "─" * 55)

        # Row 1: name (left) | AP + bonus (right)
        print(f"{left_name:<22}{right_lines[0]}")
        # Row 2: HP bar (left) | berserk meter (right)
        print(f"{left_hp:<22}  {right_lines[1]}")
        # Extra right lines (death defier, gear) aligned to right column
        for extra in right_lines[2:]:
            print(f"{'': <22}{extra}")

        # --- ENEMY ROW ---
        if enemy is not None:
            ebar = hp_bar(
                enemy.hp,
                enemy.max_hp,
                size=10,
                max_overheal=getattr(enemy, "max_overheal", enemy.max_hp)
            )
            print(f"\n💚 {enemy.display_name}")
            print(f"   ❤️  [{ebar}] {enemy.hp}/{enemy.max_hp}")

        print("─" * 55)
        print()


    def show_combat_stats(self, enemy=None):
        """In-run stats: clean + tactical (no essences, no long history)."""
        print("\n" + "=" * 40)

        # Title only if they have one
        titles = getattr(self, "titles", None)

        # Normalize titles to a list of strings
        if titles is None:
            titles_list = []
        elif isinstance(titles, (list, tuple)):
            titles_list = list(titles)
        else:
            # if a single string/title slipped in
            titles_list = [str(titles)]

        title_line = f" - {titles_list[-1]}" if titles_list else ""
        print(f"🧝 {self.name}{title_line}  |  Lv {self.level}")


        print(f"❤️ HP: {self.hp}/{self.max_hp}   🔵 AP: {self.ap}/{self.max_ap}")
        print(f"⚔️ ATK: {self.min_atk}-{self.max_atk}   🛡️ DEF: {self.defence}")

        # Bonus sources (the stuff you care about mid-fight)
        adr = getattr(self, "current_bonus_damage", 0)
        wc_bonus = getattr(self, "war_cry_bonus", 0)
        wc_turns = getattr(self, "war_cry_turns", 0)
        bers_active = getattr(self, "berserk_active", False)
        bers_bonus = getattr(self, "berserk_bonus", 0) if bers_active else 0

        parts = []
        if adr:
            parts.append(f"Adrenaline {adr}")
        if wc_turns > 0 and wc_bonus > 0:
            parts.append(f"War Cry {wc_bonus} ({wc_turns}T)")
        if bers_active:
            parts.append(f"Berserk {bers_bonus}")
        equip_bonus = getattr(self, "equipment_bonus_damage", 0)
        if equip_bonus:
            parts.append(f"Equip +{equip_bonus}")

        print("💥 Bonus: " + (" | ".join(parts) if parts else "0"))

        # --- Equipped gear (Step 4: show in detailed stats) ---
        equipped = getattr(self, "equipment", {})
        print("\n🎒 Equipment:")
        any_gear = False
        for slot in ("weapon", "armor", "accessory"):
            item = equipped.get(slot)
            if item:
                print(f"   {slot.title():<12} {item.short_label()}")
                any_gear = True
        if not any_gear:
            print("   (nothing equipped)")

        # Death Defier status
        if getattr(self, "death_defier", False):
            if getattr(self, "death_defier_used", False):
                dd = "USED"
            elif getattr(self, "death_defier_active", False):
                dd = "READY"
            else:
                cost = 0 if getattr(self, "death_defier_river", False) else 1
                dd = f"Available (activate {cost} AP)"
            print(f"💀 Death Defier: {dd}")

        # Key debuffs only if active
        if getattr(self, "blind_turns", 0) > 0:
            print(f"👁️ Blind: {self.blind_turns}T")
        if getattr(self, "poison_active", False) and getattr(self, "poison_turns", 0) > 0:
            print(f"☠️ Poison: {self.poison_amount}/tick ({self.poison_turns}T)")
        if getattr(self, "fire_stacks", 0) > 0:
            print(f"🔥 Burn: {self.fire_stacks} stack(s)")
        if getattr(self, "defence_broken", False) and getattr(self, "defence_break_turns", 0) > 0:
            print(f"🛡️ Defence Break: {self.defence_break_turns}T")
        if hasattr(self, "defence_warp_phase"):
            print("🌀 Defence Warp: ACTIVE")

        # Optional: show enemy quick line if provided
        if enemy is not None:
            try:
                print("-" * 40)
                print(f"💚 {enemy.display_name}: {enemy.hp}/{enemy.max_hp} HP  |  AP {enemy.ap}/{enemy.max_ap}")
            except Exception:
                pass

        print("=" * 40 + "\n")


        
    def show_all_game_stats(self):
        print("\n" + "=" * 40)
        print(f"Hero: {self.name}   |   Level: {self.level}")
        print(f"HP: {self.hp}/{self.max_hp}  |  ATK: {self.min_atk}-{self.max_atk}")
        print(f"AP: {self.ap}/{self.max_ap}  |  DEF: {self.defence}")
        print(f"XP: {self.xp}/{self.xp_to_lvl}")
        print(f"Gold: {self.gold}")
        wc_bonus = getattr(self, "war_cry_bonus", 0)
        wc_turns = getattr(self, "war_cry_turns", 0)

        print("\n🗣️ War Cry:")
        if wc_turns > 0 and wc_bonus > 0:
            print("   Status: ACTIVE")
            print(f"   Bonus Damage: +{wc_bonus}")
            print(f"   Turns Remaining: {wc_turns}")
        else:
            print("   Status: Inactive")

        print("=" * 40)

        if self.titles:
            print("🎖️  Titles:")
            for title in self.titles:
                print(f"   • {title}")
        else:
            print("🎖️  Titles: None earned yet")

    # Achievements
        if self.achievements:
            print("\n🏅 Achievements:")
            for achieve in self.achievements:
                print(f"   • {achieve}")
        else:
            print("\n🏅 Achievements: None yet")

    # Monster Essences
        if self.monster_essence:
            print("\n💀 Monster Essences:")
            for essence in self.monster_essence:
                print(f"   • {essence}")
        else:
            print("\n💀 Monster Essences: None collected")

        # Endings
        if hasattr(self, "endings"):
            if self.endings:
                print("\n📜 Endings Unlocked:")
                for ending in self.endings:
                    print(f"   • {ending}")
            else:
                print("\n📜 Endings Unlocked: None yet")
        else:
            print("\n📜 Endings Unlocked: None yet")


        print("=" * 40 + "\n")
    # ---------- Leveling ----------
        
    def level_up(self):
        # 1. Hard level cap check (Demo Cap = 5)
        if self.level >= 5:
            if not getattr(self, "_level_cap_notified", False):
                print(f"\n*** LEVEL CAP REACHED (Level 5) ***")
                self._level_cap_notified = True
            return False

        # 2. Increment Level and scaling
        self.level += 1
        self.xp_to_lvl = int(self.xp_to_lvl * 1.75)
        
        # Reset per-level investment trackers for the new level
        self.spent_stats_this_level = {"hp": 0, "atk": 0, "def": 0, "ap": 0}
        self.spent_skills_this_level = {}

        print(f"\n✨ LEVEL UP! You are now Level {self.level} ✨")

        # 3. PART 1: Random Weighted Buffs (Get 2)
        # Weights: HP (60%), Atk (20%), Def (20%)
        p1_options = ["hp", "atk", "def", "adr"]
        p1_weights = [50, 30, 30, 20]

        # 20% chance for a 3rd p1 option (Jackpot)
        num_p1_rolls = 3 if random.random() < 0.20 else 2
        if num_p1_rolls == 3:
            print("🌟 Bonus! You earned an extra Random Buff!")
        
        for _ in range(num_p1_rolls):
            buff = random.choices(p1_options, weights=p1_weights)[0]
            if buff == "hp":
                self.max_hp += 5
                self.hp += 5
                print("💖 Random Buff: +5 Max HP")
            elif buff == "atk":
                self.min_atk += 1
                self.max_atk += 1
                print("⚔️ Random Buff: +1 Attack")
            elif buff == "def":
                self.defence += 1
                print("🛡️ Random Buff: +1 Defense")

            elif buff == "adr":
                # This increases the PERMANENT Adrenaline bonus
                self.perm_special += 1 
                print(f"\n{YELLOW}✨ You feel a surge of primal power!{RESET}")
                print("🔥 Random Buff: Adrenaline +1 (Permanent Damage)")
        # --- PART 2: Specialization (Weighted) ---
        # 30% Skill Point, 30% Stat Point, 20% Max AP, 20% Berserk
        p2_options = ["skill", "stat", "ap", "berserk"]
        p2_weights = [30, 30, 20, 20]
        
        # 10% chance to roll twice (Jackpot)
        num_rolls = 2 if random.random() < 0.10 else 1
        if num_rolls == 2:
            print("🌟 JACKPOT! You earned a Double Specialization Reward!")

        for _ in range(num_rolls):
            spec = random.choices(p2_options, weights=p2_weights)[0]
            if spec == "skill":
                self.skill_points += 1
                print("📜 Spec: +1 Bonus Skill Point")
            elif spec == "stat":
                self.stat_points += 1
                print("📈 Spec: +1 Bonus Stat Point")
            elif spec == "ap":
                self.max_ap += 1
                print("⚡ Spec: +1 Max AP")
            elif spec == "berserk": 
                # Directly increase the bonus damage from 6 -> 7 -> 8 etc.
                self.berserk_bonus += 1
                print(f"🩸 Spec: +1 Berserk Power (Now +{self.berserk_bonus} dmg)")

        # 4. BASE POINT REWARDS
        # At level 5, player gets 5 points each. Otherwise, 2 points each.
        if self.level == 5:
            self.stat_points += 5
            self.skill_points += 5
            print("🏆 LEVEL 5 REACHED! +5 Stat Points and +5 Skill Points granted!")
        else:
            self.stat_points += 1
            self.skill_points += 2
            print("📝 Base Rewards +1 Stat Points and +2 Skill Points granted.")

        # Rejuvenate logic (Heal to full)
        self.hp = self.max_hp
        self.max_overheal = int(self.max_hp * 1.10)
        
        get_damage_bonuses(self, "level_up")  # Recalculate bonuses in case of level-based ones
        return True

SKILL_DEFS = {
    "power_strike": {
        "name": "Power Strike",
        "min_level": 1,
        "max_rank": 10,
        # cost to go from rank N -> N+1 (rank 0->1 uses index 0)
        "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
        "desc": "A powerful single attack that converts AP into impact damage."

    },
    "heal": {
        "name": "First Aid",
        "min_level": 1,
        "max_rank": 5,
        "upgrade_costs": [1, 1, 2, 3, 4],
        "desc": (
            "R1: Heal 10% HP. "
            "R2: +15%, cures Blind/Poison. "
            "R3: +20%, cures Blind/Poison. "
            "R4: +25%, cures Blind/Poison/Paralyze/Burn. "
            "R5: +30%, cures all status."
        ),
    },
    "war_cry": {
        "name": "War CRY",
        "min_level": 1,
        "max_rank": 10,
        "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
        "desc": "Battle cry that buffs/debuffs (later).",
    },
}

def skill_visible(hero, key):
    """Hide skills until min_level, unless already unlocked."""
    rank = hero.skill_ranks.get(key, 0)
    req = SKILL_DEFS[key]["min_level"]
    return hero.level >= req or rank > 0

def next_skill_cost(hero, key):
    """Cost to go from current rank -> next rank."""
    rank = hero.skill_ranks.get(key, 0)
    costs = SKILL_DEFS[key]["upgrade_costs"]
    max_rank = SKILL_DEFS[key]["max_rank"]

    if rank >= max_rank:
        return None  # already maxed
    # rank 0->1 uses costs[0], rank 1->2 uses costs[1], etc.
    return costs[rank]

def show_skill_tree(hero):
    while True:
        clear_screen()
        print("🌳 Skill Tree\n")
        print(f"📘 Skill Points: {hero.skill_points}\n")

        visible = []
        for key, data in SKILL_DEFS.items():
            if skill_visible(hero, key):
                visible.append(key)

        if not visible:
            print("No skills available yet.")
            input("\nPress Enter to return.")
            return

        for i, key in enumerate(visible, start=1):
            data = SKILL_DEFS[key]
            name = data["name"]
            rank = hero.skill_ranks.get(key, 0)
            max_rank = data["max_rank"]

            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)

            if cost is None:
                cost_text = "MAX"
                prog_text = ""
            else:
                cost_text = f"{cost} SP"
                # show progress only if not maxed
                prog_text = f" | Progress: {bank}/{cost}" if (bank > 0 or cost > 1) else ""

            status = "Unlocked" if rank > 0 else "Locked"
            req = data["min_level"]
            if rank == 0 and hero.level < req:
                status = f"Locked (Requires Lv {req})"

            print(f"{i}) {name:<12}  Rank {rank}/{max_rank}  |  Next: {cost_text}{prog_text}  |  {status}")
            print(f"   {data['desc']}")

        print("\nChoose a skill number to invest / upgrade.")
        print("0) Back")

        choice = input("> ").strip()
        if choice == "0":
            return
        if not choice.isdigit():
            continue

        idx = int(choice)
        if idx < 1 or idx > len(visible):
            continue

        key = visible[idx - 1]
        rank = hero.skill_ranks.get(key, 0)
        max_rank = SKILL_DEFS[key]["max_rank"]

        if rank == 0 and hero.level < SKILL_DEFS[key]["min_level"]:
            print(f"\nYou must be at least level {SKILL_DEFS[key]['min_level']} to learn this skill.")
            input("\nPress Enter...")
            continue

        if rank >= max_rank:
            print("\nThat skill is already max rank.")
            input("\nPress Enter...")
            continue

        cost = next_skill_cost(hero, key)
        bank = hero.skill_progress.get(key, 0)

        if cost is None:
            input("\nPress Enter...")
            continue

        

        
# --- allow partial investment ---
        if hero.skill_points <= 0:
            print("\nYou have no skill points to invest.")
            input("\nPress Enter...")
            continue

        # invest as much as possible into this skill (up to completing the next cost)
        bank = hero.skill_progress.get(key, 0)
        cost = next_skill_cost(hero, key)

        to_invest = min(hero.skill_points, max(0, cost - bank))
        hero.skill_points -= to_invest
        hero.skill_progress[key] = bank + to_invest
        hero.spent_skills_this_level[key] = hero.spent_skills_this_level.get(key, 0) + to_invest

        # resolve upgrades (handles overflow / multi-rank if you ever allow it)
        upgraded = False
        while True:
            cost = next_skill_cost(hero, key)
            if cost is None:
                break

            bank = hero.skill_progress.get(key, 0)
            if bank < cost:
                break

            hero.skill_progress[key] -= cost
            hero.skill_ranks[key] = hero.skill_ranks.get(key, 0) + 1
            hero.skills.add(key)
            upgraded = True

        if upgraded:
            print(f"\n✅ {SKILL_DEFS[key]['name']} upgraded to Rank {hero.skill_ranks[key]}!")
        elif to_invest > 0:
            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)
            print(f"\n📘 Invested {to_invest} SP into {SKILL_DEFS[key]['name']} ({bank}/{cost}).")
        else:
            print("\n📘 No additional points needed for this skill right now.")

        input("\nPress Enter...")



def skill_menu(hero, enemy):
    while True:
        clear_screen()
        hero.show_game_stats(enemy)

        options = []  # (key, label, callable)

        # -------------------------
        # DEATH DEFIER
        # -------------------------
        if hero.death_defier and not hero.death_defier_active and not hero.death_defier_used:
            cost = 0 if hero.death_defier_river else 1

            if hero.ap < cost:
                label = f"Death Defier (Cost {cost} AP) [Not enough AP]"
                fn = None
            else:
                label = f"Death Defier (Cost {cost} AP)"
                fn = lambda: activate_death_defier(hero)

            options.append(("death_defier", label, fn))

        # -------------------------
        # POWER STRIKE (downcast-aware)
        # -------------------------
        ps_rank = hero.skill_ranks.get("power_strike", 0)
        if ps_rank > 0:
            max_rank = min(ps_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= power_strike_ap_cost(r)]

            if not affordable:
                label = f"Power Strike (Rank {ps_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = power_strike_ap_cost(default_rank)
                label = f"Power Strike (Rank {ps_rank} → {default_rank}, Cost {default_cost} AP)"
                fn = lambda h=hero, e=enemy, r=default_rank: power_strike(h, e, r)

            options.append(("power_strike", label, fn))

        # -------------------------
        # HEAL (combat: auto highest rank, confirm only if 3 AP)
        # -------------------------
        heal_rank = hero.skill_ranks.get("heal", 1)
        if heal_rank > 0:
            max_rank = min(heal_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= heal_ap_cost(r)]

            if not affordable:
                label = f"First Aid (Rank {heal_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = heal_ap_cost(default_rank)
                label = f"First Aid (Rank {heal_rank} → {default_rank}, Cost {default_cost} AP)"
                fn = lambda h=hero: heal(h, mode="combat")


            options.append(("heal", label, fn))

        # -------------------------
        # WAR CRY
        # -------------------------
        wc_rank = hero.skill_ranks.get("war_cry", 0)
        if wc_rank > 0:
            max_rank = min(wc_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= war_cry_ap_cost(r)]

            if not affordable:
                label = f"War Cry (Rank {wc_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = war_cry_ap_cost(default_rank)
                bonus, turns = WAR_CRY_EFFECTS[default_rank]
                label = (f"War Cry (Rank {wc_rank} → {default_rank}, "
                         f"Cost {default_cost} AP, +{bonus} for {turns} turns)")
                fn = lambda h=hero, r=default_rank: war_cry(h, r)

            options.append(("war_cry", label, fn))

        # -------------------------
        # DISPLAY MENU
        # -------------------------
        print("=== SKILLS ===")
        if not options:
            print("No skills learned yet.")
            input("\nPress Enter...")
            return False

        selectable = []
        menu_i = 1
        for key, label, fn in options:
            if fn is None:
                print(f"- {label}")
            else:
                print(f"{menu_i}) {label}")
                selectable.append((key, label, fn))
                menu_i += 1

        print("0) Back")

        choice = input("\nChoose: ").strip()
        if choice == "0":
            return False
        if not choice.isdigit():
            continue

        idx = int(choice) - 1
        if idx < 0 or idx >= len(selectable):
            continue

        key, label, fn = selectable[idx]

        used = fn()
        if used:
            return True
        
        


        
        


def compute_adrenaline_bonus(warrior):
    """
    Returns bonus damage from adrenaline tiers + rage stat.
    Berserk is triggered separately based on HP.
    """
    hp_percent = warrior.hp / warrior.max_hp

    # Finalized tiers: max +3 bonus
    if hp_percent <= 0.25:
        tier = 3
    elif hp_percent <= 0.50:
        tier = 2
    elif hp_percent <= 0.75:
        tier = 1
    else:
        tier = 0

    # ---- PATCH: Mute adrenaline messages during Berserk ----
    berserk_block_messages = (
        getattr(warrior, "berserk_active", False) or
        getattr(warrior, "berserk_pending", False)
    )

    # Adrenaline tier messages
    if tier != warrior.rage_state:
        warrior.rage_state = tier

       
        if not berserk_block_messages:
            # Calculate the actual damage bonus including the perm_special multiplier
            perm = max(1, getattr(warrior, "perm_special", 0) or 1)
            current_boost = tier * perm

            if tier == 1:
                print(f"🔥 Your adrenaline spikes (+{current_boost} damage).")
            elif tier == 2:
                print(f"🔥🔥 Pain sharpens your focus (+{current_boost} damage).")
            elif tier == 3:
                print(f"🔥🔥🔥 You push past the pain (+{current_boost} damage).")
            elif tier == 0:
                print("You steady your breathing.")

    # perm_special is the Adrenaline upgrade from level-up buffs.
    # tier 1 normally = +1, but with perm_special=1 it becomes +2, etc.
    # Base is (tier * max(1, perm_special)) so un-upgraded stays identical.
    adr_base = tier + getattr(warrior, "perm_special", 0) if tier > 0 else 0
    return adr_base + warrior.max_rage



def check_berserk_trigger(warrior):
    """
    Triggers Berserk at <=10% HP.
    Berserk lasts exactly 2 turn ticks:
        - One player turn
        - One enemy turn
    Damage taken is halved during this entire period.
    Berserk bonus is applied to ONE player attack.
    """

    # Reset berserk_used if HP rises above 20%
    if warrior.hp / warrior.max_hp > 0.20:
        warrior.berserk_used = False

    # Already active or already used for this low-HP cycle
    if warrior.berserk_active or warrior.berserk_used:
        return

    hp_percent = warrior.hp / warrior.max_hp

    # Trigger threshold: 10% HP
    if hp_percent <= 0.10:
        # No more blindness gating – rage is animalistic
        print("🩸🔥 BERSERK MODE ACTIVATED!")
        warrior.berserk_active = True
        warrior.berserk_bonus = 6 + warrior.max_rage
        warrior.berserk_turns = 2      # lasts a FULL ROUND
        warrior.berserk_used = True
        # Optionally clear any 'berserk_pending' flag if it still exists
        warrior.berserk_pending = False


# ===============================
# Monsters
# ===============================
# Ap currrntly goes up based on hp 13 hp = 2ap, 27 hp = 3 ap, 42 hp = 4ap for now
class Green_Slime(Monster):
    def __init__(self):
        super().__init__(
            name="Green Slime",
            hp=10,
            min_atk=1,
            max_atk=2,
            gold=0,
            xp=5,
            essence=["green slime essence"],
            defence=0,
            ap=1
        )
        self.special_move = slime_poison_spit


class Young_Goblin(Monster):
    def __init__(self):
        super().__init__(
            name="Young Goblin",
            hp=8,
            min_atk=1,
            max_atk=3,
            gold=0,
            xp=7,
            essence=["young goblin essence"],
            defence=1,
            ap=1    
        )

        self.special_move = goblin_cheap_shot
        self.used_cheap_shot = False

class Goblin_Archer(Monster):
    def __init__(self):
        super().__init__(
            name="Goblin Archer",
            hp=15,
            min_atk=3,
            max_atk=5,
            gold=0,
            xp=17,
            essence=["goblin archer essence"],
            defence=1,
            ap=2
        )
        self.special_move = paralyzing_shot


class Brittle_Skeleton(Monster):
    def __init__(self):
        super().__init__(
            name="Brittle Skeleton",
            hp=12,
            min_atk=2,
            max_atk=5,
            gold=0,
            xp=9,
            essence=["skeleton essence"],
            defence=1,
            ap=1)

        self.special_move= brittle_skeleton_thrust
        
class Imp(Monster):
    def __init__(self):
        super().__init__(
        name = "Imp",
        hp=9,
        min_atk= 2,
        max_atk=4,
        gold = 0,
        xp = 7,
        essence=["imp essence"],
        defence=0,
        ap=1)

        self.special_move = imp_sneak_attack

class Wolf_Pup(Monster):
    def __init__(self):
        super().__init__(
            name="Wolf Pup",
            hp=13,
            min_atk=3,
            max_atk=5,
            gold=0,
            xp=13,
            essence=["wolf essence"],
            defence=2,
            ap=2)
        
        self.special_move = wolf_pup_bite

class Dire_Wolf_Pup(Monster):
    def __init__(self):
        super().__init__(
            name="Dire Wolf Pup",
            hp=16,                       # lowered because DEF is 3 and it can heal
            min_atk=4,                   # 4–6 is chunky but fair
            max_atk=6,
            gold=0,
            xp=19,
            essence=["dire wolf pup essence"],
            defence=3,
            ap=2,
        )
        self.loot_drop = "dire_wolf_pelt"
        self.special_move = devouring_bite
        

            
class Red_Slime(Monster):
    def __init__(self):
        super().__init__(
            name = "red slime",
            hp=16,
            min_atk=2,
            max_atk=4,
            gold=0,
            xp=16,
            essence=["red slime essence"],
            defence=1,
            ap=2
        )
        self.special_move = red_slime_fire_spit         
          
class Fallen_Warrior(Monster):
    def __init__(self):
        super().__init__(
            name="Fallen Warrior",
            hp=60,
            min_atk=6,
            max_atk=10,
            gold=0,
            xp=50,
            essence=["fallen warrior essence"],
            defence=5,
            ap=5
        )
        self.special_move = fallen_defence_warp
        


   

            
        

class Noob_Ghost(Monster):
    def __init__(self):
        super().__init__(
            name="Noob Ghost",
            hp=16,
            min_atk=3,
            max_atk=6,
            gold=0,
            xp=13,
            essence=["ghost essence"],
            defence=0,
            ap=2
        )

        # 👻 Overheal pool so life drain is never "wasted"
        self.max_overheal = int(self.max_hp * 1.5)

        # Hook up the life leech special
        self.special_move = ghost_life_leech

        

class Wolf_Pup_Rider(Monster):
    def __init__(self):
        super().__init__(name= "Wolf Pup Rider",
                         hp=21,
                         min_atk=3,
                         max_atk=7,
                         gold=0,
                         xp=23,
                         essence=["wolf pup rider essence"],
                         defence=3,
                         ap = 2
                         )
        self.loot_drop = "wolf_pup_pelt"
        self.special_move = blinding_charge
        
    
    def drop_loot(self):
        print(f"\n🎁 Loot dropped: {self.loot_drop}!")
        
        return self.loot_drop
    
class Javelina(Monster):
    def __init__(self):
        super().__init__(
            name="Javelina",
            hp=18,
            min_atk=3,
            max_atk=6,
            gold= 0,
            xp=18,
            essence=["javelina essence"],
            defence=2,
            ap=2,
            
            
        )
        self.special_move = impact_bite

    
class Hydra_Hatchling(Monster):
    def __init__(self):
        super().__init__(
            name="Hydra Hatchling",
            hp=25,
            min_atk=3,
            max_atk=6,
            gold=0,
            xp=27,
            essence=["hydra hatchling essence"],
            defence=3,
            ap=2
        )
        self.loot_drop = "acid sack"
        self.special_move = hydra_hatchling_acid_spit


# ===============================
# Hidden Boss — Young Chimera
# ===============================

# Move pools the chimera draws from on spawn
CHIMERA_TIER1_POOL = [
    slime_poison_spit,
    goblin_cheap_shot,
    imp_sneak_attack,
    brittle_skeleton_thrust,
    wolf_pup_bite,
]

CHIMERA_TIER2_POOL = [
    red_slime_fire_spit,
    ghost_life_leech,
    impact_bite,
    devouring_bite,
    paralyzing_shot,   # called with paralyze_turns=2 via dispatcher
]

CHIMERA_TIER3_POOL = [
    blinding_charge,
    hydra_hatchling_acid_spit,
]

CHIMERA_ELEMENTS = ["fire", "poison", "acid", "paralyze"]


def chimera_special_dispatcher(enemy, warrior):
    """
    Each turn the chimera randomly picks one of its four move slots.
    Borrowed moves run exactly as they would on their original monster.
    paralyzing_shot is called with paralyze_turns=2 (chimera tier).
    """
    moves = [
        enemy.chimera_tier1,
        enemy.chimera_tier2,
        enemy.chimera_tier3,
        chimera_elemental_strike,
    ]
    chosen = random.choice(moves)

    # paralyzing_shot needs the extra kwarg when borrowed by chimera
    if chosen is paralyzing_shot:
        return paralyzing_shot(enemy, warrior, paralyze_turns=2)
    return chosen(enemy, warrior)


class Young_Chimera(Monster):
    def __init__(self):
        super().__init__(
            name="Young Chimera",
            hp=60,
            min_atk=5,
            max_atk=9,
            gold=0,
            xp=0,            # no XP — this is a hidden story fight
            essence=[],
            defence=4,
            ap=3,
        )
        self.tier = 5        # above tier 4 boss — own AI tier

        # Roll borrowed moves fresh on spawn — different every fight
        self.chimera_tier1 = random.choice(CHIMERA_TIER1_POOL)
        self.chimera_tier2 = random.choice(CHIMERA_TIER2_POOL)
        self.chimera_tier3 = random.choice(CHIMERA_TIER3_POOL)

        # Roll elemental identity for this fight
        self.strike_element = random.choice(CHIMERA_ELEMENTS)

        # Dispatcher handles all four move slots
        self.special_move = chimera_special_dispatcher

        # Announce loadout on spawn so player gets a hint
        ELEMENT_ICONS = {
            "fire": "🔥", "poison": "🟢",
            "acid": "🧪", "paralyze": "⚡"
        }
        icon = ELEMENT_ICONS.get(self.strike_element, "💥")
        t1 = self.chimera_tier1.__name__.replace("_", " ")
        t2 = self.chimera_tier2.__name__.replace("_", " ")
        t3 = self.chimera_tier3.__name__.replace("_", " ")
        self.spawn_flavour = (
            f"The Young Chimera shifts, revealing its nature...\n"
            f"  🐾 It moves like something from the lower dens...\n"
            f"  🌀 Its body pulses with a darker energy...\n"
            f"  🏔️ A shadow of the deep wilds clings to it...\n"
            f"  {icon} Its eyes burn with {self.strike_element} energy."
        )
# ===============================
# Hero Type
# ===============================
class Warrior(Hero):
    """
    The Warrior — first playable class.
    Inherits all universal Hero attributes and adds Warrior-specific systems:
      - Adrenaline   (damage scaling based on HP loss)
      - Rage         (visual tier system driving adrenaline)
      - Berserk      (activated ability, reduces damage taken, boosts output)
      - War Cry      (temporary damage buff skill)
      - Death Defier (one-time save passive)
    """
    def __init__(self):
        super().__init__(
            name="warrior",
            hp=30,
            min_atk=1,
            max_atk=5,
            gold=3,
            xp=0,
            defence=0,
            potions=None
        )

        # Warrior starts with 1 healing potion
        self.potions["heal"] = 1

        # ------------------------------------------------------------------
        # ADRENALINE SYSTEM
        # Damage bonus that scales with HP loss — the lower your HP the
        # harder you hit. Driven by compute_adrenaline_bonus().
        # ------------------------------------------------------------------
        self.perm_special  = 0   # permanent growth from level-up upgrades
        self.temp_special  = 0   # temporary spike from current HP tier
        self.total_special = 0   # combined value used in damage math
        self.special_name  = "Adrenaline"

        # ------------------------------------------------------------------
        # RAGE SYSTEM
        # Visual tier tracker that mirrors temp_special for the UI bar.
        # ------------------------------------------------------------------
        self.max_rage  = 0   # increases with level-up upgrades
        self.rage_state = 0  # current tier (0-3), used for UI and berserk calc

        # ------------------------------------------------------------------
        # BERSERK SYSTEM
        # Triggered at low HP — halves incoming damage and boosts output.
        # ------------------------------------------------------------------
        self.berserk_active  = False
        self.berserk_pending = False  # primed to activate next turn
        self.berserk_used    = False  # already triggered this fight
        self.berserk_turns   = 0
        self.berserk_bonus   = 0      # extra flat damage while berserk

        # ------------------------------------------------------------------
        # WAR CRY SYSTEM
        # Short-duration damage buff skill.
        # ------------------------------------------------------------------
        self.war_cry_bonus          = 0
        self.war_cry_turns          = 0
        self.war_cry_skip_first_tick = False  # prevents tick on the turn it's cast

        # ------------------------------------------------------------------
        # DEATH DEFIER
        # One-time save passive — survive a killing blow at 1 HP.
        # ------------------------------------------------------------------
        self.death_defier        = False  # whether the warrior owns this skill
        self.death_defier_river  = False  # free version (0 AP cost)
        self.death_defier_active = False  # currently primed
        self.death_defier_used   = False  # already triggered this run


# ===============================
# Encounter Helpers
# ===============================

def monster_level_for_round(tier, round_num):
    """
    Determines monster level based on tier and round.
    Keeps scaling simple and demo-safe.
    """

    # Tier 1 monsters scale each round
    if tier == 1:
        return max(1, min(3, round_num))  # cap at level 3 for safety

    # Tier 2 monsters start scaling later
    if tier == 2:
        if round_num <= 2:
            return 1
        elif round_num == 3:
            return 2
        else:
            return 3

    # Tier 3 monsters scale very slowly
    if tier == 3:
        if round_num <= 3:
            return 1
        else:
            return 2

    # Boss or fallback
    return 1

LEVEL_TITLES = {
    1: None,
    2: "Hardened",
    3: "Veteran",
    4: "Elite",
}

def title_for_level(level: int):
    return LEVEL_TITLES.get(level, "Elite")

def apply_level_scaling(monster: "Monster", tier: int):
    """
    Tier 1-2: your scaling rules
    Tier 3: no scaling (for now)
    """
    lvl = int(getattr(monster, "level", 1))
    b = max(0, lvl - 1)

    # No scaling at level 1
    if b <= 0:
        monster.max_hp = monster.hp
        monster.max_ap = monster.ap
        return monster

    # --- Tier 1-2 scaling ---
    # HP +5 per level (10 -> 15 -> 20)
    monster.hp += 5 * b
    monster.max_hp = monster.hp

    # ATK +1 per level
    monster.min_atk += b
    monster.max_atk += b

    # DEF +1 per level
    monster.defence += b

    # XP +50% per level (rounded up each step)
    monster.xp = scaled_xp_step(monster.xp, lvl)

    # AP based ONLY on new max HP thresholds (13/27/42/58...)
    monster.max_ap = ap_from_hp(monster.max_hp)
    monster.ap = monster.max_ap

    return monster

def get_tier_for_monster_class(cls) -> int:
    """Figure out tier from MONSTER_TYPES / TIER4_BOSSES (used for debug UI)."""
    for c, w in MONSTER_TYPES:
        if c is cls:
            return weight_to_tier(w)
    for c, _w in TIER4_BOSSES:
        if c is cls:
            return 4
    return 1  # fallback


def apply_level_scaling_debug_any(monster: "Monster", *, level: int):
    """
    DEBUG scaling: allow ranking ANY monster (tier 1/2/3/4) for testing.
    Uses the same 'level bonus' rules you defined for tiers 1-2.
    """
    lvl = max(1, int(level))
    monster.level = lvl
    monster.variant_title = title_for_level(lvl)

    b = max(0, lvl - 1)
    if b <= 0:
        # ensure these exist consistently
        monster.max_hp = getattr(monster, "max_hp", monster.hp)
        monster.max_ap = getattr(monster, "max_ap", monster.ap)
        monster.ap = monster.max_ap
        return monster

    # HP +5 per level
    monster.hp += 5 * b
    monster.max_hp = monster.hp

    # ATK +1 per level
    monster.min_atk += b
    monster.max_atk += b

    # DEF +1 per level
    monster.defence += b

    # XP +50% per level (rounded up each step)
    monster.xp = scaled_xp_step(monster.xp, lvl)

    # AP based ONLY on new max HP thresholds
    monster.max_ap = ap_from_hp(monster.max_hp)
    monster.ap = monster.max_ap

    return monster

def lvl_bonus(monster) -> int:
    """+1 per monster level beyond 1"""
    return max(0,int(getattr(monster, "level", 1))-1)
def ap_from_hp(max_hp: int) -> int:
    '''HP threshholds:
    13 -> 2 ap
    27 -> 3 ap
    42 -> 4 ap
    58 -> 5 ap'''
    ap =1
    threshold = 13
    step = 14
    while max_hp >= threshold:
        ap += 1
        threshold += step
        step += 1
    return ap

def scaled_xp_step(base_xp: int, level: int) -> int:
    """+50% XP per level, rounding up each step (5 -> 8 -> 12)."""
    xp = int(base_xp)
    for _ in range(max(0, level - 1)):
        xp = math.ceil(xp * 1.5)
    return int(xp)

# Main monster list used for both arena + debug
# Weight value equals tier number directly: 1=T1, 2=T2, 3=T3, 4=T4
MONSTER_TYPES = [
    (Green_Slime, 1),
    (Young_Goblin, 1),
    (Imp, 1),
    (Brittle_Skeleton, 1),
    (Wolf_Pup, 1),
    (Red_Slime, 2),
    
    (Noob_Ghost, 2),
    (Wolf_Pup_Rider, 3),
    (Javelina, 2),
    (Goblin_Archer, 2),
    (Dire_Wolf_Pup, 2),
    (Hydra_Hatchling, 3),
]


# ---------- Tier helpers ----------
def weight_to_tier(weight):
    if weight == 1:
        return 1
    elif weight == 2:
        return 2
    elif weight == 3:
        return 3
    elif weight == 4:
        return 4
    return 1  # fallback — unknown weight treated as tier 1


def get_monsters_by_tier(tier):
    return [cls for cls, weight in MONSTER_TYPES if weight_to_tier(weight) == tier]


def random_encounter_by_tier(tier, round_num):
    pool = get_monsters_by_tier(tier)
    if not pool:
        raise ValueError(f"No monsters defined for tier {tier}")

    monster = random.choice(pool)()  # create monster normally
    monster.tier = tier

    lvl = monster_level_for_round(tier, round_num)
    monster.level = lvl
    monster.variant_title = title_for_level(lvl) 

    # Optional safe scaling:
    apply_level_scaling(monster, tier)

    return monster


# ---------- Tier 4 (Fallen Boss Pool) ----------
TIER4_BOSSES = [
    (Fallen_Warrior, 4),
    # Add Fallen_Wizard, Fallen_Rogue, Fallen_Monk later
]


def random_tier4_boss():
    total = sum(w for _, w in TIER4_BOSSES)
    r = random.random() * total
    cumulative = 0.0
    for cls, w in TIER4_BOSSES:
        cumulative += w
        if r <= cumulative:
            boss = cls()
            boss.tier = 4  # ✅
            return boss
    boss = TIER4_BOSSES[-1][0]()  # fallback
    boss.tier = 4                 # ✅
    return boss
  

# ---------- Weighted tier selection ----------
def pick_tier_from_weights(weight_map):
    r = random.random()
    cumulative = 0
    for tier, chance in weight_map.items():
        cumulative += chance
        if r <= cumulative:
            return tier
    return list(weight_map.keys())[-1]


def get_round_tier(round_num):
    if round_num == 1:
        return pick_tier_from_weights({1: 0.8, 2: 0.2})
    if round_num == 2:
        return pick_tier_from_weights({1: 0.4, 2: 0.6})
    if round_num == 3:
        return pick_tier_from_weights({1: 0.1, 2: .8, 3: 0.1})
    if round_num == 4:
        return pick_tier_from_weights({2: 0.1, 3: 0.9})
    
    if round_num == 5:
        #calls random fallen
        return 4
    
    # Fallback
    return 3


def select_arena_enemy(round_num):
    tier = get_round_tier(round_num)
    if tier == 4:
        return random_tier4_boss()
    else:
        return random_encounter_by_tier(tier, round_num)


# ---------- Debug: fully random by weight ----------
def random_encounter():
    """
    Legacy debug encounter using the raw weighted list.
    Great for testing new monsters quickly.
    """
    types, weights = zip(*MONSTER_TYPES)
    chosen_cls = random.choices(types, weights=weights, k=1)[0]
    return chosen_cls()

# ===============================
# Combat System
# ===============================
def warrior_attack_roll(warrior):
    return random.randint(warrior.min_atk, warrior.max_atk)





def enemy_attack(enemy, warrior):
    """Enemy performs one action. Tries specials safely, then falls back to normal attack."""
    enemy.rounds_in_combat += 1

    # -------------------------------------------------------------
    # TIERED AI LOGIC (Consolidated Special Move Check)
    # -------------------------------------------------------------
    tier = getattr(enemy, "tier", 1)
    special = getattr(enemy, "special_move", None)
    should_special = False

    # Only even consider a special if the monster has AP and a move assigned
    if enemy.ap > 0 and callable(special):
        if tier == 1:
            # Guaranteed on Turn 1, then 50%
            if enemy.rounds_in_combat == 1:
                should_special = True
            else:
                should_special = (random.random() < 0.50)
        
        elif tier == 2:
            # Flat 50% chance every turn
            should_special = (random.random() < 0.50)
            
        elif tier == 3:
            # Flat 33% chance every turn
            should_special = (random.random() < 0.33)
            
        elif tier == 4:
            # Flat 33% chance (Bosses/Fallen Warrior)
            should_special = (random.random() < 0.33)

    # Execute Special only if the tier roll was successful
    if should_special:
        result = special(enemy, warrior)
        if result is not None:
            # Check for death after special move
            if warrior.hp <= 0:
                if not try_death_defier(warrior, f"{enemy.name} special"):
                    return result
            return result

    # -------------------------------------------------------------
    # Normal attack fallback (If no special triggered or no AP)
    # -------------------------------------------------------------
    force_max = False
    if getattr(warrior, "paralyze_vulnerable", False):
        force_max = True
        warrior.paralyze_vulnerable = False
        print("🧊⚡ You’re still stiff from paralysis — you can’t brace properly!")

    # Roll damage (Normal Attack)
    roll = enemy.max_atk if force_max else enemy.attack_roll()
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    # Visual UI breakdown
    monster_math_breakdown(enemy, warrior, roll, actual)
    show_health(warrior)

    # Check for death after normal attack
    if warrior.hp <= 0:
        if try_death_defier(warrior, f"{enemy.name} attack"):
            return 0

    return actual

def bonus_breakdown(warrior, *, include_berserk=True, adrenaline_cap=None):
    """
    Returns (total_bonus, parts_list, adr_raw)

    include_berserk: if False, Berserk bonus is not added
    adrenaline_cap: if set (int), adrenaline bonus is capped to that amount
    """
    parts = []
    total = 0

    adr = compute_adrenaline_bonus(warrior)
    adr_used = adr
    if adrenaline_cap is not None:
        adr_used = min(adr_used, int(adrenaline_cap))

    if adr_used:
        # Show cap info only when it actually capped
        if adrenaline_cap is not None and adr_used != adr:
            parts.append(f"Adrenaline {adr_used} (capped)")
        else:
            parts.append(f"Adrenaline {adr_used}")
        total += adr_used

    if include_berserk and getattr(warrior, "berserk_active", False):
        b = getattr(warrior, "berserk_bonus", 0)
        if b:
            parts.append(f"Berserk {b}")
            total += b

    if getattr(warrior, "war_cry_turns", 0) > 0:
        wc = getattr(warrior, "war_cry_bonus", 0)
        if wc:
            parts.append(f"War Cry {wc}")
            total += wc

    equip = getattr(warrior, "equipment_bonus_damage", 0)
    if equip:
        parts.append(f"Equipment {equip}")
        total += equip

    return total, parts, adr


def player_basic_attack(warrior, enemy, multiplier=1.0, use_accessory=False):
    """
    use_accessory=False → weapon attack (weapon bonus + procs, no elemental)
    use_accessory=True  → accessory attack (basic roll + elemental, no weapon bonus/procs)
    If only accessory equipped → forced True. If only weapon → forced False.
    """
    has_weapon    = warrior.equipment.get("weapon") is not None
    has_accessory = warrior.equipment.get("accessory") is not None
    if has_accessory and not has_weapon:
        use_accessory = True
    elif has_weapon and not has_accessory:
        use_accessory = False

    # 1) Roll
    roll = warrior_attack_roll(warrior)

    # 2) Bonuses — suppress weapon equipment bonus when using accessory
    if use_accessory:
        saved_equip = warrior.equipment_bonus_damage
        warrior.equipment_bonus_damage = 0
    bonus_total, parts = get_damage_bonuses(warrior, "basic attack")
    bonus_parts = bonus_parts_to_text(parts)
    if use_accessory:
        warrior.equipment_bonus_damage = saved_equip

    # If other code expects this to be a NUMBER, keep it updated correctly:
    warrior.current_bonus_damage = parts.get("adrenaline", 0)

    # 3) Total + defence
    total = roll + bonus_total
    actual = enemy.apply_defence(total, attacker=warrior)
    enemy.hp = max(0, enemy.hp - actual)

    blocked = total - actual

    # 4) Build elemental tag BEFORE printing so it lands on the same line.
    acc      = warrior.equipment.get("accessory")
    elem_tag = ""

    if use_accessory and acc and getattr(acc, "element", None) and actual > 0 and enemy.is_alive():
        elem  = acc.element
        dmg   = acc.element_damage
        turns = acc.element_turns

        max_dots = getattr(acc, "element_max_dots", 1)
        if elem == "poison":
            cur_dots = len(getattr(enemy, "poison_dots", [])) + (1 if getattr(enemy, "poison_active", False) else 0)
            if max_dots <= 1:
                label = "refreshed" if getattr(enemy, "poison_active", False) else "applied"
                elem_tag = f"  ☠️ Poison {label}! ({dmg} dmg, {turns} turns)"
            else:
                new_count = min(cur_dots + 1, max_dots)
                elem_tag = f"  ☠️ Poison stack {new_count}/{max_dots}! ({dmg} dmg, {turns} turns)"
        elif elem == "fire":
            cur_stacks = len(getattr(enemy, "burns", []))
            if max_dots <= 1:
                label = "refreshed" if cur_stacks > 0 else "applied"
                elem_tag = f"  🔥 Burn {label}! ({dmg} dmg, {turns} turns)"
            else:
                new_count = min(cur_stacks + 1, max_dots)
                elem_tag = f"  🔥 Burn stack {new_count}/{max_dots}! ({dmg} dmg, {turns} turns)"
        elif elem == "acid":
            cur_stacks = len(getattr(enemy, "acid_stacks", []))
            restore = acc.element_restore
            erosion = getattr(acc, "element_erosion", 0)
            if erosion > 0:
                restore_txt = f"{dmg} acid dmg, -{erosion} DEF"
            else:
                restore_txt = f"{dmg} acid dmg"
            if max_dots <= 1:
                label = "refreshed" if cur_stacks > 0 else "applied"
                elem_tag = f"  🧪 Acid {label}! ({restore_txt}, {turns} turns)"
            else:
                new_count = min(cur_stacks + 1, max_dots)
                elem_tag = f"  🧪 Acid stack {new_count}/{max_dots}! ({restore_txt}, {turns} turns)"

    line_parts = [f"Roll {roll}"] + bonus_parts
    line = f"You attack {enemy.display_name} for {actual} damage! (" + " + ".join(line_parts) + ")"
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))
    if elem_tag:
        print(wrap(elem_tag.strip()))
    print(f"❤️ {enemy.display_name.title()} HP: {enemy.hp}/{enemy.max_hp}")

    # 5) Apply elemental effects AFTER printing
    if use_accessory and acc and getattr(acc, "element", None) and actual > 0 and enemy.is_alive():
        max_dots = getattr(acc, "element_max_dots", 1)
        if elem == "poison":
            if max_dots <= 1:
                # Single dot — always overwrite (reset timer)
                enemy.poison_active          = True
                enemy.poison_amount          = dmg
                enemy.poison_turns           = turns
                enemy.poison_skip_first_tick = True
            else:
                # Multi-dot rare+ sac — each use adds an independent dot up to cap.
                # When at cap, reapplying resets the oldest dot's timer.
                if not hasattr(enemy, "poison_dots"):
                    enemy.poison_dots = []
                if len(enemy.poison_dots) < max_dots:
                    enemy.poison_dots.append({"turns_left": turns, "dmg": dmg, "skip": True})
                else:
                    # At cap — refresh oldest dot
                    enemy.poison_dots[0] = {"turns_left": turns, "dmg": dmg, "skip": True}

        elif elem == "fire":
            if not hasattr(enemy, "burns"):
                enemy.burns       = []
                enemy.fire_stacks = 0
            if len(enemy.burns) < max_dots:
                # Room for a new stack — add it
                enemy.burns.append({"turns_left": turns, "bonus": dmg, "skip": True, "flat": True})
            else:
                # At cap — refresh oldest stack's timer
                enemy.burns[0] = {"turns_left": turns, "bonus": dmg, "skip": True, "flat": True}
            enemy.fire_stacks = len(enemy.burns)

        elif elem == "acid":
            restore  = acc.element_restore
            erosion  = getattr(acc, "element_erosion", 0)
            if not hasattr(enemy, "acid_stacks"):
                enemy.acid_stacks       = []
                enemy.acid_defence_loss = 0
            if len(enemy.acid_stacks) < max_dots:
                # Room for a new stack — add it
                enemy.acid_stacks.append({"turns_left": turns, "skip": True,
                                          "flat": True, "bonus": dmg, "restore_in": restore})
                # Apply immediate DEF erosion if this rarity has it (normal+)
                if erosion > 0:
                    enemy.acid_defence_loss = getattr(enemy, "acid_defence_loss", 0) + erosion
                    enemy.defence           = max(0, enemy.defence - erosion)
                    print(wrap(f"🧪 The acid eats into {enemy.display_name}'s armor! (-{erosion} DEF)"))
            else:
                # At cap — reset clock on existing stack (no extra erosion)
                enemy.acid_stacks[0] = {"turns_left": turns, "skip": True,
                                        "flat": True, "bonus": dmg, "restore_in": restore}

    # 5b) Accessory proc effects — paralyze (Paralyzing Arrow)
    if use_accessory and acc and actual > 0 and enemy.is_alive():
        paralyze_chance = getattr(acc, "paralyze_chance", 0.0)
        paralyze_turns  = getattr(acc, "paralyze_turns", 0)
        if paralyze_chance > 0 and not getattr(enemy, "skip_turns", 0) > 0:
            if random.random() < paralyze_chance:
                enemy.skip_turns = paralyze_turns
                print(wrap(f"⚡ The arrow's toxin courses through {enemy.display_name} "
                           f"— they are PARALYZED for {paralyze_turns} turn{'s' if paralyze_turns != 1 else ''}!"))

    # 5c) Accessory proc effects — soul drain (Soul Pendant)
    if use_accessory and acc and actual > 0 and enemy.is_alive():
        drain_bonus    = getattr(acc, "drain_bonus", 0)
        drain_heal_min = getattr(acc, "drain_heal_min", 0)
        drain_heal_max = getattr(acc, "drain_heal_max", 0)
        if drain_bonus > 0:
            enemy.hp = max(0, enemy.hp - drain_bonus)
            heal_amount = random.randint(drain_heal_min, drain_heal_max)
            old_hp = warrior.hp
            warrior.hp = min(warrior.max_hp, warrior.hp + heal_amount)
            actual_heal = warrior.hp - old_hp
            print(wrap(f"💀 Soul Drain! +{drain_bonus} true damage to {enemy.display_name}. "
                       f"({enemy.display_name} HP: {enemy.hp}/{enemy.max_hp})"))
            if actual_heal > 0:
                print(wrap(f"💜 You absorb their life force and recover {actual_heal} HP! "
                           f"(Your HP: {warrior.hp}/{warrior.max_hp})"))
    
    # 6) Weapon proc effects — only on weapon attacks
    weapon = warrior.equipment.get("weapon")
    if not use_accessory and weapon and actual > 0 and enemy.is_alive():

        # --- Imp Trident: chance for +1 bonus true damage ---
        proc_chance = getattr(weapon, "proc_chance", 0.0)
        proc_bonus  = getattr(weapon, "proc_bonus", 0)
        if proc_chance > 0 and proc_bonus > 0 and random.random() < proc_chance:
            enemy.hp = max(0, enemy.hp - proc_bonus)
            print(wrap(f"⚡ The trident crackles! +{proc_bonus} bonus damage! "
                       f"({enemy.display_name} HP: {enemy.hp}/{enemy.max_hp})"))

        # --- Goblin Dagger: chance to blind ---
        blind_chance = getattr(weapon, "blind_chance", 0.0)
        if blind_chance > 0 and not getattr(enemy, "blind_turns", 0) > 0:
            if random.random() < blind_chance:
                enemy.blind_turns = 3
                enemy.blind_type  = "goblin_dust"
                print(wrap("👁️ The dagger's edge catches their eyes — "
                           f"{enemy.display_name} is BLINDED! "
                           "(loses next action, then reduced damage)"))

        # --- Javelina Tusk: bleed ---
        tusk_bleed = getattr(weapon, "bleed_turns", 0)
        if tusk_bleed > 0 and actual > 0 and enemy.is_alive():
            enemy.bleed_turns = tusk_bleed
            print(wrap(f"🩸 The jagged tusk opens a wound! "
                       f"{enemy.display_name} bleeds for {tusk_bleed} turn{'s' if tusk_bleed != 1 else ''}! "
                       f"(2 damage/turn, ignores defence)"))

    # 7) Berserk extension + tick (unchanged)
    if enemy.hp <= 0 and getattr(warrior, "berserk_active", False):
        warrior.berserk_turns += 1
        print("🩸 Your killing blow feeds the frenzy! Berserk is extended!")

    if getattr(warrior, "berserk_active", False):
        warrior.berserk_turns -= 1
        if warrior.berserk_turns <= 0:
            deactivate_berserk(warrior)
            print("💤 Your Berserk fury subsides...")

    return actual






def chimera_fight(warrior):
    """
    Hidden boss encounter — Young Chimera.

    Win  → player earns the first piece of the Chimera Plate (best armour in demo).
    Loss → divine intervention: player's child discovers the armour regardless.

    Divine intervention only triggers if the player dies on turn 5 or later,
    meaning they had a genuine shot at the fight. Deaths before turn 5 are
    treated as 'didn't really engage' and skip the reward scene entirely.
    """
    chimera = Young_Chimera()

    # Show spawn flavour — hints at what the chimera rolled this fight
    print("\n" + "═" * 50)
    print("   ⚠️  A HIDDEN THREAT REVEALS ITSELF")
    print("═" * 50)
    print(wrap(chimera.spawn_flavour))
    input("\nPress Enter to face the Young Chimera...")

    # Track turn count — injected via a subclassed battle run
    # We use a mutable container so the inner loop can write to it
    turn_tracker = {"count": 0}

    # Patch battle_inner's turn_count into our tracker by running a
    # thin wrapper battle that monitors the result
    result = battle(warrior, chimera)

    # Retrieve turn count from chimera's fight — chimera stores it
    turns_survived = getattr(chimera, "turns_survived", 0)

    if result:
        # -----------------------------------------------
        # VICTORY — player earns Chimera Plate piece
        # -----------------------------------------------
        print("\n" + "═" * 50)
        print("   🏆 THE CHIMERA FALLS")
        print("═" * 50)
        print(wrap(
            "The Young Chimera lets out a final, rattling cry and collapses. "
            "The arena falls silent. No one has ever done this before. "
            "Embedded in its hide you find a gleaming plate of hardened chitin — "
            "part of a legendary set few have ever seen assembled."
        ))
        print(wrap("\n✨ You received: CHIMERA PLATE CHEST (Legendary Armour — Part 1 of 4)"))
        # TODO: add to warrior inventory when equipment system supports legendary sets

        # Chimera Scale — debug placeholder drop
        scale = make_loot("Young Chimera", monster_level=3)
        if scale:
            print(wrap(
                "\nA thick iridescent scale peels free from the chimera's flank and lands at your feet. "
                "It pulses faintly with residual energy."
            ))
            print(f"\n🎁 You also found: {scale.short_label()}")
            offer = input("\nEquip the Chimera Scale? (yes/no)\n> ").strip().lower()
            if offer == "yes":
                equip_item(warrior, scale)
                print(wrap(f"You strap on the Chimera Scale. Defence +{scale.defence}!"))
            else:
                warrior.inventory.append(scale)
                print("You store the scale for later.")
        input("\nPress Enter to continue...")

    else:
        # -----------------------------------------------
        # DEFEAT — divine intervention based on turn count
        # -----------------------------------------------
        if turns_survived < 5:
            # Died too fast — the chimera barely registered them
            print("\n" + "═" * 50)
            print("   💀 OVERWHELMED")
            print("═" * 50)
            print(wrap(
                "The Young Chimera stands over you, unimpressed. "
                "You never really had a chance to show what you were made of. "
                "It disappears back into the shadows of the arena tunnels."
            ))
            input("\nPress Enter to continue...")

        else:
            # Fought hard — divine intervention fires
            print("\n" + "═" * 50)
            print("   ✨ DIVINE INTERVENTION")
            print("═" * 50)
            print(wrap(
                "You fall. The world dims at the edges. "
                "But something shifts — a warmth you recognise. "
                "Your child, who has been watching from the shadows of the tunnel entrance, "
                "rushes onto the sand. The chimera regards this small, fearless figure "
                "and — impossibly — lowers its head. "
                "Your child reaches up and pulls a gleaming plate from its hide. "
                "The chimera turns and walks back into the dark."
            ))
            print(wrap("\n✨ Your child found: CHIMERA PLATE CHEST (Legendary Armour — Part 1 of 4)"))
            # TODO: add to warrior inventory when equipment system supports legendary sets
            input("\nPress Enter to continue...")

    return result


def battle(warrior, enemy, skip_rest=False, round_num=0):
    """
    Wrapper that runs battle_inner and handles control-flow exceptions.
    Returns:
      True  -> warrior won
      False -> warrior lost
      "win" -> special tournament win condition (fallen warrior)
    """
    try:
        result = battle_inner(warrior, enemy, skip_rest=skip_rest, round_num=round_num)

        # battle_inner now always returns True, False, or "win".
        # This guard handles any unexpected None as a loss (should never fire).
        if result is None:
            print("[DEBUG] battle_inner returned None — treating as loss. Please report this!")
            return False

        return result

    except RestartException:
        # Whatever your current behavior is (back to intro / debug menu),
        # keep it here so battle_inner stays pure.
        intro_story(GAME_WARRIOR)  # or whatever you currently do
        return False

    except QuickCombatException as qc:
        # If you have a quick combat handler, keep it here
        # qc might carry a result or a monster; depends on your design.
        return False

def update_defence_warp_after_enemy_turn(warrior):
    """
    Multi-turn armour destabilisation from Defence Warp.

    Phases:
      0 -> set defence to 0, move to phase 1
      1 -> set defence to 50% of original, move to phase 2
      2 -> restore full defence and clear state
    """
    phase = getattr(warrior, "defence_warp_phase", None)
    if phase is None:
        return

    if not warrior.is_alive():
        return

    orig = getattr(warrior, "defence_warp_original_defence", warrior.defence)

    if phase == 0:
        warrior.defence = 0
        warrior.defence_warp_phase = 1
        print(wrap("🛡️ Your defences collapse under the warped curse — you lose all defence!"))

    elif phase == 1:
        if orig > 0:
            half = max(1, orig // 2)
        else:
            half = 0
        warrior.defence = half
        warrior.defence_warp_phase = 2
        print(wrap("🛡️ Your defences begin to stabilise, partially restoring your defence."))

    elif phase == 2:
        warrior.defence = orig
        print(wrap("🛡️ Your defences fully stabilise — your defence returns to normal."))
        del warrior.defence_warp_phase
        if hasattr(warrior, "defence_warp_original_defence"):
            del warrior.defence_warp_original_defence


def battle_inner(warrior, enemy, skip_rest=False, round_num=0):
    global ALLOW_MONSTER_SELECT
    ALLOW_MONSTER_SELECT = True

    try:
        print(f"\n{warrior.name} enters the arena!")
        print(f"You face a {enemy.display_name}!")

        log()
        log("=" * 40)
        log(f"BATTLE START: {warrior.name} vs {enemy.display_name}")
        try:
            log(f"  {warrior.name}  HP:{warrior.hp}/{warrior.max_hp}  ATK:{warrior.min_atk}-{warrior.max_atk}  DEF:{warrior.defence}")
            log(f"  {enemy.display_name}  HP:{enemy.hp}/{enemy.max_hp}  ATK:{enemy.min_atk}-{enemy.max_atk}  DEF:{getattr(enemy, 'defence', 0)}")
        except AttributeError as e:
            log(f"  (stat snapshot unavailable: {e})")
        log("=" * 40)

        # Decide who starts
        warrior_turn = random.choice([True, False])
        player_turn_started = False

        if warrior_turn:
            warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)
            print("You get the first move!")
            COMBAT_LOG.append(f"{warrior.name} gets the first move!")
            enemy_went_first = False
            
            # Show HUD immediately
            

        else:
            print(f"{enemy.display_name} makes the first move!")
            COMBAT_LOG.append(f"{enemy.display_name} makes the first move!")
            enemy_went_first = True

            # Enemy attacks immediately BEFORE the loop
            enemy_attack(enemy, warrior)

            # Update adrenaline/berserk from damage taken
            check_berserk_trigger(warrior)
            warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)

            # 🔁 Apply any Defence Warp phase after this enemy turn
            update_defence_warp_after_enemy_turn(warrior)


            # After their opening strike, it becomes the warrior's turn
            warrior_turn = True
            player_turn_started = False


        # ==============================
        # MAIN COMBAT LOOP
        # ==============================
        # If the enemy went first (pre-loop attack already happened),
        # start turn_count at 2 so monster_ai_check doesn't re-trigger
        # the guaranteed turn-1 special on their first loop turn.
        turn_count = 2 if enemy_went_first else 1
        while warrior.is_alive() and enemy.is_alive():
            turn_spent = False
            # Reset per-turn Dealth Defier flag
        
            

            # ---------------------------------------
            # PLAYER TURN
            # ---------------------------------------
            if warrior_turn:
                log()
                log(f"--- Turn {turn_count}: {warrior.name}'s turn  (HP:{warrior.hp}/{warrior.max_hp}) ---")

                
                

                # ---------------------------------------
                # TURN STOP (stun/freeze/paralyze/etc.)
                # ---------------------------------------
                if not player_turn_started:
                    player_turn_started = True
                    
                    # --- GOBLIN DUST STAGE 1 (The only stage that skips a turn) ---
                    if getattr(warrior, "blind_type", "") == "goblin_dust" and warrior.blind_turns == 3:
                        # If we already skipped last turn (e.g. Paralyzed then Blinded)
                        if getattr(warrior, "last_turn_skipped", False):
                            print(wrap("\n🛡️ The Arena intervenes! You resist the blinding dust and stand your ground!"))
                            log("  [STATUS] Arena intervenes — blindness resisted (consecutive skip guard).")
                            warrior.is_blinded = False
                            warrior.blind_turns = 0
                            warrior.last_turn_skipped = False
                        else:
                            print(wrap("\n😵 You are completely blind! You swing wildly and miss your turn!"))
                            log("  [STATUS] BLINDED (goblin dust) — turn skipped.")
                            warrior.blind_turns -= 1
                            warrior.last_turn_skipped = True 
                            warrior_turn = False
                            player_turn_started = False
                            continue 

                    # --- OTHER TURN STOPS (Paralyze, Standard Blind, etc.) ---
                    elif resolve_player_turn_stop(warrior):
                        if getattr(warrior, "last_turn_skipped", False):
                            print("\n🛡️ The Arena intervenes! You shake off the stun!")
                            log("  [STATUS] Arena intervenes — stun resisted (consecutive skip guard).")
                            # Clear the specific stop reason
                            warrior.is_blinded = False
                            warrior.is_paralyzed = False
                            warrior.paralyzed = False
                            warrior.last_turn_skipped = False
                            # Arena grants a free turn — fall through to let player act
                        elif getattr(warrior, "paralyzed", False) and warrior.skill_ranks.get("heal", 0) >= 4:
                            # Paralyzed + First Aid R4+ — player can choose to use it or struggle
                            heal_rank = warrior.skill_ranks.get("heal", 0)
                            print(f"\n🧊⚡ Your muscles seize up — you are PARALYZED!")
                            print(f"🩹 Your training kicks in... you might be able to fight through it.")
                            print(f"\n  1) Use First Aid (Rank {heal_rank}) — cure Paralyze")
                            print(f"  2) Struggle — lose your turn (Paralyze fades next turn)")
                            para_choice = input("\nChoice: ").strip()
                            if para_choice == "1":
                                result = heal(warrior, mode="combat")
                                if result:
                                    # First Aid cured it — clear turn stop so they don't lose next turn
                                    warrior.paralyzed = False
                                    warrior.turn_stop = 0
                                    warrior.turn_stop_reason = ""
                                    warrior.turn_stop_chain_guard = False
                                    warrior.last_turn_skipped = False
                                    log("  [STATUS] PARALYZED — player used First Aid (Rank {}) to cure it. Turn spent.".format(warrior.skill_ranks.get("heal", 0)))
                                    # First Aid used their action — end player turn
                                    warrior_turn = False
                                    player_turn_started = False
                                    continue
                                else:
                                    # Not enough AP or cancelled — fall through to struggle
                                    print("⚡ You can't break free in time — you lose your action!")
                                    log("  [STATUS] PARALYZED — First Aid failed/cancelled. Turn lost.")
                                    warrior.last_turn_skipped = True
                                    warrior_turn = False
                                    player_turn_started = False
                                    continue
                            else:
                                # Struggle — paralyze fades via chain guard next turn
                                print("⚡ You grit your teeth and endure... the paralysis will fade!")
                                log("  [STATUS] PARALYZED — player chose to struggle. Turn lost.")
                                warrior.last_turn_skipped = True
                                warrior_turn = False
                                player_turn_started = False
                                continue
                        else:
                            print(f"🧊⚡ Your muscles lock up — you're {warrior.turn_stop_reason.upper()} and lose your action!")
                            log(f"  [STATUS] {warrior.turn_stop_reason.upper()} — turn lost.")
                            warrior.last_turn_skipped = True
                            warrior_turn = False
                            player_turn_started = False
                            continue

                    # --- STAGE 2 & 3 SAFETY ---
                    # If we get here, it means we didn't skip. 
                    # We must reset last_turn_skipped so the Arena doesn't intervene LATER.
                    else:
                        warrior.last_turn_skipped = False
                    

                    # ==========================
                    # DOT TICKS (Poison + Burn + Acid) — unified
                    # ==========================
                    dot_total, dot_parts, dot_fades = collect_dot_ticks(warrior)

                    if dot_total > 0:
                        warrior.hp = max(0, warrior.hp - dot_total)

                        # ✅ Death Defier can trigger on DOT deaths (single place)
                        if warrior.hp <= 0:
                            try_death_defier(warrior, "dot")

                        dot_math_breakdown(warrior, dot_parts, tag="DOT")
                        
                        for _fade in dot_fades:
                            print(_fade)
                        log(f"  [DOT] {warrior.name} takes {dot_total} damage from status effects. HP now: {warrior.hp}/{warrior.max_hp}")
                    if not warrior.is_alive():
                        print("You have succumbed to your wounds...")
                        log(f"  [DEATH] {warrior.name} killed by DoT (poison/burn/acid) on turn {turn_count}.")
                        log(f"  [RESULT] DEFEAT — {warrior.name} fell to status damage.")
                        while True:
                            view = input("\nWould you like to view your combat log? (yes/no): ").strip().lower()
                            if view == "yes":
                                view_combat_log()
                                break
                            elif view == "no":
                                print("Farewell, warrior.")
                                break
                            else:
                                print("Incorrect input, please enter yes or no.")
                        return False



    
                    # ==========================
                    # 4) APPLY BLEED DAMAGE (1 turn only)
                    # ==========================
                    '''if warrior.bleed_turns > 0:
                        bleed_damage = 3
                        warrior.hp = max(0, warrior.hp - bleed_damage)

                        print(wrap(
                            "🩸 Blood drips from your wound. You take 3 bleed damage."
                        ))
                        print(f"❤️ Your HP is now {warrior.hp}/{warrior.max_hp}")

                        warrior.bleed_turns = 0'''
            
                
                # ==========================
                # 5) CHECK BERSERK TRIGGER
                # ==========================
                check_berserk_trigger(warrior)

                # ==========================
                # 6) ADRENALINE UPDATE
                # ==========================
                warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)
                warrior.total_special = warrior.current_bonus_damage

                # ==========================
                # 7) SHOW UI
                # ==========================
                # Player is taking a real free action — clear post-paralyze
                # protection so the enemy can attempt to paralyze again after
                # this full turn cycle completes.
                if getattr(warrior, "post_paralyze_guard", False):
                    warrior.post_paralyze_guard = False
                warrior.show_game_stats(enemy=enemy)

                # ==========================
                # 8) INPUT + DEBUG + Monster Select COMMANDS
                # ==========================
                has_weapon    = warrior.equipment.get("weapon") is not None
                has_accessory = warrior.equipment.get("accessory") is not None

                # --- Build dynamic attack lines and slot numbers ---
                # Scenario A: both equipped  → 1) Weapon Attack  2) Accessory Attack  3) Special ...
                # Scenario B: accessory only → 1) Attack (Accessory Name)  2) Special ...
                # Scenario C: weapon only / neither → 1) Attack  2) Special ...
                if has_weapon and has_accessory:
                    acc_name      = warrior.equipment["accessory"].name
                    special_num   = "3"
                    potion_num    = "4"
                    stats_num     = "5"
                    run_num       = "6"
                    valid_choices = ("1", "2", "3", "4", "5", "6")
                    prompt = (
                        "Your move:\n"
                        f"1) Weapon Attack\n"
                        f"2) Accessory Attack ({acc_name})   "
                        f"{special_num}) Special   {potion_num}) Potion   "
                        f"{stats_num}) Stats   {run_num}) Run"
                    )
                elif has_accessory and not has_weapon:
                    acc_name      = warrior.equipment["accessory"].name
                    special_num   = "2"
                    potion_num    = "3"
                    stats_num     = "4"
                    run_num       = "5"
                    valid_choices = ("1", "2", "3", "4", "5")
                    prompt = (
                        f"Your move:   1) Attack ({acc_name})   "
                        f"{special_num}) Special   {potion_num}) Potion   "
                        f"{stats_num}) Stats   {run_num}) Run"
                    )
                else:
                    special_num   = "2"
                    potion_num    = "3"
                    stats_num     = "4"
                    run_num       = "5"
                    valid_choices = ("1", "2", "3", "4", "5")
                    prompt = (
                        f"Your move:   1) Attack   "
                        f"{special_num}) Special   {potion_num}) Potion   "
                        f"{stats_num}) Stats   {run_num}) Run"
                    )
                raw = input(prompt + "\n> ")

                handled, payload = handle_monster_select_shortcut(
                    raw,
                    warrior=warrior,
                    in_combat=True
                )

                if handled:
                    if isinstance(payload, tuple) and payload[0] == "monster_select":
                        monster = payload[1]
                        print("\n⚔️ Combat Debug: Swapping to a custom monster!\n")
                        return battle_inner(warrior, monster)
                    # handled but cancelled or ran something else → re-prompt
                    continue

                # ----------------------------------------------------
                # 🧬 UNIVERSAL MONSTER SELECT (COMBAT VERSION)
                # ----------------------------------------------------
                if isinstance(raw, tuple) and raw[0] == "monster_select":
                    monster = raw[1]
                    if monster:
                        print("\n⚔️ Combat Debug: Swapping to a custom monster!\n")
                        return battle_inner(warrior, monster)  # restart combat vs new monster
                    # If cancelled, just re-prompt combat choices
                    continue

                # ----------------------------------------------------
                # From here on we expect a normal text input
                # ----------------------------------------------------
                if not isinstance(raw, str):
                    print("Invalid input, try again.")
                    continue

                cleaned = raw.strip().lower()

                # --- Developer shortcut: quit / pause ---
                if cleaned == "q":
                    print("\n🔄 Developer Shortcut: Quit / Pause triggered.")
                    raise RestartException


                # ----------------------------------------------------
                # Debug console shortcut
                # ----------------------------------------------------
                if cleaned == "debug":
                    debug_menu(warrior, enemy)
                    continue

                # ----------------------------------------------------
                # Validate combat choices
                # ----------------------------------------------------
                if cleaned not in valid_choices:
                    print("Invalid choice, try again.")
                    continue

                choice = cleaned

                # ==========================
                # 9) PLAYER ACTIONS
                # ==========================

                # --- Stats and Run Away use dynamic slot numbers ---
                if choice == stats_num:
                    clear_screen()
                    warrior.show_combat_stats()
                    input("\nPress Enter...")
                    continue

                elif choice == run_num:
                    print(wrap(
                        "You turn your back on the crowd and attempt to flee the arena! "
                        "The crowd boos and you are shot in the back.", WIDTH))
                    space()
                    print(wrap(
                        "Death comes slowly. The arrow drips with lethal poison. "
                        "Five minutes of agony follow.", WIDTH))
                    space()
                    print(wrap(
                        "As you take your final breath, the monster shaman whispers:"
                        " 'You are not even worthy of resurrection.'", WIDTH))
                    warrior.hp = 0
                    warrior.death_reason = "ran away"
                    continue_text()

                    warrior.titles.add("Coward")
                    warrior.endings.add("Disgraced One")
                    warrior.show_all_game_stats()
                    input("\nPress Enter to quit.")
                    quit()

                elif choice == "1":
                    # Choice 1 is always a weapon attack when weapon is equipped,
                    # or the only attack (accessory-only / bare-handed) otherwise.
                    use_acc = has_accessory and not has_weapon
                    reduction = 1.0
                    if warrior.is_blinded and getattr(warrior, "blind_type", "") == "goblin_dust":
                        if warrior.blind_turns == 2:
                            reduction = 0.50
                            print("👁️ Vision blurry... (50% power)")
                        elif warrior.blind_turns == 1:
                            reduction = 0.75
                            print("👁️ Vision clearing... (75% power)")
                    atk_type = "Accessory Attack" if use_acc else "Weapon Attack"
                    log(f"  [PLAYER] chose {atk_type}" + (f" (blind x{reduction})" if reduction < 1.0 else ""))
                    player_basic_attack(warrior, enemy, multiplier=reduction, use_accessory=use_acc)
                    log(f"  [RESULT] {enemy.display_name} HP: {enemy.hp}/{enemy.max_hp}")
                    turn_spent = True

                elif choice == "2" and has_weapon and has_accessory:
                    # Both equipped → choice 2 is always the accessory attack
                    reduction = 1.0
                    if warrior.is_blinded and getattr(warrior, "blind_type", "") == "goblin_dust":
                        if warrior.blind_turns == 2:
                            reduction = 0.50
                            print("👁️ Vision blurry... (50% power)")
                        elif warrior.blind_turns == 1:
                            reduction = 0.75
                            print("👁️ Vision clearing... (75% power)")
                    log(f"  [PLAYER] chose Accessory Attack" + (f" (blind x{reduction})" if reduction < 1.0 else ""))
                    player_basic_attack(warrior, enemy, multiplier=reduction, use_accessory=True)
                    log(f"  [RESULT] {enemy.display_name} HP: {enemy.hp}/{enemy.max_hp}")
                    turn_spent = True

                elif choice == special_num:  # Special
                    log(f"  [PLAYER] chose Special Move")
                    used = skill_menu(warrior, enemy)
                    if used:
                        log(f"  [RESULT] {enemy.display_name} HP: {enemy.hp}/{enemy.max_hp}  |  {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")
                        turn_spent = True

                elif choice == potion_num:
                    log(f"  [PLAYER] chose Potion")
                    used = use_potion_menu(warrior)
                    if used:
                        log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")
                        turn_spent = True
                    else:
                        continue
                    

                # ==========================
                #  BLINDNESS TICK DOWN
                # ==========================
                if turn_spent and warrior.blind_turns > 0:

                    warrior.blind_turns -= 1

                    # When blindness ends
                    if warrior.blind_turns == 0 and warrior.blind_long:
                        print("✨ Your vision fully clears.")
                        warrior.blind_long = False

                # ==========================
                # 10) ENEMY DEATH CHECK
                # ==========================
                if not enemy.is_alive():
                    # Reset defense
                    if hasattr(warrior, "original_defence"):
                        warrior.defence = warrior.original_defence
                        del warrior.original_defence

                    print(f"\nYou have defeated {enemy.display_name}!")
                    log(f"  [DEATH] {enemy.display_name} defeated by {warrior.name} on turn {turn_count}.")
                    warrior.gold += enemy.gold
                    warrior.monster_essence.extend(enemy.essence)

                   

                    # 1. LOOT DROP
                    loot = make_loot(enemy.name, monster_level=getattr(enemy, "level", 1), round_num=round_num)
                    if loot:
                        warrior.inventory.append(loot)
                        print(f"\n🎁 {loot.short_label()} added to your bag!")
                        print(wrap("Equip it from Inventory & Equipment at the next rest."))
                        log(f"  [LOOT] {loot.short_label()} dropped.")
                    # 2. Xp animation bar 
                    animate_xp_results(warrior, enemy.xp)

                    # 3. BOSS/VICTORY CHECK
                    if enemy.name == "Fallen Warrior":
                        print("\n✨ The arena falls silent as the Fallen Warrior collapses!")
                        print("🏆 The crowd roars — you are the Champion of the Arena!")
                        log(f"  [RESULT] VICTORY — {warrior.name} defeated the Fallen Warrior! (Champion ending)")
                        return "win"

                    # 4. PAUSE AND REST
                    log(f"  [RESULT] VICTORY — {warrior.name} defeated {enemy.display_name}. Final HP: {warrior.hp}/{warrior.max_hp}")
                    input("\nPress Enter to continue.")
                    if not skip_rest:
                        rest_phase(warrior)

                    # reset_between_rounds handles all status clearing cleanly
                    reset_between_rounds(warrior)

                    return True

        
            # ---------------------------------------
            # ENEMY TURN
            # ---------------------------------------
            
            else:
                log()
                log(f"--- Turn {turn_count}: {enemy.display_name}'s turn  (HP:{enemy.hp}/{enemy.max_hp}) ---")
                # Tick any DoT the player's accessory applied to the enemy.
                # collect_dot_ticks() already exists for the hero — we just
                # pass the enemy instead.  Same function, zero new code.
                enemy_dot, enemy_dot_parts, enemy_dot_fades = collect_dot_ticks(enemy)
                if enemy_dot > 0:
                    enemy.hp = max(0, enemy.hp - enemy_dot)
                    dot_math_breakdown(enemy, enemy_dot_parts, tag="Your DoT")
                    
                    for _fade in enemy_dot_fades:
                        print(_fade)
                    log(f"  [DOT] {enemy.display_name} takes {enemy_dot} damage from your DoT. HP now: {enemy.hp}/{enemy.max_hp}")
                    if not enemy.is_alive():
                        print(wrap(f"\n{enemy.display_name.title()} collapses from your damage over time!"))
                        log(f"  [DEATH] {enemy.display_name} killed by DoT on turn {turn_count}.")

                        # === FULL DEATH / LOOT BLOCK (mirrors the player-turn death block) ===
                        if hasattr(warrior, "original_defence"):
                            warrior.defence = warrior.original_defence
                            del warrior.original_defence

                        print(f"\nYou have defeated {enemy.display_name}!")
                        warrior.gold += enemy.gold
                        warrior.monster_essence.extend(enemy.essence)

                        loot = make_loot(enemy.name, monster_level=getattr(enemy, "level", 1), round_num=round_num)
                        if loot:
                            warrior.inventory.append(loot)
                            print(f"\n🎁 {loot.short_label()} added to your bag!")
                            print(wrap("Equip it from Inventory & Equipment at the next rest."))

                        animate_xp_results(warrior, enemy.xp)

                        if enemy.name == "Fallen Warrior":
                            print("\n✨ The arena falls silent as the Fallen Warrior collapses!")
                            print("🏆 The crowd roars — you are the Champion of the Arena!")
                            log(f"  [RESULT] VICTORY — {warrior.name} defeated the Fallen Warrior via DoT! (Champion ending)")
                            return "win"

                        log(f"  [RESULT] VICTORY — {warrior.name} defeated {enemy.display_name} via DoT.")
                        input("\nPress Enter to continue.")
                        if not skip_rest:
                            rest_phase(warrior)

                        # reset_between_rounds handles all status clearing cleanly
                        reset_between_rounds(warrior)

                        return True

                # -----------------------------------------------
                # ENEMY PARALYZE CHECK  (applied by Paralyzing Arrow accessory)
                # -----------------------------------------------
                enemy_blind = getattr(enemy, "blind_turns", 0)
                if getattr(enemy, "skip_turns", 0) > 0:
                    print(wrap(f"🧊⚡ {enemy.display_name.title()} is PARALYZED — they lose their action!"))
                    log(f"  [STATUS] {enemy.display_name} PARALYZED — turn skipped. ({enemy.skip_turns} turn(s) remaining)")
                    enemy.skip_turns -= 1
                    update_defence_warp_after_enemy_turn(warrior)
                    warrior_turn = True
                    player_turn_started = False
                    turn_spent = True
                # -----------------------------------------------
                # ENEMY BLIND CHECK  (applied by Goblin Dagger)
                # blind_turns 3 = lost turn | 2 = 50% dmg | 1 = 75% dmg
                # -----------------------------------------------
                elif enemy_blind > 0:
                    if enemy_blind == 3:
                        print(wrap(f"👁️ {enemy.display_name.title()} is blinded — they stumble and lose their action!"))
                        log(f"  [STATUS] {enemy.display_name} BLINDED — turn skipped.")
                        enemy.blind_turns -= 1
                        update_defence_warp_after_enemy_turn(warrior)
                        warrior_turn = True
                        player_turn_started = False
                        continue
                        

                    else:
                        # blind_turns 2 or 1: attack at reduced effectiveness
                        if enemy_blind == 2:
                            reduction = 0.50
                            print(wrap(f"👁️ {enemy.display_name.title()} is still blinded — attack at 50% power!"))
                        else:  # blind_turns == 1
                            reduction = 0.75
                            print(wrap(f"👁️ {enemy.display_name.title()} is nearly recovered — attack at 75% power!"))

                        # Scale enemy's attack roll for this turn only
                        original_max = enemy.max_atk
                        original_min = enemy.min_atk
                        enemy.max_atk = max(1, int(enemy.max_atk * reduction))
                        enemy.min_atk = max(1, int(enemy.min_atk * reduction))

                        if monster_ai_check(enemy, turn_count):
                            log(f"  [ENEMY] {enemy.display_name} uses Special Move (blind x{reduction})")
                            enemy.special_move(enemy, warrior)
                        else:
                            log(f"  [ENEMY] {enemy.display_name} attacks (blind x{reduction})")
                            enemy_attack(enemy, warrior)
                        log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")

                        enemy.max_atk = original_max
                        enemy.min_atk = original_min
                        enemy.blind_turns -= 1
                        if enemy.blind_turns == 0:
                            print(wrap(f"✨ {enemy.display_name.title()}'s vision fully clears."))

                else:
                    # Use the new tiered AI logic
                    if monster_ai_check(enemy, turn_count):
                        # Monster has AP and passed its Tier % check
                        log(f"  [ENEMY] {enemy.display_name} uses Special Move")
                        enemy.special_move(enemy, warrior)
                    else:
                        # Default to basic attack
                        log(f"  [ENEMY] {enemy.display_name} attacks")
                        enemy_attack(enemy, warrior)
                    log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")

                turn_spent = True

                if not warrior.is_alive():
                    print("\nYou collapse as the arena roars...")
                    log(f"  [DEATH] {warrior.name} was killed by {enemy.display_name} on turn {turn_count}.")
                    log(f"  [RESULT] DEFEAT — {warrior.name} fell to {enemy.display_name}.")
                    while True:
                        view = input("\nWould you like to view your combat log? (yes/no): ").strip().lower()
                        if view == "yes":
                            view_combat_log()
                            break
                        elif view == "no":
                            print("Farewell, warrior.")
                            break
                        else:
                            print("Incorrect input, please enter yes or no.")
                    return False

                # Multi-turn defence effects from Fallen's Defence Warp
                update_defence_warp_after_enemy_turn(warrior)

                
        

            # ---------------------------------------
            # END OF TURN: advance turn if an action happened
            # ---------------------------------------
            if turn_spent:
                # Tick War Cry ONLY after a PLAYER action
                if warrior_turn:
                    tick_war_cry(warrior)
                    turn_count += 1
                    # Store turn count for chimera divine intervention check
                    # (updated here so both player and enemy turns count)
                    enemy.turns_survived = turn_count

                warrior_turn = not warrior_turn
                player_turn_started = False

        # -------------------------------------------------------
        # SAFETY FALLBACK: while loop exited cleanly
        # If warrior is alive and enemy is dead → warrior won.
        # This catches any edge case where the loop condition
        # (enemy.is_alive()) terminated the loop before an explicit
        # return True could fire (e.g. Power Strike kill, DoT kill
        # edge cases, or any future path we haven't anticipated).
        # -------------------------------------------------------
        if warrior.is_alive() and not enemy.is_alive():
            log(f"  [RESULT] VICTORY (safety fallback) — {warrior.name} defeated {enemy.display_name}. Final HP: {warrior.hp}/{warrior.max_hp}")
            return True

        # If warrior is also dead, it's a loss
        log(f"  [RESULT] DEFEAT (safety fallback) — {warrior.name} fell to {enemy.display_name}.")
        return False

    finally:
        # ALWAYS turns off monster select when combat exits
        ALLOW_MONSTER_SELECT = False






def simple_trainer_reaction(warrior):
    """Very simple trainer reaction based on 1–2 story flags."""

    if "warrior_arena_escape" in warrior.story_flags:
        print(wrap("I heard you tried to run. Hah."))
        print(wrap("At least you made them work for it. Use that fire out there."))
        return

    if "warrior_arena_submit" in warrior.story_flags:
        print(wrap("You just walked into the cell, huh?"))
        print(wrap("Being passive won't save you in the arena. Find your spark."))
        return

    # Fallback if no flag matched
    print(wrap("Whatever dragged you here, it won't matter once the gates open."))

def trainer_stat_point_scene(warrior):
    """
    One-time pre-tournament trainer scene.
    - Reacts to how you arrived (story_flags).
    - Grants 1 stat point and 1 skill point UNLESS already trained by Nob.
    - Uses the normal spend_points_menu to spend them.
    """

    # Only run once
    if "warrior_arena_trainer" in warrior.trainer_seen:
        return
    warrior.trainer_seen.add("warrior_arena_trainer")

    clear_screen()
    print(wrap(
        "Just before the first gate opens, a scarred arena trainer steps in front of you."
    ))
    space()

    already_trained = "warrior_trained_by_nob" in warrior.story_flags

    # 👀 React based on how you got here (ONLY if you haven't met Nob already)
    if "trainer_intro_arena" not in warrior.trainer_seen and not already_trained:
        simple_trainer_reaction(warrior)

    space()
    time.sleep(2)

    # If you already did the Nob training scene, don't "double-dip" rewards
    


    if already_trained:
        print(wrap(
            "Nob’s eyes briten slightly as you approach the arena. You did your training now use your new skills.", WIDTH))
        space()
        continue_text()

        # No new points granted here.
        spend_points_menu(warrior)
        space()
        return

    # Otherwise, this is your one-time pre-gate boost
    print(wrap(
        "He studies you for a long moment, then grunts. "
        "'Fine. You've earned one last adjustment before you go out there.'"
    ))
    print(wrap(
        "You feel a surge of potential — the trainer helps you sharpen one aspect of yourself."
    ))
    space()
    continue_text()

    warrior.stat_points += 1
    warrior.skill_points += 1
    print(wrap("✨ You gain 1 stat point AND 1 skill point to spend before the tournament begins."))
    space()
    continue_text()

    spend_points_menu(warrior)
    space()



def arena_battle(warrior, rounds_to_win=5):
    """
    Tournament:
    - Fight `rounds_to_win` random monsters in a row.
    - Lose or run once → run ends.
    """

    # -------------------------------
    # Arena-only hard level cap
    # -------------------------------
    old_cap = getattr(warrior, "level_cap", None)
    old_notified = getattr(warrior, "_level_cap_notified", False)

    warrior.level_cap = ARENA_LEVEL_CAP
    warrior._level_cap_notified = False

    try:
        # 🔸 One-time pre-tournament trainer scene
        trainer_stat_point_scene(warrior)

        print(wrap(
            "You are pushed out onto the arena floor. Magical torches flare to life around the ring. "
            "The stands are packed with monsters of every shape and size, all howling for blood.",
            WIDTH
        ))

        defeated_names = []
        champion = False

        for round_num in range(1, rounds_to_win + 1):
            print(f"\n--- Round {round_num} ---")

            if round_num == rounds_to_win:
                warrior.death_defier_used = False

            enemy = select_arena_enemy(round_num)
            result = battle(warrior, enemy, skip_rest=(round_num >= rounds_to_win - 1), round_num=round_num)

            # 1) Final boss / special Fallen ending
            if result == "win":
                champion = True
                defeated_names.append(enemy.name)
                break

            # 2) Tournament exit (your code uses this)
            if result == "tournament":
                return

            # 3) Normal death / loss
            if not result or not warrior.is_alive():
                print(wrap(
                    f"{enemy.name} stands victorious over your fallen body. "
                    "As your vision fades to black, you hear a voice proclaim, "
                    "'You will serve the beast gods for all eternity!'",
                    WIDTH
                ))
                space()
                print("The last thing you hear is the crowd roaring in triumph")
                GAME_WARRIOR.titles.add("Fallen Champion")
                GAME_WARRIOR.endings.add("fallen_ending")
                print("You acquired the Title: Fallen Champion")

                GAME_WARRIOR.show_all_game_stats()
                return

            # 4) Normal win (round continues)
            defeated_names.append(enemy.name)

            # 5) After penultimate round, send player to quarters (NO break)
            if round_num == rounds_to_win - 1 and warrior.is_alive():
                arena_quarters_interlude(warrior)
                clear_screen()


        # --------- POST-TOURNAMENT SUMMARY ---------
        print("\n🏆 You are victorious in the arena!")
        if defeated_names:
            print(wrap("You defeated: " + ", ".join(defeated_names)))
        print(f"You leave with {warrior.gold} gold.")
        print()

        if warrior.monster_essence:
            print(wrap("Essences collected: " + ", ".join(warrior.monster_essence)))
        else:
            print("Essences collected: None")


        if champion:
            warrior.titles.add("Champion of the Arena")
            warrior.endings.add("champion_ending")

            warrior.show_game_stats()

            print("\n🏆 Title Earned: Champion of the Arena")
            print("📜 Ending Unlocked: champion_ending")
            print(wrap(
                "Your triumph echoes throughout the arena! The monsters fall silent for a moment, "
                "then unleash a deafening roar of approval. Your legend begins here.",
                WIDTH
            ))

            # Weapon Core reverts to cube after the final fight
            core = warrior.equipment.get("weapon")
            if core and "Weapon Core" in getattr(core, "name", ""):
                print(wrap(
                    "\nThe Weapon Core pulses once in your grip — warm, alive almost — "
                    "and then collapses inward with a soft hum. "
                    "In your hand sits a small, smooth cube no larger than your fist. "
                    "It has already chosen who it belongs to next."
                ))
                warrior.equipment.pop("weapon", None)
                print(wrap("🔲 The Weapon Core has reverted. It will find its way to your child."))

            if COMBAT_LOG:
                while True:
                    view = input("\n📋 View your full combat record? (yes/no): ").strip().lower()
                    if view == "yes":
                        view_combat_log()
                        break
                    elif view == "no":
                        break
                    else:
                        print("Incorrect input, please enter yes or no.")

    finally:
        # restore previous settings after arena ends
        warrior.level_cap = old_cap
        warrior._level_cap_notified = old_notified


# ===============================
# Story / Intro
# ===============================
def intro_story_inner(warrior):
    """Long-form intro story leading into the arena_battle(warrior)."""

    clear_screen()
    print(wrap(
        "You find yourself stumbling through a forest late at night. "
        "Your torch flickers against the shadows of the trees.",
        WIDTH
    ))

    space()
    print(wrap(
        "You are hungry and exhausted, trying to reach the nearest town: Winter Haven.",
        WIDTH
    ))
    space()
    winter_heaven_info = check(
        "Would you like more information about Winter Haven? (yes/no)\n> ",
        ["yes", "no"]
    )

    

    # ============================================================
    # BRANCH: LEARN ABOUT WINTER HAVEN
    # ============================================================
    if winter_heaven_info == "yes":
        clear_screen()
        print(wrap(
            "Winter Haven is a small, poor but industrious mountain town located on the edge of the Frostback Mountains. It isn't the most exciting place, "
            "but there is a dungeon nearby.",
            WIDTH
        ))
        print(wrap(
            "It used to be the mining powerhouse of the Kingdom of Arkium, but now most of the ore veins have been exhausted.",
            WIDTH
        ))

        space()
        print(wrap(
            "The dungeon of Winter Haven is special and rumored to be blessed by the gods. Many adventurers travel to Winter Haven " 
            "in search of riches. The dungeon routinely replenishes its treasures. Nothing compares to the big prize though. Every adventurer dreams of clearing a dungeon floor. " 
            "When that happens, exhausted ore veins refill and random pockets of exotic ores also appear.",
            
            WIDTH
        ))

        space()
        print(wrap("The deeper you go the more floors you clear the better the rewards. " 
        "However, no adventurer has cleared past the first floor in over a century. A brave few have explored parts of the second floor, but only a few have returned, and those who do are often silent about their experience." 
        " Despite that Winter Haven has created some of the best black smiths this side of the Frostback Mountains.", WIDTH))
        space()
        continue_text()
        clear_screen()

        print(wrap(
            "You find yourself contemplating what could cause such a miracle.",
            WIDTH
        ))
        print(wrap(
            "Lost in thought, you fail to notice a tree stump in front of you.",
            WIDTH
        ))
        
        
    

        print(wrap(
            "Your foot catches on the stump and you tumble forward. Your torch flies from your "
            "hand and lands in the mouth of a nearby cave.",
            WIDTH
        ))
        print(wrap(
            "A deep, angry voice echoes from within, \"Who goes there?\"",
            WIDTH
        ))
        continue_text()

        #continue_text()
        clear_screen()
        GAME_WARRIOR.name = get_name_input()


        print(wrap(
            "A burly beastman steps out of the cave, towering over you. "
            "He snorts and says, \"Looks like we have another volunteer for our monster tournament.\"",
            WIDTH
        ))

        tournament_entrance = check(
            f"\nWhat do you do, {warrior.name}? Do you try to escape, or submit?\n"
            "Type '(1' to try to escape, or '(2' to accept your fate.\n> ",
            ["1", "2"]
        )

        

        # --------------------------------------------
        # TRY TO ESCAPE
        # --------------------------------------------
        if tournament_entrance == "1":
            warrior.arena_origin = "escape_attempt"
            warrior.story_flags.add("warrior_arena_escape")
            clear_screen()
            print(wrap(
                "You turn and sprint into the forest, but the beastman is far too fast. "
                "He charges after you with terrifying speed. "
                "Your mind begins to cloud you as you realize your pursuer now controls your fate.",
                WIDTH
            ))

            space()
            print(wrap(
                "A short chase ensues, but the beastman's agility and animalistic aggression "
                "are overwhelming. He slams into you with a brutal tackle.",
                WIDTH
            ))

            space()
            beast_man_tackle = random.randint(1, 4)
            GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - beast_man_tackle)
            print(wrap(
                f"Pain sears through your body. You take {beast_man_tackle} damage.",
                WIDTH
            ))
            print(wrap(
                f"You have {GAME_WARRIOR.hp} HP remaining.",
                WIDTH
            ))

            space()
            
            print(wrap(
                "The beastman roars in triumph and laughs. "
                "\"Nice try,\" he says. \"That's the most fun I've had in a while. "
                "You might actually have a chance in our tournament.\"",
                WIDTH
            ))
            space()
            continue_text()
            clear_screen()

            space()
            print(wrap("'Here is something to help you out.' Bo hands you two potions — one healing potion and one action point potion." \
            " Your hands are tied and Bo escorts you to a nearby monster stronghold. " \
            "A grizzled bear folk meets you at the gates. 'This is Nob, our current Arena Trainer. He will be taking care of you.' Bo gestures.", WIDTH))
        # this rewards player with an extra heal potion for being brave
            GAME_WARRIOR.potions["heal"] += 1

            tournament_knowledge = check(
                "\nWould you like to learn about the tournament? (yes/no)\n> ",
                ["yes", "no"]
            )
            clear_screen()

           
                

            # Learn about tournament
            if tournament_knowledge == "yes":
                print(wrap(
                    "You ask the beastman about the tournament.",
                    WIDTH
                ))
                print(wrap(
                    "\"Ah, the tournament,\" he rumbles. "
                    "\"As you adventurers train to kill monsters, "
                    "our monsters also train to kill adventurers.\"",
                    WIDTH
                ))

                space()
                print(wrap(
                    "\"We gain new skills, just like you do. The tournament is a test for our young warriors.\"",
                    WIDTH
                ))
                print(wrap(
                    f"\"The tournament pits a random adventurer— you, {warrior.name} — "
                    "against four different monsters of varying strength. "
                    "Defeat all four in single combat, then fight the champion and you win your freedom.\"",
                    WIDTH
                ))

                space()
                print(wrap(
                    "\"Every monster contains an essence. Those essences are the price of your freedom.\"",
                    WIDTH
                ))
                print(wrap(
                    "You feel like the beastman might be willing to share more information "
                    "if you can persuade him.",
                    WIDTH
                ))
                continue_text()
                clear_screen()
               

                tournament_inquiry = check(
                    "\nDo you inquire further? (yes/no)\n> ",
                    ["yes", "no"]
                )

                
                if tournament_inquiry == "yes":
                    
                    persuasion_roll = random.randint(1, 20)
                    

                    if persuasion_roll >= 12:
                        # Successful persuasion
                        extra_info_choice = check(
                            wrap(
                                "What else would you like to know?\n"
                                "Type '(1' for more about monster essences,\n"
                                "or ('2' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["1", "2"]
                        )

                        if extra_info_choice == "1":
                            clear_screen()
                            print(wrap(
                                "\"You're a curious one,\" the beastman says.\n\n"
                                "\"A monster's essence is like its soul. "
                                "It allows us to revive them. You adventurers kill so many of us "
                                "that we'd go extinct without them.\"",
                                WIDTH
                            ))
                            print(wrap(
                                f"\"The tournament starts tomorrow night. Rest up, {warrior.name}. You'll need it.\"",
                                WIDTH
                            ))
                        elif extra_info_choice == "2":
                            clear_screen()
                            print(wrap(
                                "\"A fair question,\" he nods. "
                                "\"Obviously we can't have you spreading the word "
                                "about our tournaments. Other adventurers would hunt us down.\"",
                                WIDTH
                            ))
                            print(wrap(
                                "\"If you win, your memories of this place will be wiped. "
                                "You'll be left where we found you— "
                                "possibly a little stronger, with some extra gold in your pack.\"",
                                WIDTH
                            ))
                            print(wrap(
                                "\"The tournament starts tomorrow night. Good luck.\"",
                                WIDTH
                            ))
                        
                    else:
                        # Failed persuasion
                        clear_screen()
                        print(wrap(
                            "\"The only extra information I'm going to share,\" he growls, "
                            "\"is that the tournament is tomorrow night. That should be enough for you.\"",
                            WIDTH
                        ))

                # Common wrap-up for this path
                print()
                print(wrap(
                    "You are thrown into a damp cell. After a few hours of rough sleep, "
                    "you are harshly awakened by the arena trainer, Nob. 'Get up,' he says, 'it's time for training. The beast gods want a show and you are going to give it to them.' " \
                    "Nob puts you through an intensive regimen of sprinting. Your legs burn and your breathing becomes heavy.",
                    WIDTH
                ))
                # Story-only training — no menus yet

                warrior.story_flags.add("warrior_trained_by_nob")
                warrior.trainer_seen.add("trainer_intro_arena")

                # Reward for surviving the night
                warrior.stat_points += 1
                warrior.skill_points += 1

                

                space()
                print(wrap(
                    "After a few hours of training you are put back in your cell. Monsters pass your cell." 
                    "You can understand some of the monsters speaking outside. Most of them "
                    "are placing bets on your chances of survival. The odds are overwhelmingly "
                    "stacked against you.",
                    WIDTH
                ))
                continue_text()
                clear_screen()

                space()
                print(wrap(
                    f"You do overhear the beastman who captured you placing a bet in your favor.",
                    WIDTH
                ))
                print(wrap(
                    "Night falls. The cage door creaks open. You are led toward the roaring sound "
                    "of a crowd.",
                    WIDTH
                ))

                
                continue_text()
                clear_screen()
                arena_battle(GAME_WARRIOR)
                return

            if tournament_knowledge == "no":
                clear_screen()
                print(wrap(
                    "You decide to wing it. Whatever this tournament is, you'll just survive it "
                    "the same way you survive everything else: one fight at a time.",
                    WIDTH
                ))
                space()

                print(wrap(
                    "You are thrown into a small cell. After a few hours of restless sleep you are rudely awakened by the arena trainer, Nob. " 
                    "'Get up,' he says, 'it's time to train.' You spend the next few hours being trained by Nob. After a few hours of intense and abusive training you are led back to your cell." \
                    " 'Sleep,' Nob growls, 'you fight soon.' As the sun sets and the moon rises you are grabbed by some nearby Orc guards and shoved out of your cell and down a stone hallway " 
                    "towards the sound of many voices.",
                    WIDTH
                ))
                space()

                print(wrap(
                    "The crowd roars as you step onto the blood-soaked sand.",
                    WIDTH
                ))
                continue_text()
                clear_screen()
                arena_battle(GAME_WARRIOR)
                return

        # --------------------------------------------
        # SUBMIT TO THE TOURNAMENT
        # --------------------------------------------
        if tournament_entrance == "2":
            warrior.arena_origin = "submitted"
            clear_screen()
            print(wrap(
                "The beastman looks disappointed. \"I always prefer when they run,\" he mutters.",
                WIDTH
            ))
            print(wrap(
                "\"Still,\" he says, eyeing you, \"I don't think you have much of a shot. "
                "Try to at least provide some entertainment.\"",
                WIDTH
            ))

            space()
            print(wrap(
                "You are placed in a cell for the night. The next evening, you are led "
                "into the arena as the crowd howls for blood.",
                WIDTH
            ))
            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return

    # ============================================================
    # BRANCH: NO WINTER HAVEN LORE (DARK FOREST PATH)
    # ============================================================
    if winter_heaven_info == "no":
        clear_screen()
        print(wrap(
            "You trip on a cleverly camouflaged rock and your torch flies from your hand, "
            "landing in a nearby mountain river and sputtering out.",
            WIDTH
        ))
        print(wrap(
            "The forest is swallowed by darkness. The canopy above blocks out the night sky, "
            "and the silence feels oppressive.",
            WIDTH
        ))
        continue_text()
        clear_screen()

        space()
        print(wrap(
            "You have no other source of light, and a soaked torch won't light easily.",
            WIDTH
        ))
        print(wrap(
            "Why tonight? You're tired, hungry, and this unnatural darkness makes you feel uneasy. You were looking forward to spending the night in Winter Haven.",
            WIDTH
           ))
        
        space ()
        print(wrap("You have been traveling through the thick forests of the Winter Haven for the last few days, surviving off traveler's rations, and sleeping on the cold ground", WIDTH))

       
        space()
        print(wrap("The rations are cold and bland, and sleeping on a bedroll is far from comfortable", WIDTH))
        print(wrap("You can't travel without a torch. That sweet bowl of lamb stew, a warm cider, and a soft bed will have to wait until tomorrow. Or will they?", WIDTH))
      
        continue_text()
        clear_screen()

        night_choice = check(
            wrap(
                "\nWhat do you do?\n"
                "Type '1' to rest against the trees until first light,\n"
                "or '2' to feel your way toward where the torch fell.\n> ",
                WIDTH
            ),
            ["1", "2"]
        )

        

        # ------------------------------
        # REST PATH
        # ------------------------------
        if night_choice == "1":
            clear_screen()
            print(wrap(
                "Blundering around in this deep darkness seems like a bad idea. "
                "You decide to try to get a few hours of sleep before first light.",
                WIDTH
            ))

            space()
            print(wrap(
                "As you lie down, you hear distant, heavy footsteps. "
                "Fear slowly creeps into your mind. Your adrenaline rises "
                "as the footsteps grow closer.",
                WIDTH
            ))

            footsteps_choice = check(
                wrap(
                    "What do you do?\n"
                    "Type '(1' to call out, or '(2' to stay perfectly still.\n> ",
                    WIDTH
                ),
                ["1", "2"]
            )

           

            # CALL OUT
            if footsteps_choice == "1":
                clear_screen()
                print(wrap(
                    "You call out into the darkness, \"Hello? Is someone there?\"",
                    WIDTH
                ))
                continue_text()
               

                print(wrap(
                    "A deep, animalistic voice responds, \"Who goes there?\"",
                    WIDTH
                ))
                GAME_WARRIOR.name = get_name_input()


                print(wrap(
                    "The creature snaps its fingers. The magical darkness begins to lift. "
                    "It's still night, but you can now make out the shape of a towering figure, "
                    "like a bear standing on two legs.",
                    WIDTH
                ))

                fading_darkness = check(
                    wrap(
                        f"What do you do, {warrior.name}? Do you (1) run or (2) stay?\n> ",
                        WIDTH
                    ),
                    ["1", "2"]
                )
                clear_screen()

                

                # RUN FROM BO
                if fading_darkness == "1":
                    clear_screen()
                    print(wrap(
                        "Your adrenaline spikes and you bolt into the trees. "
                        "Behind you, an excited roar shakes the forest.",
                        WIDTH
                    ))
                    print(wrap(
                        "You glance back and see the bear-like creature charging on all fours, "
                        "rapidly closing the distance.",
                        WIDTH
                    ))

                    space()
                    print(wrap(
                        "Your panic gives you unnatural speed. For a moment, it feels like you're gaining ground.",
                        WIDTH
                    ))
                    print(wrap(
                        "Then you hear a frustrated growl, followed by a sharp snap. "
                        "The forest goes dark again.",
                        WIDTH
                    ))

                    space()
                    print(wrap(
                        "With your vision suddenly obscured, you run hard, face-first into a thick tree branch.",
                        WIDTH
                    ))

                    tree_attack = random.randint(2, 5)
                    GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - tree_attack)
                    print(wrap(
                        f"You take {tree_attack} damage from the impact. Your head throbs and your vision fades.",
                        WIDTH
                    ))
                    print(wrap(
                        f"You have {GAME_WARRIOR.hp} HP remaining.",
                        WIDTH
                    ))
                    continue_text()
                    space()
                    clear_screen()

                    print(wrap(
                        "When your vision clears, a massive bearman looms over you.",
                        WIDTH
                    ))
                    print(wrap(
                        f"\"Nice try, {warrior.name},\" he rumbles. \"You almost got away. "
                        "I haven't failed a pursuit in a long time. If it weren't for my magic, "
                        "you would have escaped.\"",
                        WIDTH))
                    
                    space()
                    print(wrap("'Here is a little something to help you out.' Bo hands you two potions — one healing potion and one action point potion.",WIDTH))
                    GAME_WARRIOR.potions["heal"] += 1
                    GAME_WARRIOR.potions["ap"] += 1
                    
                    print(wrap(
                        "\"I think you'll be a top-tier competitor in our upcoming tournament. "
                        "My name is Boar, but most call me Bo.\"",
                        WIDTH
                    ))
                   

                    tournament_info = check(
                        "\nWould you like to learn more about the tournament? (yes/no)\n> ",
                        ["yes", "no"]
                    )

                   
                    if tournament_info == "yes":
                        clear_screen()
                        print(wrap(
                            "\"Ah yes, the monster tournament,\" Bo says proudly. "
                            "\"It's a training ground for our young who come of age. "
                            "It gives them real combat experience. Since we are constantly "
                            "being hunted by adventurers, we want our young to have the "
                            "best chance of survival.\"",
                            WIDTH
                        ))

                        space()
                        print(wrap(
                            "\"The tournament pits you against four monsters in solo combat. "
                            "If you defeat all four you fight the champion, beat him and you win. Each monster you defeat rewards you "
                            "with a monster essence. Turn in the essences, and you are set free.\"",
                            WIDTH
                        ))

                        bo_questions = check(
                            wrap(
                                "Bo asks if you have any questions. Type '(1' to ask about essences, or '(2' to ask what happens if you win.\n> " \
                                "or '3(' to continue on)",
                                WIDTH
                            ),
                            ["1", "2", "3"]
                        )

                        if bo_questions == "1":
                            clear_screen()
                            print(wrap(
                                "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                "\"With them, we can revive fallen monsters. The essences, "
                                "provided by the beast gods provide us with a way to come back, learn hard lessons, and still live to fight another day.\"",
                                WIDTH
                            ))
                        elif bo_questions == "2":
                            clear_screen()
                            print(wrap(
                                "\"If you win,\" Bo says, \"your memories of this place will be wiped, "
                                "and you'll be returned to where we found you. "
                                "You might be stronger, richer... but you won't remember why.\"",
                                WIDTH
                            ))
                        elif bo_questions == "3":
                            print(wrap("Very well, it's just about time for you to meet the Arena Trainer, Nob."))

                    
                    print(wrap(
                        "Soon after, you are shackled and escorted to a fortified arena. "
                        "The crowd's distant roar vibrates through the stone beneath your feet. "
                        "You rest for a few hours and are violently woken up by a scarred, battle-hardened beast folk named Nob. " \
                        "'Get up,' he growls, 'I'm told you're fast — let's see how fast you truly are.' Nob spends the next few hours having you run sprints." \
                        " After Nob seems content with your progress he takes you back to your cell. 'Rest — you're going to need it,' he mumbles.",
                        WIDTH
                    ))
                    continue_text()
                    clear_screen()
                    arena_battle(GAME_WARRIOR)
                    return

                # STAY WITH BO
                if fading_darkness == "2":
                    clear_screen()
                    print(wrap(
                        "You stay where you are, forcing yourself not to run.",
                        WIDTH
                    ))
                    print(wrap(
                        "The bear-like creature steps into view. \"Brave, or frozen?\" he asks with a chuckle.",
                        WIDTH
                    ))
                    name = GAME_WARRIOR.name or "Adventurer"
                    print(wrap(
                        f"\"Either way, {warrior.name}, you'll do nicely for our tournament.\"",
                        WIDTH
                    ))
                    print(wrap(
                        "He introduces himself as Bo and explains the basics of the tournament: "
                        "four monsters, one human, and freedom as the prize.",
                        WIDTH
                    ))
                    continue_text()
                    clear_screen()
                    arena_battle(GAME_WARRIOR)
                    return

            # STAY SILENT
            if footsteps_choice == "2":
                clear_screen()
                print(wrap(
                    "You hold your breath and stay as still as possible. "
                    "The footsteps stop just a few paces away.",
                    WIDTH
                ))
                print(wrap(
                    "A low growl rumbles in the darkness. \"I can smell you, human,\" "
                    "a deep voice says. \"Hiding won't help.\"",
                    WIDTH
                ))

                space()
                print(wrap(
                    "A moment later, a heavy hand grabs you by the collar and hoists you off the ground.",
                    WIDTH
                ))
                print(wrap(
                    "\"Congratulations,\" the unseen creature chuckles. "
                    "\"You've been drafted into our tournament.\"",
                    WIDTH
                ))
                continue_text()
                clear_screen()
                arena_battle(GAME_WARRIOR)
                return

        # ------------------------------
        # SEARCH FOR THE TORCH PATH
        # ------------------------------
        if night_choice == "2":
            clear_screen()
            print(wrap(
                "You rise and carefully feel your way toward the sound of the gently flowing river, "
                "hoping to recover your torch.",
                WIDTH
            ))
            river_attack = random.randint(1, 2)
            GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - river_attack)
            print(wrap(
                "As you step onto the muddy embankment, your foot slips. "
                "You tumble into the ice-cold mountain river.",
                WIDTH
            ))

            space()
            print(wrap(
                f"You take {river_attack} damage from the fall and the frigid water. "
                f"You now have {GAME_WARRIOR.hp} HP remaining.",
                WIDTH
            ))
            print(wrap(
                "The freezing water shocks your body."
                
            ))
            print(wrap(
                "Soaked, shivering, and still without a torch, you mutter a few choice words "
                "about your luck.",
                WIDTH
            ))

            space()
            print(wrap(
                "Before you can regain your bearings, a beastly voice rings out. 'Do you want some help?' " \
                "A furry paw reaches down toward you",
                WIDTH
            ))
            accept_help = check(
                "\nDo you accept the help? (yes/no)\n> ",
                ["yes", "no"]
            )
            clear_screen()
            if accept_help == "yes":
                print(wrap("You cautiously accept the creature's paw and are lifted out " 
                "of the water.", WIDTH))

                space()
                print(wrap("You should be cautious of who you trust. That river would probably have eventually killed you. "
                "Anyway, perhaps that would have been a better way to go. Regardless, we need more fighters "
                "for our tournament. Congratulations on being selected. Try not to die too fast.", WIDTH))
                space()

                print(wrap("The creature binds your hands and escorts you to a nearby monster stronghold of Under-Haven. On the way to the stronghold the creature introduces himself as Bo. "
                "As the moon is starting to set you reach the stronghold and a cantankerous old beast man named Nob meets you at the gates. "
                " Bo introduces Nob as the arena trainer. Nob looks at you and mumbles 'Is this really the best you could find? Fine.' "
                "You are escorted into a holding cell and allowed to rest. A few hours later Nob shows up in your cell and yells at you to get up and train.", WIDTH))
                space()
                continue_text()
                clear_screen()

                print(wrap("Nob puts you through an intense sequence of upper body exercises and rapid leg workouts. 'Falling in the water and needing help"
                " to get out, disgraceful.' Finally you are allowed to go back to sleep, your clothes damp from the exertion. As the moon rises a group of orc guards come into your cell and drag"
                " you down the coarse stone hallway and towards the sounds of a roaring crowd.", WIDTH))

            if accept_help == "no":
                print(wrap("You decline the help and the creature says 'Very well. The river banks "
                " remain pretty steep for a while, and there are some serious rapids "
                "farther downstream. Good luck finding your way out, it being dark and all'."))

                continue_text()
                clear_screen()
                accept_help_2 = check(
                    "\nDo you reconsider and accept the help? (yes/no)\n> ",
                    ["yes", "no"]
                )
                if accept_help_2 == "yes":
                    print(wrap("You reluctantly accept help. The creature introduces himself as Boar, Bo for short. " 
                    "What is your name?"))
                    GAME_WARRIOR.name = get_name_input()
                    print(wrap("I respect your courage, adventurer, so I am going to give you a little something special. " 
                    "Boar hands you a potion of AP."))
                    GAME_WARRIOR.potions["ap"] += 1
                    print(wrap("The creature's eyes intensify. 'You're going to need it for the tournament.'"))
                if accept_help_2 == "no":
                    damage = river_attack*2 + 2
                    GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - damage)
                    print(wrap("Suit yourself. You continue downstream trying to find a place to climb out." \
                    " Your body's core temperature starts to drop. Your limbs begin to go numb." \
                    " If you don't get out of the water soon the elements could kill you."))

                    space()
                    print(wrap(f"You take {damage} damage from nearby floating debris as the river picks" \
                               " up speed. Boar walks alongside you, striking up a conversation. He" \
                               " says his friends call him Bo and he is looking for new competitors in a local" \
                               " tournament."))
                    print(wrap(f"You have {GAME_WARRIOR.hp} HP remaining."))
                    if GAME_WARRIOR.hp <= 0:
                        print("You die")
                        exit()
                    accept_help_final = check("I can see you are getting pretty cold. Are you sure you don't want" \
                    " my help? (yes/no)\n> ",
                    ["yes", "no"]
                    )
                    if accept_help_final == "yes":
                        print(wrap("I can see you are very brave. I will rescue you if you agree to fight in my tournament"))
                        accept_tournament = check("Do you accept? (yes/no)\n> ",
                        ["yes", "no"]
                        )
                        if accept_tournament == "yes":
                            print(wrap("Bo reaches down and effortlessly pulls you out of the frigid river. What is your name, adventurer?"))
                            GAME_WARRIOR.name = get_name_input()
                            print(wrap(f"I respect your stubbornness, {warrior.name}. Let me give you a fighting chance in our tournament. Bo hands you two potions — one for healing and one for AP."))
                            GAME_WARRIOR.potions["heal"] += 1
                            GAME_WARRIOR.potions["ap"] += 1
                                       
                                    
                                       
                                       
                    if accept_help_final ==  "no":
                        clear_screen()
                        jagged_rocks_attack = random.randint(1,6) + random.randint(1,8) + random.randint(1,10) + 6
                        GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - jagged_rocks_attack)
                        print(wrap("You refuse the help for the final time. You slip and lose your footing and the river carries you. " \
                        "Jagged rocks tear into your skin."))

                        space()
                        print(f"You take {jagged_rocks_attack} damage from the surrounding sharp rocks in the water.")
                        print(f"You have {GAME_WARRIOR.hp} HP remaining.")
                        if GAME_WARRIOR.hp <= 0:
                            print("Your body is flayed and you die")
                            GAME_WARRIOR.titles.add("Flayed One")
                            GAME_WARRIOR.endings.add("flayed_ending")
                            GAME_WARRIOR.show_all_game_stats()
                            input("\nPress Enter to end the game.")
                            sys.exit(0)
                        
                        if GAME_WARRIOR.hp > 0:
                            print(wrap("Blood slowly drips down your body as the rushing water continues to pick up speed. " \
                            "'At least the worst is over now,' you think to yourself as your body goes numb." \
                            " You can see the river banks shrinking."))

                            space()
                            print(wrap("The mountain river begins to bubble and churn, and before you know it you are surrounded by white water."
                            " Keeping afloat is almost impossible as the water continuously drags you under, and then"
                            " you hear it — a distant roaring growing ever louder."))

                            continue_text()
                            clear_screen()

                            space()
                            print(wrap("You realise what you are hearing. It's the sound of a waterfall."
                            " Panic grips you. You try to swim against the current, but you are weakened from"
                            " prolonged exposure to cold water and the numerous cuts you sustained among"
                            " the jagged rocks."))

                            space()
                            survival_roll = random.randint(1,20)
                            if survival_roll >= 15:
                                print(wrap(
                                    "You dig deep and muster every ounce of strength you have left. "
                                    "If you can't make it to shore, you will die."
                                ))

                                space()
                                print(wrap(
                                    "With the last of your resolve, fueled by pure adrenaline, you find your footing, "
                                    "and painstakingly fight the raging river toward the shoreline."
                                ))

                                continue_text()
                                space()
                                print(wrap(
                                    "As you struggle across the raging water you spot a figure racing along the shoreline. "
                                    "To your relief, it's Bo. The bank is only a few feet away now. "
                                    "You can see the edge of the waterfall, a few hundred more feet and you would have gone over its edge. "
                                    "That terrifying thought distracts you, and you lose your footing as the current overwhelms you again."
                                ))

                                space()
                                print(wrap(
                                    "The tumultuous waters drag you under, and right as you are about to accept your fate, "
                                    "a furry paw reaches in and rips you out of the water. You cough and take a ragged breath, "
                                    "as Bo sets you down on solid ground. You collapse onto the forest floor, exhausted."
                                ))

                                continue_text()

                                space()
                                print(wrap(
                                    "'You have to be the most stubborn human I've ever met. Consider me impressed, adventurer. "
                                    "You're a survivor. You'll make an excellent addition to our tournament.'"
                                ))

                                space()
                                print(wrap(f"'I think you have a pretty decent chance to win the monster " 
                                "tournament, adventurer, but not in your current state.' " 
                                "Bo begins to chant and your wounds fully heal. He also hands you a super potion. " 
                                "These are quite rare, especially for new adventurers to come upon. Use it wisely."))
                                GAME_WARRIOR.max_hp +=1
                                GAME_WARRIOR.hp = GAME_WARRIOR.max_hp
                                GAME_WARRIOR.potions["super_potion"] += 1
                                #print(f"{GAME_WARRIOR.max_hp} max hp")
                                GAME_WARRIOR.death_defier = True
                                GAME_WARRIOR.death_defier_river = True
                                GAME_WARRIOR.death_defier_used = False
                                GAME_WARRIOR.death_defier_active = False

                                space()

                                print(wrap(
                                    "Through sheer determination and unyielding willpower not to give up, you have earned the title: River Warrior!"
                                ))
                                print(f"🏷️ Title Earned: River Warrior")
                                print(f"✨ +1 Permanent Max HP! (now {GAME_WARRIOR.max_hp})")
                                print("🏅 New Ability Learned: Death Defier! (0 AP to activate)")

                                continue_text()
                                clear_screen()

                                space()       

                                
                                GAME_WARRIOR.name = get_name_input()

                                print(wrap("Despite your incredible display of bravery I still have to escort you to our arena. As long as you promise " \
                                "not to run, I'll guide you to where we are going."))



                                
                            
                            else:
                                    
                                print(wrap("You struggle to no avail. You can see the edge of the waterfall directly ahead."
                                " Your final strength fails, and you are dragged under the water, your back grazing"
                                " the now smooth bottom of the river. You are thrown off the waterfall and for a few seconds"
                                " you take in the beautiful surroundings."))

                                space() 
                                print(wrap("The sun is just starting to rise and you can make out snow-covered mountains" \
                                " covered in pine trees. You see the town of Winter Haven on the distant marble-covered cliffs, smoke" \
                                " rising from its chimneys, and then your free fall ends. Sharp pain pounds your body as you" \
                                " land hard in the icy water below the waterfall."))
                            
                                space()
                                waterfall_damage = 30
                                GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - waterfall_damage)
                                print(wrap(f"You take {waterfall_damage} damage from the fall. You have {GAME_WARRIOR.hp} HP remaining."))
                            if GAME_WARRIOR.hp <= 0:
                                print(wrap("The impact kills you"))
                                continue_text()
                                GAME_WARRIOR.titles.add("Drowned One")
                                GAME_WARRIOR.endings.add("Broken_one")
                                GAME_WARRIOR.show_all_game_stats()

                                input("\nPress enter to end the game.")
                                sys.exit(0)

                                
                                               


            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return



if __name__ == "__main__":
    GAME_WARRIOR = Warrior()
    COMBAT_LOG.clear()
    intro_story(GAME_WARRIOR)
    

'''✅ Dungeon Adventure – Version History Summary
⚙️Version Journey To Winter Haven version v4.28 (Journey_To_Winter_Haven_v_04_28.py)
* Acid Sac redesigned — poor: 3 dmg/1 turn/no DEF erosion; normal: 3 dmg/2 turns/-1 DEF immediately; uncommon: 4 dmg/2 turns/-2 DEF immediately; DEF restores after 2 turns; reapplying resets clock
* element_erosion added as a proper Equipment parameter; poor carries 0 so behaviour unchanged at poor tier
* Hydra Hatchling acid tick bumped from 2–4 to flat 3–5 per tick (monster should hit harder than its accessory drop)
* All three combat log yes/no prompts now loop with "Incorrect input, please enter yes or no." on invalid input
* CHANGELOG.md and DEVLOG.md added to repo — full project history from v0.08 to present

⚙️Version Journey To Winter Haven version v4.27 (Journey_To_Winter_Haven_v_04_27.py)
* Debug menu option 15 Loot Manager — merged old Give Loot and Equip Loot into one unified sub-menu
* Loot Manager mode A: Give to Inventory (consumables/drop sims via make_loot with forced rarity)
* Loot Manager mode B: Equip Directly (pick any equippable item + rarity, instant equip via equip_item())
* Loot Manager mode C: Unequip Slot (lists all three slots, cleanly reverses stats via unequip_item())
* Loot Manager shows current equipped gear and live stats at the top of the menu on every pass
* Debug menu option 17: Restore AP to Full — instantly fills AP, prints old → new value
* Debug menu option 18: Debug Potion Menu — all 12 potion types, add any quantity, option 13 quick fills x3 of everything
* Debug menu level up (option 12) now grants all levels silently in one pass before prompting
* Stat snapshot added after level grant — shows HP, AP, ATK, DEF, XP threshold and current gear before spend prompt
* Spend points prompt defaults to y on enter, goes straight into spend_points_menu after level grant
* Debug menu exits renumbered — option 19 Exit Current Run, option 20 Exit Debug Menu
* Fallen Warrior HP increased to 60, AP increased to 5
* Fallen Warrior defence lowered from 5 → 4

⚙️Version Journey To Winter Haven version v4.25–v4.26 (Journey_To_Winter_Haven_v_04_25/26.py)
* Acid Sac turn scaling fixed to match Poison and Fire Sac — normal now 2 turns, uncommon 3 turns
* Quarters interlude spend points option hidden if player has no unspent points
* Duplicate combat log option removed from quarters interlude menu
* All monster names standardized to Title Case — Javelina loot table key corrected (was silently not dropping)
* Full audit confirmed all 14 monster loot table keys match their class name fields

⚙️Version Journey To Winter Haven version v4.24 (Journey_To_Winter_Haven_v_04_24.py)
* collect_dot_ticks() refactored — all expire/fade messages now collected into fade_msgs list and printed after damage line
* Duplicate dot_math_breakdown calls removed from both player and enemy DOT call sites
* Fallen Warrior HP increased from 53 to 57
* Quarters interlude spend points option added — players can spend unspent stat and skill points pre-championship

⚙️Version Journey To Winter Haven version v4.19.3 (journey_4_19_3.py)
* Fixed item stat description wrapping — each stat now prints on its own line
* element_max_dots added to Equipment class (default 1, rare=2, epic=2, legendary=3)
* Sac tables updated for multi-dot at rare+ rarities
* Fire/Poison/Acid application respects max_dots — stacks up to cap, refreshes oldest at cap
* Multi-dot poison uses separate poison_dots list so single-dot poison_active is untouched
* collect_dot_ticks updated with is_player flag; processes poison_dots for extra ticks
* equip_item() and unequip_item() added — proper equip routing replaces direct assignment
* Goblin Archer added to loot table (Paralyzing Arrow)
* Dire Wolf Pup added to loot table (Dire Wolf Pelt)

⚙️Version Journey To Winter Haven version v4.16 (Journey_To_Winter_Haven_v_04_16.py)
* player_basic_attack() split into weapon vs accessory modes via use_accessory parameter
* use_accessory=True: basic roll + elemental effect, no weapon bonus or procs
* use_accessory=False: weapon bonus + procs, no elemental
* Combat menu now routes weapon and accessory attacks through correct mode

⚙️Version Journey To Winter Haven version v4.15 (Journey_To_Winter_Haven_v_04_15.py)
* round_num parameter added to battle(), battle_inner(), make_loot(), and roll_rarity()
* Round 1 loot odds updated — better chance of normal/uncommon on first round
* monster_level_for_round() added — stronger variants appear in later rounds

⚙️Version Journey To Winter Haven version v4.14 (Journey_To_Winter_Haven_v_04_14.py)
* Wolf Pup loot table entry added (Wolf Pelt — armor)
* Brittle Skeleton loot table entry added (Rusted Sword — weapon)
* Imp loot table entry added (Imp Trident — weapon with proc chance)
* Young Goblin loot table entry added (Goblin Dagger — weapon with blind chance)
* proc_chance and blind_chance added as Equipment parameters

⚙️Version Journey To Winter Haven version v4.12–v4.13 (Journey_To_Winter_Haven_v_04_12/13.py)
* Equipment class introduced — weapons, armor, and accessories with rarity scaling
* make_loot() and roll_rarity() added — first loot drop system
* Green Slime, Red Slime, and Hydra Hatchling loot table entries added (Poison Sac, Fire Sac, Acid Sac)
* element_restore added to Equipment for timed DEF recovery on acid items
* POISON_SAC_STATS, FIRE_SAC_STATS, ACID_SAC_STATS stat tables added

⚙️Version Journey To Winter Haven version v4.11 (Journey_To_Winter_Haven_v_04_11.py)
* battle() and battle_inner() fully separated — battle() is the wrapper, battle_inner() owns the loop
* collect_dot_ticks() extracted as a standalone function
* player_basic_attack() extracted as a standalone function
* Codebase restructured in preparation for the loot system

⚙️Version Journey To Winter Haven version v4.23 (Journey_To_Winter_Haven_v_04_23.py)
* Removed unused `from ast import If` import
* Declared ALLOW_MONSTER_SELECT = False at module level (was undeclared global, potential NameError)
* burn_cream potion now clears hero.burns list in addition to fire_stacks (burn DoT was continuing after potion use)
* level_up() jackpot loop now uses range(num_p1_rolls) instead of hardcoded range(2) — 3rd buff now actually awarded
* weight_to_tier() has fallback return 1 for unknown weight values (was returning None silently)
* Debug menu option 16 now displays "16)" correctly (was missing closing paren in label)
* First duplicate simple_trainer_reaction() removed (second/correct version kept near trainer_stat_point_scene)
* Weapon Core loot split into two forms: Defensive (+3atk/+2def scaling) and Offensive (+4atk/+1def scaling)
* Player now chooses Weapon Core form immediately on drop via _make_weapon_core() menu
* Chimera Scale equip now routes through equip_item() — previous direct assignment skipped unequip of existing armor
* turns_survived tracking kept inside warrior_turn block (turn_count only increments on player turns — chimera divine intervention threshold unchanged)
* Dead xp_reward calls removed from arena_battle() after win/normal-round (XP already awarded inside battle_inner)
* Partial status clears at end of battle_inner victories replaced with reset_between_rounds() — acid/paralyze/bleed now also clear correctly between rounds
* MONSTER_TYPES weight comment corrected — weight value equals tier number directly

⚙️Version Journey To Winter Haven version v4.22 (Journey_To_Winter_Haven_v_04_22.py)
* Fixed Equipment.__init__ crash on goblin archer loot drop — paralyze_chance and paralyze_turns added as proper parameters with defaults of 0.0 and 0
* apply_turn_stop now sets hero.paralyzed = True when reason is "Paralyzed" — bridges turn_stop system with First Aid cure check
* Paralyzed players with First Aid R4+ now get a choice instead of auto-skipping: use First Aid to cure and act, or Struggle to lose the turn and let paralyze fade naturally next turn
* resolve_player_turn_stop updated to support multi-turn paralyze — chain guard gives a breathe turn but decrements remaining turns instead of wiping, enabling chimera-tier 2+ turn lockdowns; non-paralyze stuns retain original wipe behavior
* reset_between_rounds now clears hero.paralyzed and turn_stop_reason — previously a paralyzed player could carry the flag into the next fight's rest period; also added missing turn_stop_reason clear so no ghost reason string persists between rounds
* paralyzing_shot now accepts paralyze_turns parameter (default 1) — goblin archer unchanged, future enemies (chimera) can pass higher values; message now reflects actual turn count
* Added Young_Chimera hidden boss — spawns with one random move from tier 1/2/3 pools plus a unique chimera_elemental_strike; element (fire/poison/acid/paralyze) also rolls on spawn; tier 5 AI fires at 50% per turn
* Added chimera_fight() wrapper — win grants Chimera Plate Chest (legendary armour part 1); loss triggers divine intervention if player survived 5+ turns, otherwise just a defeat; turn count tracked via enemy.turns_survived written each round
* Added tier 5 branch to monster_ai_check — 50% special move chance per turn
* resolve_player_turn_stop rewritten for true consecutive lockdown on multi-turn paralyze — breathe turn only granted after ALL turns expire (Lost->Lost->Free for 2-turn, not Lost->Free->Lost->Free)
* Added post_paralyze_guard flag — blocks enemy from re-paralysing until player has landed one full free attack after paralyze expires; initialized on Warrior, cleared in reset_between_rounds and at start of player's free action
* paralyzing_shot now checks post_paralyze_guard in addition to turn_stop and turn_stop_chain_guard before applying paralyze
* added text version of hidden boss
* nob will now increase one of you ranked skills
* player can now choose to view combat log if the lose and debug menu includes this option
* level up men now allows multiple level gains at once and in debug mode does not restrict how many points you can put into a stat

⚙️Version Journey To Winter Haven version v4.20.3 (journey_4_20_3.py)
* Renamed skill "Heal" to "First Aid" across all menus, prompts, and combat labels
* First Aid max rank reduced from 10 to 5 with matching upgrade costs [1,1,2,3,4]
* Heal percents updated: R1=10%, R2=15%, R3=20%, R4=25%, R5=30%
* First Aid now cures statuses by rank: R2+ clears Blind/Poison, R4+ also clears Paralyze/Burn, R5 also clears Acid
* Death Defier debug option changed from "Activate" to "Grant Skill" — player must manually activate in combat
* Default player name changed from "Adventurer" to "Umbra"
* Fixed gap between HP bar and berserk meter in combat HUD

⚙️Version Journey To Winter Haven version v4.20.2 (journey_4_20_2.py)
* Combat HUD redesigned: two-column layout — name/HP bar on left, AP/bonus/berserk/gear on right
* Death Defier now always shows in HUD when active (was hidden if bonus = 0)
* Combat action menu options now display side by side to keep combat log visible
* arena_quarters_interlude (pre-final-boss rest) now has Inventory & Equipment option
* Both rest periods (rest_phase and arena_quarters_interlude) allow equipping between rounds

⚙️Version Journey To Winter Haven version v4.20.1 (journey_4_20_1.py)
* Added element_max_dots to Equipment class (default 1, rare+=2, legendary=3)
* Sac stat tables updated: rare=4 turns, epic=5 turns, legendary=6 turns for all sacs
* Poison/Fire/Acid application now respects max_dots — stacks up to cap, then resets oldest
* Multi-dot poison uses separate poison_dots list (independent of poison_active)
* collect_dot_ticks now processes poison_dots list for extra poison ticks
* Elem tags now show stack count: e.g. "Burn stack 2/2! (4 dmg, 4 turns)"
* stat_lines() shows max dots on element line for rare+ sacs
* short_label() now prints each stat on its own line for clean readability

⚙️Version Journey To Winter Haven version v0.5.2 (journey_4_19_2.py)
* Extended rarity ladder: poor → normal → uncommon → rare → epic → legendary
* All 9 item stat tables now have entries for all 6 rarities
* RARITY_ORDER list added as single source of truth for rarity sequence
* roll_rarity unchanged — rare/epic/legendary not on natural drop table yet
* Debug Give Loot menu now shows all 6 rarities with color icons
* Rarity icons updated in stat_lines() and short_label() for new tiers

⚙️Version Journey To Winter Haven version v0.5.1 (journey_4_19_1.py)
* Rebuilt show_game_stats to stacked layout — hero row then enemy row
* Removed side-by-side layout which broke on 65-char phone width
* Removed hardcoded name truncation [:10] and [:16] — full names now used
* wrap() applied to both HP rows so long monster names never spill past WIDTH
* Gear lines now print one per row with wrap() — rarity names fit cleanly
* Separator changed from === to ─── to visually distinguish HUD from content

⚙️Version Journey To Winter Haven version v0.5 (journey_4_19.py)
* Rebuilt combat menu to use dynamic slot numbers
* Accessory-only: option 1 is Attack (Accessory Name), Special shifts to 2
* Both equipped: 1) Weapon Attack  2) Accessory Attack (name shown)  3) Special ...
* Rarity word now appears in item names (Poor Fire Sac, Uncommon Wolf Pelt, etc.)
* Player sac DoTs now use sac stats directly, not monster move values
* Poison Sac: flat damage and turns from sac stats, reapply resets timer (no stacking)
* Fire Sac: flat damage per tick from sac stats, single stack, reapply resets timer
* Acid Sac: flat damage tick, single stack, defence restores after element_restore turns
* Monster burn/acid ticks unchanged (still random, still use AP-gated move logic)

⚙️Version Journey To Winter Haven version v0.4
* added hydra hatchling and its move
* expanded debug menu with new acid based modifiers
* added acid tick damage
* set hard level cap to 5
* added an animated xp bar
* fixed potion bag so it only counts as players turn when potion used
* expanded potion dictianry super, mega, and full potion, and ap potion
* Adgusted parts od the story
* Allow for monster to gain levels
* Adjusted player and monster UI
* Restriked player to 1 point in each stat per level till level 5
* player now get minumal additonal boost with leveling 
* minumil equitment has been aded to game 
* three catergories weapons, armor and accessories
* completed all tier 1 monster loot tables
* adding an incresed change for better loot on round 1
* monster drop rate increases if you fight stronger verison of them

(based on everything we’ve built together in the past )
¤ we switched to executable. Game now has become Journey To Winter Haven
⚙️Version Journey To Winter Haven version v0.3 
* Took combat from 4 to 5 rounds
* added a rest period for full heal and future plot points and game mechanics in between 4th and 5th rounds of combat
* Fixed burn move for fire slime
* expanded berserk to two turn and an addition turn if a creature is killed while in berserk
* adjusted player overheal bar so it dosnt turn completly red when overhealed
* currently the only move that interfears with beserk is paralize
* fixed some other minor bugs
* added a breif scene where player is awarded with stat point and skill point by arena trainer before tournament begins
* added flags to arena entry points to allow for unique chats with arena trainer
* added skill points
* added player lvl 1 moves that are unlocked by trainer
* added a rank system evry move goes to 5 currently and takes increased skill point to level it up
* power strike rank system is functinal
* stat points spend on ap increase max ap by 1 and also allow for player to recover 1 additonal ap
* combined stats and skill points into a new menu
* game now check if stat/skill points are available and if not asks player if they are ready to continue
* fixed beserk and burn again
* added cast down feature if ranked ap cost is more than player currently has
* added special move heal
* expanded debug menu to include all current and eventually futire moves
* added special move war cry to players skills
* set up the ground work for a future system where beserk damage and adrenaline damage can be expanded
* fixed power strike. It was op using beserk to bump its damage way to high
* fixed combat log so everything is clearly defined
* wraped combat breakdownbecause it got to long 

⚙️Version Journey To Winter Haven version v0.2 
* we incorperated the tier combat system with weightsa to restrick fights so hopefull player isnt overwhelemed
*player now fights through 4 rounds of combat to win
*victory is now tied to beating fallen not essences.
*fixed mistyping ended game early.
* Completed tier 2 monster line up and ther moves (dire wolf pup, javelina, goblin archer, noob ghost)

⚙️Version journey to winter haven v0.1 did some minor ui fixes

⚙️Version .14 added new titles and endings
    * Hopefully corrected river path
    * fixed some possible future bugs
    * finished all curent tier 1 monster moves(imp, wolf_pup, brittle_skelton, green slime,young goblin)
    * added debug levle up menu
    * added wolf pup rider special move blind charge
    * added javalina and goblin archer and there moves
    * added a check so turn takers dont trigger twice in a row.
    * arena now will intervene if move stoper are triggered twice in a row

⚙️ Version .13 building special moves for monsters
    * added and stabalised blind
    * added new player move dealth defier
    * Updated potion system and added new types
    * added over heal
    * turned ap into a refreshable resourse
    * finally stabilised burn dot
    * added debug menu that could be easily expanded
    * added monster universal select m during combat or monster in story
    * Extended search for torch story mode


version.12 added rest mechanice inbetween rounds of combat
    * fine tuned rage mechanic
    * created beserk mode for rage mechanic
    * tried to clear every bug
    * made story text look better
    * created rest mechanic
    

⚙️ Version .111 

Major Features Added

Rage System (complete)

HP-based rage tiers at 75%, 50%, 25%, 10%

Tier-based extra damage

Level-up stat “Rage” permanently increases rage bonus

Rage flavor messages added, triggered only once per tier

Attack roll updated to exclude permanent rage (now applied through get_rage_bonus)

Developer Shortcuts (global)

q — restart entire game from anywhere

c or combat — jump straight to arena

Implemented via RestartException, QuickCombatException, and global GAME_WARRIOR

Defense System Rewrite (finalized)

Full block flavor text

Partial block flavor text

Defense-break system for Fallen Warrior using defence_break=True

Global Fixes

GAME_WARRIOR global reference created

Removed need to pass warrior through every check()

Fixed many incorrect warrior references

Fixed Fallen Warrior attack override

Added emoji-enhanced stat screen

Textwrap unified with new safe wrap() function

Fixed multiple crash bugs from missing args in check() and intro_story_inner

🛡️ Version .10 — Defense System Overhaul

Defense now actually reduces damage

apply_defence() system created

Added full block / partial block mechanics

Introduced flavor text system for blocks

Fixed bug where defense could go negative

Added Fallen Hero/Fallen Warrior defense-breaking attack

Fixed original_defence restoration after battle

⚔️ Version .09 — Combat Stability Pass

Fixed double damage print bug

Fixed NoneType attacker in defensive messages

Fixed incorrect alternating turn logic

Fixed runaway bloodlust stacking bug

Adjusted monster weights so Fallen Hero appears less often

Cleaned up battle loop structure

Improved story text formatting

Fixed level-up not triggering in older builds

Added strict alternation between warrior/enemy turns

📘 Version .08 — Story System Improvements

Most story segments wrapped with wrap()

Reformatted intro story spacing and structure

Unified input check() system

Cleaned up several deep nested if-blocks

Added new story branches (Forest Path, Bo encounter)

Added potion reward for bravery

Added persuasion check mechanic

Gameplay flow from story → arena stabilized

💀 Version .07 — Fallen Hero Path sorta more like brainstormed about it

Added consequences: stat point or gold

Added Fallen Hero’s defense-break special

Added essences to victory conditions

Tournament victory requires 3 essences

🧪 Version .06 — Monster & Essence System

Monster essence system created

Inventory for loot items

Wolf Rider now drops pelt + dual essence

Unified monster class with proper XP/gold/essence fields

Random encounter system weighted via random.choices

🧱 Version .05 — Leveling System

Added XP thresholds

xp_to_lvl scales ×1.75

Level-up bonus menu

Added AP, Defense, HP, ATK upgrades

Added achievements and titles

Added full stat display (show_all_game_stats)

⚗️ Version .04 — Potion System Rework

Added healing, AP, and mana potions

Simplified potion selection menu

Added inventory management

Added potion reward in story branches

👊 Version .03 — Combat Improvements

Refactored base classes (Creator, Monster, Hero)

Standardized attack rolls

Created battle() and battle_inner() separation

Added run-away consequences and death messages

Fixed duplicated damage printing in several places

📜 Version .02 — Story Prototype

First draft of intro story

Cave encounter

Beastman introduction

Forked paths (run/submit/escape)

Basic arena structure established

🌱 Version .01 — Original Build

Warrior class created

Basic monster classes

Barebones attack loop

Basic HP, XP, gold, inventory

Text only, no story branching

⚙️ Proto-builds — August–October 2025 (Pre-version files)

battle_simulater_pc_update_August62025.py (590 lines)
* Earliest surviving build — where it all started
* Creator base class exists but Skeleton is just pass
* Combat is standalone functions: slime_battle(), skelton_battle(), ghost_battle()
* Global variables track gold, HP, and essence — no class-based state yet
* Comments throughout show active OOP learning in progress
* Slime was famously broken for a very long time
* endings and monster_essence already present as globals — some things never change

arena_battler_sept_17_2025.py (763 lines)
* clear_screen(), continue_text(), and check() introduced — still in the game today
* main() function wraps the game loop for the first time
* Tournament intro story text appears — the premise, memory wipe, and freedom
* Gold and essence tracking via globals, textwrap used for the first time

arena_battler_October_2_2025.py (763 lines)
* Stable checkpoint — near-identical to September build
* Saved before the bigger architecture push that followed'''

