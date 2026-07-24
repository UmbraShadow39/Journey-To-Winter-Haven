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
from leaderboard import display_at_end_of_run, show_leaderboard, show_global_leaderboard

# Shared constants, utilities and base classes (version-independent)
from shared import (
    WIDTH,
    SPECIAL_MOVE_NAMES,
    DEFENCE_BREAK_STATS,
    wrap, space, clear_screen, continue_text, show_health,
    hp_bar,
    monster_math_breakdown, monster_deal_damage,
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


# ===============================
# Combat engine — see combat.py
# ===============================
from combat import (
    # Damage calculation
    get_damage_bonuses, bonus_parts_to_text,
    collect_dot_ticks, fmt_part, dot_math_breakdown,
    # Potion/rest/loot
    REST_EVENTS, heal_percent, ap_percent, mana_percent,
    use_potion_menu, rest_phase, offer_loot,
    # Status effects
    apply_turn_stop, resolve_player_turn_stop,
    simple_trainer_reaction_stub, tick_war_cry,
    deactivate_berserk, clear_all_burns, clear_rot,
    init_fatigue, fatigue_threshold_for, roll_fatigue_save,
    clear_all_status_effects, reset_between_rounds,
    blind_damage_multiplier,
    weak_defensive_block, solid_defensive_block,
    strong_defensive_block, full_defensive_block,
    try_death_defier, get_ap_inflation, inflated_ap_cost,
    _stone_absorb_charge, chimera_fury_add, chimera_passive_heal,
    use_consumable_trinket, use_waterlogged_stone,
    _dd_display_as_river, _dd_effective_rank, _dd_ap_cost,
    activate_death_defier,
    # Special moves
    heal_ap_cost, choose_heal_rank_smart, heal,
    war_cry_ap_cost, war_cry,
    power_strike_ap_cost, power_strike_scaled_base,
    choose_power_strike_rank_smart, get_power_strike_bonus, power_strike,
    defence_break_ap_cost, defence_break,
    _tick_defence_break, _clear_defence_break, _award_defence_break,
    # Core combat
    warrior_attack_roll, enemy_attack, bonus_breakdown,
    player_basic_attack, battle, update_defence_warp_after_enemy_turn,
    battle_inner,
)

# Main globals
ARENA_LEVEL_CAP = 5
GAME_WARRIOR = None

# Difficulty settings — set at new game, locked for the run
DIFFICULTY = "warrior"  # "noob", "warrior", "champion"
# v0.7.20 BUG FIX: these five tables used to be duplicated here as literals.
# The copies drifted from combat.py's, and because the injection block below
# pushes the main-file values INTO the combat module, the stale copies here
# silently won — so the v0.7.11 Champion buffs (boss 1.30→1.50, score
# 1.35→1.50, gold 1.25→1.50) never actually took effect in play. They are now
# imported from combat.py, which is the single source of truth: edit them
# there and both modules stay in sync. The injection below becomes a harmless
# self-assignment of the same dict objects.
from combat import (
    DIFFICULTY_MONSTER_MULT,
    DIFFICULTY_SCORE_MULT,
    DIFFICULTY_GOLD_MULT,
    DIFFICULTY_XP_MULT,
    DIFFICULTY_BOSS_MULT,
)
DIFFICULTY_ICON         = {"noob": "🛡️", "warrior": "⚔️", "champion": "👑"}
DIFFICULTY_LABEL        = {"noob": "Noob", "warrior": "Warrior", "champion": "Champion"}

# Combat detail level — set at new game, locked for the run.
# "summary": just the final swing total (default, matches old behavior).
# "full":    per-hand dual-wield breakdown printed on every dual-wield swing,
#            same info debug_mode already exposed, now available without it.
COMBAT_DETAIL = "summary"


# Inject main-resident callbacks into combat module (avoids circular imports)
import combat as _combat_module
_combat_module.spend_points_menu        = lambda hero: spend_points_menu(hero)
_combat_module.has_unspent_points       = lambda hero: has_unspent_points(hero)
_combat_module._stone_usable            = lambda hero: _stone_usable(hero)
_combat_module.debug_menu               = lambda warrior, enemy=None: debug_menu(warrior, enemy)
_combat_module.confirm_continue_if_points_left = lambda hero, prompt='Continue to the next fight?': confirm_continue_if_points_left(hero, prompt)
_combat_module._real_input              = _real_input

import equipment as _equipment_module
_equipment_module._real_input = _real_input
from equipment import inventory_menu, make_loot, equip_item, unequip_item
_combat_module.show_end_summary         = lambda warrior: show_end_summary(warrior)
_combat_module.prompt_play_again        = lambda: prompt_play_again()
_combat_module.intro_story              = lambda warrior: intro_story(warrior)
_combat_module.handle_monster_select_shortcut = lambda raw, **kw: handle_monster_select_shortcut(raw, **kw)
_combat_module.DEBUG                    = DEBUG
_combat_module.GAME_WARRIOR             = GAME_WARRIOR
_combat_module.DIFFICULTY               = DIFFICULTY
_combat_module.DIFFICULTY_BOSS_MULT     = DIFFICULTY_BOSS_MULT
_combat_module.DIFFICULTY_MONSTER_MULT  = DIFFICULTY_MONSTER_MULT
_combat_module.DIFFICULTY_SCORE_MULT    = DIFFICULTY_SCORE_MULT
_combat_module.DIFFICULTY_GOLD_MULT     = DIFFICULTY_GOLD_MULT
_combat_module.DIFFICULTY_XP_MULT       = DIFFICULTY_XP_MULT
_combat_module.COMBAT_DETAIL            = COMBAT_DETAIL

# ===============================
# [Moved to shared.py] clear_screen

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


# [Moved to shared.py] continue_text

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

# ===============================
# Story/narrative — see story.py
# ===============================
from story import (
    get_name_input, intro_story,
    goblin_bookie_payout, nob_interlude_scene, arena_quarters_interlude,
    simple_trainer_reaction, trainer_stat_point_scene,
    ashenveil_prologue, intro_story_inner,
)

# Inject main-resident callbacks into story module
import story as _story_module
_story_module.spend_points_menu = lambda hero: spend_points_menu(hero)
_story_module.show_end_summary  = lambda warrior: show_end_summary(warrior)
_story_module.debug_menu        = lambda warrior, enemy=None: debug_menu(warrior, enemy)
_story_module.check             = lambda prompt, options=None: check(prompt, options)
# story._gw_ref is a mutable list — update [0] to change GAME_WARRIOR in story
# No injection needed; story._set_gw() is called directly when warrior is created
_story_module._try_dev_shortcut = _try_dev_shortcut
_story_module._real_input       = _real_input
# v0.7.18: continue_text() now honors dev shortcuts too — wire the handler
# into shared so "!debug" at a continue prompt opens the menu instead of
# being silently swallowed (the _try_dev_shortcut docstring always claimed
# this worked; now it actually does).
import shared as _shared_module
_shared_module._dev_shortcut_hook = _try_dev_shortcut
_story_module.arena_battle        = lambda warrior, rounds_to_win=5: arena_battle(warrior, rounds_to_win)
_story_module.prompt_play_again   = lambda: prompt_play_again()   # v0.7.11: fix NoneType crash at end of run

# [Moved to combat.py] REST_EVENTS, heal_percent, ap_percent, mana_percent, use_potion_menu

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
                # v0.7.17: also track in base_defence — recalculate_defence()
                # (run after every fight) rebuilds hero.defence from this
                # value, so skipping it here meant this point vanished the
                # moment the next fight ended.
                hero.base_defence = getattr(hero, "base_defence", 0) + 1
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


# [Moved to story.py] goblin_bookie_payout, nob_interlude_scene, arena_quarters_interlude




# ===============================
# Debug tools — see debug.py
# ===============================
from debug import (
    debug_menu, monster_select_menu,
    _debug_ensure_skill_dicts, _debug_skill_editor,
    _debug_title_menu, _debug_loot_menu, _debug_potion_menu,
)

# Inject callbacks into debug module
import debug as _debug_module
_debug_module._real_input        = _real_input
_debug_module.GAME_WARRIOR       = GAME_WARRIOR
_debug_module.DIFFICULTY         = DIFFICULTY
_debug_module.spend_points_menu  = lambda hero: spend_points_menu(hero)
_debug_module.animate_xp_results = lambda *a, **kw: __import__('ui').animate_xp_results(*a, **kw)

# [Moved to debug.py] debug_menu

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
    """Prints final stat snapshot, remaining potions and loot at end of run."""
    print()
    width = 50
    bar = "═" * width
    print(bar)
    print(f"  ⚔️  FINAL STATS — {warrior.name}")
    print(bar)

    # --- Core stats ---
    diff       = getattr(warrior, "difficulty", "warrior")
    diff_icon  = {"noob": "🛡️", "warrior": "⚔️", "champion": "👑", "debug": "🐛"}.get(diff, "⚔️")
    diff_label = {"noob": "Noob", "warrior": "Warrior", "champion": "Champion", "debug": "Debug"}.get(diff, "Warrior")
    print(f"  {diff_icon}  Difficulty  : {diff_label}")
    print(f"  📈 Level      : {warrior.level}")
    print(f"  ❤️  HP         : {warrior.hp}/{warrior.max_hp}")
    print(f"  ⚡ AP         : {warrior.ap}/{warrior.max_ap}")
    print(f"  ⚔️  ATK        : {warrior.min_atk}–{warrior.max_atk}")
    print(f"  🛡️  DEF        : {warrior.defence}")
    print(f"  💰 Gold        : {warrior.gold}g")

    # --- Titles earned ---
    titles     = getattr(warrior, "titles", set())
    fate       = getattr(warrior, "fate_titles", set())
    all_titles = titles | fate
    if all_titles:
        from titles import TITLE_DISPLAY
        title_names = [TITLE_DISPLAY.get(t, t) for t in sorted(all_titles)]
        print(f"  🏅 Titles     : {', '.join(title_names)}")
    else:
        print("  🏅 Titles     : none")

    # --- Skills at final rank ---
    skill_ranks = getattr(warrior, "skill_ranks", {})
    learned = {k: v for k, v in skill_ranks.items() if v > 0}
    if learned:
        skill_parts = []
        for key, rank in sorted(learned.items(), key=lambda x: -x[1]):
            name = SKILL_DEFS.get(key, {}).get("name", key)
            skill_parts.append(f"{name} R{rank}")
        print(f"  🎯 Skills     : {', '.join(skill_parts)}")

    print(bar)
    print()
    print(bar)
    print(f"  END OF RUN SUMMARY — {warrior.name}")
    print(bar)

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


# [Moved to combat.py] offer_loot

# [Moved to debug.py] _debug_title_menu

# [Moved to debug.py] _debug_loot_menu

# [Moved to debug.py] _debug_potion_menu

# [Moved to debug.py] monster_select_menu

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



# [Moved to combat.py] deactivate_berserk through _award_defence_break

class PlayAgainException(Exception):
    """
    Raised by prompt_play_again() when the player chooses to play again.
    Bubbles up through every game-end caller to the __main__ block, which
    catches it and restarts the run with fully reset global state.
    """
    pass


# [Moved to equipment.py] RARITY_ORDER, roll_rarity, _make_weapon_core, make_loot


# [Moved to shared.py] Creator, Monster


# ===============================
# Hero classes — see hero.py
# ===============================
from hero import (
    Hero, Warrior,
    _format_set_bonus_lines, _format_dual_wield_lines,
    SKILL_DEFS,
    get_skill_desc, skill_visible, next_skill_cost,
    show_skill_tree, skill_menu,
    compute_adrenaline_bonus, check_berserk_trigger,
)

def get_tier_for_monster_class(cls) -> int:
    """Figure out tier from MONSTER_TYPES / TIER4_BOSSES (used for debug UI)."""
    for c, w in MONSTER_TYPES:
        if c is cls:
            return weight_to_tier(w)
    for c, _w in TIER4_BOSSES:
        if c is cls:
            return 4
    return 1  # fallback


# [Moved to debug.py] apply_level_scaling_debug_any

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


# [Moved to story.py] simple_trainer_reaction, trainer_stat_point_scene



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
# [Moved to story.py] ashenveil_prologue, intro_story_inner



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


def difficulty_select():
    """
    Ask the player to choose a difficulty before starting a run.
    Returns the chosen difficulty string. Locked in for the full run.
    """
    global DIFFICULTY
    while True:
        clear_screen()
        print()
        print("═" * 50)
        print("       SELECT YOUR DIFFICULTY")
        print("═" * 50)
        print()
        print("   🛡️  [1] Noob    — Easy")
        print("        Reduced enemy stats (20%). 0.75x score & gold.")
        print()
        print("   ⚔️  [2] Warrior    — Normal  (Recommended)")
        print("        Standard challenge. Bosses scaled for a")
        print("        level 5 warrior.")
        print()
        print("   👑  [3] Champion   — Hard  (Experienced players)")
        print("        Stronger enemies and bosses. 1.5x score,")
        print("        1.5x gold. Prove your worth.")
        print()
        choice = input("   Select difficulty: ").strip()
        if choice == "1":
            DIFFICULTY = "noob"
            break
        elif choice == "2":
            DIFFICULTY = "warrior"
            break
        elif choice == "3":
            DIFFICULTY = "champion"
            break
        else:
            print("   Please enter 1, 2, or 3.")
            input("   Press Enter to try again...")

    icon  = DIFFICULTY_ICON[DIFFICULTY]
    label = DIFFICULTY_LABEL[DIFFICULTY]
    print()
    print(f"   {icon} Difficulty set: {label}")
    print()
    input("   Press Enter to begin your journey...")
    return DIFFICULTY


def combat_detail_select():
    """
    Ask the player how much combat math to show on-screen. Locked in for
    the full run, same as difficulty. "Full" surfaces the dual-wield
    main/off-hand breakdown on every dual-wield swing (previously only
    visible with debug_mode on) — everyone else just sees the final total.
    """
    global COMBAT_DETAIL
    while True:
        clear_screen()
        print()
        print("═" * 50)
        print("       COMBAT DETAIL")
        print("═" * 50)
        print()
        print("   [1] Summary   — Just the final damage number (default)")
        print()
        print("   [2] Full breakdown — Show main-hand / off-hand split on")
        print("        every dual-wield swing, plus bonus math.")
        print()
        choice = input("   Select combat detail: ").strip()
        if choice == "1":
            COMBAT_DETAIL = "summary"
            break
        elif choice == "2":
            COMBAT_DETAIL = "full"
            break
        else:
            print("   Please enter 1 or 2.")
            input("   Press Enter to try again...")

    print()
    print(f"   Combat detail set: {'Full breakdown' if COMBAT_DETAIL == 'full' else 'Summary'}")
    print()
    input("   Press Enter to continue...")
    return COMBAT_DETAIL


def main_menu():
    """
    Simple main menu shown on game launch. Loops until the player picks
    'New Game' or 'Quit'. The leaderboard options return here so they
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
        print("   [2] Local Leaderboard")
        print("   [3] Global Leaderboard")
        # v0.7.18: "Learn Basic Python" appears once the player has finished
        # a run. Difficulty-gated lesson unlocks are handled inside the mode.
        try:
            import python_lessons as _pylessons
            _python_unlocked = _pylessons.is_mode_unlocked()
        except Exception:
            _python_unlocked = False
        if _python_unlocked:
            print("   [4] 🐍 Learn Basic Python")
            print("   [5] Quit")
            _quit_key = "5"
        else:
            print("   [4] Quit")
            _quit_key = "4"
        print()
        choice = input("   Select an option: ").strip()

        if choice == "1":
            difficulty_select()
            combat_detail_select()
            # Sync difficulty to all modules that cache it  — v0.7.11
            _combat_module.DIFFICULTY = DIFFICULTY
            _debug_module.DIFFICULTY  = DIFFICULTY
            _combat_module.COMBAT_DETAIL = COMBAT_DETAIL
            return  # caller proceeds to launch the game
        elif choice == "2":
            show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD")
            input("\nPress Enter to return to the main menu...")
        elif choice == "3":
            # v0.7.14: restored — this got dropped from the main menu during
            # the v0.7.13 refactor even though show_global_leaderboard() and
            # the Supabase submission path were both still fully working.
            show_global_leaderboard()
            input("\nPress Enter to return to the main menu...")
        elif _python_unlocked and choice == "4":
            import python_lessons as _pylessons
            _pylessons.python_lessons_menu(_pylessons.unlocked_lesson_count())
        elif choice == _quit_key:
            print()
            print("   Until next time, warrior. ⚔️")
            print()
            sys.exit(0)
        else:
            _valid = "1-5" if _python_unlocked else "1-4"
            print(f"   Please enter {_valid}.")
            input("   Press Enter to try again...")


if __name__ == "__main__":
    # Outer loop wraps the entire game so "play again" can fully restart
    # without relying on os.execv (which fails silently in some environments).
    # Each iteration represents one full playthrough from main menu to ending.
    while True:
        try:
            main_menu()
            GAME_WARRIOR = Warrior()
            GAME_WARRIOR.difficulty = DIFFICULTY
            import story as _s; _s._set_gw(GAME_WARRIOR)
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
    


# ============================================================
# PATCH NOTES — JOURNEY TO WINTER HAVEN
# Full details: CHANGELOG.md / DEVLOG.md
# ============================================================

# ── v0.7 ERA — Modular Refactor & pygame Port Prep ──────────
# v0.7.17  Flayed One debuff now delta-tracked (mid-fight stat gains survive); Skill Rank-Up
#          Potion no longer wipes banked partial SP; base_defence desync fixed in both the
#          Level-Up Menu and Stat Point Potion (was silently erased by the next fight's
#          recalculate_defence); Goblin Shortbow/War Blade merchant tier-pricing bug fixed
#          (were pricing as tier-1); equip routing now warns before parking a weapon in the
#          untrained-Dual-Wielder off-hand penalty slot; Chimera Fury Overload no longer
#          double-kills through a fresh Death Defier save; armor socket counts rebalanced
#          (Poor/Normal 0, Uncommon 1, Rare/Epic 2, Legendary 3, Mythril 4); full pelt-curing
#          + armor-socket-reinforcement system built (raw pelts wearable as-is, Cured
#          versions socketable for +DEF/+HP); Wolf-Hide/Dire Wolf recipes reworked to require
#          Cured Pelts and scale piece stats + gold cost with pelt rarity; new Reinforcement
#          Crystal components (AP/HP/Defence/ATK) with linear per-tier bonuses feeding
#          Hood/Cloak; Champion shop ceiling extended to a real independent 20% Epic chance
#          (mirrors the merchant's epic-weapon-variant roll); crafter stock scarcity —
#          every component independently rolls 75% to appear at all per visit
# v0.7.16  Bar recoloring (red enemy/blue hero, red-flash hero-critical override); bleed-cleanse
#          bug fix (Frostpine Tonic + Cure-All Tonic now actually clear bleed_turns/warrior_bleed_dots);
#          War Cry & Defence Break now deal real damage instead of pure buff/debuff; new hidden
#          capstone Assassin's Strike (Power Strike R5 + Dual Wielder R5, no skill point cost);
#          Power Strike/War Cry/Defence Break now include the off-hand when actively dual-wielding
#          with Dual Wielder Rank 1+ (untrained/rank 0 still main-hand only); adrenaline/Berserk/
#          equipment/War Cry bonus-stacking gap closed on all three plus Assassin's Strike;
#          Assassin's Strike AP cost 4→3 after balance check vs. dual-wielding Power Strike
# v0.7.15  Rich HP/AP bars — new ui_bars.py (hp_line/ap_line/sp_line), color-coded by HP%,
#          wired into all potion HP/AP prints and the post-attack enemy HP display
# v0.7.14  Champion score mult 1.50→1.35; Combat Detail toggle (summary/full dual-wield breakdown);
#          Imp Trident Rare-Mythril rebalanced (Rare no longer duplicates Uncommon); Javelina Tusk
#          sharpening full rework (rarity-scaled cost, +1 rarity tier output, new Mythril+ tier);
#          Chimera turn-skip fairness fix (paralyze/blind 2 hard-locked turns → 1 + a weakened
#          50%-damage follow-up turn, closing a zero-counterplay death chain)
# v0.7.13  Chimera Scale/Tainted Breastplate difficulty scaling; equip_item max_hp fix
#          (negative max_hp no longer drains current HP); crafter can consume equipped
#          components; component sell-back at half price; craft-then-equip prompt;
#          tabbed component/recipe menus; Sharpened Tusk upgrade wired up; recipe stat
#          display; deep-menu 'M' shortcut back to crafter main menu
# v0.7.12  Global leaderboard (Supabase 4 tiers); defence warp arch fix (base_defence + recalculate_defence);
#          Solforged/Voidforged difficulty scaling; debug rarity fix; weapon core 4-way split;
#          Dual Wielder auto-rank; boss mult Noob 0.80→0.90; Patronus HP rebased; end-of-run stat screen
# v0.7.11  Global leaderboard scaffolding; main menu [3] global board; debug warning on first entry
# v0.7.10  debug.py extracted — main 2,543 lines (was 14,601). Refactor complete.
# v0.7.09  Difficulty system: Noob/Warrior/Champion; boss & monster scaling; score multiplier; leaderboard column
# v0.7.08  Equipment param fix (consume_on_use etc.); merchant stats fix; crafter set display; berserk trinket rework; Javelina Tusk → accessory
# v0.7.07  Javelina Tusk → accessory slot; Sharpened Tusk crafter recipe
# v0.7.06  story.py extracted; GAME_WARRIOR mutable container fix; waterfall death paths fixed
# v0.7.05  combat.py extracted — full battle engine, special moves, boss fights
# v0.7.04  ui.py extracted; duplicate shared functions removed from main
# v0.7.03  equipment.py extracted — equip/unequip/inventory/loot
# v0.7.02  Bug fix: 2H→1H swap now prompts instead of hard-blocking
# v0.7.01  hero.py extracted — Hero/Warrior/SKILL_DEFS; pygame port prep begins

# ── v0.6 ERA — Prologue, Architecture & Modularisation ──────
# v0.6.21  Bug fix pass — dev shortcut safety, equipment display, score flags, Primordial Surge exploit
# v0.6.20  Stats visibility — set bonus tracker, dual-wield breakdown, armor socket UI scaffolding
# v0.6.15  Score bug fix, blind unification, tier-3 rebalance, QoL
# v0.6.14  Combat fatigue, hardened nerfs, play-again prompt
# v0.6.13  Progression potions — Skill Rank-Up, Stat Point, Skill Point
# v0.6.12  Patronus polish, Death Defier cinematic, leaderboard & main menu
# v0.6.11  Ring slots, merchant trinket split
# v0.6.09  Merchant shop, title polish, River Spirit conversion fix
# v0.6.08  Score system, Patronus rebalance, The Gooed One
# v0.6.07  Rot system, weapon identity pass, gold overhaul
# v0.6.05  shared.py architecture, input standardisation
# v0.6.04  Monster balance pass, prologue expansion
# v0.6.03  monsters.py extracted, dev shortcut refactor
# v0.6.02  Player name prompt, re-prompt gating
# v0.6.01  Ashenveil prologue, Frostpine Tonic

# ── v5.x ERA — Arena & Systems Overhaul ─────────────────────
# v5.13  Flayed One bug fix, boss balance
# v5.12  Chimera Carapace passive, Charismatic Speaker fix
# v5.11  Chimera move overhaul, title system expansion
# v5.09  Polish & systems pass
# v5.08  Moral hook & final bosses
# v5.07  Patronus build
# v5.06  Chimera overhaul, Defence Break
# v5.05  Bug fixes, skill system upgrade
# v5.04  Goblin Warrior (Tier 3)
# v5.03  Drowned One, Waterlogged Stone, inventory overhaul
# v5.02  Flayed One, Psychic Shred
# v5.01  Title system, Fallen Warrior desperation

# ── v4.x / PROTO ERA ────────────────────────────────────────
# v4.27  Loot system complete, balance tuning
# v4.22  Hidden boss, paralyze overhaul, major bug pass
# v4.21  Class refactor, combat log, module split
# Proto  August–October 2025 — origin builds (590–763 lines)
