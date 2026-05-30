import textwrap
import os
import random
import time
import math

from colorama import init
# ===============================
# TITLE SYSTEM  (see titles.py)
# ===============================
from titles import (
    TITLE_DISPLAY,
    award_title,
    award_title_with_buff,
    check_jack_of_all_trades,
    check_breadth_titles,
    check_true_jack_of_all_trades,
    check_skill_mastery,
    switch_title_menu,
)

# Local modules
from combat_log import COMBAT_LOG, log, log_attack, log_dot, log_battle_summary, reset_battle_stats, reset_run_stats, show_run_score, view_combat_log, get_run_stats
from gold import calculate_gold_reward, display_gold_earned, award_pending_gold, bookie_encounter, display_run_score, award_gold
from score import record_fight_score
from leaderboard import display_at_end_of_run, show_leaderboard

# Shared constants, utilities and base classes (version-independent)
from shared import (
    WIDTH,
    SPECIAL_MOVE_NAMES,
    DEFENCE_BREAK_STATS,
    wrap, space, clear_screen, continue_text, show_health,
    hp_bar,
    weak_defensive_block, solid_defensive_block,
    strong_defensive_block, full_defensive_block,
    lvl_bonus, ap_from_hp, scaled_xp_step,
    monster_math_breakdown, monster_deal_damage,
    get_ap_inflation, inflated_ap_cost,
    apply_turn_stop, try_death_defier,
    RestartException, QuickCombatException, GameOverException,
    Equipment, Creator, Monster,
)



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

    # v0.6.21: monster-select moved behind the '!' prefix to match the
    # v0.6.19 dev-shortcut convention. Previously bare 'm' / 'monster'
    # would force-start a battle from inside input() — a fat-finger at
    # any of the ~200 input() prompts (yes/no, Press-Enter pauses, etc.)
    # would yank the player into a debug fight. Now we emit the existing
    # __MONSTER_SELECT__ sentinel instead of calling battle() directly,
    # so handle_monster_select_shortcut() decides combat-aware behaviour
    # (swap enemy mid-fight vs. start a debug fight out of combat). Callers
    # that don't check the sentinel just see a harmless non-empty string.
    if cleaned in ("!m", "!monster"):
        return "__MONSTER_SELECT__"

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
                             extra_parts=None, tag=None, ignore_defence=False):
    """
    Prints one clear line that includes:
      - Physical impact (roll -> actual)
      - Blocked amount (from the physical roll) — suppressed if ignore_defence=True
      - Extra/true damage parts (poison/fire/acid/etc.) that bypass defence
      - Total immediate damage

    extra_parts: list of tuples like [("Poison", 2), ("Fire", 3)]
    ignore_defence: set True for moves that bypass defence entirely (e.g. Primordial Surge)
    """
    extra_parts = extra_parts or []

    blocked = 0 if ignore_defence else max(0, int(raw_roll) - int(actual_physical))
    extra_total = sum(int(x) for _, x in extra_parts)
    total = int(actual_physical) + extra_total

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
        # Passive — Chimera Carapace: reduce player raw ATK by 20% base (35% if Flayed draw)
        reduction = getattr(defender, "chimera_atk_reduction", 0.0)
        if reduction:
            raw_roll = max(1, int(raw_roll * (1.0 - reduction)))
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

    # 6) Flayed One charge tick — fills on actual damage through defence
    if actual_physical > 0 and hasattr(attacker, "flayed_charges"):
        _flayed_charge_tick(attacker, defender, actual_physical)

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
        # v0.6.14: fatigue_def_loss now also reduces effective DEF here so acid
        # ticks see the same fully-drained DEF the player feels in combat.
        acid_loss    = getattr(hero, "acid_defence_loss", 0)
        fatigue_loss = getattr(hero, "fatigue_def_loss", 0)
        effective_def = max(0, hero.defence - acid_loss - fatigue_loss)

        for idx, stack in enumerate(acid_stacks, start=1):
            if stack.get("skip", False):
                stack["skip"] = False
                new_acid.append(stack)
                continue

            # Flat tick (player sac) vs random tick (monster acid)
            if stack.get("flat", False):
                tick = int(stack.get("bonus", acid_loss))
            else:
                # v0.6.14: hardened (non-chimera) Hydra Hatchling rolls a softer
                # 2-4 bracket. Standard hydras still hit 3-5. Chimera ignores
                # the hardened flag entirely (it has its own x2 multiplier path).
                if stack.get("hardened", False):
                    base_tick = random.randint(2, 4)
                else:
                    base_tick = random.randint(3, 5) if effective_def == 0 else random.randint(3, 5)
                multiplier = stack.get("multiplier", 1)
                tick = base_tick * multiplier

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
    # BLEED (variable dmg/turn, ignores defence, no stacking)
    # ==========================
    bleed = getattr(hero, "bleed_turns", 0)
    if bleed > 0:
        if getattr(hero, "bleed_skip", False):
            hero.bleed_skip = False   # first tick: skip damage, activate next turn
        else:
            dmg_min  = getattr(hero, "bleed_dmg_min", 2)
            dmg_max  = getattr(hero, "bleed_dmg_max", dmg_min)
            bleed_dmg = random.randint(dmg_min, dmg_max) if dmg_max > dmg_min else dmg_min
            parts.append(("Bleed", bleed_dmg))
            total += bleed_dmg
            hero.bleed_turns -= 1
            if hero.bleed_turns <= 0:
                if is_player:
                    fade_msgs.append("🩸 Your wound stops bleeding.")
                else:
                    fade_msgs.append(f"🩸 {hero.name}'s wound stops bleeding.")

    # ==========================
    # WARRIOR BLEED DOTS (Goblin Warrior Savage Slash — variable dmg, multi-stack)
    # ==========================
    warrior_bleed_dots = getattr(hero, "warrior_bleed_dots", [])
    if warrior_bleed_dots:
        new_wbdots = []
        for idx, dot in enumerate(warrior_bleed_dots, start=1):
            if dot.get("skip", False):
                dot["skip"] = False
                new_wbdots.append(dot)
                continue
            tick = random.randint(dot.get("dmg_min", 3), dot.get("dmg_max", 5))
            tick = max(1, tick)
            parts.append((f"Savage Bleed {idx}", tick))
            total += tick
            dot["turns_left"] -= 1
            if dot["turns_left"] > 0:
                new_wbdots.append(dot)
        hero.warrior_bleed_dots = new_wbdots
        if not new_wbdots and warrior_bleed_dots:
            if is_player:
                fade_msgs.append("🩸 The savage wounds stop bleeding.")
            else:
                fade_msgs.append(f"🩸 {hero.name}'s savage wounds stop bleeding.")

    # ==========================
    # PSYCHIC DEBUFF COUNTDOWN
    # (not a damage DoT — counts down duration, handles skip, clears on expiry)
    # ==========================
    if getattr(hero, "psychic_debuff_turns", 0) > 0:
        if getattr(hero, "psychic_debuff_skip", False):
            # First tick: activate the debuff now (it was applied last enemy turn)
            hero.psychic_debuff_skip = False
            _apply_psychic_debuff_to_stats(hero)
            pct = int(getattr(hero, "psychic_atk_debuff", 0) * 100)
            if is_player:
                fade_msgs.append(f"🧠 Psychic Shred takes hold — your ATK and DEF are reduced by {pct}%!")
        else:
            hero.psychic_debuff_turns -= 1
            if hero.psychic_debuff_turns <= 0:
                _clear_psychic_debuff(hero)
                if is_player:
                    fade_msgs.append("🧠 The psychic haze lifts — your ATK and DEF return to normal.")
                else:
                    fade_msgs.append(f"🧠 The psychic haze lifts from {hero.name}.")

    # ==========================
    # PSYCHIC DROWN COUNTDOWN
    # (AP inflation — not a damage DoT, just counts down and clears on expiry)
    # ==========================
    if getattr(hero, "drown_turns", 0) > 0:
        hero.drown_turns -= 1
        if hero.drown_turns <= 0:
            _clear_psychic_drown(hero)
            if is_player:
                fade_msgs.append("💧 The phantom drowning fades — your lungs clear and AP costs return to normal.")
            else:
                fade_msgs.append(f"💧 The drowning effect fades from {hero.name}.")

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
# WIDTH imported from shared.py

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

def _try_dev_shortcut(raw):
    """
    Centralized developer-shortcut handler. Used by both continue_text() and
    check() so dev shortcuts behave identically at every story prompt.

    v0.6.19: All dev shortcuts now require a '!' prefix so they can never be
    triggered by accident from menu input. Bare single letters like 'c' and
    'q' were one fat-finger away from nuking interlude state on a touchscreen.

    Recognized shortcuts:
      '!q' / '!quit'      → raise RestartException (restarts the intro story)
      '!c' / '!combat'    → raise QuickCombatException (jumps to arena_battle)
      '!debug'            → open the debug menu, then return to the prompt
      '!m' / '!monster'   → the global input() override converts these into the
                            __MONSTER_SELECT__ sentinel; this helper does NOT
                            re-handle them. The caller is responsible for the
                            sentinel via handle_monster_select_shortcut().
                            (v0.6.21: moved behind '!' — previously bare 'm' /
                            'monster' force-started a battle from inside input(),
                            which a fat-finger could trigger at any prompt.)

    Returns:
      True  → shortcut was recognized and handled. Caller should `continue`
              its prompt loop (the user is back at the same prompt).
      False → input was not a dev shortcut. Caller proceeds with normal logic.

    Note on '!q' and '!c': these RAISE exceptions instead of returning. The
    exceptions are caught by intro_story() (RestartException → restart,
    QuickCombatException → arena_battle). Do not call this helper from
    inside arena combat — !c/!combat would raise during a fight.

    Adding a new shortcut? Add it here once and it works at every story
    prompt. Don't sprinkle handlers into individual functions.
    """
    global GAME_WARRIOR

    # Only string inputs can be shortcuts; sentinel tuples bypass.
    if not isinstance(raw, str):
        return False

    cleaned = raw.strip().lower()

    # All dev shortcuts require '!' prefix (v0.6.19 safety change).
    # Bail fast on anything else so menu input isn't checked against
    # the shortcut list.
    if not cleaned.startswith("!"):
        return False

    # Restart the intro
    if cleaned in ("!q", "!quit"):
        raise RestartException

    # Quick-combat jump — straight to the arena
    if cleaned in ("!c", "!combat"):
        if GAME_WARRIOR is None:
            print(wrap("⚔️ Cannot start combat yet — no warrior exists."))
            return True
        # Sanitize warrior before jumping — the shortcut can fire before
        # the intro sets a name or story flags
        if not GAME_WARRIOR.name or GAME_WARRIOR.name.strip().lower() == "warrior":
            GAME_WARRIOR.name = "Debug Warrior"
        raise QuickCombatException

    # Debug menu — opens, then returns control to the prompt loop
    if cleaned == "!debug":
        if GAME_WARRIOR:
            debug_menu(GAME_WARRIOR)
        else:
            print("Debug unavailable — warrior not created yet.")
        return True

    # Started with '!' but wasn't a known shortcut — let the player know
    # rather than silently ignoring.
    print(f"Unknown dev shortcut: {raw}")
    print("Available: !debug, !combat (or !c), !quit (or !q)")
    return True


def continue_text():
    """
    Story continue prompt.

    - ENTER               = continue story
    - '!m' / '!monster'   = developer monster select (sentinel from input override)
    - '!q' / '!quit'      = restart intro
    - '!c' / '!combat'    = jump to arena
    - '!debug'            = open debug menu

    v0.6.21: all dev shortcuts (including monster select) require the '!'
    prefix. Bare letters were one fat-finger from triggering on a touchscreen.
    Dev shortcuts route through _try_dev_shortcut(); monster select routes
    through handle_monster_select_shortcut() (which reads the sentinel).
    """
    global GAME_WARRIOR

    while True:
        raw = input("\n(Press ENTER to continue)\n> ")

        # Story-mode monster select (sentinel from input override)
        handled, _ = handle_monster_select_shortcut(
            raw,
            warrior=GAME_WARRIOR,
            in_combat=False
        )
        if handled:
            continue

        # All other dev shortcuts (q / c / combat / debug)
        if _try_dev_shortcut(raw):
            continue

        # Normal ENTER → continue story
        if isinstance(raw, str) and raw.strip() == "":
            return

        print("Just press ENTER to continue.")


def check(prompt, options=None):
    """
    Story-mode input handler.

    - '!m' / '!monster' → open monster select (debug dev battle)
    - 'm' / 'monster'   → treated as normal text (safe for names and story options)
    - normal choices validated against 'options'
    - dev shortcuts (via _try_dev_shortcut), all '!'-prefixed (v0.6.21):
        !q / !quit    → restart intro
        !c / !combat  → jump to arena
        !debug        → open debug menu
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
        # Developer shortcuts (q / c / combat / debug) — shared helper
        # ----------------------------------------------------
        if _try_dev_shortcut(raw):
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
    - Bypasses the overridden input() so 'm' / 'monster' debug inputs are ignored.
    - Returns the entered name, or 'Umbra' if the player hits ENTER on an empty prompt.
    """
    raw = _real_input(prompt)
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned != "":
            return cleaned  # valid name entered
    return "Umbra"  # default if empty / non-string

        


def intro_story(warrior):
    """
    Wrapper for the intro story.
    This catches developer shortcut exceptions and cleanly restarts or
    jumps into combat.

    On RestartException ('q' shortcut), we replace GAME_WARRIOR with a
    completely fresh Warrior() — same as the entry path in __main__.
    Without this reset, leftover state from the previous run (the
    player's chosen name, potions, story flags, HP/level, etc.) would
    leak into the "restarted" intro: the framing scene's name gate
    `if GAME_WARRIOR.name == "warrior"` would fail, the prologue would
    skip the name prompt entirely, and the player would land mid-story
    with stale inventory. Fresh warrior == fresh start.
    """
    global GAME_WARRIOR
    try:
        return intro_story_inner(warrior)
    except RestartException:
        clear_screen()
        print(wrap("🔄 Restarting game..."))
        # Full reset — wipe the warrior so the framing/name prompt fires again
        GAME_WARRIOR = Warrior()
        COMBAT_LOG.clear()
        return intro_story(GAME_WARRIOR)
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





# ---------------------------------------------------------------
# CHARGED JAGGED ROCK — pool-based psychic charge system
# ---------------------------------------------------------------

# Tier thresholds: every 10 pool points = 1 charge = +1 ATK
_CJR_POOL_PER_CHARGE = 1.0

# Rarity color icons for the charge bar (matches RARITY_ICONS)
_CJR_TIER_ICONS = {
    1: "⬜",   # poor
    2: "🟦",   # normal
    3: "🟩",   # uncommon
    4: "🟨",   # rare
    5: "🟪",   # epic
    6: "🟥",   # legendary
    7: "🟧",   # mythril
}

def _cjr_rock(warrior):
    """Return the equipped Charged Jagged Rock trinket, or None."""
    t = warrior.equipment.get("trinket")
    if t and getattr(t, "name", "") == "Charged Jagged Rock":
        return t
    return None


def _cjr_absorb(warrior, enemy, actual_damage):
    """
    Called whenever the player deals damage through defence.
    Pool gains actual_damage * fill_rate (minimum 0.10 per hit).
    Each full 10-point charge: player +1 ATK, enemy -1 ATK/-1 DEF.
    Returns True if the charge count changed (triggers bar display).
    """
    rock = _cjr_rock(warrior)
    if not rock:
        return False

    fill_rate  = getattr(rock, "fill_rate", 0.10)
    max_ch     = getattr(rock, "max_charges", 3)
    pool_cap   = max_ch * _CJR_POOL_PER_CHARGE

    old_pool    = getattr(warrior, "cjr_pool", 0.0)
    gain        = max(0.10, actual_damage * fill_rate)
    new_pool    = min(old_pool + gain, pool_cap)
    warrior.cjr_pool = new_pool

    old_charges = int(old_pool // _CJR_POOL_PER_CHARGE)
    new_charges = int(new_pool // _CJR_POOL_PER_CHARGE)
    warrior.cjr_charges = new_charges

    _cjr_sync_atk(warrior, new_charges)

    # Apply per-charge enemy debuff (rarity-based ATK/DEF drain per charge)
    if new_charges != old_charges and enemy is not None and enemy.is_alive():
        atk_drain = getattr(rock, "enemy_atk_drain", 1)
        def_drain = getattr(rock, "enemy_def_drain", 1)
        _cjr_apply_enemy_debuff(enemy, new_charges, atk_drain, def_drain)

    return new_charges != old_charges


def _cjr_sync_atk(warrior, charges):
    """Apply base_atk + charges ATK bonus on top of the warrior's pre-equip ATK."""
    rock = _cjr_rock(warrior)
    if not rock:
        return
    base_atk = getattr(rock, "base_atk", 0)
    base_min = getattr(warrior, "cjr_base_min_atk", warrior.min_atk)
    base_max = getattr(warrior, "cjr_base_max_atk", warrior.max_atk)
    warrior.min_atk = base_min + base_atk + charges
    warrior.max_atk = base_max + base_atk + charges


def _cjr_apply_enemy_debuff(enemy, charges, atk_drain=1, def_drain=1):
    """
    Apply cumulative ATK/DEF drain per charge to the current enemy.
    Drain amounts are rarity-based (from rock.enemy_atk_drain / enemy_def_drain).
    Recalculates from base each time. ATK floor 1, DEF floor 0.
    """
    if not hasattr(enemy, "cjr_base_min_atk"):
        enemy.cjr_base_min_atk = enemy.min_atk
        enemy.cjr_base_max_atk = enemy.max_atk
        enemy.cjr_base_defence = enemy.defence

    new_min = max(1, enemy.cjr_base_min_atk - (charges * atk_drain))
    new_max = max(1, enemy.cjr_base_max_atk - (charges * atk_drain))
    new_def = max(0, enemy.cjr_base_defence  - (charges * def_drain))

    enemy.min_atk = new_min
    enemy.max_atk = new_max
    enemy.defence = new_def

    print(wrap(
        f"⚡ The stone pulses! {enemy.display_name} weakens — "
        f"ATK {enemy.cjr_base_max_atk}→{new_max}  DEF {enemy.cjr_base_defence}→{new_def}"
    ))


def _flayed_charge_tick(enemy, warrior, actual_damage):
    """
    Called whenever Flayed One deals damage that gets through defence.
    Pool gains actual_damage * 0.25 (min 0.25). Each full charge:
      Flayed One +1 ATK, player -1 ATK/-1 DEF. Cap 5.
    """
    if not hasattr(enemy, "flayed_charges"):
        return  # not a Flayed One

    fill_rate  = getattr(enemy, "flayed_fill_rate",   0.25)
    max_ch     = getattr(enemy, "flayed_max_charges",  5)
    pool_cap   = max_ch * _CJR_POOL_PER_CHARGE

    old_pool    = getattr(enemy, "flayed_pool", 10.0)
    gain        = max(0.25, actual_damage * fill_rate)
    new_pool    = min(old_pool + gain, pool_cap)
    enemy.flayed_pool = new_pool

    old_charges = int(old_pool // _CJR_POOL_PER_CHARGE)
    new_charges = int(new_pool // _CJR_POOL_PER_CHARGE)
    enemy.flayed_charges = new_charges

    # Flayed ATK scales with charges
    if not hasattr(enemy, "flayed_base_min_atk"):
        enemy.flayed_base_min_atk = enemy.min_atk
        enemy.flayed_base_max_atk = enemy.max_atk
    enemy.min_atk = enemy.flayed_base_min_atk + new_charges
    enemy.max_atk = enemy.flayed_base_max_atk + new_charges

    if new_charges != old_charges:
        _flayed_apply_player_debuff(enemy, warrior, new_charges)
        print(wrap(
            f"🧠 {enemy.display_name} grows stronger! Charge {new_charges}/{max_ch} — "
            f"ATK now {enemy.min_atk}–{enemy.max_atk}"
        ))


def _flayed_apply_player_debuff(enemy, warrior, charges):
    """
    Apply cumulative -1 ATK / -1 DEF per flayed charge to the player.
    Recalculates from base each time. ATK floor 1, DEF floor 0.
    """
    if not hasattr(warrior, "flayed_base_min_atk"):
        warrior.flayed_base_min_atk = warrior.min_atk
        warrior.flayed_base_max_atk = warrior.max_atk
        warrior.flayed_base_defence = warrior.defence

    new_min = max(1, warrior.flayed_base_min_atk - charges)
    new_max = max(1, warrior.flayed_base_max_atk - charges)
    new_def = max(0, warrior.flayed_base_defence  - charges)

    warrior.min_atk = new_min
    warrior.max_atk = new_max
    warrior.defence = new_def

    print(wrap(
        f"🧠 The psychic torment intensifies! Your ATK and DEF weaken — "
        f"ATK {warrior.flayed_base_max_atk}→{new_max}  DEF {warrior.flayed_base_defence}→{new_def}"
    ))


def cjr_bar(warrior):
    """
    Return a one-line charge bar string for the Charged Jagged Rock.
    Example:  ⬜🟦🟦░░  +2 ATK  (pool 23.4/50)
    """
    rock = _cjr_rock(warrior)
    if not rock:
        return ""
    pool       = getattr(warrior, "cjr_pool", 0.0)
    charges    = getattr(warrior, "cjr_charges", 0)
    max_ch     = getattr(rock, "max_charges", 1)
    pool_cap   = max_ch * _CJR_POOL_PER_CHARGE

    # Build bar: each cell = 1 charge slot
    # Filled cells use the icon for that charge tier, empty use ░
    bar = ""
    for i in range(1, max_ch + 1):
        if i <= charges:
            bar += _CJR_TIER_ICONS.get(i, "🟥")
        else:
            # Partial fill for the currently-filling cell
            if i == charges + 1:
                partial = (pool % _CJR_POOL_PER_CHARGE) / _CJR_POOL_PER_CHARGE
                bar += "▒" if partial > 0.4 else "░"
            else:
                bar += "░"

    atk_str = f"+{charges} ATK" if charges > 0 else "no bonus yet"
    return f"  ⚡ Stone [{bar}] {atk_str}  (pool {pool:.1f}/{pool_cap:.0f})"


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

def apply_dual_wield_modifier(hero):
    """
    v0.6.18: Recalculate the dual-wield damage modifier on the warrior.

    When the player has two non-shield weapons equipped (one in main_hand,
    one in off_hand), the OFF-HAND weapon's contribution to ATK should be
    halved (rounded down). The full equip math at equip-time adds both
    weapons' full atk_min/atk_max to hero.min_atk/max_atk — this function
    subtracts the half that shouldn't be there, and adds the Dual Wielder
    title's +1/+1 ATK bonus if the player has earned the title.

    The full off-hand damage (no halving) is gated behind the future
    Dual Wielder skill — placeholder only in v0.6.18.

    Mirrors the pattern used by apply_wolf_set_bonus: stash the currently-
    applied modifier on hero._dual_wield_modifier_applied, un-apply it,
    compute the new modifier from current state, apply it, restash.
    Safe to call repeatedly — idempotent.

    Also awards the Dual Wielder title (once per run) the first time both
    1H weapons are equipped simultaneously.
    """
    main = hero.equipment.get("main_hand")
    off  = hero.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    dual_wielding = _is_weapon(main) and _is_weapon(off)

    # Compute the NEW modifier delta (what needs to be applied right now)
    new_mod = {"atk_min": 0, "atk_max": 0}
    if dual_wielding:
        # Off-hand halving: we want only floor(off.atk_min/2) and floor(off.atk_max/2)
        # to contribute. Current state has full off.atk_min/max already added,
        # so subtract the half that shouldn't be there.
        new_mod["atk_min"] -= (off.atk_min - (off.atk_min // 2))
        new_mod["atk_max"] -= (off.atk_max - (off.atk_max // 2))
        # Dual Wielder title bonus: +1 ATK passive (min and max) while dual-wielding
        if "dual_wielder" in getattr(hero, "titles", set()):
            new_mod["atk_min"] += 1
            new_mod["atk_max"] += 1

    # Remove OLD modifier
    old = getattr(hero, "_dual_wield_modifier_applied", {"atk_min": 0, "atk_max": 0})
    hero.min_atk -= old["atk_min"]
    hero.max_atk -= old["atk_max"]

    # Apply NEW modifier
    hero.min_atk += new_mod["atk_min"]
    hero.max_atk += new_mod["atk_max"]

    # Stash for next call
    hero._dual_wield_modifier_applied = new_mod

    # Award title the first time we observe a dual-wield state
    if dual_wielding and "dual_wielder" not in getattr(hero, "titles", set()):
        if not hasattr(hero, "titles"):
            hero.titles = set()
        hero.titles.add("dual_wielder")
        print()
        print(wrap("  🏅 ACHIEVEMENT UNLOCKED: Dual Wielder", WIDTH))
        print(wrap("     You wield a blade in each hand.", WIDTH))
        print(wrap("     +1 ATK while dual-wielding. Off-hand does half damage.", WIDTH))
        print(wrap("     (+150 end-of-run score)", WIDTH))
        # Re-run with the title now in place so the +1 bonus applies immediately
        apply_dual_wield_modifier(hero)


def equip_item(hero, item):
    """
    Moves an item from inventory into the correct equipment slot.
    If something is already in that slot, swaps it back to inventory.

    Rings are special: item.slot == "ring" but the equipment dict uses
    "finger_1" and "finger_2". If a finger is empty, place there; if
    both are occupied, ask the player which to replace.

    v0.6.19: Returns True on successful equip, False on any cancel/block
    path. Callers handing in a not-yet-bagged item MUST check the return
    and bag the item themselves on False, or the item is silently lost.
    """
    slot = item.slot

    # --- Ring routing: pick which finger ---
    if slot == "ring":
        f1 = hero.equipment.get("finger_1")
        f2 = hero.equipment.get("finger_2")
        if f1 is None:
            slot = "finger_1"
        elif f2 is None:
            slot = "finger_2"
        else:
            # Both fingers occupied — ask which to swap
            print("\nBoth fingers are full:")
            print(f"  1) Finger 1: {f1.short_label()}")
            print(f"  2) Finger 2: {f2.short_label()}")
            print("  0) Cancel")
            pick = input("Replace which? ").strip()
            if pick == "1":
                slot = "finger_1"
            elif pick == "2":
                slot = "finger_2"
            else:
                print("Cancelled.")
                return False

    # --- v0.6.16: Hand routing for weapons and shields ---
    elif slot in ("weapon", "shield"):
        is_two_handed = getattr(item, "two_handed", False)
        h1 = hero.equipment.get("main_hand")
        h2 = hero.equipment.get("off_hand")

        # 2H weapons: unequip BOTH hands first, then take main_hand
        if is_two_handed:
            if h1 is not None or h2 is not None:
                print(wrap(f"\n  {item.name} needs both hands."))
                occupants = []
                if h1: occupants.append(h1.short_label())
                if h2: occupants.append(h2.short_label())
                print(wrap(f"  Will unequip: {', '.join(occupants)}"))
                confirm = input("  Proceed? (y/n): ").strip().lower()
                if confirm != "y":
                    print("Cancelled.")
                    return False
                if h1: unequip_item(hero, h1)
                if h2: unequip_item(hero, h2)
            slot = "main_hand"

        # 1H weapon or shield: pick an empty hand if any, otherwise ask
        else:
            # Block equipping shield/1H if existing weapon is 2H
            for s in ("main_hand", "off_hand"):
                existing = hero.equipment.get(s)
                if existing is not None and getattr(existing, "two_handed", False):
                    print(wrap(f"\n  Can't equip {item.name} — {existing.name} is two-handed."))
                    print(wrap(f"  Unequip {existing.name} first."))
                    return False

            if h1 is None:
                slot = "main_hand"
            elif h2 is None:
                slot = "off_hand"
            else:
                # Both hands full — ask which to swap
                print("\nBoth hands are full:")
                print(f"  1) Main Hand: {h1.short_label()}")
                print(f"  2) Off Hand:  {h2.short_label()}")
                print("  0) Cancel")
                pick = input("Replace which? ").strip()
                if pick == "1":
                    slot = "main_hand"
                elif pick == "2":
                    slot = "off_hand"
                else:
                    print("Cancelled.")
                    return False

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
    if getattr(item, "max_ap_bonus", 0):
        hero.max_ap += item.max_ap_bonus
        hero.ap     = min(hero.ap, hero.max_ap)
    if getattr(item, "max_rage_bonus", 0):
        hero.max_rage += item.max_rage_bonus

    # Charged Jagged Rock: store base ATK and apply base_atk + existing charges on equip
    if getattr(item, "name", "") == "Charged Jagged Rock":
        hero.cjr_base_min_atk = hero.min_atk
        hero.cjr_base_max_atk = hero.max_atk
        base_atk = getattr(item, "base_atk", 0)
        charges  = getattr(hero, "cjr_charges", 0)
        hero.min_atk += base_atk + charges
        hero.max_atk += base_atk + charges
        bonus_str = f"+{base_atk + charges} ATK" if (base_atk + charges) > 0 else "no bonus yet"
        print(wrap(f"⚡ The stone hums with stored energy — {bonus_str} active"))

    # Keep combat damage hook updated. v0.6.16: read via get_weapon().
    weapon = hero.get_weapon()
    hero.equipment_bonus_damage = weapon.atk_min if weapon else 0

    # v0.6.16: recalc ALL crafted set bonuses (Wolf-Hide AND Dire Wolf).
    try:
        from crafter import apply_all_set_bonuses
        apply_all_set_bonuses(hero)
    except ImportError:
        pass

    # v0.6.18: recalc dual-wield damage modifier (off-hand halving + title bonus)
    apply_dual_wield_modifier(hero)

    print(f"\n✅ Equipped: {item.short_label()}")
    return True

def unequip_item(hero, item):
    """
    Removes an item from its equipment slot and puts it back in inventory.
    Reverses all stat bonuses that were applied on equip.

    v0.6.19: For weapons and shields, item.slot is "weapon"/"shield" but the
    equipment dict only has "main_hand"/"off_hand". Resolve to whichever hand
    actually holds this item. Without this, the function wrote to a phantom
    "weapon" key, left the real slot occupied, and silently duplicated the
    item in inventory. Bug surfaced when a tester tried to unequip the
    Walking Staff via the slot menu.
    """
    slot = item.slot

    # --- Ring routing: find which finger actually holds this item ---
    if slot == "ring":
        if hero.equipment.get("finger_1") is item:
            slot = "finger_1"
        elif hero.equipment.get("finger_2") is item:
            slot = "finger_2"
        else:
            print("Ring not currently equipped.")
            return

    # --- v0.6.19: Hand routing for weapons and shields ---
    elif slot in ("weapon", "shield"):
        if hero.equipment.get("main_hand") is item:
            slot = "main_hand"
        elif hero.equipment.get("off_hand") is item:
            slot = "off_hand"
        else:
            print(f"{item.name} not currently equipped.")
            return

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
        hero.hp      = min(hero.hp, hero.max_hp)
        hero.max_overheal = int(hero.max_hp * 1.10)
    if getattr(item, "max_ap_bonus", 0):
        hero.max_ap = max(1, hero.max_ap - item.max_ap_bonus)
        hero.ap     = min(hero.ap, hero.max_ap)
    if getattr(item, "max_rage_bonus", 0):
        hero.max_rage = max(0, hero.max_rage - item.max_rage_bonus)

    # Charged Jagged Rock: strip base_atk + charge-based ATK bonus on unequip
    if getattr(item, "name", "") == "Charged Jagged Rock":
        base_atk = getattr(item, "base_atk", 0)
        charges  = getattr(hero, "cjr_charges", 0)
        hero.min_atk = max(1, hero.min_atk - base_atk - charges)
        hero.max_atk = max(hero.min_atk, hero.max_atk - base_atk - charges)
        # Pool persists — charges restored if re-equipped

    # Reset trinket charges on unequip (only for trinkets that use charges)
    if item.slot == "trinket" and getattr(item, "stone_max_charges", 0) > 0:
        item.stone_charges = 0
        item.stone_deployed = False

    # Keep combat damage hook updated. v0.6.16: read via get_weapon().
    weapon = hero.get_weapon()
    hero.equipment_bonus_damage = weapon.atk_min if weapon else 0

    # v0.6.16: recalc ALL crafted set bonuses (Wolf-Hide AND Dire Wolf).
    try:
        from crafter import apply_all_set_bonuses
        apply_all_set_bonuses(hero)
    except ImportError:
        pass

    # v0.6.18: recalc dual-wield damage modifier (off-hand halving + title bonus)
    apply_dual_wield_modifier(hero)

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
        slot_labels = {
            "main_hand": "Main Hand",
            "off_hand":  "Off Hand",
            "armor":     "Armor",
            "accessory": "Accessory",
            "trinket":   "Trinket",
            "helm":      "Helm",
            "cape":      "Cape",
            "finger_1":  "Finger 1",
            "finger_2":  "Finger 2",
        }
        for slot in ("main_hand", "off_hand", "armor", "helm", "cape", "accessory", "trinket", "finger_1", "finger_2"):
            item = hero.equipment[slot]
            label_name = slot_labels[slot]
            if item:
                label = item.short_label()
                if slot == "trinket" and getattr(item, "stone_max_charges", 0) > 0:
                    label += f"  [{item.stone_charges}/{item.stone_max_charges} charges]"
                print(f"  {label_name:<12} {label}")
            else:
                print(f"  {label_name:<12} (empty)")

        print()

        # --- Unequipped Items ---
        print("── Bag ──")
        if not hero.inventory:
            print("  (nothing)")
        else:
            for i, item in enumerate(hero.inventory, start=1):
                print(f"  {i}) {item.short_label()}")

        print("\n  i<number> — inspect item (e.g. i1)")
        print("  <slot>    — unequip slot (main / off / armor / helm / cape / accessory / trinket / finger1 / finger2)")
        print("  0         — back")

        choice = input("\nEnter item number to equip, slot to unequip, or i# to inspect: ").strip().lower()

        if choice == "0":
            return

        # Map user-facing slot aliases to internal equipment dict keys
        SLOT_ALIASES = {
            # v0.6.18: main_hand / off_hand are the canonical slot names
            "main": "main_hand", "mainhand": "main_hand", "main_hand": "main_hand",
            "off": "off_hand", "offhand": "off_hand", "off_hand": "off_hand",
            # Legacy aliases — keep working so muscle memory doesn't break
            "hand1": "main_hand", "hand2": "off_hand",
            "h1": "main_hand", "h2": "off_hand",
            "weapon": "main_hand",   # legacy alias — typing 'weapon' unequips the weapon hand
            "shield": "off_hand",   # convenience
            "armor": "armor", "accessory": "accessory", "trinket": "trinket",
            "helm": "helm", "cape": "cape",
            "finger1": "finger_1", "finger2": "finger_2",
            "f1": "finger_1", "f2": "finger_2",
        }

        # --- Inspect item ---
        if choice.startswith("i") and choice[1:].isdigit():
            idx = int(choice[1:]) - 1
            if idx < 0 or idx >= len(hero.inventory):
                print("Invalid item number.")
                input("\nPress Enter...")
                continue
            item = hero.inventory[idx]
            clear_screen()
            print(f"\n🔍 Inspecting: {item.name}\n")
            print(item.full_detail())
            input("\nPress Enter...")
            continue

        # --- Inspect equipped slot by typing its name with 'i' prefix ---
        if choice.startswith("i") and choice[1:] in SLOT_ALIASES:
            slot = SLOT_ALIASES[choice[1:]]
            item = hero.equipment[slot]
            if item is None:
                print(f"Nothing equipped in {slot.replace('_', ' ')} slot.")
                input("\nPress Enter...")
            else:
                clear_screen()
                print(f"\n🔍 Inspecting equipped {slot.replace('_', ' ').title()}:\n")
                print(item.full_detail())
                input("\nPress Enter...")
            continue

        # --- Equip from bag ---
        if choice.isdigit():
            idx = int(choice) - 1
            if idx < 0 or idx >= len(hero.inventory):
                print("Invalid choice.")
                input("\nPress Enter...")
                continue
            item = hero.inventory[idx]
            # Show full detail before equipping so player knows what they're putting on
            clear_screen()
            print(f"\n📦 Equipping:\n")
            print(item.full_detail())
            equip_item(hero, item)
            input("\nPress Enter...")

        # --- Unequip by slot name ---
        elif choice in SLOT_ALIASES:
            slot = SLOT_ALIASES[choice]
            item = hero.equipment[slot]
            if item is None:
                print(f"Nothing equipped in {slot.replace('_', ' ')} slot.")
                input("\nPress Enter...")
            else:
                unequip_item(hero, item)
                input("\nPress Enter...")

        else:
            print("Enter a number to equip, i# to inspect, a slot name to unequip, or 0 to go back.")
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
    # If already overhealed, don't reduce HP — just cap at max_hp on the way up
    effective_base = min(hero.hp, hero.max_hp)
    hero.hp = min(hero.max_hp, effective_base + heal_amount)
    actual = hero.hp - old_hp
    if actual > 0:
        print(f"You recover {actual} HP! ({int(percent*100)}% heal)")
    else:
        print(f"You are already at full HP!")

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


def use_potion_menu(hero, in_combat=False):
    clear_screen()
    print("🧪 Potion Bag\n")

    # Bonus action tracker
    bonus_available = not getattr(hero, "bonus_action_used", False)
    if bonus_available:
        print("⚡ Bonus Action: AVAILABLE — first potion this fight is FREE (no turn cost)")
    else:
        print("⚡ Bonus Action: USED — using a potion will cost your turn")
    print()

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

    # Warn if using an HP potion at full health
    hp_potions = ("heal", "super_potion", "mega_potion", "full_potion")
    if potion_type in hp_potions and hero.hp >= hero.max_hp:
        print(wrap("⚠️  You are already at full HP! Use the potion anyway?"))
        confirm = _real_input("(y/n) > ").strip().lower()
        if confirm != "y":
            print("You put the potion away.")
            space()
            return False

    # Consume potion ONCE
    hero.potions[potion_type] -= 1

    # Track bonus action
    is_bonus = not getattr(hero, "bonus_action_used", False)
    if is_bonus:
        hero.bonus_action_used = True


    # ---------- Potion Effects ----------
        
    if potion_type == "heal":       
        heal_percent(hero, 0.25)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "super_potion":  # 50% heal
        heal_percent(hero, 0.50)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return "bonus" if is_bonus else True
    
    elif potion_type == "mega_potion":
        heal_percent(hero, 0.75)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "full_potion":
        heal_percent(hero, 1.00)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "ap":
        recovered = ap_percent(hero, 0.25)
        print(f"\n⚡ You drink an AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "super_ap":
        recovered = ap_percent(hero, 0.50)
        print(f"\n⚡ You drink a Super AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "mega_ap":
        recovered = ap_percent(hero, 0.75)
        print(f"\n⚡ You drink a Mega AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "full_ap":
        recovered = ap_percent(hero, 1.00)
        print(f"\n⚡ You drink a Full AP potion and recover {recovered} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return "bonus" if is_bonus else True
    
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
        return "bonus" if is_bonus else True

    # 🔵 Greater Mana Potion (25%)
    elif potion_type == "greater_mana":
        mana_percent(hero, 0.25)
        print(f"Current MP: {hero.mana}/{hero.max_mana}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

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
        return "bonus" if is_bonus else True


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
        return "bonus" if is_bonus else True

    # 🧪 Cure-All Tonic — clears all physical status effects (NOT psychic)
    # Removes: poison, burn/fire stacks, acid stacks, paralysis, blindness
    # Does NOT remove: psychic charge, turn_stop reasons that aren't paralysis
    elif potion_type == "cure_all":
        cleared = []
        if hero.poison_active:
            hero.poison_active = False
            hero.poison_amount = 0
            hero.poison_turns = 0
            hero.poison_skip_first_tick = False
            cleared.append("poison")
        if hasattr(hero, "fire_stacks") and hero.fire_stacks > 0:
            hero.burns = []
            hero.fire_stacks = 0
            cleared.append("burns")
        if getattr(hero, "acid_stacks", []):
            hero.acid_stacks = []
            cleared.append("acid")
        if getattr(hero, "paralyzed", False):
            hero.paralyzed = False
            # Only clear turn_stop if it was caused by paralysis — leave psychic-source stops alone
            if getattr(hero, "turn_stop_reason", "") == "paralyzed":
                hero.turn_stop = 0
                hero.turn_stop_reason = ""
            cleared.append("paralysis")
        if getattr(hero, "blind_turns", 0) > 0:
            hero.blind_turns = 0
            hero.blind_long = False
            cleared.append("blindness")

        if cleared:
            print(f"\n🧪 The Cure-All burns clean. Cleared: {', '.join(cleared)}.")
        else:
            print("\n🧪 You drink the Cure-All Tonic, but had no afflictions to cure.")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    # ⚗️ Elixir — 50% HP and 50% AP in one potion (premium combo restore)
    elif potion_type == "elixir":
        print("\n⚗️ You drink the Elixir.")
        heal_percent(hero, 0.50)        # prints its own "+N HP" line
        recovered_ap = ap_percent(hero, 0.50)
        print(f"⚡ +{recovered_ap} AP recovered.")
        print(f"Current HP: {hero.hp}/{hero.max_hp}    AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    # 🌿❄️ Frostpine Tonic — Elwyn's gift (40% HP + clear all status + 2 AP)
    elif potion_type == "frostpine_tonic":
        print(wrap(
            "\nYou uncork the small flask. The scent of pine and frost hits you "
            "— it smells like home. You feel your wounds close and your strength return.",
            WIDTH
        ))
        # v0.6.15 BUG FIX: Frostpine was designed (per v0.6.07 patch notes and
        # DEVLOG entry) to fully clear rot BEFORE the 40% heal, so the heal
        # calculates against restored max HP. "Mom's recipe beats the rot every
        # time." This was documented but never actually implemented in the
        # handler. Now it is. Order matters: clear_rot first, then heal_percent.
        clear_rot(hero, restore_hp=False, source="frostpine_tonic")
        heal_percent(hero, 0.40)
        # Clear all status effects
        hero.poison_active = False
        hero.poison_amount = 0
        hero.poison_turns = 0
        hero.poison_skip_first_tick = False
        if hasattr(hero, "fire_stacks"):
            hero.burns = []
            hero.fire_stacks = 0
        hero.acid_stacks = []
        hero.paralyzed = False
        hero.turn_stop = 0
        hero.turn_stop_reason = ""
        hero.blind_turns = 0
        hero.blind_long = False
        # Restore 2 AP
        hero.ap = min(hero.max_ap, hero.ap + 2)
        print(f"🌿 HP restored to {hero.hp}/{hero.max_hp}")
        print(f"❄️  All status effects cleared.")
        print(f"⚡ +2 AP restored. ({hero.ap}/{hero.max_ap})")
        continue_text()
        space()
        return "bonus" if is_bonus else True

    # ============================================================
    # 🌟 PROGRESSION POTIONS (v0.6.13) — out-of-combat only
    # ============================================================
    # These three potions interact with the level-up / skill systems.
    # They cannot be used during combat — they'd interrupt the turn flow
    # and the prompt menus would feel out of place mid-fight. If a player
    # tries to use one in combat, refund it and bail.

    elif potion_type == "skill_rank_up":
        if in_combat:
            hero.potions[potion_type] += 1  # refund — bail before consumption sticks
            if is_bonus:
                hero.bonus_action_used = False
            print("\n🌟 You can't use a Skill Rank-Up Potion in the middle of a fight.")
            print("    Save it for between battles.")
            continue_text()
            space()
            return False

        # Build list of skills the hero has actually learned (rank >= 1)
        # that aren't already at max rank
        learned = []
        for key, rank in hero.skill_ranks.items():
            if rank <= 0:
                continue
            max_rank = SKILL_DEFS[key]["max_rank"]
            if rank >= max_rank:
                continue
            learned.append(key)

        if not learned:
            hero.potions[potion_type] += 1  # refund — nothing to upgrade
            if is_bonus:
                hero.bonus_action_used = False
            print("\n🌟 The potion shimmers, but you have no learned skills that")
            print("    aren't already maxed. You stow it away for later.")
            continue_text()
            space()
            return False

        print("\n🌟 You uncork the Skill Rank-Up Potion. The liquid glows faintly,")
        print("    waiting for your focus. Which skill do you want to advance?\n")
        for i, key in enumerate(learned, start=1):
            name     = SKILL_DEFS[key]["name"]
            rank     = hero.skill_ranks[key]
            max_rank = SKILL_DEFS[key]["max_rank"]
            print(f"  {i}) {name}  (Rank {rank} → {rank + 1} / {max_rank})")
        print(f"  {len(learned) + 1}) Cancel (don't drink)")

        pick = input("\nChoose: ").strip()
        if pick == str(len(learned) + 1) or not pick.isdigit():
            hero.potions[potion_type] += 1  # refund — cancelled
            if is_bonus:
                hero.bonus_action_used = False
            print("You re-cork the potion.")
            space()
            return False

        idx = int(pick) - 1
        if idx < 0 or idx >= len(learned):
            hero.potions[potion_type] += 1  # refund — invalid choice
            if is_bonus:
                hero.bonus_action_used = False
            print("Invalid choice. You re-cork the potion.")
            space()
            return False

        chosen_key = learned[idx]
        hero.skill_ranks[chosen_key] += 1
        hero.skills.add(chosen_key)
        # Clear any partial progress on this skill — the potion completes it cleanly
        hero.skill_progress[chosen_key] = 0
        print(f"\n✨ {SKILL_DEFS[chosen_key]['name']} advances to Rank {hero.skill_ranks[chosen_key]}!")
        # Check for cross-skill achievements (e.g. Jack of All Trades)
        if 'check_jack_of_all_trades' in globals():
            check_jack_of_all_trades(hero)
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "stat_point":
        if in_combat:
            hero.potions[potion_type] += 1  # refund
            if is_bonus:
                hero.bonus_action_used = False
            print("\n🌟 You can't use a Stat Point Potion in the middle of a fight.")
            print("    Save it for between battles.")
            continue_text()
            space()
            return False

        print("\n🌟 You drink the Stat Point Potion. Strength surges through you")
        print("    — you can feel your body adapting. (+2 stat points)\n")
        hero.stat_points += 2

        # Prompt immediately to assign — simple inline menu, no per-level cap
        # (the potion is rare and the player paid for it; let them dump both
        # points into one stat if they want).
        while hero.stat_points > 0:
            print(f"\nStat Points remaining: {hero.stat_points}")
            print(f"  1) +5 Max HP")
            print(f"  2) +1 Attack")
            print(f"  3) +1 Defense")
            print(f"  4) +1 Max AP")
            print(f"  5) Save remaining points for later")

            ch = input("\nChoose: ").strip()
            if ch == "1":
                hero.max_hp += 5
                hero.hp     += 5
                hero.max_overheal = int(hero.max_hp * 1.10)
                hero.stat_points -= 1
                print("  → Max HP increased!")
            elif ch == "2":
                hero.min_atk += 1
                hero.max_atk += 1
                hero.stat_points -= 1
                print("  → Attack increased!")
            elif ch == "3":
                hero.defence += 1
                hero.stat_points -= 1
                print("  → Defense increased!")
            elif ch == "4":
                hero.max_ap += 1
                hero.ap = min(hero.ap + 1, hero.max_ap)
                hero.stat_points -= 1
                print("  → Max AP increased!")
            elif ch == "5":
                print(f"  → Saved {hero.stat_points} stat point(s) for later.")
                break
            else:
                print("  Invalid choice.")

        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "skill_point":
        if in_combat:
            hero.potions[potion_type] += 1  # refund
            if is_bonus:
                hero.bonus_action_used = False
            print("\n🌟 You can't use a Skill Point Potion in the middle of a fight.")
            print("    Save it for between battles.")
            continue_text()
            space()
            return False

        print("\n🌟 You drink the Skill Point Potion. Insight blooms in your mind")
        print("    — techniques you've been chasing feel suddenly closer. (+2 skill points)")
        hero.skill_points += 2

        # Drop the player into the skill tree immediately to spend the points.
        # show_skill_tree handles partial investment, multi-rank, and progress
        # banking — exactly what we want. Player can also back out and save the
        # points for later via the tree's "0) Back" option.
        if 'show_skill_tree' in globals():
            show_skill_tree(hero)
        else:
            print(f"\n(You now have {hero.skill_points} skill point(s) banked.)")

        continue_text()
        space()
        return "bonus" if is_bonus else True

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

    # Cap per category = total stat points available (so a double level-up lets
    # you put both points into one stat if you choose), unless debug mode (uncapped).
    # Level 5 always allows at least 2 per category (milestone level).
    if getattr(hero, "debug_mode", False):
        stat_cap = 999
    else:
        # Cap per category = points available when menu opened, max 2.
        # Prevents spending more into one stat than you have points for,
        # and stops level 5's 5-point windfall from being dumped into one stat.
        stat_cap = min(2, hero.stat_points)

    while hero.stat_points > 0:
        clear_screen()

        # Live stat block — shows in debug mode now, full game in v5
        if True:
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
    Also lets player view stats and equipment before committing.
    Auto-exits when all points are spent.
    """
    while True:
        if hero.stat_points <= 0 and hero.skill_points <= 0:
            print("\n✅ All points spent.")
            return

        print("📈 Spend Points\n")
        print(f"Stat Points:  {hero.stat_points}")
        print(f"Skill Points: {hero.skill_points}")

        # Unequipped loot reminder
        unequipped = getattr(hero, "inventory", [])
        if unequipped:
            loot_names = ", ".join(item.name for item in unequipped)
            print(f"\n🎒 Unequipped loot: {loot_names}")

        print()
        option = 1
        stat_opt = skill_opt = view_opt = equip_opt = None

        if hero.stat_points > 0:
            print(f"{option}) Spend Stat Points")
            stat_opt = str(option); option += 1
        if hero.skill_points > 0:
            print(f"{option}) Spend Skill Points")
            skill_opt = str(option); option += 1

        print(f"{option}) View Stats & Equipment")
        view_opt = str(option); option += 1

        if unequipped:
            print(f"{option}) Equip Loot")
            equip_opt = str(option); option += 1

        print("0) Back")

        choice = input("\n> ").strip()

        if choice == "0":
            return
        elif stat_opt and choice == stat_opt:
            level_up_menu(hero)
        elif skill_opt and choice == skill_opt:
            show_skill_tree(hero)
        elif choice == view_opt:
            hero.show_all_game_stats()
            input("\nPress Enter...")
        elif equip_opt and choice == equip_opt:
            inventory_menu(hero)
        else:
            print("\nInvalid choice.")
            input("\nPress Enter...")

def has_unspent_points(hero) -> bool:
    return (getattr(hero, "stat_points", 0) + getattr(hero, "skill_points", 0)) > 0


def _stone_usable(hero):
    """Returns the Waterlogged Stone if equipped and has charges, else None."""
    stone = hero.equipment.get("trinket") if hasattr(hero, "equipment") else None
    if stone and stone.name == "Waterlogged Stone" and stone.stone_charges > 0:
        return stone
    return None


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

        # Only show title switcher if player has 2+ titles
        title_option = None
        if len(getattr(hero, "titles", set())) >= 2:
            print(f"{option}) Change Active Title")
            title_option = str(option)
            option += 1

        # Only show stone option if equipped and has charges
        stone_option = None
        _stone = _stone_usable(hero)
        if _stone:
            bonus_tag = " ⚡ FREE" if not getattr(hero, "bonus_action_used", False) else ""
            print(f"{option}) Use Waterlogged Stone ({_stone.stone_charges}/{_stone.stone_max_charges} charges) — restore AP{bonus_tag}")
            stone_option = str(option)
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

        if title_option and choice == title_option:
            switch_title_menu(hero)
            continue

        if stone_option and choice == stone_option:
            use_waterlogged_stone(hero)
            input("\nPress Enter...")
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
        continue_text()
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
        # Death Defier: set passive flag on first rank
        if key == "death_defier" and warrior.skill_ranks[key] == 1:
            warrior.death_defier       = True
            warrior.death_defier_river = False
            warrior.death_defier_active = False
            warrior.death_defier_used   = False

        clear_screen()
        print(wrap(
            f"Nob puts you through a focused drill. "
            f"By the end of it your {name} has sharpened noticeably."
        ))
        print(f"\n✨ {name} is now Rank {rank + 1}.")

        # Fire mastery-title check — rank 5 awards Brawl Master / Combat Medic / etc.
        # Without this, hitting rank 5 via Nob silently skipped the title award.
        check_skill_mastery(warrior, key)
        # Also check the breadth capstone — Nob's free rank-up can be the
        # tipping point that gets the player to rank 2 in all five skills.
        check_true_jack_of_all_trades(warrior)

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
    # Clear rot with full restore before the heal so max_hp is correct
    clear_rot(warrior, restore_hp=True, source="long_rest")
    warrior.hp = warrior.max_hp
    warrior.max_overheal = int(warrior.max_hp * 1.10)
    warrior.ap = warrior.max_ap

    # Clear combat stats — full_rest=True is THE round 4-5 "day passes" moment.
    # This is the only place berserk fully wipes regardless of remaining charges.
    reset_between_rounds(warrior, full_rest=True)
    # Reset Death Defier for the new stage
   
   
    


    print(f"\n❤️ You are fully healed: {warrior.hp}/{warrior.max_hp} HP")
    print(f"🔵 AP restored: {warrior.ap}/{warrior.max_ap}")
    space(2)

    # -------- SMALL HUB LOOP (all dialogue is placeholder) --------
    talked_goblin = False
    talked_orc = False
    talked_hooded = False
    talked_crafter = False
    merchant_stock = None     # holds the merchant's stock across revisits within this interlude
    crafter_stock = None      # v0.6.16: same pattern for crafter stock
    talked_bo = False

    while True:
        clear_screen()
        print("What would you like to do before the next stage of the tournament?")
        print("1) Talk to the goblin bookie (arena accountant)")
        print("2) Talk to the orc guard (wip)")
        print("3) Talk to the hooded figure (wip)")
        print("4) Visit the crafter")
        print("5) Talk to merchant")
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
        _stone = _stone_usable(warrior)
        if _stone:
            print(f"14) Use Waterlogged Stone ({_stone.stone_charges}/{_stone.stone_max_charges} charges) — restore AP")
        # v0.6.15: Use a potion option added so players can drink progression
        # potions (skill_point, stat_point, skill_rank_up) during the interlude.
        # Previously the only way to drink potions outside the per-round rest
        # was inventory_menu, and progression potions weren't accessible there.
        print("15) Use a potion")

        raw = input("\nChoose: ")

        # Allow monster debug here too
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            monster = raw[1]
            if monster:
                battle(warrior, monster)
            clear_screen()
            continue

        # v0.6.19: route 'debug' / 'q' / 'c' through the shared dev-shortcut
        # helper so the interlude has the same shortcuts as story prompts.
        # Without this, typing 'debug' in the interlude was a no-op — only
        # story prompts (continue_text / check) handled it.
        if isinstance(raw, str) and _try_dev_shortcut(raw):
            clear_screen()
            continue

        choice = str(raw).strip()

        if choice == "1":
            clear_screen()
            bookie_encounter(warrior)
            talked_goblin = True
            space(2)

        elif choice == "2":
            clear_screen()
            # TODO: add orc guard dialogue here
            if not talked_orc:
                talked_orc = True
                print(wrap("(The guard makes a low annoyed grunt)"))
            else:
                print(wrap("(The guard glares at you. What!)"))
            space(2)
            continue_text()

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
            continue_text()

        elif choice == "4":
            clear_screen()
            # v0.6.16: replaces WIP placeholder. Stock persists across re-visits.
            from crafter import crafter_scene
            crafter_stock = crafter_scene(warrior, stock=crafter_stock)
            talked_crafter = True
            space(2)
        
        elif choice == "5":
            clear_screen()
            # Stock persists across visits within this interlude — first
            # visit rolls fresh inventory, subsequent visits reopen the same
            # catalog with sold items still sold and potion counts intact.
            # Prevents re-roll exploits while letting the player leave to
            # check gear and come back.
            from merchant import merchant_scene
            merchant_stock = merchant_scene(warrior, stock=merchant_stock)
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
            space(2)
            continue_text()

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
            if not confirm_continue_if_points_left(warrior, "Head into the championship with unused loot or points?"):
                continue


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
            # v0.6.20: pause so stats don't vanish on loop restart (which calls clear_screen())
            _real_input("Press Enter to return to the menu...")

        elif choice == "10":
            if has_unspent_points(warrior):
                spend_points_menu(warrior)
            else:
                print("Invalid choice.\n")

        elif choice == "11":
            clear_screen()
            warrior.show_all_game_stats()
            space()
            # v0.6.20: pause so stats don't vanish on loop restart (which calls clear_screen())
            _real_input("Press Enter to return to the menu...")

        elif choice == "12":
            clear_screen()
            inventory_menu(warrior)

        elif choice == "13":
            if COMBAT_LOG:
                view_combat_log()

        elif choice == "14":
            if _stone_usable(warrior):
                use_waterlogged_stone(warrior)
                input("\nPress Enter...")
            else:
                print("Invalid choice.\n")

        # v0.6.15: Use a potion (interlude version). All non-combat potions
        # work here — heal, AP, antidote, cure-all, elixir, frostpine, and
        # the progression potions (skill_point, stat_point, skill_rank_up).
        # Calls use_potion_menu with in_combat=False so progression handlers
        # take their successful out-of-combat path.
        elif choice == "15":
            clear_screen()
            use_potion_menu(warrior, in_combat=False)
            space()

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
        print("10) Grant River Spirit (river version — free, 1 HP revival)")
        print("11) Trigger Death Defier / River Spirit (test)")
        print("12) Level Up")
        print("13) Skill Editor (set any skill rank)")
        print("14) Loot Manager (give / equip / unequip)")
        print("15) View Combat Log")
        print("16) Restore AP to Full")
        print("17) Debug Potion Menu")
        print("18) Title Grant Menu")
        print("19) Give Gold")            # v0.6.16
        print("20) Jump to Interlude")    # v0.6.16
        print("---------------------")
        print("21) Exit Current Run")
        print("22) Exit Debug Menu")
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

        # --- 10) Grant River Spirit (river version) ---
        elif choice == "10":
            warrior.death_defier = True
            warrior.death_defier_river = True  # debug = free version (0 AP)
            warrior.death_defier_active = False
            warrior.death_defier_used = False
            print("💀 Debug: River Spirit granted. Activate it in combat via the skill menu.")
            input("\nPress Enter...")

        # --- 11) Trigger Death Defier test ---
        elif choice == "11":
            # This simulates a death to verify the hook works
            if "try_death_defier" in globals():
                warrior.hp = 0
                # v0.6.21: was source="debug" — try_death_defier takes `reason`,
                # not `source`. The wrong kwarg raised TypeError and made this
                # debug test crash instead of exercising the revival hook.
                try_death_defier(warrior, reason="debug")
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
                if go in ("", "y"):
                    spend_points_menu(warrior)
            else:
                input("\nPress Enter...")

        # --- 13) Skill editor ---
        elif choice == "13":
            _debug_skill_editor(warrior)

        # --- 14) Loot Manager ---
        elif choice == "14":
            _debug_loot_menu(warrior)

        elif choice == "15":
            view_combat_log()

        # --- 16) Restore AP to Full ---
        elif choice == "16":
            old_ap = warrior.ap
            warrior.ap = warrior.max_ap
            restored = warrior.ap - old_ap
            print(f"⚡ Debug: AP fully restored! ({old_ap} → {warrior.ap}/{warrior.max_ap})")
            input("\nPress Enter...")

        # --- 17) Debug Potion Menu ---
        elif choice == "17":
            _debug_potion_menu(warrior)

        # --- 18) Title Grant Menu ---
        elif choice == "18":
            _debug_title_menu(warrior)

        # --- 19) Give Gold (v0.6.16) ---
        elif choice == "19":
            clear_screen()
            print("===== DEBUG: GIVE GOLD =====")
            print(f"Current gold: {warrior.gold}")
            print()
            print("1) +50g")
            print("2) +100g")
            print("3) +500g")
            print("4) Custom amount")
            print("0) Back")
            gc = _real_input("> ").strip()
            if gc == "1":
                warrior.gold += 50
                print(f"\n✅ +50g. Total: {warrior.gold}g")
            elif gc == "2":
                warrior.gold += 100
                print(f"\n✅ +100g. Total: {warrior.gold}g")
            elif gc == "3":
                warrior.gold += 500
                print(f"\n✅ +500g. Total: {warrior.gold}g")
            elif gc == "4":
                amt = _real_input("Amount: ").strip()
                try:
                    warrior.gold += int(amt)
                    print(f"\n✅ +{amt}g. Total: {warrior.gold}g")
                except ValueError:
                    print("\nInvalid amount.")
            _real_input("\nPress Enter...")

        # --- 20) Jump to Interlude (v0.6.16) ---
        elif choice == "20":
            clear_screen()
            print("===== DEBUG: JUMP TO INTERLUDE =====")
            print()
            print("This drops you into the rest period directly.")
            print("Use option 19 first to grant some gold for testing.")
            print()
            confirm = _real_input("Jump now? (y/n): ").strip().lower()
            if confirm == "y":
                arena_quarters_interlude(warrior)
                _real_input("\nReturned from interlude. Press Enter...")

        # --- 21) Exit run ---
        elif choice == "21":
            sys.exit(0)

        # --- 22) Exit debug menu ---
        elif choice == "22":
            return


# ============================================================
# FATE TITLE: The Gooed One
# ============================================================
# Triggered when the player dies to a regular Green Slime while having
# every tool needed to survive. Specifically excludes Chimera-variant
# Green Slimes (those are legitimately scary, not embarrassing) and
# Red Slime (tier 2, has its own threat profile). The whole point of
# this title is to call out humiliation deaths — so the conditions
# require both:
#   - killer is a non-Chimera Green Slime
#   - hero had healing options unused (potions or learned First Aid)
# If either condition fails, the player gets the regular Fallen Champion
# fate title instead, no roast required.
#
# Death Defier / River Spirit interaction:
#   This check runs AFTER try_death_defier has already had its chance to
#   trigger. If Death Defier is armed and unused, it fires inside the
#   damage handlers (line ~8619 for DoT, ~6931/6968 for direct hits) and
#   revives the player BEFORE this code ever runs — so a successful
#   Death Defier save means the player is alive, no death sequence runs,
#   and this title is never considered. If Death Defier was burned
#   earlier in the run (death_defier_used = True), it returns False and
#   the death proceeds normally — at which point we still roast the
#   player if they had potions left, since "I burned my save" doesn't
#   excuse "I also forgot I had three Mega Potions."
def is_gooed_one_death(warrior, killer):
    """Return True if the player's death qualifies as 'The Gooed One' —
    i.e., a regular Green Slime kill with healing options still available."""
    if killer is None:
        return False
    # Must be a Green Slime — Red Slime (tier 2) does NOT qualify
    if getattr(killer, "name", "") != "Green Slime":
        return False
    # Chimera-variant Green Slimes are legitimately dangerous — don't roast
    if hasattr(killer, "chimera_tier1"):
        return False

    # Hero must have had healing options available
    healing_potions = ("heal", "super_potion", "mega_potion", "full_potion")
    had_potion = any(
        warrior.potions.get(k, 0) > 0 for k in healing_potions
    )
    had_first_aid = warrior.skill_ranks.get("heal", 0) > 0
    had_antidote = warrior.potions.get("antidote", 0) > 0
    # Frostpine Tonic — Elwyn's prologue gift, 40% HP heal + status clear.
    # Dying to a slime with this still unused is peak Goo Guy energy.
    had_frostpine = warrior.potions.get("frostpine_tonic", 0) > 0

    # If they had ANY of these and still lost to a Green Slime, that's on them
    return had_potion or had_first_aid or had_antidote or had_frostpine


def show_end_summary(warrior):
    """Prints remaining potions and loot acquired at end of run."""
    print()
    print("=" * 50)
    print(f"  END OF RUN SUMMARY -- {warrior.name}")
    print("=" * 50)

    # --- Potions remaining ---
    potion_labels = {
        "heal":            "Heal Potion",
        "super_potion":    "Super Potion",
        "mega_potion":     "Mega Potion",
        "full_potion":     "Full Potion",
        "ap":              "AP Potion",
        "super_ap":        "Super AP Potion",
        "mega_ap":         "Mega AP Potion",
        "full_ap":         "Full AP Potion",
        "antidote":        "Antidote",
        "burn_cream":      "Burn Cream",
        "cure_all":        "Cure-All Tonic",
        "elixir":          "Elixir",
        "frostpine_tonic": "Frostpine Tonic",
    }
    remaining = [(potion_labels.get(k, k), v) for k, v in warrior.potions.items() if v > 0]
    if remaining:
        print("  Potions Remaining:")
        for label, count in remaining:
            print(f"    {label}: {count}")
    else:
        print("  Potions Remaining: none")

    # --- Equipment equipped ---
    print("  Equipment:")
    any_gear = False
    # v0.6.21: slot keys corrected to match the v0.6.16 equipment dict
    # (main_hand / off_hand / helm / cape). The old ("weapon", ...) loop
    # silently skipped weapons, shields, helms, and capes in this summary
    # since v0.6.16 — players never saw their weapon on the end screen.
    slot_labels = {
        "main_hand": "Main Hand", "off_hand": "Off Hand", "armor": "Armor",
        "helm": "Helm", "cape": "Cape", "accessory": "Accessory",
        "trinket": "Trinket", "finger_1": "Finger 1", "finger_2": "Finger 2",
    }
    for slot in ("main_hand", "off_hand", "armor", "helm", "cape",
                 "accessory", "trinket", "finger_1", "finger_2"):
        item = warrior.equipment.get(slot)
        if item:
            print(f"    {slot_labels[slot]:<12} {item.short_label()}")
            any_gear = True
    if not any_gear:
        print("    (nothing equipped)")

    # --- Inventory (unequipped loot in bag) ---
    equipped_items = set(i for i in warrior.equipment.values() if i is not None)
    inv = [i for i in warrior.inventory if i not in equipped_items]
    if inv:
        print("  Bag:")
        for item in inv:
            print(f"    {item.short_label()}")

    print("=" * 50)


def offer_loot(warrior, loot):
    """
    Show loot detail, ask player to equip now or save for later.
    Used after every enemy defeat so players never miss a drop.
    """
    print(f"\n🎁 Loot acquired!\n")
    print(loot.full_detail())
    print()

    # Check what's currently in that slot
    if loot.slot == "ring":
        f1 = warrior.equipment.get("finger_1")
        f2 = warrior.equipment.get("finger_2")
        if f1 and f2:
            print(wrap(f"Both fingers full: F1 {f1.short_label()} | F2 {f2.short_label()}"))
        elif f1:
            print(wrap(f"Finger 1: {f1.short_label()}  (Finger 2 is empty)"))
        elif f2:
            print(wrap(f"Finger 2: {f2.short_label()}  (Finger 1 is empty)"))
    else:
        current = warrior.equipment.get(loot.slot)
        if current:
            print(wrap(f"Currently equipped in {loot.slot} slot: {current.short_label()}"))

    while True:
        choice = _real_input(f"Equip {loot.name} now? (y/n): ").strip().lower()
        if choice == "y":
            # v0.6.19: equip_item returns False on cancel/block (e.g. 1H weapon
            # vs 2H equipped, two-handed confirm declined, ring cancel). Without
            # this fallback the loot was silently lost — the bug that ate a
            # tester's Javelina Tusk against a Walking Staff main_hand.
            if not equip_item(warrior, loot):
                warrior.inventory.append(loot)
                print(wrap(f"{loot.name} saved to your bag instead."))
            break
        elif choice == "n":
            warrior.inventory.append(loot)
            print(wrap(f"{loot.name} saved to your bag."))
            break
        else:
            print("Enter y or n.")

    log(f"  [LOOT] {loot.short_label()} dropped.")


def _debug_title_menu(warrior):
    """
    Debug submenu — grant any title to the warrior.
    Equippable titles apply their stat buffs via award_title_with_buff.
    Fate titles and achievements go into their respective sets directly.
    Adding new titles: just add an entry to the TITLES list below.
    """
    # All known titles — add new ones here as they're created
    TITLES = [
        # (key, category, display_name)
        # --- Equippable (with stat buffs) ---
        ("champion_of_the_arena", "equippable",  "Champion of the Arena  [no buff]"),
        ("river_warrior",         "equippable",  "River Warrior         [no buff]"),
        ("jack_of_all_trades",    "equippable",  "Jack of All Trades    [+1 HP/ATK/DEF/AP]"),
        ("guardian",              "equippable",  "Guardian              [+2 HP, +2 DEF]"),
        ("dark_champion",         "equippable",  "Dark Champion         [+2 ATK, +2 AP]"),
        # --- Fate titles ---
        ("drowned_one",           "fate",        "Drowned One"),
        ("flayed_one",            "fate",        "Flayed One"),
        ("coward",                "fate",        "Coward"),
        ("fallen_champion",       "fate",        "Fallen Champion"),
        # --- Achievements ---
        ("champion_of_the_arena", "achievement", "Champion of the Arena (achievement)"),
    ]

    while True:
        clear_screen()
        print("=" * 45)
        print("🏅  DEBUG — TITLE GRANT MENU")
        print("=" * 45)
        print()

        for i, (key, cat, label) in enumerate(TITLES, 1):
            # Check if already owned
            if cat == "equippable":
                owned = key in getattr(warrior, "titles", set())
            elif cat == "fate":
                owned = key in getattr(warrior, "fate_titles", set())
            else:
                owned = key in getattr(warrior, "achievements", set())

            owned_tag = " ✅" if owned else ""
            print(f"  {i:>2}) {label}{owned_tag}")

        print()
        print("   0) Back")
        print()
        choice = _real_input("> ").strip()

        if choice == "0":
            return

        if not choice.isdigit():
            continue

        idx = int(choice) - 1
        if idx < 0 or idx >= len(TITLES):
            continue

        key, cat, label = TITLES[idx]

        if cat == "equippable":
            if key in getattr(warrior, "titles", set()):
                print(f"\n  Already have '{label}' — skipping buff, setting active title.")
                warrior.active_title = key
            else:
                # Apply buffs for titles that have them
                if key in ("guardian", "dark_champion", "jack_of_all_trades"):
                    award_title_with_buff(warrior, key)
                else:
                    warrior.titles.add(key)
                    warrior.active_title = key
                    print(f"\n  ✅ Granted: {label}")

        elif cat == "fate":
            warrior.fate_titles.add(key)
            print(f"\n  ✅ Fate title granted: {label}")

        elif cat == "achievement":
            warrior.achievements.add(key)
            print(f"\n  ✅ Achievement granted: {label}")

        input("\nPress Enter...")


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
        "7": "mythril",
    }

    def _pick_rarity():
        print("\n  Rarity:")
        print("    1) ⬜ Poor      2) 🟦 Normal    3) 🟩 Uncommon")
        print("    4) 🟨 Rare      5) 🟪 Epic       6) 🟥 Legendary  7) 🟧 Mythril")
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
        ("9",  "Goblin Shortbow   (weapon)    — Goblin Archer",      "Goblin Archer"),
        ("10", "Javelina Tusk     (weapon)    — Javelina",          "Javelina"),
        ("11", "Soul Pendant      (accessory) — Noob Ghost",        "Noob Ghost"),
        ("12", "Rider's Armor     (armor)     — Wolf Pup Rider",    "Wolf Pup Rider"),
        ("13", "Lightrender / Destiny Definer (weapon) — Fallen Warrior", "Fallen Warrior"),
        ("14", "Chimera Scale     (armor)     — Young Chimera",     "Young Chimera"),
        ("15", "Charged Jagged Rock (trinket) — Flayed One",       "Flayed One"),
        ("16", "Waterlogged Stone   (trinket)   — Drowned One",     "Drowned One"),
        ("17", "Goblin War Blade    (weapon)    — Goblin Warrior",   "Goblin Warrior"),
        ("18", "Tainted Champion's Breastplate (armor) — Patronus", "Patronus"),
        # v0.6.16 — crafted set pieces (no monster source, given directly)
        ("19", "Wolf-Hide Hood        (helm)      — crafted",          "DEBUG_WOLF_HIDE_HOOD"),
        ("20", "Wolf-Hide Cloak       (cape)      — crafted",          "DEBUG_WOLF_HIDE_CLOAK"),
        ("21", "Wolf-Hide Jerkin      (armor)     — crafted",          "DEBUG_WOLF_HIDE_JERKIN"),
        ("22", "Wolf-Tooth Charm      (accessory) — crafted",          "DEBUG_WOLF_TOOTH_CHARM"),
        ("23", "Dire Wolf Hood        (helm)      — crafted",          "DEBUG_DIRE_WOLF_HOOD"),
        ("24", "Dire Wolf Cloak       (cape)      — crafted",          "DEBUG_DIRE_WOLF_CLOAK"),
        ("25", "Dire Wolf Jerkin      (armor)     — crafted",          "DEBUG_DIRE_WOLF_JERKIN"),
        ("26", "Dire Wolf Talisman    (accessory) — crafted",          "DEBUG_DIRE_WOLF_TALISMAN"),
        # v0.6.16 — merchant shields (no monster source, given directly)
        ("27", "Pine Shield           (shield)    — merchant",         "DEBUG_PINE_SHIELD"),
        ("28", "Oak Shield            (shield)    — merchant",         "DEBUG_OAK_SHIELD"),
        ("29", "Ironwood Shield       (shield)    — merchant",         "DEBUG_IRONWOOD_SHIELD"),
        ("30", "Ashen Shield          (shield)    — merchant",         "DEBUG_ASHEN_SHIELD"),
    ]

    while True:
        clear_screen()
        print("===== DEBUG: LOOT MANAGER =====\n")

        # Show currently equipped gear at a glance
        eq = warrior.equipment
        print("  Currently equipped:")
        # v0.6.16: main_hand and off_hand instead of single weapon slot
        h1 = eq.get('main_hand')
        h2 = eq.get('off_hand')
        print(f"    ⚔️  Hand 1   : {h1.short_label() if h1 else '(none)'}")
        print(f"    ⚔️  Hand 2   : {h2.short_label() if h2 else '(none)'}")
        print(f"    🛡️  Armor    : {eq.get('armor').short_label() if eq.get('armor') else '(none)'}")
        # v0.6.16: helm and cape
        print(f"    🪖 Helm     : {eq.get('helm').short_label() if eq.get('helm') else '(none)'}")
        print(f"    🧥 Cape     : {eq.get('cape').short_label() if eq.get('cape') else '(none)'}")
        print(f"    💍 Accessory: {eq.get('accessory').short_label() if eq.get('accessory') else '(none)'}")
        tr = eq.get('trinket')
        if tr and getattr(tr, "stone_max_charges", 0) > 0:
            tr_label = f"{tr.short_label()} [{tr.stone_charges}/{tr.stone_max_charges} charges]"
        elif tr:
            tr_label = tr.short_label()
        else:
            tr_label = "(none)"
        print(f"    🪨 Trinket  : {tr_label}")
        f1 = eq.get('finger_1')
        f2 = eq.get('finger_2')
        print(f"    💍 Finger 1 : {f1.short_label() if f1 else '(none)'}")
        print(f"    💍 Finger 2 : {f2.short_label() if f2 else '(none)'}")
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
                # v0.6.16: updated for main_hand/off_hand/helm/cape
                h1 = eq.get('main_hand')
                h2 = eq.get('off_hand')
                print(f"  ⚔️  Hand 1   : {h1.short_label() if h1 else '(none)'}")
                print(f"  ⚔️  Hand 2   : {h2.short_label() if h2 else '(none)'}")
                print(f"  🛡️  Armor    : {eq.get('armor').short_label() if eq.get('armor') else '(none)'}")
                print(f"  🪖 Helm     : {eq.get('helm').short_label() if eq.get('helm') else '(none)'}")
                print(f"  🧥 Cape     : {eq.get('cape').short_label() if eq.get('cape') else '(none)'}")
                print(f"  💍 Accessory: {eq.get('accessory').short_label() if eq.get('accessory') else '(none)'}")
                print(f"  🪨 Trinket  : {eq.get('trinket').short_label() if eq.get('trinket') else '(none)'}")
                print(f"  💍 Finger 1 : {eq.get('finger_1').short_label() if eq.get('finger_1') else '(none)'}")
                print(f"  💍 Finger 2 : {eq.get('finger_2').short_label() if eq.get('finger_2') else '(none)'}")
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

                # v0.6.16: handle DEBUG_ sentinels (crafted set pieces and shields)
                # These have FIXED stats so we skip the rarity prompt entirely.
                if monster_key.startswith("DEBUG_"):
                    from crafter import (WOLF_HIDE_RECIPES, DIRE_WOLF_RECIPES,
                                         make_crafted_item)
                    crafted_map = {
                        "DEBUG_WOLF_HIDE_HOOD":     ("Wolf-Hide Hood",     WOLF_HIDE_RECIPES),
                        "DEBUG_WOLF_HIDE_CLOAK":    ("Wolf-Hide Cloak",    WOLF_HIDE_RECIPES),
                        "DEBUG_WOLF_HIDE_JERKIN":   ("Wolf-Hide Jerkin",   WOLF_HIDE_RECIPES),
                        "DEBUG_WOLF_TOOTH_CHARM":   ("Wolf-Tooth Charm",   WOLF_HIDE_RECIPES),
                        "DEBUG_DIRE_WOLF_HOOD":     ("Dire Wolf Hood",     DIRE_WOLF_RECIPES),
                        "DEBUG_DIRE_WOLF_CLOAK":    ("Dire Wolf Cloak",    DIRE_WOLF_RECIPES),
                        "DEBUG_DIRE_WOLF_JERKIN":   ("Dire Wolf Jerkin",   DIRE_WOLF_RECIPES),
                        "DEBUG_DIRE_WOLF_TALISMAN": ("Dire Wolf Talisman", DIRE_WOLF_RECIPES),
                    }
                    shield_map = {
                        "DEBUG_PINE_SHIELD":     ("Pine Shield",     1, 0),
                        "DEBUG_OAK_SHIELD":      ("Oak Shield",      2, 0),
                        "DEBUG_IRONWOOD_SHIELD": ("Ironwood Shield", 3, 0),
                        "DEBUG_ASHEN_SHIELD":    ("Ashen Shield",    4, 0),
                    }
                    if monster_key in crafted_map:
                        name, recipes = crafted_map[monster_key]
                        item = make_crafted_item(name, recipes[name])
                    elif monster_key in shield_map:
                        name, defence, max_hp = shield_map[monster_key]
                        item = Equipment(name=name, slot="shield", rarity="normal",
                                         defence=defence, max_hp=max_hp)
                    else:
                        print(f"  Unknown debug key: {monster_key}")
                        _real_input("\nPress Enter...")
                        continue
                    warrior.inventory.append(item)
                    print(f"\n  ✅ Granted to inventory: {item.short_label()}")
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
                    # v0.6.19: debug-equip can hit the same equip_item cancel
                    # paths (1H vs 2H, etc.) so bag the item if equip fails.
                    if equip_item(warrior, item):
                        print(f"\n  Stats after equip — ATK: {warrior.min_atk}-{warrior.max_atk}  "
                              f"DEF: {warrior.defence}  HP: {warrior.hp}/{warrior.max_hp}")
                    else:
                        warrior.inventory.append(item)
                        print(f"\n✅ Equip blocked — added to inventory instead: {item.short_label()}")
                else:
                    warrior.inventory.append(item)
                    print(f"\n✅ Added to inventory: {item.short_label()}")
                _real_input("\nPress Enter...")

        # ── C: Unequip a Slot ────────────────────────────────────────────
        elif mode == "C":
            while True:
                clear_screen()
                print("===== UNEQUIP SLOT =====\n")
                # v0.6.21: corrected slot keys to match the v0.6.16 equipment
                # dict. Debug-only tool, but it couldn't unequip weapons/shields/
                # helms/capes under the old ("weapon", ...) list.
                slots = ["main_hand", "off_hand", "armor", "helm", "cape",
                         "accessory", "trinket", "finger_1", "finger_2"]
                slot_labels = {
                    "main_hand": "Main Hand", "off_hand": "Off Hand", "armor": "Armor",
                    "helm": "Helm", "cape": "Cape", "accessory": "Accessory",
                    "trinket": "Trinket", "finger_1": "Finger 1", "finger_2": "Finger 2",
                }
                for i, slot in enumerate(slots, 1):
                    current = warrior.equipment.get(slot)
                    label = current.short_label() if current else "(empty)"
                    print(f"  {i}) {slot_labels[slot]:<12} {label}")
                print("  0) Done")

                slot_choice = _real_input("\n  Pick slot to unequip > ").strip()
                if slot_choice == "0":
                    break

                slot_map = {str(i): s for i, s in enumerate(slots, 1)}
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
        ("13", "cure_all",     "Cure-All Tonic    (clear all status, not psychic)"),
        ("14", "elixir",       "Elixir            (50% HP + 50% AP)"),
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
        print("  15) Add ALL potions x3 (quick fill)")
        print("   0) Back")

        choice = _real_input("\nPick potion to add > ").strip()

        if choice == "0":
            return

        if choice == "15":
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
    print("15) Flayed One")
    print("16) Drowned One")
    print("17) Goblin Warrior")
    print("18) Patronus (Evil Path Boss)")
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
        "14": Young_Chimera,
        "15": Flayed_One,
        "16": Drowned_One,
        "17": Goblin_Warrior,
        "18": Patronus,
    }

    # NEW — tier lookup (logic only)
    tier_map = {
        "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
        "7": 4,
        "8": 3, "9": 2, "10": 2, "11": 2, "12": 2,
        "13": 3,
        "14": 5,
        "15": 3,  # Flayed One
        "16": 3,  # Drowned One
        "17": 3,  # Goblin Warrior
        "18": 5,  # Patronus
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
    Warns about unspent points AND unequipped loot before proceeding.
    """
    while True:
        stat  = getattr(hero, "stat_points", 0)
        skill = getattr(hero, "skill_points", 0)
        unequipped = getattr(hero, "inventory", [])

        has_points = stat > 0 or skill > 0
        has_loot   = len(unequipped) > 0

        if not has_points and not has_loot:
            return True

        print()
        if has_points:
            print(f"⚠️  Unspent points — Stat: {stat}  Skill: {skill}")
        if has_loot:
            loot_names = ", ".join(item.name for item in unequipped)
            print(f"🎒 Unequipped loot: {loot_names}")

        ans = input(f"\n{prompt} (y/n): ").strip().lower()

        if ans == "y":
            return True
        if ans == "n":
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

def clear_rot(hero, restore_hp=False, source="rest"):
    """Remove all rot from the player. Max HP is restored to pre-rot value.
    restore_hp=True also heals current HP back to the restored max (used for
    long rest / Patronus intervention / Chimera intervention).
    Regular rest clears rot but does NOT restore HP — player heals naturally."""
    loss = getattr(hero, "rot_max_hp_loss", 0)
    if loss <= 0:
        return
    hero.max_hp          += loss
    hero.max_overheal     = int(hero.max_hp * 1.10)
    hero.rot_max_hp_loss  = 0
    hero.rot_base_max_hp  = 0
    if restore_hp:
        hero.hp = hero.max_hp
        print(wrap(f"✨ The rot lifts — your vitality is fully restored! Max HP recovered (+{loss})."))
    else:
        print(wrap(f"🟫 The rot fades — your Max HP recovers (+{loss})."))


# ====================================================================
# COMBAT FATIGUE (v0.6.14)
# ====================================================================
# Long fights now apply a focus-streak save mechanic to prevent stalemates.
# Both player and monster roll independently against escalating DCs:
#   Save tier 0: d20 >= 10 to hold focus
#   Save tier 1: d20 >= 15 to hold focus
#   Save tier 2: d20 >= 20 to hold focus
# Pass -> advance one tier (tier 2 passing wraps back to tier 0).
# Fail -> lose 1 DEF if roll <= 13, lose 2 DEF if roll >= 14. Tier resets to 0.
# DEF loss is tracked in fatigue_def_loss (separate from acid_defence_loss so
# they stack independently). Both are subtracted from effective DEF in
# apply_defence and elsewhere.
#
# Thresholds:
#   Regular monsters: kicks in starting turn 10
#   Bosses (Young Chimera, Patronus): kicks in starting turn 15
# Reset on fight end via reset_after_battle / reset_between_rounds.
# ====================================================================

FATIGUE_DC_BY_TIER = {0: 10, 1: 15, 2: 20}

def init_fatigue(entity):
    """Make sure the entity has fatigue state. Safe to call repeatedly."""
    if not hasattr(entity, "fatigue_def_loss"):
        entity.fatigue_def_loss = 0
    if not hasattr(entity, "fatigue_save_tier"):
        entity.fatigue_save_tier = 0

def fatigue_threshold_for(enemy):
    """Bosses (Chimera/Patronus) get a higher threshold so scripted long
    fights aren't ground down by fatigue too early. Everyone else: turn 10."""
    name = getattr(enemy, "name", "")
    if name in ("Young Chimera", "Patronus"):
        return 15
    return 10

def roll_fatigue_save(entity, turn_count, enemy, is_player):
    """
    Roll a focus-streak save for one side. Called at the start of that side's
    turn after the threshold. Mutates entity.fatigue_def_loss and
    entity.fatigue_save_tier in place. Returns nothing.

    Silent rolls — narrate outcome only, no dice numbers shown (per design).
    """
    threshold = fatigue_threshold_for(enemy)
    if turn_count < threshold:
        return

    init_fatigue(entity)

    tier = entity.fatigue_save_tier
    dc   = FATIGUE_DC_BY_TIER.get(tier, 10)
    roll = random.randint(1, 20)

    if roll >= dc:
        # Pass — advance one tier, wrap from 2 back to 0
        entity.fatigue_save_tier = (tier + 1) % 3
        if is_player:
            # Only narrate on the harder saves so we're not spamming "focus holds"
            # every turn. Tier 0 -> tier 1 is the easy one; tier 1 -> tier 2 and
            # tier 2 -> 0 are the dramatic ones worth flagging.
            if tier == 1:
                print(wrap("\U0001f9d8  Your focus holds — you steady your stance."))
            elif tier == 2:
                print(wrap("\U0001f9d8  Through the haze of exhaustion, you find a second wind!"))
        return

    # Fail — lose DEF and reset tier
    loss = 2 if roll >= 14 else 1
    entity.fatigue_def_loss += loss
    entity.fatigue_save_tier = 0

    if is_player:
        if loss == 1:
            print(wrap(f"\U0001f4a8 Fatigue creeps in — your guard wavers. (-{loss} DEF)"))
        else:
            print(wrap(f"\U0001f4a8 The long fight catches up with you — your stance breaks! (-{loss} DEF)"))
    else:
        # Show monster fatigue too so the player feels the mutual pressure
        ename = getattr(enemy, "display_name", enemy.name)
        if loss == 1:
            print(wrap(f"\U0001f4a8 {ename}'s guard sags from the long fight. (-{loss} DEF)"))
        else:
            print(wrap(f"\U0001f4a8 {ename} stumbles, exhausted — its defence falters! (-{loss} DEF)"))


def clear_all_status_effects(hero):
    """Clears all harmful status effects"""
    clear_all_burns(hero)
    clear_rot(hero, restore_hp=True, source="intervention")

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
    hero.warrior_bleed_dots = []

    # v0.6.14: combat fatigue — wipe on fight end, DEF auto-restores via the
    # effective_def calc (apply_defence subtracts fatigue_def_loss from base).
    hero.fatigue_def_loss  = 0
    hero.fatigue_save_tier = 0

    # Defence warp — restore original defence if warp is active
    if hasattr(hero, "defence_warp_phase"):
        if hasattr(hero, "defence_warp_original_defence"):
            hero.defence = hero.defence_warp_original_defence
        del hero.defence_warp_phase
    if hasattr(hero, "defence_warp_original_defence"):
        del hero.defence_warp_original_defence

    # NOTE: Psychic debuffs are NOT cleared here — requires Triage (rank 6+)

def reset_between_rounds(hero, full_rest=False):
    """
    Cleanup between arena fights.

    full_rest=False (default): standard inter-round cleanup. Berserk carries
                               over while berserk_turns > 0 — fury is allowed
                               to ride into the next fight.
    full_rest=True:            true "a day passes" rest (round 4-5 interlude).
                               Berserk fully wipes, no matter how many charges
                               remain.
    """
    # DoTs / debuffs that should not persist between fights
    clear_all_burns(hero)
    clear_rot(hero, restore_hp=False, source="rest")  # rot clears, HP not restored

    hero.poison_active = False
    hero.poison_amount = 0
    hero.poison_turns = 0
    hero.poison_skip_first_tick = False   # ✅ add

    hero.fire_stacks = 0                  # ✅ add (if HUD uses it)

    # Adrenaline — clears between fights, rebuilds naturally from first hit taken
    hero.current_bonus_damage = 0
    hero.temp_special = 0
    hero.total_special = hero.perm_special   # perm stays, temp resets

    hero.war_cry_bonus = 0
    hero.war_cry_turns = 0

    # Charismatic Speaker — strip the per-fight 15% ATK buff
    if "charismatic_speaker" in getattr(hero, "titles", set()):
        bonus = getattr(hero, "charismatic_speaker_bonus", 2)
        hero.min_atk = max(1, hero.min_atk - bonus)
        hero.max_atk = max(hero.min_atk, hero.max_atk - bonus)
        hero.charismatic_speaker_bonus = 0

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
    hero.warrior_bleed_dots = []       # Savage Slash stacks don't carry between rounds

    # v0.6.14: combat fatigue resets between rounds — each new fight starts fresh
    hero.fatigue_def_loss  = 0
    hero.fatigue_save_tier = 0


    # --- Fallen Warrior: Defence Warp cleanup (boss-only debuff) ---
    if hasattr(hero, "defence_warp_phase"):
        if hasattr(hero, "defence_warp_original_defence"):
            hero.defence = hero.defence_warp_original_defence
        del hero.defence_warp_phase
    if hasattr(hero, "defence_warp_original_defence"):
        del hero.defence_warp_original_defence

    # --- Berserk ---
    # Design rule: berserk carries over between rounds while charges remain.
    # The only full clear is the round 4-5 interlude (full_rest=True), which
    # is the one true "a day passes" moment.
    if full_rest:
        if getattr(hero, "berserk_active", False):
            print("\n\U0001fa78 The berserk rage fades as the day passes. You feel the cold return.")
        hero.berserk_active  = False
        hero.berserk_bonus   = 0
        hero.berserk_turns   = 0
        hero.berserk_used    = False
        hero.berserk_pending = False
    else:
        # Mid-tournament: only clean up if charges are spent.
        # Otherwise let the fury carry into the next fight.
        if getattr(hero, "berserk_turns", 0) <= 0:
            hero.berserk_active  = False
            hero.berserk_bonus   = 0
            hero.berserk_pending = False
            # berserk_used: leave True until check_berserk_trigger() naturally
            # resets it when HP recovers above 20% (handled in that function).

    # Optional: clear “one-fight only” flags here if you have them
    # hero.defense_break = False   # example if you store something like this

    # --- Psychic debuff cleanup (Flayed One — Psychic Shred) ---
    _clear_psychic_debuff(hero)

    # --- Psychic drown cleanup (Drowned One — Psychic Drown) ---
    _clear_psychic_drown(hero)

    # --- Flayed One debuff cleanup — restores player ATK/DEF to pre-fight base ---
    if hasattr(hero, "flayed_base_min_atk"):
        hero.min_atk = hero.flayed_base_min_atk
        hero.max_atk = hero.flayed_base_max_atk
        hero.defence = hero.flayed_base_defence
        del hero.flayed_base_min_atk
        del hero.flayed_base_max_atk
        del hero.flayed_base_defence

    # --- Charged Jagged Rock — reset pool and charges between rounds ---
    # Enemy debuff naturally expires with the enemy; player ATK returns to base+base_atk
    rock = hero.equipment.get("trinket") if hasattr(hero, "equipment") else None
    if rock and getattr(rock, "name", "") == "Charged Jagged Rock":
        old_charges = getattr(hero, "cjr_charges", 0)
        hero.cjr_pool    = 0.0
        hero.cjr_charges = 0
        base_atk = getattr(rock, "base_atk", 0)
        base_min = getattr(hero, "cjr_base_min_atk", hero.min_atk)
        base_max = getattr(hero, "cjr_base_max_atk", hero.max_atk)
        hero.min_atk = base_min + base_atk
        hero.max_atk = base_max + base_atk
        if old_charges > 0:
            print(wrap("⚡ The stone's charge fades as you rest — ATK bonus reset."))

def blind_damage_multiplier(hero):
    """
    v0.6.15: Unified blind damage multiplier across all attack paths.
      blind_turns == 3 → turn 1 of blind, the SKIP turn (handled separately in
                         the turn loop; this returns 0.0 as a defensive value
                         in case something else asks).
      blind_turns == 2 → turn 2 of blind, attacks deal 50% damage.
      blind_turns <= 1 → no longer blind (or about to fade), full damage.
    """
    turns = getattr(hero, "blind_turns", 0)
    if turns >= 3:
        return 0.0
    if turns == 2:
        return 0.5
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






   






















def try_death_defier(hero, reason="", enemy=None):
    # Only triggers if you'd die right now
    if hero.hp > 0:
        return False

    if hero.death_defier and hero.death_defier_active and not hero.death_defier_used:
        hero.death_defier_used = True
        hero.death_defier_active = False
        # v0.6.21: per-fight flag for SCORING. death_defier_used has run-wide
        # semantics (it's only reset at the full-rest interlude), so once Death
        # Defier fires it stays True for the rest of the run — handing out the
        # +50 score bonus on every subsequent fight. This flag is reset at
        # battle_inner start and read by record_fight_score.
        hero.death_defier_used_this_fight = True

        # Survival HP scales with skill rank
        # River Spirit (rank 0 starter blessing) = rank 1 effect
        rank = _dd_effective_rank(hero)
        survive_pcts = {1: 0.0, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
        pct = survive_pcts.get(rank, 0.0)
        survive_hp = max(1, int(hero.max_hp * pct)) if pct > 0 else 1
        hero.hp = survive_hp

        print()
        dd_name = "River Spirit" if _dd_display_as_river(hero) else "Death Defier"
        print(wrap(f"💀✨ {dd_name} surges — you refuse to die! (Survived at {survive_hp} HP)"))
        if reason:
            print(wrap(f"(Saved from: {reason})"))

        # Death's Apprentice mastery — death itself reaches through the apprentice's body
        # to mark the enemy. Deals 20% of hero's max HP as psychic damage (ignores defence).
        # Requires an enemy reference — DoT deaths without a specific source don't trigger.
        if enemy is not None and "death_apprentice" in getattr(hero, "titles", set()):
            if getattr(enemy, "hp", 0) > 0:
                rebound = max(1, int(hero.max_hp * 0.20))
                enemy.hp = max(0, enemy.hp - rebound)

                # Flavor dialogue — random variant per trigger, cold and mythological.
                # Death is not friendly, not cruel — death is a bookkeeper. You are an
                # interesting case, not a beloved student. The arena itself responds.
                dialogue_variants = [
                    (
                        "The arena floor trembles. From somewhere beneath the world, a voice arrives — "
                        "not loud, but PRESENT, the way cold is present:",
                        "\"This one is not yours to take.\"",
                        f"{enemy.display_name} staggers as the voice passes through them — something in their mind tears."
                    ),
                    (
                        "A pressure settles over the arena. The torches flicker low. When the voice comes, "
                        "it does not echo — echoes require space, and this voice fills all of it:",
                        "\"Mark this one. The ledger is not yet closed.\"",
                        f"{enemy.display_name} clutches their head as the words reach them — not heard, but KNOWN."
                    ),
                    (
                        "The ground shivers as if something vast has shifted, far below. The voice that follows "
                        "is patient, uninterested, exact:",
                        "\"Return. The accounting is incomplete.\"",
                        f"{enemy.display_name} reels — the voice has touched something in them that was never meant to be touched."
                    ),
                    (
                        "Dust rises from the stones without wind. The voice comes from no direction, from every "
                        "direction, ancient and bored:",
                        "\"Not yet. I am still watching.\"",
                        f"{enemy.display_name}'s eyes go wide — something has just LOOKED at them from very far away."
                    ),
                    (
                        "The arena groans like old stone under impossible weight. A voice older than language "
                        "speaks once, and once is enough:",
                        "\"Continue. I would see what you become.\"",
                        f"{enemy.display_name} falters — somewhere in the back of their skull, a name has just been written down."
                    ),
                ]
                setup, voice, reaction = random.choice(dialogue_variants)
                print()
                print(wrap(setup))
                print(wrap(voice))
                print(wrap(reaction))
                print(wrap(
                    f"🕯️ Death's Apprentice: {enemy.display_name} takes {rebound} psychic damage."
                ))

        show_health(hero)
        return True

    return False











# =============================
# AP INFLATION HELPER
# =============================

def get_ap_inflation(warrior) -> int:
    """
    Returns the current AP cost inflation from Psychic Drown stacks.
    Standard: each stack adds +1. Max 3 stacks = +3 inflation.
    Chimera version: fixed +2 inflation regardless of stack count.
    Returns 0 if no drown active.
    """
    if getattr(warrior, "drown_stacks", 0) <= 0:
        return 0
    chimera_inflation = getattr(warrior, "drown_chimera_inflation", 0)
    if chimera_inflation > 0:
        return chimera_inflation
    return getattr(warrior, "drown_stacks", 0)


def inflated_ap_cost(base_cost: int, warrior) -> int:
    """Returns base AP cost + current drown inflation."""
    return base_cost + get_ap_inflation(warrior)










# =============================
# WATERLOGGED STONE TRINKET
# =============================



# =============================
# WATERLOGGED STONE TRINKET
# =============================

def _stone_absorb_charge(warrior):
    """
    Called after any enemy special move fires.
    If Waterlogged Stone is equipped in trinket slot and not full, adds 1 charge.
    Uses a per-turn flag to prevent double-charging if called from multiple paths.
    """
    # Guard against double-charge on same turn
    if getattr(warrior, "_stone_charged_this_turn", False):
        return
    warrior._stone_charged_this_turn = True

    trinket = warrior.equipment.get("trinket") if hasattr(warrior, "equipment") else None
    if not trinket or trinket.name != "Waterlogged Stone":
        return
    if trinket.stone_charges < trinket.stone_max_charges:
        trinket.stone_charges += 1
        print(wrap(
            f"\U0001faa8 The Waterlogged Stone pulses — it absorbs the energy! "
            f"({trinket.stone_charges}/{trinket.stone_max_charges} charges)"
        ))
    else:
        print(wrap(
            f"\U0001faa8 The Waterlogged Stone is already full "
            f"({trinket.stone_charges}/{trinket.stone_max_charges}) — release charges to make room!"
        ))


def chimera_fury_add(enemy, warrior, rank_used):
    """
    Called whenever the player uses a ranked skill while fighting Young Chimera.
    Adds rank_used * 10 fury charge. At 100: sets fury_overloading flag and warns player.
    The actual surge fires at the START of Chimera's next turn (in the combat loop).
    """
    if enemy.name != "Young Chimera":
        return
    gain = rank_used * 10
    enemy.chimera_fury_charge = min(100, enemy.chimera_fury_charge + gain)
    bar_filled = int(enemy.chimera_fury_charge / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    print(wrap(
        f"⚡ Chimera Fury: [{bar}] {enemy.chimera_fury_charge}%  "
        f"(+{gain} from Rank {rank_used} skill)"
    ))
    if enemy.chimera_fury_charge >= 100 and not enemy.chimera_fury_overloading:
        enemy.chimera_fury_overloading = True
        print(wrap(
            f"\n🔴 THE YOUNG CHIMERA IS OVERLOADING! "
            f"It has absorbed your power — brace yourself!"
        ))


def chimera_passive_heal(enemy, warrior):
    """
    v0.6.16: Fires at the START of every Chimera turn, unconditionally.
    Heals Chimera for 10% of its max HP (capped at max_hp). Previously
    only fired after a successful basic-attack hit — now ticks every turn
    regardless of action (basic, special, or skipped via blind).
    """
    if enemy.name != "Young Chimera":
        return
    heal_amount = max(1, int(enemy.max_hp * 0.10))
    old_hp = enemy.hp
    enemy.hp = min(enemy.max_hp, enemy.hp + heal_amount)
    actual_heal = enemy.hp - old_hp
    if actual_heal > 0:
        print(wrap(
            f"🌿 The Chimera's body knits itself together! "
            f"+{actual_heal} HP ({enemy.hp}/{enemy.max_hp})"
        ))


def use_consumable_trinket(warrior, trinket):
    """
    Player action — crush a one-shot consumable trinket to trigger its effect.
    The trinket is removed from the equipment slot after use (consumed forever).
    Returns True if used, False if cancelled.

    Currently supports:
      - Trinket of Berserk: force-activates Berserk mode for 2 turns
    """
    if not trinket or not getattr(trinket, "consume_on_use", False):
        print("This trinket cannot be crushed.")
        return False

    # Confirm with player — this is permanent
    confirm = input(wrap(
        f"Crush the {trinket.name}? It will be destroyed permanently. (y/n): "
    )).strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return False

    # --- Trinket of Berserk ---
    if trinket.name == "Trinket of Berserk":
        if getattr(warrior, "berserk_active", False):
            print(wrap("You're already in a berserk rage — crushing it now would be wasted."))
            return False
        print(wrap(f"You crush the {trinket.name} in your fist. Shards bite your palm — "
                   "and the pain wakes something hungry behind your eyes."))
        print("🩸🔥 BERSERK MODE ACTIVATED!")
        warrior.berserk_active = True
        warrior.berserk_bonus  = 6 + getattr(warrior, "max_rage", 0)
        warrior.berserk_turns  = 2
        warrior.berserk_used   = True   # blocks the natural <=10% HP trigger this cycle
        warrior.berserk_used_this_fight = True   # v0.6.21: per-fight scoring flag
        warrior.berserk_pending = False
        # Consume the trinket — remove from slot, do NOT return to inventory
        warrior.equipment["trinket"] = None
        return True

    # Fallback for future consumables
    print(wrap(f"{trinket.name} has no defined crush effect."))
    return False


def use_waterlogged_stone(warrior):
    """
    Player action — release charges from Waterlogged Stone to restore AP.
    Player chooses how many charges to release (1 up to current count).
    Each charge restores 1 AP, capped at max_ap + 1.
    Costs the player's turn.
    """
    stone = warrior.equipment.get("trinket") if hasattr(warrior, "equipment") else None
    if not stone or stone.name != "Waterlogged Stone":
        print("No Waterlogged Stone equipped.")
        return False
    if stone.stone_charges <= 0:
        print(wrap("\U0001faa8 The Waterlogged Stone has no charges — wait for the enemy to use a special move."))
        return False

    print(f"\n\U0001faa8 Waterlogged Stone: {stone.stone_charges}/{stone.stone_max_charges} charges")
    print(f"   Current AP: {warrior.ap}/{warrior.max_ap}  (can overfill to {warrior.max_ap + 1})")
    print(f"   How many charges to release? (1-{stone.stone_charges}, or 0 to cancel)")

    raw = _real_input("> ").strip()
    if raw == "0" or raw == "":
        print("Cancelled.")
        return False
    try:
        amount = int(raw)
    except ValueError:
        print("Invalid input.")
        return False

    if amount < 1 or amount > stone.stone_charges:
        print(f"Enter a number between 1 and {stone.stone_charges}.")
        return False

    # Release charges — cap at max_ap + 1
    ap_cap     = warrior.max_ap + 1
    ap_gained  = min(amount, ap_cap - warrior.ap)
    if ap_gained <= 0:
        print(wrap("Your AP is already at maximum — release would be wasted. Wait until you spend some AP first."))
        return False

    warrior.ap        = min(warrior.ap + ap_gained, ap_cap)
    stone.stone_charges -= amount

    # Track bonus action
    is_bonus = not getattr(warrior, "bonus_action_used", False)
    if is_bonus:
        warrior.bonus_action_used = True

    print(wrap(
        f"\U0001faa8 You release {amount} charge(s) from the Waterlogged Stone — "
        f"+{ap_gained} AP restored! (AP: {warrior.ap}/{warrior.max_ap})"
    ))
    if amount > ap_gained:
        wasted = amount - ap_gained
        print(wrap(f"   ({wasted} charge(s) were absorbed by the overflow cap and wasted.)"))
    show_health(warrior)
    return "bonus" if is_bonus else True   # bonus = no turn cost





# =============================
# HERO MOVES
# =============================

def _dd_display_as_river(hero):
    """
    Returns True only when the skill should still be presented as 'River Spirit'.
    This is the rank-0 starter blessing state — once the player invests any SP
    into Death Defier, the name flips to 'Death Defier' even though
    death_defier_river stays True (it persists as the permanent 0-AP / -1 SP
    discount earned from the river path).
    """
    return (getattr(hero, "death_defier_river", False)
            and hero.skill_ranks.get("death_defier", 0) == 0)


def _dd_effective_rank(hero):
    """
    Return the rank used for survive-HP and other rank-scaled effects.
    River Spirit at rank 0 behaves as rank 1 (the starter blessing).
    Once the player invests SP, actual rank takes over.
    """
    rank = hero.skill_ranks.get("death_defier", 0)
    if rank == 0 and getattr(hero, "death_defier_river", False):
        return 1
    return rank


def _dd_ap_cost(hero):
    """
    Single source of truth for Death Defier AP cost.
    Base cost by rank: 1/1/2/3/4 (ranks 1-5).
    River Spirit path: -1 AP at every rank (river's gift carries forward).
    Death's Apprentice mastery: additional -1 AP. Discounts stack, floor at 0.
    """
    rank = hero.skill_ranks.get("death_defier", 1)
    if rank <= 2:
        cost = 1
    elif rank == 3:
        cost = 2
    elif rank == 4:
        cost = 3
    else:
        cost = 4  # rank 5 — maximum cost

    if getattr(hero, "death_defier_river", False):
        cost -= 1
    if "death_apprentice" in getattr(hero, "titles", set()):
        cost -= 1

    # Floor: river path can reach 0 AP (the river's gift). Non-river players
    # always pay at least 1 AP — Death's Apprentice discount alone can't make
    # Death Defier free. Free casts are the unique reward of the river path.
    min_cost = 0 if getattr(hero, "death_defier_river", False) else 1
    return max(min_cost, cost)


def activate_death_defier(hero):
    """
    Uses the hero's turn to activate Death Defier.
    AP cost by rank: 1/1/2/3/4 (ranks 1-5).
    River Spirit path: -1 AP at every rank.
    Death's Apprentice mastery: additional -1 AP.
    Floor: 0 AP only with River Spirit (non-river players always pay >=1 AP).
    Resulting tables:
      Normal:        1 / 1 / 2 / 3 / 4
      River:         0 / 0 / 1 / 2 / 3
      Normal + DA:   1 / 1 / 1 / 2 / 3
      River + DA:    0 / 0 / 0 / 1 / 2
    Does no damage on activation, just sets the passive that triggers on lethal damage.
    """
    dd_name = "River Spirit" if _dd_display_as_river(hero) else "Death Defier"

    if hero.death_defier_used:
        print(f"You've already used {dd_name} this tournament.")
        return False

    if hero.death_defier_active:
        print(f"{dd_name} is already active.")
        return False

    if not hero.death_defier:
        print("You don't have that ability.")
        return False

    # AP cost — uses shared helper so skill menu display and activation always match.
    cost = _dd_ap_cost(hero)

    if hero.ap < cost:
        print(f"Not enough AP. {dd_name} costs {cost} AP.")
        return False

    hero.ap -= cost
    hero.death_defier_active = True

    # Show survival HP so player knows what they're getting
    rank = _dd_effective_rank(hero)
    survive_pcts = {1: 0.0, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
    pct = survive_pcts.get(rank, 0.0)
    survive_hp = max(1, int(hero.max_hp * pct)) if pct > 0 else 1

    print()

    if _dd_display_as_river(hero):
        # River Spirit — rank-0 starter blessing flavour
        print(wrap(
            "You close your eyes and reach out into the cold depths. "
            "The river remembers you. "
            "You feel its current wrap around your heartbeat and hold it steady — "
            "your life force is now tied to its flow."
        ))
    elif "crushed_essence" in getattr(hero, "story_flags", set()):
        # Good path — mysterious figure, deity of life
        print(wrap(
            "You bow your head and say a silent prayer to your deity of life. "
            "Something ancient and warm stirs at the edge of your awareness. "
            "You feel it settle around you like armour. "
            "Death will not come so easily today."
        ))
    elif "returned_essence" in getattr(hero, "story_flags", set()):
        # Evil path — Beast Gods
        print(wrap(
            "You begin to chant under your breath, drawing on the power of the Beast Gods. "
            "Their investment in you pulses through your bones like a current. "
            "You are worth more alive. "
            "You will not die so easily today."
        ))
    else:
        # Neutral — pre-moral choice or no path taken
        print(wrap(
            "You plant your feet and refuse. "
            "Whatever comes at you — you will not fall."
        ))

    print(wrap(f"({dd_name} active — survive at {survive_hp} HP. AP remaining: {hero.ap})"))
    return True

def heal_ap_cost(rank: int, warrior=None) -> int:
    base = 1 if rank <= 2 else (2 if rank <= 4 else 3)
    return base + (get_ap_inflation(warrior) if warrior else 0)
HEAL_PERCENTS = {
    1: 0.10,
    2: 0.20,
    3: 0.30,
    4: 0.40,
    5: 0.50,
}

def choose_heal_rank_smart(hero, learned_rank: int):
    learned_rank = min(learned_rank, 5)

    affordable = [
        r for r in range(1, learned_rank + 1)
        if hero.ap >= heal_ap_cost(r, hero)
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
            cost = heal_ap_cost(r, hero)
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
            if 1 <= r <= learned_rank and hero.ap >= heal_ap_cost(r, hero):
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
            affordable = [r for r in range(1, learned + 1) if hero.ap >= heal_ap_cost(r, hero)]
            if not affordable:
                print("You don't have enough AP for First Aid.")
                return False

            chosen_rank = max(affordable)
            cost = heal_ap_cost(chosen_rank, hero)

            if cost == 3:
                pct = int(HEAL_PERCENTS[chosen_rank] * 100)
                ans = input(
                    f"\n🩹 First Aid will use Rank {chosen_rank} ({pct}%) for {cost} AP. Use it? (y/n): "
                ).strip().lower()
                if ans != "y":
                    print("You hold off for now.")
                    return False
        else:
            chosen_rank = choose_heal_rank_smart(hero, learned)
            if chosen_rank is None:
                return False

    # Sanitize chosen rank
    chosen_rank = max(1, min(int(chosen_rank), learned))

    # Spend AP
    ap_cost = heal_ap_cost(chosen_rank, hero)
    if hero.ap < ap_cost:
        print("Not enough AP!")
        return False
    hero.ap -= ap_cost
    # TODO: trigger_pressure_feedback(hero, enemy) — enemy not in scope here yet

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

    # Rank 4+: also cure Paralyze, Burn, and Rot
    # Rot is cleared BEFORE the heal — but the heal is reduced by the percentage
    # of max HP that was lost to rot (nastier the rot, smaller the recovery).
    heal_penalty = 0.0
    if chosen_rank >= 4:
        if getattr(hero, "paralyzed", False):
            hero.paralyzed = False
            hero.paralyze_turns = 0
            cured.append("Paralyze")
        if getattr(hero, "burns", None):
            hero.burns = []
            hero.fire_stacks = 0
            cured.append("Burn")
        if getattr(hero, "rot_max_hp_loss", 0) > 0:
            rot_loss    = hero.rot_max_hp_loss
            rot_base    = getattr(hero, "rot_base_max_hp", hero.max_hp + rot_loss)
            heal_penalty = rot_loss / rot_base  # e.g. 0.40 if 40% max HP was rotted
            clear_rot(hero, restore_hp=False, source="first_aid")
            cured.append("Rot")

    # Apply heal (no overheal) — reduced if rot was cured this turn
    percent     = HEAL_PERCENTS[chosen_rank]
    eff_percent = percent * (1.0 - heal_penalty)
    heal_amount = math.ceil(hero.max_hp * eff_percent)

    before = hero.hp
    hero.hp = min(hero.max_hp, hero.hp + heal_amount)
    actual = hero.hp - before

    print()
    if heal_penalty > 0:
        print(wrap(
            f"🩹 You fight through the rot to patch yourself up. "
            f"The corruption sapped your recovery — you heal {actual} HP "
            f"({int(eff_percent * 100)}% effective, reduced from {int(percent * 100)}% "
            f"by {int(heal_penalty * 100)}% rot penalty)."
        ))
    else:
        print(wrap(
            f"🩹 You apply first aid, tending to your wounds. "
            f"You recover {actual} HP "
            f"({int(percent * 100)}%, Rank {chosen_rank})."
        ))

    # Rank 5: also cure all status affects

    if chosen_rank >= 5:
        clear_all_status_effects(hero)
        cured.append("all statuses")
    if cured:
        print(wrap(f"✨ First Aid cures: {', '.join(cured)}!"))

    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    show_health(hero)

    return True

def war_cry_ap_cost(rank: int, warrior=None) -> int:
    # R1-2: 1 AP, R3-4: 2 AP, R5: 3 AP (+ drown inflation)
    base = 1 if rank <= 2 else (2 if rank <= 4 else 3)
    return base + (get_ap_inflation(warrior) if warrior else 0)


WAR_CRY_PERCENTS = {
    1: 0.10,   # 10% ATK bonus, min +1
    2: 0.15,   # 15% ATK bonus, min +1
    3: 0.20,   # 20% ATK bonus, min +1
    4: 0.25,   # 25% ATK bonus, min +1
    5: 0.35,   # 35% ATK bonus, min +1
}
WAR_CRY_TURNS = {
    1: 3,
    2: 3,
    3: 3,
    4: 4,
    5: 3,
}

def war_cry(hero, chosen_rank=None):
    learned = hero.skill_ranks.get("war_cry", 0)
    if learned <= 0:
        print("You haven't learned War Cry.")
        return False

    learned = min(learned, 5)

    # Pick rank: in combat we auto-pick highest affordable (like your Heal/PS pattern)
    if chosen_rank is None:
        affordable = [r for r in range(1, learned + 1) if hero.ap >= war_cry_ap_cost(r, hero)]
        if not affordable:
            print("You don't have enough AP for War Cry.")
            return False
        chosen_rank = max(affordable)
    else:
        chosen_rank = max(1, min(int(chosen_rank), learned))

    cost = war_cry_ap_cost(chosen_rank, hero)
    if hero.ap < cost:
        print("Not enough AP!")
        return False

    pct   = WAR_CRY_PERCENTS[chosen_rank]
    turns = WAR_CRY_TURNS[chosen_rank]
    bonus = max(1, math.ceil(hero.max_atk * pct))

    hero.ap -= cost
    # TODO: trigger_pressure_feedback(hero, enemy) — enemy not in scope here yet

    # Re-cast friendly: overwrite bonus & reset duration
    hero.war_cry_bonus = bonus
    hero.war_cry_turns = turns
    hero.war_cry_skip_first_tick = True

    print()
    print(wrap(
        f"🗣️ You unleash a WAR CRY! "
        f"(Rank {chosen_rank}, Cost {cost} AP)\n"
        f"Your attacks surge with power: +{bonus} to attack rolls for {turns} turns. "
        f"({int(pct * 100)}% of ATK)"
    ))
    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    return True



def power_strike_ap_cost(rank: int, warrior=None) -> int:
    # R1-2: 1 AP, R3-4: 2 AP, R5: 3 AP (+ drown inflation)
    base = 1 if rank <= 2 else (2 if rank <= 4 else 3)
    return base + (get_ap_inflation(warrior) if warrior else 0)


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

    affordable = [r for r in range(1, learned_rank + 1) if warrior.ap >= power_strike_ap_cost(r, warrior)]
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
            cost = power_strike_ap_cost(r, warrior)
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

        cost = power_strike_ap_cost(chosen, warrior)
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

    ap_cost = power_strike_ap_cost(chosen_rank, warrior)
    if warrior.ap < ap_cost:
        print("Not enough AP!")
        return False
    warrior.ap -= ap_cost
    trigger_pressure_feedback(warrior, enemy)

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
    # BLINDNESS scaling — unified via blind_damage_multiplier()
    # v0.6.15: was using inline 0.5/0.75 table; now uses the helper so basic
    # attack and Power Strike share the same blind math (50% at blind_turns=2,
    # full at blind_turns<=1, 0 at blind_turns=3 which is the skip turn).
    # --------------------------
    raw_for_defence = total_raw
    if getattr(warrior, "blind_turns", 0) > 0:
        mult = blind_damage_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"👁️ Blinded! Power Strike hits at {int(mult * 100)}% power.")

    final = enemy.apply_defence(raw_for_defence, attacker=warrior)
    enemy.hp = max(0, enemy.hp - final)

    # Exposed bonus: +1 true damage if enemy DEF is at -1
    if getattr(enemy, "psychic_exposed", False) and final > 0:
        enemy.hp = max(0, enemy.hp - 1)
        final += 1

    blocked = raw_for_defence - final

    # --------------------------
    # One-line breakdown
    # --------------------------
    print(f"\nPOWER STRIKE! (Rank {chosen_rank}, Cost {ap_cost} AP)")

    parts = [f"Roll {base_roll}"] + hit_parts_txt + [f"Power Strike {impact}"]
    if raw_for_defence != total_raw:
        mult = blind_damage_multiplier(warrior)
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

    # Log to combat log as a special attack
    log_attack(warrior.name, enemy.display_name, total_raw, final, blocked,
               effect_tag=f"[Power Strike Rank {chosen_rank}]",
               is_player=True, is_special=True)

    return True


# ===============================
# DEFENCE BREAK
# ===============================

DEFENCE_BREAK_STATS = {
    #  rank: (pct, turns)
    1: (0.10, 2),
    2: (0.20, 2),
    3: (0.30, 3),
    4: (0.40, 3),
    5: (0.50, 3),
}

def defence_break_ap_cost(rank: int) -> int:
    # R1-2: 2 AP, R3-4: 3 AP, R5: 4 AP
    if rank <= 2:
        return 2
    elif rank <= 4:
        return 3
    return 4


def defence_break(warrior, enemy, chosen_rank=None):
    """
    Defence Break — player skill (unlocks at level 3, taught by Fallen Warrior).

    Reduces enemy DEF by a percentage for a number of turns.
    Takes effect immediately (turn 0) then lasts for full combat rounds.
    Refreshes if used again while active — does not stack.
    If enemy has 0 DEF, deals 1 true damage instead.
    Minimum reduction is always 1 (can never do nothing).
    """
    learned = warrior.skill_ranks.get("defence_break", 0)
    if learned <= 0:
        print("You haven't learned Defence Break.")
        return False

    # Clamp to learned rank
    max_rank = min(learned, 5)
    if chosen_rank is None:
        chosen_rank = max_rank
    chosen_rank = max(1, min(int(chosen_rank), max_rank))

    ap_cost = defence_break_ap_cost(chosen_rank)
    if warrior.ap < ap_cost:
        print(f"Not enough AP for Defence Break Rank {chosen_rank}. (Need {ap_cost}, have {warrior.ap})")
        return False

    warrior.ap -= ap_cost
    pct, turns = DEFENCE_BREAK_STATS[chosen_rank]

    # -----------------------------------------------
    # Calculate reduction — minimum 1
    # -----------------------------------------------
    base_def  = getattr(enemy, "defence_break_base_def", enemy.defence)
    reduction = max(1, math.floor(base_def * pct))
    new_def   = max(0, base_def - reduction)

    # Apply — store base so refreshes don't compound
    enemy.defence_break_active   = True
    enemy.defence_break_turns    = turns
    enemy.defence_break_pct      = pct
    enemy.defence_break_base_def = base_def
    enemy.defence                = new_def

    # -----------------------------------------------
    # Fully eroded OR naturally 0 DEF — deal 1 true damage
    # -----------------------------------------------
    if new_def == 0:
        enemy.hp = max(0, enemy.hp - 1)
        if base_def == 0:
            # Enemy had no armour to begin with
            print(wrap(
                f"⚔️ Defence Break! (Rank {chosen_rank}, Cost {ap_cost} AP)\n"
                f"{enemy.display_name} has no armour — the strike finds a gap! (+1 true damage)"
            ))
        else:
            # Break fully eroded their DEF
            print(wrap(
                f"⚔️ Defence Break! (Rank {chosen_rank}, Cost {ap_cost} AP)\n"
                f"{enemy.display_name}'s guard is shattered! "
                f"DEF {base_def} → 0  (-{reduction}, {turns} turns) +1 true damage!"
            ))
    else:
        print(wrap(
            f"⚔️ Defence Break! (Rank {chosen_rank}, Cost {ap_cost} AP)\n"
            f"{enemy.display_name}'s guard crumbles! "
            f"DEF {base_def} → {new_def}  (-{reduction}, {turns} turns)"
        ))
    show_health(warrior)
    return True


def _tick_defence_break(enemy):
    """
    Called once per enemy turn. Counts down defence_break_turns.
    Restores DEF when it expires.
    """
    if not getattr(enemy, "defence_break_active", False):
        return

    enemy.defence_break_turns -= 1
    if enemy.defence_break_turns <= 0:
        # Restore base DEF
        base = getattr(enemy, "defence_break_base_def", enemy.defence)
        enemy.defence             = base
        enemy.defence_break_active   = False
        enemy.defence_break_turns    = 0
        enemy.defence_break_pct      = 0.0
        enemy.defence_break_base_def = base
        print(wrap(f"🛡️ {enemy.display_name}'s defences recover — Defence Break wore off."))


def _clear_defence_break(enemy):
    """Full reset — called in reset_between_rounds."""
    base = getattr(enemy, "defence_break_base_def", enemy.defence)
    enemy.defence                = base
    enemy.defence_break_active   = False
    enemy.defence_break_turns    = 0
    enemy.defence_break_pct      = 0.0
    enemy.defence_break_base_def = getattr(enemy, "defence", 0)


def _award_defence_break(warrior):
    """
    Called on Fallen Warrior kill.
    - Rank 0: unlock at rank 1 with flavour narrative.
    - Rank 1-4: free rank up, sharpened by the fight.
    - Rank 5: already mastered, print flavour only.
    """
    cur = warrior.skill_ranks.get("defence_break", 0)
    mx  = SKILL_DEFS["defence_break"]["max_rank"]

    if cur == 0:
        warrior.skill_ranks["defence_break"] = 1
        warrior.skills.add("defence_break")
        warrior.skill_progress.pop("defence_break", None)
        print(wrap(
            "\n⚔️  Watching the Fallen Warrior's technique, something clicks. "
            "You've learned how to crack an enemy's guard."
        ))
        print("✨ SKILL UNLOCKED: Defence Break (Rank 1)")
    elif cur < mx:
        warrior.skill_ranks["defence_break"] = cur + 1
        warrior.skill_progress.pop("defence_break", None)
        print(wrap(
            "\n⚔️  The Fallen Warrior's relentless pressure sharpens your technique."
        ))
        print(f"✨ Defence Break upgraded: Rank {cur} → {cur + 1}")
    else:
        print(wrap(
            "\n⚔️  You already know everything the Fallen Warrior could teach you "
            "about breaking armour."
        ))


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

class PlayAgainException(Exception):
    """
    Raised by prompt_play_again() when the player chooses to play again.
    Bubbles up through every game-end caller to the __main__ block, which
    catches it and restarts the run with fully reset global state.

    Why this instead of os.execv: os.execv silently fails in some hosted
    environments (Replit, frozen PyInstaller exes) — the game prints
    "Restarting..." but the process never actually replaces. An exception
    that the main loop catches works in every environment.
    """
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
        paralyze_chance=0.0,  # weapon proc: chance to paralyze on hit (Goblin Shortbow)
        paralyze_turns=0,     # weapon proc: how many turns paralyze lasts
        drain_bonus=0,        # accessory proc: bonus damage + heal (Soul Pendant)
        drain_heal_min=0,     # accessory proc: min HP recovered on drain hit
        drain_heal_max=0,     # accessory proc: max HP recovered on drain hit
        bleed_turns=0,        # weapon proc: bleed duration (Javelina Tusk / Goblin War Blade)
        bleed_dmg_min=0,      # weapon proc: min bleed damage per tick
        bleed_dmg_max=0,      # weapon proc: max bleed damage per tick (0 = flat bleed_dmg_min)
        element_erosion=0,    # accessory proc: immediate DEF reduction on acid hit (Acid Sac normal+)
        atk_debuff=0.0,       # legacy field — kept for compatibility, unused by CJR
        def_debuff=0.0,       # legacy field — kept for compatibility, unused by CJR
        debuff_turns=0,       # legacy field — kept for compatibility, unused by CJR
        max_charges=0,        # trinket: max charges (Charged Jagged Rock)
        base_atk=0,           # trinket: flat ATK bonus on equip by rarity (Charged Jagged Rock)
        fill_rate=0.0,        # trinket: pool fill per damage point through defence (Charged Jagged Rock)
        max_ap_bonus=0,       # trinket: passive max AP increase (Waterlogged Stone normal+)
        max_rage_bonus=0,     # trinket/ring: passive max_rage (adrenaline cap) increase
        consume_on_use=False, # trinket: one-shot consumable (Trinket of Berserk)
        stone_max_charges=0,  # trinket: max charges stone can hold
        stone_charges=0,      # trinket: current charges accumulated this run
        enemy_atk_drain=1,    # trinket: enemy ATK lost per charge (Charged Jagged Rock)
        enemy_def_drain=1,    # trinket: enemy DEF lost per charge (Charged Jagged Rock)
        rot_chance=0.0,      # weapon proc: chance to apply rot on hit (Rusted Sword)
        rot_stacks=0,         # weapon proc: rot stacks applied per proc
        rot_hp_per_stack=0,   # weapon proc: max HP drained per rot stack
        two_handed=False,    # v0.6.16: 2H weapons block the other hand slot
        sockets=None,        # v0.6.16: None → compute from slot+rarity; list → explicit
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
        self.bleed_dmg_min    = bleed_dmg_min
        self.bleed_dmg_max    = bleed_dmg_max
        self.atk_debuff       = atk_debuff
        self.def_debuff       = def_debuff
        self.debuff_turns     = debuff_turns
        self.max_charges      = max_charges
        self.base_atk         = base_atk
        self.fill_rate        = fill_rate
        self.max_ap_bonus     = max_ap_bonus
        self.max_rage_bonus   = max_rage_bonus
        self.consume_on_use   = consume_on_use
        self.stone_max_charges = stone_max_charges
        self.stone_charges    = stone_charges
        self.enemy_atk_drain  = enemy_atk_drain
        self.enemy_def_drain  = enemy_def_drain
        self.rot_chance       = rot_chance
        self.rot_stacks       = rot_stacks
        self.rot_hp_per_stack  = rot_hp_per_stack
        # v0.6.16: 2H weapons block second hand slot
        self.two_handed       = two_handed
        # v0.6.16: socket system. None means "compute from rarity at this
        # item's slot"; an explicit list preserves the socket state through
        # save/load. Each socket holds either None (empty) or another
        # Equipment instance (the socketed component).
        if sockets is None:
            self.sockets = self._compute_initial_sockets()
        else:
            self.sockets = sockets

    # ---------- Socket system helpers (v0.6.16) ----------
    # Class-level tables mirror crafter.SOCKET_COUNTS_BY_RARITY but inlined
    # here to avoid an import dependency on crafter.
    _SOCKET_COUNTS_WEAPON = {
        "poor":      0,
        "normal":    1,
        "uncommon":  1,
        "rare":      2,
        "epic":      2,
        "legendary": 2,
        "mythril":   2,
    }
    _SOCKET_COUNTS_ARMOR = {
        # No "poor" entry — Poor armor doesn't exist in v0.6.16
        "normal":    1,
        "uncommon":  1,
        "rare":      2,
        "epic":      2,
        "legendary": 2,
        "mythril":   2,
    }
    _SOCKETABLE_SLOTS = {"weapon", "armor"}

    def _compute_initial_sockets(self):
        """Initial socket layout based on slot + rarity. Called at construction."""
        if self.slot not in self._SOCKETABLE_SLOTS:
            return []
        if self.slot == "weapon":
            count = self._SOCKET_COUNTS_WEAPON.get(self.rarity, 0)
        else:  # armor
            count = self._SOCKET_COUNTS_ARMOR.get(self.rarity, 0)
        return [None] * count

    def socket_count(self):
        """Total socket count (filled + empty)."""
        return len(self.sockets) if hasattr(self, "sockets") else 0

    def empty_socket_count(self):
        """How many sockets are currently empty."""
        return sum(1 for s in self.sockets if s is None) if hasattr(self, "sockets") else 0

    def filled_sockets(self):
        """List of socketed Equipment instances (no Nones)."""
        return [s for s in self.sockets if s is not None] if hasattr(self, "sockets") else []

    # Rarity colour icons — shared by all display methods
    RARITY_ICONS = {
        "starter":   "",
        "poor":      "⬜",
        "normal":    "🟦",
        "uncommon":  "🟩",
        "rare":      "🟨",
        "epic":      "🟪",
        "legendary": "🟥",
        "mythril":   "🟧",
    }

    def stat_lines(self):
        """Returns a list of stat strings (no header). Used by short_label and full_detail."""
        lines = []
        if self.atk_min or self.atk_max:
            lines.append(f"  ⚔️  ATK +{self.atk_min}/+{self.atk_max}")
        if self.defence:
            lines.append(f"  🛡️  DEF +{self.defence}")
        if self.max_hp:
            lines.append(f"  ❤️  HP +{self.max_hp}")
        if self.max_ap_bonus:
            lines.append(f"  🔵 Max AP +{self.max_ap_bonus}")
        if self.max_rage_bonus:
            lines.append(f"  🔥 Adrenaline cap +{self.max_rage_bonus}")
        if self.consume_on_use:
            lines.append(f"  💥 One-shot: consumed on use")
        if self.element:
            dots = getattr(self, "element_max_dots", 1)
            dot_txt = f", max {dots} stacks" if dots > 1 else ""
            lines.append(f"  ✨ {self.element.title()} {self.element_damage} dmg ({self.element_turns} turns{dot_txt})")
        if self.element_erosion:
            lines.append(f"  🧪 Acid Erosion: -{self.element_erosion} DEF on hit")
        if self.proc_chance > 0:
            lines.append(f"  ⚡ {int(self.proc_chance*100)}% chance +{self.proc_bonus} bonus dmg")
        if self.rot_chance > 0:
            lines.append(f"  🟫 {int(self.rot_chance*100)}% chance to rot ({self.rot_stacks} stack(s), -{self.rot_hp_per_stack} max HP/stack)")
        if self.blind_chance > 0:
            lines.append(f"  👁️  {int(self.blind_chance*100)}% chance to blind")
        if self.drain_bonus > 0:
            lines.append(f"  🩸 Drain: +{self.drain_bonus} dmg, heals {self.drain_heal_min}–{self.drain_heal_max} HP")
        if self.paralyze_chance > 0:
            lines.append(f"  🧊 {int(self.paralyze_chance*100)}% chance to paralyze ({self.paralyze_turns} turn{'s' if self.paralyze_turns != 1 else ''})")
        if self.bleed_turns > 0:
            dmg_str = f"{self.bleed_dmg_min}–{self.bleed_dmg_max}" if self.bleed_dmg_max > self.bleed_dmg_min else str(self.bleed_dmg_min)
            lines.append(f"  🩹 Bleed: {dmg_str} dmg/turn for {self.bleed_turns} turns")
        if self.atk_debuff > 0:
            txt = f"  📉 On hit: -{int(self.atk_debuff*100)}% ATK"
            if self.def_debuff > 0:
                txt += f", -{int(self.def_debuff*100)}% DEF"
            if self.debuff_turns:
                txt += f" ({self.debuff_turns} turns)"
            lines.append(txt)
        elif self.def_debuff > 0:
            lines.append(f"  📉 On hit: -{int(self.def_debuff*100)}% DEF ({self.debuff_turns} turns)")
        if self.max_charges > 0:
            base_str = f"+{self.base_atk} ATK (base), " if self.base_atk > 0 else ""
            lines.append(f"  ⚡ {base_str}+1 ATK per charge (max {self.max_charges})")
            atk_d = getattr(self, "enemy_atk_drain", 1)
            def_d = getattr(self, "enemy_def_drain", 1)
            drain_str = f"-{atk_d} ATK" + (f" / -{def_d} DEF" if def_d > 0 else "")
            lines.append(f"  📉 Each charge: enemy {drain_str}")
        return lines

    def short_label(self):
        """One-liner (or a few lines) for inventory lists."""
        if self.rarity == "starter":
            header = self.name
        else:
            icon        = self.RARITY_ICONS.get(self.rarity, "⬜")
            rarity_word = self.rarity.title()
            header      = f"{icon} {rarity_word} {self.name}"
        stat_rows   = self.stat_lines()
        if stat_rows:
            return header + "\n" + "\n".join(stat_rows)
        return header

    def full_detail(self):
        """Detailed loot card shown on drop and on inspect in inventory."""
        slot_word   = self.slot.title()
        divider     = "─" * 36
        if self.rarity == "starter":
            name_line = f"  {self.name}"
        else:
            icon        = self.RARITY_ICONS.get(self.rarity, "⬜")
            rarity_word = self.rarity.title()
            name_line   = f"  {icon} {rarity_word} {self.name}"
        lines = [
            divider,
            name_line,
            f"  Slot: {slot_word}",
            divider,
        ]
        stat_rows = self.stat_lines()
        if stat_rows:
            lines += stat_rows
        else:
            lines.append("  (no bonus stats)")
        if self.stone_max_charges > 0:
            lines.append(f"  🌀 Charges: {self.stone_charges}/{self.stone_max_charges}")
        lines.append(divider)
        return "\n".join(lines)

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
RARITY_ORDER = ["poor", "normal", "uncommon", "rare", "epic", "legendary", "mythril"]

def roll_rarity(monster_level=1, round_num=0):
    """Returns a rarity string based on monster level and round.
    rare/epic/legendary/mythril are not yet on the natural drop table —
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
    "mythril":  (5, 7, 0, 3),   # 3 stacks, 7 turns each
}

FIRE_SAC_STATS = {
    # Format: (element_damage, element_turns, def_restore_turns, max_dots)
    "poor":     (2, 1, 0, 1),
    "normal":   (2, 2, 0, 1),
    "uncommon": (3, 3, 0, 1),
    "rare":     (4, 4, 0, 2),   # 2 stacks, 4 turns each
    "epic":     (4, 5, 0, 2),   # 2 stacks, 5 turns each
    "legendary":(5, 6, 0, 3),   # 3 stacks, 6 turns each
    "mythril":  (6, 7, 0, 3),   # 3 stacks, 7 turns each
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
    "mythril":  (7, 6, 6, 3, 5),   # 3 stacks, 6 turns each, -5 DEF
}

# ----------------------------------------------------------------
# Charged Jagged Rock  (accessory) — Flayed One drop
# A psychic-residue-soaked rock that weakens enemy resolve on hit.
# Does NOT stack. Refreshes duration on each application.
# poor:     10% ATK reduction, 1 turn
# normal:   10% ATK + DEF reduction, 2 turns
# uncommon: 15% ATK + DEF reduction, 3 turns
# ----------------------------------------------------------------
# Charged Jagged Rock  (accessory) — Flayed One drop
# Psychic residue accumulates on enemy each hit — no duration, persists until fight ends.
# Reduction = floor(base_stat * accumulated_pct), capped at round(base_stat * per_hit_pct).
# ATK floor is 1 (can never reach 0). DEF can reach 0.
# poor:     10% per hit → cap = round(base × 0.10)
# normal:   15% per hit → cap = round(base × 0.15)
# uncommon: 20% per hit → cap = round(base × 0.20), lands in 1 hit on most enemies
# rare:     25% per hit → cap = round(base × 0.25)
# epic:     30% per hit → cap = round(base × 0.30)
# legendary:35% per hit → cap = round(base × 0.35)
# mythril:  40% per hit → cap = round(base × 0.40)
# ----------------------------------------------------------------
CHARGED_JAGGED_ROCK_STATS = {
    # base_atk    : flat ATK bonus applied immediately on equip (before charges)
    # max_charges : how many full charges the rock can hold
    # fill_rate   : pool points gained per 1 point of damage dealt through defence
    #               (min 0.10 per hit regardless). Pool per charge = 10.0.
    # enemy_atk_drain / enemy_def_drain : flat enemy stat loss per charge reached
    # Player gains +1 ATK per charge regardless of rarity.
    # Resets at rest between rounds.
    "poor":      {"base_atk": 0, "max_charges": 3, "fill_rate": 0.10, "enemy_atk_drain": 1, "enemy_def_drain": 0},
    "normal":    {"base_atk": 1, "max_charges": 4, "fill_rate": 0.15, "enemy_atk_drain": 1, "enemy_def_drain": 1},
    "uncommon":  {"base_atk": 2, "max_charges": 5, "fill_rate": 0.20, "enemy_atk_drain": 2, "enemy_def_drain": 1},
    "rare":      {"base_atk": 3, "max_charges": 6, "fill_rate": 0.25, "enemy_atk_drain": 2, "enemy_def_drain": 2},
    "epic":      {"base_atk": 4, "max_charges": 7, "fill_rate": 0.30, "enemy_atk_drain": 3, "enemy_def_drain": 3},
    "legendary": {"base_atk": 5, "max_charges": 8, "fill_rate": 0.35, "enemy_atk_drain": 4, "enemy_def_drain": 4},
    "mythril":   {"base_atk": 6, "max_charges": 9, "fill_rate": 0.40, "enemy_atk_drain": 5, "enemy_def_drain": 5},
}

# ----------------------------------------------------------------
# Waterlogged Stone  (trinket) — Drowned One drop
# Passively absorbs charges when enemy uses a special move.
# Player spends a turn to release charges and restore AP.
# Charges persist between rounds. Capped at max_ap + 1 on release.
# poor:     max 1 charge, +1 DEF
# normal:   max 2 charges, +1 DEF
# uncommon: max 3 charges, +1 DEF
# rare:     max 4 charges, +1 DEF, +1 max AP
# epic:     max 5 charges, +2 DEF, +2 max AP
# legendary:max 6 charges, +3 DEF, +3 max AP
# ----------------------------------------------------------------
WATERLOGGED_STONE_STATS = {
    "poor":     {"max_charges": 1, "defence": 1, "max_ap_bonus": 0},
    "normal":   {"max_charges": 2, "defence": 1, "max_ap_bonus": 0},
    "uncommon": {"max_charges": 3, "defence": 1, "max_ap_bonus": 0},
    "rare":     {"max_charges": 4, "defence": 1, "max_ap_bonus": 1},
    "epic":     {"max_charges": 5, "defence": 2, "max_ap_bonus": 2},
    "legendary":{"max_charges": 6, "defence": 3, "max_ap_bonus": 3},
    "mythril":  {"max_charges": 7, "defence": 4, "max_ap_bonus": 4},
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
    "mythril":  {"defence": 4, "max_hp": 4},
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
    "mythril":  {"defence": 5, "max_hp": 5},
}

# ----------------------------------------------------------------
# Bone Sword  (weapon)
# poor:     +1 atk min/max
# normal:   +1 atk, +1 def
# uncommon: +2 atk, +1 def
# ----------------------------------------------------------------
# Rusted Sword: no defence — the blade is too corroded to parry.
# Rot proc: temporarily drains enemy max HP per stack, capped at 30% of enemy max HP.
# Resets between fights. Poor starts at 15% since payoff (-1 max HP) is minimal.
RUSTED_SWORD_STATS = {
    "poor":     {"atk_min": 1, "atk_max": 1, "defence": 0, "rot_chance": 0.15, "rot_stacks": 1, "rot_hp_per_stack": 1},
    "normal":   {"atk_min": 1, "atk_max": 1, "defence": 0, "rot_chance": 0.25, "rot_stacks": 2, "rot_hp_per_stack": 1},
    "uncommon": {"atk_min": 2, "atk_max": 2, "defence": 0, "rot_chance": 0.40, "rot_stacks": 3, "rot_hp_per_stack": 1},
    "rare":     {"atk_min": 2, "atk_max": 3, "defence": 0, "rot_chance": 0.55, "rot_stacks": 4, "rot_hp_per_stack": 2},
    "epic":     {"atk_min": 3, "atk_max": 3, "defence": 0, "rot_chance": 0.65, "rot_stacks": 5, "rot_hp_per_stack": 3},
    "legendary":{"atk_min": 3, "atk_max": 4, "defence": 0, "rot_chance": 0.75, "rot_stacks": 6, "rot_hp_per_stack": 4},
    "mythril":  {"atk_min": 4, "atk_max": 5, "defence": 0, "rot_chance": 0.90, "rot_stacks": 7, "rot_hp_per_stack": 5},
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
    "mythril":  {"atk_min": 4, "atk_max": 5, "proc_chance": 0.90, "proc_bonus": 4},
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
    "mythril":  {"atk_min": 4, "atk_max": 5, "blind_chance": 1.00},
}

# ----------------------------------------------------------------
# Goblin Shortbow  (weapon) — Goblin Archer drop
# v0.6.19: Rebalanced damage. With v0.6.18 making the bow two-handed,
# the old 1-2 / 2-3 / 2-3 / 3-4 / 3-4 / 4-5 / 5-6 curve was strictly
# worse than 1H weapons of the same tier — you'd lose your off-hand
# slot for less raw damage than a Rusted Sword. New curve makes the
# bow hit notably harder than any 1H weapon at the same tier, with a
# wider spread to reinforce its "variable arrow distance" identity,
# and paralyze stays as the unique control utility on top.
# Wide ATK spread represents variable arrow distance effectiveness.
# Paralyze proc built in — chain guard prevents consecutive lockdown.
# Multi-turn paralyze only unlocks at rare+.
# NOTE: Paralyze Ointment planned as future shop/crafting item —
#       will allow any weapon to gain a paralyze proc via crafting.
# ----------------------------------------------------------------
GOBLIN_SHORTBOW_STATS = {
    "poor":     {"atk_min": 2, "atk_max": 3, "paralyze_chance": 0.15, "paralyze_turns": 1},
    "normal":   {"atk_min": 3, "atk_max": 4, "paralyze_chance": 0.25, "paralyze_turns": 1},
    "uncommon": {"atk_min": 3, "atk_max": 5, "paralyze_chance": 0.35, "paralyze_turns": 1},
    "rare":     {"atk_min": 4, "atk_max": 6, "paralyze_chance": 0.45, "paralyze_turns": 2},
    "epic":     {"atk_min": 5, "atk_max": 7, "paralyze_chance": 0.55, "paralyze_turns": 2},
    "legendary":{"atk_min": 6, "atk_max": 8, "paralyze_chance": 0.65, "paralyze_turns": 3},
    "mythril":  {"atk_min": 7, "atk_max": 9, "paralyze_chance": 0.80, "paralyze_turns": 3},
}


# ----------------------------------------------------------------

# Goblin War Blade  (weapon) — Goblin Warrior drop
# poor:     +2 atk, no bleed (blade too dull)
# normal:   +2 atk, bleed = half ATK roll rounded up min 1, 1 turn
# uncommon: +3 atk, bleed 2 turns
# rare:     +4 atk, bleed 3 turns
# epic:     +5 atk, bleed 4 turns
# legendary:+6 atk, bleed 5 turns
# mythril:  +7 atk, bleed 6 turns
# Bleed damage scales with player's own attack roll — War Cry amplifies it.
GOBLIN_WAR_BLADE_STATS = {
    # T3 weapon — starts with bleed at poor, scales hard
    "poor":      {"atk_min": 3, "atk_max": 3, "bleed_turns": 1, "bleed_dmg_min": 1, "bleed_dmg_max": 1},
    "normal":    {"atk_min": 3, "atk_max": 3, "bleed_turns": 1, "bleed_dmg_min": 1, "bleed_dmg_max": 2},
    "uncommon":  {"atk_min": 4, "atk_max": 4, "bleed_turns": 2, "bleed_dmg_min": 1, "bleed_dmg_max": 3},
    "rare":      {"atk_min": 5, "atk_max": 5, "bleed_turns": 3, "bleed_dmg_min": 2, "bleed_dmg_max": 4},
    "epic":      {"atk_min": 6, "atk_max": 6, "bleed_turns": 4, "bleed_dmg_min": 3, "bleed_dmg_max": 5},
    "legendary": {"atk_min": 7, "atk_max": 7, "bleed_turns": 5, "bleed_dmg_min": 4, "bleed_dmg_max": 6},
    "mythril":   {"atk_min": 8, "atk_max": 8, "bleed_turns": 6, "bleed_dmg_min": 5, "bleed_dmg_max": 7},
}

# Javelina Tusk  (weapon)
# poor:     +2 atk, no bleed
# normal:   +2 atk, 1 turn, 1 dmg
# uncommon: +3 atk, 2 turns, 1-2 dmg
# rare:     +4 atk, 3 turns, 2-3 dmg
# epic:     +5 atk, 4 turns, 2-4 dmg
# legendary:+6 atk, 5 turns, 3-5 dmg
# ----------------------------------------------------------------
JAVELINA_TUSK_STATS = {
    "poor":      {"atk_min": 2, "atk_max": 2, "bleed_turns": 0, "bleed_dmg_min": 0, "bleed_dmg_max": 0},
    "normal":    {"atk_min": 2, "atk_max": 2, "bleed_turns": 1, "bleed_dmg_min": 1, "bleed_dmg_max": 1},
    "uncommon":  {"atk_min": 3, "atk_max": 3, "bleed_turns": 2, "bleed_dmg_min": 1, "bleed_dmg_max": 2},
    "rare":      {"atk_min": 4, "atk_max": 4, "bleed_turns": 3, "bleed_dmg_min": 2, "bleed_dmg_max": 3},
    "epic":      {"atk_min": 5, "atk_max": 5, "bleed_turns": 4, "bleed_dmg_min": 2, "bleed_dmg_max": 4},
    "legendary": {"atk_min": 6, "atk_max": 6, "bleed_turns": 5, "bleed_dmg_min": 3, "bleed_dmg_max": 5},
    "mythril":   {"atk_min": 7, "atk_max": 7, "bleed_turns": 6, "bleed_dmg_min": 4, "bleed_dmg_max": 6},
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
    "mythril":  {"drain_bonus": 6, "drain_heal_min": 4, "drain_heal_max": 8},
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
    "mythril":  {"defence": 6, "max_hp": 5},
}

# ----------------------------------------------------------------
# MERCHANT-ONLY ARMORS — fixed tiers, no rarity variants
# ----------------------------------------------------------------
# These are the basic store-bought armors sold by the arena merchant in
# the round 4-5 interlude. Designed to be clearly "store-bought" — no
# random rarity rolls, no procs, no special effects. Just baseline gear.
#
# Tier 1-3 follow the copper/bronze/iron progression — basic metallurgy
# the merchant could plausibly stock. Tier 4 (Frost-iron) is the
# aspirational buy, tied to the world's frost-and-ash atmosphere; rare
# enough that only a gold-rich player walks away with one.
#
# These are FIXED equipment definitions. No STATS-by-rarity dict needed —
# just hardcode in the merchant factory.
#
# DESIGN NOTE: As more merchant-only armors are added, consider promoting
# these to a MERCHANT_ARMOR_DEFS dict with rarity tiers, but for now
# YAGNI — four hardcoded stat blocks live happily in merchant.py.
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# Weapon Core  (weapon) — Fallen Warrior drop
# A mysterious nano-tech artifact that adapts to its wielder.
# Tier 4 item.  Player chooses form immediately on drop.
# Core reverts to a cube after the final fight and is passed to the
# player's son — the form choice here shapes the son's weapon.
#
# Fixed stats — no rarity roll. Milestone drops shouldn't punish bad
# RNG or trivialize the endgame with a lucky legendary. The player
# knows exactly what they're getting and can plan around it.
#
# Lightrender  (One-Handed): +6 ATK, +3 DEF — balanced, keeps accessory slot free.
# Destiny Definer (Two-Handed): +9 ATK, no DEF — raw power, no room for accessories.
# ----------------------------------------------------------------
# ----------------------------------------------------------------
# Tainted Champion's Breastplate  (armor) — Patronus drop (evil path)
# Fixed stats — no rarity. The corruption bleeds power inward — strong defence
# but the taint slowly hollows you out (-5 max HP).
# Piece 1 of the Tainted Champion's Armor set.
# ----------------------------------------------------------------
TAINTED_CHAMPIONS_BREASTPLATE_STATS = {"defence": 7, "max_hp": -5}

# Fixed stats — no rarity roll on boss drops.
# One-Handed: balanced, lets player keep accessory slot free.
# Two-Handed: raw power, trades defence for more ATK.
WEAPON_CORE_ONEHANDED_STATS = {"atk_min": 6, "atk_max": 6, "defence": 0}  # v0.6.16: DEF removed — shields handle defense now
WEAPON_CORE_TWOHANDED_STATS = {"atk_min": 9, "atk_max": 9, "defence": 0}

# Keep old dicts as aliases so any remaining references don't crash
WEAPON_CORE_DEFENSIVE_STATS = {"fixed": WEAPON_CORE_ONEHANDED_STATS}
WEAPON_CORE_OFFENSIVE_STATS  = {"fixed": WEAPON_CORE_TWOHANDED_STATS}

# ----------------------------------------------------------------
# Chimera Scale  (armor) — Young Chimera drop
# Fixed stats — no rarity roll. Piece 1 of the Chimera Scale set.
# Power comes from the full set bonus, not the individual piece.
# ----------------------------------------------------------------
CHIMERA_SCALE_STATS = {"defence": 5, "max_hp": 3}

def _make_weapon_core(corrupted=False):
    """
    Called after the Fallen Warrior's death scene.
    Good path  (corrupted=False): Lightrender (1h) or Destiny Definer (2h)
    Evil path  (corrupted=True):  Duskbringer (1h) or Destiny Destroyer (2h)
    Player chooses 1-handed or 2-handed — choice is permanent.
    """
    print("\n" + "═" * 50)
    if corrupted:
        print("   ⚙️  THE WEAPON CORE WRITHES")
    else:
        print("   ⚙️  THE WEAPON CORE STIRS")
    print("═" * 50)

    if corrupted:
        print(wrap(
            "The Fallen Warrior's weapon dissolves into a dense, humming cube "
            "that floats into your palm. It pulses — but something is wrong. "
            "A darkness seeps through it, the Beast Gods' mark bleeding into the metal."
        ))
        print()
        print(wrap("It writhes between two dark forms. Choose — it will not change again."))
        print()
        d_name = "Duskbringer"
        o_name = "Destiny Destroyer"
        d_stats = {"atk_min": 7, "atk_max": 7, "defence": -3}
        o_stats = {"atk_min": 10, "atk_max": 10, "defence": -5}


        d_flavour = "The cube blackens and elongates — Duskbringer takes shape. Its edge drinks light rather than reflects it."
        o_flavour = "The cube tears itself into a massive two-handed blade — Destiny Destroyer. It hums with borrowed rage."
    else:
        print(wrap(
            "The Fallen Warrior's weapon dissolves into a dense, humming cube "
            "that floats into your palm. It pulses faintly — waiting. "
            "You feel it reading you, deciding what to become."
        ))
        print()
        print(wrap("It can take one of two forms. Choose carefully — it will not change again."))
        print()
        d_name = "Lightrender"
        o_name = "Destiny Definer"
        d_stats = WEAPON_CORE_ONEHANDED_STATS
        o_stats = WEAPON_CORE_TWOHANDED_STATS
        d_flavour = "The cube flattens and elongates — Lightrender takes shape. Its edge catches light and holds it, as if the blade remembers the sun."
        o_flavour = "The cube unfolds into a massive two-handed sword — Destiny Definer. The weight of it is immense. This blade does not just cut. It decides."

    d = d_stats
    o = o_stats

    print(f"  1) {d_name}  — One-Handed Sword")
    print(f"       ⚔️  ATK +{d['atk_min']}   🛡️  DEF {'+' if d['defence'] >= 0 else ''}{d['defence']}")
    print(f"       Balanced. Lets you keep an accessory equipped.")
    print()
    print(f"  2) {o_name}  — Two-Handed Sword")
    print(f"       ⚔️  ATK +{o['atk_min']}   🛡️  DEF {'+' if o['defence'] >= 0 else ''}{o['defence']}")
    print(f"       Raw power. No room for accessories.")
    print()

    while True:
        choice = _real_input("Choose a form (1 or 2): ").strip()
        if choice == "1":
            stats = d
            form_name = d_name
            is_two_handed = False
            print(wrap(f"\n{d_flavour}"))
            break
        elif choice == "2":
            stats = o
            form_name = o_name
            is_two_handed = True
            print(wrap(f"\n{o_flavour}"))
            break
        else:
            print("Enter 1 or 2.")

    print()
    return Equipment(
        name    = form_name,
        slot    = "weapon",
        rarity  = "legendary",
        atk_min = stats["atk_min"],
        atk_max = stats["atk_max"],
        defence = stats["defence"],
        two_handed = is_two_handed,   # v0.6.16: 2H weapons block the other hand slot
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
            name           = "Rusted Sword",
            slot           = "weapon",
            rarity         = rarity,
            tier           = 1,
            atk_min        = RUSTED_SWORD_STATS[rarity]["atk_min"],
            atk_max        = RUSTED_SWORD_STATS[rarity]["atk_max"],
            defence        = RUSTED_SWORD_STATS[rarity]["defence"],
            rot_chance     = RUSTED_SWORD_STATS[rarity]["rot_chance"],
            rot_stacks     = RUSTED_SWORD_STATS[rarity]["rot_stacks"],
            rot_hp_per_stack = RUSTED_SWORD_STATS[rarity]["rot_hp_per_stack"],
        ),

        "Imp": lambda: Equipment(
            name        = "Imp Trident",
            slot        = "weapon",
            rarity      = rarity,
            tier        = 1,
            atk_min     = IMP_TRIDENT_STATS[rarity]["atk_min"],
            atk_max     = IMP_TRIDENT_STATS[rarity]["atk_max"],
            proc_chance = IMP_TRIDENT_STATS[rarity]["proc_chance"],
            proc_bonus  = IMP_TRIDENT_STATS[rarity]["proc_bonus"],
        ),

        "Young Goblin": lambda: Equipment(
            name        = "Goblin Dagger",
            slot        = "weapon",
            rarity      = rarity,
            tier        = 1,
            atk_min     = GOBLIN_DAGGER_STATS[rarity]["atk_min"],
            atk_max     = GOBLIN_DAGGER_STATS[rarity]["atk_max"],
            blind_chance = GOBLIN_DAGGER_STATS[rarity]["blind_chance"],
        ),
        "Goblin Archer": lambda: Equipment(
            name              = "Goblin Shortbow",
            slot              = "weapon",
            rarity            = rarity,
            tier              = 2,
            atk_min           = GOBLIN_SHORTBOW_STATS[rarity]["atk_min"],
            atk_max           = GOBLIN_SHORTBOW_STATS[rarity]["atk_max"],
            paralyze_chance   = GOBLIN_SHORTBOW_STATS[rarity]["paralyze_chance"],
            paralyze_turns    = GOBLIN_SHORTBOW_STATS[rarity]["paralyze_turns"],
            two_handed        = True,   # v0.6.18: bow requires both hands
        ),

        # ── Tier 2 new drops ───────────────────────────────────
        "Goblin Warrior": lambda: Equipment(
            name          = "Goblin War Blade",
            slot          = "weapon",
            rarity        = rarity,
            tier          = 3,
            atk_min       = GOBLIN_WAR_BLADE_STATS[rarity]["atk_min"],
            atk_max       = GOBLIN_WAR_BLADE_STATS[rarity]["atk_max"],
            bleed_turns   = GOBLIN_WAR_BLADE_STATS[rarity]["bleed_turns"],
            bleed_dmg_min = GOBLIN_WAR_BLADE_STATS[rarity]["bleed_dmg_min"],
            bleed_dmg_max = GOBLIN_WAR_BLADE_STATS[rarity]["bleed_dmg_max"],
        ),
        "Javelina": lambda: Equipment(
            name          = "Javelina Tusk",
            slot          = "weapon",
            rarity        = rarity,
            tier          = 2,
            atk_min       = JAVELINA_TUSK_STATS[rarity]["atk_min"],
            atk_max       = JAVELINA_TUSK_STATS[rarity]["atk_max"],
            bleed_turns   = JAVELINA_TUSK_STATS[rarity]["bleed_turns"],
            bleed_dmg_min = JAVELINA_TUSK_STATS[rarity]["bleed_dmg_min"],
            bleed_dmg_max = JAVELINA_TUSK_STATS[rarity]["bleed_dmg_max"],
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

        # ── Tier 3 drops ───────────────────────────────────────
        "Flayed One": lambda: Equipment(
            name            = "Charged Jagged Rock",
            slot            = "trinket",
            rarity          = rarity,
            base_atk        = CHARGED_JAGGED_ROCK_STATS[rarity]["base_atk"],
            max_charges     = CHARGED_JAGGED_ROCK_STATS[rarity]["max_charges"],
            fill_rate       = CHARGED_JAGGED_ROCK_STATS[rarity]["fill_rate"],
            enemy_atk_drain = CHARGED_JAGGED_ROCK_STATS[rarity]["enemy_atk_drain"],
            enemy_def_drain = CHARGED_JAGGED_ROCK_STATS[rarity]["enemy_def_drain"],
        ),

        "Drowned One": lambda: Equipment(
            name              = "Waterlogged Stone",
            slot              = "trinket",
            rarity            = rarity,
            defence           = WATERLOGGED_STONE_STATS[rarity]["defence"],
            max_ap_bonus      = WATERLOGGED_STONE_STATS[rarity]["max_ap_bonus"],
            stone_max_charges = WATERLOGGED_STONE_STATS[rarity]["max_charges"],
            stone_charges     = 0,
        ),

        # ── Boss drops (evil path) ─────────────────────────────
        "Patronus": lambda: Equipment(
            name    = "Tainted Champion's Breastplate",
            slot    = "armor",
            rarity  = "legendary",
            defence = TAINTED_CHAMPIONS_BREASTPLATE_STATS["defence"],
            max_hp  = TAINTED_CHAMPIONS_BREASTPLATE_STATS["max_hp"],
        ),

        # ── Debug-only drops ───────────────────────────────────
        "Young Chimera": lambda: Equipment(
            name    = "Chimera Scale",
            slot    = "armor",
            rarity  = "legendary",
            defence = CHIMERA_SCALE_STATS["defence"],
            max_hp  = CHIMERA_SCALE_STATS["max_hp"],
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
        # 🧪 Acid erosion + 💨 Combat fatigue (fight-only): reduce effective defence
        # Both are independent stacking sources; sum them and subtract from base.
        # ---------------------------------------------
        acid_loss    = getattr(self, "acid_defence_loss", 0)
        fatigue_loss = getattr(self, "fatigue_def_loss", 0)
        effective_def = max(0, self.defence - acid_loss - fatigue_loss)


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

        # ---------------------------------------------
        # 💀 Negative defence penalty — each point below 0 adds 10% bonus damage
        # e.g. DEF -3 = +30% incoming damage
        # ---------------------------------------------
        raw_def = self.defence - acid_loss - fatigue_loss
        if raw_def < 0:
            bonus_pct = abs(raw_def) * 0.10
            bonus_dmg = max(1, round(actual * bonus_pct))
            actual += bonus_dmg

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

        # Psychic debuff base stats — stored here so any enemy can safely
        # receive Charged Jagged Rock debuffs without crashing on first hit.
        # _apply_psychic_debuff_to_stats() reads these; _clear_psychic_debuff()
        # restores from them. Always reflects spawn stats.
        self.psychic_base_min_atk = min_atk
        self.psychic_base_max_atk = max_atk
        self.psychic_base_defence = defence
        self.psychic_atk_debuff   = 0.0
        self.psychic_def_debuff   = 0.0
        self.psychic_debuff_turns = 0
        self.psychic_debuff_skip  = False
        self.psychic_exposed      = False   # DEF at -1, player deals +1 true damage

        # Defence Break fields (player skill — applied to enemy)
        self.defence_break_active   = False
        self.defence_break_turns    = 0
        self.defence_break_pct      = 0.0
        self.defence_break_base_def = defence  # base DEF before any break

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
    

                    
                                
        
# ============================================================
# v0.6.20: STATS DISPLAY HELPERS — set bonus & dual-wield tracking
# ============================================================
# Pure-read helpers used by show_combat_stats and show_all_game_stats.
# Return lists of strings (or empty list if nothing to show). Callers
# decide whether to print a header or skip when the list is empty.
#
# These helpers READ state only — they never mutate. Set bonuses and
# the dual-wield modifier are applied at equip-time by apply_all_set_bonuses
# and apply_dual_wield_modifier; these helpers just surface what's active
# so the player can see what their gear is doing.

def _format_set_bonus_lines(hero):
    """
    Build display lines for Wolf-Hide and Dire Wolf set status.
    Shows: piece count, currently-active threshold bonuses, and what
    the next threshold unlocks (if any). Returns [] if no set pieces
    equipped at all.
    """
    try:
        from crafter import (
            wolf_set_active_pieces, dire_wolf_set_active_pieces,
            pack_hunter_active, apex_predator_active,
        )
    except ImportError:
        return []

    wolf_n = wolf_set_active_pieces(hero)
    dire_n = dire_wolf_set_active_pieces(hero)

    if wolf_n == 0 and dire_n == 0:
        return []

    lines = []

    # Wolf-Hide bonuses by threshold (must mirror apply_wolf_set_bonus)
    if wolf_n > 0:
        active = []
        if wolf_n >= 2: active.append("+5 max HP")
        if wolf_n >= 3: active.append("+1 max AP")
        if wolf_n >= 4: active.append("+2 DEF, +2 ATK")
        if pack_hunter_active(hero):
            active.append("Pack Hunter: +10% basic atk, 50% bleed-on-hit")

        next_unlock = None
        if wolf_n == 1: next_unlock = "(2pc unlocks +5 max HP)"
        elif wolf_n == 2: next_unlock = "(3pc unlocks +1 max AP)"
        elif wolf_n == 3: next_unlock = "(4pc unlocks +2 DEF/ATK + Pack Hunter)"

        lines.append(f"🐺 Wolf-Hide: {wolf_n}/4 pieces")
        if active:
            for bonus in active:
                lines.append(f"   • {bonus}")
        if next_unlock:
            lines.append(f"   {next_unlock}")

    # Dire Wolf bonuses by threshold (must mirror apply_dire_wolf_set_bonus)
    if dire_n > 0:
        active = []
        if dire_n >= 2: active.append("+8 max HP")
        if dire_n >= 3: active.append("+2 max AP")
        if dire_n >= 4: active.append("+3 DEF, +3 ATK")
        if apex_predator_active(hero):
            active.append("Apex Predator: +10% basic atk, 5% lifesteal")

        next_unlock = None
        if dire_n == 1: next_unlock = "(2pc unlocks +8 max HP)"
        elif dire_n == 2: next_unlock = "(3pc unlocks +2 max AP)"
        elif dire_n == 3: next_unlock = "(4pc unlocks +3 DEF/ATK + Apex Predator)"

        lines.append(f"🐺 Dire Wolf: {dire_n}/4 pieces")
        if active:
            for bonus in active:
                lines.append(f"   • {bonus}")
        if next_unlock:
            lines.append(f"   {next_unlock}")

    return lines


def _format_dual_wield_lines(hero):
    """
    Build display lines for dual-wield ATK breakdown. Shows main-hand
    full contribution, off-hand halved contribution, and Dual Wielder
    title bonus (if held). Returns [] when not dual-wielding.

    Source of truth: apply_dual_wield_modifier — off_atk halved via
    floor(off_atk / 2), and Dual Wielder title adds +1/+1.
    """
    main = hero.equipment.get("main_hand")
    off  = hero.equipment.get("off_hand")
    if main is None or off is None:
        return []
    if getattr(main, "slot", None) != "weapon" or getattr(off, "slot", None) != "weapon":
        return []

    main_min, main_max = main.atk_min, main.atk_max
    off_full_min, off_full_max = off.atk_min, off.atk_max
    off_half_min, off_half_max = off_full_min // 2, off_full_max // 2

    lines = ["⚔️  Dual Wielding:"]
    lines.append(f"   Main: {main.name} ({main_min}-{main_max} ATK, full)")
    lines.append(f"   Off:  {off.name} ({off_full_min}-{off_full_max} → {off_half_min}-{off_half_max} ATK, halved)")

    if "dual_wielder" in getattr(hero, "titles", set()):
        lines.append("   Dual Wielder title: +1/+1 ATK passive")
    else:
        lines.append("   (Dual Wielder title unlocks +1/+1 ATK passive)")

    return lines


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
            "main_hand":    None,   # v0.6.16: was "weapon" — now holds weapon OR shield
            "off_hand":    None,   # v0.6.16: second hand slot for shields / off-hand
            "armor":     None,
            "accessory": None,
            "trinket":   None,
            "finger_1":  None,
            "finger_2":  None,
            "helm":      None,   # v0.6.16: crafted gear (Wolf-Hide Hood etc.)
            "cape":      None,   # v0.6.16: crafted gear (Wolf-Hide Cloak etc.)
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
                "burn_cream": 0,
                "cure_all": 0,         # Clears poison/burn/blind/paralysis (not psychic)
                "elixir": 0,           # 50% HP + 50% AP combo restore
                "frostpine_tonic": 0,  # Unique starting item — gifted by Elwyn in prologue
                # ── Progression potions (v0.6.13) — out-of-combat only ──
                "skill_rank_up": 0,    # ranks up one learned skill by 1
                "stat_point":    0,    # +2 stat points (assigned immediately)
                "skill_point":   0,    # +2 skill points (spent immediately)
            }
        else:
            self.potions = potions

        # ------------------------------------------------------------------
        # PROGRESSION
        # ------------------------------------------------------------------
        self.level = 1
        self.xp_to_lvl = 15
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
            "heal":           0,
            "power_strike":   0,
            "war_cry":        0,
            "defence_break":  0,
            "death_defier":   0,
        }
        self.skill_progress = {}

        # ------------------------------------------------------------------
        # TRACKING & STORY
        # ------------------------------------------------------------------
        self.titles          = set()
        self.active_title    = None        # which title is currently displayed
        self.fate_titles     = set()       # death/failure narrative markers
        self.achievements    = set()       # milestone completions
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

        # Rot — max HP drain applied by Brittle Skeleton special / Chimera borrowed move
        # Clears on: regular rest, long rest, Patronus intervention, Chimera intervention, Rank 4+ First Aid
        # Does NOT restore on level-up (max HP just lifts, player heals naturally)
        self.rot_max_hp_loss   = 0   # total max HP currently lost to rot
        self.rot_base_max_hp   = 0   # snapshot of max_hp before rot was first applied

        # Bleed — reserved for Thief enemies / future content
        self.bleed_turns        = 0
        self.warrior_bleed_dots = []   # Goblin Warrior Savage Slash stacks
        self.bonus_action_used  = False  # 1 free potion/stone use per fight

        # Skip turns — used by paralyze application on any target
        self.skip_turns = 0

        # ------------------------------------------------------------------
        # FUTURE CLASS PLACEHOLDERS
        # ------------------------------------------------------------------

        # Mage — spell resource (Mage subclass will set real values)
        self.mana     = 0
        self.max_mana = 0

        # Thief — placeholder section reserved here

    # ---------- v0.6.16: Hand-slot helpers ----------
    def get_weapon(self):
        """Return the weapon in either hand slot, or None.
        Skips items whose slot is 'shield'. Single source of truth for
        'what weapon does the hero have?' — all combat code reads via
        this rather than equipment['weapon'] (which no longer exists)."""
        for slot_name in ("main_hand", "off_hand"):
            item = self.equipment.get(slot_name)
            if item is not None and getattr(item, "slot", None) != "shield":
                return item
        return None

    def has_shield_equipped(self):
        """v0.6.16: True if either hand holds a shield."""
        for slot_name in ("main_hand", "off_hand"):
            item = self.equipment.get(slot_name)
            if item is not None and getattr(item, "slot", None) == "shield":
                return True
        return False

    def get_other_hand(self, hand_slot):
        """v0.6.16: Given 'main_hand' returns 'off_hand', and vice versa."""
        return "off_hand" if hand_slot == "main_hand" else "main_hand"

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
            dd_name = "River Spirit" if _dd_display_as_river(self) else "Death Defier"
            if getattr(self, "death_defier_used", False):
                right_lines.append(f"💀 {dd_name}: USED")
            elif getattr(self, "death_defier_active", False):
                right_lines.append(f"💀 {dd_name}: READY")
            else:
                right_lines.append(f"💀 {dd_name}: available")

        # Gear — short names on one line separated by pipes
        equipped = getattr(self, "equipment", {})
        gear_names = []
        # v0.6.21: corrected slot keys (was ("weapon", ...) — skipped weapons,
        # shields, helms, capes since the v0.6.16 dict rename).
        for slot in ("main_hand", "off_hand", "armor", "helm", "cape",
                     "accessory", "trinket", "finger_1", "finger_2"):
            item = equipped.get(slot)
            if item:
                extra = f" ({item.stone_charges}/{item.stone_max_charges})" if slot == "trinket" and getattr(item, "stone_max_charges", 0) > 0 else ""
                gear_names.append(f"{item.rarity.title()} {item.name}{extra}")
        if gear_names:
            right_lines.append("🎒 " + "  |  ".join(gear_names))

        # Charged Jagged Rock bar — show when equipped
        cjr_line = cjr_bar(self)
        if cjr_line:
            right_lines.append(cjr_line)

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

            # Show active debuffs on enemy
            psych_pool = getattr(enemy, "psychic_atk_debuff", 0.0)
            exposed    = getattr(enemy, "psychic_exposed", False)
            if psych_pool > 0 or exposed:
                atk_loss = enemy.psychic_base_max_atk - enemy.max_atk
                atk_part = f"ATK -{atk_loss}" if atk_loss > 0 else f"ATK ({int(psych_pool*100)}% residue, building...)"
                if exposed:
                    def_part = "  DEF -1 💀 EXPOSED (+1 dmg taken)"
                else:
                    def_loss = enemy.psychic_base_defence - enemy.defence
                    def_part = f"  DEF -{def_loss}" if def_loss > 0 else ""
                print(f"   🔮 Psychic Residue: {int(psych_pool*100)}%  |  {atk_part}{def_part}")

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

        title_line = f" - {TITLE_DISPLAY.get(getattr(self, 'active_title', None), getattr(self, 'active_title', None))}" if getattr(self, "active_title", None) else ""
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
        # v0.6.21: corrected slot keys to match the v0.6.16 equipment dict.
        # The old ("weapon", ...) loop never matched main_hand/off_hand/helm/
        # cape, so weapons and shields were invisible in the detailed stats.
        slot_labels = {
            "main_hand": "Main Hand", "off_hand": "Off Hand", "armor": "Armor",
            "helm": "Helm", "cape": "Cape", "accessory": "Accessory",
            "trinket": "Trinket", "finger_1": "Finger 1", "finger_2": "Finger 2",
        }
        for slot in ("main_hand", "off_hand", "armor", "helm", "cape",
                     "accessory", "trinket", "finger_1", "finger_2"):
            item = equipped.get(slot)
            if item:
                extra = ""
                if slot == "trinket" and getattr(item, "stone_max_charges", 0) > 0:
                    extra = f"  [{item.stone_charges}/{item.stone_max_charges} charges]"
                print(f"   {slot_labels[slot]:<12} {item.short_label()}{extra}")
                any_gear = True
        if not any_gear:
            print("   (nothing equipped)")

        # v0.6.20: Set bonus tracker — visibility for Wolf-Hide / Dire Wolf.
        # Surfaces piece count, what's currently active, and what the next
        # threshold unlocks. Skipped silently if no set pieces equipped.
        set_lines = _format_set_bonus_lines(self)
        if set_lines:
            print()
            for line in set_lines:
                print(line)

        # v0.6.20: Dual-wield ATK breakdown — shows main-hand full / off-hand
        # halved contribution and Dual Wielder title bonus. Skipped silently
        # when not dual-wielding (single weapon, shield, or no weapons).
        dw_lines = _format_dual_wield_lines(self)
        if dw_lines:
            print()
            for line in dw_lines:
                print(line)

        # Death Defier status
        if getattr(self, "death_defier", False):
            if getattr(self, "death_defier_used", False):
                dd = "USED"
            elif getattr(self, "death_defier_active", False):
                dd = "READY"
            else:
                cost = 0 if getattr(self, "death_defier_river", False) else 1
                dd = f"Available (activate {cost} AP)"
            dd_name = "River Spirit" if _dd_display_as_river(self) else "Death Defier"
            print(f"💀 {dd_name}: {dd}")

        # Key debuffs only if active
        if getattr(self, "blind_turns", 0) > 0:
            print(f"👁️  Blind: {self.blind_turns}T remaining")

        if getattr(self, "turn_stop", 0) > 0:
            reason = getattr(self, "turn_stop_reason", "Stunned")
            print(f"⚡ {reason}: {self.turn_stop}T remaining (you lose your action)")
        elif getattr(self, "post_paralyze_guard", False):
            print(f"⚡ Post-Paralyze: recovering (enemy cannot re-paralyze yet)")

        if getattr(self, "poison_active", False) and getattr(self, "poison_turns", 0) > 0:
            print(f"☠️  Poison: {self.poison_amount} dmg/tick  ({self.poison_turns}T remaining)")
        extra_dots = getattr(self, "poison_dots", [])
        if extra_dots:
            active = [d for d in extra_dots if not d.get("skip", False)]
            if active:
                print(f"☠️  Poison stacks: {len(active)} extra dot(s) active")

        if getattr(self, "fire_stacks", 0) > 0:
            burns = getattr(self, "burns", [])
            max_t = max((b.get("turns_left", 0) for b in burns), default=0)
            print(f"🔥 Burn: {self.fire_stacks} stack(s)  (longest {max_t}T remaining)")

        acid_stacks = getattr(self, "acid_stacks", [])
        acid_loss   = getattr(self, "acid_defence_loss", 0)
        if acid_stacks or acid_loss > 0:
            active_acid = [s for s in acid_stacks if not s.get("skip", False)]
            max_t = max((s.get("turns_left", 0) for s in acid_stacks), default=0)
            def_line = f"  DEF -{acid_loss} (currently {self.defence})" if acid_loss > 0 else ""
            print(f"🧪 Acid: {len(acid_stacks)} stack(s)  (longest {max_t}T remaining){def_line}")

        rot_loss = getattr(self, "rot_max_hp_loss", 0)
        if rot_loss > 0:
            rot_base = getattr(self, "rot_base_max_hp", self.max_hp + rot_loss)
            cap_pct  = 60 if hasattr(self, "_chimera_rot") else 50
            print(f"🟫 Rot: Max HP -{rot_loss} (base {rot_base} → current {self.max_hp}, cap {cap_pct}%)")
            print(f"   Clears on rest. Rank 4+ First Aid cures it.")

        if getattr(self, "bleed_turns", 0) > 0:
            dmg_min = getattr(self, "bleed_dmg_min", 2)
            dmg_max = getattr(self, "bleed_dmg_max", dmg_min)
            dmg_str = f"{dmg_min}–{dmg_max}" if dmg_max > dmg_min else str(dmg_min)
            print(f"🩸 Bleed: {dmg_str} dmg/tick  ({self.bleed_turns}T remaining)")
        wbd = getattr(self, "warrior_bleed_dots", [])
        active_wbd = [d for d in wbd if not d.get("skip", False)]
        if active_wbd:
            max_t = max(d.get("turns_left", 0) for d in active_wbd)
            dmg_min = active_wbd[0].get("dmg_min", 3)
            dmg_max = active_wbd[0].get("dmg_max", 5)
            print(f"🩸 Savage Bleed: {len(active_wbd)} stack(s)  {dmg_min}-{dmg_max} dmg/tick  (longest {max_t}T remaining)")

        if getattr(self, "defence_break_active", False):
            turns = getattr(self, "defence_break_turns", 0)
            pct   = getattr(self, "defence_break_pct", 0)
            print(f"🛡️  Defence Break: -{int(pct*100)}% DEF  ({turns}T remaining)")

        if hasattr(self, "defence_warp_phase"):
            phase = self.defence_warp_phase
            orig  = getattr(self, "defence_warp_original_defence", "?")
            WARP_LABELS = {
                0: f"COLLAPSING — DEF dropping to 0 next enemy turn (base {orig})",
                1: f"PARTIAL — DEF at {self.defence}/{orig}  (restoring next enemy turn)",
                2: f"STABILISING — DEF restoring to {orig} next enemy turn",
            }
            print(f"🌀 Defence Warp: {WARP_LABELS.get(phase, 'ACTIVE')}")

        # Psychic Shred debuff
        psych_turns = getattr(self, "psychic_debuff_turns", 0)
        psych_pct   = getattr(self, "psychic_atk_debuff", 0.0)
        psych_skip  = getattr(self, "psychic_debuff_skip", False)
        if psych_turns > 0 and psych_pct > 0:
            def_pct   = getattr(self, "psychic_def_debuff", 0.0)
            base_atk  = getattr(self, "psychic_base_min_atk", self.min_atk)
            base_def  = getattr(self, "psychic_base_defence", self.defence)
            status_tag = " (pending — activates next round)" if psych_skip else ""
            atk_line  = f"ATK -{int(psych_pct * 100)}%  (base {base_atk} → now {self.min_atk}-{self.max_atk})"
            def_line  = f"  |  DEF -{int(def_pct * 100)}%  (base {base_def} → now {self.defence})" if def_pct > 0 else ""
            print(f"🧠 Psychic Shred: {psych_turns}T remaining{status_tag}")
            print(f"   {atk_line}{def_line}")

        # Psychic Drown — AP inflation stacks
        drown_stacks = getattr(self, "drown_stacks", 0)
        drown_turns  = getattr(self, "drown_turns", 0)
        if drown_stacks > 0 and drown_turns > 0:
            inflation    = drown_stacks
            cheapest     = 1 + inflation
            hardened_src = getattr(self, "drown_hardened_source", False)
            DMG_TABLE    = {1: 3, 2: 4, 3: 5} if hardened_src else {1: 2, 2: 3, 3: 4}
            punishment   = DMG_TABLE.get(drown_stacks, 4)
            warn = f"  ⚠️ Max AP {self.max_ap} < {cheapest} — taking {punishment} true dmg/turn!" if self.max_ap < cheapest else ""
            print(f"💧 Psychic Drown: {drown_stacks}/3 stack(s)  ({drown_turns}T remaining)")
            print(f"   All special moves cost +{inflation} AP  (cheapest rank-1 = {cheapest} AP){warn}")
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

        # v0.6.20: Set bonus tracker — same helper as show_combat_stats.
        # Shows Wolf-Hide / Dire Wolf piece count, active bonuses, and the
        # next-threshold preview. Skipped silently if no set pieces equipped.
        set_lines = _format_set_bonus_lines(self)
        if set_lines:
            print()
            for line in set_lines:
                print(line)

        # v0.6.20: Dual-wield breakdown — main full + off halved + title bonus.
        # Skipped silently when not dual-wielding.
        dw_lines = _format_dual_wield_lines(self)
        if dw_lines:
            print()
            for line in dw_lines:
                print(line)

        wc_bonus = getattr(self, "war_cry_bonus", 0)
        wc_turns = getattr(self, "war_cry_turns", 0)

        print("\n🗣️ War Cry:")
        if wc_turns > 0 and wc_bonus > 0:
            print("   Status: ACTIVE")
            print(f"   Bonus Damage: +{wc_bonus}")
            print(f"   Turns Remaining: {wc_turns}")
        else:
            print("   Status: Inactive")

        # --- Skills ---
        print("\n⚔️  Skills:")
        skill_ranks = getattr(self, "skill_ranks", {})
        any_learned = False
        for key, data in SKILL_DEFS.items():
            rank = skill_ranks.get(key, 0)
            if rank > 0:
                any_learned = True
                max_rank  = data["max_rank"]
                tier2     = data.get("tier2_name", "")
                desc      = data["rank_descs"].get(rank, "")
                name_str  = f"{data['name']}"
                rank_str  = f"Rank {rank}/{max_rank}"
                t2_str    = f"  → {tier2} (Rank 6 unlocks)" if rank == max_rank and tier2 else ""
                print(f"   • {name_str} — {rank_str}{t2_str}")
                print(f"     {desc}")
        if not any_learned:
            print("   None learned yet")

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
        display_run_score(self)
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
            self.jackpot_count = getattr(self, "jackpot_count", 0) + 1

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
                self.ap = min(self.ap + 1, self.max_ap)
                print("⚡ Spec: +1 Max AP (+1 AP restored)")
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
        "max_rank": 5,
        # cost to go from rank N -> N+1 (rank 0->1 uses index 0)
        "upgrade_costs": [1, 1, 2, 3, 4],
        "tier2_name": "Double Strike",
        "rank_descs": {
            1: "Bonus damage = half your attack roll (rounded down).          1 AP",
            2: "Bonus damage = half your attack roll (rounded up).            1 AP",
            3: "Bonus damage = \u00be your attack roll (rounded down).             2 AP",
            4: "Bonus damage = \u00be your attack roll (rounded up).               2 AP",
            5: "Bonus damage = your full attack roll.                         3 AP",
        },
    },
    "heal": {
        "name": "First Aid",
        "min_level": 1,
        "max_rank": 5,
        "upgrade_costs": [1, 1, 2, 3, 4],
        "tier2_name": "Triage",
        "rank_descs": {
            1: "Restore 10% max HP.                                           1 AP",
            2: "Restore 20% max HP. Cures Blind and Poison.                   1 AP",
            3: "Restore 30% max HP. Cures Blind and Poison.                   2 AP",
            4: "Restore 40% max HP. Cures Blind, Poison, Paralyze, Burn.      2 AP",
            5: "Restore 50% max HP. Cures all status effects except psychic. 3 AP",
        },
    },
    "war_cry": {
        "name": "War Cry",
        "min_level": 1,
        "max_rank": 5,
        "upgrade_costs": [1, 1, 2, 3, 4],
        "tier2_name": "War Shout",
        "rank_descs": {
            1: "+10% ATK for 3 turns (min +1).                               1 AP",
            2: "+15% ATK for 3 turns (min +1).                               1 AP",
            3: "+20% ATK for 3 turns (min +1).                               2 AP",
            4: "+25% ATK for 4 turns (min +1).                               2 AP",
            5: "+35% ATK for 3 turns (min +1).                               3 AP",
        },
    },
    "defence_break": {
        "name": "Defence Break",
        "min_level": 3,
        "max_rank": 5,
        "upgrade_costs": [1, 2, 3, 4, 4],
        "tier2_name": "Defence Shatter",
        "rank_descs": {
            1: "Reduce enemy DEF 10% (min 1) for 2 turns. 0 DEF: +1 true dmg. 2 AP",
            2: "Reduce enemy DEF 20% (min 1) for 2 turns. 0 DEF: +1 true dmg. 2 AP",
            3: "Reduce enemy DEF 30% (min 1) for 3 turns. 0 DEF: +1 true dmg. 3 AP",
            4: "Reduce enemy DEF 40% (min 1) for 3 turns. 0 DEF: +1 true dmg. 3 AP",
            5: "Reduce enemy DEF 50% (min 1) for 3 turns. 0 DEF: +1 true dmg. 4 AP",
        },
    },
    "death_defier": {
        "name": "Death Defier",
        "min_level": 5,
        "max_rank": 5,
        "upgrade_costs": [2, 3, 3, 4, 5],
        "tier2_name": "Undying",
        "rank_descs": {
            1: "Survive lethal damage at 1 HP. One use per fight.           3 AP",
            2: "Survive lethal damage at 10% max HP. One use per fight.     3 AP",
            3: "Survive lethal damage at 20% max HP. One use per fight.     4 AP",
            4: "Survive lethal damage at 30% max HP. One use per fight.     4 AP",
            5: "Survive lethal damage at 40% max HP. One use per fight.     5 AP",
        },
    },

    # v0.6.18: Dual Wielder — PLACEHOLDER. The skill data model is in place
    # so v0.7 can wire up the actual rank progression without UI churn. In
    # v0.6.18 the skill only shows in the trainer menu when the player is
    # actively dual-wielding (two 1H weapons), and cannot be purchased.
    # See POST_DEMO_IDEAS.md for the full design (ranks 1-5, off-hand full
    # damage at rank 1, +ATK% at higher ranks, rank 5 dual-proc chance).
    "dual_wielder": {
        "name": "Dual Wielder",
        "min_level": 1,
        "max_rank": 5,
        "upgrade_costs": [1, 2, 3, 4, 4],
        "tier2_name": "Twin Strike",
        "placeholder": True,    # v0.6.18: not yet implemented — UI shows greyed
        "rank_descs": {
            1: "Off-hand attacks for full damage instead of half.            passive",
            2: "+5% ATK while dual-wielding.                                 passive",
            3: "+10% ATK while dual-wielding.                                passive",
            4: "+15% ATK while dual-wielding.                                passive",
            5: "+20% ATK; chance for both weapons' procs to fire on a hit.   passive",
        },
    },
}


def get_skill_desc(key, hero):
    """
    Returns a list of description lines visible to the player based on
    their current rank — sliding window of 2 ranks ahead.

    Rank 0 -> shows ranks 1 and 2
    Rank 1 -> shows ranks 2 and 3
    ...
    Rank 3 -> shows ranks 4 and 5
    Rank 4 -> shows rank 5 + tier 2 locked hint (name only)
    Rank 5 -> shows tier 2 locked hint (name revealed, nothing else)
    """
    data      = SKILL_DEFS[key]
    rank      = hero.skill_ranks.get(key, 0)
    max_rank  = data["max_rank"]
    descs     = data["rank_descs"]
    t2_name   = data.get("tier2_name", "???")

    lines = []

    # Which ranks to show: current+1 and current+2, capped at max_rank
    show_ranks = [r for r in (rank + 1, rank + 2) if 1 <= r <= max_rank]

    for r in show_ranks:
        prefix = "► NEXT " if r == rank + 1 else "  THEN "
        lines.append(f"   {prefix}Rank {r}: {descs[r]}")

    # Tier 2 hint — show name at rank 4, show name at rank 5 (maxed)
    if rank >= 4:
        lines.append(f"   🔒 {t2_name} — Locked (Demo)")

    # If maxed and no ahead ranks were added, still show the hint
    if not lines:
        lines.append(f"   🔒 {t2_name} — Locked (Demo)")

    return lines




def skill_visible(hero, key):
    """Hide skills until min_level, unless already unlocked."""
    rank = hero.skill_ranks.get(key, 0)
    req = SKILL_DEFS[key]["min_level"]

    # v0.6.18: Dual Wielder is only visible when player is actively
    # dual-wielding (two non-shield weapons equipped). Once seen, it stays
    # visible if the player has invested into it. In v0.6.18 it's a
    # placeholder skill — see SKILL_DEFS["dual_wielder"]["placeholder"].
    if key == "dual_wielder":
        if rank > 0:
            return True   # earned, always visible
        mh = hero.equipment.get("main_hand")
        oh = hero.equipment.get("off_hand")
        def _is_weapon(item):
            return item is not None and getattr(item, "slot", None) == "weapon"
        return _is_weapon(mh) and _is_weapon(oh)

    return hero.level >= req or rank > 0

def next_skill_cost(hero, key):
    """Cost to go from current rank -> next rank.
    River Spirit discount: Death Defier costs 1 less SP per rank (min 0).
    Rank 0->1 is free (0 SP). Rank 1->2 costs 2, rank 2->3 costs 2, etc.
    """
    rank = hero.skill_ranks.get(key, 0)
    costs = SKILL_DEFS[key]["upgrade_costs"]
    max_rank = SKILL_DEFS[key]["max_rank"]

    if rank >= max_rank:
        return None  # already maxed

    base_cost = costs[rank]

    # River Spirit discount — -1 SP per rank on Death Defier (min 0)
    if key == "death_defier" and getattr(hero, "death_defier_river", False):
        return max(0, base_cost - 1)

    return base_cost

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

            # v0.6.18: placeholder skills display greyed and cannot be purchased
            is_placeholder = data.get("placeholder", False)

            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)

            if is_placeholder:
                cost_text = "—"
                prog_text = ""
            elif cost is None:
                cost_text = "MAX"
                prog_text = ""
            else:
                # River Spirit discount label
                river_disc = (key == "death_defier" and
                              getattr(hero, "death_defier_river", False) and
                              rank < SKILL_DEFS[key]["max_rank"])
                if cost == 0:
                    cost_text = "FREE ✨"
                elif river_disc:
                    cost_text = f"{cost} SP (River Spirit discount)"
                else:
                    cost_text = f"{cost} SP"
                # show progress only if not maxed
                prog_text = f" | Progress: {bank}/{cost}" if (bank > 0 or cost > 1) else ""

            if is_placeholder:
                status = "🚧 Coming in v0.7"
            else:
                status = "Unlocked" if rank > 0 else "Locked"
                req = data["min_level"]
                if rank == 0 and hero.level < req:
                    status = f"Locked (Requires Lv {req})"

            print(f"{i}) {name:<14}  Rank {rank}/{max_rank}  |  Next: {cost_text}{prog_text}  |  {status}")
            for line in get_skill_desc(key, hero):
                print(line)

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

        # v0.6.18: placeholder skills can't be purchased — show coming-soon
        if SKILL_DEFS[key].get("placeholder", False):
            print(f"\n🚧 {SKILL_DEFS[key]['name']} isn't available yet — coming in v0.7.")
            print("   You can preview its design here, but you can't invest into it now.")
            input("\nPress Enter...")
            continue

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
        # River Spirit: Death Defier rank 1 is free — bypass SP check
        _dd_free = (key == "death_defier" and
                    getattr(hero, "death_defier_river", False) and
                    hero.skill_ranks.get(key, 0) == 0)

        if not _dd_free and hero.skill_points <= 0:
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
            # Death Defier: set the passive flag on first rank
            if key == "death_defier" and hero.skill_ranks[key] == 1:
                hero.death_defier = True
                # River Spirit converts to rank 1 — preserve 0 AP cost
                if getattr(hero, "death_defier_river", False):
                    print()
                    print("✨ The River Spirit's blessing evolves into Death Defier rank 1.")
                    print("   Activation cost remains 0 AP — the river still remembers you.")
                    # death_defier_river stays True — 0 AP cost preserved
                else:
                    hero.death_defier_river = False
                hero.death_defier_active = False
                hero.death_defier_used   = False
            upgraded = True

        if upgraded:
            print(f"\n✅ {SKILL_DEFS[key]['name']} upgraded to Rank {hero.skill_ranks[key]}!")
            check_jack_of_all_trades(hero)
            check_breadth_titles(hero, key)
            check_skill_mastery(hero, key)
            check_true_jack_of_all_trades(hero)
        elif to_invest > 0:
            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)
            print(f"\n📘 Invested {to_invest} SP into {SKILL_DEFS[key]['name']} ({bank}/{cost}).")
        else:
            print("\n📘 No additional points needed for this skill right now.")



def skill_menu(hero, enemy):
    while True:
        clear_screen()
        hero.show_game_stats(enemy)

        options = []  # (key, label, callable)

        # -------------------------
        # DEATH DEFIER
        # -------------------------
        if hero.death_defier and not hero.death_defier_active and not hero.death_defier_used:
            dd_label = "River Spirit" if _dd_display_as_river(hero) else "Death Defier"
            cost = _dd_ap_cost(hero)

            # Calculate survival HP for display
            rank = _dd_effective_rank(hero)
            survive_pcts = {1: 0.0, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
            pct = survive_pcts.get(rank, 0.0)
            survive_hp = max(1, int(hero.max_hp * pct)) if pct > 0 else 1
            survive_str = f"{survive_hp} HP ({int(pct*100)}%)" if pct > 0 else "1 HP"

            if hero.ap < cost:
                label = f"{dd_label} Rank {rank} — survive at {survive_str} (Cost {cost} AP) [Not enough AP]"
                fn = None
            else:
                label = f"{dd_label} Rank {rank} — survive at {survive_str} (Cost {cost} AP)"
                fn = lambda: activate_death_defier(hero)

            options.append(("death_defier", label, fn))

        # -------------------------
        # POWER STRIKE (downcast-aware)
        # -------------------------
        ps_rank = hero.skill_ranks.get("power_strike", 0)
        if ps_rank > 0:
            max_rank = min(ps_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= power_strike_ap_cost(r, hero)]

            if not affordable:
                label = f"Power Strike (Rank {ps_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = power_strike_ap_cost(default_rank, hero)
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
                          if hero.ap >= heal_ap_cost(r, hero)]

            if not affordable:
                label = f"First Aid (Rank {heal_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = heal_ap_cost(default_rank, hero)
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
                          if hero.ap >= war_cry_ap_cost(r, hero)]

            if not affordable:
                label = f"War Cry (Rank {wc_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = war_cry_ap_cost(default_rank, hero)
                pct   = WAR_CRY_PERCENTS[default_rank]
                turns = WAR_CRY_TURNS[default_rank]
                bonus = max(1, math.ceil(hero.max_atk * pct))
                label = (f"War Cry (Rank {wc_rank} → {default_rank}, "
                         f"Cost {default_cost} AP, +{bonus} for {turns} turns)")
                fn = lambda h=hero, r=default_rank: war_cry(h, r)

            options.append(("war_cry", label, fn))

        # -------------------------
        # DEFENCE BREAK
        # -------------------------
        db_rank = hero.skill_ranks.get("defence_break", 0)
        if db_rank > 0:
            max_rank = min(db_rank, 5)
            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= defence_break_ap_cost(r)]
            if not affordable:
                label = f"Defence Break (Rank {db_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = defence_break_ap_cost(default_rank)
                pct, turns = DEFENCE_BREAK_STATS[default_rank]
                label = (f"Defence Break (Rank {db_rank} → {default_rank}, "
                         f"Cost {default_cost} AP, -{int(pct*100)}% DEF {turns}T)")
                fn = lambda h=hero, e=enemy, r=default_rank: defence_break(h, e, r)
            options.append(("defence_break", label, fn))
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
            # Chimera Fury — build charge based on rank of skill used
            if hasattr(enemy, "chimera_fury_charge"):
                rank_used = hero.skill_ranks.get(key, 1)
                chimera_fury_add(enemy, hero, rank_used)
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
        # v0.6.21: per-fight flag for SCORING. berserk_used has run-cycle
        # semantics (it gates the natural re-trigger until HP recovers above
        # 20%), so the score can't read it — it stays True across fights while
        # the player is low, handing out the +20 berserk bonus every fight.
        # This flag is reset at battle_inner start and read by record_fight_score.
        warrior.berserk_used_this_fight = True
        # Optionally clear any 'berserk_pending' flag if it still exists
        warrior.berserk_pending = False









        


        

            
          
        


   

            
        


        

    

    














































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
        self.berserk_used_this_fight = False  # v0.6.21: per-fight scoring flag (reset each fight)
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
        self.death_defier_used_this_fight = False  # v0.6.21: per-fight scoring flag (reset each fight)

        # ------------------------------------------------------------------
        # GOBLIN BOOKIE SYSTEM
        # Gold earned in fights is held here until the player visits the
        # bookie in the arena quarters. bookie_result tracks what happened
        # on the first visit so the second visit dialogue can react.
        # ------------------------------------------------------------------
        self.pending_bookie_gold = 0
        self.bookie_result       = None   # "stolen" | "caught" | "intimidated"
        self.jackpot_count       = 0      # times jackpot fired during level-ups

        # ---- v0.6.08 score system tracking ----
        # total_gold_earned: lifetime gold earned, never decreases on spending.
        #   The score system reads this so spending isn't punished.
        # bookie_intimidated_count: number of intimidate-results across the run,
        #   awarded as a small luck/skill bonus by the score system.
        # per_fight_scores: list of per-fight score breakdowns appended by
        #   score.record_fight_score() after each victory.
        self.total_gold_earned        = self.gold  # seed with starting gold
        self.bookie_intimidated_count = 0
        self.per_fight_scores         = []
        # v0.6.19: quick-kill tracking — accumulated by score.record_fight_score
        # when turn_count <= QUICK_KILL_TURNS for the enemy's tier. The
        # multiplier bonus adds onto the outcome multiplier at end of run.
        self.quick_kill_count           = 0
        self.quick_kill_multiplier_bonus = 0.0






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

    # Re-sync psychic base stats so Charged Jagged Rock cap math
    # uses the correct post-scaling values, not the spawn-time values.
    monster.psychic_base_min_atk = monster.min_atk
    monster.psychic_base_max_atk = monster.max_atk
    monster.psychic_base_defence = monster.defence

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











  








# ===============================
# Combat System
# ===============================

# ---------------------------------------------------------------
# DEFERRED IMPORT — DO NOT MOVE TO TOP OF FILE
# ---------------------------------------------------------------
# v0.6.04 monster balance pass — tier 2/3 base stat buffs, hardened
# scaling doubled, DoT hardened damage and duration increased.
# v0.6.03 extracted monster classes, special moves, and encounter
# helpers into monsters.py. `monsters.py` imports back from this file
# the helpers it needs (lvl_bonus, monster_deal_damage, wrap, etc.).
#
# That means monsters.py CAN'T be imported until all those helpers
# already exist in this file's namespace. The latest helper monsters.py
# needs is `scaled_xp_step` defined just above this line, so this import
# has to live HERE — after every helper is defined, before the combat
# system starts using monster classes.
#
# Moving this import to the top of the file will cause a circular
# import failure at startup. If a future refactor extracts the shared
# helpers into their own module (e.g. helpers.py), this import can move
# back to the top with the rest.
# ---------------------------------------------------------------
from monsters import *  # noqa: F401,F403  -- pull in 18 monster classes + moves + encounter helpers
# (Private/underscored names like _clear_psychic_debuff are exposed by the
# explicit __all__ list at the top of monsters.py — no separate import needed.)


def warrior_attack_roll(warrior):
    roll = random.randint(warrior.min_atk, warrior.max_atk)
    # v0.6.16: Pack Hunter (Wolf-Hide 4pc) and Apex Predator (Dire Wolf 4pc)
    # both grant +10% basic attack damage. The two sets share slots so only
    # one can be active at a time. Rounds half-up for predictability.
    try:
        from crafter import pack_hunter_active, apex_predator_active
        if pack_hunter_active(warrior) or apex_predator_active(warrior):
            roll = int(round(roll * 1.10))
    except ImportError:
        pass
    return roll





def enemy_attack(enemy, warrior):
    """Enemy performs one action. Tries specials safely, then falls back to normal attack."""
    enemy.rounds_in_combat += 1

    # v0.6.16: Young Chimera passive heal — fires at START of every turn,
    # unconditionally. No longer gated on landing a basic attack hit.
    if enemy.name == "Young Chimera":
        chimera_passive_heal(enemy, warrior)

    # -------------------------------------------------------------
    # TIERED AI LOGIC (Consolidated Special Move Check)
    # -------------------------------------------------------------
    tier = getattr(enemy, "tier", 1)
    special = getattr(enemy, "special_move", None)
    should_special = False

    # Only even consider a special if the monster has AP and a move assigned
    # Tier 5 (Chimera) is charge-based — no AP gate, handled separately below
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

    # Tier 5 — charge-based, no AP requirement
    if tier == 5 and callable(special):
        should_special = (random.random() < 0.65)

    # Execute Special only if the tier roll was successful
    if should_special:
        result = special(enemy, warrior)
        _stone_absorb_charge(warrior)   # stone charges on any special, any path
        if result is not None:
            # Check for death after special move
            if warrior.hp <= 0:
                if not try_death_defier(warrior, f"{enemy.name} special", enemy=enemy):
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

    # Monster-specific flavour text for normal attacks
    if enemy.name in ("Goblin Warrior", "Hardened Goblin Warrior"):
        print(random.choice([
            "⚔️  The Goblin Warrior swings its rusted blade!",
            "⚔️  The Goblin Warrior charges with a guttural war cry!",
            "⚔️  The Goblin Warrior slashes with practiced fury!",
            "⚔️  The Goblin Warrior lunges forward, blade first!",
        ]))

    # Roll damage (Normal Attack)
    roll = enemy.max_atk if force_max else enemy.attack_roll()
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    # Visual UI breakdown
    monster_math_breakdown(enemy, warrior, roll, actual)
    show_health(warrior)

    # v0.6.16: Chimera passive heal moved to enemy_attack() — now fires EVERY
    # turn (start-of-turn) regardless of whether basic attack hits.

    # Check for death after normal attack
    if warrior.hp <= 0:
        if try_death_defier(warrior, f"{enemy.name} attack", enemy=enemy):
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
    has_weapon    = warrior.get_weapon() is not None   # v0.6.16
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

    # v0.6.15 — BLIND FIX: basic attack previously ignored blind_turns entirely,
    # so the player could swing at full power on turn 2 of blind. Now unified
    # with Power Strike via blind_damage_multiplier() helper.
    blind_mult = 1.0
    if getattr(warrior, "blind_turns", 0) > 0:
        blind_mult = blind_damage_multiplier(warrior)
        if blind_mult < 1.0:
            pre_blind_total = total
            total = max(1, int(total * blind_mult))
            print(f"👁️ Blinded! Your swing lands at {int(blind_mult * 100)}% power. ({pre_blind_total} → {total})")

    actual = enemy.apply_defence(total, attacker=warrior)

    # Patronus shield damage reduction — 30% while shield is equipped
    if getattr(enemy, "shield_equipped", False):
        reduction = round(actual * 0.30)
        actual = max(1, actual - reduction)

    enemy.hp = max(0, enemy.hp - actual)

    # Exposed bonus: +1 true damage if enemy DEF is at -1
    if getattr(enemy, "psychic_exposed", False) and actual > 0:
        enemy.hp = max(0, enemy.hp - 1)
        actual += 1

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

    # 5b) Weapon proc effects — paralyze (Goblin Shortbow)
    weapon = warrior.get_weapon()   # v0.6.16
    if weapon and actual > 0 and enemy.is_alive():
        paralyze_chance    = getattr(weapon, "paralyze_chance", 0.0)
        paralyze_turns     = getattr(weapon, "paralyze_turns", 0)
        if paralyze_chance > 0 and not getattr(enemy, "skip_turns", 0) > 0:
            if random.random() < paralyze_chance:
                enemy.skip_turns = paralyze_turns
                print(wrap(f"⚡ The arrow finds a gap — {enemy.display_name} "
                           f"is PARALYZED for {paralyze_turns} turn{'s' if paralyze_turns != 1 else ''}!"))

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
    
    # 5d) Charged Jagged Rock — passive charge fill on any hit that gets through defence
    # Pool fills by actual_damage * fill_rate (min 0.10). Each full charge:
    #   player +1 ATK (stacks with base_atk), current enemy -1 ATK/-1 DEF.
    # Resets at rest between rounds.
    if actual > 0 and enemy.is_alive() and _cjr_rock(warrior):
        changed = _cjr_absorb(warrior, enemy, actual)
        if changed:
            print(wrap(cjr_bar(warrior)))

    # 6) Weapon proc effects — only on weapon attacks
    weapon = warrior.get_weapon()   # v0.6.16
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

        # --- Rusted Sword: chance to apply Rot (enemy max HP drain) ---
        rot_chance      = getattr(weapon, "rot_chance", 0.0)
        rot_stacks      = getattr(weapon, "rot_stacks", 0)
        rot_hp_per_stack = getattr(weapon, "rot_hp_per_stack", 0)
        if rot_chance > 0 and rot_stacks > 0 and random.random() < rot_chance:
            if not hasattr(enemy, "rot_stacks_applied"):
                enemy.rot_stacks_applied = 0
                enemy.rot_max_hp_loss    = 0
            cap = max(1, int(enemy.max_hp * 0.30))
            already_lost = enemy.rot_max_hp_loss
            space_left   = cap - already_lost
            if space_left > 0:
                drain = min(rot_stacks * rot_hp_per_stack, space_left)
                enemy.max_hp           = max(1, enemy.max_hp - drain)
                enemy.hp               = min(enemy.hp, enemy.max_hp)
                enemy.rot_max_hp_loss += drain
                enemy.rot_stacks_applied += rot_stacks
                print(wrap(f"🟫 The rusted blade corrupts the wound! "
                           f"{enemy.display_name}'s flesh rots — Max HP -{drain}! "
                           f"(Total rot: -{enemy.rot_max_hp_loss}, cap {cap})"))
            else:
                print(wrap(f"🟫 {enemy.display_name} is already fully rotted — the blade finds no purchase."))

        # --- Javelina Tusk: bleed ---
        tusk_bleed = getattr(weapon, "bleed_turns", 0)
        if tusk_bleed > 0 and actual > 0 and enemy.is_alive():
            dmg_min = getattr(weapon, "bleed_dmg_min", 1)
            dmg_max = getattr(weapon, "bleed_dmg_max", dmg_min)
            enemy.bleed_turns   = tusk_bleed
            enemy.bleed_dmg_min = dmg_min
            enemy.bleed_dmg_max = dmg_max
            dmg_str = f"{dmg_min}–{dmg_max}" if dmg_max > dmg_min else str(dmg_min)
            print(wrap(f"🩸 The jagged tusk opens a wound! "
                       f"{enemy.display_name} bleeds for {dmg_str} dmg/turn "
                       f"over {tusk_bleed} turn{'s' if tusk_bleed != 1 else ''}! "
                       f"(ignores defence)"))

        # --- Goblin War Blade: scaling bleed from stats table ---
        war_blade_turns = getattr(weapon, "bleed_turns", 0)
        if (war_blade_turns > 0 and actual > 0 and enemy.is_alive()
                and getattr(weapon, "name", "") == "Goblin War Blade"):
            dmg_min = getattr(weapon, "bleed_dmg_min", 1)
            dmg_max = getattr(weapon, "bleed_dmg_max", dmg_min)
            if not hasattr(enemy, "warrior_bleed_dots"):
                enemy.warrior_bleed_dots = []
            # Overwrite existing stack — blade reopens the same wound
            enemy.warrior_bleed_dots = [{
                "dmg_min":    dmg_min,
                "dmg_max":    dmg_max,
                "turns_left": war_blade_turns,
                "skip":       True,
            }]
            dmg_str = f"{dmg_min}–{dmg_max}" if dmg_max > dmg_min else str(dmg_min)
            print(wrap(f"🩸 The war blade opens a deep wound! "
                       f"{enemy.display_name} bleeds for {dmg_str} dmg/turn "
                       f"over {war_blade_turns} turn{'s' if war_blade_turns != 1 else ''}! "
                       f"(ignores defence)"))

        # --- v0.6.16: Pack Hunter passive — 50% chance to apply +3 bleed
        # for 2 turns when 4-piece Wolf-Hide set is worn. Stacks ADDITIVELY
        # with existing weapon bleed: +3 is added to existing tick rather
        # than creating a separate effect.
        try:
            from crafter import pack_hunter_active
            if (pack_hunter_active(warrior) and actual > 0 and enemy.is_alive()
                    and random.random() < 0.50):
                pack_dmg = 3
                pack_turns = 2

                if getattr(enemy, "bleed_turns", 0) > 0:
                    enemy.bleed_dmg_min += pack_dmg
                    enemy.bleed_dmg_max += pack_dmg
                    enemy.bleed_turns = max(enemy.bleed_turns, pack_turns)
                    print(wrap(f"🩸 Pack Hunter! Your fangs find the wound — bleed deepens "
                               f"(+{pack_dmg} dmg/turn, {enemy.bleed_turns} turns left)."))
                elif getattr(enemy, "warrior_bleed_dots", []):
                    for dot in enemy.warrior_bleed_dots:
                        dot["dmg_min"] += pack_dmg
                        dot["dmg_max"] += pack_dmg
                        dot["turns_left"] = max(dot["turns_left"], pack_turns)
                    print(wrap(f"🩸 Pack Hunter! The wound rips wider (+{pack_dmg} dmg/turn)."))
                else:
                    enemy.bleed_turns   = pack_turns
                    enemy.bleed_dmg_min = pack_dmg
                    enemy.bleed_dmg_max = pack_dmg
                    print(wrap(f"🩸 Pack Hunter! Your strike tears flesh — "
                               f"{enemy.display_name} bleeds ({pack_dmg} dmg/turn for "
                               f"{pack_turns} turns)."))
        except ImportError:
            pass

        # --- v0.6.16: Apex Predator passive — 5% lifesteal when 4-piece
        # Dire Wolf set is worn. Heals warrior for 5% of damage dealt,
        # minimum 1 if any damage landed. Respects max_overheal cap.
        try:
            from crafter import apex_predator_active
            if apex_predator_active(warrior) and actual > 0:
                lifesteal = max(1, int(actual * 0.05))
                if warrior.hp < warrior.max_overheal:
                    healed = min(lifesteal, warrior.max_overheal - warrior.hp)
                    warrior.hp += healed
                    print(wrap(f"🩸 Apex Predator! Your strike drinks the wound — "
                               f"+{healed} HP."))
        except ImportError:
            pass

        # --- v0.6.16: Socketed accessory procs.
        # Sockets fire AFTER weapon-native procs. Each socketed item applies
        # its effect independently at 75% effectiveness.
        try:
            from crafter import get_weapon_socket_procs
            if actual > 0 and enemy.is_alive() and weapon is not None:
                for proc in get_weapon_socket_procs(weapon):
                    if random.random() >= proc.get("chance", 1.0):
                        continue

                    if proc["type"] == "element":
                        elem = proc["element"]
                        if elem == "poison":
                            target_list = getattr(enemy, "warrior_poison_dots", None)
                        elif elem == "fire":
                            target_list = getattr(enemy, "warrior_burn_dots", None)
                        elif elem == "acid":
                            target_list = getattr(enemy, "warrior_acid_dots", None)
                        else:
                            target_list = None
                        if target_list is None:
                            continue
                        if len(target_list) < proc["max_dots"]:
                            target_list.append({
                                "dmg":        proc["damage"],
                                "turns_left": proc["turns"],
                                "restore":    proc.get("restore", 0),
                                "erosion":    proc.get("erosion", 0),
                                "source":     "socket",
                            })
                            print(wrap(f"💎 Socketed {proc['source']} — "
                                       f"{elem} ({proc['damage']} dmg/turn for "
                                       f"{proc['turns']} turns)."))

                    elif proc["type"] == "bleed":
                        existing = getattr(enemy, "bleed_turns", 0)
                        if existing > 0:
                            enemy.bleed_dmg_min += proc["dmg_min"]
                            enemy.bleed_dmg_max += proc["dmg_max"]
                            enemy.bleed_turns = max(existing, proc["turns"])
                            print(wrap(f"💎 Socketed Tusk deepens the bleed."))
                        else:
                            enemy.bleed_turns = proc["turns"]
                            enemy.bleed_dmg_min = proc["dmg_min"]
                            enemy.bleed_dmg_max = proc["dmg_max"]
                            print(wrap(f"💎 Socketed Tusk — bleed "
                                       f"({proc['dmg_min']}-{proc['dmg_max']} dmg/turn, "
                                       f"{proc['turns']} turns)."))

                    elif proc["type"] == "drain":
                        bonus = proc["bonus"]
                        if bonus > 0:
                            extra = min(bonus, enemy.hp)
                            enemy.hp -= extra
                            heal = random.randint(proc["heal_min"], proc["heal_max"])
                            healed = min(heal, warrior.max_overheal - warrior.hp)
                            if healed > 0:
                                warrior.hp += healed
                            print(wrap(f"💎 Socketed Soul Pendant — drain "
                                       f"(+{extra} dmg, +{healed} HP)."))
        except ImportError:
            pass

    # 7) Berserk extension + tick (unchanged)
    if enemy.hp <= 0 and getattr(warrior, "berserk_active", False):
        warrior.berserk_turns += 1
        print("🩸 Your killing blow feeds the frenzy! Berserk is extended!")

    if getattr(warrior, "berserk_active", False):
        warrior.berserk_turns -= 1
        if warrior.berserk_turns <= 0:
            deactivate_berserk(warrior)
            print("💤 Your Berserk fury subsides...")

    return {
        "actual":      actual,
        "roll":        roll,
        "blocked":     blocked,
        "bonus_parts": bonus_parts,
        "elem_tag":    elem_tag.strip() if elem_tag else "",
    }






def _ensure_level_5_for_final_boss(warrior):
    """
    Safety net: a player who beat the Fallen Warrior at level 4 (or lower)
    gets bumped to level 5 before the final boss fires. Grants exactly the
    XP needed to push to 5, then lets animate_xp_results handle the level-up
    sequence normally — random buffs, stat/skill points, spend menu, etc.

    Design rule: players SHOULD hit 5 before the final boss but should NOT
    be 5 before the Fallen fight (level cap applies in arena). This catches
    edge cases where the arena XP didn't quite land them at 5.
    """
    if warrior.level >= 5:
        return  # already there, nothing to do

    # Calculate XP needed to reach level 5 from the current level
    # animate_xp_results handles xp_to_lvl scaling internally, so we just
    # need to grant a big enough chunk to cross every threshold up to 5.
    levels_to_gain = 5 - warrior.level
    xp_needed = 0
    projected_xp_to_lvl = warrior.xp_to_lvl
    projected_xp = warrior.xp

    for _ in range(levels_to_gain):
        # XP needed to clear the current bar
        xp_needed += max(0, int(projected_xp_to_lvl) - int(projected_xp))
        # Mirror the level_up scaling so the next bar size is right
        projected_xp_to_lvl = int(projected_xp_to_lvl * 1.75)
        projected_xp = 0

    if xp_needed <= 0:
        return

    print()
    print("=" * 50)
    print("  ⚜️  THE WEIGHT OF VICTORY")
    print("=" * 50)
    print(wrap(
        "The Fallen Warrior's strength settles into your bones. "
        "Hard-won. Earned. You feel yourself ready for what comes next."
    ))
    print()
    input("Press Enter...")
    animate_xp_results(warrior, xp_needed)
    print()


def fallen_warrior_moral_choice(warrior, fallen=None):
    """
    Fires when Fallen Warrior is clamped to 1 HP.

    Order:
    1. Story scene — Fallen Warrior's last moments
    2. Beast Gods intervene — the choice
    3. Choice delivers killing blow (1 true damage → HP = 0)
    4. Weapon offered based on choice
    5. Champion of the Arena title awarded
    6. XP rewarded
    7. chimera_fight() or patronus_fight()

    Sets story_flag: "crushed_essence" or "returned_essence"
    """
    input("\nPress Enter to continue...")

    # --- The Fallen Warrior's last moments ---
    print("\n" + "═" * 50)
    print("   THE FALLEN WARRIOR'S LAST BREATH")
    print("═" * 50)
    print()
    print(wrap(
        "The Fallen Warrior collapses to the sand. You stand over him, "
        "blade still raised. The crowd is deafening."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Then something shifts in his face. The rage drains away. "
        "His eyes — bloodshot, hollow, ancient — find yours."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "\"Please,\" he rasps. His hand reaches toward you, trembling. "
        "\"I don't want to kill anymore.\""
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "His eyes fill. Something behind them breaking open — not weakness. "
        "Recognition. Memory. The weight of a thousand fights he never chose."
    ))
    print()
    print(wrap(
        "\"So much death,\" he breathes. \"So much...\""
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "His chest barely moves. A shimmer rises from his body — dense, pulsing, "
        "ancient. His essence. It drifts toward you slowly, like it's waiting."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "A deep red light bleeds into the air around the Fallen Warrior's body — "
        "not fire, not blood. Something older. It pulses in slow, rhythmic draws, "
        "like breath. Like hunger."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "It flickers."
    ))
    print()
    print(wrap(
        "Just once. A stutter in the rhythm — like something interrupted it. "
        "The red light steadies again almost immediately."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "The shimmer of his essence begins to move. Not toward you. "
        "Upward. Pulled. Thin threads of light peel away from the mass of it, "
        "rising toward the overseer's box in long, slow ribbons."
    ))
    print()
    input("Press Enter...")
    print()
    print()
    print(wrap(
        "The red light deepens. The ribbons thicken. Whatever broke open "
        "in the Fallen Warrior in his final moments — the grief, the weight "
        "of it — the feed is drawing on all of it. More than usual. "
        "You can feel the hunger in it from where you stand."
    ))
    print()
    input("Press Enter...")

    # --- The Beast Gods intervene ---
    print()
    print("═" * 50)
    print()
    print(wrap(
        "The arena shudders. A voice — vast, layered, wrong — "
        "pours down from the overseer's box and fills the arena."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "\"DON'T LISTEN TO HIM, CHAMPION.\""
    ))
    print()
    print(wrap(
        "\"Return the essence to us. He is ours. He has always been ours. "
        "His weapon is yours to keep. And we will add gold — more than the arena "
        "owes you. Our blessing on every fight that follows.\""
    ))
    print()
    print(wrap(
        "The voice shifts. Smoother now. The way a hand might open "
        "rather than reach."
    ))
    print()
    print(wrap(
        "\"You have performed... remarkably. Even we did not anticipate "
        "a champion quite like you. The arena has not seen your kind in "
        "a very long time.\""
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Their voice settles into your bones, smooth and unhurried. "
        "Every word coaxes you toward agreement, as if compliance were "
        "the only natural answer."
    ))
    print()
    print(wrap(
        "\"What do you do, adventurer?\""
    ))
    print()

    # --- The choice ---
    print("═" * 50)
    print()
    print("  1) Crush the essence — set him free")
    print("  2) Return the essence to the Beast Gods")
    print()

    while True:
        choice = _real_input("> ").strip()
        if choice == "1":
            # Good path
            warrior.story_flags.add("crushed_essence")

            print()
            print(wrap(
                "You close your fist around the essence. "
                "It resists for a moment — something ancient pushing back."
            ))
            print()
            input("Press Enter...")
            print()

            # --- Killing blow — crush delivers the final damage ---
            if fallen is not None:
                fallen.hp = 0
            print(wrap(
                "Then it gives. Not with violence. With relief. "
                "The light fractures, scatters, and is gone."
            ))
            print()
            print(wrap(
                "The Fallen Warrior's eyes find yours one last time. "
                "His lips move — barely. A whisper so faint you almost miss it."
            ))
            print()
            print(wrap(
                "\"...thank you.\""
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "He breathes his last. "
                "The arena goes dead silent. The overseers do not speak."
            ))
            print()
            print(wrap(
                "Somewhere far above you, something stirs. "
                "Something that has been watching far longer than the Beast Gods. "
                "It noticed what you just did."
            ))
            print()
            input("Press Enter...")
            print()

            # --- Champion of the Arena title ---
            print()
            print("=" * 45)
            print("🏆  TITLE UNLOCKED: Champion of the Arena!")
            print("=" * 45)
            print(wrap(
                "The crowd roars your name. Whatever comes next — "
                "you earned this."
            ))
            print()
            input("Press Enter to face what comes next...")
            reset_between_rounds(warrior)
            animate_xp_results(warrior, 50)

            # --- Weapon Core dropped — good path, pure form ---
            print(wrap(
                "The Fallen Warrior's weapon clatters to the sand beside you. "
                "Something pulses inside it — a core of pure energy, waiting to be shaped."
            ))
            print()
            weapon_core = _make_weapon_core(corrupted=False)
            if weapon_core:
                offer = _real_input("\nEquip the Weapon Core now? (y/n)\n> ").strip().lower()
                if offer == "y":
                    # v0.6.19: fall back to bag on equip cancel/block
                    if equip_item(warrior, weapon_core):
                        print(wrap(f"You equip the {weapon_core.name}."))
                    else:
                        warrior.inventory.append(weapon_core)
                        print(wrap(f"{weapon_core.name} saved to your bag instead."))
                else:
                    warrior.inventory.append(weapon_core)
                    print(wrap(f"You store the {weapon_core.name} in your bag."))
                print()

            # Level-5 safety net before final boss
            _ensure_level_5_for_final_boss(warrior)

            chimera_fight(warrior)
            return "good"

        elif choice == "2":
            # Evil path
            warrior.story_flags.add("returned_essence")

            print()
            print(wrap(
                "You reach out and let the essence flow past your fingers "
                "toward the overseer's box. It rises like smoke, eager."
            ))
            print()

            # --- Killing blow — returning the essence seals his fate ---
            if fallen is not None:
                fallen.hp = 0
            print(wrap(
                "The Fallen Warrior's eyes find yours as the essence leaves him. "
                "Something shifts in them — the hollow grief gone, replaced by something raw. "
                "His whole body tenses with a last surge of will."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "He drags in one last breath — and on it, a deep, primal, rage-filled scream tears out of him and fills the arena —"
            ))
            print()
            print(wrap(
                "\"WHY!\""
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "The cry echoes off the stone walls long after his body goes still."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "\"WELL CHOSEN, CHAMPION.\""
            ))
            print()
            print(wrap(
                "Coin hits the sand at your feet. More than the arena would have paid. "
                "You don't count it — you don't need to."
            ))
            gold_reward = 50
            award_gold(warrior, gold_reward)
            print(f"\n  🪙 +{gold_reward} gold from the Beast Gods. Total: {warrior.gold} gold.")
            print()
            print(wrap(
                "You don't look at where the essence went. "
                "You tell yourself that's wisdom."
            ))
            print()

            # --- Champion of the Arena title ---
            print("=" * 45)
            print("🏆  TITLE UNLOCKED: Champion of the Arena!")
            print("=" * 45)
            print(wrap(
                "The crowd roars your name. Whatever comes next — "
                "you earned this."
            ))
            print()
            input("Press Enter to face what comes next...")
            reset_between_rounds(warrior)
            animate_xp_results(warrior, 50)

            # --- Weapon Core dropped — evil path, corrupted form ---
            print(wrap(
                "The Fallen Warrior's weapon clatters to the sand. "
                "Something pulses inside it — but it's already changing, "
                "the Beast Gods' mark bleeding through the metal."
            ))
            print()
            weapon_core = _make_weapon_core(corrupted=True)
            if weapon_core:
                offer = _real_input("\nEquip the Weapon Core now? (y/n)\n> ").strip().lower()
                if offer == "y":
                    # v0.6.19: fall back to bag on equip cancel/block
                    if equip_item(warrior, weapon_core):
                        print(wrap(f"You equip the {weapon_core.name}."))
                    else:
                        warrior.inventory.append(weapon_core)
                        print(wrap(f"{weapon_core.name} saved to your bag instead."))
                else:
                    warrior.inventory.append(weapon_core)
                    print(wrap(f"You store the {weapon_core.name} in your bag."))
                print()

            # Level-5 safety net before final boss
            _ensure_level_5_for_final_boss(warrior)

            patronus_fight(warrior)
            return "evil"

        else:
            print("Enter 1 or 2.")





def chimera_fight(warrior):
    """
    True final boss of the good path — Young Chimera.

    Win  → Chimera is vanquished. Chimera Scale drops.
           story_flag: "chimera_vanquished"

    Loss (cycles < 4) → Regular defeat. Player didn't last long enough.
           No intervention. Game over.

    Loss (cycles >= 4) → Player survived long enough to prove their worth.
           The mysterious figure freezes time and stabilises the player.
           story_flag: "chimera_alive" — son hunts it down 30 years later.
           No loot drops.
    """
    chimera = Young_Chimera()

    # --- Good path entry scene ---
    print("\n" + "═" * 50)
    print("   ⚠️  SOMETHING STIRS BELOW")
    print("═" * 50)
    print()
    print(wrap(
        "A deep, resonant roar rises from somewhere beneath the arena. "
        "The sand shudders. Then the pit drains — fast, like a drain unplugged — "
        "and the floor cracks open."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "The Young Chimera erupts from below in a burst of wings and fury, "
        "landing in the centre of the arena with enough force to kick sand "
        "across the walls. The crowd screams."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Then — stillness. Not silence. Stillness. "
        "The noise doesn't stop, but it falls away from you. "
        "Time slows. Thickens. Stops."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "A figure stands before you. She wasn't there a moment ago. "
        "She has no face you can hold in your mind — only the impression "
        "of something ancient, patient, and watching."
    ))
    print()
    print(wrap(
        "She reaches out and touches your chest."
    ))
    print()
    input("Press Enter...")
    print()

    # Full heal, status clear, and temporary max AP boost
    warrior.hp     = warrior.max_hp
    warrior.max_ap += 2
    warrior.ap     = warrior.max_ap
    clear_all_status_effects(warrior)

    print(wrap(
        "Warmth floods through you — not the warmth of fire, "
        "but something older. Your wounds close. "
        "The exhaustion lifts. Your body hums with energy you haven't felt "
        "since before the first fight."
    ))
    print()
    print(f"  ✨ HP fully restored: {warrior.hp}/{warrior.max_hp}")
    print(f"  ✨ AP fully restored: {warrior.ap}/{warrior.max_ap}  (+2 max AP — the energy of the universe)")
    print(f"  ✨ All status effects cleared")
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Time resumes with a snap. The crowd roars back into existence. "
        "The Chimera snarls across the sand."
    ))
    print()
    print(wrap(
        "And somewhere — close enough to be inside your own skull — "
        "a whisper."
    ))
    print()
    print(wrap(
        "\"We will meet again.\""
    ))
    print()
    # --- Oppressive Presence — if Chimera rolled Flayed One's move ---
    if chimera.chimera_tier3 == psychic_shred:
        warrior.min_atk = max(1, warrior.min_atk - 2)
        warrior.max_atk = max(1, warrior.max_atk - 2)
        warrior.defence = max(0, warrior.defence - 2)
        # Store base so cleanup can restore after fight
        warrior.chimera_presence_min_atk = warrior.min_atk + 2
        warrior.chimera_presence_max_atk = warrior.max_atk + 2
        warrior.chimera_presence_defence = warrior.defence + 2
        print(wrap(
            "😰 As the Chimera locks eyes with you, an oppressive psychic weight "
            "crushes down on your body. Your muscles seize. Your grip weakens."
        ))
        print(f"  ⬇️  ATK reduced by 2  |  DEF reduced by 2 (Oppressive Presence)")
        print()

    input(f"\nPress Enter to face the Young Chimera...")

    result = battle(warrior, chimera)

    # Always restore stats degraded by Primordial Surge
    _restore_primordial_stats(warrior)

    # Restore Chimera oppressive presence debuff if it was applied
    if hasattr(warrior, "chimera_presence_min_atk"):
        warrior.min_atk = warrior.chimera_presence_min_atk
        warrior.max_atk = warrior.chimera_presence_max_atk
        warrior.defence = warrior.chimera_presence_defence
        del warrior.chimera_presence_min_atk
        del warrior.chimera_presence_max_atk
        del warrior.chimera_presence_defence

    cycles = getattr(chimera, "combat_cycles", 0)

    if result:
        # -----------------------------------------------
        # VICTORY — Chimera vanquished, chaos, demo end
        # -----------------------------------------------
        warrior.story_flags.add("chimera_vanquished")

        print("\n" + "═" * 50)
        print("   🏆 THE CHIMERA FALLS")
        print("═" * 50)
        print()
        print(wrap(
            "The Young Chimera lets out a final, rattling cry and collapses. "
            "For a heartbeat the arena is completely still."
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "Then it erupts."
        ))
        print()
        print(wrap(
            "The crowd surges. The walls shake. Something in the overseer's box "
            "is wrong — voices overlapping, discordant, rising in pitch. "
            "The Beast Gods did not expect this."
        ))
        print()
        input("Press Enter...")
        print()

        scale = make_loot("Young Chimera", monster_level=3)
        if scale:
            # v0.6.14: clear combat fatigue (and any lingering fight-only DEF
            # mods) BEFORE equipping the scale. Matches the Fallen Warrior
            # defence_warp fix pattern — gear should be evaluated against
            # base DEF, not a fight-fatigued DEF.
            warrior.fatigue_def_loss  = 0
            warrior.fatigue_save_tier = 0
            print(wrap(
                "A thick iridescent scale rolls free from the Chimera's flank "
                "and comes to rest at your feet. Like it was always meant to."
            ))
            print(f"\n🎁 {scale.short_label()}")
            offer = input("\nEquip the Chimera Scale? (y/n)\n> ").strip().lower()
            if offer == "y":
                # v0.6.19: defensive — armor has no equip-block paths today,
                # but using the new contract keeps us safe if slot rules change.
                if equip_item(warrior, scale):
                    print(wrap(f"You strap it on. Defence +{scale.defence}."))
                else:
                    warrior.inventory.append(scale)
                    print(wrap(f"{scale.name} saved to your bag instead."))
            else:
                warrior.inventory.append(scale)
                print("You store it.")
            print()

        input("Press Enter...")
        print()
        print(wrap(
            "Then — a whisper. Silent. Inside your skull, not your ears."
        ))
        print()
        print(wrap(
            "\"Run. Before they regain their composure.\""
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "You don't need to be told twice."
        ))
        print()

        # Award Guardian title — good path true ending
        print("═" * 50)
        print("🏅  TITLE UNLOCKED: Guardian!")
        print("═" * 50)
        print(wrap(
            "The mysterious figure's blessing lingers in your bones. "
            "You are something more than you were when you entered this arena."
        ))
        print()
        award_title_with_buff(warrior, "guardian")

        # v0.6.08: record final-boss kill for per-fight score system
        # Note: Chimera victory awards NO gold — defying the Beast Gods means
        # you take nothing. Outcome multiplier (×2.1) compensates for this.
        record_fight_score(warrior, chimera, cycles)

        print()
        # End-of-run wrap-up — proper order: stats → score → combat log → leaderboard → demo close
        show_end_summary(warrior)
        _final_score = show_run_score(warrior, outcome="chimera_victory")
        view_combat_log()
        display_at_end_of_run(warrior, _final_score or 0, outcome="chimera_victory")

        print("═" * 50)
        print()
        print(wrap(
            "Thank you for playing the Journey to Winter Haven demo."
        ))
        print()
        print(wrap(
            "More content coming soon."
        ))
        print()
        print("═" * 50)
        prompt_play_again()  # v0.6.14: ask y/n instead of just closing
        return

    else:
        # -----------------------------------------------
        # DEFEAT — intervention check
        # -----------------------------------------------
        if cycles < 4:
            # Didn't survive 4 full cycles — no intervention
            print("\n" + "═" * 50)
            print("   💀 OVERWHELMED")
            print("═" * 50)
            print(wrap(
                "The Young Chimera stands over you, its breath hot against your face. "
                "You barely had time to understand what you were facing. "
                "It was never a fair fight."
            ))
            input("\nPress Enter to continue...")

        else:
            # Survived 4+ cycles — the mysterious figure intervenes again
            warrior.story_flags.add("chimera_alive")

            print("\n" + "═" * 50)
            print("   ✨ SHE RETURNS")
            print("═" * 50)
            print()
            print(wrap(
                "You hit the sand. The Chimera looms over you, "
                "chest heaving, ready to finish it."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "Then — stillness. The same stillness as before. "
                "Time slows and stops. The Chimera freezes mid-snarl."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "She is there again. The figure. Her hand finds your chest "
                "the same way it did before — steady, certain."
            ))
            print()
            print(wrap(
                "The warmth returns. Not as strong this time. "
                "But enough. Your wounds stabilise. The worst of it recedes."
            ))
            print()

            # Partial heal — stabilise, not full restore
            heal = max(1, warrior.max_hp // 3)
            warrior.hp = min(warrior.max_hp, warrior.hp + heal)
            # Clear all statuses — rot only cleared if Chimera drew rot_thrust
            _chimera_had_rot = (
                hasattr(chimera, "chimera_tier1") and
                getattr(chimera.chimera_tier1, "__name__", "") == "rot_thrust"
            )
            if not _chimera_had_rot:
                # Temporarily block rot clear — restore max_hp snapshot so clear_rot is a no-op
                _saved_rot_loss = getattr(warrior, "rot_max_hp_loss", 0)
                _saved_rot_base = getattr(warrior, "rot_base_max_hp", 0)
                warrior.rot_max_hp_loss = 0
                clear_all_status_effects(warrior)
                # Re-apply rot since Chimera didn't draw that move
                warrior.rot_max_hp_loss = _saved_rot_loss
                warrior.rot_base_max_hp = _saved_rot_base
                warrior.max_hp          = max(1, warrior.max_hp - _saved_rot_loss)
                warrior.max_overheal    = int(warrior.max_hp * 1.10)
            else:
                clear_all_status_effects(warrior)
                print(wrap("🟫 The figure's touch burns the rot away — your body remembers its true shape."))
            warrior.hp = min(warrior.max_hp, warrior.hp + heal)
            print(f"  ✨ Stabilised — HP restored to {warrior.hp}/{warrior.max_hp}")
            print(f"  ✨ All status effects cleared")
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "\"Go now,\" she says. Her voice is quieter than before. "
                "Strained. \"I am limited in how much I can intervene.\""
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "Time snaps back. The Chimera staggers — confused, disoriented. "
                "The arena gates are open."
            ))
            print()
            print(wrap(
                "You don't look back."
            ))
            input("\nPress Enter to continue...")

            # ----- Encouragement for survived-but-didn't-finish-the-fight -----
            # Player earned the intervention by surviving 4+ cycles. They didn't
            # land the kill, but they proved themselves. Give them a heroic
            # send-off that nudges toward a retry rather than a clean goodbye.
            space()
            print("─" * 50)
            print(wrap(
                "Well fought, warrior. You stood against something far older "
                "than the arena, and you survived. The figure's intervention "
                "saved your life — but the deeper victory is yours alone to claim.",
                WIDTH
            ))
            space()
            print(wrap(
                "The Chimera still draws breath, and so do you. "
                "The story isn't over. Care to try again?",
                WIDTH
            ))
            print("─" * 50)
            space()

        # End-of-run wrap-up — outcome depends on whether intervention saved them
        # cycles >= 4 means the intervention narrative played; < 4 means overwhelmed
        chimera_outcome = "intervention" if cycles >= 4 else "defeat"

        show_end_summary(warrior)
        _final_score = show_run_score(warrior, outcome=chimera_outcome)
        view_combat_log()
        display_at_end_of_run(warrior, _final_score or 0, outcome=chimera_outcome)

        print("═" * 50)
        print()
        print(wrap(
            "Thank you for playing the Journey to Winter Haven demo."
        ))
        print()
        print(wrap(
            "More content coming soon."
        ))
        print()
        print("═" * 50)
        prompt_play_again()  # v0.6.14: ask y/n instead of just closing

    # Strip the temporary max AP bonus granted before the fight
    warrior.max_ap = max(1, warrior.max_ap - 2)
    warrior.ap     = min(warrior.ap, warrior.max_ap)

    return result


def patronus_fight(warrior):
    """
    Evil path boss encounter — Patronus, Protector of Winter Haven.

    Triggered when player forces the Fallen Warrior to suffer.

    Win  → Patronus hits 0 HP. Death Defier fires — his ancient blood
           refuses to give out and he rises, shield gone. The Beast Gods
           surround the player in a stronger shield. Patronus strikes it,
           no effect. The Beast Gods banish him; he leaves the arena a
           shadow of what he was. Patronus survives in the world (to be
           hunted down later on the evil path) but the fight ENDS here.
           Tainted Champion's Breastplate drops (corrupted: +7 DEF -5 HP).
           story_flag: "patronus_breastplate_dropped"
           Guardian of Winter Haven later uses a weaker replacement shield.

    Loss (cycles < 4) → Regular defeat. No intervention.

    Loss (cycles >= 4) → Beast Gods intervene — stronger shield, Patronus teleported out.
           story_flag: "patronus_intervention"
           Child later seeks out the shield.
    """
    patronus = Patronus()

    # --- Evil path entry scene ---
    print("\n" + "═" * 50)
    print("   ⚔️  A VOICE FROM ACROSS THE ARENA")
    print("═" * 50)
    print()
    print(wrap(
        "You pick up the Fallen Warrior's essence and walk toward "
        "the master of the arena. The gold is already at your feet. "
        "The crowd roars."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "\"VILE CREATURE.\""
    ))
    print()
    print(wrap(
        "The voice hits you — piercing the atmosphere of the arena. "
        "Deep. Certain. Furious. The crowd goes silent."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "A figure drops from the upper wall, landing in a crouch on the sand. "
        "He straightens slowly. Armoured. A shield on one arm, "
        "a weapon in the other. His eyes find yours across the arena floor."
    ))
    print()
    print(wrap(
        "\"I will not forgive such evil.\""
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "He takes one step forward — and stops. "
        "A barrier shimmers into existence around you, pale and crackling. "
        "A shield. Not yours."
    ))
    print()
    print(wrap(
        "\"GOOD CHOICE, CHAMPION.\""
    ))
    print()
    print(wrap(
        "The Beast Gods' voices curl through the air like smoke. "
        "Burning energy licks across your body — your wounds close, "
        "your exhaustion burns away."
    ))
    print()
    input("Press Enter...")
    print()

    # Full heal, status clear, and temporary max AP boost
    warrior.hp     = warrior.max_hp
    warrior.max_ap += 2
    warrior.ap     = warrior.max_ap
    clear_all_status_effects(warrior)

    print(f"  🔥 HP fully restored: {warrior.hp}/{warrior.max_hp}")
    print(f"  🔥 AP fully restored: {warrior.ap}/{warrior.max_ap}  (+2 max AP — the Beast Gods' favour burns through you)")
    print(f"  🔥 All status effects cleared")
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Patronus strides forward. He swings once — not at you. "
        "At the shield."
    ))
    print()
    print(wrap(
        "It cracks. A spiderweb fracture runs across the barrier. "
        "The Beast Gods say nothing."
    ))
    print()
    input("Press Enter...")
    print()
    print(wrap(
        "Anger flashes in his eyes — not the cold fury of a soldier. "
        "Something rawer. Personal."
    ))
    print()
    print(wrap(
        "\"You die NOW.\""
    ))
    print()
    input("\nPress Enter to face Patronus...")

    try:
        result = battle(warrior, patronus)
    finally:
        # Always restore DEF reduced by Patronus Defence Break — even on crash/exception
        _restore_patronus_def(warrior)

    cycles = getattr(patronus, "combat_cycles", 0)

    if result:
        # -----------------------------------------------
        # VICTORY — Patronus banished, disgrace, demo end
        # -----------------------------------------------
        warrior.story_flags.add("patronus_breastplate_dropped")

        print("\n" + "=" * 50)
        print("   ⚔️  PATRONUS BANISHED")
        print("=" * 50)
        print()
        print(wrap(
            "Patronus stands motionless on the sand. The shield around you "
            "fades. His weapon hangs at his side. The arena holds its breath."
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "A piece of his armour breaks free and falls — heavy, final, "
            "ringing against the stone."
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "\"YOU HAVE LOST.\""
        ))
        print()
        print(wrap(
            "The Beast Gods' voices fill the arena — cold, dismissive. "
            "Not angry. Worse than angry. Indifferent."
        ))
        print()
        print(wrap(
            "\"BE GONE.\""
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "Patronus turns toward the gate."
        ))
        print()
        print(wrap(
            "And then — the air changes. The cold indifference is gone. "
            "What replaces it is colder."
        ))
        print()
        print(wrap(
            "\"YOU BIT THE HAND THAT FED YOU, PATRONUS.\""
        ))
        print()
        print(wrap(
            "He stops. He does not turn around."
        ))
        print()
        print(wrap(
            "\"YOUR TIME IS LIMITED. YOU WILL NOT LONG SURVIVE.\""
        ))
        print()
        print(wrap(
            "The words settle into the stone of the arena like a brand. "
            "Patronus's shoulders rise — once — then fall. He understands "
            "what has just been spoken over him. A century of protection, "
            "withdrawn in a single breath. He has been marked."
        ))
        print()
        input("Press Enter...")
        print()
        print(wrap(
            "He does not look back at the overseers' box. "
            "He does not look at the crowd."
        ))
        print()
        print(wrap(
            "He glances over his shoulder — just once — at you. "
            "Then he walks. Head down. Each step measured. "
            "A shadow of what he was."
        ))
        print()
        print(wrap(
            "The crowd does not cheer. They watch in silence as the Protector "
            "of Winter Haven leaves the arena in disgrace — and under sentence."
        ))
        print()
        input("Press Enter...")
        print()

        shield = make_loot("Patronus", monster_level=5)
        if shield:
            # v0.6.14: clear combat fatigue before equipping the breastplate
            # (same defensive pattern as Chimera scale — see notes there).
            warrior.fatigue_def_loss  = 0
            warrior.fatigue_save_tier = 0
            print(wrap(
                "The piece of armour lies where it fell. "
                "Dense, dark at the edges — warped by the Beast Gods' touch. "
                "The protection is real. So is the cost."
            ))
            print(f"\n🎁 {shield.short_label()}")
            offer = input("\nEquip the Tainted Champion's Breastplate? (y/n)\n> ").strip().lower()
            if offer == "y":
                # v0.6.19: defensive — armor has no equip-block paths today,
                # but using the new contract keeps us safe if slot rules change.
                if equip_item(warrior, shield):
                    print(wrap(f"You strap on the breastplate. Defence +{shield.defence}, but you feel it settling into you like a debt."))
                else:
                    warrior.inventory.append(shield)
                    print(wrap(f"{shield.name} saved to your bag instead."))
            else:
                warrior.inventory.append(shield)
                print("You store it. You'll deal with what it cost later.")
            print()

        # Award Dark Champion title — evil path true ending
        print("=" * 50)
        print("🏅  TITLE UNLOCKED: Dark Champion!")
        print("=" * 50)
        print(wrap(
            "The Beast Gods' mark is on you now. "
            "You feel their favour coursing through you — raw, hungry, powerful."
        ))
        print()
        award_title_with_buff(warrior, "dark_champion")

        # v0.6.08: Patronus victory gold reward — Beast Gods favour the evil path
        award_gold(warrior, 100)
        print(f"\n🪙 The Beast Gods leave +100 gold at your feet. Total: {warrior.gold} gold.")

        # v0.6.08: record final-boss kill for per-fight score system
        # `cycles` is the boss-fight equivalent of turn_count
        record_fight_score(warrior, patronus, cycles)

        print()
        # End-of-run wrap-up — proper order: stats → score → combat log → leaderboard → demo close
        show_end_summary(warrior)
        _final_score = show_run_score(warrior, outcome="patronus_victory")
        view_combat_log()
        display_at_end_of_run(warrior, _final_score or 0, outcome="patronus_victory")

        print("=" * 50)
        print()
        print(wrap(
            "Thank you for playing the Journey to Winter Haven demo."
        ))
        print()
        print(wrap(
            "More content coming soon."
        ))
        print()
        print("=" * 50)
        prompt_play_again()  # v0.6.14: ask y/n instead of just closing
        return

    else:
        # -----------------------------------------------
        # DEFEAT — check if player proved themselves
        # -----------------------------------------------
        if cycles < 4:
            print("\n" + "=" * 50)
            print("   💀 OVERWHELMED")
            print("=" * 50)
            print(wrap(
                "Patronus stands over you, unhurried. "
                "He has done this a hundred times. He will do it again."
            ))
            input("\nPress Enter to continue...")

        else:
            # Survived 4+ cycles — Beast Gods intervene, Patronus teleported out
            warrior.story_flags.add("patronus_intervention")

            print("\n" + "=" * 50)
            print("   🐍 THE BEAST GODS INTERVENE")
            print("=" * 50)
            print()
            print(wrap(
                "You fall to one knee. Patronus advances. "
                "His shield arm rises."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "Then the air changes. A barrier erupts around you — "
                "not the cracked flicker from before. "
                "Something solid. Blinding. Patronus stops dead."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "He swings at it. Full force. "
                "The shield doesn't crack. Doesn't even shudder."
            ))
            print()
            print(wrap(
                "\"ENOUGH.\""
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "The Beast Gods' voice fills the arena like pressure filling a sealed room. "
                "\"THIS ONE IS OUR PAWN. BE GONE.\""
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "Patronus doesn't move. For a moment he just stands there, "
                "chest heaving, staring at you through the barrier."
            ))
            print()
            print(wrap(
                "Then the air folds around him. He doesn't disappear — "
                "he's taken. Pulled. The arena floor where he stood "
                "is empty before you finish blinking."
            ))
            print()
            input("Press Enter...")
            print()
            print(wrap(
                "But you saw his eyes before he went. "
                "Not defeat. Not acceptance."
            ))
            print()
            print(wrap(
                "Rage. Pure and patient. The kind that keeps."
            ))
            print()
            print(wrap(
                "He will have his revenge."
            ))
            input("\nPress Enter to continue...")

            # ----- Encouragement for survived-but-didn't-finish-the-fight -----
            # Player earned the intervention by surviving 4+ cycles. They didn't
            # land the kill on Patronus, but they proved themselves to the
            # Beast Gods. Darker tone than Chimera's send-off, but still nudges
            # toward a retry.
            space()
            print("─" * 50)
            print(wrap(
                "Well fought, warrior. You did what no one in the arena thought "
                "possible — you bled the old protector and held your ground "
                "long enough for the Beast Gods themselves to take notice.",
                WIDTH
            ))
            space()
            print(wrap(
                "Patronus walks free, but so do you. He carries his rage. "
                "You carry the lesson. Care to try again?",
                WIDTH
            ))
            print("─" * 50)
            space()

        # End-of-run wrap-up — outcome depends on whether intervention saved them
        # cycles >= 4 means the intervention narrative played; < 4 means overwhelmed
        patronus_outcome = "intervention" if cycles >= 4 else "defeat"

        show_end_summary(warrior)
        _final_score = show_run_score(warrior, outcome=patronus_outcome)
        view_combat_log()
        display_at_end_of_run(warrior, _final_score or 0, outcome=patronus_outcome)

        print("=" * 50)
        print()
        print(wrap(
            "Thank you for playing the Journey to Winter Haven demo."
        ))
        print()
        print(wrap(
            "More content coming soon."
        ))
        print()
        print("=" * 50)
        prompt_play_again()  # v0.6.14: ask y/n instead of just closing

    # Strip the temporary max AP bonus granted before the fight
    warrior.max_ap = max(1, warrior.max_ap - 2)
    warrior.ap     = min(warrior.ap, warrior.max_ap)

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

        # Reset bonus action for every new opponent
        warrior.bonus_action_used = False

        # v0.6.21: reset per-fight scoring flags. These mirror berserk_used /
        # death_defier_used at their trigger sites but, unlike those, are
        # cleared at the START of every fight so record_fight_score only
        # awards the +20 / +50 bonuses for the fight they actually fired in.
        # (berserk_used / death_defier_used can't be used for this — they
        # carry across fights by design to gate re-triggering.)
        warrior.berserk_used_this_fight = False
        warrior.death_defier_used_this_fight = False

        # Charismatic Speaker mastery — +15% ATK for the entire fight
        if "charismatic_speaker" in getattr(warrior, "titles", set()):
            bonus = max(1, math.ceil(warrior.max_atk * 0.15))
            warrior.min_atk += bonus
            warrior.max_atk += bonus
            warrior.charismatic_speaker_bonus = bonus  # stored so reset strips the exact amount
            print(wrap(f"🎤 Charismatic Speaker: Your presence surges — +{bonus} ATK for this fight! (15% of ATK)"))

        # Flayed One: starts with 1 charge — immediately apply ATK boost and player debuff
        if hasattr(enemy, "flayed_charges"):
            enemy.flayed_base_min_atk = enemy.min_atk
            enemy.flayed_base_max_atk = enemy.max_atk
            charges = enemy.flayed_charges  # = 1 at spawn
            enemy.min_atk = enemy.flayed_base_min_atk + charges
            enemy.max_atk = enemy.flayed_base_max_atk + charges
            warrior.flayed_base_min_atk = warrior.min_atk
            warrior.flayed_base_max_atk = warrior.max_atk
            warrior.flayed_base_defence = warrior.defence
            warrior.min_atk = max(1, warrior.flayed_base_min_atk - charges)
            warrior.max_atk = max(1, warrior.flayed_base_max_atk - charges)
            warrior.defence = max(0, warrior.flayed_base_defence  - charges)
            print(wrap(
                f"🧠 {enemy.display_name}'s psychic aura is already pulsing — "
                f"you feel your body weaken before the fight even begins! "
                f"Your ATK and DEF are reduced by 1."
            ))

        log()
        log("=" * 40)
        log(f"BATTLE START: {warrior.name} vs {enemy.display_name}")
        try:
            log(f"  {warrior.name}  HP:{warrior.hp}/{warrior.max_hp}  ATK:{warrior.min_atk}-{warrior.max_atk}  DEF:{warrior.defence}")
            log(f"  {enemy.display_name}  HP:{enemy.hp}/{enemy.max_hp}  ATK:{enemy.min_atk}-{enemy.max_atk}  DEF:{getattr(enemy, 'defence', 0)}")
        except AttributeError as e:
            log(f"  (stat snapshot unavailable: {e})")
        log("=" * 40)
        reset_battle_stats()

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
            _eatk = enemy_attack(enemy, warrior)
            if _eatk:
                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)

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

                    # v0.6.14: Combat fatigue save (player side).
                    # Fires once per player turn after the threshold (10 for
                    # regular fights, 15 for bosses). Silent d20 vs escalating
                    # DC — pass = focus holds, fail = lose 1-2 DEF and tier
                    # resets. See roll_fatigue_save() for full mechanic.
                    roll_fatigue_save(warrior, turn_count, enemy, is_player=True)

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
                            turn_spent = True
                            warrior.last_turn_skipped = True 
                            warrior_turn = False
                            player_turn_started = False
                            continue 

                    # --- OTHER TURN STOPS (Paralyze, Standard Blind, etc.) ---
                    elif resolve_player_turn_stop(warrior):
                        if getattr(warrior, "last_turn_skipped", False) and getattr(enemy, "name", "") != "Young Chimera":
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
                                    turn_spent = True
                                    warrior.last_turn_skipped = True
                                    warrior_turn = False
                                    player_turn_started = False
                                    continue
                            else:
                                # Struggle — paralyze fades via chain guard next turn
                                print("⚡ You grit your teeth and endure... the paralysis will fade!")
                                log("  [STATUS] PARALYZED — player chose to struggle. Turn lost.")
                                turn_spent = True
                                warrior.last_turn_skipped = True
                                warrior_turn = False
                                player_turn_started = False
                                continue
                        elif getattr(warrior, "is_blinded", False) and warrior.skill_ranks.get("heal", 0) >= 2:
                            # Blinded + First Aid R2+ — player can cure it
                            heal_rank = warrior.skill_ranks.get("heal", 0)
                            print(f"\n👁️ Your vision is gone — you are BLINDED!")
                            print(f"🩹 Your training kicks in... you might be able to treat this.")
                            print(f"\n  1) Use First Aid (Rank {heal_rank}) — cure Blind")
                            print(f"  2) Struggle — lose your turn (Blind fades eventually)")
                            blind_choice = input("\nChoice: ").strip()
                            if blind_choice == "1":
                                result = heal(warrior, mode="combat")
                                if result:
                                    warrior.is_blinded = False
                                    warrior.blind_turns = 0
                                    warrior.blind_long = False
                                    warrior.turn_stop = 0
                                    warrior.turn_stop_reason = ""
                                    warrior.turn_stop_chain_guard = False
                                    warrior.last_turn_skipped = False
                                    log(f"  [STATUS] BLINDED — player used First Aid (Rank {heal_rank}) to cure it. Turn spent.")
                                    warrior_turn = False
                                    player_turn_started = False
                                    continue
                                else:
                                    print("👁️ You can't treat your eyes in time — you lose your action!")
                                    log("  [STATUS] BLINDED — First Aid failed/cancelled. Turn lost.")
                                    turn_spent = True
                                    warrior.last_turn_skipped = True
                                    warrior_turn = False
                                    player_turn_started = False
                                    continue
                            else:
                                print("👁️ You endure the darkness... your vision may return.")
                                log("  [STATUS] BLINDED — player chose to struggle. Turn lost.")
                                turn_spent = True
                                warrior.last_turn_skipped = True
                                warrior_turn = False
                                player_turn_started = False
                                continue
                        else:
                            print(f"🧊⚡ Your muscles lock up — you're {warrior.turn_stop_reason.upper()} and lose your action!")
                            log(f"  [STATUS] {warrior.turn_stop_reason.upper()} — turn lost.")
                            warrior.last_turn_skipped = True
                            turn_spent = True
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
                            try_death_defier(warrior, "dot", enemy=enemy)

                        dot_math_breakdown(warrior, dot_parts, tag="DOT")
                        _dot_breakdown = ", ".join(f"{n} {v}" for n, v in dot_parts)
                        log(f"  [DOT] {warrior.name} takes {dot_total} damage ({_dot_breakdown}). HP now: {warrior.hp}/{warrior.max_hp}")
                        log_dot(warrior.name, dot_total, is_player_target=True)
                        for _fade in dot_fades:
                            print(_fade)
                    if not warrior.is_alive():
                        print("You have succumbed to your wounds...")
                        log(f"  [DEATH] {warrior.name} killed by DoT (poison/burn/acid) on turn {turn_count}.")
                        log(f"  [RESULT] DEFEAT — {warrior.name} fell to status damage.")
                        log_battle_summary(warrior.name, enemy.display_name, "DEFEAT", turn_count)
                        # End-of-run wrap-up (stats, score, combat log, thanks for playing)
                        # is handled by arena_battle's death block — single source of truth.
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
                # 5) COMBAT MEDIC PASSIVE (First Aid rank 5 mastery)
                # ==========================
                if "combat_medic" in getattr(warrior, "titles", set()) and warrior.is_alive():
                    regen = max(1, int(warrior.max_hp * 0.10))
                    before = warrior.hp
                    warrior.hp = min(warrior.max_hp, warrior.hp + regen)
                    gained = warrior.hp - before
                    if gained > 0:
                        print(wrap(f"🩹 Combat Medic: You recover {gained} HP."))

                # ==========================
                # 6) CHECK BERSERK TRIGGER
                # ==========================
                check_berserk_trigger(warrior)

                # ==========================
                # 7) ADRENALINE UPDATE
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
                has_weapon    = warrior.get_weapon() is not None   # v0.6.16
                has_accessory = warrior.equipment.get("accessory") is not None
                trinket_item  = warrior.equipment.get("trinket")
                # Trinket counts as a combat-menu option if it uses charges (Waterlogged Stone)
                # or is a one-shot consumable (Trinket of Berserk).
                trinket_is_charge_based = trinket_item is not None and getattr(trinket_item, "stone_max_charges", 0) > 0
                trinket_is_consumable   = trinket_item is not None and getattr(trinket_item, "consume_on_use", False)
                has_trinket   = trinket_is_charge_based or trinket_is_consumable
                trinket_charges = trinket_item.stone_charges if trinket_is_charge_based else 0
                trinket_max     = trinket_item.stone_max_charges if trinket_is_charge_based else 0
                # Build the menu label based on which type of trinket
                if trinket_is_charge_based:
                    trinket_label = f"Stone ({trinket_charges}/{trinket_max})"
                elif trinket_is_consumable:
                    trinket_label = f"Crush ({trinket_item.name})"
                else:
                    trinket_label = ""

                # --- Build dynamic attack lines and slot numbers ---
                # Scenario A: both equipped  → 1) Weapon Attack  2) Accessory Attack  3) Special ...
                # Scenario B: accessory only → 1) Attack (Accessory Name)  2) Special ...
                # Scenario C: weapon only / neither → 1) Attack  2) Special ...
                # Trinket always appears before Potion if equipped
                if has_weapon and has_accessory:
                    acc_name      = warrior.equipment["accessory"].name
                    special_num   = "3"
                    if has_trinket:
                        trinket_num   = "4"
                        potion_num    = "5"
                        stats_num     = "6"
                        run_num       = "7"
                        valid_choices = ("1", "2", "3", "4", "5", "6", "7")
                        prompt = (
                            "Your move:\n"
                            f"1) Weapon Attack\n"
                            f"2) Accessory Attack ({acc_name})   "
                            f"{special_num}) Special   {trinket_num}) {trinket_label}   "
                            f"{potion_num}) Potion   {stats_num}) Stats   {run_num}) Run"
                        )
                    else:
                        trinket_num   = None
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
                    if has_trinket:
                        trinket_num   = "3"
                        potion_num    = "4"
                        stats_num     = "5"
                        run_num       = "6"
                        valid_choices = ("1", "2", "3", "4", "5", "6")
                        prompt = (
                            f"Your move:   1) Attack ({acc_name})   "
                            f"{special_num}) Special   {trinket_num}) {trinket_label}   "
                            f"{potion_num}) Potion   {stats_num}) Stats   {run_num}) Run"
                        )
                    else:
                        trinket_num   = None
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
                    if has_trinket:
                        trinket_num   = "3"
                        potion_num    = "4"
                        stats_num     = "5"
                        run_num       = "6"
                        valid_choices = ("1", "2", "3", "4", "5", "6")
                        prompt = (
                            f"Your move:   1) Attack   "
                            f"{special_num}) Special   {trinket_num}) {trinket_label}   "
                            f"{potion_num}) Potion   {stats_num}) Stats   {run_num}) Run"
                        )
                    else:
                        trinket_num   = None
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

                # --- Developer shortcut: quit / pause (v0.6.19: ! prefix) ---
                if cleaned in ("!q", "!quit"):
                    print("\n🔄 Developer Shortcut: Quit / Pause triggered.")
                    raise RestartException


                # ----------------------------------------------------
                # Debug console shortcut (v0.6.19: ! prefix)
                # ----------------------------------------------------
                if cleaned == "!debug":
                    debug_menu(warrior, enemy)
                    continue

                # Started with '!' but wasn't a known combat shortcut.
                # Bail before invalid-choice handler so the user gets a
                # useful message rather than "Invalid choice, try again."
                if cleaned.startswith("!"):
                    print(f"Unknown dev shortcut in combat: {raw}")
                    print("Available: !debug, !quit (or !q)")
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

                    warrior.fate_titles.add("coward")
                    warrior.endings.add("Disgraced One")
                    # v0.6.11: Coward death now flows through normal end-of-run sequence
                    # so the player sees stats → score → combat log → leaderboard
                    # instead of an abrupt quit().
                    show_end_summary(warrior)
                    _final_score = show_run_score(warrior, outcome="coward")
                    view_combat_log()
                    display_at_end_of_run(warrior, _final_score or 0, outcome="coward")
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
                    _atk = player_basic_attack(warrior, enemy, multiplier=reduction, use_accessory=use_acc)
                    if _atk:
                        log_attack(warrior.name, enemy.display_name, _atk["roll"], _atk["actual"], _atk["blocked"],
                                   bonus_parts=_atk.get("bonus_parts"), effect_tag=_atk.get("elem_tag", ""), is_player=True, is_special=False)
                        # Armor Piercer — -1 enemy DEF on every basic attack
                        if "armor_piercer" in getattr(warrior, "titles", set()):
                            if getattr(enemy, "defence", 0) > 0:
                                enemy.defence = max(0, enemy.defence - 1)
                                print(wrap(f"🪖 Armor Piercer: {enemy.display_name}'s defence reduced to {enemy.defence}!"))
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
                    _atk = player_basic_attack(warrior, enemy, multiplier=reduction, use_accessory=True)
                    if _atk:
                        log_attack(warrior.name, enemy.display_name, _atk["roll"], _atk["actual"], _atk["blocked"],
                                   bonus_parts=_atk.get("bonus_parts"), effect_tag=_atk.get("elem_tag", ""), is_player=True, is_special=False)
                        # Armor Piercer — -1 enemy DEF on every basic attack
                        if "armor_piercer" in getattr(warrior, "titles", set()):
                            if getattr(enemy, "defence", 0) > 0:
                                enemy.defence = max(0, enemy.defence - 1)
                                print(wrap(f"🪖 Armor Piercer: {enemy.display_name}'s defence reduced to {enemy.defence}!"))
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
                    used = use_potion_menu(warrior, in_combat=True)
                    if used == "bonus":
                        log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp} (bonus action — turn not spent)")
                        print(wrap("⚡ Bonus action used — you still have your turn!"))
                        continue  # turn NOT spent
                    elif used:
                        log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")
                        turn_spent = True
                    else:
                        continue

                elif trinket_num and choice == trinket_num:
                    if trinket_is_consumable:
                        # One-shot consumable trinket — currently Trinket of Berserk
                        log(f"  [PLAYER] crushed {trinket_item.name}")
                        used = use_consumable_trinket(warrior, trinket_item)
                        if used:
                            log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")
                            turn_spent = True
                        else:
                            continue
                    else:
                        # Charge-based trinket (Waterlogged Stone)
                        log(f"  [PLAYER] chose Waterlogged Stone")
                        used = use_waterlogged_stone(warrior)
                        if used == "bonus":
                            log(f"  [RESULT] {warrior.name} AP: {warrior.ap}/{warrior.max_ap} (bonus action — turn not spent)")
                            print(wrap("⚡ Bonus action used — you still have your turn!"))
                            continue  # turn NOT spent
                        elif used:
                            log(f"  [RESULT] {warrior.name} AP: {warrior.ap}/{warrior.max_ap}")
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
                    # --- Patronus Death Defier ---
                    # Lore: Patronus is a demi-god and cannot be killed outright.
                    # His ancient blood refuses to give out — he RISES, shield gone,
                    # intent on continuing. But the Beast Gods surround the player
                    # in a stronger shield. Patronus strikes it — no effect. Then
                    # the Beast Gods banish him. Mechanically: fight ENDS in victory.
                    # The disgrace exit cutscene runs in patronus_fight() after this.
                    if (enemy.name == "Patronus"
                            and getattr(enemy, "death_defier_active", False)
                            and not getattr(enemy, "death_defier_used", True)):
                        enemy.death_defier_used   = True
                        enemy.death_defier_active = False

                        # Strip shield — Beast Gods withdraw their favour
                        if getattr(enemy, "shield_equipped", False):
                            enemy.defence        = max(0, enemy.defence - Patronus.SHIELD_DEF_BONUS)
                            enemy.shield_equipped = False

                        print("\n" + "=" * 50)
                        print("   ⚡ DEATH DEFIER — ANCIENT BLOOD REFUSES")
                        print("=" * 50)
                        print(wrap(
                            "Patronus drops to the sand. The arena holds its breath. "
                            "Then — a pulse. Ancient blood refusing to give out. "
                            "He rises, slower, shield gone, but still standing."
                        ))
                        print()
                        input("Press Enter...")
                        print()
                        print(wrap(
                            "The air around you crackles. A shield — stronger than before, "
                            "denser, woven with the same burning energy that healed you — "
                            "blooms outward and wraps you completely. The Beast Gods speak "
                            "in your bones, not your ears."
                        ))
                        print()
                        print(wrap(
                            "\"HE WILL NOT TOUCH YOU.\""
                        ))
                        print()
                        input("Press Enter...")
                        print()
                        print(wrap(
                            "Patronus charges. He swings — a strike that would have "
                            "shattered stone a moment ago."
                        ))
                        print()
                        print(wrap(
                            "The shield does not move. The blow lands and dies against it "
                            "without a sound. His weapon arm drops. He looks at you "
                            "through the barrier, and something in his face goes still."
                        ))
                        print()
                        print(wrap(
                            "He understands. The Beast Gods are done with him."
                        ))
                        print()
                        log(f"  [DEATH DEFIER] Patronus rises but Beast Gods shield the player — his strike has no effect. Banishment follows.")
                        input("Press Enter...")
                        # Fall through — battle resolves as victory.
                        # patronus_fight() will run the banishment + disgrace exit cutscene.

                    # Reset defense
                    if hasattr(warrior, "original_defence"):
                        warrior.defence = warrior.original_defence
                        del warrior.original_defence

                    print(f"\nYou have defeated {enemy.display_name}!")
                    log(f"  [DEATH] {enemy.display_name} defeated by {warrior.name} on turn {turn_count}.")
                    award_gold(warrior, enemy.gold)
                    warrior.monster_essence.extend(enemy.essence)

                    # v0.6.08: record per-fight score (threat-based, with bonuses)
                    record_fight_score(warrior, enemy, turn_count)

                   

                    # v0.6.14: clear combat fatigue (and reset save tier) BEFORE
                    # the loot offer. Equipping armour while fatigue is still
                    # active means the effective DEF math momentarily looks
                    # weird (new base DEF minus old fatigue). Numerically it
                    # all comes out right after reset_between_rounds, but we
                    # match the defence_warp fix pattern and clear it here so
                    # there's no intermediate confusing state.
                    warrior.fatigue_def_loss  = 0
                    warrior.fatigue_save_tier = 0

                    # 1. LOOT DROP — skip for Fallen Warrior, Chimera, Patronus (handled in their own fight functions)
                    if enemy.name not in ("Fallen Warrior", "Young Chimera", "Patronus"):
                        loot = make_loot(enemy.name, monster_level=getattr(enemy, "level", 1), round_num=round_num)
                        if loot:
                            offer_loot(warrior, loot)

                    # 2. XP — skip for Fallen Warrior, Chimera, Patronus
                    if enemy.name not in ("Fallen Warrior", "Young Chimera", "Patronus"):
                        animate_xp_results(warrior, enemy.xp)

                    # 3. BOSS/VICTORY CHECK
                    if enemy.name == "Fallen Warrior":
                        # Clamp to 1 HP — moral choice delivers the killing blow
                        enemy.hp = 1
                        _award_defence_break(warrior)

                        print("\n✨ The Fallen Warrior collapses to his knees, barely breathing...")
                        print(wrap(
                            "He is beaten. Broken. One blow away from the end. "
                            "The crowd holds its breath."
                        ))
                        input("\nPress Enter...")

                        # Moral choice fires — weapon offered, choice does killing blow, title awarded inside
                        fallen_warrior_moral_choice(warrior, fallen=enemy)

                        # Now finish him — enemy.hp already set to 0 inside moral choice
                        log(f"  [RESULT] VICTORY — {warrior.name} defeated the Fallen Warrior! (Champion ending)")
                        return "win"

                    # 4. PAUSE AND REST
                    log(f"  [RESULT] VICTORY — {warrior.name} defeated {enemy.display_name}. Final HP: {warrior.hp}/{warrior.max_hp}")
                    log_battle_summary(warrior.name, enemy.display_name, "VICTORY", turn_count)
                    if enemy.name not in ("Young Chimera", "Patronus"):
                        input("\nPress Enter to continue.")
                    if not skip_rest and enemy.name not in ("Young Chimera", "Patronus"):
                        rest_phase(warrior)

                    # reset_between_rounds handles all status clearing cleanly
                    reset_between_rounds(warrior)

                    # Award gold — Chimera pays nothing, Patronus handled post-tournament
                    if enemy.name not in ("Young Chimera", "Patronus"):
                        _gold_result = calculate_gold_reward(enemy, turn_count, warrior)
                        display_gold_earned(_gold_result)
                        award_pending_gold(warrior, _gold_result)

                    # Final bosses return immediately — their fight functions handle endings
                    if enemy.name in ("Young Chimera", "Patronus"):
                        return True

                    return True

        
            # ---------------------------------------
            # ENEMY TURN
            # ---------------------------------------
            
            else:
                log()
                log(f"--- Turn {turn_count}: {enemy.display_name}'s turn  (HP:{enemy.hp}/{enemy.max_hp}) ---")

                # v0.6.14: Combat fatigue save (monster side). Independent from
                # the player's save — both sides roll their own d20s. Fires
                # once per monster turn after the threshold (10 regular / 15 boss).
                roll_fatigue_save(enemy, turn_count, enemy, is_player=False)

                # Tick any DoT the player's accessory applied to the enemy.
                # collect_dot_ticks() already exists for the hero — we just
                # pass the enemy instead.  Same function, zero new code.
                enemy_dot, enemy_dot_parts, enemy_dot_fades = collect_dot_ticks(enemy)
                if enemy_dot > 0:
                    enemy.hp = max(0, enemy.hp - enemy_dot)
                    dot_math_breakdown(enemy, enemy_dot_parts, tag="Your DoT")
                    _edot_breakdown = ", ".join(f"{n} {v}" for n, v in enemy_dot_parts)
                    log(f"  [DOT] {enemy.display_name} takes {enemy_dot} damage ({_edot_breakdown}). HP now: {enemy.hp}/{enemy.max_hp}")
                    log_dot(enemy.display_name, enemy_dot, is_player_target=False)
                    for _fade in enemy_dot_fades:
                        print(_fade)
                    if not enemy.is_alive():
                        print(wrap(f"\n{enemy.display_name.title()} collapses from your damage over time!"))
                        log(f"  [DEATH] {enemy.display_name} killed by DoT on turn {turn_count}.")

                        # === FULL DEATH / LOOT BLOCK (mirrors the player-turn death block) ===
                        if hasattr(warrior, "original_defence"):
                            warrior.defence = warrior.original_defence
                            del warrior.original_defence

                        print(f"\nYou have defeated {enemy.display_name}!")
                        award_gold(warrior, enemy.gold)
                        warrior.monster_essence.extend(enemy.essence)

                        # v0.6.08: record per-fight score (threat-based, with bonuses)
                        record_fight_score(warrior, enemy, turn_count)

                        if enemy.name == "Fallen Warrior":
                            # Clamp to 1 — moral choice delivers the killing blow
                            enemy.hp = 1
                            _award_defence_break(warrior)
                            print("\n✨ The Fallen Warrior collapses to his knees, barely breathing...")
                            print(wrap(
                                "Your poison/burn finishes what your blade started. "
                                "He is one breath from the end."
                            ))
                            input("\nPress Enter...")
                            fallen_warrior_moral_choice(warrior, fallen=enemy)
                            log(f"  [RESULT] VICTORY — {warrior.name} defeated the Fallen Warrior via DoT! (Champion ending)")
                            return "win"

                        loot = make_loot(enemy.name, monster_level=getattr(enemy, "level", 1), round_num=round_num) if enemy.name not in ("Young Chimera", "Patronus") else None
                        # v0.6.14: clear combat fatigue before loot offer.
                        # Mirrors the player-turn death block — same rationale,
                        # see notes there.
                        warrior.fatigue_def_loss  = 0
                        warrior.fatigue_save_tier = 0
                        if loot:
                            offer_loot(warrior, loot)

                        if enemy.name not in ("Young Chimera", "Patronus"):
                            animate_xp_results(warrior, enemy.xp)

                        log(f"  [RESULT] VICTORY — {warrior.name} defeated {enemy.display_name} via DoT.")
                        log_battle_summary(warrior.name, enemy.display_name, "VICTORY", turn_count)

                        if enemy.name not in ("Young Chimera", "Patronus"):
                            input("\nPress Enter to continue.")
                        if not skip_rest and enemy.name not in ("Young Chimera", "Patronus"):
                            rest_phase(warrior)

                        # reset_between_rounds handles all status clearing cleanly
                        reset_between_rounds(warrior)

                        # Award gold — Chimera pays nothing, Patronus handled post-tournament
                        if enemy.name not in ("Young Chimera", "Patronus"):
                            _gold_result = calculate_gold_reward(enemy, turn_count, warrior)
                            display_gold_earned(_gold_result)
                            award_pending_gold(warrior, _gold_result)

                        return True

                # -----------------------------------------------
                # ENEMY PARALYZE CHECK  (applied by Goblin Shortbow weapon proc)
                # -----------------------------------------------
                # Clear Defence Warp cooldown at the start of each enemy turn
                # (it was set last turn — player has had their breather)
                if getattr(enemy, "warp_on_cooldown", False):
                    enemy.warp_on_cooldown = False

                # Reset stone charge flag — one charge per enemy turn max
                warrior._stone_charged_this_turn = False

                # Tick Defence Break duration down each enemy turn
                _tick_defence_break(enemy)

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
                            _smove_name = SPECIAL_MOVE_NAMES.get(getattr(enemy.special_move, "__name__", ""), "Special Move")
                            log(f"  [ENEMY] {enemy.display_name} uses {_smove_name} (blind x{reduction})")
                            _sdmg = enemy.special_move(enemy, warrior)
                            _stone_absorb_charge(warrior)
                            if _sdmg:
                                log_attack(enemy.display_name, warrior.name, _sdmg, _sdmg, 0,
                                           effect_tag=f"[{_smove_name}]", is_player=False)
                        else:
                            log(f"  [ENEMY] {enemy.display_name} attacks (blind x{reduction})")
                            _eatk = enemy_attack(enemy, warrior)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                        log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")

                        enemy.max_atk = original_max
                        enemy.min_atk = original_min
                        enemy.blind_turns -= 1
                        if enemy.blind_turns == 0:
                            print(wrap(f"✨ {enemy.display_name.title()}'s vision fully clears."))

                else:
                    # --- Psychic Drown: flat ATK boost when locked out ---
                    # If drown is active and warrior can't afford cheapest move,
                    # enemy gets a flat +2 ATK this turn. Consistent penalty
                    # regardless of gap size — defence still applies normally.
                    drown_stacks = getattr(warrior, "drown_stacks", 0)
                    drown_gap_boost = 0
                    if drown_stacks > 0:
                        cheapest_cost = 1 + drown_stacks  # rank 1 + inflation
                        if warrior.ap < cheapest_cost:
                            drown_gap_boost = 2
                            enemy.min_atk += drown_gap_boost
                            enemy.max_atk += drown_gap_boost
                            print(wrap(
                                f"💧 The drowning pressure overwhelms you — "
                                f"{enemy.display_name} senses your weakness! "
                                f"(+{drown_gap_boost} ATK this turn)"
                            ))

                    # Fallen Warrior uses desperation-aware trigger; all others use tiered AI
                    if enemy.name == "Fallen Warrior":
                        should_special = fallen_warp_should_trigger(enemy, warrior)
                    else:
                        should_special = monster_ai_check(enemy, turn_count)

                    # Flayed One / Drowned One: always basic attacks, THEN 33% chance to also use special
                    if enemy.name in ("Flayed One", "Drowned One"):
                        log(f"  [ENEMY] {enemy.display_name} attacks")
                        _eatk = enemy_attack(enemy, warrior)
                        if _eatk:
                            _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                            log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                        if warrior.is_alive() and monster_ai_check(enemy, turn_count):
                            _smove_name = SPECIAL_MOVE_NAMES.get(getattr(enemy.special_move, "__name__", ""), "Special Move")
                            log(f"  [ENEMY] {enemy.display_name} follows with {_smove_name}")
                            _sdmg = enemy.special_move(enemy, warrior)
                            _stone_absorb_charge(warrior)
                            if _sdmg:
                                log_attack(enemy.display_name, warrior.name, _sdmg, _sdmg, 0,
                                           effect_tag=f"[{_smove_name}]", is_player=False)
                            # v0.6.19: Death Defier check for the chained special.
                            # Basic attack above goes through enemy_attack (has its own check),
                            # but the follow-up special dispatches directly and bypasses it.
                            if warrior.hp <= 0:
                                try_death_defier(warrior, f"{enemy.name} {_smove_name}", enemy=enemy)
                    elif enemy.name == "Young Chimera":
                        # --- FURY OVERLOAD CHECK — fires before normal turn logic ---
                        if getattr(enemy, "chimera_fury_overloading", False):
                            print(wrap(
                                f"\n💥 THE YOUNG CHIMERA UNLEASHES ITS FURY!"
                            ))
                            # Basic attack first (normal defence applies)
                            _eatk = enemy_attack(enemy, warrior)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                            # Then Primordial Surge as true damage (fury_triggered=True suppresses charge display)
                            # Capture actual damage so the combat log reports it correctly
                            # (was previously hardcoded to 0 — bug fixed v0.6.11)
                            _surge_fired = False
                            if warrior.is_alive():
                                _surge_fired = True
                                from monsters import primordial_surge as _ps
                                _surge_dmg = _ps(enemy, warrior, fury_triggered=True)
                                _surge_dmg = _surge_dmg if _surge_dmg is not None else 0
                                log_attack(enemy.display_name, warrior.name,
                                           _surge_dmg, _surge_dmg, 0,
                                           effect_tag="[Primordial Surge — Fury, true dmg]",
                                           is_player=False)
                                # If Surge killed the player, fire Death Defier
                                if warrior.hp <= 0:
                                    try_death_defier(warrior, f"{enemy.name} fury surge", enemy=enemy)
                            # Log overall fury outcome — only mention surge if it actually fired
                            if _surge_fired:
                                log(f"  [ENEMY] Young Chimera — Fury Overload: basic ATK + Primordial Surge")
                            else:
                                log(f"  [ENEMY] Young Chimera — Fury Overload: basic ATK landed killing blow (Surge skipped)")
                            # Reset fury
                            enemy.chimera_fury_charge      = 0
                            enemy.chimera_fury_overloading = False
                        # Strict alternation — special then rest, repeat.
                        # Charge-based — no AP gating. should_special from monster_ai_check tier 5.
                        elif getattr(enemy, "chimera_used_special", False):
                            # Rest turn — basic attack only, no AP regen
                            log(f"  [ENEMY] Young Chimera rests — basic attack")
                            _eatk = enemy_attack(enemy, warrior)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                            enemy.chimera_used_special = False
                        elif should_special and random.random() > 0.25:
                            # Special turn — 75% chance to fire, 25% basic attack feint
                            _sdmg = enemy.special_move(enemy, warrior)
                            _stone_absorb_charge(warrior)
                            # Read move name set by dispatcher after it chose
                            _smove_name = getattr(enemy, "chimera_last_move_name", "Special Move")
                            log(f"  [ENEMY] Young Chimera uses {_smove_name}")
                            if _sdmg:
                                log_attack(enemy.display_name, warrior.name, _sdmg, _sdmg, 0,
                                           effect_tag=f"[{_smove_name}]", is_player=False)
                            enemy.chimera_used_special = True
                            # v0.6.19: Death Defier check for Chimera's main special path.
                            # The Fury Overload path above already has this check (v0.6.11),
                            # but this regular special-turn path was missing it. Same class
                            # of bug as the generic _smove dispatcher.
                            if warrior.hp <= 0:
                                try_death_defier(warrior, f"{enemy.name} {_smove_name}", enemy=enemy)
                        else:
                            # 25% basic attack feint — retry special next turn
                            log(f"  [ENEMY] Young Chimera attacks")
                            _eatk = enemy_attack(enemy, warrior)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                    elif enemy.name == "Patronus":
                        # Tick buffs/debuffs each enemy turn
                        _tick_patronus_war_cry(enemy)
                        _tick_patronus_def_break(warrior)
                        # v0.6.15: passive First Aid trigger — fires once when
                        # HP first drops below 50%. Acts before action picker
                        # so the heal lands before any double-strike attempt.
                        _tick_patronus_passive_first_aid(enemy)

                        # Passive AP regen — only used for Power Charge (costs 2 AP)
                        enemy.ap = min(enemy.max_ap, enemy.ap + 1)

                        action = patronus_ai(enemy, warrior, turn_count)

                        if action == "war_cry":
                            log(f"  [ENEMY] Patronus uses War Cry")
                            patronus_war_cry(enemy)
                            COMBAT_LOG.append(f"  [EFFECT] Patronus War Cry — ATK buffed for next turns")
                            _stone_absorb_charge(warrior)
                        elif action == "double_strike":
                            log(f"  [ENEMY] Patronus uses Double Strike")
                            _sdmg = patronus_double_strike(enemy, warrior)
                            if _sdmg:
                                log_attack("Patronus", warrior.name, _sdmg, _sdmg, 0,
                                           effect_tag="[Double Strike — 2 hits]", is_player=False)
                            _stone_absorb_charge(warrior)
                        elif action == "power_charge":
                            log(f"  [ENEMY] Patronus uses Power Charge")
                            _sdmg = patronus_power_charge(enemy, warrior)
                            if _sdmg:
                                log_attack("Patronus", warrior.name, _sdmg, _sdmg, 0,
                                           effect_tag="[Power Charge — ATK buffed]", is_player=False)
                            _stone_absorb_charge(warrior)
                        elif action == "first_aid":
                            log(f"  [ENEMY] Patronus uses First Aid")
                            patronus_first_aid(enemy)
                            COMBAT_LOG.append(f"  [EFFECT] Patronus First Aid — HP restored")
                            _stone_absorb_charge(warrior)
                        elif action == "defence_break":
                            log(f"  [ENEMY] Patronus uses Defence Break")
                            _def_red = patronus_defence_break(enemy, warrior)
                            COMBAT_LOG.append(f"  [EFFECT] Patronus Defence Break — your DEF reduced by {_def_red}")
                            _stone_absorb_charge(warrior)
                        else:
                            log(f"  [ENEMY] Patronus attacks")
                            _eatk = enemy_attack(enemy, warrior)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                        # v0.6.19: Death Defier check for Patronus damage-dealing actions
                        # (double_strike, power_charge). The basic attack branch already
                        # routes through enemy_attack which has its own check, but the
                        # special actions bypass it — same class of bug as Fallen Warrior.
                        if warrior.hp <= 0:
                            try_death_defier(warrior, f"{enemy.name} {action}", enemy=enemy)
                    elif should_special:
                        _smove_name = SPECIAL_MOVE_NAMES.get(getattr(enemy.special_move, "__name__", ""), "Special Move")
                        log(f"  [ENEMY] {enemy.display_name} uses {_smove_name}")
                        _sdmg = enemy.special_move(enemy, warrior)
                        _stone_absorb_charge(warrior)
                        if _sdmg:
                            log_attack(enemy.display_name, warrior.name, _sdmg, _sdmg, 0,
                                       effect_tag=f"[{_smove_name}]", is_player=False)
                        # v0.6.19: Death Defier check for special-move dispatch path.
                        # The enemy_attack() function has its own check for the basic-attack
                        # path, but specials dispatched here bypass it — that's how a tester
                        # died to Fallen Warrior's Defence Warp with River Spirit primed.
                        # Mirrors the Chimera Fury Surge fix from v0.6.11 changelog.
                        if warrior.hp <= 0:
                            try_death_defier(warrior, f"{enemy.name} special", enemy=enemy)
                    else:
                        log(f"  [ENEMY] {enemy.display_name} attacks")
                        _eatk = enemy_attack(enemy, warrior)
                        if _eatk:
                            _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                            log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                    log(f"  [RESULT] {warrior.name} HP: {warrior.hp}/{warrior.max_hp}")

                    # Restore drown gap boost after attack
                    if drown_gap_boost > 0:
                        enemy.min_atk -= drown_gap_boost
                        enemy.max_atk -= drown_gap_boost

                turn_spent = True

                if not warrior.is_alive():
                    print("\nYou collapse as the arena roars...")
                    log(f"  [DEATH] {warrior.name} was killed by {enemy.display_name} on turn {turn_count}.")
                    log(f"  [RESULT] DEFEAT — {warrior.name} fell to {enemy.display_name}.")
                    log_battle_summary(warrior.name, enemy.display_name, "DEFEAT", turn_count)
                    # End-of-run wrap-up (stats, score, combat log, thanks for playing)
                    # is handled by arena_battle's death block — single source of truth.
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
                else:
                    # Enemy turn just completed — increment cycle counter if tracking
                    if hasattr(enemy, "combat_cycles"):
                        enemy.combat_cycles += 1

                    # Chimera passive fury build — +10% per full round of combat,
                    # stacked on top of any ranked-skill bonuses the player
                    # contributed during their turn. Caps at 100. Triggers the
                    # overload warning the same way chimera_fury_add() does.
                    if enemy.name == "Young Chimera" and not enemy.chimera_fury_overloading:
                        gain = 10
                        enemy.chimera_fury_charge = min(100, enemy.chimera_fury_charge + gain)
                        bar_filled = int(enemy.chimera_fury_charge / 10)
                        bar = "█" * bar_filled + "░" * (10 - bar_filled)
                        print(wrap(
                            f"⚡ Chimera Fury: [{bar}] {enemy.chimera_fury_charge}%  "
                            f"(+{gain} from a full round of combat)"
                        ))
                        if enemy.chimera_fury_charge >= 100 and not enemy.chimera_fury_overloading:
                            enemy.chimera_fury_overloading = True
                            print(wrap(
                                f"\n🔴 THE YOUNG CHIMERA IS OVERLOADING! "
                                f"It has absorbed your power — brace yourself!"
                            ))

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
            log_battle_summary(warrior.name, enemy.display_name, "VICTORY", turn_count)
            # Patronus and Chimera are called from their own fight wrappers —
            # return "win" so the arena loop breaks cleanly
            if enemy.name in ("Patronus", "Young Chimera"):
                return "win"
            # Award gold on safety fallback victory too
            _gold_result = calculate_gold_reward(enemy, turn_count, warrior)
            display_gold_earned(_gold_result)
            award_pending_gold(warrior, _gold_result)
            return True

        # If warrior is also dead, it's a loss
        log(f"  [RESULT] DEFEAT (safety fallback) — {warrior.name} fell to {enemy.display_name}.")
        log_battle_summary(warrior.name, enemy.display_name, "DEFEAT", turn_count)
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
                # Moral choice, weapon, and title all handled inside battle_inner
                # before returning "win" — nothing to do here except break
                break

            # 2) Tournament exit (your code uses this)
            if result == "tournament":
                return

            # 3) Normal death / loss
            if not result or not warrior.is_alive():
                # Track which death type for tailored retry message at the end
                death_type = "fallen"

                # Check for the special "Gooed One" embarrassing death first.
                # If the killer was a regular Green Slime AND the player had
                # healing tools unused, they earn a much more humiliating end.
                if is_gooed_one_death(warrior, enemy):
                    death_type = "gooed"
                    print(wrap(
                        "The Green Slime jiggles triumphantly atop your motionless body.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "In the stands, the crowd boos. A bottle whistles past your corpse. "
                        "Somewhere, a child asks 'Mom, didn't he have potions?' — "
                        "and her mother sighs, because yes. Yes, he did.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "The bookkeeper mutters, 'Refund the bets — this wasn't a fight, "
                        "it was a suicide.' The Green Slime, equally confused, gives you "
                        "a polite nudge as if to ask if you're okay.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "You are not.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "The bards will not sing of this. The history books will skip the page. "
                        "Your name, if ever spoken again, will be followed only by the words: "
                        "'you know — Goo Guy.'",
                        WIDTH
                    ))
                    space()
                    GAME_WARRIOR.fate_titles.add("gooed_one")
                    GAME_WARRIOR.endings.add("gooed_ending")
                    print("🟢 You acquired the Title: The Gooed One")
                else:
                    print(wrap(
                        f"{enemy.name} stands victorious over your fallen body. "
                        "As your vision fades to black, you hear a voice proclaim, "
                        "'You will serve the beast gods for all eternity!'",
                        WIDTH
                    ))
                    space()
                    print("The last thing you hear is the crowd roaring in triumph")
                    GAME_WARRIOR.fate_titles.add("fallen_champion")
                    GAME_WARRIOR.endings.add("fallen_ending")
                    print("You acquired the Title: Fallen Champion")

                # ----- End-of-run wrap-up (single source of truth) -----
                # Inventory / equipment summary, full stats, run score breakdown,
                # then the optional combat log review, then the demo close.
                space()
                show_end_summary(warrior)
                GAME_WARRIOR.show_all_game_stats()
                # v0.6.08: pass outcome to score system for proper multiplier
                # ("gooed" gets ×1.0 + 1 pity bonus; "defeat" gets ×1.0)
                arena_outcome = "gooed" if death_type == "gooed" else "defeat"
                _final_score = show_run_score(warrior, outcome=arena_outcome)

                # Combat log prompt
                while True:
                    view = input("\nWould you like to view your combat log? (y/n): ").strip().lower()
                    if view == "y":
                        view_combat_log()
                        break
                    elif view == "n":
                        break
                    else:
                        print("Incorrect input, please enter y or n.")

                # Leaderboard — show after combat log review
                display_at_end_of_run(warrior, _final_score or 0, outcome=arena_outcome)
                # ----- Thanks for playing + retry encouragement -----
                space()
                print("═" * 50)
                print(wrap(
                    "Thank you for playing the Journey to Winter Haven demo.",
                    WIDTH
                ))
                print("═" * 50)
                space()

                if death_type == "gooed":
                    print(wrap(
                        "Better luck next time, Goo Guy. The arena gates will open again "
                        "when you're ready — and we believe in you. Mostly.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Tip: potions exist for a reason. So does the 'use a potion' menu. "
                        "They're connected.",
                        WIDTH
                    ))
                else:
                    print(wrap(
                        "The Beast Gods have claimed another champion — but every fallen "
                        "warrior teaches the next. The arena remembers your name, even if "
                        "the bards do not.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Will you take up the blade again? Winter Haven still waits beyond "
                        "the mountains.",
                        WIDTH
                    ))

                space()
                print(wrap(
                    "More content coming soon.",
                    WIDTH
                ))
                space()
                prompt_play_again()  # v0.6.14: ask y/n instead of just closing
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


        # Champion title already awarded in the arena loop win block
        # Final endings (Guardian / Dark Champion) are awarded inside
        # chimera_fight() and patronus_fight() respectively

    finally:
        # restore previous settings after arena ends
        warrior.level_cap = old_cap
        warrior._level_cap_notified = old_notified


# ===============================
# Story / Intro
# ===============================
def ashenveil_prologue(warrior):
    """
    New v0.6 prologue — sendoff from Ashenveil before the forest and Bo encounter.
    Called at the start of intro_story_inner before the forest scene.
    Opens with a brief framing scene, then asks for the player's name.
    """
    # --- OPENING FRAMING (only on a fresh run) ---
    # Brief atmospheric setup before the name prompt — gives the player
    # a moment to settle into the world before being asked who they are.
    if GAME_WARRIOR.name == "warrior":
        clear_screen()
        print(wrap(
            "Cold morning light filters through the eastern gate of Ashenveil. "
            "Ash drifts down from Frostveil Peak in the distance — fine grey flakes "
            "carried on the wind from somewhere high on the mountain that has never "
            "fully gone quiet. It settles on your shoulders, on the cobblestones, "
            "on the worn leather of your traveling pack.",
            WIDTH
        ))
        space()
        continue_text()

        print(wrap(
            "You are nineteen. A greenhorn of the Ashen Vanguard, the city's storied adventurer guild. "
            "Today you leave on your first quest — a scouting run through the Ashen Frost Forest "
            "to a place called Winter Haven.",
            WIDTH
        ))
        space()
        continue_text()

        print(wrap(
            "But before any of that — before the road, before the forest, before what waits at "
            "the foot of Frostback Mountain — there is one question still left to answer.",
            WIDTH
        ))
        space()
        continue_text()

        # --- NAME PROMPT ---
        clear_screen()
        GAME_WARRIOR.name = get_name_input()

    clear_screen()
    print(wrap(
        "The Ash Hall of Ashenveil stands at the heart of the city, its stone walls blackened "
        "by decades of torchlight and the slow drift of ash from the forest beyond. "
        "You have spent the last year training inside those walls.",
        WIDTH
    ))
    space()
    print(wrap(
        f"You are {warrior.name}. Greenhorn rank, Ashen Vanguard. "
        "Son of Aldric — A-rank adventurer, senior Vanguard member, and the man "
        "whose name people say when they want to explain what a real warrior looks like.",
        WIDTH
    ))
    space()
    print(wrap(
        "Today is your first quest.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ALDRIC'S SENDOFF ---
    print(wrap(
        "Aldric finds you at the gate, arms crossed, looking you over the way he always does "
        "— checking for the small things. Buckles that catch light. A pack strap that might rattle. "
        "Anything that announces you before you announce yourself.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"Winter Haven.\" He hands you the quest parchment without ceremony. "
        "\"Confirm the dungeon entrance exists. Watch what comes in and out for a day or two. "
        "Take notes. Then get back here.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "He fixes you with a hard look. "
        "Something flickers behind his eyes — there and gone before you can name it. "
        "The road to Winter Haven has been quiet lately. Too quiet, some of the returning "
        "merchants have said. He hasn't mentioned it to you.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"Eyes only. You don't go inside. You don't pick a fight. You don't try to be a hero. "
        "Rumors have been floating around the hall for years — someone needs to actually go look. "
        "Should be simple enough even for a greenhorn.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "He clasps you on the shoulder and holds it a moment longer than necessary.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()
    print(wrap(
        "\"Come back and make your old man proud.\" A rare hint of a smile crosses his face. "
        "\"I know you've been eyeing that girl in the market district. "
        "Make a little gold on this run and maybe you can actually talk to her.\"",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Before you can respond he is already walking back toward the Ash Hall.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ELWYN'S SENDOFF ---
    print(wrap(
        "Elwyn is waiting for you just past the gate. She presses a small flask into your hand.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"I made it myself,\" she says quietly. "
        "\"Your father never took one when he left for his first quest. "
        "You're smarter than he was.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "You turn the flask over in your hands. It smells like pine and frost — "
        "like the forest on a cold morning. Like home.",
        WIDTH
    ))
    space()
    print(wrap(
        "She wraps you in a warm hug, kisses you on the cheek, and then says quietly, "
        "\"Stay out of trouble. And don't dawdle.\"",
        WIDTH
    ))
    space()

    # Grant Frostpine Tonic — replaces the starting heal potion.
    # The narrative justification: Elwyn presses this into your hand
    # *instead of* whatever basic heal flask you'd have packed yourself.
    # This is intentional design — keeps starting inventory at one consumable.
    warrior.potions["heal"] = 0
    warrior.potions["frostpine_tonic"] = 1
    print(wrap(
        "✨ Elwyn's Frostpine Tonic added to your inventory. "
        "(Restores 40% HP, clears all status effects, and restores 2 AP. One use only.)",
        WIDTH
    ))
    print(wrap(
        "(It replaces the basic heal flask you'd packed for the trip.)",
        WIDTH
    ))
    space()

    # Grant Walking Staff — the traveler's weapon carried the whole road.
    # Weaker than any arena drop (no procs, no element) but keeps early fights
    # from being a slog against high-defence enemies before a weapon drops.
    # v0.6.18: marked two-handed — a staff is canonically a two-hander, and
    # without this flag the player could equip a sword + staff for stat
    # stacking (bug surfaced when a tester equipped both).
    walking_staff = Equipment(
        name       = "Walking Staff",
        slot       = "weapon",
        rarity     = "starter",
        atk_min    = 0,
        atk_max    = 1,
        defence    = 1,
        two_handed = True,
    )
    equip_item(warrior, walking_staff)
    print(wrap(
        "\U0001fab5 You've had your walking staff the whole journey. "
        "It's not a weapon — but it'll do until something better turns up.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ASHEN FROST FOREST ---
    print(wrap(
        "The road out of Ashenveil cuts through the Ashen Frost Forest — "
        "tall ash trees with pale grey bark rising on either side, frost crunching "
        "under your boots even in the early afternoon. The locals call it Ashen Frost "
        "for a reason. It never fully warms up in here.",
        WIDTH
    ))
    space()
    print(wrap(
        "You have traveled this stretch of road before, but never alone. "
        "Never with a guild parchment in your pack.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "The first night you make camp off the road, sheltered behind a fallen ash trunk. "
        "Cold rations — hard bread, dried meat, a strip of cured fruit. You eat without "
        "tasting it. You sleep with one hand on your walking staff and one ear on the wind.",
        WIDTH
    ))
    space()
    print(wrap(
        "The forest is quiet. Not peaceful quiet — something else. "
        "No owl calls. No rustle of small things in the undergrowth. "
        "Just the creak of frost-heavy branches and your own breathing. "
        "You tell yourself it's the cold keeping the animals down. "
        "You almost believe it.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Day two. The forest deepens. The road narrows. "
        "Something moves in the trees to your left. You stop. Silence. "
        "Then nothing — just the wind pulling frost off the branches.",
        WIDTH
    ))
    space()
    print(wrap(
        "You keep walking. The forest has always felt like it was watching. "
        "Today it feels like it is waiting.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Day three. You haven't seen another traveler since you left Ashenveil. "
        "Not a merchant cart. Not a hunter. Not even a pilgrim taking the long road. "
        "The Ashen Frost is a known route — people use it. "
        "People should be using it.",
        WIDTH
    ))
    space()
    print(wrap(
        "The quiet that felt like nothing on the first night feels like something now. "
        "A slow dread settles into your chest that you can't quite name. "
        "You find yourself glancing back down the road more than you glance forward. "
        "The trees stand perfectly still. The sky is the colour of old ash. "
        "It is too quiet. It has been too quiet since you left.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "By the fourth day the fear has worn down into something worse — loneliness. "
        "A deep, hollow ache you weren't expecting. "
        "You catch yourself wanting to talk to someone. Anyone. "
        "You'd give up your boots for a hot meal and your rations for ten minutes of "
        "conversation with a stranger heading the other way.",
        WIDTH
    ))
    space()
    print(wrap(
        "You think about the market district back in Ashenveil. The noise of it. "
        "The smell of bread and tallow and too many people in one place. "
        "You never thought you'd miss that.",
        WIDTH
    ))
    space()
    print(wrap(
        "Something is wrong with the world. You can't say what. "
        "You don't have the words for it yet. "
        "But the road feels emptier than it should, the forest feels older than it should, "
        "and somewhere deep in your bones there is a pull — like the air itself is "
        "holding its breath before something breaks.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "By the time the trees thin the lights of Winter Haven are visible at the base "
        "of Frostback Mountain — still hours away, but there. You stop walking and just "
        "look at them for a moment. Somewhere down there people are talking. Laughing. "
        "Arguing over the price of something. Living their ordinary lives without a second "
        "thought. The thought of it almost makes you want to run.",
        WIDTH
    ))
    space()
    print(wrap(
        "You can hear it faintly on the wind. The distant hum of a city at night — "
        "a cart somewhere, voices carried up the road, the muffled sound of an inn "
        "that hasn't closed yet. You hadn't realised how much you missed the sound "
        "of other people until just now.",
        WIDTH
    ))
    space()
    print(wrap(
        "You make camp a few hours outside the city. Too tired to push through tonight, "
        "too relieved to care. The lights are still there when you close your eyes.",
        WIDTH
    ))
    space()
    print(wrap(
        "They are still there when you open them.",
        WIDTH
    ))
    space()
    print(wrap(
        "You sit up. The fire is cold ash. The sky is wrong — deep amber, the sun "
        "already dragging itself toward the horizon. You slept through the entire day. "
        "Not a few hours. The whole day.",
        WIDTH
    ))
    space()
    print(wrap(
        "For a moment something prickles at the back of your neck. A wrongness you "
        "can't quite name. Then your stomach growls, your legs ache, and your head is "
        "thick with the fog of too-deep sleep. You rub your face and reach for your pack.",
        WIDTH
    ))
    space()
    print(wrap(
        "You must have been more tired than you thought. Four days alone on a silent "
        "road — of course you crashed. That's all it was.",
        WIDTH
    ))
    space()
    print(wrap(
        "You never make it to the dungeon entrance.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()


def intro_story_inner(warrior):
    """Long-form intro story leading into the arena_battle(warrior)."""

    # v0.6 — Ashenveil prologue: Aldric & Elwyn sendoff, Frostpine Tonic, forest travel
    ashenveil_prologue(warrior)

    clear_screen()
    print(wrap(
        "You find yourself stumbling through the last stretch of Ashen Frost Forest "
        "as the last light bleeds out of the sky. Winter Haven's lights glow ahead — "
        "the same lights you fell asleep looking at. Your torch flickers against the "
        "dark closing in around you.",
        WIDTH
    ))

    space()
    print(wrap(
        "Almost there. Hungry, stiff, but almost there.",
        WIDTH
    ))
    space()
    winter_heaven_info = check(
        "Would you like more information about Winter Haven? (y/n)\n> ",
        ["y", "n"]
    )

    

    # ============================================================
    # BRANCH: LEARN ABOUT WINTER HAVEN
    # ============================================================
    if winter_heaven_info == "y":
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
        if GAME_WARRIOR.name == "warrior":
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
            print(wrap("'Here is something to help you out.' Bo hands you a healing potion." \
            " Your hands are tied and Bo escorts you to a nearby monster stronghold. " \
            "A grizzled bear folk meets you at the gates. 'This is Nob, our current Arena Trainer. He will be taking care of you.' Bo gestures.", WIDTH))
            GAME_WARRIOR.potions["heal"] += 1

            tournament_knowledge = check(
                "\nWould you like to learn about the tournament? (y/n)\n> ",
                ["y", "n"]
            )
            clear_screen()

           
                

            # Learn about tournament
            if tournament_knowledge == "y":
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
                    "\nDo you inquire further? (y/n)\n> ",
                    ["y", "n"]
                )

                
                if tournament_inquiry == "y":
                    
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

            if tournament_knowledge == "n":
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
    if winter_heaven_info == "n":
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
        print(wrap("You have been traveling through the Ashen Frost Forest for the last few days, surviving off traveler's rations, and sleeping on the cold ground", WIDTH))

       
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
                if GAME_WARRIOR.name == "warrior":
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
                        "\nWould you like to learn more about the tournament? (y/n)\n> ",
                        ["y", "n"]
                    )

                   
                    if tournament_info == "y":
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
                        continue_text()
                        clear_screen()
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

                    space()
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
                "\nDo you accept the help? (y/n)\n> ",
                ["y", "n"]
            )
            clear_screen()
            if accept_help == "y":
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

            if accept_help == "n":
                print(wrap("You decline the help and the creature says 'Very well. The river banks "
                " remain pretty steep for a while, and there are some serious rapids "
                "farther downstream. Good luck finding your way out, it being dark and all'."))

                continue_text()
                clear_screen()
                accept_help_2 = check(
                    "\nDo you reconsider and accept the help? (y/n)\n> ",
                    ["y", "n"]
                )
                if accept_help_2 == "y":
                    print(wrap("You reluctantly accept help. The creature introduces himself as Boar, Bo for short. " 
                    "What is your name?"))
                    if GAME_WARRIOR.name == "warrior":
                        GAME_WARRIOR.name = get_name_input()
                    print(wrap("I respect your courage, adventurer, so I am going to give you a little something special. " 
                    "Boar hands you a potion of AP."))
                    GAME_WARRIOR.potions["ap"] += 1
                    print(wrap("The creature's eyes intensify. 'You're going to need it for the tournament.'"))
                if accept_help_2 == "n":
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
                    " my help? (y/n)\n> ",
                    ["y", "n"]
                    )
                    if accept_help_final == "y":
                        print(wrap("I can see you are very brave. I will rescue you if you agree to fight in my tournament"))
                        accept_tournament = check("Do you accept? (y/n)\n> ",
                        ["y", "n"]
                        )
                        if accept_tournament == "y":
                            print(wrap("Bo reaches down and effortlessly pulls you out of the frigid river. What is your name, adventurer?"))
                            if GAME_WARRIOR.name == "warrior":
                                GAME_WARRIOR.name = get_name_input()
                            print(wrap(f"I respect your stubbornness, {GAME_WARRIOR.name}. Let me give you a fighting chance in our tournament. Bo hands you two potions — one for healing and one for AP."))
                            GAME_WARRIOR.potions["heal"] += 1
                            GAME_WARRIOR.potions["ap"] += 1

                            space()
                            continue_text()
                            clear_screen()

                            # --- Bo escorts the stubborn river survivor to Under-Haven ---
                            print(wrap(
                                "Bo walks beside you as you make your way through the forest. "
                                "Soaked, shivering, and barely standing, you stumble along. "
                                "Bo doesn't bind your hands — he's already decided you won't run.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "As the moon begins to set you reach the monster stronghold of Under-Haven. "
                                "A cantankerous old beast man named Nob meets you at the gates. "
                                "Bo introduces Nob as the arena trainer. "
                                "Nob looks you up and down, water still dripping from your clothes. "
                                "'Half-drowned. Wonderful. Fine.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "You are escorted into a holding cell and allowed to rest. "
                                "A few hours later Nob shows up in your cell and yells at you to get up and train.",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Path-specific Nob training: BALANCE (you fell in the river)
                            print(wrap(
                                "Nob marches you out to a stone yard ringed with weathered wooden posts. "
                                "'You fell in a river,' he says flatly. 'That tells me everything I need "
                                "to know about your footing. We're going to fix that, or you're going to "
                                "die in there. Up.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He has you stand on a single foot until your standing leg burns. "
                                "Then the other foot. Then a narrow beam set between two of the posts — "
                                "walk it, turn at the end, walk it back, do not fall. "
                                "You fall. Nob makes you climb back up without a word.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Your centre of gravity is where your enemy puts it,' he barks. "
                                "'Until you take it back.' He shoves you off the beam mid-step to prove it. "
                                "You hit the dirt. You climb back up. You do it again. And again.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "By the time he lets you stop, your legs are shaking and the sky is paling. "
                                "Your clothes are finally dry. 'Better,' Nob grunts. 'Not good. Better. "
                                "Back to your cell. The crowd will be here soon.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Bo returns to escort — personal interest in the stubborn one
                            print(wrap(
                                "You sit on the cot in your cell, legs trembling, listening to the slow "
                                "rise of voices somewhere above. A crowd gathering. The sound of it "
                                "settles into your chest the way cold water did, hours ago.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Footsteps in the corridor. Not orc-guard footsteps — heavier, calmer. "
                                "Bo appears at the bars, looks you over once, and unlocks the cell himself.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                f"'On your feet, {GAME_WARRIOR.name}. I picked you out of that river. "
                                "I'd like to walk you in myself.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo leads you down the coarse stone hallway toward the sounds of a roaring crowd. "
                                "He doesn't say anything else. He doesn't have to.",
                                WIDTH
                            ))

                        if accept_tournament == "n":
                            # --- Player refuses the tournament. Bo overrides with holding magic. ---
                            clear_screen()
                            print(wrap(
                                "'Well, that's unfortunate. That really wasn't a question, adventurer.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo mumbles something low under his breath — a sound that feels older than "
                                "language, the kind of noise that lives in an animal's chest before it lives "
                                "in any word. Your body starts to tingle. Then your muscles stop answering.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Can't have you freezing to death either.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Fire surrounds your body. You panic — but the fire is warm, not hot. "
                                "It dries you quickly and is gone before you've fully understood what happened.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Off to the tournament then. I still think you have a fair shot.'",
                                WIDTH
                            ))
                            space()
                            print(wrap("What is your name, adventurer?", WIDTH))
                            if GAME_WARRIOR.name == "warrior":
                                GAME_WARRIOR.name = get_name_input()
                            space()
                            print(wrap(
                                f"'Speaking of the tournament, {GAME_WARRIOR.name} — would you like to "
                                "learn about it?'",
                                WIDTH
                            ))
                            learn_tournament = check(
                                "(y/n)\n> ",
                                ["y", "n"]
                            )
                            clear_screen()
                            if learn_tournament == "y":
                                print(wrap(
                                    "Bo lifts you onto his shoulder with insulting ease and begins to walk. "
                                    "The forest passes sideways in your vision. As he walks, he talks.",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'It's a monster tournament. We need fighters — humans, mostly. "
                                    "The crowd likes humans. You'll fight what we put in front of you, "
                                    "and if you win, you fight again. If you lose, well. You won't have "
                                    "to worry about a third fight.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'There's a trainer at the stronghold — Nob. Cranky old beast. "
                                    "He'll work you over before the crowd does. Don't take it personal. "
                                    "It's his job to find out what's wrong with you before the arena does.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'I think you have a fair shot. I really do. You fought the river "
                                    "longer than most. That counts for something where we're going.'",
                                    WIDTH
                                ))
                            if learn_tournament == "n":
                                print(wrap(
                                    "Bo huffs. 'Suit yourself. It's easier when they don't know what's "
                                    "coming, anyway.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "He lifts you onto his shoulder and begins to walk. The forest "
                                    "passes sideways in your vision. Bo says nothing else for a long time.",
                                    WIDTH
                                ))
                            space()
                            continue_text()
                            clear_screen()

                            # Arrival at Under-Haven. Hold breaks. Brief Nob intro.
                            print(wrap(
                                "Some long time later the world tilts. Stone floor. Cell bars. The smell "
                                "of straw and old sweat. Bo lowers you onto a rough cot with surprising "
                                "care and crouches to look you in the eye.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Hold breaks in a few minutes. By then Nob will be here. He's going to "
                                "be unkind. That's just how he is.'",
                                WIDTH
                            ))
                            space()
                            # Bo's wordless gesture of respect — the stubborn one's reward
                            print(wrap(
                                "Bo pauses. Reaches into a pouch at his hip and sets something small on the "
                                "cot beside you — a vial that glows faintly blue in the cell's dim light. "
                                "He doesn't say anything about it. He doesn't have to.",
                                WIDTH
                            ))
                            GAME_WARRIOR.potions["super_ap"] += 1
                            print("🏅 You received: Super AP Potion (50% AP restore)")
                            space()
                            print(wrap(
                                "Bo stands. The cell door closes. His footsteps recede down the corridor. "
                                "You lie on the cot, fully aware, completely still, and wait for your body "
                                "to remember it belongs to you.",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Tingling returns. Nob arrives.
                            print(wrap(
                                "Feeling returns to your fingers first, then your arms, then your legs — "
                                "a slow pins-and-needles thaw. You sit up just as a cantankerous old beast "
                                "man named Nob appears at the bars.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'You're the one Bo had to carry in.' Nob looks you up and down. "
                                "'Wonderful. Fine. On your feet. We have work to do.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Path-specific Nob training: BALANCE (you fell in the river)
                            print(wrap(
                                "Nob marches you out to a stone yard ringed with weathered wooden posts. "
                                "'You fell in a river,' he says flatly. 'That tells me everything I need "
                                "to know about your footing. We're going to fix that, or you're going to "
                                "die in there. Up.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He has you stand on a single foot until your standing leg burns. "
                                "Then the other foot. Then a narrow beam set between two of the posts — "
                                "walk it, turn at the end, walk it back, do not fall. "
                                "You fall. Nob makes you climb back up without a word.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Your centre of gravity is where your enemy puts it,' he barks. "
                                "'Until you take it back.' He shoves you off the beam mid-step to prove it. "
                                "You hit the dirt. You climb back up. You do it again. And again.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "By the time he lets you stop, your legs are shaking and the sky is paling. "
                                "'Better,' Nob grunts. 'Not good. Better. Back to your cell. The crowd will "
                                "be here soon.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Bo returns to escort — personal interest in the stubborn one
                            print(wrap(
                                "You sit on the cot in your cell, legs trembling, listening to the slow "
                                "rise of voices somewhere above. A crowd gathering. The sound of it "
                                "settles into your chest the way cold water did, hours ago.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Footsteps in the corridor. Not orc-guard footsteps — heavier, calmer. "
                                "Bo appears at the bars, looks you over once, and unlocks the cell himself.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                f"'On your feet, {GAME_WARRIOR.name}. I picked you out of that river. "
                                "I'd like to walk you in myself.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo leads you down the coarse stone hallway toward the sounds of a roaring crowd. "
                                "He doesn't say anything else. He doesn't have to.",
                                WIDTH
                            ))

                    if accept_help_final == "n":
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
                            GAME_WARRIOR.fate_titles.add("flayed_one")
                            GAME_WARRIOR.endings.add("flayed_ending")
                            # v0.6.11: route through normal end-of-run flow
                            # (was sys.exit(0) — player never saw score/leaderboard)
                            show_end_summary(GAME_WARRIOR)
                            _final_score = show_run_score(GAME_WARRIOR, outcome="flayed_one")
                            view_combat_log()
                            display_at_end_of_run(GAME_WARRIOR, _final_score or 0, outcome="flayed_one")
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
                                GAME_WARRIOR.max_hp += 1  # River Warrior: +1 max HP
                                award_title(GAME_WARRIOR, "river_warrior")
                                print(f"✨ +1 Permanent Max HP! (now {GAME_WARRIOR.max_hp})")
                                print("🏅 New Ability Learned: River Spirit! (0 AP to activate — revives at 1 HP)")

                                continue_text()
                                clear_screen()

                                space()       

                                
                                if GAME_WARRIOR.name == "warrior":
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
                                GAME_WARRIOR.fate_titles.add("drowned_one")
                                GAME_WARRIOR.endings.add("Broken_one")
                                # v0.6.11: route through normal end-of-run flow
                                # (was sys.exit(0) — player never saw score/leaderboard)
                                show_end_summary(GAME_WARRIOR)
                                _final_score = show_run_score(GAME_WARRIOR, outcome="drowned_one")
                                view_combat_log()
                                display_at_end_of_run(GAME_WARRIOR, _final_score or 0, outcome="drowned_one")
                                input("\nPress enter to end the game.")
                                sys.exit(0)

                                
                                               


            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return



def prompt_play_again():
    """
    Final post-run prompt shown at every demo endpoint (victory OR defeat).
    Asks the player if they want to play again.

    On 'y' we raise PlayAgainException, which bubbles up to __main__. The
    main loop catches it, resets all global state (warrior, combat log,
    run stats), and starts a fresh run. This works in every environment —
    terminal, PyInstaller exe, Replit, anywhere.

    Previous implementation used os.execv to re-exec the script. That works
    on a local terminal but silently fails on PyInstaller exes (the frozen
    binary doesn't always re-exec cleanly) and on Replit (the platform
    catches the syscall). The exception approach removes the dependency on
    the host environment supporting process replacement.
    """
    space()
    while True:
        choice = input("Play again? (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            print("\n🔄 Restarting...\n")
            raise PlayAgainException
        elif choice in ("n", "no"):
            print("\nThanks for playing. Until next time, warrior. ⚔️\n")
            sys.exit(0)
        else:
            print("Please enter y or n.")


def main_menu():
    """
    Simple main menu shown on game launch. Loops until the player picks
    'New Game' or 'Quit'. The leaderboard option returns here so they
    can browse and then decide whether to start a run.
    """
    while True:
        clear_screen()
        print()
        print("═" * 50)
        print("        JOURNEY TO WINTER HAVEN")
        print("═" * 50)
        print()
        print("   [1] New Game")
        print("   [2] View Leaderboard")
        print("   [3] Quit")
        print()
        choice = input("   Select an option: ").strip()

        if choice == "1":
            return  # caller proceeds to launch the game
        elif choice == "2":
            show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD")
            input("\nPress Enter to return to the main menu...")
        elif choice == "3":
            print()
            print("   Until next time, warrior. ⚔️")
            print()
            sys.exit(0)
        else:
            print("   Please enter 1, 2, or 3.")
            input("   Press Enter to try again...")


if __name__ == "__main__":
    # Outer loop wraps the entire game so "play again" can fully restart
    # without relying on os.execv (which fails silently in some environments).
    # Each iteration represents one full playthrough from main menu to ending.
    while True:
        try:
            main_menu()
            GAME_WARRIOR = Warrior()
            COMBAT_LOG.clear()
            reset_run_stats()
            intro_story(GAME_WARRIOR)
            # If the run completes without raising PlayAgainException, the
            # endpoint already called sys.exit(0). Break defensively just in
            # case any endpoint returns normally.
            break
        except PlayAgainException:
            # Player chose "play again" at an end-of-run prompt. Loop back
            # to the top — global state will be re-initialised by the
            # statements at the head of the loop.
            continue
    

_PATCH_NOTES = r"""
# ✅ Dungeon Adventure – Version History Summary

# ============================================================
# PATCH NOTES — JOURNEY TO WINTER HAVEN
# ============================================================
#
#  ▸ v5.xx  — Current major version (arena + systems overhaul)
#  ▸ v4.xx  — Feature build era (loot, skills, monsters)
#  ▸ v0.xx  — Early versions (pre-rename, raw prototype era)
#  ▸ Proto  — Pre-version files (August–October 2025)
#
# ============================================================


# ────────────────────────────────────────────────────────────
#  v5  SERIES  —  Arena & Systems Overhaul
# ────────────────────────────────────────────────────────────

⚙️  v0.6.21  |  Journey_To_Winter_Haven_v_06_21.py  (Bug Fix Pass — Dev Shortcut Safety, Equipment Display, Score Flags, Primordial Surge Exploit)

# Five HIGH-severity fixes from the pre-push audit. No new features.

# === FIX 1: Monster-select dev shortcut moved behind '!' prefix ===
* BUG: The global input() override triggered a debug monster battle on bare 'm' or 'monster' at ANY of the ~200 input() prompts (yes/no confirms, Press-Enter pauses, merchant equip prompts). A fat-finger could yank the player into a debug fight mid-session. The v0.6.19 patch added '!' protection to every OTHER dev shortcut but missed this one.
* FIX: input() now recognizes '!m' / '!monster' (case-insensitive) and emits the existing __MONSTER_SELECT__ sentinel instead of calling battle() directly. handle_monster_select_shortcut() then decides combat-aware behaviour (swap enemy mid-fight vs. start a debug fight out of combat). Bare 'm' / 'monster' / player names now pass through as ordinary text.
* WHY SENTINEL NOT BATTLE(): the old code called battle(GAME_WARRIOR, ...) from inside input(), which has no idea whether it's mid-combat — wrong warrior reference and wrong flow in a fight. The sentinel path was already correct; we just route through it.
* DOCS: continue_text / check / _try_dev_shortcut docstrings updated to reflect the '!' convention (they still claimed bare 'q'/'c'/'monster' worked).

# === FIX 2: Equipment lists used stale slot keys (4 locations) ===
* BUG: Four display loops iterated ("weapon", "armor", "accessory", "trinket", "finger_1", "finger_2") — but v0.6.16 renamed the equipment dict to main_hand / off_hand / armor / helm / cape / accessory / trinket / finger_1 / finger_2. Weapons, shields, helms, and capes have been INVISIBLE in every equipment display since v0.6.16.
* PLAYER IMPACT: worst at show_end_summary (the win/loss screen every player sees) — your weapon never appeared. Also show_game_stats (combat HUD gear line) and show_combat_stats (detailed stats). Fourth was the debug-menu unequip tool (dev-only).
* FIX: all four now iterate the correct 9 slot keys with Main Hand / Off Hand / Helm / Cape labels. The debug unequip slot_map is now generated from the slot list (str(i): slot) so it can't drift again.
* SYNERGY: pairs with the v0.6.20 dual-wield + set-bonus blocks — between them, every equipped item is now visible from multiple angles.

# === FIX 3: Berserk / Death Defier score bonuses double-counted across fights ===
* BUG: record_fight_score read warrior.berserk_used (+20) and warrior.death_defier_used (+50). But those flags have run-wide semantics: berserk_used gates the natural <=20% HP re-trigger (stays True until HP recovers above 20%), and death_defier_used is only reset at the full-rest interlude. So once either fired, EVERY subsequent fight that round silently collected the bonus for doing nothing — score inflation.
* FIX: added dedicated per-fight flags berserk_used_this_fight / death_defier_used_this_fight. Set True alongside the run-wide flags at every trigger site (natural berserk, Trinket of Berserk, Death Defier revival). Reset False at battle_inner start (next to bonus_action_used). record_fight_score now reads the per-fight flags (with a defensive fallback to the old flags if the new ones are somehow missing). Initialized on Warrior creation so the first fight and first score read never hit a missing attr.
* NOTE: the run-wide flags keep their original gating behaviour untouched — only the SCORE read changed.

# === FIX 4: Primordial Surge stat restore over-credited (permanent stat exploit) ===
* BUG: Primordial Surge degrades ATK/DEF/max-HP by 10%, tracks the loss, and restores it after combat. But the subtract was floored (max(1,...)/max(0,...)) while the RECORDED loss was the intended (pre-floor) amount. When a stat was low enough to clamp at the floor, the post-combat restore added back MORE than was taken — a permanent stat GAIN from being hit. Reproduced: min_atk 2 → 4 after 3 surges + restore. Drifts low-ATK/low-DEF builds upward over a long Chimera fight.
* FIX: capture the ACTUAL before/after delta and record that, so the round-trip nets to zero. min and max ATK are now tracked SEPARATELY (primordial_atk_loss = min, primordial_max_atk_loss = max) because they floor against different bounds (min floors at 1, max floors at the new min) — a single shared tracker couldn't restore both faithfully. _restore_primordial_stats updated to match.
* VERIFIED: degrade+restore nets to (0,0,0,0) across low-stat, typical-L5, and extreme-floor cases.
* TYPICAL PLAY: a normal L5 warrior (min_atk ~14, atk_loss ~2) never hit the floor, so most runs never saw the drift — but it's a real correctness bug regardless.

# === FIX 5: Debug menu option 11 crashed with TypeError ===
* BUG: the "Trigger Death Defier (test)" debug option called try_death_defier(warrior, source="debug"). Neither try_death_defier version accepts 'source' (they take 'reason') — raised TypeError, crashing the debug test instead of exercising the hook.
* FIX: source="debug" → reason="debug". One-word change. Dev-only.

# === NOTED, STILL DEFERRED (from the audit, not fixed in v0.6.21) ===
* MEDIUM: off-hand weapon procs/sockets don't fire when dual-wielding (get_weapon() returns main-hand only). Needs a design decision (one swing blended vs. two swings) before touching — left for a dedicated pass.
* MEDIUM: triplicate dead-code class definitions (Equipment, Creator, Monster) in the main file shadow the shared.py imports. No live bug (all instances use the shared versions) but a refactor hazard. Safe to delete in a cleanup pass.
* MEDIUM: two divergent try_death_defier definitions (shared 2-param vs. main 3-param). The main version wins everywhere it matters; the shared one is effectively unused. Consolidate later.
* LOW: leaderboard save is non-atomic (write-in-place); chinker/death_delver dead TITLE_BUFFS entries; player DoT fade messages are third-person; a few stale docstrings.
* DESIGN FLAG: Chimera passive heal (10% max HP every turn, unconditional) can soft-lock under-DPS players. Balance review, not a code bug.


⚙️  v0.6.20  |  Journey_To_Winter_Haven_v_06_20.py  (Stats Visibility — Interlude Pause, Set Bonus Tracker, Dual-Wield Breakdown, Armor Socket UI Scaffolding)

# === INTERLUDE STATS PAUSE BUG ===
* BUG FIX: arena_quarters_interlude options 9 ("Check your status") and 11 ("View all game stats") had no Press-Enter pause. Output flashed and vanished on the next loop iteration because the loop top calls clear_screen() unconditionally. Stats display worked correctly — player just couldn't read it.
* FIX: Both options now call _real_input("Press Enter to return to the menu...") after the stats print, matching the pattern already used by option 14 (Waterlogged Stone).
* PATTERN: Used _real_input (the saved-off bypass of the dev-shortcut wrapper) so debug shortcuts can't trigger from the pause prompt and skip the menu reset.

# === SET BONUS TRACKER (visibility, no mechanical change) ===
* NEW: Wolf-Hide and Dire Wolf set status now shows in both show_combat_stats (mid-fight) and show_all_game_stats (full stats screen). Surfaces piece count (1/4, 2/4, 3/4, 4/4), currently-active bonuses, and a next-threshold preview line.
* RATIONALE: Set bonuses were correctly applied at equip time by apply_all_set_bonuses, but the only place piece counts were visible was inside the crafter scene. Player at 3/4 pieces had no way to see that +5 HP and +1 AP were active, or that 4pc would unlock +2 DEF/ATK + Pack Hunter.
* HELPER: New module-level _format_set_bonus_lines(hero) returns a list of strings; empty list when no set pieces are equipped (so the section is skipped entirely on bare builds). Mirrors the bonus tables in apply_wolf_set_bonus and apply_dire_wolf_set_bonus — must be kept in sync if those bonuses change.
* DISPLAY: 3pc Wolf-Hide example:
    🐺 Wolf-Hide: 3/4 pieces
       • +5 max HP
       • +1 max AP
       (4pc unlocks +2 DEF/ATK + Pack Hunter)

# === DUAL-WIELD ATK BREAKDOWN (visibility, no mechanical change) ===
* NEW: Dual-wield breakdown shows in both stats screens. Surfaces main-hand full contribution, off-hand halved contribution (with the math: e.g. "3-6 → 1-3 ATK, halved"), and Dual Wielder title bonus when held.
* RATIONALE: The blended ATK range made it impossible to tell what the off-hand was actually contributing. Player at "ATK 8-19" with sword + dagger had no way to verify that "off-hand halved" was happening — it just looked like a big number.
* HELPER: New module-level _format_dual_wield_lines(hero) returns a list of strings; empty list when not dual-wielding (single weapon, weapon+shield, or no weapons). The math (floor(off_atk/2)) mirrors apply_dual_wield_modifier exactly — kept in sync if the halving formula ever changes (e.g. the future Dual Wielder skill that grants full off-hand damage).
* DISPLAY: Sword(5-10) + Dagger(3-6) with title held:
    ⚔️  Dual Wielding:
       Main: Iron Sword (5-10 ATK, full)
       Off:  Bone Dagger (3-6 → 1-3 ATK, halved)
       Dual Wielder title: +1/+1 ATK passive

# === NOTED BUT NOT FIXED ===
* show_combat_stats and show_all_game_stats equipment-list loops still iterate ("weapon", "armor", ...) instead of ("main_hand", "off_hand", "armor", "helm", "cape", ...). Since v0.6.16 changed the equipment dict to main_hand/off_hand, weapons and shields no longer appear in the equipment list. The new set-bonus and dual-wield blocks surface this info from a different angle, so the gap is no longer total — but the equipment-list loop is still wrong and should be fixed in a separate pass.

# === ARMOR SOCKET UI SCAFFOLDING (Phase 2 preview, no mechanics) ===
* NEW: Crafter socketing menu now has a "What to socket?" front-menu instead of dropping straight into the weapon picker. Options: 1) Weapon, 2) Armor (💤 coming soon), 0) Back.
* NEW: Armor branch lists the player's socketable armor pieces (equipped + bag) with current socket counts so they can preview what Phase 2 will activate. Filtered to slot=="armor" only — helms and capes aren't socketable in the Phase 2 design (chest armor only).
* RATIONALE: Player asked about armor sockets that were discussed in v0.6.16 but deferred. Real implementation (Tusk = retaliation bleed, Soul Amulet = damage absorb + heal) needs combat hooks on the player's apply_defence path — meaningful new system. UI scaffolding is cheap and tells the player "this is a planned thing" without committing to mechanics.
* CRAFTER FLAVOR LINE: "Armor sockets — aye, the thought's there. Got the holes punched, but the runes to make them sing? Not yet. Come back later."
* RENAME: Old _socket_loop (the weapon-picker) is now _weapon_socket_loop. New _socket_loop is the front-menu. _armor_socket_preview is the new coming-soon screen.
* SOCKET COUNTS UNCHANGED: _SOCKET_COUNTS_ARMOR stays at Normal 1, Uncommon 1, Rare/Epic/Legendary/Mythril 2. Armor items have been spawning with empty socket lists since v0.6.16 — inert until combat hooks land in Phase 2.
* DESIGN NOTES: A new "PHASE 2 DESIGN NOTES" block in crafter.py documents the planned items (Tusk, Soul Amulet), starting damage values, and the open design questions (Tusk retaliation attribution, Soul Amulet + Pack Hunter interaction, future resistance system). Resolve these before Phase 2 implementation.


⚙️  v0.6.15  |  Journey_To_Winter_Haven_v_06_15.py  (Score Bug Fix, Blind Unification, Tier-3 Rebalance, QoL)

# === SCORE BUG — leaderboard was saving 0 ===
* BUG FIX: combat_log.show_run_score() (the wrapper imported by the main file) was calling score.show_run_score() and then `return`ing with no value. The actual final_score (correctly computed AND printed on-screen) got dropped on the floor. Callers received None, `_final_score or 0` collapsed to 0, and the leaderboard saved every defeat as score=0.
* FIX: One-line change — `_score_show(...); return` → `return _score_show(...)`. Existing zero-score entries (Umbra L3, beast L5) stay as-is in scores.json; future defeats save correctly.
* DETECTION: User reported leaderboard showed level, outcome, date but always score=0. Initial suspicion was OUTCOME_MULTIPLIERS but defeat already had 1.0. Traced to wrapper return path via grep on import chain.

# === BLIND UNIFICATION ===
* BUG FIX: player_basic_attack() never applied the blind damage multiplier. Power Strike applied 0.5/0.75 inline. blind_damage_multiplier() helper returned 0.5/0.25/full — yet a third table. Three different blind systems in flight.
* UNIFIED: blind_damage_multiplier(hero) is now the single source of truth: blind_turns=3 → 0.0 (skip turn, handled in turn loop), blind_turns=2 → 0.5, blind_turns<=1 → 1.0. Both Power Strike AND basic attack call the helper now.
* USER-REPORTED: Goblin dust hit, player skipped turn (correct), but next turn basic attack landed for 7 damage on a 2-6 ATK + walking stick build (max roll at full power — should have been 50%).

# === TIER 3 + FALLEN REBALANCE ===
* DEFENCE rebalanced — tier 3 monsters had >= Fallen Warrior DEF, which is wrong for a prologue boss:
  - Goblin Warrior: 6 → 5 DEF
  - Drowned One:    5 → 4 DEF
  - Hydra Hatchling: 5 → 4 DEF
  - Flayed One:     4 → 3 DEF
  - Fallen Warrior: 5 → 6 DEF (boss now leads)
* ATTACK rebalanced — Goblin Warrior and Drowned One outhit Fallen:
  - Goblin Warrior: 7-11 → 6-10 ATK
  - Drowned One:    7-10 → 6-9 ATK
  - Fallen Warrior: 6-10 → 7-11 ATK
* HP bump — Fallen Warrior 60 → 65 HP (boss durability)
* RESULT: Fallen leads every category at base level. Hardened tier-3 variants can match or barely exceed in one category but never sweep all three.

# === INTERLUDE POTION ACCESS ===
* BUG FIX: arena_quarters_interlude (the round 4-5 "day passes" rest) had no Use-a-Potion menu option. Player could buy a Skill Point Potion from the merchant but had no way to drink it during the interlude — and obviously couldn't use it in combat either.
* NEW: Option 15 "Use a potion" added to interlude hub menu. Calls use_potion_menu(warrior, in_combat=False), so all 17 potion types work — including the 3 progression potions (skill_point, stat_point, skill_rank_up).
* AUDIT: All 17 potion handlers reviewed for out-of-combat behavior. Heal/AP/MP potions work anywhere. Status cleansers correctly no-op if no status active. Frostpine works fully. Progression potions correctly require in_combat=False.

# === DEBUG MENU NUMBERING FIX ===
* BUG FIX: Debug menu printed options 1-17, then 20, then 18, 19. Dispatch handled the labels correctly but the print order was scrambled.
* FIX: Renumbered to clean ascending order. 18 = Title Grant Menu, 19 = Exit Run, 20 = Exit Debug Menu. Dispatch updated to match.

# === FROSTPINE TONIC / CURE-ALL acid_defence_loss "BUG" — RESOLVED AS NOT-A-BUG ===
* PREVIOUSLY FLAGGED IN v0.6.14 docs: Frostpine Tonic and Cure-All cleared acid_stacks but not acid_defence_loss. Suspected this meant tonics didn't fully clear acid effects.
* RESOLUTION: User playtest revealed this isn't a bug. Each new acid stack reapplies its own erosion fresh, so leaving acid_defence_loss alone after a tonic is correct — if the player gets re-acided post-tonic, the erosion rebuilds from the new hit. Removed from "deferred bugs" list.

# === FILES MODIFIED ===
* Journey_To_Winter_Haven_v_06_15.py (renamed from v_06_14.py) — blind helper unified, basic attack blind fix, debug menu renumber + dispatch fix, interlude option 15 + dispatch
* monsters.py — Goblin/Drowned/Hydra/Flayed/Fallen ATK+DEF+HP rebalance
* combat_log.py — show_run_score wrapper now returns the computed score (one-line fix)




# === NEW RANK — S+ "DEMIGOD CHAMPION" ===
* NEW: S+ rank added at score threshold 6,500. Sits above S (4,500) and below the eventual SS / SSS tiers (sketched but not implemented).
* TITLE: "Demigod Champion. The Beast Gods themselves take notice."
* DESIGN: S+ at ~70% of theoretical max (~9,600 on a perfect Chimera path). Achievable only on a strong run that triggers most bonus systems — berserk + defier across many fights, low-HP close-match survival, full gold, saved potions, jackpot/bookie wins. Has to feel earned, not default-great.
* IMPL: New entry at top of RANK_THRESHOLDS in score.py and matching RANK_DESCRIPTIONS entry. The _rank_for_score() walk-and-return-first-match logic handles "S+" automatically since the list is now ordered S+ → S → A → B → C → D → F. Rank box display in show_run_score() also adapts to "S+" via dynamic padding (already correct, no change needed).
* FUTURE LADDER: Sketched in score.py comment. SS "god champion" (lowercase, greek pantheon tier), SS+ "Elder god champion", SSS "God Champion" (uppercase G — the Holy Trinity tier), SSS+ TBD. Not implemented — left as a roadmap note for when the run economy supports much higher score ceilings.

# === COMBAT FATIGUE — NEW MECHANIC ===
* NEW: Focus-streak save system kicks in after turn 10 (regular fights) or turn 15 (Chimera/Patronus). Both player and enemy roll d20 independently each turn — escalating DC by streak tier (DC 10 → 15 → 20). Pass = focus holds, fail = lose 1 DEF (roll ≤13) or 2 DEF (roll ≥14), tier resets to 0.
* WHY: Long high-DEF stalemates were grinding fights into spreadsheet duels — both sides chipping for 1-3 dmg/turn for 15+ turns. Fatigue puts a soft end on those by gradually breaking down DEF until someone lands real damage. Solves the actual root cause (mutual DEF too high to break through) rather than just speeding things up arbitrarily.
* DESIGN: Streak resets on fail by design. Means players get satisfying micro-wins (passing the DC 15 save), and the dramatic -2 DEF hit can ONLY happen after a few consecutive passes — narratively this is "you held it together for ages, then finally cracked."
* IMPL: New helper functions init_fatigue(entity), fatigue_threshold_for(enemy), and roll_fatigue_save(entity, turn_count, enemy, is_player) live near clear_rot. State stored as entity.fatigue_def_loss (cumulative, fight-only) and entity.fatigue_save_tier. Subtracts from effective DEF in apply_defence and acid tick logic alongside acid_defence_loss. Reset via reset_after_battle / reset_between_rounds.
* NARRATION: Silent rolls (no dice shown). Pass tier 0 → silent. Pass tier 1 → 🧘 "Your focus holds — you steady your stance." Pass tier 2 → 🧘 "Through the haze of exhaustion, you find a second wind!" Fail -1 → 💨 "Fatigue creeps in — your guard wavers." Fail -2 → 💨 "The long fight catches up with you — your stance breaks!" Monster fatigue narrated with monster's name.
* STACKING: Fatigue stacks INDEPENDENTLY from acid_defence_loss. Both subtract from base DEF. A player with acid + fatigue could have negative effective DEF, triggering the existing -10% per point bonus damage penalty.

# === HARDENED HYDRA + GOBLIN WARRIOR NERFS ===
* HARDENED AP: Hydra Hatchling and Goblin Warrior hardened (level 2) cap at AP 3 (was 4). Higher levels still scale up normally via the HP threshold formula. Was applied as a name-keyed override inside apply_level_scaling — easy to revert.
* WHY: Hardened Hydra's acid spit could chain 4 times in a fight, and even with a Frostpine Tonic mid-fight cleanse, a player would still take 30+ acid tick damage in a single bad-luck run. Capping AP at 3 trims the worst-case tail without removing the threat.
* HARDENED BLEED (Goblin Warrior savage_slash): Tick damage reduced from 4-6 → 3-5 (now matches standard bracket). Duration still 4 turns (vs 2 standard) — hardened remains distinct via duration, not per-tick severity.
* HARDENED ACID (Hydra Hatchling): New hardened tick bracket 2-4 (standard is 3-5). Stack flagged with "hardened": True at apply time so the tick handler can pick the correct bracket. Chimera ignores the flag (it has its own x2 multiplier path).

# === FROSTPINE TONIC + CURE-ALL BUG SURFACED ===
* DIAGNOSIS: Both potions clear acid_stacks (the visible DoT) but NEVER cleared acid_defence_loss. So the sizzling and tick damage stopped, but effective DEF stayed reduced (up to -3) for the rest of the fight. Player thought the tonic did nothing.
* STATUS: Bug identified during a playtest where the player took 9 acid damage plus basic ATK plus -4 effective DEF over a single fight against hardened hydra. NOT FIXED in this version — Nathan opted to feel-test fatigue + AP nerf first before piling on more changes. Logged here so it doesn't get lost.

# === DEMO PLAY-AGAIN PROMPT ===
* NEW: All 5 demo end-points (Chimera victory/defeat, Patronus victory/defeat, arena death) now prompt "Play again? (y/n)" instead of just closing. Yes = relaunch script via os.execv (100% fresh state). No = clean exit with farewell line.
* WHY: Players reaching the end of the demo (especially after a tough loss) shouldn't have to manually relaunch — the friction was killing replay sessions. os.execv re-exec is bulletproof since all 5 endpoints are nested deep in battle/chimera/patronus functions; unwinding to __main__ from each would require threading a "restart requested" exception through several layers.
* HELPER: New prompt_play_again() function placed just above main_menu(). Loops on invalid input until y or n.

# === EDGE CASE — FATIGUE + LOOT EQUIP ORDER ===
* DEFENSIVE FIX: All 4 loot equip points (regular monster kill, DoT-kill, Chimera scale, Patronus breastplate) now explicitly reset fatigue_def_loss and fatigue_save_tier to 0 BEFORE the loot offer. Mirrors the existing defence_warp fix pattern — gear should be evaluated against base DEF, never fight-fatigued DEF.
* WHY: Numerically this wasn't a bug (equipment is additive on base DEF, and reset_between_rounds clears fatigue afterward) — but if Chimera/Patronus victories ever continue into another fight in the future, this would silently corrupt DEF accounting. Fixed now while the system is fresh.

# === FILES MODIFIED ===
* Journey_To_Winter_Haven_v_06_14.py — combat fatigue helpers, apply_defence subtract update, acid tick update, reset_after_battle + reset_between_rounds fatigue cleanup, fatigue save hooks in player + enemy turn blocks, 4 loot-equip safety resets, prompt_play_again helper, 5 endpoint swaps
* monsters.py — hardened AP cap (Hydra + Goblin Warrior name-keyed in apply_level_scaling), savage_slash bleed bracket 4-6 → 3-5, hydra_hatchling_acid_spit tags hardened stacks
* score.py — added S+ "Demigod Champion" rank at threshold 6,500


⚙️  v0.6.13  |  Journey_To_Winter_Haven_v_06_13.py  (Progression Potions — Skill Rank-Up, Stat Point, Skill Point)

# === THREE NEW PROGRESSION POTIONS ===
* NEW POTIONS: skill_rank_up, stat_point, skill_point. All three are out-of-combat only — they refund themselves if used during a fight (the prompt menus would break combat flow). Added to the hero's default potions dict alongside existing healing/utility potions.
* SKILL RANK-UP POTION: Player picks one learned skill (rank >= 1, not yet at max_rank) from a numbered list; that skill advances by 1 rank. Skips skills already maxed. If no eligible skills exist, refunds the potion. Also clears partial skill_progress on the chosen skill so the next rank starts clean.
* STAT POINT POTION: Grants +2 stat points immediately. Drops the player into an inline assignment menu (1) +5 Max HP, 2) +1 ATK, 3) +1 DEF, 4) +1 Max AP, 5) Save for later). No per-level cap — player can dump both points into one stat. Max HP gain also bumps current HP, max_overheal, and AP gain bumps current AP.
* SKILL POINT POTION: Grants +2 skill points and immediately opens show_skill_tree() so player can spend them. Falls through to a simple "+N skill points banked" message if show_skill_tree isn't loaded (defensive guard).

# === USE_POTION_MENU SIGNATURE CHANGE ===
* CHANGED: use_potion_menu(hero) → use_potion_menu(hero, in_combat=False). Combat-side callers pass in_combat=True so progression potions can refund themselves; non-combat callers can omit (defaults to False).
* WHY: The three new potions interact with level-up systems (stat points, skill points, skill ranks) and would interrupt the turn flow if used mid-fight. Refund-and-bail keeps them out of combat without losing inventory.

# === FILES MODIFIED ===
* Journey_To_Winter_Haven_v_06_13.py — three new potion handlers in use_potion_menu, signature change, default potions dict updated


⚙️  v0.6.12  |  Journey_To_Winter_Haven_v_06_12.py  (Patronus Polish, Death Defier Cinematic, Leaderboard & Main Menu)

# === PATRONUS REBALANCE (continued from v0.6.11 work) ===
* PATRONUS FIRST AID: Locked at Rank 4 (40% max HP heal), charges reduced from 2 → 1, trigger threshold raised from 40% → 50% HP. One decisive nuke-heal instead of two random heals. Average healing per fight drops from ~50% to flat 40%, but the moment feels much more threatening.
* PATRONUS DEFENCE BREAK: Locked at Rank 4 (was random 1-4). Priority opener lands at max strength every fight. Charges unchanged at 3.

# === PATRONUS DEATH DEFIER — FULL CINEMATIC ENDING ===
* BUG FIX: Death Defier no longer revives Patronus for a second round. Previously hit 0 HP → revived at 30% → fight continued → required second kill, contradicting the lore that Patronus cannot be killed outright. Now the fight ENDS in player victory when Death Defier fires.
* CINEMATIC: Patronus drops → ancient blood refuses → he RISES (shield gone) → Beast Gods surround player in stronger shield → Patronus charges, strikes the barrier → no effect → he understands.
* NEW: Beast Gods' death sentence. After "BE GONE" he turns to leave. The air changes. "YOU BIT THE HAND THAT FED YOU, PATRONUS. YOUR TIME IS LIMITED. YOU WILL NOT LONG SURVIVE." He stops. He does not turn around. He has been marked.
* DESIGN: The prophecy reframes the future evil-path encounter — player isn't chasing a loose end, they're delivering a sentence the Beast Gods already pronounced. Establishes that the Beast Gods *execute* their fallen champions (deepens their cosmology as active enforcers, not just indifferent harvesters).
* CUTSCENE REWORK: "PATRONUS FALLS" header changed to "PATRONUS BANISHED". Removed double drop-to-sand beat. Added "a shadow of what he was" image. Crowd watches him leave "in disgrace — and under sentence."

# === LEADERBOARD SYSTEM (NEW) ===
* NEW MODULE: leaderboard.py. Top 10 leaderboard persisted to scores.json in the game directory. Captures player name, score, outcome, level, final stats snapshot, and date. Sorts by score desc, date desc tiebreaker (newer wins ties).
* STORAGE: Retains top 10 plus up to 10 most recent non-top-10 runs so non-qualifying players see accurate placement. Corrupted JSON gracefully starts fresh. Disk write failures warn but don't crash the run.
* DISPLAY: Clean fixed-width board (rank, name, level, score, outcome, date). Player's row highlighted with ►...◄ markers when shown. First-time #1 gets 🏆 callout; other top-10 placements get 🎖️ callout. Empty board shows "be the first!" message.
* PLACEMENT: If player makes top 10, row highlighted in board. If not, divider line appears below board followed by "Your run: #N" and their highlighted row.

# === SCORE SYSTEM EXTENDED FOR FATE DEATHS ===
* NEW OUTCOMES: flayed_one (0.5×), drowned_one (0.5×), coward (0.3×). Previously these deaths bypassed the entire end-of-run flow.
* RATIONALE: Coward gets lowest because fleeing the arena is moral failure + dying. Flayed/Drowned are arguably less the player's fault (hostile river terrain) so half-score instead of third-score.
* show_run_score() now returns final_score so the leaderboard can use it. Backwards-compatible (old callers ignored return).

# === FATE-DEATH PATHS REFACTORED ===
* BUG FIX: Coward, Flayed One, and Drowned One deaths previously called quit() / sys.exit(0) immediately — player never saw stats, score, combat log, or leaderboard. All three now flow through show_end_summary → show_run_score → view_combat_log → display_at_end_of_run before exit.
* RESULT: All 8 run-ending paths now flow through a single leaderboard hook. Consistent close-out regardless of how the run ended.

# === MAIN MENU (NEW) ===
* NEW: main_menu() function wraps game launch. Three options: [1] New Game [2] View Leaderboard [3] Quit. Leaderboard option returns to menu after viewing so player can browse before deciding to play.
* HOOK: if __name__ == "__main__": now calls main_menu() before instantiating GAME_WARRIOR. Existing intro_story() flow runs after "New Game" is picked.

# === FURY SURGE COMBAT LOG FIX ===
* BUG FIX: Chimera Fury Overload's Primordial Surge was always logged as 0 damage because log_attack() received hardcoded zeros. Now captures Surge's return value and logs actual damage.
* BUG FIX: Death Defier was never given a chance to fire if Fury Surge dealt the killing blow. Added try_death_defier() call after Surge if warrior.hp <= 0.
* LOG TAG: Fury Surge log line now tagged "[Primordial Surge — Fury, true dmg]" (was "[Primordial Surge — Fury]") for clarity.
* CONDITIONAL LOG: Fury overload log line now distinguishes "basic ATK + Primordial Surge" vs "basic ATK landed killing blow (Surge skipped)" based on whether Surge actually fired.

# === FILES MODIFIED ===
* monsters.py — Patronus class docstring and init (First Aid charges/rank, Defence Break rank)
* Journey_To_Winter_Haven_v_06_12.py — Death Defier rewrite, prophecy cinematic, 8 end-of-run hooks, main menu, Fury Surge log fix
* score.py — 3 new outcome multipliers, 3 new labels, return final_score
* leaderboard.py — NEW module
* LORE.md — Patronus Death Defier description updated with full arc + prophecy
* CHANGELOG.md — full v0.6.12 entry (separate doc)

⚙️  v0.6.11  |  Journey_To_Winter_Haven_v_06_11.py  (Ring Slots, Merchant Trinket Split, 0-of-0 Cleanup)

# === NEW EQUIPMENT SLOTS — FINGER 1 & FINGER 2 ===
* NEW: Hero.equipment dict gained two new slots: finger_1 and finger_2. These hold rings (item.slot == "ring") — two rings can be worn at once.
* RATIONALE: Reserves the trinket slot for active/charged mechanics (Charged Jagged Rock, Waterlogged Stone, consumables) while giving stat-stick items their own home. Also opens design space — gauntlets and gloves can eventually live in a "hand" slot without colliding with rings.
* equip_item(): When equipping an item with slot=="ring", the function picks an empty finger automatically. If both fingers are occupied, the player is prompted to choose which to replace (or cancel).
* unequip_item(): Locates which finger holds a given ring before removing it. Falls back gracefully if the ring isn't currently equipped.
* DISPLAY: Inventory menu, run recap, combat HUD, detailed stats panel, debug glance panel, and debug unequip menu all show both finger slots with clean "Finger 1" / "Finger 2" labels.
* INVENTORY PARSER: Slot commands accept finger1/finger2/f1/f2 aliases for inspect and unequip (e.g. "if1" inspects finger 1, "finger2" unequips ring on finger 2).

# === MERCHANT RING/TRINKET SPLIT ===
* MOVED: The 4 merchant "trinkets" introduced in v0.6.09 (Stoneheart Pendant, Tiger Fang, Stoneskin, Spirit Crystal) are now RINGS — they live in the finger slots. Stoneskin Trinket renamed to Stoneskin Band to fit its new home.
* RATIONALE: These items were always stat-sticks pretending to be trinkets. The trinket slot is more meaningful when reserved for active/passive systems (charges, consumables, adrenaline scaling). Rings = passive stats; trinket = active mechanic.
* NEW: MERCHANT_RINGS list in merchant.py — same 4 items, slot="ring", same prices.
* NEW: MERCHANT_TRINKETS list replaced with the new dedicated trinket lineup (see below).
* STOCK PER VISIT: 2 rings random from the 4-item ring pool, plus 2 trinkets (both currently in pool, so always both shown).
* MENU: New "── RINGS ──" section above "── TRINKETS ──" in the merchant catalog. New buy_ring action handler mirrors buy_trinket. Sell-back works identically (rings appear in the sell list at half price).

# === NEW TRINKETS (merchant) ===
* NEW: Trinket of Adrenaline (20g, passive) — equipped: +2 to max_rage (adrenaline cap). The cheap-buy-in to the adrenaline scaling system; rewards taking damage in fights but doesn't activate until you're hurt.
* NEW: Trinket of Berserk (45g, ONE-SHOT CONSUMABLE) — equipped: no stats. During combat, can be "crushed" to force-activate Berserk mode for 2 turns regardless of HP. Premium price because Berserk is powerful and this lets you fire it without dropping to 10% HP first. Item is destroyed permanently on use.
* DESIGN: Adrenaline trinket is the slow-burn "carry through every fight" choice; Berserk trinket is the "I need to win THIS fight" panic button. Different shapes, different niches.

# === NEW EQUIPMENT FIELDS ===
* NEW: Equipment.max_rage_bonus (int, default 0) — passive +X to hero.max_rage on equip; reversed on unequip. Mirrors max_ap_bonus pattern from v0.6.09.
* NEW: Equipment.consume_on_use (bool, default False) — flags one-shot consumable items. Combat menu uses this flag to surface a "Crush" action instead of a "Stone" action.
* NEW: use_consumable_trinket(warrior, trinket) — handles the Berserk crush action. Asks for y/n confirmation (avoids accidental 45g loss on misclick), checks for redundant activation (you can't crush it while already berserk), removes from equipment slot on success (does not return to inventory — it's gone).

# === COMBAT MENU — TRINKET BUTTON GENERALIZED ===
* CHANGED: The combat menu's trinket option used to be hardcoded as "Stone (X/Y)". Now branches on trinket type:
  - Charge-based trinkets (Waterlogged Stone, etc.) → "Stone (charges/max)"
  - Consumable trinkets (Trinket of Berserk) → "Crush (item name)"
  - Stat-only trinkets (none currently) → no menu option
* New trinket_label variable built once per turn, used across all three combat menu prompt scenarios (weapon+accessory, accessory-only, weapon-only).

# === 0-OF-0 CHARGES DISPLAY FIX ===
* FIX: Trinkets without a charge system (any equipped trinket with stone_max_charges == 0) used to display "[0/0 charges]" across multiple UI surfaces — confusing for the player.
* FIXED IN: Equipment.full_detail(), inventory_menu equipped display, inventory bag list, combat HUD gear line, detailed stats panel, debug menu glance panel.
* GATE: All display sites now check `getattr(item, "stone_max_charges", 0) > 0` instead of `hasattr(item, "stone_charges")`. The hasattr check was always true since the field is defined on the base class.
* COMBAT MENU GATE: The "Stone" combat button used to appear for ANY equipped trinket; now only appears when the trinket actually uses charges or is consumable (prevents a useless button on stat-only trinkets).

# === DEFENSIVE: TRINKET CHARGE RESET ===
* CHANGED: unequip_item() used to unconditionally reset stone_charges and stone_deployed on any trinket. Now only resets when the trinket actually uses charges (stone_max_charges > 0). Prevents touching attributes on trinkets that don't care about them.




# === DEATH DEFIER — AP COST CURVE REBALANCED ===
* CHANGED: Base AP cost curve from 3/3/4/4/5 (rank 1-5) to 1/1/2/3/4. Cheaper at every rank — making Death Defier feel like a tool to reach for, not a luxury saved for emergencies.
* RATIONALE: Old curve discouraged use until late ranks. Combined with the new Death's Apprentice rebound damage, lower AP cost makes the skill feel more active and integrated into combat decisions.

# === RIVER SPIRIT — DISCOUNT CHANGED FROM "FLAT 0 AP" TO "-1 AP PER RANK" ===
* CHANGED: River Spirit path AP cost was flat 0 AP regardless of rank. Now applies -1 AP discount per rank instead.
* NEW RIVER COSTS: rank 1-2 cost 0 AP, rank 3 costs 1 AP, rank 4 costs 2 AP, rank 5 costs 3 AP.
* RATIONALE: The old "always free" gift made River Spirit functionally identical at every rank, so the river path's reward stopped scaling with player investment. The new discount-per-rank model means river-path players still pay less than regular players at every rank, but the cost scales with the power of the ability — preserving the path's identity (cheap casts) while letting investment matter.

# === NEW TITLE — DEATH'S APPRENTICE (renamed from Death Challenger) ===
* RENAMED: death_challenger → death_apprentice. Display name "Death's Apprentice." Internal key changed throughout titles.py, score.py, and main file.
* RATIONALE: Old "Death Challenger" framed the skill as defiance against death. New "Death's Apprentice" reframes it — death has noticed you, claimed you as a study, and reaches through your body to mark those who tried to kill you. Cold familiarity, not friendship. Sets up lore hooks for Game 2.
* NEW PASSIVE: When Death Defier triggers, the enemy takes 20% of the player's max HP as PSYCHIC damage (ignores defence — death's voice itself, not a physical strike).
* KEPT: The -1 AP discount on Death Defier activation cost (floor at 1 AP for non-river players; 0 AP reachable only via River Spirit).
* NEW DIALOGUE: Five flavor variants picked randomly when the rebound fires. Tone: ancient, bureaucratic, indifferent — death as a bookkeeper, not a friend. Each variant has a three-part structure: arena reaction (the ground trembles / pressure settles / dust rises), the voice itself (cold and exact), and an enemy reaction (psychic damage rendered as flavor — "a name has just been written down").

# === REFACTOR — SINGLE SOURCE OF TRUTH FOR AP COST ===
* NEW: _dd_ap_cost(hero) helper added near _dd_effective_rank in main file. Returns the current AP cost based on rank, river status, and mastery title.
* REFACTOR: Both activate_death_defier() (the casting code) and skill_menu() (the display code) now call the helper instead of duplicating the cost calculation. Previously the same logic existed in two places — a maintenance trap where edits to one could drift from the other.
* FLOOR RULE: Discounts can stack down to 0 AP, but only for River Spirit players. Non-river players always pay at least 1 AP — Death's Apprentice discount alone cannot make the skill free. Free casts are the unique reward of the river path.

# === REBOUND DAMAGE PROPAGATION ===
* CHANGED: try_death_defier(hero, reason, enemy=None) — added optional enemy parameter so the rebound knows what to hit. Three call sites updated to pass enemy: special-move death, basic-attack death, and DoT death. DoT case included because the DoT was inflicted by the enemy — death still reaches through the apprentice and marks the source.
* RESILIENCE: Rebound block guarded by enemy is not None — debug invocations of try_death_defier (which call without an enemy) cleanly skip the rebound.

# === DOCSTRING CORRECTION ===
* FIX: activate_death_defier() docstring was stale — claimed rank 1-2 cost 1 AP, rank 3-4 cost 2 AP, rank 5 cost 0 AP. Actual code was 3/3/4/4/5 with -1 mastery discount. Docstring rewritten to match the new 1/1/2/3/4 base curve and full discount table.


⚙️  v0.6.09  |  Journey_To_Winter_Haven_v_06_09.py  (Merchant Shop, Title Polish, River Spirit Fix & Score Display)

# === NEW TITLE: TRUE JACK OF ALL TRADES ===
* NEW: True Jack of All Trades — breadth capstone title awarded when the player reaches rank 2+ in all five core skills (power_strike, heal, war_cry, defence_break, death_defier).
* TRUE JACK BUFFS: +5 Max HP | +1 ATK | +2 DEF | +1 Max AP | +1 Adrenaline (perm_special) | +1 Berserk damage.
* TRUE JACK SCORING: Tier 3, worth 250 points — same tier as the rank-5 mastery titles.
* TITLES.PY: check_true_jack_of_all_trades() added; called from show_skill_tree() and nob_interlude() so Nob's free rank-up can be the trigger.
* TITLES.PY: award_title_with_buff() extended to handle perm_special and berserk_bonus stat keys (previously only handled HP/DEF/ATK/AP).

# === ENDGAME TITLE BUFFS — GUARDIAN & DARK CHAMPION ===
* GUARDIAN (Young Chimera kill): +2 HP / +2 DEF → +10 HP / +4 DEF / +1 ATK / +1 Max AP. Defensive titan identity.
* DARK CHAMPION (Patronus kill): +2 ATK / +2 Max AP → +5 HP / +1 DEF / +4 ATK / +4 Max AP. Glass-cannon striker identity.
* RATIONALE: These are the rarest titles in the game (final-boss-kill only) and were under-tuned vs. their tier-3 score value (500 pts). Buffs now match prestige.

# === REMOVED: DIVINE BLESSING & BEAST GODS' BLESSING ===
* REMOVED: divine_blessing and beast_gods_blessing from TITLE_DISPLAY, TITLE_BUFFS, and TITLE_SCORE_VALUES.
* RATIONALE: Both were dead scaffolding — defined but never awarded anywhere in the codebase. Original intent overlapped with Guardian / Dark Champion (the actual ending titles).
* MORAL CHOICE BLESSING: The good/evil-path full-heal + 2 AP buff remains as an in-fight effect, where it belongs. Not a title.
* SCORE.PY: Tier 3 score header updated — "hereditary blessings" → "breadth capstone".

# === RIVER SPIRIT → DEATH DEFIER CONVERSION FIX ===
* BUG FIX (display): Once the player invested SP into Death Defier, the name still showed as "River Spirit" everywhere (skill menu, HUD, status panel, activation flavour, post-revival message).
* BUG FIX (gameplay): Survive-HP calculation forced rank=1 for any river-flagged hero — ranking up Death Defier from 1→2 expecting 10% survive HP still gave 1 HP because the river flag overrode actual rank.
* ROOT CAUSE: The death_defier_river flag was doing double duty — gating both the displayed name AND the 0-AP / -1 SP discounts. Conversion code intentionally kept the flag True past rank-up to preserve the discount, but that broke the name and rank-scaled effects.
* FIX: Two helpers added — _dd_display_as_river(hero) returns True only when rank == 0, and _dd_effective_rank(hero) returns rank 1 for the rank-0 starter blessing but actual rank once SP is invested. All five name-display call sites updated; survive-HP and skill-menu rank lookups use the effective-rank helper.
* PRESERVED: 0 AP activation cost and -1 SP per rank discount still persist past rank-up — those are the river path's permanent gift, intentional design.

# === NOB TRAINER — SKILL MASTERY FIX ===
* BUG FIX: Nob's free rank-up never fired check_skill_mastery — taking Power Strike from rank 4 to rank 5 via Nob silently skipped the Brawl Master title award.
* FIX: nob_interlude() now calls check_skill_mastery(warrior, key) and check_true_jack_of_all_trades(warrior) after applying the rank-up. Both checks idempotent — guard at function top prevents double awards.
* COVERAGE: Affects all five mastery titles — Brawl Master, Combat Medic, Charismatic Speaker, Armor Piercer, Death Challenger — when Nob's training pushes the relevant skill to rank 5.

# === XP CURVE — LEVEL 1 → 2 ===
* BALANCE: Initial xp_to_lvl raised from 10 to 15. The 1.75 scaling carries through, so the new curve is 15 → 26 → 45 → 78 (cumulative 164 to hit level 5; was 106).
* RATIONALE: With the increased XP rewards from recent monster balance passes, level 5 was being hit before the Fallen Warrior fight, undermining the level-cap-as-pacing-tool design. The ~55% XP bump pushes level 5 reliably past Fallen.

# === WALKING STAFF — atk_max LOWERED ===
* BALANCE: Walking Staff atk_max dropped from 2 to 1. New range: 0 / 1 ATK with +1 DEF.
* RATIONALE: Even the Rusted Sword (poor rarity, 1-2 ATK) felt like a sidegrade. Now the staff is clearly the "carried it from home" placeholder it's meant to be — any arena weapon drop is an upgrade.

# === OVERSEER DIALOGUE — TEMPTATION REWRITE ===
* DIALOGUE: Replaced the post-Fallen Overseer line. Was: "What you are feeling is sentiment. Sentiment is a luxury the arena does not permit."
* NEW: "Their voice settles into your bones, smooth and unhurried. Every word coaxes you toward agreement, as if compliance were the only natural answer."
* RATIONALE: Original line read like a debate-team rebuttal. New line conveys temptation/almost-hypnosis — the Overseer's words pulling the player toward compliance, reinforcing the moral-choice tension at the crux of the Fallen scene.

# === SCORE DISPLAY — TOTAL DAMAGE PROMINENCE ===
* DISPLAY FIX: End-of-run score sheet now leads the Combat Performance section with prominent "Total Damage Dealt" and "Total Damage Blocked" lines, separated from the score contribution by a divider.
* PREVIOUS: Raw totals were buried as parenthetical labels next to score values — easy to miss.
* SCORE.PY: Both raw values and weighted score values are now visible — players can see what they actually did AND how it scored.

# === NEW MODULE: merchant.py — ARENA MERCHANT (round 4-5 interlude shop) ===
* NEW: merchant.py module — shop active only at the round 4-5 interlude. Replaces the prior "(wip)" placeholder in arena_quarters_interlude option 5. Stock generated once per interlude; player can leave to check gear and return without re-rolling the catalog (sold items stay sold, potion counts persist).
* STOCK PER VISIT: 3 weapon types (each expanding to 1-3 rarity variants — see variant rolls below), 2 armors (random from 4 fixed-tier merchant-only basics), 2 trinkets (random from 4 fixed-stat merchant-only basics), full potion lineup (8 types).
* WEAPON POOL: Rusted Sword, Imp Trident, Goblin Dagger, Goblin Shortbow, Goblin War Blade. Javelina Tusk REMOVED — now a crafting component.
* WEAPON VARIANT ROLLS: 3 weapon TYPES drawn per visit. Each type guarantees a normal-rarity listing, plus independent rolls — uncommon variant 50%, rare variant 25%. So a single weapon type can appear at 1, 2, or 3 rarity tiers, letting the player pick what their gold can afford. Total weapon listings per visit: 3 (minimum) to 9 (maximum), averaging ~5.25. NO poor-tier weapons at the merchant — he's been holding back the good stock.
* MENU — EXPANDABLE WEAPON GROUPS: Multi-variant weapons render as a single parent line with [+]/[-] indicator and "(N of N variants)" hint. Click the parent number to expand/collapse — variants show indented underneath with sub-letter codes (1a, 1b, 1c). Single-variant weapons render flat with price visible — clicking goes straight to buy confirm. Keeps the catalog scannable even when total listings hit 9 weapons.
* MENU INPUT PARSER: _parse_menu_choice() handles "1" (parent/flat row), "1a" through "1c" (variant rows), "S" (sell menu), "0" (leave). Case-insensitive on letters. Rejects multi-letter suffixes and letter-prefixed inputs.
* PRICING: anchored against ~60g typical run total. Equipment by rarity: normal 18g, uncommon 35g, rare 65g. Tier 4 armor 80g (aspirational). Sell-back is half buy-price (rounded down, 1g floor).

# === NEW: 4 MERCHANT-ONLY ARMORS (DEF-only, no rarity variants) ===
* NEW: Copper Scale Vest (+1 DEF, 15g) — tier 1 baseline.
* NEW: Bronze Hauberk (+2 DEF, 30g) — tier 2 mid-tier metal.
* NEW: Iron Cuirass (+3 DEF, 50g) — tier 3 solid endgame baseline.
* NEW: Frost-iron Cuirass (+4 DEF, 80g) — tier 4 aspirational; ties to the world's frost-and-ash atmosphere.
* DESIGN: DEF-only on purpose — crafted armors (using Wolf Pelt et al.) will provide HP. Store-bought is the dependable baseline; crafted is the upgrade path.
* PRIOR ARMOR DROPS: Wolf Pelt and Dire Wolf Pelt are now CRAFTING COMPONENTS, not equippable armor in their own right. They still drop from monsters but are blocked from merchant resale.

# === NEW: 4 MERCHANT-ONLY TRINKETS (single-stat, no rarity variants) ===
* NEW: Stoneheart Pendant (+10 max HP, 25g) — flat HP boost for the worried player.
* NEW: Tiger Fang (+2 min/max ATK, 30g) — clean offensive bump.
* NEW: Stoneskin (+2 DEF, 25g) — defensive trinket; meaningful vs. layering low-tier armor.
* NEW: Spirit Crystal (+2 max AP, 30g) — enables an extra ranked-skill use per fight.
* DESIGN: Drop-table trinkets (Charged Jagged Rock, Waterlogged Stone) keep their rarity rolls and complex effects. Merchant trinkets are the simple reliable line.

# === NEW POTIONS: CURE-ALL TONIC & ELIXIR ===
* NEW: Cure-All Tonic (15g, 2 stock) — clears poison, burns/fire stacks, acid stacks, paralysis (only paralysis-source turn_stop), and blindness. Does NOT clear psychic charge or non-paralysis turn_stop reasons.
* NEW: Elixir (30g, 2 stock) — 50% HP + 50% AP combo restore. Premium "I need everything right now" potion.
* MERCHANT POTION LINEUP (no Mega/Full — too premium for an arena vendor): Heal 8g (3), Super Potion 20g (2), AP 10g (3), Super AP 25g (2), Antidote 5g (2), Burn Cream 5g (2), Cure-All 15g (2), Elixir 30g (2).
* MAIN.PY: Warrior __init__ potion dict extended with cure_all and elixir keys. potion_labels dict updated. Debug potion menu items 13-14 added; "Add ALL potions x3" hotkey moved from 13 to 15.

# === NEW: SELL-BACK SYSTEM ===
* NEW: Player can sell unequipped non-blocked inventory back to the merchant at half buy-price (rounded down, 1g floor).
* SELL-BACK GOLD: added to warrior.gold but NOT total_gold_earned (gold.py convention — score system uses lifetime earnings, so sell-back doesn't inflate score).
* CRAFTING COMPONENTS BLOCKED: Wolf Pelt, Dire Wolf Pelt, Poison Sac, Fire Sac, Acid Sac, Soul Pendant, Javelina Tusk all listed in the sell menu but refused with "That's a crafter's job, not mine. Take it to the workshop." — pointer to the future crafter.
* NO-RESALE LIST: Tainted Champion's Breastplate, Chimera Scale, Lightrender, Destiny Definer, Walking Staff (sentimental prologue gift), Frostpine Tonic.

# === ARENA_QUARTERS_INTERLUDE — MERCHANT WIRED IN ===
* MENU: "5) Talk to merchant (wip)" → "5) Talk to merchant" (no longer WIP).
* HANDLER: replaces the "merchant stands behind an empty stall" placeholder with `from merchant import merchant_scene; merchant_scene(warrior)`.
* REVISIT SUPPORT: Stock persists across multiple visits within one interlude — first visit rolls fresh inventory, subsequent visits reopen the same catalog with sold items still sold and potion counts intact. Player can leave to check gear and come back without re-rolling. Prevents the re-roll exploit while supporting natural "let me check my bag" workflow.


⚙️  v0.6.08  |  Journey_To_Winter_Haven_v_06_08.py  (Score System, Patronus Rebalance & The Gooed One)

# === SCORE SYSTEM (NEW) ===
* NEW: score.py module — RNG-resistant end-of-run scoring with 6-tier rank system (S/A/B/C/D/F).
* SCORING: per-fight points = monster threat value (HP + ATK*3 + DEF*2 + AP*2, AP capped at 8).
* SCORING: speed bonus +threat × 0.5 if cleared in <= cap_rounds (reuses gold.py's cap_rounds).
* SCORING: drag penalty -threat × 0.3 if fight exceeds penalty_start.
* SCORING: berserk +20 / death defier +50 / close match (<=20% HP survival) +threat × 0.5.
* SCORING: per-fight floor — never goes below threat / 2.
* SCORING: damage_dealt × 0.5 (capped at 1000 contribution) + damage_blocked × 0.5 (capped 500) — anti-grinder caps.
* SCORING: total_gold_earned × 1 (lifetime, NOT current — spending isn't punished).
* SCORING: titles tiered by difficulty — Tier 1 (50): jack_of_all_trades, chinker, death_delver. Tier 2 (150): champion_of_the_arena. Tier 3 (250): river_warrior, all 5 skill-mastery titles, divine_blessing, beast_gods_blessing. Tier 4 (500): guardian, dark_champion.
* SCORING: fate titles tiered — drowned_one/flayed_one/fallen_champion (50), coward (25), gooed_one (1, the eternal joke).
* SCORING: jackpot_count × 50 (luck bonus) + bookie_intimidated × 25 (skill+luck bonus).
* SCORING: potion bonuses — all regular potions × 5 each (capped at 100 total) + Frostpine Tonic saved +25 separate.
* SCORING: outcome multipliers — chimera_victory ×2.1 (compensates for no gold reward), patronus_victory ×2.0, intervention ×1.5, defeat ×1.0, gooed ×1.0 + 1 flat pity bonus.
* SCORING: rank thresholds — S 4500+, A 3000+, B 1200+, C 500+, D 150+, F 0+.

# === PATRONUS REBALANCE ===
* PATRONUS WAR CRY: Converted from flat +5 ATK to 50% of max_atk (min +1) for 3 turns. Boss-tier scaling exceeds player War Cry Rank 5 (35%). At base stats: +6 ATK (was +5). Future-proofs scaling.
* PATRONUS POWER CHARGE: Damage component unchanged (1.5× attack). Buff component now applies 25% of base max_atk (was flat +3) for 2 turns. Reflects "weaker combo" design — half the buff of full War Cry as the cost of doing two moves at once.
* PATRONUS POWER CHARGE: Buff calculation now uses BASE max_atk (subtracts active war_cry_bonus before %-calc) — fixes subtle stacking math issue when chained with active War Cry.
* PATRONUS VICTORY: Now rewards +100 gold ("The Beast Gods leave +100 gold at your feet"). Compensates evil-path payout vs. good-path's ×2.1 score multiplier.

# === THE GOOED ONE (NEW FATE TITLE) ===
* NEW: gooed_one fate title — awarded when player dies to a regular (non-Chimera) Green Slime while still having unused healing options (heal/super/mega/full potion, antidote, Frostpine Tonic, or learned First Aid).
* GOOED ONE: replaces standard Fallen Champion sequence with a custom roast (crowd boos, refunds issued, the slime nudges your corpse to ask if you're okay). Designed for "death by my own stupidity" scenarios after the slime tier rebalance.
* GOOED ONE: Death Defier / River Spirit interaction documented in helper comments — title only fires after Death Defier has had its chance to save the player.

# === END-OF-RUN FLOW ===
* BUG FIX: End-of-run stats no longer display twice on combat death. Both battle_inner death paths (DoT and direct-hit) were calling the full end-of-run sequence, then arena_battle was calling stats again on top.
* CONSOLIDATION: arena_battle now owns all post-death wrap-up. battle_inner death paths only log the death and return False.
* NEW: Demo-end "thanks for playing" sequence on combat death. Tailored retry encouragement — cheeky for Gooed One deaths ("Better luck next time, Goo Guy"), solemn for regular Fallen Champion deaths ("The Beast Gods have claimed another champion").
* NEW: "Well fought, warrior" send-off for boss-intervention defeats (Chimera or Patronus, cycles >= 4). Distinct tones — Chimera path heroic, Patronus path darker but encouraging.
* FIX: Boss fight close paths (chimera_fight, patronus_fight) — score order corrected. Was: thanks-for-playing → score. Now: score → combat log → thanks-for-playing → press-Enter close. Matches arena_battle's order.

# === GOLD TRACKING ===
* NEW: gold.py — award_gold(warrior, amount) helper. Adds to both warrior.gold (current pouch) and warrior.total_gold_earned (lifetime, never decreases on spending).
* GOLD: All 4 bookie sites (skim/catch/intimidate/+1 tip) now use award_gold().
* GOLD: All 3 main-file gold sites (Beast Gods 50g, direct kill enemy.gold, DoT kill enemy.gold) now use award_gold().
* TRACKING: warrior.bookie_intimidated_count increments on each successful intimidate result (used by score system).
* TRACKING: warrior.per_fight_scores list — populated by score.record_fight_score() at each victory site (3 generic + Chimera + Patronus = 5 sites).

# === FILE STRUCTURE ===
* NEW: score.py module created.
* MOVED: Journey_To_Winter_Haven_v_06_07.py → Old .6 builds/ folder.
* COMBAT_LOG: show_run_score() now delegates to score.py when given a warrior object; falls back to legacy stat-dump for callers passing just a name string.


⚙️  v0.6.07  |  Journey_To_Winter_Haven_v_06_06.py  (Rot System, Weapon Identity & Gold Overhaul)
* NEW: Rot — new status effect that drains max HP rather than current HP.
* ROT (player → enemy): Rusted Sword proc. Flat stack drain per hit, capped at 30% enemy max HP. Resets between fights.
* ROT (enemy → player): Brittle Skeleton Rot Thrust special — 50% proc, -20% max HP per stack, capped at 50% base max HP.
* ROT (Chimera): Borrowed Rot Thrust — 75% proc, cap 60% base max HP. Only clears on intervention if this move was drawn.
* ROT CLEAR: Regular rest (max HP restored, no HP heal). Long rest / Patronus / Chimera intervention (full restore).
* ROT CLEAR: Rank 4+ First Aid cures rot but heal is reduced by rot loss percentage.
* ROT CLEAR: Frostpine Tonic clears rot fully, no penalty (unique item, handmade).
* ROT HUD: Active rot shown in combat stats — total loss, base max HP, cap percentage.
* RUSTED SWORD: Defence removed across all rarities. Poison proc replaced with Rot proc.
* RUSTED SWORD: poor 15%/1 stack/-1HP | normal 25%/2 stacks/-1HP | uncommon 40%/3 stacks/-1HP.
* RUSTED SWORD: rare 55%/4 stacks/-2HP | epic 65%/5 stacks/-3HP | legendary 75%/6 stacks/-4HP | mythril 90%/7 stacks/-5HP.
* WALKING STAFF: Rarity changed from poor to starter — displays as just "Walking Staff" with no rarity prefix or icon.
* WALKING STAFF: atk_min lowered from 1 to 0 — can now whiff, making it feel unreliable vs Rusted Sword.
* Equipment class: rot_chance, rot_stacks, rot_hp_per_stack fields added (default 0). starter rarity added to RARITY_ICONS.
* stat_lines(): rot proc displays as "🟫 X% chance to rot (N stacks, -Y max HP/stack)".
* short_label() / full_detail(): starter rarity skips icon and rarity word entirely.
* MONSTERS: brittle_skeleton_thrust renamed to rot_thrust. Old name kept as alias. __all__ updated.
* CHIMERA: CHIMERA_TIER1_POOL updated to rot_thrust. Spawn flavour hints at rot when drawn.
* GOLD: Variant bonus added — +5g per monster level above 1 (Hardened +5g, Veteran +10g, Elite +15g).
* GOLD: Variant bonus baked into base_gold so the floor also reflects it. Shows in payout breakdown.
* BOOKIE: Pickpocket tell removed — player no longer told the exact amount stolen.
* BUG FIX: show_all_game_stats() (display_run_score) now fires on both defeat paths — DoT death and regular death.

⚙️  v0.6.06  |  Journey_To_Winter_Haven_v_06_06.py  (Gold System & Run Scoring)
* GOLD SYSTEM: New gold.py module added — handles all arena gold reward logic.
* GOLD: Per-tier base payouts (Tier 1: 5g, Tier 2: 10g, Tier 3: 15g, Fallen: 20g, Patronus: 30g).
* GOLD: Round bonus system — +1 gold per round up to tier cap, -1 per round over cap.
* GOLD: Floor enforced at base gold — penalty rounds can never drop payout below base.
* GOLD: Performance bonuses — +5 gold if Berserk triggered, +10 gold if Death Defier triggered.
* GOLD: Close match bonus — warrior at ≤20% HP on victory restores full base payout on top.
* GOLD: Chimera pays 0 gold — you angered the Beast Gods.
* GOLD: Patronus/Fallen pay out but bypass bookie (handled post-tournament).
* GOLD: Payout is held as pending_bookie_gold until player collects from the bookie.
* BOOKIE: Goblin bookie placeholder replaced with full d20 encounter system.
* BOOKIE: Roll 1–11 — bookie skims 10%, player doesn't notice.
* BOOKIE: Roll 12–17 — player catches the skim, full amount paid.
* BOOKIE: Roll 18–20 — player intimidates bookie, +10% bonus payout.
* BOOKIE: Second visit dialogue reacts to first visit outcome (stolen / caught / intimidated).
* BOOKIE: bookie_result and pending_bookie_gold added to Warrior.__init__.
* SCORING: display_run_score() added — end-of-run performance grade (F/D/C/B/A/S).
* SCORING: Score components: ATK, Defence, Gold earned, Loot equipped, Potions unused, Titles.
* SCORING: Rank thresholds — F:<30, D:30-49, C:50-74, B:75-99, A:100-124, S:125+.
* SCORING: Score card displays after show_all_game_stats() on all win and loss endings.

⚙️  v0.6.05  |  Journey_To_Winter_Haven_v_06_05.py  (Combat Systems & Balance)

⚙️  v0.6.04  |  Journey_To_Winter_Haven_v_06_04.py  (Monster Balance Pass)
* BALANCE — Tier 2 monster base stat buff (+5 HP, +1 ATK, +1 DEF, +1 AP, +10% XP):
  Red Slime (16→21 HP, 2-4→3-5 ATK, DEF 1→2, AP 2→3, XP 16→18),
  Noob Ghost (16→21 HP, 3-6→4-7 ATK, DEF 0→1, AP 2→3, XP 13→15),
  Goblin Archer (15→20 HP, 3-5→4-6 ATK, DEF 1→2, AP 2→3, XP 17→19),
  Dire Wolf Pup (16→21 HP, 4-6→5-7 ATK, DEF 3→4, AP 2→3, XP 19→21),
  Javelina (18→23 HP, 3-6→4-7 ATK, DEF 2→3, AP 2→3, XP 18→20).
* BALANCE — Tier 3 monster base stat buff (+10 HP, +2 ATK, +2 DEF, +2 AP, +20% XP):
  Wolf Pup Rider (21→31 HP, 3-7→5-9 ATK, DEF 3→5, AP 2→4, XP 23→28),
  Hydra Hatchling (25→35 HP, 3-6→5-8 ATK, DEF 3→5, AP 2→4, XP 27→33),
  Flayed One (23→33 HP, 4-6→6-8 ATK, DEF 2→4, AP 2→4, XP 25→30),
  Drowned One (27→37 HP, 5-8→7-10 ATK, DEF 3→5, AP 3→5, XP 30→36),
  Goblin Warrior (30→40 HP, 5-9→7-11 ATK, DEF 4→6, AP 3→5, XP 33→40).
* BALANCE — Hardened level scaling formula doubled for all tiers:
  HP +10 per level (was +5), ATK +2 per level (was +1), DEF +2 per level (was +1).
* BALANCE — DoT hardened values increased across all DoT monsters:
  Poison (Slime) hardened: 3-4 dmg/turn for 4 turns (was 1-2 for 2 turns).
  Bleed (Savage Slash) hardened: 6-8 dmg/turn for 5 turns (was 4-6 for 3 turns).
  Psychic Shred hardened: debuff duration 4 turns (was 3 turns).
  Psychic Drown hardened: damage table 5/6/7 per stack (was 3/4/5), 6 turn duration (was 4).
  Acid Spit (Hydra) hardened: 4 turn duration (was 3 turns).
* STORY — Aldric sendoff: flicker of concern added before "Eyes only" line — hints
  the road to Winter Haven has been too quiet; merchants have mentioned it. He hasn't
  told Umbra. Clasp rewritten from "claps harder than necessary" to "clasps shoulder
  and holds it a moment longer than necessary."
* STORY — Forest journey expanded: Day 1 now has eerie animal silence beat. Day 3
  added (no travelers on a known road, slow dread). Day 4 rewritten as deep loneliness
  and longing for human contact. Arrival rewritten: sees city lights hours out, hears
  distant city sounds, makes camp outside rather than pushing through — then "you never
  make it to the dungeon entrance."
* STORY — Elwyn renamed from Elwin throughout. Farewell rewritten: wraps Umbra in a
  warm hug, kisses him on the cheek, delivers "Stay out of trouble. And don't dawdle."
  (line moved from Aldric's section to Elwyn's). Aldric's section cleaned accordingly.
* BUG FIX — Bo tackle path (say yes to Winter Haven → run → caught): was granting
  only heal potion despite dialogue saying two potions. Corrected: tackle path now
  grants heal potion only (dialogue updated to match). Tree branch path (say no →
  run → hit branch) correctly grants both heal and AP potion — earns it for the
  harder hit.
* BUG FIX — Skill investment loop: stale input("Press Enter...") removed from
  show_skill_tree(). Player can now invest points back-to-back without pressing
  Enter between each investment, as intended.

⚙️  v0.6.03  |  Journey_To_Winter_Haven_v_06_03.py  (Monster Extraction, Dev Shortcut Refactor & Prologue Polish)
* ARCHITECTURE — monsters.py extraction: 18 monster classes (Green_Slime through
  Patronus), 51 special-move/AI/encounter functions, and 8 module-level constants
  (MONSTER_TYPES, CHIMERA_TIER1/2/3_POOL, TIER4_BOSSES, HEAL_PERCENTS_ENEMY,
  CHIMERA_ELEMENTS, LEVEL_TITLES) moved out of the main file into monsters.py.
  Main file shrank from ~13,255 to ~11,090 lines (–2,175). monsters.py is ~2,300
  lines. `__all__` list in monsters.py exports public AND underscored helpers
  (cleanly handles names like _clear_psychic_debuff that main calls back into).
  Resolves Python 3.13 partial-module circular-import edge case discovered during
  testing.
* DEV SHORTCUT REFACTOR — new _try_dev_shortcut() helper used by both
  continue_text() and check(). q (restart), c/combat (jump to arena), and debug
  (open debug menu) now work at every story prompt — previously inconsistent
  (q only worked at check() prompts, debug only at check() prompts, etc.).
  Adding a new shortcut now requires editing one function instead of three.
* RESTART BUG FIX — intro_story() on RestartException now fully replaces
  GAME_WARRIOR with a fresh Warrior() and clears COMBAT_LOG. Previously the
  existing warrior was reused, which leaked the player's name across the restart
  and caused the framing/name-prompt scene's `name == "warrior"` gate to fail —
  player landed mid-prologue with stale state instead of restarting from the top.
* STORY — Opening framing scene added: cold-morning beat at Ashenveil's eastern
  gate, ash drifting from Frostveil Peak, three short paragraphs that establish
  scout-quest tone before the name prompt. "First quest — a scouting run" replaces
  "first real quest" to scale tone to the actual mission.
* STORY — Aldric rewritten for scout mission: checks for buckles/pack-strap noise
  instead of armor weak points; brief is "Confirm the dungeon entrance exists,
  watch what comes in and out, take notes, get back" with explicit "Eyes only.
  You don't go inside. You don't pick a fight. You don't try to be a hero."
  Parting line: "Don't dawdle. And stay out of trouble." Scene split across two
  screens (advice / exit) so player isn't scrolling back to re-read.
* STORY — Forest travel expanded from one-afternoon walk to four-day trek.
  Daily beats: forest entry, first night camp (sheltered behind ash trunk, cold
  rations), day two (something in the trees), day four (rations and aching feet,
  "trade your boots for a hot meal"), arrival at Winter Haven (legs screaming,
  ready for warm bed → "you never make it to the dungeon entrance"). Each beat
  gets its own clear_screen.
* LORE CANON — Frostveil Peak established as semi-active volcano. Airborne ash
  drifts down from the peak and settles on Ashenveil + the forest. Ash etymology
  is now *layered*: ash trees with pale grey bark + volcanic ash drift. Both
  meanings real, both canonical.
* GAMEPLAY — Frostpine Tonic now REPLACES the starting heal potion at Elwyn's
  scene. heal=0 + frostpine_tonic=1. Player walks into the arena with one
  consumable, not two. Lampshaded in-fiction: "(It replaces the basic heal flask
  you'd packed for the trip.)"
* WORD CHOICES — "in the lee of" → "sheltered behind" (clarity); "dagger" →
  "walking staff" / "boots" (Umbra carries no real weapons — sells the
  "captured and stripped, fighting bare-fisted" tournament setup cleanly).
* TYPO — "Forstback Mountain" → "Frostback Mountain" in prologue prose
  (consistent with the rest of the codebase; LORE.md still has both spellings
  to reconcile in a future pass).

⚙️  v0.6.02  |  Journey_To_Winter_Haven_v_06_02.py  (Player Name Prompt & Re-prompt Gating)
* NEW: get_name_input() called at start of ashenveil_prologue() — player can
  name their character at the very first beat. Default to "Umbra" if ENTER is
  hit on an empty prompt (preserves canonical name as fallback). Gated by
  `if GAME_WARRIOR.name == "warrior"` (the Warrior() __init__ default), so it
  only fires on a fresh run.
* UPDATED: hardcoded "You are Umbra" → f"You are {warrior.name}" in the Ash
  Hall paragraph.
* GATED: 5 legacy get_name_input() call sites at later story junctures
  (cave/beastman intro, magical darkness, Bo introduction, frigid river rescue,
  River Warrior path) wrapped in `if GAME_WARRIOR.name == "warrior"`. NPC
  dialogue lines that ask "What is your name?" still play, but the prompt is
  skipped when the player has already named themselves at the start.
* CLEANUP: dead `while True:` loop removed from get_name_input() — every branch
  inside returned, so the loop never iterated. Stripped unused `global` too.

⚙️  v0.6.01  |  Journey_To_Winter_Haven_v_06_01.py  (Ashenveil Prologue & Frostpine Tonic)
* NEW: ashenveil_prologue() — full pre-arena backstory scene. Umbra is 19, greenhorn
  Vanguard member, sent on his first quest: travel to Winter Haven, confirm the dungeon
  exists, clear the first floor. His father Aldric (A-rank senior Vanguard) quietly
  arranged the mission thinking it was a safe first win for his son.
* NEW: Aldric sendoff scene — gruff, proud, teases Umbra about a girl in the market.
* NEW: Elwyn sendoff scene — quiet, warm, presses the Frostpine Tonic into his hand
  and walks away without saying goodbye.
* NEW: Ashen Frost Forest travel narrative — atmospheric passage from Ashenveil toward
  Winter Haven, hints at danger without combat encounters. Named for ash-pale trees and
  frost creeping in from Forstback Mountain.
* NEW: Frostpine Tonic — unique starting item gifted by Elwyn. Restores 40% HP, clears
  all status effects, and restores 2 AP. Cannot be bought or found. One use only.
  Added to potions dict and fully implemented in use_potion handler.
* UPDATED: intro_story_inner() forest opening text updated to flow naturally from the
  new prologue — Umbra is now arriving rather than wandering lost.

⚙️  v0.5.14  |  Journey_To_Winter_Haven_v_05_14.py  (Chimera Carapace Passive, Bug Fixes & Word Wrap)
* CHIMERA CARAPACE: Young Chimera now has a permanent 20% reduction on all incoming
  player physical ATK rolls, applied before defence is calculated in monster_deal_damage().
  If tier 3 draw is psychic_shred (Flayed One's move), reduction increases to 35%.
  Flayed draw announces in spawn flavour text. chimera_atk_reduction stored as float
  on enemy; getattr default 0.0 means zero overhead on all non-Chimera enemies.
* BUG FIX: Charismatic Speaker ATK drift — reset_between_rounds() was stripping a
  hardcoded flat 2 from player ATK but the title applies ceil(max_atk * 0.15) which
  equals 3 at ATK ≥ 14. Caused permanent silent ATK inflation over a full run. Fixed
  by storing exact bonus as warrior.charismatic_speaker_bonus at apply time and reading
  it back at strip time.
* BUG FIX: Patronus DEF restore hardened — battle(warrior, patronus) wrapped in
  try/finally so _restore_patronus_def() fires even on unhandled exception.
* WORD WRAP: Five bare print() calls in arena_quarters_interlude() were missing wrap()
  — goblin bookie repeat, orc guard both lines, crafter both lines. All now wrapped.
  Were rendering without line breaks on narrow tablet viewports.

⚙️  v0.5.13  |  Journey_To_Winter_Haven_v_05_13.py  (Flayed One Bug Fix & Boss Balance)
* BUG FIX: Flayed One double-debuff — psychic_shred() was applying a separate
  25-50% ATK/DEF reduction on top of the charge system, reducing player to ATK 1-1
  and DEF 0. psychic_shred() is now damage-only for Flayed One; all stat drain is
  handled exclusively by _flayed_charge_tick(). Chimera retains percentage debuff.
* CHIMERA: psychic_shred debuff reduced from 60% to flat 30% ATK/DEF for 4 turns —
  prevents death spiral interaction with DEF-below-zero 10% damage bonus mechanic.
* CHIMERA: Oppressive Presence added — if Chimera rolls psychic_shred as her Tier 3
  move, player starts the fight at -2 ATK / -2 DEF. Restored after fight ends.
* PATRONUS: 30% passive damage reduction already active via shield_equipped flag —
  confirmed working, no changes needed.

⚙️  v0.5.12  |  Journey_To_Winter_Haven_v_05_12.py  (Balance & Evil Path Polish)
──────────────────────────────────────────────────
* END SEQUENCE: view_combat_log() added before "Thank you for playing" on Chimera victory path
* END SEQUENCE: Chimera defeat — show_run_score() moved to after intervention scene on both defeat branches; "Thank you" + combat log now fire correctly on all four Chimera outcomes
* END SEQUENCE: Patronus victory — view_combat_log() added before "Thank you for playing"
* END SEQUENCE: Patronus defeat — was completely missing closing sequence; now fires view_combat_log() + "Thank you" + show_run_score() after both defeat branches (overwhelmed and intervention)
* SAVAGE SLASH: Fixed loop bug — was applying 2 bleed stacks per cast instead of 1; now correctly applies 1 stack per hit up to a cap of 2 simultaneous stacks
* BERSERK: Now clears in reset_between_rounds() — all five variables (active, bonus, turns, used, pending); prints flavour line if berserk was active at round end
* WARRIOR_BLEED_DOTS: Added to reset_between_rounds() — Savage Slash stacks no longer carry between rounds
* DUSKBRINGER: Flat stats — ATK +6, DEF -2 (was derived from base constants, penalty silently cancelled out)
* DESTINY DESTROYER: Flat stats — ATK +8, DEF -3 (same fix)
* EVIL PATH SCENE: Removed "The crowd watches too" line from Fallen Warrior moral choice scene
* EVIL PATH SCENE: Beast Gods offer rewritten — now promises weapon core + gold + blessing (removed "every piece of loot" wording)
* EVIL PATH: Beast Gods deliver 50 gold mechanically on essence return — prints running total

⚙️  v0.5.11  |  Journey_To_Winter_Haven_v_05_11.py  (End Sequence & Balance Pass)
──────────────────────────────────────────────────
* FALLEN WARRIOR: HP clamped to 1 on death — moral choice delivers the killing blow (both direct and DoT kill paths)
* FALLEN WARRIOR: Moral choice now fires before Champion title is awarded
* WEAPON CORE: _make_weapon_core() now path-aware — corrupted=False gives Lightrender/Destiny Definer, corrupted=True gives Duskbringer/Destiny Destroyer
* WEAPON CORE: Drops after moral choice on both paths — good path pure, evil path corrupted by Beast Gods
* WEAPON CORE: Old in-place corruption block removed — replaced by unified _make_weapon_core(corrupted=True)
* CHAMPION TITLE: Now awarded inside fallen_warrior_moral_choice() after weapon is offered, before boss fight
* CHIMERA INTERVENTION: Moved from victory path to defeat (else) path — was unreachable on loss
* STAT CAP: Hard cap of 2 per category at all levels including level 5 — was incorrectly allowing all 5 points into one stat
* BONUS ACTION: 1 free potion or Waterlogged Stone use per opponent — resets at start of every battle_inner call
* BONUS ACTION: Potion menu shows AVAILABLE/USED tracker — stone option shows ⚡ FREE tag in combat menu
* BONUS ACTION: Returns "bonus" instead of True so battle loop knows not to set turn_spent
* OVERHEAL + POTION: heal_percent() fixed — being above max_hp no longer causes negative heal
* POTION: Full HP confirmation — warns player and asks yes/no before consuming HP potion at full health
* DIRE WOLF: Devouring Bite now uses overheal cap (1.5x max HP) matching Ghost life leech behavior
* DIRE WOLF: Removed full HP safeguard that was silently aborting Devouring Bite
* SLIME POISON: slime_poison_spit() now uses slime's full ATK roll for physical hit
* SLIME POISON: Green Slime poison 1-2 dmg/turn for 2 turns — Chimera borrowed version 4-6 dmg/turn for 3 turns
* STATUS CLEAR: clear_all_status_effects() now clears defence warp and psychic debuffs — fixes bleed-in to boss fights
* BONUS ACTION: Removed from clear_all_status_effects() — was incorrectly treated as a status effect
* BERSERK: berserk_used reset now requires berserk_active=False — healing above 20% HP during rest no longer re-arms berserk while kill extension is still running

⚙️  v0.5.10  |  Journey_To_Winter_Haven_v_05_10.py  (Bonus Action & Bug Fixes)
──────────────────────────────────────────────────
* BONUS ACTION: Initial implementation — 1 free potion/stone use per fight
* OVERHEAL + POTION: Initial heal_percent fix
* DIRE WOLF: Initial overheal and devouring bite fixes
* BERSERK: berserk_used reset fix
* Note: v5.10 superseded by v5.11 which corrects bonus action reset scope and end sequence

⚙️  v0.5.09  |  Journey_To_Winter_Haven_v_05_09.py  (Polish & Systems Pass)
──────────────────────────────────────────────────
* LOOT: offer_loot() helper — immediate equip prompt after every enemy defeat, shows current slot item for comparison
* LOOT: All three drop locations (main battle, DoT kill, Fallen Warrior) now use offer_loot()
* CHARGED JAGGED ROCK: Moved from accessory to trinket slot — can now coexist with Waterlogged Stone
* CHARGED JAGGED ROCK: Pool-based charge system — absorbs enemy.max_atk * debuff_pct per hit, persists run-wide
* CHARGED JAGGED ROCK: Charge bar in HUD using rarity colors (⬜🟦🟩🟨🟪🟥🟧), updates on tier change
* CHARGED JAGGED ROCK: ATK bonus applies while equipped, scales with charges (max by rarity 1-7)
* CHARGED JAGGED ROCK: Debuff now fires on any hit (trinket slot), not just accessory attacks
* CHARGED JAGGED ROCK: Turn limit by rarity (2/2/3/3/4/4/5), resets on expiry with stat restore
* DEATH DEFIER: Path-aware dialogue — River Spirit, good path (deity prayer), evil path (Beast Gods chant), neutral
* COMBAT SCORE: show_run_score() — grand total damage breakdown at demo end screen (basic/special/DoT split with %)
* COMBAT LOG: Per-fight summary now shows basic vs special damage split
* TITLE SYSTEM: Debug title grant menu (item 20) — all titles with buff descriptions, owned marker
* LEVEL UP: stat_cap now scales with stat_points available — double level-up allows 2 points per category
* DEATH DEFIER HUD: Fixed dd_name scope bug — UnboundLocalError on available state
* CHIMERA: Fixed monster_ai_check tier 5 — was gated on ap > 0, specials never fired
* XP: Fallen Warrior now properly grants 50 XP via animate_xp_results in moral choice

⚙️  v0.5.08  |  Journey_To_Winter_Haven_v_05_08.py  (Moral Hook & Final Bosses)
──────────────────────────────────────────────────
* MORAL CHOICE: fallen_warrior_moral_choice() — Fallen Warrior death scene, Beast God intervention, crush/return essence split
* GOOD PATH: chimera_fight() rebuilt as true final boss — charge-based, Primordial Surge active move, 80 HP / 8 DEF / ATK 14-18
* EVIL PATH: patronus_fight() — existing boss now properly gated behind evil path choice
* TAINTED BLADE: evil path corrupts Weapon Core in place — Duskbringer (one-handed: +6 ATK, -2 DEF) or Destiny Destroyer (two-handed: +8 ATK, -3 DEF)
* TAINTED BREASTPLATE: Patronus drop changed from shield to Tainted Champion's Breastplate (+7 DEF, -5 HP)
* ENTRY SCENES: both boss fights now have full cinematic entry scenes with heal, +2 temp max AP, status clear
* CHIMERA ENTRY: mysterious figure freezes time, heals player, "We will meet again"
* PATRONUS ENTRY: Patronus drops into arena, Beast Gods' shield appears, cracks, "You die NOW"
* INTERVENTION: threshold raised to 4 cycles for both fights
* CHIMERA INTERVENTION: figure returns, stabilises player (1/3 HP restore), "I am limited in how much I can intervene"
* PATRONUS INTERVENTION: stronger unbreakable shield, Beast Gods teleport Patronus out, rage in his eyes, "He will have his revenge"
* COMBAT LOG: detailed round breakdown — attack names, damage dealt/blocked, DoT sources per effect
* CHIMERA AI: fixed tier 5 in monster_ai_check — was gated on ap > 0, specials never fired
* CHIMERA CHARGES: tier-based charge system (tier1=5, tier2=4, tier3=3, surge=4), ap=99 dummy pool
* GOBLIN CHEAP SHOT: blind reduced to 1 turn when used by Chimera
* CREATURE NAMES: fixed hardcoded names in borrowed moves (imp, dire wolf, skeleton, ghost)
* VIEW ALL STATS: now shows all learned skills with ranks and descriptions
* DEBUG MENU: removed Defence Break shortcut, renumbered items 13-19
* DOT LOG: breakdown now shows per-effect sources inline

⚙️  v0.5.07  |  Journey_To_Winter_Haven_v_05_07.py  (Session 8 — Patronus build)
──────────────────────────────────────────────────
* PATRONUS: New evil path boss — class, AI dispatcher, all enemy skill functions built
* PATRONUS: Stats — HP 85 (+6 shield = 91 effective), DEF 4 (+6 shield = 10 effective), ATK 5-9, AP 7
* PATRONUS: Skills — Double Strike R5, War Cry R5, Power Charge (hidden combo), First Aid (random R1-4), Defence Break (random R1-4)
* PATRONUS: Desperation scaling — 50/60/75/90% special chance by HP threshold
* PATRONUS: Death Defier — revives at 30% HP on first death, shield stripped (DEF drops to base 4)
* PATRONUS: cycle-based intervention — 3 full cycles required before Beast Gods intervene on loss
* PATRONUS: patronus_fight() wrapper — spawn scene, Death Defier revival scene, Beast Gods banishment, Tainted Champion's Shield drop
* PATRONUS: story flags — patronus_shield_dropped, patronus_intervention
* PATRONUS: _restore_patronus_def() — restores Defence Break debuff after combat
* PATRONUS: War Cry and Defence Break tick functions — buff/debuff expire correctly each turn
* PATRONUS: Added to debug monster select (18) and debug loot manager (18)
* TAINTED CHAMPION'S SHIELD: Renamed from Light Corrupter — +6 DEF -3 HP (updated from -2 HP)
* CHIMERA SCALE: Updated to +5 DEF +3 HP (was +5 DEF +0 HP)
* CHIMERA: combo system replaced chimera_double — borrowed move fires then Chimera follows through with own basic attack
* CHIMERA: Primordial Surge now true damage — bypasses defence entirely
* CHIMERA: AP regen on rest turns fixed to flat 1 (was random 1-2)
* CHIMERA: Arena intervention exempted during Chimera fight — paralyze chain guard still active
* CHIMERA: Psychic drown/shred no-stacking flavour text removed
* CHIMERA: Strict alternation special/rest with 25% basic attack feint chance on special turns
* CHIMERA: combat_cycles tracker — increments after every enemy turn, generic for Patronus reuse
* CHIMERA: chimera_fight() rewritten — cycle-based intervention (3 cycles), story flags chimera_vanquished / chimera_alive
* WEAPON CORE: Stale rarity comment block removed — replaced with fixed stats design note

⚙️  v0.5.06  |  Journey_To_Winter_Haven_v_05_06.py
──────────────────────────────────────────────────
* CHIMERA: Stats updated — HP 75, ATK 7-12, DEF 6, AP 7 (from LORE v5 overhaul targets)
* CHIMERA: HP-threshold aggression added to monster_ai_check tier 5 — 40/50/65/80% by HP %
* CHIMERA: Cooldown system — special fires then forced rest turn (basic attack + 1-2 AP regen)
* CHIMERA: Weighted move selection — escalating by turn count (tier1 early, tier3 late) with 20% chaos roll; last used move gets -2 weight to encourage variety; filters to affordable moves only
* CHIMERA: CHIMERA_TIER3_POOL expanded — savage_slash, psychic_shred, psychic_drown added
* CHIMERA: All borrowed move display names fixed to use enemy.display_name
* CHIMERA: chimera_double() helper — doubles physical roll when chimera_extra_turns flag set
* CHIMERA: chimera_boost() helper — returns +1 turn duration for tier 3 moves
* PRIMORDIAL SURGE: New signature breath attack — 3 charges, no recharge, rest-turn only
* PRIMORDIAL SURGE: Desperation trigger — 50/65/80/90% chance by HP threshold on rest turns
* PRIMORDIAL SURGE: Heavy physical hit + permanent stat degradation per charge used (-2 max ATK, -2 DEF, -5 max HP)
* PRIMORDIAL SURGE: Stats tracked on warrior.primordial_atk/def/hp_loss; restored after combat via _restore_primordial_stats()
* GOBLIN SHORTBOW: Replaces Paralyzing Arrow — weapon slot, wide ATK spread, paralyze proc built in; multi-turn paralyze locked behind rare+
* BOSS DROPS: Fixed stats, no rarity — Lightrender (+4 ATK +2 DEF), Destiny Definer (+5 ATK +1 DEF), Chimera Scale (+5 DEF), Light Corrupter (+6 DEF -2 HP)
* SKILL SYSTEM: All skills capped at rank 5; rank_descs sliding window; tier 2 names teased
* DEFENCE BREAK: Full skill system — SKILL_DEFS, combat function, tick, award on Fallen Warrior kill
* RIVER SPIRIT: Renamed from Death Defier throughout for river path version
* BUG FIX: import math crash in player_basic_attack
* BUG FIX: Charged Jagged Rock stale stats on hardened enemies
* BUG FIX: Turn counter not advancing on lost player turns
* BUG FIX: Drown punishment reworked to flat +2 ATK gap boost

⚙️  v0.5.05  |  Journey_To_Winter_Haven_v_05_06.py
──────────────────────────────────────────────────
* BUG FIX: UnboundLocalError crash on Charged Jagged Rock proc — `import math` inside the Goblin War Blade bleed block caused Python to treat `math` as a local variable throughout all of `player_basic_attack`; removed redundant local import (math already imported at module level line 5)
* BUG FIX: Charged Jagged Rock cap math used stale pre-scaling stats on Hardened enemies — added psychic_base_* re-sync block at end of both apply_level_scaling() and apply_level_scaling_debug_any()
* SKILL SYSTEM: All four skills now capped at max_rank 5 — Power Strike and War Cry reduced from max_rank 10; internal combat functions were already clamped at 5, only display was affected
* SKILL SYSTEM: SKILL_DEFS upgraded — static `desc` string replaced with `rank_descs` dict (rank → description line) and `tier2_name` field on every skill
* SKILL SYSTEM: Added Defence Break to SKILL_DEFS — min_level 3, max_rank 5, upgrade_costs [1,1,2,3,4], tier2_name "Defence Shatter"; added "defence_break": 0 to Hero.skill_ranks init
* SKILL SYSTEM: get_skill_desc(key, hero) helper added — sliding window of 2 ranks ahead; rank 0 shows ranks 1+2, rank 1 shows ranks 2+3, rank 3 shows ranks 4+5, rank 4 shows rank 5 + tier 2 locked hint (name only), rank 5 shows only tier 2 locked hint
* SKILL SYSTEM: show_skill_tree() updated — replaces single static desc line with get_skill_desc() output; each visible rank prefixed with ► NEXT or   THEN; tier 2 hint shows "🔒 [Name] — Locked (Demo)"
* SKILL SYSTEM: War Cry name corrected in SKILL_DEFS ("War CRY" → "War Cry")
* DEFENCE BREAK: DEFENCE_BREAK_STATS table added — rank:(pct, turns) — R1 10%/2T, R2 20%/2T, R3 30%/3T, R4 40%/3T, R5 50%/3T
* DEFENCE BREAK: defence_break_ap_cost(rank) helper — R1-2: 2 AP, R3-4: 3 AP, R5: 4 AP
* DEFENCE BREAK: defence_break(warrior, enemy, chosen_rank) function — takes player turn, costs AP, reduces enemy DEF by pct (min 1), refreshes on reapply, 0 DEF deals 1 true damage instead
* DEFENCE BREAK: _tick_defence_break(enemy) — called each enemy turn, counts down duration, restores base DEF on expiry
* DEFENCE BREAK: _clear_defence_break(enemy) — full reset helper for between-round cleanup
* DEFENCE BREAK: _award_defence_break(warrior) — Fallen Warrior kill reward; rank 0 → unlock rank 1 with narrative; rank 1-4 → free rank up; rank 5 → flavour message only
* DEFENCE BREAK: defence_break_active/turns/pct/base_def fields added to Monster.__init__ so every enemy spawns with clean state
* DEFENCE BREAK: _tick_defence_break wired into enemy turn start (alongside warp_on_cooldown clear)
* DEFENCE BREAK: _award_defence_break wired into both Fallen Warrior kill paths (player-turn kill and DoT kill)
* DEFENCE BREAK: Defence Break option added to skill_menu — shows rank, AP cost, pct reduction and duration; grayed if insufficient AP

⚙️  v0.5.04  |  Journey_To_Winter_Haven_v_05_04.py
──────────────────────────────────────────────────
* Added Goblin Warrior (Tier 3) — 30 HP, 5-9 ATK, DEF 4, XP 33, AP 3; completes goblin ladder (Young Goblin → Goblin Archer → Goblin Warrior)
* Added Hardened Goblin Warrior — handled by existing level scaling system
* Added Savage Slash special move — 33% independent trigger chance after basic attack, costs 1 AP
* Savage Slash: immediate bonus damage = half the basic attack roll rounded down, bypasses defence entirely
* Savage Slash: applies 2 bleed stacks to player — each 3-5 dmg/tick (4-6 hardened), skip=True so they start on player's next turn
* Savage Slash: max 2 simultaneous stacks; hardened variant adds +1 min/max dmg and +1 extra turn duration
* Added warrior_bleed_dots system — list of stack dicts {"dmg_min", "dmg_max", "turns_left", "skip"} tracked separately from Javelina Tusk bleed_turns
* warrior_bleed_dots processed in collect_dot_ticks — variable dmg roll per tick, skip logic, fade message on expiry
* warrior_bleed_dots initialized on Hero.__init__, cleared in reset_between_rounds, displayed in show_combat_stats
* Added Goblin War Blade (weapon drop) — poor: +2 ATK no bleed (blade too dull); normal+: scaling ATK with bleed proc
* Goblin War Blade bleed: damage = half the player attack roll rounded up, min 1; War Cry amplifies naturally via ATK boost
* Goblin War Blade bleed stored as single warrior_bleed_dots stack on enemy — overwrites on reapplication (reopens same wound)
* Goblin War Blade stat table: poor +2/none, normal +2/1T, uncommon +3/2T, rare +4/3T, epic +5/4T, legendary +6/5T, mythril +7/6T
* Added Goblin_Warrior to MONSTER_TYPES (weight 3), debug monster select (entry 17), debug loot menu (entry 17)
* Added GOBLIN_WAR_BLADE_STATS table and make_loot entry for Goblin Warrior

⚙️  v0.5.03  |  Journey_To_Winter_Haven_v_05_03.py
──────────────────────────────────────────────────
* BUG FIX: short_label() NameError — icon variable used in f-string before assignment; RARITY_COLORS dict was defined but lookup line was missing; added icon = RARITY_COLORS.get(self.rarity, "⬜")
* BUG FIX: stat_lines() NameError — lines.append() called before lines was initialised; added lines = [] at top of method
* REFACTOR: Removed duplicate RARITY_COLORS dict defined identically inside both stat_lines and short_label; replaced with single class-level RARITY_ICONS dict shared by all display methods
* BUG FIX: stat_lines() was silently missing paralyze, bleed, acid erosion, max AP bonus, and atk/def debuff procs; all added
* NEW: Equipment.full_detail() method — bordered loot card showing rarity icon, item name, slot, and every stat/proc line; used on drop and on inspect
* NEW: Loot drop display upgraded — both normal kill and DoT kill paths now call full_detail() instead of short_label(); player sees complete stat breakdown immediately on receiving loot
* NEW: Weapon Core loot drop now offers immediate equip choice (y/n) since game ends after Fallen Warrior with no rest phase; equips via equip_item() on yes, stays in bag on no
* BUG FIX: Weapon Core atk_max was assigned stats["atk_min"] instead of stats["atk_max"]; corrected
* BUG FIX: Weapon Core end-game revert logic only checked equipped weapon slot; if player said no to equipping, the revert scene silently skipped; now checks inventory bag as well and always fires the lore moment and removal
* NEW: inventory_menu inspect commands — i# inspects a bag item by number; iweapon/iarmor/iaccessory/itrinket inspects equipped slot; full_detail() shown for all inspects
* NEW: inventory_menu now shows full_detail() card automatically when equipping an item from the bag
* NEW: _stone_usable(hero) helper — returns Waterlogged Stone if equipped and has charges > 0, else None; used by both rest menus
* NEW: Waterlogged Stone use option added to rest_phase — appears dynamically in numbered menu only when stone is equipped with charges; shows live charge count; slots before Continue via dynamic option counter
* NEW: Waterlogged Stone use option added to arena_quarters_interlude — option 14; appears only when stone equipped with charges; handler double-checks _stone_usable before firing
* BUG FIX: Ghost adrenaline between rounds — current_bonus_damage, temp_special, and total_special were never cleared in reset_between_rounds; adrenaline from one fight carried into status display of next; added resets preserving perm_special (permanent level-up baseline)
* NOTE: Berserk intentionally carries between rounds by design — not cleared in reset_between_rounds
* Added Drowned One (Tier 3) — 27 HP, 5-8 ATK, DEF 3, XP 30, AP 3; added to MONSTER_TYPES and debug monster select (entry 16)
* Added Hardened Drowned One — 32 HP, 6-9 ATK, DEF 4, XP 45, AP 3 (handled by existing level scaling)
* Added Psychic Drown special move — Drowned One always basic attacks first, then 33% independent chance to also fire Psychic Drown
* Psychic Drown: each stack adds +1 to ALL special move AP costs (Power Strike, War Cry, First Aid); max 3 stacks; 3-turn duration (4-turn hardened); refreshes on reapplication; stacks do not reset on refresh
* Psychic Drown punishment: if player's max_ap < cheapest rank-1 move after inflation, deal flat true damage — standard: 2/3/4 per stack count; hardened: 3/4/5; uses max_ap as baseline not current AP so active players are not punished for spending AP
* AP cost functions (heal_ap_cost, war_cry_ap_cost, power_strike_ap_cost) updated with optional warrior param — all return base + drown inflation when warrior passed; all call sites updated
* Added get_ap_inflation() and inflated_ap_cost() helpers for future use
* Added check_drown_punishment() — called at start of player turn before action menu if drown stacks active
* Added _clear_psychic_drown() — zeroes all drown fields; called on expiry in collect_dot_ticks and in reset_between_rounds
* Added Waterlogged Stone (trinket) — Drowned One drop; new trinket equipment slot; passively absorbs 1 charge per enemy special move (any enemy, not just Drowned One); player spends turn to release charges and restore AP; charges persist between rounds; AP capped at max_ap+1 on release; player chooses how many charges to release
* Trinket slot stats — poor: 1 charge +1 DEF / normal: 2 charges +1 DEF / uncommon: 3 charges +1 DEF / rare: 4 charges +1 DEF +1 max AP / epic: 5 charges +2 DEF +2 max AP / legendary: 6 charges +3 DEF +3 max AP
* Added trinket equipment slot to Hero.equipment dict, equip_item (applies max_ap_bonus), unequip_item (reverses max_ap_bonus, resets charges)
* Added Equipment fields: max_ap_bonus, stone_max_charges, stone_charges
* Added _stone_absorb_charge() — fires after every enemy special move; adds charge if stone equipped and under cap; prints cap warning if full
* Added use_waterlogged_stone() — player selects charge count to release; restores AP up to max_ap+1; costs player turn; returns False on cancel so turn is not spent
* Combat action menu updated — Stone option appears before Potion when trinket equipped; shows live charge count; all three weapon/accessory scenarios handled
* Inventory menu, show_combat_stats, show_game_stats HUD, debug loot menu all updated to show trinket slot and charge count
* Debug unequip slot list updated to include trinket (slot 4)

⚙️  v0.5.02  |  Journey_To_Winter_Haven_v_05_02.py
──────────────────────────────────────────────────
* Added Flayed One (Tier 3) — 23 HP, 4-6 ATK, DEF 2, 25 XP, 2 AP; added to MONSTER_TYPES (live arena pool) and debug monster select
* Added Hardened Flayed One variant — 28 HP, 5-7 ATK, DEF 3, 38 XP, 3 AP (handled by existing level scaling system)
* Added Psychic Shred special move — Flayed One always basic attacks first, then 33% independent chance to also fire Psychic Shred (does not replace basic attack)
* Psychic Shred: 25% ATK+DEF reduction (30% hardened), 2-turn duration (3-turn hardened), skip-first-tick so debuff activates on player's next action not immediately
* Psychic Shred: refreshes duration on reapplication; stacks to 50%/60% on second hit; hard 90% ceiling on all reductions
* Psychic Shred: max 3 uses per fight (tracked via psychic_shred_uses on enemy); cannot be cleansed by First Aid ranks 1-5
* Psychic Shred: if player has 0 DEF when hit, ATK reduction doubles (50% base / 60% hardened), still capped at 90%
* Added _apply_psychic_debuff_to_stats() — rounding favours the defender: ceil (player takes more loss) vs floor (enemy takes less loss); minimum 1 point reduction guaranteed so Psychic Shred always does something; max_atk floors at min_atk to prevent randint crash
* Added _clear_psychic_debuff() — fully restores base stats, wipes all psychic tracking fields including skip flag; called on expiry and in reset_between_rounds
* Added Charged Jagged Rock accessory (Flayed One drop) — poor: 10% ATK 1T / normal: 10% ATK+DEF 2T / uncommon: 15% ATK+DEF 3T; refreshes on reapplication, does not stack; same rounding rules applied to enemy
* Added Charged Jagged Rock to debug loot menu (entry 15) and monster select map (entry 15, tier 3)
* show_combat_stats() debuff section fully rewritten — now displays all active debuffs with tactical detail: blind turns, paralyze turns + post-paralyze guard state, poison dmg/tick + extra dot stacks, burn stacks + longest duration, acid stacks + DEF loss + current DEF, bleed turns, defence warp with phase label (collapsing/partial/stabilising) and original DEF value, psychic shred with pending tag and base→current ATK/DEF values
* TODO: Triage (First Aid Rank 6+) — cleanse psychic debuffs; follows same skill evolution pattern as Power Strike → Double Strike

⚙️  v0.5.01  |  Journey_To_Winter_Haven_v_05_01.py
──────────────────────────────────────────────────
* TITLE SYSTEM: Added active_title attribute to Hero; titles now have display names via TITLE_DISPLAY dict
* TITLE SYSTEM: award_title() helper handles earning, prompts player to set as active title
* TITLE SYSTEM: Jack of All Trades title added — unlocks when Power Strike, First Aid, and War Cry all reach rank 1; grants +1 HP, +1 ATK (min+max), +1 DEF, +1 AP
* TITLE SYSTEM: check_jack_of_all_trades() fires automatically after every skill upgrade in show_skill_tree
* TITLE SYSTEM: River Warrior now uses award_title() — consistent with new system, removed duplicate max_hp increment
* TITLE SYSTEM: Stat screen reads active_title via TITLE_DISPLAY instead of raw titles set
* TITLE SYSTEM: _switch_title_menu() added — lets player swap active title; hidden in rest menu until 2+ titles owned
* FALLEN WARRIOR: Desperation system added — Defence Warp trigger chance now scales with HP thresholds (10/25/50/75%)
* FALLEN WARRIOR: fallen_warp_should_trigger() replaces flat 33% monster_ai_check for Fallen Warrior specifically
* FALLEN WARRIOR: Guaranteed 1-turn cooldown after Defence Warp fires — player always gets a recovery window
* FALLEN WARRIOR: Cooldown override if HP drops to a new lower threshold mid-cooldown (desperation takes over)
* FALLEN WARRIOR: Desperation flavour text at 0-25% HP threshold; warning message when warp phases begin (tiers 0-2)
* FALLEN WARRIOR: warp_on_cooldown cleared at start of each enemy turn in battle loop


# ────────────────────────────────────────────────────────────
#  v4  SERIES  —  Feature Build Era
# ────────────────────────────────────────────────────────────

⚙️  v4.28  |  Journey_To_Winter_Haven_v_04_28.py
──────────────────────────────────────────────────
* Acid Sac redesigned — poor: 3 dmg/1 turn/no DEF erosion; normal: 3 dmg/2 turns/-1 DEF immediately; uncommon: 4 dmg/2 turns/-2 DEF immediately; DEF restores after 2 turns; reapplying resets clock
* element_erosion added as a proper Equipment parameter; poor carries 0 so behaviour unchanged at poor tier
* Hydra Hatchling acid tick bumped from 2–4 to flat 3–5 per tick (monster should hit harder than its accessory drop)
* All three combat log yes/no prompts now loop with "Incorrect input, please enter y or n." on invalid input
* CHANGELOG.md and DEVLOG.md added to repo — full project history from v0.08 to present

⚙️  v4.27  |  Journey_To_Winter_Haven_v_04_27.py
──────────────────────────────────────────────────
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

⚙️  v4.25–v4.26  |  Journey_To_Winter_Haven_v_04_25/26.py
──────────────────────────────────────────────────
* Acid Sac turn scaling fixed to match Poison and Fire Sac — normal now 2 turns, uncommon 3 turns
* Quarters interlude spend points option hidden if player has no unspent points
* Duplicate combat log option removed from quarters interlude menu
* All monster names standardized to Title Case — Javelina loot table key corrected (was silently not dropping)
* Full audit confirmed all 14 monster loot table keys match their class name fields

⚙️  v4.24  |  Journey_To_Winter_Haven_v_04_24.py
──────────────────────────────────────────────────
* collect_dot_ticks() refactored — all expire/fade messages now collected into fade_msgs list and printed after damage line
* Duplicate dot_math_breakdown calls removed from both player and enemy DOT call sites
* Fallen Warrior HP increased from 53 to 57
* Quarters interlude spend points option added — players can spend unspent stat and skill points pre-championship

⚙️  v4.23  |  Journey_To_Winter_Haven_v_04_23.py
──────────────────────────────────────────────────
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

⚙️  v4.22  |  Journey_To_Winter_Haven_v_04_22.py
──────────────────────────────────────────────────
* Fixed Equipment.__init__ crash on goblin archer loot drop — paralyze_chance and paralyze_turns added as proper parameters with defaults of 0.0 and 0
* apply_turn_stop now sets hero.paralyzed = True when reason is "Paralyzed" — bridges turn_stop system with First Aid cure check
* Paralyzed players with First Aid R4+ now get a choice instead of auto-skipping: use First Aid to cure and act, or Struggle to lose the turn and let paralyze fade naturally next turn
* resolve_player_turn_stop updated to support multi-turn paralyze — chain guard gives a breathe turn but decrements remaining turns instead of wiping, enabling chimera-tier 2+ turn lockdowns; non-paralyze stuns retain original wipe behavior
* reset_between_rounds now clears hero.paralyzed and turn_stop_reason — previously a paralyzed player could carry the flag into the next fight's rest period; also added missing turn_stop_reason clear so no ghost reason string persists between rounds
* paralyzing_shot now accepts paralyze_turns parameter (default 1) — goblin archer unchanged, future enemies (chimera) can pass higher values; message now reflects actual turn count
* Added Young_Chimera hidden boss — spawns with one random move from tier 1/2/3 pools plus a unique chimera_elemental_strike; element (fire/poison/acid/paralyze) also rolls on spawn; tier 5 AI fires at 50% per turn
* Added chimera_fight() wrapper — win grants Chimera Plate Chest (legendary armour part 1); loss triggers divine intervention if player survived 5+ turns, otherwise just a defeat; turn count tracked via enemy.turns_survived written each round
* Added tier 5 branch to monster_ai_check — 50% special move chance per turn
* resolve_player_turn_stop rewritten for true consecutive lockdown on multi-turn paralyze — breathe turn only granted after ALL turns expire
* Added post_paralyze_guard flag — blocks enemy from re-paralysing until player has landed one full free attack after paralyze expires; initialized on Warrior, cleared in reset_between_rounds and at start of player's free action
* paralyzing_shot now checks post_paralyze_guard in addition to turn_stop and turn_stop_chain_guard before applying paralyze
* Added text version of hidden boss
* Nob will now increase one of your ranked skills
* Player can now choose to view combat log on loss; debug menu includes this option
* Level up menu now allows multiple level gains at once; debug mode does not restrict stat point distribution
* Added post_paralyze_guard flag — blocks enemy from re-paralysing until player has landed one full free attack after paralyze expires; initialized on Warrior, cleared in reset_between_rounds and at start of player's free action

⚙️  v4.20.3  |  journey_4_20_3.py
──────────────────────────────────────────────────
* Renamed skill "Heal" to "First Aid" across all menus, prompts, and combat labels
* First Aid max rank reduced from 10 to 5 with matching upgrade costs [1,1,2,3,4]
* Heal percents updated: R1=10%, R2=15%, R3=20%, R4=25%, R5=30%
* First Aid now cures statuses by rank: R2+ clears Blind/Poison, R4+ also clears Paralyze/Burn, R5 also clears Acid
* Death Defier debug option changed from "Activate" to "Grant Skill" — player must manually activate in combat
* Default player name changed from "Adventurer" to "Umbra"
* Fixed gap between HP bar and berserk meter in combat HUD

⚙️  v4.20.2  |  journey_4_20_2.py
──────────────────────────────────────────────────
* Combat HUD redesigned: two-column layout — name/HP bar on left, AP/bonus/berserk/gear on right
* Death Defier now always shows in HUD when active (was hidden if bonus = 0)
* Combat action menu options now display side by side to keep combat log visible
* arena_quarters_interlude (pre-final-boss rest) now has Inventory & Equipment option
* Both rest periods (rest_phase and arena_quarters_interlude) allow equipping between rounds

⚙️  v4.20.1  |  journey_4_20_1.py
──────────────────────────────────────────────────
* Added element_max_dots to Equipment class (default 1, rare+=2, legendary=3)
* Sac stat tables updated: rare=4 turns, epic=5 turns, legendary=6 turns for all sacs
* Poison/Fire/Acid application now respects max_dots — stacks up to cap, then resets oldest
* Multi-dot poison uses separate poison_dots list (independent of poison_active)
* collect_dot_ticks now processes poison_dots list for extra poison ticks
* Elem tags now show stack count: e.g. "Burn stack 2/2! (4 dmg, 4 turns)"
* stat_lines() shows max dots on element line for rare+ sacs
* short_label() now prints each stat on its own line for clean readability

⚙️  v4.19.3  |  journey_4_19_3.py
──────────────────────────────────────────────────
* Fixed item stat description wrapping — each stat now prints on its own line
* element_max_dots added to Equipment class (default 1, rare=2, epic=2, legendary=3)
* Sac tables updated for multi-dot at rare+ rarities
* Fire/Poison/Acid application respects max_dots — stacks up to cap, refreshes oldest at cap
* Multi-dot poison uses separate poison_dots list so single-dot poison_active is untouched
* collect_dot_ticks updated with is_player flag; processes poison_dots for extra ticks
* equip_item() and unequip_item() added — proper equip routing replaces direct assignment
* Goblin Archer added to loot table (Paralyzing Arrow)
* Dire Wolf Pup added to loot table (Dire Wolf Pelt)

⚙️  v4.16  |  Journey_To_Winter_Haven_v_04_16.py
──────────────────────────────────────────────────
* player_basic_attack() split into weapon vs accessory modes via use_accessory parameter
* use_accessory=True: basic roll + elemental effect, no weapon bonus or procs
* use_accessory=False: weapon bonus + procs, no elemental
* Combat menu now routes weapon and accessory attacks through correct mode

⚙️  v4.15  |  Journey_To_Winter_Haven_v_04_15.py
──────────────────────────────────────────────────
* round_num parameter added to battle(), battle_inner(), make_loot(), and roll_rarity()
* Round 1 loot odds updated — better chance of normal/uncommon on first round
* monster_level_for_round() added — stronger variants appear in later rounds

⚙️  v4.14  |  Journey_To_Winter_Haven_v_04_14.py
──────────────────────────────────────────────────
* Wolf Pup loot table entry added (Wolf Pelt — armor)
* Brittle Skeleton loot table entry added (Rusted Sword — weapon)
* Imp loot table entry added (Imp Trident — weapon with proc chance)
* Young Goblin loot table entry added (Goblin Dagger — weapon with blind chance)
* proc_chance and blind_chance added as Equipment parameters

⚙️  v4.12–v4.13  |  Journey_To_Winter_Haven_v_04_12/13.py
──────────────────────────────────────────────────
* Equipment class introduced — weapons, armor, and accessories with rarity scaling
* make_loot() and roll_rarity() added — first loot drop system
* Green Slime, Red Slime, and Hydra Hatchling loot table entries added (Poison Sac, Fire Sac, Acid Sac)
* element_restore added to Equipment for timed DEF recovery on acid items
* POISON_SAC_STATS, FIRE_SAC_STATS, ACID_SAC_STATS stat tables added

⚙️  v4.11  |  Journey_To_Winter_Haven_v_04_11.py
──────────────────────────────────────────────────
* battle() and battle_inner() fully separated — battle() is the wrapper, battle_inner() owns the loop
* collect_dot_ticks() extracted as a standalone function
* player_basic_attack() extracted as a standalone function
* Codebase restructured in preparation for the loot system

⚙️  v0.5.2  |  journey_4_19_2.py
──────────────────────────────────────────────────
* Extended rarity ladder: poor → normal → uncommon → rare → epic → legendary
* All 9 item stat tables now have entries for all 6 rarities
* RARITY_ORDER list added as single source of truth for rarity sequence
* roll_rarity unchanged — rare/epic/legendary not on natural drop table yet
* Debug Give Loot menu now shows all 6 rarities with color icons
* Rarity icons updated in stat_lines() and short_label() for new tiers

⚙️  v0.5.1  |  journey_4_19_1.py
──────────────────────────────────────────────────
* Rebuilt show_game_stats to stacked layout — hero row then enemy row
* Removed side-by-side layout which broke on 65-char phone width
* Removed hardcoded name truncation [:10] and [:16] — full names now used
* wrap() applied to both HP rows so long monster names never spill past WIDTH
* Gear lines now print one per row with wrap() — rarity names fit cleanly
* Separator changed from === to ─── to visually distinguish HUD from content

⚙️  v0.5  |  journey_4_19.py
──────────────────────────────────────────────────
* Rebuilt combat menu to use dynamic slot numbers
* Accessory-only: option 1 is Attack (Accessory Name), Special shifts to 2
* Both equipped: 1) Weapon Attack  2) Accessory Attack (name shown)  3) Special ...
* Rarity word now appears in item names (Poor Fire Sac, Uncommon Wolf Pelt, etc.)
* Player sac DoTs now use sac stats directly, not monster move values
* Poison Sac: flat damage and turns from sac stats, reapply resets timer (no stacking)
* Fire Sac: flat damage per tick from sac stats, single stack, reapply resets timer
* Acid Sac: flat damage tick, single stack, defence restores after element_restore turns
* Monster burn/acid ticks unchanged (still random, still use AP-gated move logic)

⚙️  v0.4
──────────────────────────────────────────────────
* Added Hydra Hatchling and its acid move
* Expanded debug menu with new acid-based modifiers
* Added acid tick damage
* Set hard level cap to 5
* Added animated XP bar
* Fixed potion bag so it only counts as player's turn when potion used
* Expanded potion dictionary — super, mega, full potion, and AP potion
* Adjusted parts of the story
* Allowed monsters to gain levels
* Adjusted player and monster UI
* Restricted player to 1 point in each stat per level until level 5
* Player now gets minimal additional boost with leveling
* Minimal equipment added to game — three categories: weapons, armor, accessories
* Completed all Tier 1 monster loot tables
* Added increased chance for better loot on round 1
* Monster drop rate increases when fighting stronger versions
* Switched to executable — game is now officially named Journey To Winter Haven

⚙️  v0.3
──────────────────────────────────────────────────
* Took combat from 4 to 5 rounds
* Added rest period for full heal and future plot/game mechanics between rounds 4 and 5
* Fixed burn move for fire slime
* Expanded Berserk to two turns with an additional turn if a creature is killed during Berserk
* Adjusted player overheal bar so it doesn't turn completely red when overhealed
* Currently the only move that interferes with Berserk is Paralyze
* Fixed some other minor bugs
* Added a brief scene where player is awarded a stat point and skill point by arena trainer before tournament begins
* Added flags to arena entry points to allow for unique chats with arena trainer
* Added skill points
* Added player level 1 moves unlocked by trainer
* Added a rank system — every move goes to rank 5 currently, takes increased skill points to level up
* Added Power Strike (ranks 1–5)
* Added special move Heal
* Added special move War Cry
* Set up groundwork for future Berserk damage and adrenaline expansion system
* Fixed Power Strike — was using Berserk to bump damage way too high
* Fixed combat log so everything is clearly defined
* Wrapped combat breakdown because it got too long

⚙️  v0.2
──────────────────────────────────────────────────
* Incorporated tier combat system with weights to restrict fights so player isn't overwhelmed
* Player now fights through 4 rounds of combat to win
* Victory is now tied to beating the Fallen Warrior, not essences
* Fixed mistyping that ended game early
* Completed Tier 2 monster lineup and their moves (Dire Wolf Pup, Javelina, Goblin Archer, Noob Ghost)


# ────────────────────────────────────────────────────────────
#  v0  SERIES  —  Early & Pre-Rename Versions
# ────────────────────────────────────────────────────────────

⚙️  v0.1
──────────────────────────────────────────────────
* Minor UI fixes

⚙️  v.14
──────────────────────────────────────────────────
* Added new titles and endings
* Hopefully corrected river path
* Fixed some possible future bugs
* Finished all current Tier 1 monster moves (Imp, Wolf Pup, Brittle Skeleton, Green Slime, Young Goblin)
* Added debug level up menu
* Added Wolf Pup Rider special move: Blind Charge
* Added Javelina and Goblin Archer and their moves
* Added a check so turn takers don't trigger twice in a row
* Arena now will intervene if move stoppers are triggered twice in a row

⚙️  v.13  —  Building Special Moves for Monsters
──────────────────────────────────────────────────
* Added and stabilised Blind
* Added new player move: Death Defier
* Updated potion system and added new types
* Added overheal
* Turned AP into a refreshable resource
* Finally stabilised burn DoT
* Added debug menu that can be easily expanded
* Added monster universal select — M during combat or "monster" in story
* Extended search for torch in story mode

⚙️  v.12  —  Rest Mechanic Between Rounds
──────────────────────────────────────────────────
* Fine-tuned rage mechanic
* Created Berserk mode for rage mechanic
* Tried to clear every bug
* Made story text look better
* Created rest mechanic

⚙️  v.111  —  Rage System & Defence Overhaul
──────────────────────────────────────────────────
* HP-based rage tiers at 75%, 50%, 25%, 10% — tier-based extra damage
* Level-up stat "Rage" permanently increases rage bonus
* Rage flavor messages added, triggered only once per tier
* Attack roll updated to exclude permanent rage (now applied through get_rage_bonus)
* Developer shortcuts added — q: restart, c/combat: jump to arena (via RestartException, QuickCombatException)
* Full block and partial block flavor text added
* Defense-break system for Fallen Warrior using defence_break=True
* GAME_WARRIOR global reference created — removed need to pass warrior through every check()
* Fixed many incorrect warrior references
* Fixed Fallen Warrior attack override
* Added emoji-enhanced stat screen
* Textwrap unified with new safe wrap() function
* Fixed multiple crash bugs from missing args in check() and intro_story_inner

⚙️  v.10  —  Defense System Overhaul
──────────────────────────────────────────────────
* Defense now actually reduces damage
* apply_defence() system created
* Added full block / partial block mechanics
* Introduced flavor text system for blocks
* Fixed bug where defense could go negative
* Added Fallen Hero / Fallen Warrior defense-breaking attack
* Fixed original_defence restoration after battle

⚙️  v.09  —  Combat Stability Pass
──────────────────────────────────────────────────
* Fixed double damage print bug
* Fixed NoneType attacker in defensive messages
* Fixed incorrect alternating turn logic
* Fixed runaway bloodlust stacking bug
* Adjusted monster weights so Fallen Hero appears less often
* Cleaned up battle loop structure
* Improved story text formatting
* Fixed level-up not triggering in older builds
* Added strict alternation between warrior/enemy turns

⚙️  v.08  —  Story System Improvements
──────────────────────────────────────────────────
* Most story segments wrapped with wrap()
* Reformatted intro story spacing and structure
* Unified input check() system
* Cleaned up several deep nested if-blocks
* Added new story branches (Forest Path, Bo encounter)
* Added potion reward for bravery
* Added persuasion check mechanic
* Gameplay flow from story → arena stabilized

⚙️  v.07  —  Fallen Hero Path
──────────────────────────────────────────────────
* Added consequences: stat point or gold
* Added Fallen Hero's defense-break special
* Added essences to victory conditions
* Tournament victory requires 3 essences (later changed)
* Mostly brainstormed/sketched at this stage

⚙️  v.06  —  Monster & Essence System
──────────────────────────────────────────────────
* Monster essence system created
* Inventory for loot items
* Wolf Rider now drops pelt + dual essence
* Unified monster class with proper XP/gold/essence fields
* Random encounter system weighted via random.choices

⚙️  v.05  —  Leveling System
──────────────────────────────────────────────────
* Added XP thresholds — xp_to_lvl scales x1.75
* Level-up bonus menu
* Added AP, Defense, HP, ATK upgrades
* Added achievements and titles
* Added full stat display (show_all_game_stats)

⚙️  v.04  —  Potion System Rework
──────────────────────────────────────────────────
* Added healing, AP, and mana potions
* Simplified potion selection menu
* Added inventory management
* Added potion reward in story branches

⚙️  v.03  —  Combat Improvements
──────────────────────────────────────────────────
* Refactored base classes (Creator, Monster, Hero)
* Standardized attack rolls
* Created battle() and battle_inner() separation
* Added run-away consequences and death messages
* Fixed duplicated damage printing in several places

⚙️  v.02  —  Story Prototype
──────────────────────────────────────────────────
* First draft of intro story
* Cave encounter
* Beastman introduction
* Forked paths (run/submit/escape)
* Basic arena structure established

⚙️  v.01  —  Original Build
──────────────────────────────────────────────────
* Warrior class created
* Basic monster classes
* Barebones attack loop
* Basic HP, XP, gold, inventory
* Text only, no story branching


# ────────────────────────────────────────────────────────────
#  PROTO-BUILDS  —  August–October 2025
# ────────────────────────────────────────────────────────────

⚙️  battle_simulater_pc_update_August62025.py  (590 lines)
──────────────────────────────────────────────────
* Earliest surviving build — where it all started
* Creator base class exists but Skeleton is just pass
* Combat is standalone functions: slime_battle(), skelton_battle(), ghost_battle()
* Global variables track gold, HP, and essence — no class-based state yet
* Comments throughout show active OOP learning in progress
* Slime was famously broken for a very long time
* endings and monster_essence already present as globals — some things never change

⚙️  arena_battler_sept_17_2025.py  (763 lines)
──────────────────────────────────────────────────
* clear_screen(), continue_text(), and check() introduced — still in the game today
* main() function wraps the game loop for the first time
* Tournament intro story text appears — the premise, memory wipe, and freedom
* Gold and essence tracking via globals, textwrap used for the first time

⚙️  arena_battler_October_2_2025.py  (763 lines)
──────────────────────────────────────────────────
* Stable checkpoint — near-identical to September build
* Saved before the bigger architecture push that followed
"""
