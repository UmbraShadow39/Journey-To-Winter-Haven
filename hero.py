# hero.py
# Hero base class and Warrior subclass for Journey to Winter Haven
# Extracted from main during v0.7 modular refactor (prep for pygame port)

import random
import math

from shared import (
    Creator,
    Equipment,
    SPECIAL_MOVE_NAMES,
    DEFENCE_BREAK_STATS,
    WIDTH,
    YELLOW,
    RESET,
    clear_screen,
    hp_bar,
)
from titles import (
    TITLE_DISPLAY,
    check_jack_of_all_trades,
    check_breadth_titles,
    check_skill_mastery,
    check_true_jack_of_all_trades,
)
from combat_log import log

# Direct imports from combat/ui (loaded after hero, so use lazy import pattern)
def _lazy_combat():
    import combat
    return combat

def _lazy_ui():
    import ui
    return ui

def _lazy_gold():
    import gold
    return gold

def berserk_meter(*a, **kw):         return _lazy_ui().berserk_meter(*a, **kw)
def cjr_bar(*a, **kw):               return _lazy_ui().cjr_bar(*a, **kw)
def _dd_display_as_river(*a, **kw):  return _lazy_combat()._dd_display_as_river(*a, **kw)
def _dd_ap_cost(*a, **kw):           return _lazy_combat()._dd_ap_cost(*a, **kw)
def _dd_effective_rank(*a, **kw):    return _lazy_combat()._dd_effective_rank(*a, **kw)
def activate_death_defier(*a, **kw): return _lazy_combat().activate_death_defier(*a, **kw)
def get_damage_bonuses(*a, **kw):    return _lazy_combat().get_damage_bonuses(*a, **kw)
def power_strike_ap_cost(*a, **kw):  return _lazy_combat().power_strike_ap_cost(*a, **kw)
def power_strike(*a, **kw):          return _lazy_combat().power_strike(*a, **kw)
def heal_ap_cost(*a, **kw):          return _lazy_combat().heal_ap_cost(*a, **kw)
def heal(*a, **kw):                  return _lazy_combat().heal(*a, **kw)
def war_cry_ap_cost(*a, **kw):       return _lazy_combat().war_cry_ap_cost(*a, **kw)
def war_cry(*a, **kw):               return _lazy_combat().war_cry(*a, **kw)
def defence_break_ap_cost(*a, **kw): return _lazy_combat().defence_break_ap_cost(*a, **kw)
def defence_break(*a, **kw):         return _lazy_combat().defence_break(*a, **kw)
def assassins_strike_available(*a, **kw): return _lazy_combat().assassins_strike_available(*a, **kw)
def assassins_strike_ap_cost(*a, **kw):   return _lazy_combat().assassins_strike_ap_cost(*a, **kw)
def assassins_strike(*a, **kw):      return _lazy_combat().assassins_strike(*a, **kw)
def chimera_fury_add(*a, **kw):      return _lazy_combat().chimera_fury_add(*a, **kw)
def display_run_score(*a, **kw):     return _lazy_gold().display_run_score(*a, **kw)


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
    Build display lines for dual-wield ATK breakdown.

    Session 19 REWORK: main-hand and off-hand are now rolled as two
    independent attacks and summed (see warrior_dual_wield_attack_roll in
    combat.py), rather than pooled into one shared min/max range. This
    display now shows each weapon's own roll range separately, the rank-0
    untrained halving (off-hand only) or rank 1+ full off-hand strength,
    and the rank 2-5 ATK% bonus (which applies to the summed total of
    both rolls, not to either weapon individually).

    Source of truth: apply_dual_wield_modifier + get_off_hand_only_atk in
    equipment.py, and warrior_dual_wield_attack_roll in combat.py.
    """
    main = hero.equipment.get("main_hand")
    off  = hero.equipment.get("off_hand")
    if main is None or off is None:
        return []
    if getattr(main, "slot", None) != "weapon" or getattr(off, "slot", None) != "weapon":
        return []

    dw_rank = hero.skill_ranks.get("dual_wielder", 0)

    main_min, main_max = main.atk_min, main.atk_max
    off_full_min, off_full_max = off.atk_min, off.atk_max
    off_half_min, off_half_max = off_full_min // 2, off_full_max // 2

    lines = ["⚔️  Dual Wielding (two independent rolls, summed):"]
    lines.append(f"   Main: {main.name} ({main_min}-{main_max} ATK, rolled on its own)")

    if dw_rank >= 1:
        lines.append(f"   Off:  {off.name} ({off_full_min}-{off_full_max} ATK, rolled on its own — full, Dual Wielder rank {dw_rank})")
    else:
        lines.append(f"   Off:  {off.name} ({off_full_min}-{off_full_max} → {off_half_min}-{off_half_max} ATK, halved — untrained)")

    if "dual_wielder" in getattr(hero, "titles", set()):
        lines.append("   Dual Wielder title: +1/+1 ATK passive (added to main-hand's base)")
    elif dw_rank == 0:
        lines.append("   (Dual Wielder title unlocks +1/+1 ATK passive at rank 1)")

    DUAL_WIELDER_ATK_PCT = {2: 10, 3: 15, 4: 20, 5: 25}
    pct = DUAL_WIELDER_ATK_PCT.get(dw_rank)
    if pct:
        lines.append(f"   Dual Wielder rank {dw_rank}: +{pct}% ATK applied to the summed total (main + off)")

    if dw_rank >= 5:
        lines.append("   Dual Wielder rank 5: off-hand has a separate 50% chance to also proc on a hit")

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
                self.base_defence = getattr(self, "base_defence", 0) + 1
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
            1: "Strike + buff: +10% ATK for 3 turns (min +1).                 1 AP",
            2: "Strike + buff: +15% ATK for 3 turns (min +1).                 1 AP",
            3: "Strike + buff: +20% ATK for 3 turns (min +1).                 2 AP",
            4: "Strike + buff: +25% ATK for 4 turns (min +1).                 2 AP",
            5: "Strike + buff: +35% ATK for 3 turns (min +1).                 3 AP",
        },
    },
    "defence_break": {
        "name": "Defence Break",
        "min_level": 3,
        "max_rank": 5,
        "upgrade_costs": [1, 2, 3, 4, 4],
        "tier2_name": "Defence Shatter",
        "rank_descs": {
            1: "Strike + reduce enemy DEF 10% (min 1) for 2 turns.  0 DEF: +1 true. 2 AP",
            2: "Strike + reduce enemy DEF 20% (min 1) for 2 turns.  0 DEF: +1 true. 2 AP",
            3: "Strike + reduce enemy DEF 30% (min 1) for 3 turns.  0 DEF: +1 true. 3 AP",
            4: "Strike + reduce enemy DEF 40% (min 1) for 3 turns.  0 DEF: +1 true. 3 AP",
            5: "Strike + reduce enemy DEF 50% (min 1) for 3 turns.  0 DEF: +1 true. 4 AP",
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

    # v0.6.18: Dual Wielder. Rank 1 (off-hand full damage) and the title's
    # flat +1/+1 ATK have been live since v0.7.11. Ranks 2-5's ATK% and the
    # rank 5 off-hand proc chance were finalized and wired up in Session 19
    # (see equipment.py apply_dual_wield_modifier and combat.py off-hand
    # proc block).
    "dual_wielder": {
        "name": "Dual Wielder",
        "min_level": 1,
        "max_rank": 5,
        "upgrade_costs": [1, 2, 3, 4, 5],
        "tier2_name": "Twin Strike",
        "rank_descs": {
            1: "Off-hand attacks for full damage instead of half.            passive",
            2: "+10% ATK while dual-wielding.                                passive",
            3: "+15% ATK while dual-wielding.                                passive",
            4: "+20% ATK while dual-wielding.                                passive",
            5: "+25% ATK; off-hand gets a separate 50% chance to also proc.  passive",
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

    # Dual Wielder is only visible when player is actively dual-wielding
    # (two non-shield weapons equipped). Once seen/purchased, always visible.
    # v0.7.11: rank 1 now live — full off-hand damage when purchased.
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
            # Dual Wielder rank 1: re-run modifier so full off-hand damage applies immediately
            # and title check fires if player is already dual-wielding  — v0.7.11
            if key == "dual_wielder":
                from equipment import apply_dual_wield_modifier
                apply_dual_wield_modifier(hero)
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
                pct   = _lazy_combat().WAR_CRY_PERCENTS[default_rank]
                turns = _lazy_combat().WAR_CRY_TURNS[default_rank]
                bonus = max(1, math.ceil(hero.max_atk * pct))
                label = (f"War Cry (Rank {wc_rank} → {default_rank}, "
                         f"Cost {default_cost} AP, +{bonus} for {turns} turns)")
                fn = lambda h=hero, e=enemy, r=default_rank: war_cry(h, e, r)

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

        # -------------------------
        # ASSASSIN'S STRIKE (hidden capstone — Power Strike R5 + Dual Wielder R5)
        # -------------------------
        if assassins_strike_available(hero):
            as_cost = assassins_strike_ap_cost(hero)
            if hero.ap < as_cost:
                label = f"Assassin's Strike (Cost {as_cost} AP) [Not enough AP]"
                fn = None
            else:
                label = (f"Assassin's Strike (Cost {as_cost} AP, "
                         f"both blades +75% fused, 75% proc chance each hand)")
                fn = lambda h=hero, e=enemy: assassins_strike(h, e)
            options.append(("assassins_strike", label, fn))

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
        warrior.berserk_natural = True   # v0.7.11: natural trigger — halves incoming damage
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
            # v0.7.18: was 5. The sex prompt sets Male 1-6 / Female 2-5
            # (both avg 3.5), but debug paths that skip the prologue kept
            # this old 1-5 default (avg 3.0) — a secretly weaker third
            # profile. Default now matches the default sex (male).
            max_atk=6,
            gold=3,
            xp=0,
            defence=0,
            potions=None
        )

        # Warrior starts with 1 healing potion
        self.potions["heal"] = 1

        # v0.7.12: base_defence tracks defence from stat points only (no gear).
        # Used by recalculate_defence() to cleanly restore after Defence Warp
        # without the delta-restore math that breaks with stacked title/gear bonuses.
        self.base_defence = 0

        # v0.7.18: player-chosen sex, asked alongside the name prompt in
        # ashenveil_prologue(). Defaults to "male" so debug/quick-combat
        # paths that skip the prologue (e.g. !c before a name exists) never
        # hit a missing attribute — the prologue overwrites this normally.
        self.sex = "male"

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
        self.total_gold_spent         = 0           # v0.7.18: Penny Pincher / Big Spender tracking
        self.bookie_intimidated_count = 0
        self.per_fight_scores         = []
        # v0.6.19: quick-kill tracking — accumulated by score.record_fight_score
        # when turn_count <= QUICK_KILL_TURNS for the enemy's tier. The
        # multiplier bonus adds onto the outcome multiplier at end of run.
        self.quick_kill_count           = 0
        self.quick_kill_multiplier_bonus = 0.0






