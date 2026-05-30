"""
shared.py — Shared constants, utilities, and base classes for Journey to Winter Haven.

This module exists to break the circular import between the main game file
and monsters.py. Both files import from here. Neither imports from the other.

Contains:
  * Core constants      (WIDTH, SPECIAL_MOVE_NAMES, DEFENCE_BREAK_STATS)
  * Display utilities   (wrap, space, clear_screen, continue_text, show_health)
  * Defence flavour     (weak/solid/strong/full_defensive_block)
  * Combat math         (lvl_bonus, ap_from_hp, scaled_xp_step,
                         monster_math_breakdown, monster_deal_damage,
                         get_ap_inflation, inflated_ap_cost)
  * Status helpers      (apply_turn_stop, try_death_defier)
  * Exception classes   (RestartException, QuickCombatException, GameOverException)
  * Base classes        (Equipment, Creator, Monster, Hero)
"""

import textwrap
import os
import random
import math

# ============================================================
# CONSTANTS
# ============================================================

WIDTH = 65

SPECIAL_MOVE_NAMES = {
    "slime_poison_spit":          "Poison Spit",
    "red_slime_fire_spit":        "Fire Spit",
    "goblin_cheap_shot":          "Cheap Shot",
    "paralyzing_shot":            "Paralyzing Shot",
    "imp_sneak_attack":           "Sneak Attack",
    "brittle_skeleton_thrust":    "Brittle Thrust",
    "wolf_pup_bite":              "Wolf Bite",
    "devouring_bite":             "Devouring Bite",
    "ghost_life_leech":           "Life Leech",
    "blinding_charge":            "Blinding Charge",
    "impact_bite":                "Impact Bite",
    "hydra_hatchling_acid_spit":  "Acid Spit",
    "savage_slash":               "Savage Slash",
    "psychic_shred":              "Psychic Shred",
    "psychic_drown":              "Psychic Drown",
    "fallen_defence_warp":        "Defence Warp",
    "chimera_special_dispatcher": "Chimera Special",
    "primordial_surge":           "Primordial Surge",
}

DEFENCE_BREAK_STATS = {
    #  rank: (pct, turns)
    1: (0.10, 2),
    2: (0.20, 2),
    3: (0.30, 3),
    4: (0.40, 3),
    5: (0.50, 3),
}

# ============================================================
# DISPLAY UTILITIES
# ============================================================

def clear_screen():
    """Clear the console screen (Windows / Mac / Linux)."""
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def space(line=1):
    for _ in range(line):
        print()


def wrap(text, width=WIDTH):
    if not isinstance(text, str):
        text = str(text)
    return textwrap.fill(
        text,
        width=width,
        break_long_words=False,
        replace_whitespace=False,
    )


def continue_text():
    input("\nPress Enter to continue...\n")


def show_health(hero):
    from shared import hp_bar  # hp_bar defined below in this file
    bar = hp_bar(hero.hp, hero.max_hp)
    print(f"❤️ HP [{bar}] {hero.hp}/{hero.max_hp}")


# ============================================================
# HP BAR  (needed by show_health — kept here to avoid circular pull)
# ============================================================

WHITE   = "\033[97m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RESET   = "\033[0m"

def hp_bar(current, maximum, size=12, max_overheal=None):
    if maximum <= 0:
        return "[" + "?" * size + "]"
    overheal_cap = max_overheal if max_overheal else maximum
    display_max  = max(maximum, current)
    filled = int((current / display_max) * size)
    filled = max(0, min(size, filled))
    empty  = size - filled
    pct    = current / maximum if maximum > 0 else 0
    if current > maximum:
        colour = WHITE
    elif pct > 0.5:
        colour = GREEN
    elif pct > 0.25:
        colour = YELLOW
    else:
        colour = RED
    return colour + "█" * filled + RESET + "░" * empty


# ============================================================
# DEFENSIVE BLOCK FLAVOUR TEXT
# ============================================================

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
        f"{defender.name} blocks too late to stop much.",
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
        f"{defender.name} absorbs the hit without faltering.",
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
        f"{attacker.name}'s strike barely makes contact.",
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
        f"{attacker.name}'s attack is rendered meaningless!",
    ]
    return wrap(random.choice(messages))


