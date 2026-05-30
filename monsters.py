"""
monsters.py — Monster classes, special moves, encounter helpers.

Extracted from Journey_To_Winter_Haven_v_06_02.py in v0.6.03.

Contains:
  * 18 monster classes (Green_Slime through Patronus)
  * All monster special-move functions (slime_poison_spit, savage_slash, etc.)
  * Psychic / Drown / Chimera / Patronus subsystems
  * Encounter helpers (random_encounter, MONSTER_TYPES, tier picking)

Imports back from the main module the shared helpers it needs:
combat math (lvl_bonus, monster_deal_damage, monster_math_breakdown),
display helpers (wrap, show_health, space, clear_screen, continue_text,
WIDTH), the Equipment registry / status helpers, and Hero/Monster bases.

These are imported lazily (inside functions where needed) to avoid the
circular-import trap, since the main file does `from monsters import *`.
"""

import random
import math
import time

# Lazy back-imports happen inside functions. We pull common ones at
# module load — they only resolve when a function in this module is
# *called*, by which time the main module is fully loaded.
from shared import (
    Monster,
    wrap, space, clear_screen, continue_text, show_health,
    lvl_bonus, monster_math_breakdown, monster_deal_damage,
    try_death_defier,
    get_ap_inflation, inflated_ap_cost,
    scaled_xp_step, ap_from_hp,
    apply_turn_stop,
    SPECIAL_MOVE_NAMES, DEFENCE_BREAK_STATS,
    WIDTH,
)
from combat_log import COMBAT_LOG


# ---------------------------------------------------------------
# __all__ — what `from monsters import *` exposes to the main file.
# ---------------------------------------------------------------
# Python's `import *` skips names that start with `_` by default,
# but main.py legitimately calls a handful of our private helpers
# (state restorers, debuff clears, tick helpers). Listing them here
# makes them visible through `import *` without needing a second,
# explicit `from monsters import (_name1, _name2, ...)` block in
# main — which causes a circular-import failure on Python 3.13.
#
# Add new public names here when you create them.
# Add new underscored names here when main needs to call them.
# ---------------------------------------------------------------
__all__ = [
    # Monster classes
    "Green_Slime", "Young_Goblin", "Goblin_Archer", "Goblin_Warrior",
    "Brittle_Skeleton", "rot_thrust", "Imp", "Wolf_Pup", "Dire_Wolf_Pup", "Red_Slime",
    "Fallen_Warrior", "Noob_Ghost", "Wolf_Pup_Rider", "Javelina",
    "Hydra_Hatchling", "Flayed_One", "Drowned_One",
    "Young_Chimera", "Patronus",

    # Monster AI / special-move functions (public)
    "monster_ai_check",
    "slime_poison_spit", "red_slime_fire_spit",
    "goblin_cheap_shot", "paralyzing_shot",
    "imp_sneak_attack", "brittle_skeleton_thrust", "rot_thrust",
    "wolf_pup_bite", "devouring_bite",
    "ghost_life_leech", "blinding_charge",
    "impact_bite", "fallen_warp_should_trigger", "fallen_defence_warp",
    "hydra_hatchling_acid_spit", "savage_slash",
    "psychic_shred", "trigger_pressure_feedback",
    "check_drown_punishment", "psychic_drown",
    "primordial_surge", "chimera_elemental_strike",
    "chimera_boost", "chimera_double", "chimera_triple",
    "chimera_combo_bonus", "chimera_special_dispatcher",
    "patronus_double_strike", "patronus_war_cry", "patronus_power_charge",
    "patronus_first_aid", "patronus_defence_break",
    "patronus_ai",

    # Encounter helpers
    "monster_level_for_round", "title_for_level", "apply_level_scaling",
    "weight_to_tier", "get_monsters_by_tier", "random_encounter_by_tier",
    "random_tier4_boss", "pick_tier_from_weights", "get_round_tier",
    "select_arena_enemy", "random_encounter",

    # Constants
    "MONSTER_TYPES", "TIER4_BOSSES", "LEVEL_TITLES",
    "CHIMERA_TIER1_POOL", "CHIMERA_TIER2_POOL", "CHIMERA_TIER3_POOL",
    "CHIMERA_ELEMENTS", "HEAL_PERCENTS_ENEMY",

    # Underscored helpers main calls back into. `import *` skips
    # underscored names by default — listing them here forces export.
    "_apply_psychic_debuff_to_stats",
    "_clear_psychic_debuff",
    "_clear_psychic_drown",
    "_restore_primordial_stats",
    "_restore_patronus_def",
    "_tick_patronus_war_cry",
    "_tick_patronus_def_break",
    "_tick_patronus_passive_first_aid",
]


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
        # Young Chimera — HP-threshold weighted aggression
        # Calm early, desperate late. Random move selection stays in dispatcher.
        hp_pct = monster.hp / monster.max_hp if monster.max_hp > 0 else 0
        if hp_pct > 0.75:
            return random.random() < 0.40   # probing
        elif hp_pct > 0.50:
            return random.random() < 0.50   # engaged
        elif hp_pct > 0.25:
            return random.random() < 0.65   # dangerous
        else:
            return random.random() < 0.80   # desperate

    return False

# ===============================
# Monster Special Moves
# ===============================
def slime_poison_spit(slime, hero):
    if slime.ap <= 0:
        return None

    slime.ap -= 1

    b = lvl_bonus(slime)

    is_chimera = hasattr(slime, "chimera_tier1")

    # ---- Physical hit — Chimera uses its own ATK stat, slime uses its own ----
    if is_chimera:
        roll = random.randint(slime.min_atk + b, slime.max_atk + b)  # 14-18 range
    else:
        roll = random.randint(slime.min_atk + b, slime.max_atk + b)
    actual = hero.apply_defence(roll, attacker=slime)
    hero.hp = max(0, hero.hp - actual)

    # ---- Apply poison — Chimera: 3-6/turn for 3 turns. Hardened: 3-4/turn for 4 turns. Slime: 1-2/turn for 2 turns ----
    hero.poison_active = True
    is_hardened = getattr(slime, "level", 1) >= 2
    if is_chimera:
        hero.poison_amount = random.randint(3, 6)
        hero.poison_turns  = 3
    elif is_hardened:
        hero.poison_amount = random.randint(3, 4)
        hero.poison_turns  = 4
    else:
        hero.poison_amount = random.randint(1, 2)
        hero.poison_turns  = 2
    hero.poison_skip_first_tick = True

    print(wrap(f"{slime.name} spits corrosive slime!"))
    monster_math_breakdown(slime, hero, roll, actual, tag="Poison Spit")
    print(wrap(f"🟢 You are poisoned! ({hero.poison_amount} dmg/turn for {hero.poison_turns} turns)"))

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

    is_chimera = hasattr(slime, "chimera_tier1")

    print(f"🔥 {slime.name} spits burning slime at you!")

    # --------------------------------
    # 1) PHYSICAL IMPACT (defense applies)
    # --------------------------------
    normal_roll = random.randint(slime.min_atk, slime.max_atk)
    normal_actual = hero.apply_defence(normal_roll, attacker=slime)
    hero.hp = max(0, hero.hp - normal_actual)

    # --------------------------------
    # 2) FIRE DAMAGE (TRUE damage, ignores defence)
    #    Chimera: doubled to 4-6, Slime: 2-3
    # --------------------------------
    if is_chimera:
        fire_damage = random.randint((2 + b) * 2, (3 + b) * 2)
    else:
        fire_damage = random.randint(2 + b, 3 + b)
    hero.hp = max(0, hero.hp - fire_damage)

    monster_math_breakdown(
        slime, hero,
        normal_roll, normal_actual,
        extra_parts=[("Fire", fire_damage)],
        tag="Fire Spit"
)

    print("🔥 Burning slime scorches your skin!")

    # --------------------------------
    # 3) APPLY BURN STACK (DoT) — per-stack timers
    #    Chimera: 3 turns. Slime: 2 turns.
    # --------------------------------
    if not hasattr(hero, "burns"):
        hero.burns = []

    burn_turns = 3 if is_chimera else 2
    if len(hero.burns) < 2:
        hero.burns.append({"turns_left": burn_turns, "skip": True, "bonus": b})
    else:
        weakest_idx = min(
            range(len(hero.burns)),
            key=lambda i: hero.burns[i]["turns_left"]
        )
        hero.burns[weakest_idx] = {"turns_left": burn_turns, "skip": True, "bonus": b}

    hero.fire_stacks = len(hero.burns)
    stack_text = "stack" if hero.fire_stacks == 1 else "stacks"
    print(f"🔥 Burning slime clings to your skin! ({hero.fire_stacks} burn {stack_text})")

    show_health(hero)

    # Return total immediate damage
    return normal_actual + fire_damage

