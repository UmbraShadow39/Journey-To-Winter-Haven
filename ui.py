# ui.py
# Display utilities: meters, bars, animations, state refresh
# Extracted from main during v0.7 modular refactor (prep for pygame port)

import time
import sys
import random

from shared import WHITE, RED, GREEN, YELLOW, RESET, WIDTH, wrap, space, hp_bar

# ---------------------------------------------------------------
# XP BAR COLOR CONSTANTS
# ---------------------------------------------------------------
DIM_GRAY    = "\033[90m"   # empty bar blocks
DIM_CYAN    = "\033[36m"   # 0-25%  — just starting out
BRIGHT_GREEN = "\033[92m"  # 25-50% — making progress
YELLOW_GREEN = "\033[33m"  # 50-75% — getting there
BRIGHT_YELLOW = "\033[93m" # 75-99% — almost
GOLD        = "\033[93m"   # 100%   — level up (sparkle base)
BRIGHT_WHITE = "\033[97m"  # 100%   — sparkle highlight

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


    


def xp_bar(current, needed, size=20):
    """
    Color-shifting XP bar:
      0-25%  dim grey    — just started
      25-50% green       — making progress
      50-75% yellow-green — getting there
      75-99% bright yellow — almost
      100%   gold sparkle — LEVEL UP
    """
    needed = max(1, int(needed))
    current = max(0, min(int(current), needed))
    filled = int(round((current / needed) * size))
    if current > 0 and filled == 0:
        filled = 1
    empty = size - filled
    ratio = current / needed

    # --- GOLD SPARKLE at 100% ---
    if ratio >= 1.0:
        sparkle = ""
        for _ in range(filled):
            if random.random() < 0.3:
                sparkle += BRIGHT_WHITE + "✦" + RESET
            else:
                sparkle += GOLD + "█" + RESET
        return sparkle + DIM_GRAY + "░" * empty + RESET

    # --- COLOR STAGES ---
    if ratio >= 0.75:
        color = BRIGHT_YELLOW
    elif ratio >= 0.50:
        color = YELLOW_GREEN
    elif ratio >= 0.25:
        color = BRIGHT_GREEN
    else:
        color = DIM_CYAN

    return color + "█" * filled + RESET + DIM_GRAY + "░" * empty + RESET





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


def _flayed_apply_player_debuff(enemy, warrior, charges, announce=True):
    """
    Apply the incremental ATK/DEF penalty for Flayed One charges.

    v0.7.17: Only ever applies the DELTA between the new charge count and
    however much penalty is already applied (warrior.flayed_charges_applied).
    The actual (post-floor) amount subtracted is tracked cumulatively in
    warrior.flayed_atk_penalty / warrior.flayed_def_penalty, which combat
    cleanup adds back at the end of the fight.

    This replaces the old "snapshot base once, recompute from it" approach,
    which went stale the moment the player's real stats changed mid-fight
    (e.g. a level-up stat point in Defence) — the snapshot didn't know about
    the gain, so the next charge tick silently overwrote it. Working in
    deltas means a mid-fight stat gain is never touched by this system at
    all; it just rides along underneath the penalty and reappears in full
    at cleanup.
    """
    applied = getattr(warrior, "flayed_charges_applied", 0)
    delta = charges - applied
    if delta <= 0:
        return

    atk_dec = min(delta, warrior.min_atk - 1)  # keep ATK floor at 1
    def_dec = min(delta, warrior.defence)      # keep DEF floor at 0

    warrior.min_atk -= atk_dec
    warrior.max_atk -= atk_dec
    warrior.defence -= def_dec

    warrior.flayed_atk_penalty     = getattr(warrior, "flayed_atk_penalty", 0) + atk_dec
    warrior.flayed_def_penalty     = getattr(warrior, "flayed_def_penalty", 0) + def_dec
    warrior.flayed_charges_applied = applied + delta

    if announce:
        print(wrap(
            f"🧠 The psychic torment intensifies! Your ATK and DEF weaken — "
            f"ATK now {warrior.min_atk}-{warrior.max_atk}  DEF now {warrior.defence}"
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


def animate_xp_results(hero, gained_xp, size=22, duration=0.8, spend_points_fn=None):
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
            line = f"\rXP: [{bar}] {virtual}/{need}"
            sys.stdout.write(line + " " * 10)  # trailing spaces clear old chars
            sys.stdout.flush()
            time.sleep(duration / frames)

        # 2) Update actual hero XP
        hero.xp += chunk
        remaining -= chunk

        # 3) Handle Level Up
        if hero.xp >= need:
            # ✨ Gold sparkle flash — shimmer 5 times before level up
            for _ in range(5):
                sparkle_bar = ""
                for _ in range(size):
                    if random.random() < 0.35:
                        sparkle_bar += BRIGHT_WHITE + "✦" + RESET
                    else:
                        sparkle_bar += GOLD + "█" + RESET
                sys.stdout.write(f"\rXP: [{sparkle_bar}] {need}/{need}")
                sys.stdout.flush()
                time.sleep(0.08)

            # Reset XP to 0 for the NEXT level before calling level_up
            hero.xp = 0

            # Level up (adds points, heals, etc.)
            hero.level_up()

            # Clear the sparkle line completely before printing level-up
            sys.stdout.write("\r" + " " * (size + 40) + "\r")
            sys.stdout.flush()
            print(f"✨ Level {hero.level} acquired! ✨")

            # Cap Check: If we hit max, kill remaining XP
            if getattr(hero, "level_cap", None) and hero.level >= hero.level_cap:
                remaining = 0
                hero.xp = 0

    # ✅ Pause ONCE after ALL bars/levels from this XP award are done
    # Clear any leftover animation \r line, then print the ONE final bar
    sys.stdout.write("\r" + " " * (size + 40) + "\r")
    sys.stdout.flush()

    # If at level cap, show a full gold bar
    if getattr(hero, "level_cap", None) and hero.level >= hero.level_cap:
        cap_bar = GOLD + "█" * size + RESET
        print(f"XP: [{cap_bar}] MAX")
    elif hero.level > old_level and int(hero.xp) == 0:
        # Just leveled up with no leftover XP — show fresh bar at 0
        fresh_bar = xp_bar(0, int(hero.xp_to_lvl), size=size)
        print(f"XP: [{fresh_bar}] 0/{int(hero.xp_to_lvl)}")
    else:
        final_bar = xp_bar(int(hero.xp), int(hero.xp_to_lvl), size=size)
        print(f"XP: [{final_bar}] {int(hero.xp)}/{int(hero.xp_to_lvl)}")

    # 4) FINAL ACT: The point menu (Only once!)
    if hero.level > old_level:
        sys.stdout.write("\n")
        time.sleep(0.2)
        if getattr(hero, "stat_points", 0) > 0 or getattr(hero, "skill_points", 0) > 0:
            if spend_points_fn is not None:
                spend_points_fn(hero)

    
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

