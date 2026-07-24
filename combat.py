# combat.py
# Combat engine: damage, status effects, special moves, battle loop
# Extracted from main during v0.7 modular refactor (prep for pygame port)

import random
import math
import time

from ui_bars import hp_line, ap_line, sp_line

from shared import (
    WIDTH, wrap, space, clear_screen, continue_text, show_health,
    WHITE, RED, GREEN, YELLOW, RESET,
    DEFENCE_BREAK_STATS, SPECIAL_MOVE_NAMES,
    RestartException, QuickCombatException,
)
from combat_log import COMBAT_LOG, log, log_attack, log_dot, log_battle_summary, reset_battle_stats, view_combat_log
from gold import calculate_gold_reward, display_gold_earned, award_pending_gold, bookie_encounter, award_gold
from score import record_fight_score, show_run_score
from titles import award_title, award_title_with_buff, check_jack_of_all_trades, switch_title_menu
from equipment import equip_item, make_loot, RARITY_ORDER, inventory_menu, _make_weapon_core, get_main_hand_only_atk, get_off_hand_only_atk
from ui import berserk_meter, xp_bar, cjr_bar, animate_xp_results, refresh_special_state, _cjr_rock, _cjr_absorb, _flayed_charge_tick, _flayed_apply_player_debuff
from hero import SKILL_DEFS, show_skill_tree, skill_menu, compute_adrenaline_bonus, check_berserk_trigger, next_skill_cost
from monsters import (
    monster_ai_check, fallen_warp_should_trigger, Young_Chimera, Patronus,
    _apply_psychic_debuff_to_stats, _clear_psychic_debuff, _clear_psychic_drown,
    psychic_shred, trigger_pressure_feedback, _restore_primordial_stats,
    _restore_patronus_def, _tick_patronus_war_cry, _tick_patronus_def_break,
    _tick_patronus_passive_first_aid, patronus_ai, patronus_war_cry,
    patronus_double_strike, patronus_power_charge, patronus_first_aid,
    patronus_defence_break, CHIMERA_PASSIVE_HEAL_PCT,
)
from crafter import pack_hunter_active, apex_predator_active, get_weapon_socket_procs
from leaderboard import display_at_end_of_run
# --- Runtime callbacks injected by main (avoids circular imports) ---
DIFFICULTY              = "warrior"
DIFFICULTY_BOSS_MULT    = {"noob": 0.80, "warrior": 1.20, "champion": 1.50}  # v0.7.11: champion 1.30 → 1.50
DIFFICULTY_MONSTER_MULT = {"noob": 0.80, "warrior": 1.0,  "champion": 1.20}
DIFFICULTY_SCORE_MULT   = {"noob": 0.75, "warrior": 1.0,  "champion": 1.50}
DIFFICULTY_GOLD_MULT    = {"noob": 0.75, "warrior": 1.0,  "champion": 1.50}  # v0.7.11: champion 1.25 → 1.50
DIFFICULTY_XP_MULT      = {"noob": 0.75, "warrior": 1.0,  "champion": 1.25}
COMBAT_DETAIL           = "summary"  # overwritten by main's injection at load time

def _xp_with_difficulty_mult(base_xp):
    """Scale awarded XP by the current difficulty's XP multiplier."""
    mult = DIFFICULTY_XP_MULT.get(DIFFICULTY, 1.0)
    if mult == 1.0:
        return base_xp
    return max(1, round(base_xp * mult))


# Additional stubs for main-resident functions used in battle context
show_end_summary = None
prompt_play_again = None
intro_story = None
handle_monster_select_shortcut = None
DEBUG = False
GAME_WARRIOR = None