def goblin_cheap_shot(enemy, warrior):
    """Goblin special move: 3-stage blind (Miss -> 50% -> 75%)
    When used by Young Chimera: 2 full missed turns, max ATK hit through defence.
    """
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1
    b = lvl_bonus(enemy)
    is_chimera = hasattr(enemy, "chimera_tier1")

    if is_chimera:
        warrior.blind_turns = 2
        warrior.blind_long  = True
        warrior.is_blinded  = True
        warrior.blind_type  = "goblin_dust"
        print(f"\n🌀 {enemy.display_name} lashes out with blinding force!")
        print("😵 You are BLINDED! You will miss your next 2 turns!")
    else:
        warrior.blind_turns = 3
        warrior.blind_long  = True
        warrior.is_blinded  = True
        warrior.blind_type  = "goblin_dust"
        print(f"\n🗡️ {enemy.display_name} gets close and blows dust into your eyes!")
        print("😵 You are BLINDED! Your vision is completely obscured!")

    # Chimera: max atk through defence. Goblin: max atk flat (no defence)
    if is_chimera:
        actual = warrior.apply_defence(enemy.max_atk + b, attacker=enemy)
    else:
        actual = enemy.max_atk + b

    warrior.hp = max(0, warrior.hp - actual)
    print(f"👁️ {enemy.display_name} strikes while you're vulnerable for {actual} damage!")
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

    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)  # Chimera already has 14-18 ATK
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
    When borrowed by Chimera: defence applies normally.
    """

    if enemy.ap <= 0:
        return None

    is_chimera = hasattr(enemy, "chimera_tier1")

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print(f"\n👿 {enemy.display_name} vanishes in a puff of smoke!")
    print(f"⚡ {enemy.display_name} reappears behind you, striking before you can react!")

    # Chimera: max ATK + 3 bonus through defence. Imp: max ATK flat, bypasses defence.
    if is_chimera:
        raw = enemy.max_atk + b + 3
        if warrior.defence == 0:
            raw += 1 + b
            print("🩸 Your lack of defense leaves you wide open!")
        damage = warrior.apply_defence(raw, attacker=enemy)
    else:
        raw = chimera_triple(enemy, enemy.max_atk + b)
        if warrior.defence == 0:
            raw += 1 + b
            print("🩸 Your lack of defense leaves you wide open!")
        damage = raw

    warrior.hp = max(0, warrior.hp - damage)
    print(f"🗡️ {enemy.display_name} deals {damage} damage!")

    return damage

def rot_thrust(enemy, target):
    """Brittle Skeleton / Chimera borrowed move.
    Deals precise damage and applies Rot — temporarily draining the target's max HP.

    Skeleton version:
      - 50% chance to apply rot on use (only fires when skeleton uses special)
      - Rot: -20% of target's current max HP per proc, capped at 50% of original max HP
      - Stronger skeletons (higher rarity/HP tier) get 2-3 uses of special
      - Bypasses defence (precision strike)

    Chimera version:
      - 75% chance to apply rot
      - Cap raised to 60% of player's max HP
      - Defence applies normally (3x damage already punishing enough)
      - Clears on Chimera intervention if this move was drawn
    """
    if enemy.ap <= 0:
        return 0

    b = lvl_bonus(enemy)
    is_chimera = hasattr(enemy, "chimera_tier1")

    # Raw damage before defence — tripled if Chimera is the attacker
    raw = chimera_triple(enemy, 6 + b)
    if target.defence == 0:
        raw += chimera_triple(enemy, 1 + b)

    if is_chimera:
        print(f"💀 {enemy.display_name} channels the rot — a precise, corrupting thrust!")
    else:
        print(f"💀 {enemy.display_name} lunges with a rotting thrust!")

    enemy.ap -= 1

    # Damage — Chimera applies defence, Skeleton bypasses it
    if is_chimera:
        damage = target.apply_defence(raw, attacker=enemy)
    else:
        damage = raw

    target.hp = max(0, target.hp - damage)
    print(f"You take {damage} damage!")
    show_health(target)

    # --- Rot application ---
    rot_chance = 0.75 if is_chimera else 0.50
    hp_cap_pct = 0.60 if is_chimera else 0.50

    import random as _r
    if _r.random() < rot_chance:
        # Snapshot original max HP on first rot application
        if not getattr(target, "rot_base_max_hp", 0):
            target.rot_base_max_hp = target.max_hp
        if not getattr(target, "rot_max_hp_loss", 0):
            target.rot_max_hp_loss = 0

        cap       = max(1, int(target.rot_base_max_hp * hp_cap_pct))
        already   = target.rot_max_hp_loss
        space     = cap - already

        if space > 0:
            drain = min(int(target.max_hp * 0.20), space)
            drain = max(1, drain)
            target.max_hp          = max(1, target.max_hp - drain)
            target.hp              = min(target.hp, target.max_hp)
            target.max_overheal    = int(target.max_hp * 1.10)
            target.rot_max_hp_loss += drain
            pct_label = "60%" if is_chimera else "50%"
            print(wrap(
                f"🟫 The corroded blade festers in the wound! "
                f"Your Max HP is reduced by {drain}! "
                f"(Rot: -{target.rot_max_hp_loss} total, cap {pct_label} of base)"
            ))
            print(wrap("   Rot clears on rest. Rank 4+ First Aid cures it."))
        else:
            print(wrap("🟫 Your body is already deeply rotted — the wound festers but holds no more."))
    
    return damage

# Keep old name as alias so existing CHIMERA_TIER1_POOL reference still works
brittle_skeleton_thrust = rot_thrust

def wolf_pup_bite(enemy, warrior):
    if enemy.ap <= 0:
        return None

    is_chimera = hasattr(enemy, "chimera_tier1")
    
    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print(f"🐺 {enemy.display_name} lunges forward and viciously bites you!")

    # Base attack — Chimera uses its own ATK (14-18), wolf uses its own (2-5)
    if is_chimera:
        roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    else:
        roll = random.randint(2 + b, 5 + b)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    # Bite bonus (ignores defence) — tripled for Chimera
    raw_bite = random.randint(1 + b, 5 + b)
    bite_bonus = chimera_triple(enemy, raw_bite)
    warrior.hp = max(0, warrior.hp - bite_bonus)

    monster_math_breakdown(enemy, warrior, roll, actual, extra_parts=[("Bite", bite_bonus)], tag="Bite")
    print(f"🩸 The bite rips flesh for {bite_bonus} extra damage!")

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

    
    

    enemy.ap -= 1
    b = lvl_bonus(enemy)

    print(f"\n🐺 {enemy.display_name} lunges with a DEVOURING BITE!")

    is_chimera = hasattr(enemy, "chimera_tier1")

    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    monster_math_breakdown(enemy, warrior, roll, actual, tag="Devouring Bite")

    # Chimera heals half the roll (pre-defence). Dire wolf heals half actual damage dealt.
    heal = max(1, roll // 2) if is_chimera else actual // 2
    if heal > 0:
        overheal_cap = int(enemy.max_hp * 1.5)
        if not hasattr(enemy, "max_overheal"):
            enemy.max_overheal = overheal_cap
        before = enemy.hp
        enemy.hp = min(overheal_cap, enemy.hp + heal)
        gained = enemy.hp - before
        overheal_tag = " (overheal!)" if enemy.hp > enemy.max_hp else ""
        print(f"🧶 {enemy.display_name} devours flesh and regains {gained} HP{overheal_tag}!")
    else:
        print(f"🛡️ Your defence denies {enemy.display_name} its meal!")

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

    print(wrap(f"\n👻 {enemy.display_name}'s claws pass through your flesh, chilling your soul!"))

    is_chimera = hasattr(enemy, "chimera_tier1")

    # ---------- Step 1: physical hit (defence applies) ----------
    roll = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    physical = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - physical)

    monster_math_breakdown(enemy, warrior, roll, physical, tag="Life Leech (Hit)")

    # ---------- Step 2: life drain (ignores defence) ----------
    # Drain is half the original roll — same for chimera and ghost
    drain = max(1, roll // 2)

    before = warrior.hp
    warrior.hp = max(0, warrior.hp - drain)
    actual_drain = before - warrior.hp

    overheal_cap = int(enemy.max_hp * 1.5)
    if not hasattr(enemy, "max_overheal"):
        enemy.max_overheal = overheal_cap
    enemy.hp = min(overheal_cap, enemy.hp + actual_drain)

    print(
        f"💀 Life Leech drains an additional {actual_drain} HP "
        f"(ignores defence) and empowers {enemy.display_name}!"
    )
    show_health(warrior)
    # If you ever add an enemy HP HUD, it will reflect overheal too.

    # Total damage to the hero this turn
    return physical + actual_drain

def blinding_charge(self, hero):
    if self.ap <= 0:
        return None

    is_chimera = hasattr(self, "chimera_tier1")

    self.ap -= 1
    b = lvl_bonus(self)

    print(f"\n👺 {self.display_name} blinds you and charges!")

    # Chimera: max atk through defence. Original: flat 4-8 no defence check
    if is_chimera:
        raw = self.max_atk + b
        damage = hero.apply_defence(raw, attacker=self)
    else:
        damage = random.randint(4, 8)
    hero.hp = max(0, hero.hp - damage)

    # Blind application
    if getattr(hero, "blind_turns", 0) > 0:
        print(wrap("👁️‍🗨️ You're already blinded — the charge just hits HARD!"))
    else:
        if is_chimera:
            # 2 full missed turns
            hero.blind_turns = 2
            hero.blind_long  = True
            apply_turn_stop(hero, turns=2, reason="Blinded")
            print("😵 You are BLINDED! You will miss your next 2 turns!")
        else:
            hero.blind_turns = 1
            hero.blind_long = False
            apply_turn_stop(hero, turns=1, reason="Blinded")

    print(f"💥 You take {damage} damage!")
    show_health(hero)
    return damage

def impact_bite(enemy, hero):
    if enemy.ap <= 0:
        return None

    is_chimera = hasattr(enemy, "chimera_tier1")

    enemy.ap -= 1
    b = lvl_bonus(enemy)
    print(wrap(f"\n🐗 {enemy.display_name} barrels into you and snaps its jaws!"))

    if is_chimera:
        # Chimera: base ATK through defence + doubled impact roll as true damage
        base_roll   = random.randint(enemy.min_atk + b, enemy.max_atk + b)
        base_actual = hero.apply_defence(base_roll, attacker=enemy)
        hero.hp     = max(0, hero.hp - base_actual)

        impact_roll = random.randint(2 + b, 4 + b) * 2   # 4-8 true damage
        hero.hp     = max(0, hero.hp - impact_roll)

        total = base_actual + impact_roll
        print(f"💥 Chimera Combo! Base ({base_actual}) + Impact ({impact_roll})")
        print(f"You take {total} total damage!")
        show_health(hero)
        return total

    else:
        # Original javelina version — full combo through defence once
        impact_roll = random.randint(4 + b, 6 + b)
        bite_roll   = random.randint(2 + b, 4 + b)
        total_power = impact_roll + bite_roll

        actual_damage = hero.apply_defence(total_power, attacker=enemy)
        hero.hp = max(0, hero.hp - actual_damage)

        print(f"💥 Combo Hit! Impact ({impact_roll}) + Bite ({bite_roll})")
        print(f"🛡️ Your defence mitigated the force, but you still take {actual_damage} damage!")
        show_health(hero)
        return actual_damage

def fallen_warp_should_trigger(enemy, warrior):
    """
    Desperation-aware trigger check for Defence Warp.
    Replaces the flat 33% from monster_ai_check for the Fallen Warrior.

    HP thresholds:
      76-100% ->  10% chance  (early fight, probing)
      51-75%  ->  25% chance  (getting serious)
      26-50%  ->  50% chance  (dangerous territory)
       0-25%  ->  75% chance  (desperation)

    Cooldown:
      - After firing, warp_on_cooldown = True for 1 turn (guaranteed breather)
      - Exception: if HP drops to a NEW lower threshold while on cooldown,
        desperation overrides and cooldown is ignored
    """
    if enemy.ap <= 0:
        return False

    hp_pct = enemy.hp / enemy.max_hp if enemy.max_hp > 0 else 0

    if hp_pct > 0.75:
        tier, chance = 0, 0.10
    elif hp_pct > 0.50:
        tier, chance = 1, 0.25
    elif hp_pct > 0.25:
        tier, chance = 2, 0.50
    else:
        tier, chance = 3, 0.75

    on_cooldown = getattr(enemy, "warp_on_cooldown", False)
    last_tier   = getattr(enemy, "warp_last_tier", tier)

    if on_cooldown:
        if tier >= last_tier:
            return False  # respect the cooldown
        # Dropped to a worse tier mid-cooldown — desperation kicks in
        print(wrap("💀 The Fallen Warrior's desperation overrides his fatigue!"))

    return random.random() < chance

def fallen_defence_warp(enemy, warrior):
    """
    Fallen Warrior special: Defence Warp (v0.5.01 — desperation system)

    Trigger chance now scales with HP thresholds (10/25/50/75%).
    Guaranteed 1-turn cooldown after firing — player always gets a breather.
    Cooldown overridden if HP drops to a new lower threshold mid-cooldown.
    Defence strip phases unchanged: 0 defence -> 50% -> full restore.
    """
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1

    # Record current tier so cooldown override logic works next turn
    hp_pct = enemy.hp / enemy.max_hp if enemy.max_hp > 0 else 0
    if hp_pct > 0.75:
        current_tier = 0
    elif hp_pct > 0.50:
        current_tier = 1
    elif hp_pct > 0.25:
        current_tier = 2
    else:
        current_tier = 3

    enemy.warp_last_tier   = current_tier
    enemy.warp_on_cooldown = True  # cleared next turn in update_defence_warp_after_enemy_turn

    if current_tier == 3:
        print(f"\n💀 {enemy.name} fights like a cornered animal — wild, desperate, dangerous!")
    else:
        print(f"\n💀 {enemy.name} twists his blade with a warped defence-breaking technique!")
    print("🌀 Your armour shudders as the strike slips past your guard!")

    roll   = random.randint(enemy.max_atk, enemy.max_atk + 3)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    monster_math_breakdown(enemy, warrior, roll, actual, tag="Defence Warp")
    show_health(warrior)

    if actual <= 0:
        return actual
    warp_active = hasattr(warrior, "defence_warp_phase")

    if warrior.defence <= 0 and not warp_active:
        # DEF already at or below 0 — store it so we can restore after warp resolves
        warrior.defence_warp_original_defence = warrior.defence
        warrior.defence_warp_phase = 0
        print(wrap(
            "You feel your armour and body destabilising — "
            "your defence is already compromised, but the warp makes it worse."
        ))
        return actual

    if warp_active:
        warrior.defence_warp_phase = 0
        print(wrap("🌀 The warped curse tightens again — your armour cannot stabilise yet."))
    else:
        warrior.defence_warp_original_defence = warrior.defence
        warrior.defence_warp_phase = 0

    print(wrap(
        "You feel your armour and body destabilising — seams creak and plates rattle. "
        "Your muscles warp and contort. Your defence is coming apart. "
        "You no longer feel protected."
    ))

    if current_tier < 3:
        print(wrap("You have one turn before your defence collapses — act fast!"))

    return actual

def hydra_hatchling_acid_spit(enemy, warrior):
    if enemy.ap <= 0:
        return None

    is_chimera = hasattr(enemy, "chimera_tier1")

    enemy.ap -= 1
    print(wrap(f"\n🐍 {enemy.display_name} spits corrosive acid at you! Your defense is reduced!"))

    # -----------------------------
    # 1) Physical impact (defence applies)
    #    Chimera uses its own ATK (14-18), hydra uses its own stats
    # -----------------------------
    roll = random.randint(enemy.min_atk, enemy.max_atk)

    dealt = monster_deal_damage(
        enemy,
        warrior,
        roll,
        extra_parts=[],
        tag="Acid Spit"
    )

    # -----------------------------
    # 2) Apply Acid Stack + Defence Erosion
    #    Chimera: doubled tick damage (effectively 2 ticks per stack), 3 turns
    #    Hardened Hydra: normal tick, 4 turns
    #    Hydra:   normal tick, 3 turns
    # -----------------------------
    if not hasattr(warrior, "acid_stacks"):
        warrior.acid_stacks = []
    if not hasattr(warrior, "acid_defence_loss"):
        warrior.acid_defence_loss = 0

    is_hardened = getattr(enemy, "level", 1) >= 2
    acid_turns = 3 if not is_hardened else 4
    if is_chimera:
        acid_turns = 3
    acid_multiplier = 2 if is_chimera else 1  # stored so tick handler can apply it

    if len(warrior.acid_stacks) < 3:
        # v0.6.14: tag hardened stacks so tick handler can roll a lower bracket
        # (2-4 vs standard 3-5). Hardened still hits 1 turn longer than standard,
        # so the total HP swing is roughly comparable but easier to survive
        # if the player drinks a tonic mid-fight.
        warrior.acid_stacks.append({
            "turns_left":  acid_turns,
            "skip":        True,
            "multiplier":  acid_multiplier,
            "hardened":    is_hardened and not is_chimera,
        })
    else:
        print("🧪 The acid is already eating at you as much as it can!")

    # Determine effective defence AFTER current erosion
    effective_def = max(0, warrior.defence - warrior.acid_defence_loss)

    # If player has defence remaining, erode it (cap 3 total erosion)
    # Chimera: -2 per hit. Hydra: -1 per hit.
    erosion_amount = 2 if is_chimera else 1
    if effective_def > 0:
        erosion = min(erosion_amount, 3 - warrior.acid_defence_loss)
        if erosion > 0:
            warrior.acid_defence_loss += erosion
        print("🧪 The acid sizzles into your body — you feel weaker!")
    else:
        # Edge case: no defence left → +2 immediate damage
        warrior.hp = max(0, warrior.hp - 2)
        print("🧪 With no defenses left, the acid bites deep! (+2)")
        show_health(warrior)

    return dealt

# =============================
# GOBLIN WARRIOR SPECIAL MOVE
# =============================

def savage_slash(enemy, warrior):
    """
    Goblin Warrior special: Savage Slash
    1) Basic attack fires first (handled by monster_ai_check before calling this).
    2) Immediate bonus damage = half the base attack roll, rounded down, bypasses defence.
    3) Applies bleed stacks — Chimera version: doubled dmg, 1 stack only (no multi-stack).
       Standard: 2 stacks, 3-5 dmg, 2 turns. Hardened: 4-6 dmg, 4 turns.
       Chimera:  1 stack,  6-10 dmg, 2 turns (doubled, no stacking).
    """
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1
    b = lvl_bonus(enemy)
    is_hardened = getattr(enemy, "level", 1) >= 2
    is_chimera  = hasattr(enemy, "chimera_tier1")

    print(f"\n\u2694\ufe0f  {enemy.display_name} lets out a savage war cry and slashes deep!")

    # Bonus damage — half the ATK roll, ignores defence
    # Chimera: 14-18 base roll, bonus is 7-9 (half). No doubling.
    roll  = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    bonus = max(1, roll // 2)
    warrior.hp = max(0, warrior.hp - bonus)
    print(f"\U0001f4a5 Savage Slash: {bonus} bonus damage (ignores defence)!")

    # Bleed — Chimera doubles dmg, applies 1 stack only
    # v0.6.10: Hardened duration reduced 5 -> 4 turns (was deleting players
    # too aggressively when both stacks landed early)
    # v0.6.14: Hardened tick reduced from 4-6 -> 3-5 (now same per-tick as
    # standard). Hardened still distinguished by longer duration (4 vs 2 turns).
    # With hardened AP also dropped from 4 -> 3, the previous 4-6 bracket made
    # an unlucky double-stack a near-deathblow even for level-3/4 players.
    dmg_min = 3
    dmg_max = 5
    turns   = (4 if is_hardened else 2) + (1 if is_chimera else 0)
    if is_chimera:
        dmg_min *= 2
        dmg_max *= 2

    if not hasattr(warrior, "warrior_bleed_dots"):
        warrior.warrior_bleed_dots = []

    max_stacks = 1 if is_chimera else 2
    stacks_applied = 0
    if len(warrior.warrior_bleed_dots) < max_stacks:
        warrior.warrior_bleed_dots.append({
            "dmg_min":    dmg_min,
            "dmg_max":    dmg_max,
            "turns_left": turns,
            "skip":       True,
        })
        stacks_applied += 1

    if stacks_applied > 0:
        variant = "chimera " if is_chimera else ("hardened " if is_hardened else "")
        print(f"\U0001fa78 {stacks_applied} {variant}bleed stack(s) applied! "
              f"({dmg_min}-{dmg_max} dmg/tick for {turns} turns \u2014 starts your next turn)")
    else:
        print("\U0001fa78 Your wounds are already bleeding as much as they can!")

    show_health(warrior)
    return bonus

# =============================
# FLAYED ONE SPECIAL MOVE
# =============================

def psychic_shred(enemy, warrior):
    """
    Flayed One special: Psychic Shred
    33% trigger chance (handled by monster_ai_check).
    Costs 1 AP. Max 3 uses total (hardcoded on enemy).

    Flayed One version: damage-only hit. Stat drain is handled
    exclusively by the charge system (_flayed_charge_tick).
    No ATK/DEF debuff applied here.

    Chimera version: still applies double % ATK+DEF debuff (no stacking).
    Hard cap: 90% reduction on both stats.
    Does NOT interact with First Aid ranks 1-5.
    TODO: Triage (First Aid Rank 6+) will cleanse psychic debuffs.
    """
    if enemy.ap <= 0:
        return None

    # Check use limit (3 max)
    uses_left = getattr(enemy, "psychic_shred_uses", 3)
    if uses_left <= 0:
        return None

    enemy.ap -= 1
    enemy.psychic_shred_uses = uses_left - 1

    is_chimera = hasattr(enemy, "chimera_tier1")

    # --- Physical hit (defence applies) ---
    roll  = random.randint(enemy.min_atk, enemy.max_atk)
    dealt = monster_deal_damage(enemy, warrior, roll, tag="Psychic Shred")

    print(wrap(
        f"\n🧠 {enemy.display_name} tears at your mind — your body feels like it's "
        "being cut apart even though your skin is untouched!"
    ))

    # -------------------------------------------------------
    # Flayed One: damage only — charge system handles stat drain
    # -------------------------------------------------------
    if not is_chimera:
        print(wrap(
            "😣 You feel yourself growing weaker... the Flayed One seems to revel in your pain."
        ))
        show_health(warrior)
        return dealt

    # -------------------------------------------------------
    # Chimera only: apply doubled ATK+DEF debuff (no stacking)
    # -------------------------------------------------------
    is_hardened = getattr(enemy, "level", 1) >= 2
    debuff_pct  = 0.30                            # flat 30% for Chimera — no doubling
    duration    = (4 if is_hardened else 2) + 1  # always +1 for chimera

    # Warn player if 0 DEF doubles the ATK penalty
    if getattr(warrior, "psychic_base_defence", warrior.defence) == 0 or warrior.defence == 0:
        print(wrap(
            "⚠️ You have no armour to absorb the psychic assault — "
            "your ATK penalty is doubled!"
        ))

    # Initialise psychic debuff tracking on warrior if needed
    if not hasattr(warrior, "psychic_atk_debuff"):
        warrior.psychic_atk_debuff   = 0.0
        warrior.psychic_def_debuff   = 0.0
        warrior.psychic_debuff_turns = 0

    # Chimera: always fresh application, no stacking
    warrior.psychic_atk_debuff   = debuff_pct
    warrior.psychic_def_debuff   = debuff_pct
    warrior.psychic_debuff_turns = duration
    warrior.psychic_debuff_skip  = True

    print(wrap(
        f"🧠 Your ATK and DEF will be reduced by {int(debuff_pct * 100)}% "
        f"starting next round for {duration} turns! (First Aid cannot treat psychic wounds.)"
    ))

    # Apply the debuff to the warrior's actual stats (only if not skipping first round)
    if not getattr(warrior, "psychic_debuff_skip", False):
        _apply_psychic_debuff_to_stats(warrior)

    show_health(warrior)
    return dealt

def _apply_psychic_debuff_to_stats(warrior):
    """
    Recalculates effective ATK and DEF from base values using current
    psychic debuff percentages. Stores originals on first call.

    Rounding rules (favour the defender):
      Player being debuffed  → reduction rounds UP   (math.ceil on reduction)
      Enemy being debuffed   → reduction rounds DOWN  (math.floor on reduction)
    Both use the REDUCTION amount so we never get float ATK/DEF on the object.

    DEF of 0 is safe — max(0, ...) clamps it and we skip the calculation cleanly.
    ATK floor is 1 — player always keeps at least 1 ATK even at 90% reduction.
    """
    if not hasattr(warrior, "psychic_base_min_atk"):
        warrior.psychic_base_min_atk = warrior.min_atk
        warrior.psychic_base_max_atk = warrior.max_atk
        warrior.psychic_base_defence = warrior.defence

    atk_pct = getattr(warrior, "psychic_atk_debuff", 0.0)
    def_pct = getattr(warrior, "psychic_def_debuff", 0.0)

    # Enemies have display_name but no inventory — use that to detect who is who
    is_enemy = hasattr(warrior, "display_name") and not hasattr(warrior, "inventory")

    if is_enemy:
        # Enemy debuffed by Charged Jagged Rock — round reduction DOWN (favour enemy)
        min_atk_loss = math.floor(warrior.psychic_base_min_atk * atk_pct)
        max_atk_loss = math.floor(warrior.psychic_base_max_atk * atk_pct)
        def_loss     = math.floor(warrior.psychic_base_defence  * def_pct)
    else:
        # Player debuffed by Psychic Shred — round reduction UP (worse for player)
        # If player has 0 DEF, the psychic assault hits harder — ATK penalty doubles.
        effective_atk_pct = min(0.90, atk_pct * 2) if warrior.psychic_base_defence == 0 else atk_pct
        min_atk_loss = math.ceil(warrior.psychic_base_min_atk * effective_atk_pct)
        max_atk_loss = math.ceil(warrior.psychic_base_max_atk * effective_atk_pct)
        def_loss     = math.ceil(warrior.psychic_base_defence  * def_pct)

    # Guarantee at least 1 point of reduction on ATK — Psychic Shred always does something
    min_atk_loss = max(1, min_atk_loss)
    max_atk_loss = max(1, max_atk_loss)
    # DEF loss can be 0 if DEF is already 0 — no guarantee needed there

    warrior.min_atk = max(1, warrior.psychic_base_min_atk - min_atk_loss)
    warrior.max_atk = max(warrior.min_atk, warrior.psychic_base_max_atk - max_atk_loss)

    # DEF of 0: no calculation needed, stays 0. No floor of 1 — DEF CAN be 0.
    if warrior.psychic_base_defence == 0:
        warrior.defence = 0
    else:
        warrior.defence = max(0, warrior.psychic_base_defence - def_loss)

def _clear_psychic_debuff(warrior):
    """
    Fully restores ATK and DEF from stored base values and zeroes
    all psychic debuff tracking fields.
    Called when psychic_debuff_turns reaches 0.

    Monsters have psychic_base_* set permanently at spawn — don't delete them
    so they're always ready for the next application.
    Player base stats are deleted so they're recalculated fresh next fight
    (player stats can change between fights via gear/upgrades).
    """
    is_monster = hasattr(warrior, "display_name") and not hasattr(warrior, "inventory")

    if hasattr(warrior, "psychic_base_min_atk"):
        warrior.min_atk = warrior.psychic_base_min_atk
        warrior.max_atk = warrior.psychic_base_max_atk
        warrior.defence = warrior.psychic_base_defence
        if not is_monster:
            del warrior.psychic_base_min_atk
            del warrior.psychic_base_max_atk
            del warrior.psychic_base_defence

    warrior.psychic_atk_debuff   = 0.0
    warrior.psychic_def_debuff   = 0.0
    warrior.psychic_debuff_turns = 0
    warrior.psychic_debuff_skip  = False
    warrior.psychic_exposed      = False

def trigger_pressure_feedback(hero, enemy):
    """
    Called after any AP move fires while Psychic Drown is active.
    If hero has a Pressure Stone accessory equipped, enemy recovers 1 AP.
    TODO: wire Pressure Stone accessory stats when item is built.
    For now this is a stub hook so the plumbing is visible during testing.
    """
    if getattr(hero, "drown_stacks", 0) <= 0:
        return
    acc = hero.equipment.get("accessory") if hasattr(hero, "equipment") else None
    if acc and getattr(acc, "pressure_feedback", False):
        recovered = min(1, enemy.max_ap - enemy.ap)
        if recovered > 0:
            enemy.ap += recovered
            print(wrap(
                f"\u26a1 Pressure Feedback! The {enemy.display_name} draws energy "
                f"from your exertion and recovers {recovered} AP!"
            ))

def check_drown_punishment(warrior):
    """
    Called at the start of the player's turn if Psychic Drown is active.
    Punishment fires only when current AP = 0 — completely locked out.
    The main pressure of drown is AP inflation making skills unaffordable.
    True damage is the last resort penalty for being fully AP-drained.

    Damage table (standard):   1 stack=2, 2 stacks=3, 3 stacks=4
    Damage table (hardened):   1 stack=5, 2 stacks=6, 3 stacks=7
    """
    stacks = getattr(warrior, "drown_stacks", 0)
    if stacks <= 0:
        return

    # Only punish if completely out of AP — inflation already creates
    # enough pressure by locking skills; damage on top would be a death spiral
    if warrior.ap > 0:
        return

    # Determine damage from stack count
    is_hardened = getattr(warrior, "drown_hardened_source", False)
    DAMAGE_TABLE = {1: 5, 2: 6, 3: 7} if is_hardened else {1: 2, 2: 3, 3: 4}
    dmg = DAMAGE_TABLE.get(stacks, 4)

    warrior.hp = max(0, warrior.hp - dmg)
    print(wrap(
        f"\n💧 The drowning pressure is overwhelming — your lungs burn! "
        f"You cannot muster the strength for any special move. "
        f"({dmg} true damage, ignores defence)"
    ))
    show_health(warrior)

# =============================
# DROWNED ONE SPECIAL MOVE
# =============================

def psychic_drown(enemy, warrior):
    """
    Drowned One special: Psychic Drown
    33% trigger chance (handled by monster_ai_check).
    Costs 1 AP. Max 3 uses total (hardcoded on enemy).

    Standard Drowned One:  +1 AP inflation per stack, 3-turn duration
    Hardened Drowned One:  same inflation, 6-turn duration
    (hardened detected via enemy.level >= 2)

    Stacking: each application adds +1 stack (max 3), refreshes duration.
    At 3 stacks all rank-1 moves cost 4 AP.

    Punishment: enemy gets a flat +3 min/max ATK boost applied on first stack.
    Does not multiply with additional stacks — one boost for the duration.
    Defence applies normally so armour absorbs the boosted hits.
    Boost is reversed when drown expires or between rounds.

    Does NOT interact with First Aid ranks 1-5.
    TODO: Triage (First Aid Rank 6+) will cleanse psychic debuffs.
    """
    if enemy.ap <= 0:
        return None

    uses_left = getattr(enemy, "psychic_drown_uses", 3)
    if uses_left <= 0:
        return None

    enemy.ap -= 1
    enemy.psychic_drown_uses = uses_left - 1

    is_hardened = getattr(enemy, "level", 1) >= 2
    is_chimera  = hasattr(enemy, "chimera_tier1")
    duration    = (6 if is_hardened else 3) + (1 if is_chimera else 0)
    # --- Physical hit (defence applies) ---
    roll  = random.randint(enemy.min_atk, enemy.max_atk)
    dealt = monster_deal_damage(enemy, warrior, roll, tag="Psychic Drown")

    print(wrap(
        f"\n\U0001f4a7 {enemy.display_name} reaches into your mind \u2014 your lungs fill with "
        "phantom water! Every exertion feels twice as hard!"
    ))

    # Initialise drown tracking on warrior if needed
    if not hasattr(warrior, "drown_stacks"):
        warrior.drown_stacks          = 0
        warrior.drown_turns           = 0
        warrior.drown_hardened_source = False

    current_stacks = warrior.drown_stacks

    if is_chimera:
        # Chimera: double AP inflation but max 1 stack, no compounding
        inflation = 2  # +2 AP per skill instead of +1
        if current_stacks == 0:
            warrior.drown_stacks          = 1
            warrior.drown_turns           = duration
            warrior.drown_hardened_source = False
            print(wrap(
                f"\U0001f4a7 Chimera Drown! All special move AP costs +{inflation} "
                f"for {duration} turns!"
            ))
        else:
            # Already drowning — just refresh, no extra stack
            warrior.drown_turns = duration
            print(wrap(
                f"\U0001f4a7 The chimera reinforces the drowning sensation! "
                f"Duration refreshed to {duration} turns."
            ))
        # Override drown inflation for chimera — store on warrior
        warrior.drown_chimera_inflation = inflation
    elif current_stacks >= 3:
        # Already at max stacks — just refresh duration
        warrior.drown_turns = duration
        print(wrap(
            f"\U0001f4a7 The drowning sensation intensifies but cannot get worse! "
            f"Duration refreshed to {duration} turns."
        ))
    else:
        # Add a stack and refresh duration
        warrior.drown_stacks          = current_stacks + 1
        warrior.drown_turns           = duration
        warrior.drown_hardened_source = is_hardened
        inflation = warrior.drown_stacks

        print(wrap(
            f"\U0001f4a7 Stack {warrior.drown_stacks}/3! All special move AP costs "
            f"+{inflation} for {duration} turns!"
        ))

    show_health(warrior)
    return dealt

def _clear_psychic_drown(warrior, enemy=None):
    """
    Zeroes all drown tracking fields on warrior.
    Called on expiry in collect_dot_ticks and in reset_between_rounds.
    Dynamic ATK gap boost is applied/removed per enemy turn — no cleanup needed here.
    """
    warrior.drown_stacks            = 0
    warrior.drown_turns             = 0
    warrior.drown_hardened_source   = False
    warrior.drown_chimera_inflation = 0

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
            hp=20,
            min_atk=4,
            max_atk=6,
            gold=0,
            xp=19,
            essence=["goblin archer essence"],
            defence=2,
            ap=3
        )
        self.special_move = paralyzing_shot

class Goblin_Warrior(Monster):
    def __init__(self):
        super().__init__(
            name="Goblin Warrior",
            hp=40,
            min_atk=5,  # v0.6.15: 7 -> 6 (was outhitting Fallen)
            max_atk=9, # v0.6.15: 11 -> 10
            gold=0,
            xp=40,
            essence=["goblin warrior essence"],
            defence=5,  # v0.6.15: 6 -> 5 (tier 3 DEF rebalance — was higher than Fallen)
            ap=5,
        )
        self.special_move = savage_slash

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

        self.special_move = rot_thrust

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
            hp=21,                       # buffed tier 2 pass: +5 HP
            min_atk=5,                   # +1 ATK
            max_atk=7,
            gold=0,
            xp=21,
            essence=["dire wolf pup essence"],
            defence=4,
            ap=3,
        )
        self.loot_drop = "dire_wolf_pelt"
        self.special_move = devouring_bite

class Red_Slime(Monster):
    def __init__(self):
        super().__init__(
            name = "red slime",
            hp=21,
            min_atk=3,
            max_atk=5,
            gold=0,
            xp=18,
            essence=["red slime essence"],
            defence=2,
            ap=3
        )
        self.special_move = red_slime_fire_spit         

class Fallen_Warrior(Monster):
    def __init__(self):
        super().__init__(
            name="Fallen Warrior",
            hp=65,       # v0.6.15: 60 -> 65 (boss-tier durability bump)
            min_atk=7,   # v0.6.15: 6 -> 7 (now outhits Goblin Warrior & Drowned One)
            max_atk=11,  # v0.6.15: 10 -> 11
            gold=0,
            xp=75,
            essence=["fallen warrior essence"],
            defence=6,  # v0.6.15: 5 -> 6 (prologue boss should outrank tier 3s in DEF)
            ap=5
        )
        self.special_move = fallen_defence_warp

class Noob_Ghost(Monster):
    def __init__(self):
        super().__init__(
            name="Noob Ghost",
            hp=21,
            min_atk=4,
            max_atk=7,
            gold=0,
            xp=15,
            essence=["ghost essence"],
            defence=1,
            ap=3
        )

        # 👻 Overheal pool so life drain is never "wasted"
        self.max_overheal = int(self.max_hp * 1.5)

        # Hook up the life leech special
        self.special_move = ghost_life_leech

class Wolf_Pup_Rider(Monster):
    def __init__(self):
        super().__init__(name= "Wolf Pup Rider",
                         hp=31,
                         min_atk=5,
                         max_atk=9,
                         gold=0,
                         xp=28,
                         essence=["wolf pup rider essence"],
                         defence=5,
                         ap = 4
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
            hp=23,
            min_atk=4,
            max_atk=7,
            gold= 0,
            xp=20,
            essence=["javelina essence"],
            defence=3,
            ap=3,
            
            
        )
        self.special_move = impact_bite

class Hydra_Hatchling(Monster):
    def __init__(self):
        super().__init__(
            name="Hydra Hatchling",
            hp=35,
            min_atk=5,
            max_atk=8,
            gold=0,
            xp=33,
            essence=["hydra hatchling essence"],
            defence=4,  # v0.6.15: 5 -> 4 (tier 3 DEF rebalance)
            ap=4
        )
        self.loot_drop = "acid sack"
        self.special_move = hydra_hatchling_acid_spit

class Flayed_One(Monster):
    def __init__(self):
        super().__init__(
            name="Flayed One",
            hp=33,
            min_atk=6,
            max_atk=8,
            gold=0,
            xp=30,
            essence=["flayed one essence"],
            defence=3,  # v0.6.15: 4 -> 3 (tier 3 DEF rebalance)
            ap=4
        )
        self.loot_drop = "charged jagged rock"
        self.special_move = psychic_shred
        self.psychic_shred_uses = 3   # hard cap — 3 uses total per fight
        # Flayed charge system: starts at 1, fills 0.25 per damage point through defence
        # Each charge: Flayed One +1 ATK, player -1 ATK/-1 DEF. Cap 5.
        self.flayed_charges  = 1
        self.flayed_pool     = 1.0    # start at 1 full charge (pool per charge = 1)
        self.flayed_fill_rate = 0.25
        self.flayed_max_charges = 5

class Drowned_One(Monster):
    def __init__(self):
        super().__init__(
            name="Drowned One",
            hp=37,
            min_atk=6,  # v0.6.15: 7 -> 6 (was tying Fallen max)
            max_atk=9,  # v0.6.15: 10 -> 9
            gold=0,
            xp=36,
            essence=["drowned one essence"],
            defence=4,  # v0.6.15: 5 -> 4 (tier 3 DEF rebalance)
            ap=5
        )
        self.special_move = psychic_drown
        self.psychic_drown_uses = 3   # hard cap — 3 uses total per fight

# ===============================
# Hidden Boss — Young Chimera
# ===============================

# Move pools the chimera draws from on spawn
CHIMERA_TIER1_POOL = [
    slime_poison_spit,
    goblin_cheap_shot,
    imp_sneak_attack,
    rot_thrust,           # Brittle Skeleton's move — renamed from precise thrust
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
    savage_slash,
    psychic_shred,
    psychic_drown,
]

CHIMERA_ELEMENTS = ["fire", "poison", "acid", "paralyze"]

def primordial_surge(enemy, warrior, fury_triggered=False):
    """
    Chimera's signature move — Primordial Surge.
    Fury-triggered only — fires when chimera_fury_charge hits 100.

    Damage: Full ATK roll — ignores defence entirely.
    Also permanently degrades player stats for this fight:
      -10% current max ATK, -10% current DEF, -10% current max HP (restores after combat).

    fury_triggered=True suppresses the charge counter display (fury pop has no charge cost).
    """
    import math

    charges_left = getattr(enemy, "primordial_charges", 0)

    print(wrap(
        f"\n🌀 The Young Chimera rears back — reality fractures around it!"
    ))
    if fury_triggered:
        print(wrap(
            f"✨ PRIMORDIAL SURGE! (Fury Overload — ignores defence!)"
        ))
    else:
        print(wrap(
            f"✨ PRIMORDIAL SURGE! ({charges_left} charge{'s' if charges_left != 1 else ''} remaining)"
        ))

    # Full ATK roll as true damage — ignores defence entirely
    b      = lvl_bonus(enemy)
    roll   = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    actual = roll
    warrior.hp = max(0, warrior.hp - actual)
    monster_math_breakdown(enemy, warrior, roll, actual,
                           tag="Primordial Surge (true damage, ignores DEF)",
                           ignore_defence=True)

    # Permanent stat degradation — 10% of current stats, min 1
    atk_loss = max(1, int(warrior.max_atk * 0.10))
    def_loss = max(1, int(warrior.defence * 0.10)) if warrior.defence > 0 else 0
    hp_loss  = max(1, int(warrior.max_hp  * 0.10))

    if not hasattr(warrior, "primordial_atk_loss"):
        warrior.primordial_atk_loss = 0      # tracks MIN atk loss (see note)
        warrior.primordial_def_loss = 0
        warrior.primordial_hp_loss  = 0
    # v0.6.21: track max-atk loss separately. min and max floor against
    # different bounds (min floors at 1, max floors at the new min), so a
    # single atk tracker can't faithfully restore both.
    if not hasattr(warrior, "primordial_max_atk_loss"):
        warrior.primordial_max_atk_loss = 0

    # v0.6.21 BUG FIX: record the ACTUAL floored delta, not the intended
    # loss. Previously we subtracted with a floor (max(1, ...)/max(0, ...))
    # but recorded the full intended `*_loss`. When a stat was low enough
    # that the floor clamped the subtraction, the post-combat restore added
    # back MORE than was taken — a permanent stat *gain* from being hit by
    # Surge (reproduced: min_atk 2 → 4 after 3 surges + restore). Capturing
    # the real before/after delta makes the round-trip net to zero.
    _old_min_atk = warrior.min_atk
    _old_max_atk = warrior.max_atk
    _old_def     = warrior.defence
    _old_max_hp  = warrior.max_hp

    warrior.min_atk = max(1, warrior.min_atk - atk_loss)
    warrior.max_atk = max(warrior.min_atk, warrior.max_atk - atk_loss)
    warrior.defence = max(0, warrior.defence - def_loss)
    warrior.max_hp  = max(1, warrior.max_hp - hp_loss)
    warrior.hp      = min(warrior.hp, warrior.max_hp)

    actual_min_atk_loss = _old_min_atk - warrior.min_atk
    actual_max_atk_loss = _old_max_atk - warrior.max_atk
    actual_def_loss     = _old_def     - warrior.defence
    actual_hp_loss      = _old_max_hp  - warrior.max_hp

    warrior.primordial_atk_loss     += actual_min_atk_loss
    warrior.primordial_max_atk_loss += actual_max_atk_loss
    warrior.primordial_def_loss     += actual_def_loss
    warrior.primordial_hp_loss      += actual_hp_loss

    print(wrap(
        f"💀 The primordial energy tears at your very essence! "
        f"ATK -{actual_max_atk_loss} (-10%), DEF -{actual_def_loss} (-10%), "
        f"Max HP -{actual_hp_loss} (-10%) (restores after combat)"
    ))
    show_health(warrior)
    return actual

def _restore_primordial_stats(warrior):
    """Restores stats degraded by Primordial Surge after combat ends.

    v0.6.21: min and max ATK are tracked separately (primordial_atk_loss =
    min, primordial_max_atk_loss = max) because they floor against different
    bounds during degradation. Restoring them with one shared value would
    re-introduce the over/under-credit the actual-delta fix removed.
    """
    min_atk = getattr(warrior, "primordial_atk_loss", 0)
    max_atk = getattr(warrior, "primordial_max_atk_loss", 0)
    df      = getattr(warrior, "primordial_def_loss", 0)
    hp      = getattr(warrior, "primordial_hp_loss", 0)
    if min_atk > 0 or max_atk > 0 or df > 0 or hp > 0:
        warrior.min_atk += min_atk
        warrior.max_atk += max_atk
        warrior.defence += df
        warrior.max_hp  += hp
        warrior.primordial_atk_loss     = 0
        warrior.primordial_max_atk_loss = 0
        warrior.primordial_def_loss     = 0
        warrior.primordial_hp_loss      = 0

def _restore_patronus_def(warrior):
    """Restores DEF reduced by Patronus Defence Break after combat ends."""
    reduction = getattr(warrior, "patronus_def_reduction", 0)
    if reduction > 0:
        warrior.defence += reduction
        warrior.patronus_def_reduction = 0
        warrior.patronus_def_turns     = 0

def chimera_boost(enemy):
    """Returns 1 if chimera_extra_turns flag is set, else 0. Used for +1 turn duration."""
    return 1 if getattr(enemy, "chimera_extra_turns", False) else 0

def chimera_double(enemy, value):
    """Doubles a damage/roll value if chimera_extra_turns is set. Returns int, min 1."""
    if getattr(enemy, "chimera_extra_turns", False):
        return max(1, int(value * 2))
    return value

def chimera_triple(enemy, value):
    """Triples a damage/roll value when the Chimera is the attacker. Returns int, min 1.
    Used for tier 1 borrowed moves — light moves hit 3x harder from the Chimera."""
    is_chimera = hasattr(enemy, "chimera_tier1")  # only Young_Chimera has this attribute
    if is_chimera:
        return max(1, int(value * 3))
    return value

def chimera_combo_bonus(enemy, warrior, move_result, tier=1):
    """
    Chimera combo system — fires after every borrowed special move.
    Follow-through scales with tier so light moves don't stack into massive combos.
      tier 1 — light tap   (2–5)
      tier 2 — medium hit  (5–10)
      tier 3 — full weight (8–14)
    """
    b = lvl_bonus(enemy)

    tier_range = {
        1: (2, 5),
        2: (5, 10),
        3: (8, 14),
    }
    lo, hi = tier_range.get(tier, (5, 10))

    basic_roll = random.randint(lo + b, hi + b)
    basic_dealt = warrior.apply_defence(basic_roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - basic_dealt)

    print(wrap(f"💥 The Chimera follows through! [{basic_dealt} physical]"))
    show_health(warrior)
    return basic_dealt

def chimera_special_dispatcher(enemy, warrior):
    """
    Each turn the chimera randomly picks one of its three move slots.
    Charge-based — tier1=5, tier2=4, tier3=3.
    Primordial Surge is fury-only — NOT in this pool.
    Dispatcher decrements the right charge counter before calling the move.
    Borrowed moves' internal ap checks pass because ap=99 (dummy pool).
    Tier 3 borrowed moves get +1 turn duration via chimera_extra_turns flag.

    Slots:
      Tier 1 — borrowed light move   (5 charges)
      Tier 2 — borrowed mid move     (4 charges)
      Tier 3 — borrowed heavy move   (3 charges)
    """
    moves = [
        enemy.chimera_tier1,
        enemy.chimera_tier2,
        enemy.chimera_tier3,
    ]

    # Map move → charge attribute name
    charge_attr = {
        enemy.chimera_tier1: "charges_tier1",
        enemy.chimera_tier2: "charges_tier2",
        enemy.chimera_tier3: "charges_tier3",
    }

    # Escalating weights by turn count
    turn = getattr(enemy, "turns_survived", 0)
    last = getattr(enemy, "chimera_last_move", None)

    if random.random() < 0.20:
        base_weights = {
            enemy.chimera_tier1: 3,
            enemy.chimera_tier2: 3,
            enemy.chimera_tier3: 3,
        }
    elif turn <= 3:
        base_weights = {
            enemy.chimera_tier1: 5,
            enemy.chimera_tier2: 2,
            enemy.chimera_tier3: 1,
        }
    elif turn <= 6:
        base_weights = {
            enemy.chimera_tier1: 2,
            enemy.chimera_tier2: 5,
            enemy.chimera_tier3: 2,
        }
    else:
        base_weights = {
            enemy.chimera_tier1: 1,
            enemy.chimera_tier2: 2,
            enemy.chimera_tier3: 4,
        }

    # Reduce weight of last used move
    if last in base_weights:
        base_weights[last] = max(1, base_weights[last] - 2)

    # Filter out moves with no charges remaining
    available = [
        (m, base_weights[m]) for m in moves
        if getattr(enemy, charge_attr[m], 0) > 0
    ]
    if not available:
        return None

    moves_a, weights_a = zip(*available)
    chosen = random.choices(moves_a, weights=list(weights_a), k=1)[0]

    # Decrement the chosen move's charge
    attr = charge_attr[chosen]
    setattr(enemy, attr, getattr(enemy, attr) - 1)

    # Track last used move
    enemy.chimera_last_move = chosen
    enemy.chimera_last_move_name = SPECIAL_MOVE_NAMES.get(
        getattr(chosen, "__name__", ""),
        chosen.__name__.replace("_", " ").title()
    )

    # Duration bonus for tier 3 borrowed moves only
    enemy.chimera_extra_turns = (chosen is enemy.chimera_tier3)
    if enemy.chimera_extra_turns:
        print(wrap(f"⚠️ The Young Chimera channels its power! (+1 turn duration)"))

    # Dispatch
    if chosen is paralyzing_shot:
        result = paralyzing_shot(enemy, warrior, paralyze_turns=2)
    else:
        result = chosen(enemy, warrior)

    enemy.chimera_extra_turns = False

    # Combo follow-through
    tier = 1 if chosen is enemy.chimera_tier1 else 2 if chosen is enemy.chimera_tier2 else 3
    chimera_combo_bonus(enemy, warrior, result, tier=tier)

    return result

class Young_Chimera(Monster):
    def __init__(self):
        super().__init__(
            name="Young Chimera",
            hp=80,
            min_atk=14,
            max_atk=18,
            gold=0,
            xp=0,            # no XP — true final boss of the good path
            essence=[],
            defence=8,
            ap=99,           # dummy pool — borrowed moves gate on ap internally,
                             # actual resource management is charge-based via dispatcher
        )
        self.tier = 5        # above tier 4 boss — own AI tier

        # Roll borrowed moves fresh on spawn — different every fight
        self.chimera_tier1 = random.choice(CHIMERA_TIER1_POOL)
        self.chimera_tier2 = random.choice(CHIMERA_TIER2_POOL)
        self.chimera_tier3 = random.choice(CHIMERA_TIER3_POOL)

        # Passive — Chimera Carapace: 20% base player ATK reduction always active.
        # +15% more (35% total) if tier 3 draw is psychic_shred (Flayed One's move).
        self.chimera_atk_reduction = 0.20
        if self.chimera_tier3 is psychic_shred:
            self.chimera_atk_reduction += 0.15

        # Dispatcher handles all four move slots
        self.special_move = chimera_special_dispatcher

        # Per-tier charge counts — dispatcher decrements before calling move
        self.charges_tier1 = 5   # light moves — more uses
        self.charges_tier2 = 4   # mid moves
        self.charges_tier3 = 3   # heavy moves — fewer uses
        # Primordial Surge is fury-only — no dispatcher charges needed

        # Fury Charge — builds when player uses ranked skills (rank * 10 per use)
        # At 100: warns player this turn, next turn fires basic ATK + Primordial Surge
        self.chimera_fury_charge    = 0
        self.chimera_fury_overloading = False   # True = surge fires next turn

        # Cooldown tracking — alternates special/basic each turn
        self.chimera_used_special = False
        self.chimera_last_move    = None

        # Cycle tracking
        self.combat_cycles = 0
        self.primordial_triggered = False

        # Announce loadout on spawn
        t1 = self.chimera_tier1.__name__.replace("_", " ").title()
        t2 = self.chimera_tier2.__name__.replace("_", " ").title()
        t3 = self.chimera_tier3.__name__.replace("_", " ").title()
        self.spawn_flavour = (
            f"The Young Chimera shifts, revealing its nature...\n"
            f"  🐾 It moves like something from the lower dens...\n"
            f"  🌀 Its body pulses with a darker energy...\n"
            f"  🏔️ A shadow of the deep wilds clings to it...\n"
            f"  ✨ It radiates raw primordial power."
        )
        if self.chimera_tier3 is psychic_shred:
            self.spawn_flavour += "\n  🩸 Its hide pulses with corrupted energy — your strikes feel dulled..."
        if self.chimera_tier1 is rot_thrust:
            self.spawn_flavour += "\n  🟫 A faint smell of decay clings to its claws — its touch rots the flesh."

# ===============================
# PATRONUS — Enemy Skill Functions
# ===============================

HEAL_PERCENTS_ENEMY = {
    1: 0.10,
    2: 0.20,
    3: 0.30,
    4: 0.40,
}

def patronus_double_strike(enemy, warrior):
    """
    Patronus Double Strike — 3 charges.
    Hits twice through defence. Main damage move.
    No AP cost — charge based.
    """
    if getattr(enemy, "charges_double_strike", 0) <= 0:
        return None
    enemy.charges_double_strike -= 1

    b = lvl_bonus(enemy)

    roll1  = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    dealt1 = monster_deal_damage(enemy, warrior, roll1, tag="Double Strike I")

    roll2  = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    dealt2 = monster_deal_damage(enemy, warrior, roll2, tag="Double Strike II")

    total = dealt1 + dealt2
    charges_left = enemy.charges_double_strike
    print(wrap(
        f"⚔️⚔️ PATRONUS — DOUBLE STRIKE! "
        f"[{dealt1} + {dealt2} = {total} total] "
        f"({charges_left} use{'s' if charges_left != 1 else ''} remaining)"
    ))
    show_health(warrior)
    return total

def patronus_war_cry(enemy):
    """
    Patronus War Cry — 2 charges.
    Buffs own ATK by 50% of max_atk (min +1) for 3 turns. No AP cost — charge based.
    Boss-tier version of the player's Rank 5 War Cry (35%) — Patronus exceeds player ceiling.
    Future-proofs scaling — if Patronus's base ATK ever rises (sequel/arena tiers),
    the buff scales with him automatically.
    """
    if getattr(enemy, "charges_war_cry", 0) <= 0:
        return False
    enemy.charges_war_cry -= 1

    pct   = 0.50
    bonus = max(1, math.ceil(enemy.max_atk * pct))
    turns = 3
    enemy.war_cry_bonus = bonus
    enemy.war_cry_turns = turns
    enemy.min_atk += bonus
    enemy.max_atk += bonus

    charges_left = enemy.charges_war_cry
    print(wrap(
        f"🗣️ Patronus lets out a BATTLE CRY — "
        f"his attacks surge with power! (+{bonus} ATK for {turns} turns) "
        f"({int(pct * 100)}% of ATK) "
        f"({charges_left} use{'s' if charges_left != 1 else ''} remaining)"
    ))
    return True

def patronus_power_charge(enemy, warrior):
    """
    Patronus Power Charge — 2 charges. Hidden combo (Double Strike + War Cry, weaker forms).
    Hits at 1.5x damage + applies a partial War Cry buff (25% of max_atk, min +1) for 2 turns.
    The reduced multipliers (1.5x vs Double Strike's 2 hits, 25% vs War Cry's 50%) reflect
    the cost of doing both at once.
    Stacks additively with active War Cry — if War Cry is up, the bonuses combine.
    Costs 2 AP — the only move that still uses AP, reflecting its special nature.
    """
    if getattr(enemy, "charges_power_charge", 0) <= 0:
        return None
    if enemy.ap < 2:
        return None
    enemy.charges_power_charge -= 1
    enemy.ap -= 2

    b = lvl_bonus(enemy)

    # 1.5x damage hit (Double Strike component, weaker form)
    raw     = random.randint(enemy.min_atk + b, enemy.max_atk + b)
    boosted = max(1, int(raw * 1.5))
    dealt   = monster_deal_damage(enemy, warrior, boosted, tag="Power Charge")

    # 25% ATK buff (War Cry component, weaker form — half of full War Cry's 50%)
    # NOTE: enemy.max_atk here may already include an active War Cry bonus.
    # We compute the buff against the BASE max_atk so stacking stays predictable.
    base_max_atk = enemy.max_atk - getattr(enemy, "war_cry_bonus", 0)
    pct          = 0.25
    buff         = max(1, math.ceil(base_max_atk * pct))
    turns        = 2

    # Stack additively with any active War Cry bonus, extend duration if longer
    enemy.war_cry_bonus = getattr(enemy, "war_cry_bonus", 0) + buff
    enemy.war_cry_turns = max(getattr(enemy, "war_cry_turns", 0), turns)
    enemy.min_atk += buff
    enemy.max_atk += buff

    charges_left = enemy.charges_power_charge
    print(wrap(
        f"💥 PATRONUS — POWER CHARGE! "
        f"[{dealt} damage + +{buff} ATK for {turns} turns] "
        f"({int(pct * 100)}% of base ATK) "
        f"({charges_left} use{'s' if charges_left != 1 else ''} remaining)"
    ))
    show_health(warrior)
    return dealt

def patronus_first_aid(enemy):
    """
    Patronus First Aid — 1 charge, locked at Rank 4 (40% max HP heal).
    Only fires when missing HP. No AP cost — charge based.
    """
    if getattr(enemy, "charges_first_aid", 0) <= 0:
        return False
    if enemy.hp >= enemy.max_hp:
        return False
    enemy.charges_first_aid -= 1

    rank   = getattr(enemy, "patronus_heal_rank", 1)
    pct    = HEAL_PERCENTS_ENEMY[rank]
    amount = math.ceil(enemy.max_hp * pct)
    before = enemy.hp
    enemy.hp = min(enemy.max_hp, enemy.hp + amount)
    actual = enemy.hp - before

    charges_left = enemy.charges_first_aid
    print(wrap(
        f"🩹 Patronus tends to his wounds — recovers {actual} HP! "
        f"(First Aid Rank {rank}, {charges_left} use{'s' if charges_left != 1 else ''} remaining)"
    ))
    show_health(enemy)
    return True

def patronus_defence_break(enemy, warrior):
    """
    Patronus Defence Break — 3 charges, locked at Rank 4 (max DEF strip).
    Reduces warrior DEF by percentage for 2-3 turns. No AP cost — charge based.
    Fires early — priority opener to strip player DEF before Double Strike lands.
    """
    if getattr(enemy, "charges_defence_break", 0) <= 0:
        return None
    enemy.charges_defence_break -= 1

    rank      = getattr(enemy, "patronus_db_rank", 1)
    pct, turns = DEFENCE_BREAK_STATS[rank]
    reduction = max(1, int(warrior.defence * pct))

    warrior.defence = max(0, warrior.defence - reduction)

    if not hasattr(warrior, "patronus_def_reduction"):
        warrior.patronus_def_reduction = 0
    warrior.patronus_def_reduction += reduction
    warrior.patronus_def_turns      = turns

    charges_left = enemy.charges_defence_break
    print(wrap(
        f"🛡️ Patronus shatters your guard! "
        f"Your DEF reduced by {reduction} for {turns} turns! "
        f"(Defence Break Rank {rank}, {charges_left} use{'s' if charges_left != 1 else ''} remaining)"
    ))
    show_health(warrior)
    return reduction

def _tick_patronus_war_cry(enemy):
    """Ticks down Patronus War Cry buff each enemy turn. Restores ATK on expiry."""
    if getattr(enemy, "war_cry_turns", 0) > 0:
        enemy.war_cry_turns -= 1
        if enemy.war_cry_turns <= 0:
            bonus = getattr(enemy, "war_cry_bonus", 0)
            enemy.min_atk = max(1, enemy.min_atk - bonus)
            enemy.max_atk = max(enemy.min_atk, enemy.max_atk - bonus)
            enemy.war_cry_bonus = 0
            print(wrap("Patronus's battle fury subsides..."))

def _tick_patronus_def_break(warrior):
    """Ticks down Defence Break debuff on warrior each turn. Restores DEF on expiry."""
    if getattr(warrior, "patronus_def_turns", 0) > 0:
        warrior.patronus_def_turns -= 1
        if warrior.patronus_def_turns <= 0:
            reduction = getattr(warrior, "patronus_def_reduction", 0)
            if reduction > 0:
                warrior.defence += reduction
                warrior.patronus_def_reduction = 0
                print(wrap("Your guard recovers — Defence restored!"))

def _tick_patronus_passive_first_aid(enemy):
    """
    v0.6.15: Patronus passive First Aid trigger.
    When his HP first drops below 50%, his First Aid Rank 4 (40% max HP heal)
    fires automatically at the start of his turn — no AP cost, doesn't consume
    his regular AI action. Behaves like a player drinking a potion as a bonus
    action. Still respects the existing charges_first_aid count (default 1)
    so it can only fire ONCE per fight unless we ever raise the charges.

    Without this passive, a fast-burst player could kill Patronus before the
    AI ever rolled a turn that chose First Aid (it was priority 5 in the
    dispatcher, gated by the 'special vs basic' chance roll). 7-turn kills
    were stripping the heal phase entirely.

    Sets enemy.passive_first_aid_fired so it only triggers once per fight
    even if HP yo-yos across the 50% threshold.
    """
    if getattr(enemy, "passive_first_aid_fired", False):
        return
    if getattr(enemy, "charges_first_aid", 0) <= 0:
        return
    if enemy.max_hp <= 0:
        return

    hp_pct = enemy.hp / enemy.max_hp
    if hp_pct >= 0.50:
        return
    if enemy.hp >= enemy.max_hp:
        return  # nothing to heal

    # Trigger — flavor before the heal so it reads as a deliberate moment
    print(wrap(
        "🩹 Patronus staggers, gritting his teeth — battle instinct takes over. "
        "Without breaking stance, he tends to his wounds!"
    ))
    patronus_first_aid(enemy)
    enemy.passive_first_aid_fired = True

def patronus_ai(enemy, warrior, turn_count):
    """
    Patronus AI dispatcher — charge based, no AP gating except Power Charge.

    Desperation scaling drives special frequency.
    Priority:
      0) Post-Defence Break follow-up — 85% Double Strike the turn after Defence Break
      1) Defence Break early — fires first 3 turns if charges remain
      2) War Cry if not active and charges remain
      3) Power Charge (surprise combo, 40% chance, needs 2 AP)
      4) Double Strike — main damage
      5) First Aid below 40% HP
      6) Basic attack fallback
    """
    hp_pct = enemy.hp / enemy.max_hp if enemy.max_hp > 0 else 0

    # Desperation scaling
    if hp_pct > 0.75:
        chance = 0.50
    elif hp_pct > 0.50:
        chance = 0.60
    elif hp_pct > 0.25:
        chance = 0.75
    else:
        chance = 0.90

    if random.random() > chance:
        enemy.defence_break_followup = False   # reset flag on a basic roll-away
        return "basic"

    # Post-Defence Break follow-up — 85% Double Strike the very next turn
    if getattr(enemy, "defence_break_followup", False):
        enemy.defence_break_followup = False
        if getattr(enemy, "charges_double_strike", 0) > 0 and random.random() < 0.85:
            return "double_strike"

    # Defence Break — priority opener first 3 turns
    if turn_count <= 3 and getattr(enemy, "charges_defence_break", 0) > 0:
        enemy.defence_break_followup = True
        return "defence_break"

    # War Cry — buff before attacking if not active
    if getattr(enemy, "war_cry_turns", 0) == 0 and getattr(enemy, "charges_war_cry", 0) > 0:
        return "war_cry"

    # Power Charge — surprise combo, needs 2 AP
    if (getattr(enemy, "charges_power_charge", 0) > 0
            and enemy.ap >= 2
            and random.random() < 0.35):
        return "power_charge"

    # Double Strike — main damage
    if getattr(enemy, "charges_double_strike", 0) > 0 and random.random() < 0.65:
        return "double_strike"

    # First Aid — REMOVED from active rotation (v0.6.15). It now fires as a
    # passive in _tick_patronus_passive_first_aid the moment HP drops below
    # 50%, so the AI shouldn't waste a turn picking it. Was priority 5 here;
    # fast-burst players could kill Patronus before the picker ever rolled
    # this option, stripping his heal phase entirely.

    # Defence Break — remaining charges after opener phase, always set followup flag
    if getattr(enemy, "charges_defence_break", 0) > 0:
        enemy.defence_break_followup = True
        return "defence_break"

    return "basic"

# ===============================
# Patronus Class
# ===============================
class Patronus(Monster):
    """
    Evil path boss — Patronus, Protector of Winter Haven.

    Charge-based skill system — no AP gating except Power Charge (2 AP).
    Each skill has a finite number of uses. Once exhausted it drops from
    the rotation permanently, creating natural fight phases.

    Shield grants +6 DEF +6 HP during fight. Also reduces all incoming
    damage by 30% while equipped. Stripped when Death Defier triggers.

    Death Defier fires on first death — Patronus's ancient blood refuses
    to give out (demi-god, cannot be killed outright). He rises, shield
    gone, intent on continuing — but the Beast Gods surround the player
    in a stronger shield. Patronus strikes it; no effect. The Beast Gods
    then banish him. Fight ENDS in player victory. He leaves the arena
    a shadow of what he was, surviving in the world to be hunted down
    later on the evil path.
    """
    SHIELD_DEF_BONUS = 6
    SHIELD_HP_BONUS  = 6

    def __init__(self):
        super().__init__(
            name    = "Patronus",
            hp      = 129 + Patronus.SHIELD_HP_BONUS,  # 135 effective
            min_atk = 7,
            max_atk = 12,
            gold    = 0,
            xp      = 0,
            essence = [],
            defence = 4 + Patronus.SHIELD_DEF_BONUS,   # 10 effective
            ap      = 4,   # only used for Power Charge (costs 2 AP)
        )
        self.tier = 5

        self.max_ap = 7  # matches design spec — AP regen cap

        # Skill charges — finite uses per fight
        self.charges_double_strike  = 3
        self.charges_war_cry        = 2
        self.charges_power_charge   = 2
        self.charges_first_aid      = 1
        self.charges_defence_break  = 3

        # First Aid and Defence Break — locked at Rank 4 (max tier)
        self.patronus_heal_rank = 4
        self.patronus_db_rank   = 4

        # War Cry tracking
        self.war_cry_bonus = 0
        self.war_cry_turns = 0

        # Death Defier — fires once, revives at 30% HP
        self.death_defier_active = True
        self.death_defier_used   = False

        # Cycle tracker — same system as Young Chimera
        self.combat_cycles = 0

        # Shield tracking — stripped when Death Defier fires
        self.shield_equipped = True

        self.spawn_flavour = (
            "An elderly man drops from the arena wall above you, landing in a "
            "fighter\'s crouch with no effort at all. He straightens slowly.\n"
            "  \u2694\ufe0f  His eyes are calm. He has done this before. Many times.\n"
            "  \U0001f6e1\ufe0f  The shield on his arm catches the light — nano-tech older "
            "than anything in Winter Haven.\n"
            "  \U0001f480 He looks at you the way a man looks at something he hopes "
            "will finally be enough."
        )

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
    Applies per-level stat scaling for non-boss tiers.

    Tier 1-3: same scaling rules apply — +10 HP, +2 ATK, +1 DEF, +50% XP per
              level above 1. AP recomputed from new max_hp via thresholds.
    Tier 4+:  no scaling (bosses have hand-tuned stats; level handled
              via spawn-time variants like the Fallen Wizard/Rogue/etc.).

    Tier 3 was previously excluded from this scaling, which meant a
    "Hardened Drowned One" had identical base stats to a regular one —
    only the special-move duration/damage scaled. Inconsistent with how
    Tier 1-2 hardened works. v0.6.10 fix: apply the same rule to Tier 3.
    """
    lvl = int(getattr(monster, "level", 1))
    b = max(0, lvl - 1)

    # No scaling at level 1
    if b <= 0:
        monster.max_hp = monster.hp
        monster.max_ap = monster.ap
        return monster

    # Bosses (tier 4+) skip scaling — they're hand-tuned
    if tier >= 4:
        monster.max_hp = monster.hp
        monster.max_ap = monster.ap
        return monster

    # --- Tier 1-3 scaling ---
    # HP +10 per level
    monster.hp += 10 * b
    monster.max_hp = monster.hp

    # ATK +2 per level
    monster.min_atk += 2 * b
    monster.max_atk += 2 * b

    # DEF +1 per level (v0.6.10: reduced from +2 — Hardened variants were
    # creating too much DEF-vs-DEF deadlock against the player's gear; fights
    # turned into slug-fests where neither side could move the bar)
    monster.defence += 1 * b

    # XP +50% per level (rounded up each step)
    monster.xp = scaled_xp_step(monster.xp, lvl)

    # AP based ONLY on new max HP thresholds (13/27/42/58...)
    monster.max_ap = ap_from_hp(monster.max_hp)
    monster.ap = monster.max_ap

    # v0.6.14: Hardened (lvl 2) AP nerf for Hydra Hatchling + Goblin Warrior.
    # Their DoT specials (acid spit / savage slash) could chain off all 4 AP
    # and shred a player who'd already burned their tonic. Cap at 3 AP at lvl 2
    # only — higher levels still scale up normally via the HP threshold formula.
    if lvl == 2 and monster.name in ("Hydra Hatchling", "Goblin Warrior"):
        monster.max_ap = 3
        monster.ap = 3

    # Re-sync psychic base stats so Charged Jagged Rock cap math
    # uses the correct post-scaling values, not the spawn-time values.
    monster.psychic_base_min_atk = monster.min_atk
    monster.psychic_base_max_atk = monster.max_atk
    monster.psychic_base_defence = monster.defence

    return monster

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
    (Flayed_One, 3),
    (Drowned_One, 3),
    (Goblin_Warrior, 3),
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