# ============================================================
# COMBAT MATH HELPERS
# ============================================================

def lvl_bonus(monster) -> int:
    """+1 per monster level beyond 1"""
    return max(0, int(getattr(monster, "level", 1)) - 1)


def ap_from_hp(max_hp: int) -> int:
    ap = 1
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


def monster_math_breakdown(attacker, defender, raw_roll, actual_physical, *,
                            extra_parts=None, tag=None, ignore_defence=False):
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
    print(wrap(line))


def monster_deal_damage(attacker, defender, raw_roll, *, extra_parts=None, tag=None):
    extra_parts = extra_parts or []
    if raw_roll and raw_roll > 0:
        reduction = getattr(defender, "chimera_atk_reduction", 0.0)
        if reduction:
            raw_roll = max(1, int(raw_roll * (1.0 - reduction)))
        actual_physical = defender.apply_defence(raw_roll, attacker=attacker)
    else:
        actual_physical = 0
    extra_total = sum(int(x) for _, x in extra_parts)
    total = actual_physical + extra_total
    defender.hp = max(0, defender.hp - total)
    monster_math_breakdown(
        attacker, defender, raw_roll, actual_physical,
        extra_parts=extra_parts, tag=tag,
    )
    if actual_physical > 0 and hasattr(attacker, "flayed_charges"):
        _flayed_charge_tick(attacker, defender, actual_physical)
    return total


def _flayed_charge_tick(enemy, warrior, actual_damage):
    """Forward declaration — real implementation stays in main. Imported lazily."""
    pass  # overridden at runtime by main module import


# ============================================================
# AP INFLATION
# ============================================================

def get_ap_inflation(warrior) -> int:
    if getattr(warrior, "drown_stacks", 0) <= 0:
        return 0
    chimera_inflation = getattr(warrior, "drown_chimera_inflation", 0)
    if chimera_inflation > 0:
        return chimera_inflation
    return getattr(warrior, "drown_stacks", 0)


def inflated_ap_cost(base_cost: int, warrior) -> int:
    return base_cost + get_ap_inflation(warrior)


# ============================================================
# STATUS HELPERS
# ============================================================

def apply_turn_stop(hero, turns=1, reason="Stunned"):
    hero.turn_stop = max(getattr(hero, "turn_stop", 0), turns)
    hero.turn_stop_reason = reason
    if reason == "Paralyzed":
        hero.paralyzed = True