# main.py sets these after importing combat
spend_points_menu = None
has_unspent_points = lambda hero: (getattr(hero, 'stat_points', 0) + getattr(hero, 'skill_points', 0)) > 0
_stone_usable = lambda hero: None
debug_menu = None
confirm_continue_if_points_left = lambda hero, prompt='Continue?': True
_real_input = input



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

    # v0.7.11: Natural berserk halves ALL incoming damage (min 0 if blocked fully).
    # Trinket berserk does NOT reduce damage — artificial aggression, no survival instinct.
    if getattr(defender, "berserk_natural", False) and total > 0:
        total = total // 2

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

    # v0.7.19: Elemental resistance — read live from the player's equipped
    # armor sockets (Poison/Fire/Acid Sacs). Only ever non-zero for the
    # player (monsters don't have .equipment), regardless of the is_player
    # flag passed in — checked via hasattr so it can't misfire on a monster.
    _resist_poison = _resist_fire = _resist_acid = 0.0
    if hasattr(hero, "equipment"):
        from crafter import get_hero_element_resistance
        _resist_poison = get_hero_element_resistance(hero, "poison")
        _resist_fire   = get_hero_element_resistance(hero, "fire")
        _resist_acid   = get_hero_element_resistance(hero, "acid")

    def _apply_resist(amount, resist):
        """Reduce a tick amount by a resistance fraction (0.0-1.0), rounded."""
        if amount > 0 and resist:
            return max(0, round(amount * (1 - resist)))
        return amount

    # ==========================
    # POISON (flat)
    # ==========================
    if getattr(hero, "poison_active", False):
        if getattr(hero, "poison_skip_first_tick", False):
            hero.poison_skip_first_tick = False
        else:
            dmg = int(getattr(hero, "poison_amount", 0))
            dmg = _apply_resist(dmg, _resist_poison)
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
            ddmg = _apply_resist(ddmg, _resist_poison)
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
            tick = _apply_resist(tick, _resist_fire)

            # ✅ record each tick separately (skip a zero-damage line — can
            # happen now that high fire resistance can round a tick to 0)
            if tick > 0:
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

            tick = _apply_resist(tick, _resist_acid)
            if tick > 0:
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

    # Difficulty DoT scaling — applied to total and each part  — v0.7.11
    # Noob: 80% damage (min 1 per part), Champion: 120% damage (min +1 per part)
    import sys
    _main = sys.modules.get("__main__")
    _diff = getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"
    if _diff == "noob" and total > 0:
        scaled_parts = []
        new_total = 0
        for name, amt in parts:
            scaled = max(1, round(amt * 0.80))
            scaled_parts.append((name, scaled))
            new_total += scaled
        parts = scaled_parts
        total = new_total
    elif _diff == "champion" and total > 0:
        scaled_parts = []
        new_total = 0
        for name, amt in parts:
            scaled = max(amt + 1, round(amt * 1.20))
            scaled_parts.append((name, scaled))
            new_total += scaled
        parts = scaled_parts
        total = new_total

    # v0.7.11: Natural berserk halves DoT damage too — same survival instinct
    if getattr(hero, "berserk_natural", False) and total > 0:
        halved_parts = [(name, max(0, amt // 2)) for name, amt in parts]
        parts  = halved_parts
        total  = sum(amt for _, amt in parts)

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
# [ARENA_LEVEL_CAP and GAME_WARRIOR remain in main — global game state]


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
        print(hp_line(hero.name, hero.hp, hero.max_hp, icon="\U0001F49B"))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "super_potion":  # 50% heal
        heal_percent(hero, 0.50)
        print(hp_line(hero.name, hero.hp, hero.max_hp, icon="\U0001F49B"))
        continue_text()
        space()
        return "bonus" if is_bonus else True
    
    elif potion_type == "mega_potion":
        heal_percent(hero, 0.75)
        print(hp_line(hero.name, hero.hp, hero.max_hp, icon="\U0001F49B"))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "full_potion":
        heal_percent(hero, 1.00)
        print(hp_line(hero.name, hero.hp, hero.max_hp, icon="\U0001F49B"))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "ap":
        recovered = ap_percent(hero, 0.25)
        print(f"\n⚡ You drink an AP potion and recover {recovered} AP!")
        print(ap_line(hero.ap, hero.max_ap))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "super_ap":
        recovered = ap_percent(hero, 0.50)
        print(f"\n⚡ You drink a Super AP potion and recover {recovered} AP!")
        print(ap_line(hero.ap, hero.max_ap))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "mega_ap":
        recovered = ap_percent(hero, 0.75)
        print(f"\n⚡ You drink a Mega AP potion and recover {recovered} AP!")
        print(ap_line(hero.ap, hero.max_ap))
        continue_text()
        space()
        return "bonus" if is_bonus else True

    elif potion_type == "full_ap":
        recovered = ap_percent(hero, 1.00)
        print(f"\n⚡ You drink a Full AP potion and recover {recovered} AP!")
        print(ap_line(hero.ap, hero.max_ap))
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
    # Removes: poison, burn/fire stacks, acid stacks, paralysis, blindness, bleed
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
        # v0.7.x BUG FIX: bleed was missing from Cure-All's clear list too —
        # same omission as Frostpine. Covers both regular bleed_turns and
        # Goblin War Blade-style stacked warrior_bleed_dots.
        if getattr(hero, "bleed_turns", 0) > 0 or getattr(hero, "warrior_bleed_dots", []):
            hero.bleed_turns = 0
            hero.bleed_dmg_min = 0
            hero.bleed_dmg_max = 0
            hero.warrior_bleed_dots = []
            cleared.append("bleed")

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
        print(hp_line(hero.name, hero.hp, hero.max_hp, icon="💛"))
        print(ap_line(hero.ap, hero.max_ap))
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
        # v0.7.x BUG FIX: bleed was missing from the "clear all status" block —
        # Frostpine's own comment/design says it clears everything, but
        # bleed_turns and warrior_bleed_dots were never reset here.
        hero.bleed_turns = 0
        hero.bleed_dmg_min = 0
        hero.bleed_dmg_max = 0
        hero.warrior_bleed_dots = []
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
        # v0.7.17: leave hero.skill_progress[chosen_key] untouched — any SP
        # already banked toward this skill wasn't spent by the potion, so it
        # carries forward as partial progress toward the NEW next rank.
        print(f"\n✨ {SKILL_DEFS[chosen_key]['name']} advances to Rank {hero.skill_ranks[chosen_key]}!")
        carried = hero.skill_progress.get(chosen_key, 0)
        if carried > 0:
            new_cost = next_skill_cost(hero, chosen_key)
            if new_cost:
                print(f"   ({carried} SP already banked carries forward: {carried}/{new_cost} toward the next rank.)")
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
                # v0.7.17: also track in base_defence — see level_up_menu fix,
                # same reasoning: recalculate_defence() would otherwise wipe
                # this point after the very next fight.
                hero.base_defence = getattr(hero, "base_defence", 0) + 1
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
    print(ap_line(hero.ap, hero.max_ap))

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




def deactivate_berserk(hero):
    hero.berserk_active   = False
    hero.berserk_bonus    = 0
    hero.berserk_turns    = 0
    hero.berserk_pending  = False
    hero.berserk_natural  = False   # v0.7.11: clear damage reduction flag

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

    # v0.7.12: recalculate defence from scratch after warp — replaces the
    # broken delta-restore that failed with stacked title/gear bonuses.
    try:
        from equipment import recalculate_defence
        recalculate_defence(hero)
    except Exception:
        # Fallback: at least clear the warp attributes so they don't persist
        for attr in ("defence_warp_phase", "defence_warp_original_defence",
                     "defence_warp_snapshot"):
            if hasattr(hero, attr):
                delattr(hero, attr)

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
    # v0.7.12: recalculate from scratch — replaces broken delta restore.
    try:
        from equipment import recalculate_defence
        recalculate_defence(hero)
    except Exception:
        for attr in ("defence_warp_phase", "defence_warp_original_defence",
                     "defence_warp_snapshot"):
            if hasattr(hero, attr):
                delattr(hero, attr)

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
        # Restore defence reduced by Patronus Defence Break
        _restore_patronus_def(hero)
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

    # --- Flayed One debuff cleanup — adds penalty back so mid-fight stat gains are kept ---
    if hasattr(hero, "flayed_atk_penalty"):
        hero.min_atk += hero.flayed_atk_penalty
        hero.max_atk += hero.flayed_atk_penalty
        hero.defence += hero.flayed_def_penalty
        del hero.flayed_atk_penalty
        del hero.flayed_def_penalty
    if hasattr(hero, "flayed_charges_applied"):
        del hero.flayed_charges_applied

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


def chimera_weakened_multiplier(hero):
    """
    v0.7.16: Chimera-exclusive follow-up to its shortened paralyze/blind.
    Chimera's turn-skippers were reduced from 2 hard-locked turns to 1 (the
    "Arena intervenes" consecutive-skip guard is disabled for this fight
    specifically, so 2 full skips back-to-back with no counterplay was
    getting players killed by stacked poison + missed heals-worth of
    damage, not skill). In place of the second hard skip, the player gets
    ONE turn where they can act but at half damage — still a real cost,
    but never a second turn with zero agency.

    Consumed on read: set chimera_weakened_turns = 1 when the skip turn
    resolves, this function eats it on the very next damage roll.
    """
    if getattr(hero, "chimera_weakened_turns", 0) > 0:
        hero.chimera_weakened_turns -= 1
        return 0.5
    return 1.0




# [Moved to shared.py] space, wrap


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

        # v0.7.11: Clear all DoTs and status effects on survival.
        # Cheating death closes wounds and breaks all afflictions — River Spirit
        # and Death Defier follow identical rules.
        # --- DoTs ---
        hero.poison_active      = False
        hero.poison_turns       = 0
        hero.poison_dots        = []
        hero.burns              = []
        hero.fire_stacks        = 0
        hero.acid_stacks        = []
        hero.bleed_turns        = 0
        hero.warrior_bleed_dots = []
        # --- Acid defence loss (intentionally kept — clears at end of combat anyway) ---
        # --- Paralysis ---
        hero.turn_stop          = False
        hero.paralyze_turns     = 0
        # --- Blind ---
        hero.blind              = False
        hero.blind_turns        = 0
        # --- Psychic debuff ---
        if getattr(hero, "psychic_debuff_turns", 0) > 0:
            _clear_psychic_debuff(hero)
        # --- Psychic drown ---
        if getattr(hero, "drown_turns", 0) > 0:
            _clear_psychic_drown(hero)
        # --- Fatigue DEF loss ---
        if getattr(hero, "fatigue_def_loss", 0) > 0:
            hero.defence += hero.fatigue_def_loss
            hero.fatigue_def_loss = 0

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
    Heals Chimera for 10% of its max HP on Warrior, 15% on Champion.
    Uses CHIMERA_PASSIVE_HEAL_PCT on Champion so it doesn't share the
    HEAL_PERCENTS_ENEMY rank table with Patronus.  — v0.7.11
    """
    if enemy.name != "Young Chimera":
        return
    import sys
    _main = sys.modules.get("__main__")
    _diff = getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"
    heal_pct    = CHIMERA_PASSIVE_HEAL_PCT if _diff == "champion" else 0.10
    heal_amount = max(1, int(enemy.max_hp * heal_pct))
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
        turns = getattr(trinket, "berserk_turns", 2)
        turn_str = f"{turns} turn{'s' if turns > 1 else ''}"
        print(wrap(f"You crush the {trinket.name} in your fist. Shards bite your palm — "
                   "and the pain wakes something hungry behind your eyes."))
        print(f"🩸🔥 BERSERK MODE ACTIVATED! ({turn_str})")
        warrior.berserk_active = True
        warrior.berserk_bonus  = 6 + getattr(warrior, "max_rage", 0)
        # v0.7.08: berserk_turns now comes from trinket rarity (1-4 turns)
        warrior.berserk_turns  = getattr(trinket, "berserk_turns", 2)
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

def war_cry(hero, enemy, chosen_rank=None):
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
    _, main_hand_max_atk = get_main_hand_only_atk(hero)  # Session 19: don't compound with Dual Wielder
    bonus = max(1, math.ceil(main_hand_max_atk * pct))

    hero.ap -= cost
    trigger_pressure_feedback(hero, enemy)

    # v0.7.x: War Cry no longer just buffs with no damage — it lands a real
    # strike now too. Base roll includes the off-hand when dual-wielding
    # (warrior_skill_base_roll), and — same as a normal attack or Power
    # Strike — picks up adrenaline/Berserk/equipment/an already-running
    # War Cry buff as a flat hit_bonus BEFORE this cast overwrites that
    # buff below, so a recast still benefits from the old buff one last time.
    base_roll = warrior_skill_base_roll(hero)
    hit_bonus, hit_parts = get_damage_bonuses(hero, "basic attack")
    hit_parts_txt = bonus_parts_to_text(hit_parts)
    roll_total = base_roll + hit_bonus
    # Rank% applies only to the weapon roll, not to adrenaline/Berserk/etc —
    # same split Power Strike uses between its "hit" and "scaling" portions.
    strike_bonus = max(1, math.ceil(base_roll * pct))
    total_raw = roll_total + strike_bonus

    raw_for_defence = total_raw
    if getattr(hero, "blind_turns", 0) > 0:
        mult = blind_damage_multiplier(hero)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"👁️ Blinded! War Cry hits at {int(mult * 100)}% power.")
    if getattr(hero, "chimera_weakened_turns", 0) > 0:
        mult = chimera_weakened_multiplier(hero)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"😮‍💨 Still shaking it off! War Cry hits at {int(mult * 100)}% power.")

    final = enemy.apply_defence(raw_for_defence, attacker=hero)
    enemy.hp = max(0, enemy.hp - final)
    blocked = raw_for_defence - final

    # Re-cast friendly: overwrite bonus & reset duration
    hero.war_cry_bonus = bonus
    hero.war_cry_turns = turns
    hero.war_cry_skip_first_tick = True

    print()
    parts = [f"Roll {base_roll}"] + hit_parts_txt + [f"War Cry Strike {strike_bonus}"]
    line = (f"🗣️ You unleash a WAR CRY and strike {enemy.display_name} for {final} damage! ("
            + " + ".join(parts) + ")")
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))
    print(wrap(
        f"(Rank {chosen_rank}, Cost {cost} AP) "
        f"Your attacks surge with power: +{bonus} to attack rolls for {turns} turns. "
        f"({int(pct * 100)}% of ATK)"
    ))
    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")

    log_attack(hero.name, enemy.display_name, total_raw, final, blocked,
               effect_tag=f"[War Cry Rank {chosen_rank}]",
               is_player=True, is_special=True)

    return True



def _power_strike_dual_wield_active(warrior) -> bool:
    """
    True exactly when Power Strike's AP surcharge applies — the identical
    condition under which warrior_skill_base_roll() actually sums BOTH
    weapons instead of main-hand only (see that function for the full
    reasoning). Kept as its own cheap check so power_strike_ap_cost can
    test it before any combat math runs.
    """
    main = warrior.equipment.get("main_hand")
    off  = warrior.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    dw_rank = warrior.skill_ranks.get("dual_wielder", 0)
    return _is_weapon(main) and _is_weapon(off) and dw_rank > 0


def power_strike_ap_cost(rank: int, warrior=None) -> int:
    # R1-2: 1 AP, R3-4: 2 AP, R5: 3 AP (+ drown inflation)
    base = 1 if rank <= 2 else (2 if rank <= 4 else 3)
    # v0.7.19: Nathan's call. Power Strike's base_roll sums BOTH weapons
    # when dual-wielding (warrior_skill_base_roll) — and unlike War Cry
    # (its buff is main-hand only, "don't compound with Dual Wielder") or
    # Defence Break (its % reduction is a fixed per-rank table untouched
    # by dual-wield), Power Strike's ENTIRE output — hit and scaling both —
    # rides that inflated roll with nothing held back. So dual-wielders pay
    # a 50%-rounded-up AP surcharge here, gated on the exact condition that
    # actually causes the inflation (two weapons + Dual Wielder rank 1+) —
    # a dual-wield setup that hasn't trained the skill gets no bonus roll,
    # so it pays no surcharge either.
    if warrior is not None and _power_strike_dual_wield_active(warrior):
        base = math.ceil(base * 1.5)
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
        scaled = (base_roll * 6) // 5        # 120% roll (rank 5+) — v0.7.20: was 100%

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

    base_roll = warrior_skill_base_roll(warrior)  # v0.7.x: includes off-hand when dual-wielding

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
    if getattr(warrior, "chimera_weakened_turns", 0) > 0:
        mult = chimera_weakened_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"😮‍💨 Still shaking it off! Power Strike hits at {int(mult * 100)}% power.")

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

# DEFENCE_BREAK_STATS is imported from shared.py (single source of truth).

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

    Reduces enemy DEF by a percentage for a number of turns, then strikes
    through the freshly-exposed gap with a main-hand attack roll (v0.7.x —
    previously this only dealt damage in the corner case of DEF hitting 0;
    now it always lands a hit, calculated against the newly-lowered DEF).
    Takes effect immediately (turn 0) then lasts for full combat rounds.
    Refreshes if used again while active — does not stack.
    If DEF is fully broken to 0, still adds +1 true damage on top.
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
    trigger_pressure_feedback(warrior, enemy)
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
    # v0.7.x: Strike through the newly-exposed gap. Base roll includes the
    # off-hand when dual-wielding (warrior_skill_base_roll), applied against
    # the FRESH (already-reduced) defence. Also now picks up adrenaline/
    # Berserk/equipment/War Cry as a flat hit_bonus, same as any other attack.
    # -----------------------------------------------
    base_roll = warrior_skill_base_roll(warrior)
    hit_bonus, hit_parts = get_damage_bonuses(warrior, "basic attack")
    hit_parts_txt = bonus_parts_to_text(hit_parts)
    total_raw = base_roll + hit_bonus

    raw_for_defence = total_raw
    if getattr(warrior, "blind_turns", 0) > 0:
        mult = blind_damage_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"👁️ Blinded! Defence Break hits at {int(mult * 100)}% power.")
    if getattr(warrior, "chimera_weakened_turns", 0) > 0:
        mult = chimera_weakened_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"😮‍💨 Still shaking it off! Defence Break hits at {int(mult * 100)}% power.")

    final = enemy.apply_defence(raw_for_defence, attacker=warrior)
    enemy.hp = max(0, enemy.hp - final)
    blocked = raw_for_defence - final

    # -----------------------------------------------
    # Fully eroded OR naturally 0 DEF — still adds +1 true damage on top
    # -----------------------------------------------
    bonus_true = 0
    if new_def == 0:
        bonus_true = 1
        enemy.hp = max(0, enemy.hp - bonus_true)
        if base_def == 0:
            gap_line = f"{enemy.display_name} has no armour — the strike finds a gap!"
        else:
            gap_line = (f"{enemy.display_name}'s guard is shattered! "
                        f"DEF {base_def} → 0  (-{reduction}, {turns} turns)")
    else:
        gap_line = (f"{enemy.display_name}'s guard crumbles! "
                    f"DEF {base_def} → {new_def}  (-{reduction}, {turns} turns)")

    print(wrap(f"⚔️ Defence Break! (Rank {chosen_rank}, Cost {ap_cost} AP)\n{gap_line}"))

    total_final = final + bonus_true
    parts = [f"Roll {base_roll}"] + hit_parts_txt
    line = f"You strike through the opening for {total_final} damage! (" + " + ".join(parts)
    if bonus_true:
        line += f" + {bonus_true} true dmg"
    line += ")"
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))

    log_attack(warrior.name, enemy.display_name, total_raw, total_final, blocked,
               effect_tag=f"[Defence Break Rank {chosen_rank}]",
               is_player=True, is_special=True)

    show_health(warrior)
    return True


# ===============================
# ASSASSIN'S STRIKE — hidden capstone combo
# ===============================

ASSASSIN_STRIKE_AP_COST     = 3
ASSASSIN_STRIKE_BONUS_PCT   = 0.75   # fusion bonus on the combined main+off roll
ASSASSIN_STRIKE_PROC_CHANCE = 0.75   # EACH weapon's own proc chance on this move


def assassins_strike_ap_cost(warrior):
    return ASSASSIN_STRIKE_AP_COST + get_ap_inflation(warrior)


def assassins_strike_available(warrior):
    """
    True once the player has BOTH Power Strike Rank 5 and Dual Wielder
    Rank 5, while actively dual-wielding two weapons. Not a separately
    learned skill — it's a fusion unlocked by maxing two others.
    """
    if warrior.skill_ranks.get("power_strike", 0) < 5:
        return False
    if warrior.skill_ranks.get("dual_wielder", 0) < 5:
        return False
    main = warrior.equipment.get("main_hand")
    off  = warrior.equipment.get("off_hand")
    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"
    return _is_weapon(main) and _is_weapon(off)


def assassins_strike(warrior, enemy):
    """
    Assassin's Strike — hidden capstone combo move.

    Both blades swing together as one attack: main-hand and off-hand rolls
    are summed using their own ATK ranges (no Dual Wielder passive % baked
    in here — same "don't compound" rule Power Strike already follows for
    its own roll), then the combined total gets a flat +75% fusion bonus.

    Each weapon independently rolls its OWN 75% chance to fire its on-hit
    procs (poison, bleed, blind, rot, etc.) — replacing main-hand's normal
    guaranteed proc and off-hand's normal 50%-at-rank-5 proc chance for
    this move only.
    """
    if not assassins_strike_available(warrior):
        print("Assassin's Strike requires Power Strike Rank 5, Dual Wielder Rank 5, "
              "and two weapons equipped.")
        return False

    ap_cost = assassins_strike_ap_cost(warrior)
    if warrior.ap < ap_cost:
        print(f"Not enough AP for Assassin's Strike. (Need {ap_cost}, have {warrior.ap})")
        return False

    warrior.ap -= ap_cost
    trigger_pressure_feedback(warrior, enemy)

    main = warrior.equipment.get("main_hand")
    off  = warrior.equipment.get("off_hand")
    main_min, main_max = get_main_hand_only_atk(warrior)
    off_min, off_max   = get_off_hand_only_atk(warrior)
    main_roll = random.randint(main_min, main_max) if main_max >= main_min else main_min
    off_roll  = random.randint(off_min, off_max) if off_max >= off_min else off_min
    combined  = main_roll + off_roll

    # Same flat hit_bonus every other attack gets (adrenaline/Berserk/
    # equipment/War Cry) — applied AFTER the fusion %, not multiplied by
    # it, same split Power Strike uses between its "hit" and "scaling".
    hit_bonus, hit_parts = get_damage_bonuses(warrior, "basic attack")
    hit_parts_txt = bonus_parts_to_text(hit_parts)

    bonus     = max(1, math.ceil(combined * ASSASSIN_STRIKE_BONUS_PCT))
    total_raw = combined + hit_bonus + bonus

    raw_for_defence = total_raw
    if getattr(warrior, "blind_turns", 0) > 0:
        mult = blind_damage_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"👁️ Blinded! Assassin's Strike hits at {int(mult * 100)}% power.")
    if getattr(warrior, "chimera_weakened_turns", 0) > 0:
        mult = chimera_weakened_multiplier(warrior)
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"😮‍💨 Still shaking it off! Assassin's Strike hits at {int(mult * 100)}% power.")

    final = enemy.apply_defence(raw_for_defence, attacker=warrior)
    enemy.hp = max(0, enemy.hp - final)
    blocked = raw_for_defence - final

    print()
    parts = [f"Main {main_roll}", f"Off {off_roll}"] + hit_parts_txt + [
        f"{bonus} fusion bonus [{int(ASSASSIN_STRIKE_BONUS_PCT * 100)}%]"
    ]
    line = (f"🗡️🗡️ ASSASSIN'S STRIKE! (Cost {ap_cost} AP)\n"
            f"Both blades flash as one — you cut {enemy.display_name} for {final} damage! ("
            + " + ".join(parts) + ")")
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))

    # Each weapon independently gets its own 75% proc chance on this move
    if final > 0 and enemy.is_alive():
        if random.random() < ASSASSIN_STRIKE_PROC_CHANCE:
            _fire_weapon_native_procs(warrior, main, enemy, final)
        else:
            print("   (Main-hand's edge finds no purchase this time.)")
        if random.random() < ASSASSIN_STRIKE_PROC_CHANCE:
            _fire_weapon_native_procs(warrior, off, enemy, final)
        else:
            print("   (Off-hand's edge finds no purchase this time.)")

    log_attack(warrior.name, enemy.display_name, total_raw, final, blocked,
               effect_tag="[Assassin's Strike]",
               is_player=True, is_special=True)

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



# [Moved to shared.py] RestartException, QuickCombatException, GameOverException, Equipment



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


def warrior_main_hand_attack_roll(warrior):
    """
    Session 19: Power Strike and War Cry use this instead of
    warrior_attack_roll(). Same roll, same Pack Hunter/Apex Predator set
    bonus — the only difference is the min/max ATK range comes from
    get_main_hand_only_atk(), which strips out Dual Wielder's bonuses so
    these two skills don't compound on top of an already-inflated basic
    attack stat. See get_main_hand_only_atk() in equipment.py for why.
    """
    main_min, main_max = get_main_hand_only_atk(warrior)
    roll = random.randint(main_min, main_max)
    try:
        from crafter import pack_hunter_active, apex_predator_active
        if pack_hunter_active(warrior) or apex_predator_active(warrior):
            roll = int(round(roll * 1.10))
    except ImportError:
        pass
    return roll


# Session 19: rank 2-5 ATK% applied to the summed main+off total in
# warrior_dual_wield_attack_roll() below — single source of truth.
DUAL_WIELDER_ATK_PCT = {2: 0.10, 3: 0.15, 4: 0.20, 5: 0.25}


def warrior_dual_wield_attack_roll(warrior):
    """
    Session 19 REWORK: dual-wielding basic attacks now roll main-hand and
    off-hand INDEPENDENTLY and sum them, instead of pooling both weapons'
    ATK into one shared min/max range (the old v0.6.18-v0.7.12 model).

    - Rank 0 (untrained): off-hand's own roll is halved before summing.
    - Rank 1+: off-hand rolls at full strength.
    - Rank 2-5: the ATK% bonus applies to the SUMMED total (main + off),
      not to either roll individually — a dual wielder's % bonus is meant
      to represent overall combat mastery, not favor one hand over the other.
    - Rank 5's "off-hand also procs" 50% chance is handled separately in
      player_basic_attack's weapon-proc block, not here — this function
      only returns the damage number.

    Falls back to the normal single-roll warrior_attack_roll() when not
    actually dual-wielding (single weapon, weapon+shield, accessory, etc.)
    — safe to call unconditionally from player_basic_attack.
    """
    main = warrior.equipment.get("main_hand")
    off  = warrior.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    if not (_is_weapon(main) and _is_weapon(off)):
        return warrior_attack_roll(warrior)

    main_min, main_max = get_main_hand_only_atk(warrior)
    off_min, off_max = get_off_hand_only_atk(warrior)

    main_roll = random.randint(main_min, main_max) if main_max >= main_min else main_min
    off_roll  = random.randint(off_min, off_max) if off_max >= off_min else off_min

    dw_rank = warrior.skill_ranks.get("dual_wielder", 0)
    if dw_rank == 0:
        off_roll = off_roll // 2  # untrained penalty, now applied per-roll

    total = main_roll + off_roll

    pct = DUAL_WIELDER_ATK_PCT.get(dw_rank, 0.0)
    pre_pct_total = total
    if pct:
        total = math.ceil(total * (1 + pct))

    # Pack Hunter / Apex Predator — same basic-attack set bonus as the
    # single-roll path, applied once to the combined total.
    pre_set_bonus_total = total
    try:
        from crafter import pack_hunter_active, apex_predator_active
        if pack_hunter_active(warrior) or apex_predator_active(warrior):
            total = int(round(total * 1.10))
    except ImportError:
        pass

    total = max(1, total)

    # Debug troubleshooting: stash the per-hand breakdown so
    # player_basic_attack can report it without re-deriving the math.
    # Purely additive — does not affect the returned total in any way.
    warrior._last_dw_breakdown = {
        "main_roll": main_roll,
        "off_roll_applied": off_roll,
        "dw_rank": dw_rank,
        "untrained_halved": dw_rank == 0,
        "pre_pct_total": pre_pct_total,
        "pct_applied": pct,
        "pre_set_bonus_total": pre_set_bonus_total,
        "final_total": total,
    }

    return total


def warrior_skill_base_roll(warrior):
    """
    v0.7.x: shared base roll for Power Strike, War Cry, and Defence Break.

    Dual Wielder is a heavy investment (5 skill points + two weapons
    equipped) — these skills used to ignore the off-hand entirely and
    only roll main-hand, meaning a dual-wielder's second weapon
    contributed literally nothing when using them. That's fixed here,
    but ONLY for players who've actually trained the skill:

    - Two weapons equipped AND Dual Wielder Rank 1+: roll main-hand AND
      off-hand independently and sum them. Deliberately does NOT bake in
      the passive Dual Wielder rank 2-5 ATK% here — that stays reserved
      for normal basic attacks so it doesn't compound with the skill's
      own rank bonus, which now scales off this larger combined total.
    - Two weapons equipped but Dual Wielder Rank 0 (untrained): the
      player isn't proficient enough to use the off-hand weapon in a
      focused strike like this — main-hand roll only, off-hand
      contributes nothing. Same as if only one weapon were equipped.
    - Single weapon (or weapon+shield/accessory): unchanged, main-hand
      roll only — identical to the old behavior.
    """
    main = warrior.equipment.get("main_hand")
    off  = warrior.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    dw_rank = warrior.skill_ranks.get("dual_wielder", 0)

    if not (_is_weapon(main) and _is_weapon(off)) or dw_rank == 0:
        roll = warrior_main_hand_attack_roll(warrior)
        # v0.7.20: Brawl Master 20% ATK multiplier (single-weapon path)
        bm_mult = getattr(warrior, "brawl_master_atk_mult", 1.0)
        if bm_mult != 1.0:
            roll = max(1, int(roll * bm_mult))
        return roll

    main_min, main_max = get_main_hand_only_atk(warrior)
    off_min, off_max = get_off_hand_only_atk(warrior)
    main_roll = random.randint(main_min, main_max) if main_max >= main_min else main_min
    off_roll  = random.randint(off_min, off_max) if off_max >= off_min else off_min

    total = main_roll + off_roll

    # Pack Hunter / Apex Predator set bonus — same as normal dual-wield attacks
    try:
        from crafter import pack_hunter_active, apex_predator_active
        if pack_hunter_active(warrior) or apex_predator_active(warrior):
            total = int(round(total * 1.10))
    except ImportError:
        pass

    warrior._last_skill_dw_breakdown = {
        "main_roll": main_roll,
        "off_roll_applied": off_roll,
        "dw_rank": dw_rank,
        "untrained_halved": False,
    }
    total = max(1, total)

    # v0.7.20 (Nathan's call): Brawl Master — 20% permanent ATK multiplier.
    # Applied to the combined base roll so it scales with gear/stats/dual-wield.
    bm_mult = getattr(warrior, "brawl_master_atk_mult", 1.0)
    if bm_mult != 1.0:
        total = max(1, int(total * bm_mult))

    return total





def _soul_pendant_armor_heal(warrior):
    """
    v0.7.20 (Nathan's call): Soul Pendant socketed into armor heals the
    player when they take a direct hit — the defensive mirror of weapon-
    socket drain. Heal amount comes from the pendant's own drain_heal stats
    at 75% socket power, similar to Dire Wolf Pup's devouring bite heal.

    Only the first pendant in armor sockets procs (no double-heal).
    """
    armor = warrior.equipment.get("armor")
    if armor is None:
        return
    sockets = getattr(armor, "sockets", None)
    if not sockets:
        return

    from crafter import SOCKET_POWER_RATIO
    from equipment import SOUL_PENDANT_STATS

    for socketed in sockets:
        if socketed is None:
            continue
        if getattr(socketed, "name", "") != "Soul Pendant":
            continue

        sock_rarity = getattr(socketed, "rarity", "normal")
        stats = SOUL_PENDANT_STATS.get(sock_rarity)
        if not stats:
            break

        heal_min = max(1, int(stats["drain_heal_min"] * SOCKET_POWER_RATIO))
        heal_max = max(heal_min, int(stats["drain_heal_max"] * SOCKET_POWER_RATIO))
        heal = random.randint(heal_min, heal_max)

        before = warrior.hp
        warrior.hp = min(warrior.max_hp, warrior.hp + heal)
        gained = warrior.hp - before
        if gained > 0:
            print(wrap(f"💜 Soul Ward! Your socketed pendant absorbs the blow — you recover {gained} HP."))
        break  # only first pendant procs


def _tusk_retaliation(enemy, warrior):
    """
    v0.7.20 (Nathan's call): if the player has a Javelina Tusk or Sharpened
    Tusk socketed into their equipped armor, the enemy takes retaliation bleed
    when they land a basic attack on the player.

    Bleed stats come from the tusk's own table (JAVELINA_TUSK_STATS or
    SHARPENED_TUSK_STATS), scaled by SOCKET_POWER_RATIO (75%). Only the first
    tusk found in armor sockets is used (no double-proc from two tusks).

    Does NOT proc on DoT/tick damage — callers gate on actual > 0 from a
    direct hit only.
    """
    armor = warrior.equipment.get("armor")
    if armor is None:
        return
    sockets = getattr(armor, "sockets", None)
    if not sockets:
        return

    from crafter import SOCKET_POWER_RATIO
    from equipment import JAVELINA_TUSK_STATS, SHARPENED_TUSK_STATS

    for socketed in sockets:
        if socketed is None:
            continue
        sock_name = getattr(socketed, "name", "")
        sock_rarity = getattr(socketed, "rarity", "normal")

        if sock_name == "Javelina Tusk":
            stats = JAVELINA_TUSK_STATS.get(sock_rarity)
        elif sock_name == "Sharpened Tusk":
            stats = SHARPENED_TUSK_STATS.get(sock_rarity)
        else:
            continue

        if not stats or stats.get("bleed_turns", 0) <= 0:
            break  # poor-rarity tusk — no bleed

        bleed_turns = stats["bleed_turns"]
        raw_min = stats["bleed_dmg_min"]
        raw_max = stats["bleed_dmg_max"]

        # Apply socket power ratio (75%) — floor at 1
        bleed_min = max(1, int(raw_min * SOCKET_POWER_RATIO))
        bleed_max = max(bleed_min, int(raw_max * SOCKET_POWER_RATIO))

        bleed_dmg = random.randint(bleed_min, bleed_max)

        # Apply bleed to enemy — use existing bleed_turns system
        # which already ticks via collect_dot_ticks on the enemy's turn.
        existing = getattr(enemy, "bleed_turns", 0)
        if existing > 0:
            # Refresh — keep higher values
            enemy.bleed_dmg_min = max(getattr(enemy, "bleed_dmg_min", bleed_min), bleed_min)
            enemy.bleed_dmg_max = max(getattr(enemy, "bleed_dmg_max", bleed_max), bleed_max)
            enemy.bleed_turns   = max(existing, bleed_turns)
        else:
            enemy.bleed_turns   = bleed_turns
            enemy.bleed_dmg_min = bleed_min
            enemy.bleed_dmg_max = bleed_max
            enemy.bleed_skip    = False  # tick immediately next enemy turn

        tusk_label = sock_name
        if sock_rarity != "normal":
            tusk_label = f"{sock_rarity.title()} {sock_name}"
        print(wrap(
            f"🦔 Spiked Armor! Your {tusk_label} retaliates — "
            f"{enemy.display_name} bleeds for {bleed_dmg}/turn for {bleed_turns} turns!"
        ))
        break  # only first tusk procs


def enemy_attack(enemy, warrior, resolve_special=True):
    """Enemy performs one action. Tries specials safely, then falls back to normal attack.

    resolve_special: when True (default), this function does its own tiered
    should-use-a-special roll. Callers that already resolved should_special via
    monster_ai_check() (or the tier-5 chimera dispatcher) — and are calling this
    purely for the basic-attack fallback — must pass resolve_special=False.
    Otherwise the special-move chance gets rolled a second time here on top of
    the outer check, silently inflating the real proc rate (e.g. a tier-2
    monster's "50% per turn" special was actually landing ~75% of the time:
    1 - (0.5 miss outer * 0.5 miss inner). v0.7.18 fix.
    """
    enemy.rounds_in_combat += 1

    # v0.6.16: Young Chimera passive heal — fires at START of every turn,
    # unconditionally. No longer gated on landing a basic attack hit.
    if enemy.name == "Young Chimera":
        chimera_passive_heal(enemy, warrior)

    # -------------------------------------------------------------
    # TIERED AI LOGIC (Consolidated Special Move Check)
    # -------------------------------------------------------------
    if resolve_special:
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
                # v0.7.18: the Fallen Warrior's desperation curve applies on
                # THIS path too — previously the pre-loop opening strike
                # (enemy wins initiative) rolled the flat 33% below, warping
                # 3x more often at full HP than the 10% the desperation
                # system intends. Docstring on fallen_warp_should_trigger
                # says it "replaces the flat 33%" — now it does everywhere.
                if enemy.name == "Fallen Warrior":
                    should_special = fallen_warp_should_trigger(enemy, warrior)
                else:
                    # Flat 33% chance (other Tier 4 bosses)
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
    # Normal attack fallback (If no special triggered, none assigned, or the
    # caller already resolved should_special=False and just wants the attack)
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

    # v0.7.20 (Nathan's call): TUSK RETALIATION — Javelina Tusk or Sharpened
    # Tusk socketed into armor causes bleed on the enemy when they hit you.
    # Only procs on direct hits that deal damage (actual > 0), NOT on DoT ticks.
    # Bleed stats are the tusk's own stats at 75% socket power (SOCKET_POWER_RATIO).
    # SOUL PENDANT ARMOR HEAL — heals the player on hit, defensive mirror of
    # weapon-socket drain. Similar to Dire Wolf Pup's devouring bite.
    if actual > 0:
        _tusk_retaliation(enemy, warrior)
        _soul_pendant_armor_heal(warrior)

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


def _fire_weapon_native_procs(warrior, weapon, enemy, actual):
    """
    Session 19: extracted from player_basic_attack's weapon proc block so the
    same weapon-native effects (NOT armor-set passives like Pack Hunter/Apex
    Predator, and NOT socket procs — those stay tied to the main-hand pass
    only, see call site) can be rolled a second time against the off-hand
    weapon when Dual Wielder rank 5's 50% off-hand-proc chance hits.

    Covers exactly: Imp Trident bonus true damage, Goblin Dagger blind,
    Rusted Sword rot, Javelina Tusk bleed, Goblin War Blade scaling bleed.
    Behavior for the main-hand call site is unchanged from pre-Session-19.
    """
    if weapon is None or actual <= 0 or not enemy.is_alive():
        return

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

    # 1) Roll — Session 19: dual-wielding now rolls main/off independently
    # and sums them; falls back to the normal single roll otherwise.
    roll = warrior_dual_wield_attack_roll(warrior)

    # v0.7.20 (Nathan's call): Brawl Master — 20% permanent ATK multiplier.
    # Applied to the final base roll so it scales with gear/stats/dual-wield.
    bm_mult = getattr(warrior, "brawl_master_atk_mult", 1.0)
    if bm_mult != 1.0:
        roll = max(1, int(roll * bm_mult))

    # Troubleshooting: show the main/off-hand split when debug_mode is on,
    # OR when the player opted into full combat detail at game start —
    # and this swing was actually a dual-wield roll (breakdown only gets
    # set inside warrior_dual_wield_attack_roll's two-weapon branch).
    if getattr(warrior, "debug_mode", False) or COMBAT_DETAIL == "full":
        bd = getattr(warrior, "_last_dw_breakdown", None)
        if bd is not None:
            off_note = " (untrained, halved)" if bd["untrained_halved"] else ""
            pct_note = f" → +{int(bd['pct_applied']*100)}% rank bonus → {bd['pre_set_bonus_total']}" if bd["pct_applied"] else ""
            print(
                f"🗡️ DW split — main: {bd['main_roll']}  off: {bd['off_roll_applied']}{off_note}"
                f"  sum: {bd['pre_pct_total']}{pct_note}  →  final roll: {roll}"
            )
            warrior._last_dw_breakdown = None  # consumed, avoid stale reuse on non-DW hits

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

    if getattr(warrior, "chimera_weakened_turns", 0) > 0:
        weak_mult = chimera_weakened_multiplier(warrior)
        if weak_mult < 1.0:
            pre_weak_total = total
            total = max(1, int(total * weak_mult))
            print(f"😮‍💨 Still shaking it off! Your swing lands at {int(weak_mult * 100)}% power. ({pre_weak_total} → {total})")

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
    print(hp_line(enemy.display_name.title(), enemy.hp, enemy.max_hp, side="enemy"))

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

    # 5c-2) Accessory proc — Javelina Tusk bleed. Unlike Soul Pendant's drain
    # (only on a dedicated accessory attack), the tusk is worn passively and
    # procs on ANY landed hit per its item description, so this isn't gated
    # behind use_accessory.
    if acc and actual > 0 and enemy.is_alive():
        tusk_bleed = getattr(acc, "bleed_turns", 0)
        if tusk_bleed > 0:
            dmg_min = getattr(acc, "bleed_dmg_min", 1)
            dmg_max = getattr(acc, "bleed_dmg_max", dmg_min)
            existing = getattr(enemy, "bleed_turns", 0)
            if existing > 0:
                enemy.bleed_dmg_min = max(getattr(enemy, "bleed_dmg_min", dmg_min), dmg_min)
                enemy.bleed_dmg_max = max(getattr(enemy, "bleed_dmg_max", dmg_max), dmg_max)
                enemy.bleed_turns   = max(existing, tusk_bleed)
            else:
                enemy.bleed_turns   = tusk_bleed
                enemy.bleed_dmg_min = dmg_min
                enemy.bleed_dmg_max = dmg_max
            dmg_str = f"{dmg_min}–{dmg_max}" if dmg_max > dmg_min else str(dmg_min)
            print(wrap(f"🩸 The jagged tusk opens a wound! "
                       f"{enemy.display_name} bleeds for {dmg_str} dmg/turn "
                       f"over {tusk_bleed} turn{'s' if tusk_bleed != 1 else ''}! "
                       f"(ignores defence)"))
    
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

        # Main-hand weapon-native procs — unchanged behavior, just extracted
        # into a shared helper (Session 19) so off-hand can reuse it below.
        _fire_weapon_native_procs(warrior, weapon, enemy, actual)

        # --- Dual Wielder rank 5: off-hand gets a separate 50% chance to
        # also fire its own weapon-native procs. Main-hand above is always
        # unaffected by this — this is purely additive. Deliberately does
        # NOT re-roll Pack Hunter / Apex Predator (armor-set passives, not
        # weapon procs — they already fired once above) or socket procs
        # (left as a main-hand-only effect for now, not in scope here).
        if warrior.skill_ranks.get("dual_wielder", 0) >= 5:
            off_weapon = warrior.equipment.get("off_hand")
            is_off_weapon = (off_weapon is not None
                              and getattr(off_weapon, "slot", None) == "weapon")
            if is_off_weapon and random.random() < 0.50:
                _fire_weapon_native_procs(warrior, off_weapon, enemy, actual)

        # --- Pack Hunter / Apex Predator / socket procs continue below,
        # main-hand-only, exactly as before this change ---

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
                        # v0.7.18 FIX: this branch used to append dots to
                        # enemy.warrior_poison_dots / warrior_burn_dots /
                        # warrior_acid_dots — attribute names that exist
                        # NOWHERE else in the codebase. Nothing initialized
                        # them (so getattr returned None and we skipped) and
                        # nothing ticked them. Socketed Sacs have therefore
                        # never dealt element damage since sockets shipped in
                        # v0.6.16. Now applies through the SAME structures the
                        # worn-accessory path uses (poison_dots / burns /
                        # acid_stacks), which collect_dot_ticks already ticks.
                        elem = proc["element"]
                        if elem == "poison":
                            if not hasattr(enemy, "poison_dots"):
                                enemy.poison_dots = []
                            dot = {"turns_left": proc["turns"],
                                   "dmg": proc["damage"], "skip": True}
                            if len(enemy.poison_dots) < proc["max_dots"]:
                                enemy.poison_dots.append(dot)
                            else:
                                enemy.poison_dots[0] = dot  # at cap — refresh oldest
                            print(wrap(f"💎 Socketed {proc['source']} — "
                                       f"poison ({proc['damage']} dmg/turn for "
                                       f"{proc['turns']} turns)."))

                        elif elem == "fire":
                            if not hasattr(enemy, "burns"):
                                enemy.burns       = []
                                enemy.fire_stacks = 0
                            stack = {"turns_left": proc["turns"],
                                     "bonus": proc["damage"],
                                     "skip": True, "flat": True}
                            if len(enemy.burns) < proc["max_dots"]:
                                enemy.burns.append(stack)
                            else:
                                enemy.burns[0] = stack
                            enemy.fire_stacks = len(enemy.burns)
                            print(wrap(f"💎 Socketed {proc['source']} — "
                                       f"burn ({proc['damage']} dmg/turn for "
                                       f"{proc['turns']} turns)."))

                        elif elem == "acid":
                            if not hasattr(enemy, "acid_stacks"):
                                enemy.acid_stacks       = []
                                enemy.acid_defence_loss = 0
                            stack = {"turns_left": proc["turns"], "skip": True,
                                     "flat": True, "bonus": proc["damage"],
                                     "restore_in": proc.get("restore", 0)}
                            if len(enemy.acid_stacks) < proc["max_dots"]:
                                enemy.acid_stacks.append(stack)
                                erosion = proc.get("erosion", 0)
                                if erosion > 0:
                                    enemy.acid_defence_loss = getattr(enemy, "acid_defence_loss", 0) + erosion
                                    enemy.defence = max(0, enemy.defence - erosion)
                                    print(wrap(f"🧪 The socketed acid eats into "
                                               f"{enemy.display_name}'s armor! (-{erosion} DEF)"))
                            else:
                                enemy.acid_stacks[0] = stack  # at cap — refresh, no extra erosion
                            print(wrap(f"💎 Socketed {proc['source']} — "
                                       f"acid ({proc['damage']} dmg/turn for "
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
    animate_xp_results(warrior, xp_needed, spend_points_fn=spend_points_menu)
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
            reset_between_rounds(warrior, full_rest=True)
            animate_xp_results(warrior, 50, spend_points_fn=spend_points_menu)

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

            # Clear all status effects before final boss
            reset_between_rounds(warrior, full_rest=True)
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
            reset_between_rounds(warrior, full_rest=True)
            animate_xp_results(warrior, 50, spend_points_fn=spend_points_menu)

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

            # Clear all status effects before final boss
            reset_between_rounds(warrior, full_rest=True)
            patronus_fight(warrior)
            return "evil"

        else:
            print("Enter 1 or 2.")






# v0.7.19: Nathan's call — a flat, path-and-difficulty-scaled ATK/HP boost
# awarded right after the path's climax fight (Chimera for good, Patronus
# for evil), separate from the Weapon Core and the Void/Sol Metal drop.
# Not meant to be game-breaking — just enough to keep the transition into
# the new path from feeling like a power dip. Good path gets more than
# evil (evil already got its edge on the Weapon Core — see WEAPON_CORE_*
# in equipment.py); this is intentionally NOT the same DEF/HP-vs-ATK/AP
# lean as the future Sol/Void armor set, just a flat "you made it" bump.
PATH_VICTORY_BOOST = {
    "good": {"noob": (4, 4), "warrior": (5, 5), "champion": (6, 6)},
    "evil": {"noob": (2, 2), "warrior": (3, 3), "champion": (4, 4)},
}


def _award_path_victory_boost(warrior, path):
    """
    Grant the flat post-climax ATK/HP boost (see PATH_VICTORY_BOOST above)
    and print a short confirmation line. path is "good" or "evil".
    """
    atk_boost, hp_boost = PATH_VICTORY_BOOST[path][DIFFICULTY]
    warrior.min_atk  += atk_boost
    warrior.max_atk  += atk_boost
    warrior.max_hp   += hp_boost
    warrior.hp       += hp_boost
    print(wrap(f"You feel steadier — ATK +{atk_boost}, Max HP +{hp_boost}."))


def _apply_boss_difficulty(boss):
    """Apply difficulty multiplier to a boss monster. Min 1 on all stats."""
    mult = DIFFICULTY_BOSS_MULT.get(DIFFICULTY, 1.20)
    if mult == 1.0:
        return boss
    boss.hp      = max(1, round(boss.hp      * mult))
    boss.max_hp  = boss.hp
    boss.min_atk = max(1, round(boss.min_atk * mult))
    boss.max_atk = max(boss.min_atk, round(boss.max_atk * mult))
    boss.defence = max(1, round(boss.defence * mult)) if boss.defence > 0 else 0
    return boss


def chimera_fight(warrior):
    """
    True final boss of the good path — Young Chimera.

    Win  → Chimera is vanquished. Chunk of Void Metal drops (raw, unusable
           until purified by the Solari).
           story_flag: "chimera_vanquished"

    Loss (rounds < 5) → Regular defeat. Player didn't last long enough.
           No intervention. Game over.

    Loss (rounds >= 5) → Player survived long enough to prove their worth.
           The mysterious figure freezes time and stabilises the player.
           story_flag: "chimera_alive" — son hunts it down 30 years later.
           No loot drops.
    """
    chimera = Young_Chimera()
    chimera = _apply_boss_difficulty(chimera)

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
    # v0.7.20 (Nathan's call): the intervention now gates on ROUNDS SURVIVED —
    # the number the player watches on screen — instead of combat_cycles.
    # combat_cycles only ticks at the END of the enemy's turn, so dying during
    # the boss's turn silently lost you that tick and could drop you under the
    # threshold despite reaching round 5+. `cycles` is still used for scoring.
    rounds_survived = max(getattr(chimera, "turns_survived", 0), cycles)

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

        void_metal = make_loot("Young Chimera", monster_level=3)
        if void_metal:
            # v0.6.14: clear combat fatigue (lingering fight-only DEF mods)
            # even though this drop is no longer wearable — keeps fatigue
            # state consistent with the rest of the victory cleanup.
            warrior.fatigue_def_loss  = 0
            warrior.fatigue_save_tier = 0
            print(wrap(
                "Something dark rolls free from the Chimera's flank as it falls — "
                "not scale, not bone. A chunk of raw, restless metal that has no "
                "business existing on this side of the fight. It doesn't belong to "
                "you yet. Not until something older than the arena says otherwise."
            ))
            print(f"\n🎁 {void_metal.short_label()}")
            warrior.inventory.append(void_metal)
            print(wrap(f"You take the {void_metal.name}. It's cold, and it waits."))
            print()
            _award_path_victory_boost(warrior, "good")
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
        input("Press Enter...")
        print()
        # v0.7.20 (Nathan's call): foreshadow the Game 1 -> Game 2 power reset.
        # Diegetic justification for the weapon returning to a max-tier-1 base
        # and regrowing via weapon points beyond the arena — the strength here
        # belonged to the arena, not the hero. No mechanics stated; flavour only.
        print(wrap(
            "As you run, the sword in your grip feels suddenly lighter — not "
            "broken, but quieter, as though the fury it carried was the arena's "
            "and never truly yours. Past these walls its edge will remember only "
            "what you teach it again. Whatever you were in here, you leave it in "
            "the sand."
        ))
        print()
        input("Press Enter...")
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
        if rounds_survived < 5:
            # Didn't reach round 5 — no intervention
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
        # rounds_survived >= 5 means the intervention narrative played
        chimera_outcome = "intervention" if rounds_survived >= 5 else "defeat"

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
           Chunk of Sol Metal drops (raw, unusable until corrupted by the
           Beast Gods).
           story_flag: "patronus_breastplate_dropped"
           Guardian of Winter Haven later uses a weaker replacement shield.

    Loss (rounds < 5) → Regular defeat. No intervention.

    Loss (rounds >= 5) → Beast Gods intervene — stronger shield, Patronus teleported out.
           story_flag: "patronus_intervention"
           Child later seeks out the shield.
    """
    patronus = Patronus()
    patronus = _apply_boss_difficulty(patronus)

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
    # v0.7.20 (Nathan's call): gate the intervention on ROUNDS SURVIVED, not
    # combat_cycles — see the matching note in chimera_fight. Patronus is
    # charge-based, so his cycle count drifts furthest behind the on-screen
    # round number; dying to his turn (e.g. Double Strike) previously cost the
    # player the tick that would have earned the Beast Gods' intervention.
    rounds_survived = max(getattr(patronus, "turns_survived", 0), cycles)

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

        sol_metal = make_loot("Patronus", monster_level=5)
        if sol_metal:
            # v0.6.14: clear combat fatigue — kept for consistency with the
            # rest of the victory cleanup, even though this drop is no
            # longer wearable (see notes at the Chimera drop above).
            warrior.fatigue_def_loss  = 0
            warrior.fatigue_save_tier = 0
            print(wrap(
                "Light-forged metal lies where the breastplate should have been — "
                "torn loose, still faintly warm. It resists your grip, like it knows "
                "whose hands it was made for, and yours aren't them. Not yet. The "
                "Beast Gods will want their say in that first."
            ))
            print(f"\n🎁 {sol_metal.short_label()}")
            warrior.inventory.append(sol_metal)
            print(wrap(f"You take the {sol_metal.name}. It fights you the whole way into your bag."))
            print()
            _award_path_victory_boost(warrior, "evil")
            print()

        # v0.7.20 (Nathan's call): foreshadow the Game 1 -> Game 2 power reset.
        # Diegetic justification for the weapon returning to a max-tier-1 base
        # and regrowing via weapon points once the hero is marched out under the
        # Beast Gods' brand. No mechanics stated; flavour only.
        print(wrap(
            "They march you from the sand under the Beast Gods' brand, and "
            "somewhere between one step and the next the weight in your hand "
            "changes. The power the arena lent you was never yours to keep — "
            "beyond the gate the blade dulls, and what you carry out is only the "
            "promise of what it could become again. The Gods will decide how "
            "much of it you earn back."
        ))
        print()
        input("Press Enter...")
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
        if rounds_survived < 5:
            print("\n" + "=" * 50)
            print("   💀 OVERWHELMED")
            print("=" * 50)
            print(wrap(
                "Patronus stands over you, unhurried. "
                "He has done this a hundred times. He will do it again."
            ))
            input("\nPress Enter to continue...")

        else:
            # Reached round 5+ — Beast Gods intervene, Patronus teleported out
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
        # rounds_survived >= 5 means the intervention narrative played
        patronus_outcome = "intervention" if rounds_survived >= 5 else "defeat"

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

    except QuickCombatException:
        # Dev shortcut ('!c' / '!combat') fallback while already in battle():
        # end the current fight as a loss. Real quick-combat routing happens
        # in the arena/story layer that raises this.
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
            print(wrap(
                f"🧠 {enemy.display_name}'s psychic aura is already pulsing — "
                f"you feel your body weaken before the fight even begins! "
                f"Your ATK and DEF are reduced by 1."
            ))
            # v0.7.17: route through the same incremental path used for
            # mid-fight charge gains, so there's one system of record and
            # cleanup always restores exactly what was applied — even if
            # the player picks up a stat point (e.g. Defence) mid-fight.
            _flayed_apply_player_debuff(enemy, warrior, charges, announce=False)

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
                        # Check Chimera/Patronus intervention — DoT death on player turn
                        # still qualifies if enough cycles survived
                        if hasattr(enemy, "combat_cycles") and getattr(enemy, "combat_cycles", 0) >= 4:
                            log(f"  [RESULT] DEFEAT (DoT) — but {warrior.name} survived 4+ cycles.")
                            log_battle_summary(warrior.name, enemy.display_name, "DEFEAT", turn_count)
                            return False  # chimera_fight/patronus_fight checks cycles on False
                        log(f"  [RESULT] DEFEAT — {warrior.name} fell to status damage.")
                        log_battle_summary(warrior.name, enemy.display_name, "DEFEAT", turn_count)
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
                        animate_xp_results(warrior, _xp_with_difficulty_mult(enemy.xp), spend_points_fn=spend_points_menu)

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

                        # Session 19 hotfix: this branch returns "win" directly
                        # and skips the "PAUSE AND REST" section below, which is
                        # where reset_between_rounds() normally fires. That meant
                        # any defence warp/erosion picked up mid-fight (Defence
                        # Warp, acid, etc.) carried uncorrected straight into the
                        # next round (e.g. Young Chimera). Same root cause as the
                        # v0.7.12 Defence Warp fix — just a second return path
                        # that fix didn't cover. Call it here too.
                        reset_between_rounds(warrior)
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
                            animate_xp_results(warrior, _xp_with_difficulty_mult(enemy.xp), spend_points_fn=spend_points_menu)

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
                # v0.7.18: the Defence Warp cooldown clear used to live here,
                # at the start of every enemy turn — but that ran BEFORE
                # fallen_warp_should_trigger's cooldown check, making the
                # guaranteed breather dead code. The trigger check itself now
                # consumes the cooldown (see monsters.py).

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
                    continue  # v0.7.19: was missing — enemy attacked after "PARALYZED" message
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
                            _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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
                        _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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
                            # v0.7.17: snapshot before the basic attack so we can tell
                            # whether THIS hit is what just spent Death Defier — if so,
                            # the follow-up Surge below is skipped. Otherwise a single
                            # enemy turn could burn your one-time save on the basic
                            # attack and then kill you anyway with the Surge immediately
                            # after, with no turn in between to do anything about it.
                            _dd_used_before_fury = getattr(warrior, "death_defier_used", False)
                            # Basic attack first (normal defence applies)
                            _eatk = enemy_attack(enemy, warrior, resolve_special=False)
                            if _eatk:
                                _eroll = _eatk + max(0, getattr(warrior, "defence", 0))
                                log_attack(enemy.display_name, warrior.name, _eroll, _eatk, _eroll - _eatk, is_player=False)
                            _dd_just_fired_on_basic = (
                                not _dd_used_before_fury
                                and getattr(warrior, "death_defier_used", False)
                            )
                            # Then Primordial Surge as true damage (fury_triggered=True suppresses charge display)
                            # Capture actual damage so the combat log reports it correctly
                            # (was previously hardcoded to 0 — bug fixed v0.6.11)
                            _surge_fired = False
                            if warrior.is_alive() and not _dd_just_fired_on_basic:
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
                            elif _dd_just_fired_on_basic:
                                print(wrap(
                                    "😮‍💨 Still reeling from cheating death, you brace against the "
                                    "follow-up surge — it doesn't come. The Chimera's fury passes."
                                ))
                                log(f"  [ENEMY] Young Chimera — Fury Overload: Surge withheld, Death Defier just fired on the basic attack.")
                            # Log overall fury outcome — only mention surge if it actually fired
                            if _surge_fired:
                                log(f"  [ENEMY] Young Chimera — Fury Overload: basic ATK + Primordial Surge")
                            elif not _dd_just_fired_on_basic:
                                log(f"  [ENEMY] Young Chimera — Fury Overload: basic ATK landed killing blow (Surge skipped)")
                            # Reset fury
                            enemy.chimera_fury_charge      = 0
                            enemy.chimera_fury_overloading = False
                        # Strict alternation — special then rest, repeat.
                        # Charge-based — no AP gating. should_special from monster_ai_check tier 5.
                        elif getattr(enemy, "chimera_used_special", False):
                            # Rest turn — basic attack only, no AP regen
                            log(f"  [ENEMY] Young Chimera rests — basic attack")
                            _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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
                            _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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
                            _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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
                        _eatk = enemy_attack(enemy, warrior, resolve_special=False)
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