def try_death_defier(hero, reason=""):
    if hero.hp > 0:
        return False
    if hero.death_defier and hero.death_defier_active and not hero.death_defier_used:
        hero.death_defier_used = True
        hero.death_defier_active = False
        rank = hero.skill_ranks.get("death_defier", 0) if not getattr(hero, "death_defier_river", False) else 1
        survive_pcts = {1: 0.0, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
        pct = survive_pcts.get(rank, 0.0)
        survive_hp = max(1, int(hero.max_hp * pct)) if pct > 0 else 1
        hero.hp = survive_hp
        print()
        dd_name = "River Spirit" if getattr(hero, "death_defier_river", False) else "Death Defier"
        print(wrap(f"💀✨ {dd_name} surges — you refuse to die! (Survived at {survive_hp} HP)"))
        if reason:
            print(wrap(f"(Saved from: {reason})"))
        show_health(hero)
        return True
    return False


# ============================================================
# EXCEPTION CLASSES
# ============================================================

class RestartException(Exception):
    pass

class QuickCombatException(Exception):
    pass

class GameOverException(Exception):
    pass


# ============================================================
# EQUIPMENT CLASS
# ============================================================

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
        proc_chance=0.0,
        proc_bonus=0,
        blind_chance=0.0,
        element_max_dots=1,
        paralyze_chance=0.0,
        paralyze_turns=0,
        drain_bonus=0,
        drain_heal_min=0,
        drain_heal_max=0,
        bleed_turns=0,
        bleed_dmg_min=0,
        bleed_dmg_max=0,
        element_erosion=0,
        atk_debuff=0.0,
        def_debuff=0.0,
        debuff_turns=0,
        max_charges=0,
        base_atk=0,
        fill_rate=0.0,
        max_ap_bonus=0,
        stone_max_charges=0,
        stone_charges=0,
        enemy_atk_drain=1,
        enemy_def_drain=1,
        two_handed=False,
        sockets=None,
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
        self.stone_max_charges = stone_max_charges
        self.stone_charges    = stone_charges
        self.enemy_atk_drain  = enemy_atk_drain
        self.enemy_def_drain  = enemy_def_drain
        # v0.6.16: 2H weapons block second hand slot
        self.two_handed       = two_handed
        # v0.6.16: socket system. None means "compute from rarity at this
        # item's slot"; an explicit list preserves the socket state through
        # save/load. The socket count comes from SOCKET_COUNTS_BY_RARITY in
        # crafter.py, with armor having no Poor variant (so no Poor entry).
        # Each socket holds either None (empty) or another Equipment instance.
        if sockets is None:
            self.sockets = self._compute_initial_sockets()
        else:
            self.sockets = sockets

    # ---------- Socket system helpers (v0.6.16) ----------

    # Class-level table mirrors crafter.SOCKET_COUNTS_BY_RARITY but inlined
    # here so Equipment doesn't have to import crafter (avoids a circular
    # import — crafter already imports Equipment from shared).
    _SOCKET_COUNTS_WEAPON = {
        "poor":      0,
        "normal":    1,
        "uncommon":  1,
        "rare":      2,
        "epic":      2,   # placeholder; reviewed when Epic+ design lands
        "legendary": 2,   # placeholder
        "mythril":   2,   # placeholder
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
        """
        Initial socket layout based on slot + rarity. Called at Equipment
        construction time when sockets=None is passed (the default).
        Socketed items themselves (Wolf Pelt, sacs, etc.) never have
        sub-sockets — only weapon/armor slot items do.
        """
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

    RARITY_ICONS = {
        "poor":      "⬜",
        "normal":    "🟦",
        "uncommon":  "🟩",
        "rare":      "🟨",
        "epic":      "🟪",
        "legendary": "🟥",
        "mythril":   "🟧",
    }

    def stat_lines(self):
        lines = []
        if self.atk_min or self.atk_max:
            lines.append(f"  ⚔️  ATK +{self.atk_min}/+{self.atk_max}")
        if self.defence:
            lines.append(f"  🛡️  DEF +{self.defence}")
        if self.max_hp:
            lines.append(f"  ❤️  HP +{self.max_hp}")
        if self.max_ap_bonus:
            lines.append(f"  🔵 Max AP +{self.max_ap_bonus}")
        if self.element:
            dots = getattr(self, "element_max_dots", 1)
            dot_txt = f", max {dots} stacks" if dots > 1 else ""
            lines.append(f"  ✨ {self.element.title()} {self.element_damage} dmg ({self.element_turns} turns{dot_txt})")
        if self.element_erosion:
            lines.append(f"  🧪 Acid Erosion: -{self.element_erosion} DEF on hit")
        if self.proc_chance > 0:
            lines.append(f"  ⚡ {int(self.proc_chance*100)}% chance +{self.proc_bonus} bonus dmg")
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
        icon        = self.RARITY_ICONS.get(self.rarity, "⬜")
        rarity_word = self.rarity.title()
        header      = f"{icon} {rarity_word} {self.name}"
        stat_rows   = self.stat_lines()
        if stat_rows:
            return header + "\n" + "\n".join(stat_rows)
        return header

    def full_detail(self):
        icon        = self.RARITY_ICONS.get(self.rarity, "⬜")
        rarity_word = self.rarity.title()
        slot_word   = self.slot.title()
        divider     = "─" * 36
        lines = [
            divider,
            f"  {icon} {rarity_word} {self.name}",
            f"  Slot: {slot_word}",
            divider,
        ]
        stat_rows = self.stat_lines()
        if stat_rows:
            lines += stat_rows
        else:
            lines.append("  (no bonus stats)")
        if self.stone_max_charges:
            lines.append(f"  🌀 Charges: {self.stone_charges}/{self.stone_max_charges}")
        lines.append(divider)
        return "\n".join(lines)


# ============================================================
# BASE CLASSES
# ============================================================

class Creator:
    def __init__(self, name, hp, min_atk, max_atk, gold=0, xp=0, defence=0):
        self.name    = name
        self.hp      = hp
        self.max_hp  = hp
        self.min_atk = min_atk
        self.max_atk = max_atk
        self.gold    = gold
        self.xp      = xp
        self.defence = defence

    def is_alive(self):
        return self.hp > 0

    def take_damage(self, amount):
        self.hp = max(self.hp - amount, 0)

    def attack_roll(self):
        return random.randint(self.min_atk, self.max_atk)

    def apply_defence(self, damage, attacker=None, defence_break=False, true_block=False):
        attacker_name = attacker.name if attacker else "The attacker"

        if true_block:
            print(full_defensive_block(attacker, self))
            return 0

        if getattr(self, "berserk_active", False):
            damage = max(1, damage // 2)

        if defence_break:
            print(wrap(f"{attacker_name}'s brutal strike shatters your defenses!"))
            print(wrap(f"{self.name} is knocked backwards by the impact!"))
            return max(1, damage)

        effective_def = max(0, self.defence - getattr(self, "acid_defence_loss", 0))
        blocked_amount = min(effective_def, damage)
        block_ratio = (blocked_amount / damage) if damage > 0 else 0

        if block_ratio >= 0.75:
            print(strong_defensive_block(attacker, self))
        elif block_ratio >= 0.50:
            print(solid_defensive_block(attacker, self, blocked_amount))
        elif block_ratio > 0:
            print(weak_defensive_block(attacker, self))

        actual = damage - effective_def
        actual = max(1, actual)

        raw_def = self.defence - getattr(self, "acid_defence_loss", 0)
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
        variant_title=None,
    ):
        super().__init__(
            name=name,
            hp=hp,
            min_atk=min_atk,
            max_atk=max_atk,
            gold=gold,
            xp=xp,
            defence=defence,
        )
        self.essence          = essence
        self.ap               = ap
        self.special_move     = special_move
        self.rounds_in_combat = 0
        self.level            = level
        self.variant_title    = variant_title
        self.turns_survived   = 0

        # Psychic debuff base stats
        self.psychic_base_min_atk = min_atk
        self.psychic_base_max_atk = max_atk
        self.psychic_base_defence = defence
        self.psychic_atk_debuff   = 0.0
        self.psychic_def_debuff   = 0.0
        self.psychic_debuff_turns = 0
        self.psychic_debuff_skip  = False
        self.psychic_exposed      = False

        # Defence Break fields (player skill — applied to enemy)
        self.defence_break_active   = False
        self.defence_break_turns    = 0
        self.defence_break_pct      = 0.0
        self.defence_break_base_def = defence

    @property
    def display_name(self):
        title = getattr(self, "variant_title", "")
        if title:
            return f"{title} {self.name}"
        return self.name

    def attack(self, target):
        """Normal monster attack."""
        damage = random.randint(self.min_atk, self.max_atk)
        actual = target.apply_defence(damage, attacker=self)
        target.hp = max(0, target.hp - actual)
        return actual
