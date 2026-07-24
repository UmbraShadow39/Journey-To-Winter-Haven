# equipment.py
# Equipment management: equip/unequip, inventory menu, loot generation
# Extracted from main during v0.7 modular refactor (prep for pygame port)

import random
import math

from shared import Equipment, WIDTH, wrap, clear_screen, continue_text

# Injected by main after import (avoids circular import)
_real_input = input

def apply_dual_wield_modifier(hero):
    """
    Session 19 REWORK: off-hand and main-hand are now rolled as two
    INDEPENDENT attacks and summed, rather than pooled into one shared
    min/max ATK range. See warrior_dual_wield_attack_roll() in combat.py
    for where the actual two-roll-sum-plus-bonus math happens.

    This function's only remaining job: while dual-wielding, pull the
    off-hand weapon's raw atk_min/atk_max back OUT of hero.min_atk/max_atk
    (equip_item adds it in generically for any equipped item, same as
    armor/accessories) — because off-hand damage is no longer pooled here,
    it's rolled separately at attack time instead. The Dual Wielder
    title's flat +1/+1 ATK stays as a simple permanent stat addition.

    Old behavior (rank 0 halving, rank 2-5 ATK%) has MOVED to
    warrior_dual_wield_attack_roll() in combat.py, applied per-roll
    instead of baked into a standing stat. This avoids the old
    architecture's core problem: with off-hand pooled into hero.min_atk/
    max_atk, Power Strike and War Cry (which also read those totals)
    would compound on top of an already-inflated number. Now hero.min_atk/
    max_atk while dual-wielding is simply "what main-hand alone would be,"
    so nothing downstream needs special-casing.

    Safe to call repeatedly — idempotent.
    """
    main = hero.equipment.get("main_hand")
    off  = hero.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    dual_wielding = _is_weapon(main) and _is_weapon(off)

    # Remove OLD modifier first (idempotent — order-independent regardless
    # of which hand got equipped first)
    old = getattr(hero, "_dual_wield_modifier_applied", {"atk_min": 0, "atk_max": 0})
    hero.min_atk -= old["atk_min"]
    hero.max_atk -= old["atk_max"]

    new_mod = {"atk_min": 0, "atk_max": 0}
    if dual_wielding:
        # Pull off-hand's raw atk back out — it's rolled independently now,
        # not pooled into hero.min_atk/max_atk.
        new_mod["atk_min"] -= off.atk_min
        new_mod["atk_max"] -= off.atk_max

        # Dual Wielder title bonus: +1 ATK passive while dual-wielding.
        # Kept as a flat permanent addition (not part of the per-roll
        # dual-wield math) — it's a small, simple bonus, not worth the
        # extra complexity of moving it into the roll function too.
        if "dual_wielder" in getattr(hero, "titles", set()):
            new_mod["atk_min"] += 1
            new_mod["atk_max"] += 1

    hero.min_atk += new_mod["atk_min"]
    hero.max_atk += new_mod["atk_max"]

    hero._dual_wield_modifier_applied = new_mod

    # Award title once player has purchased Dual Wielder rank 1 and is actively dual-wielding
    # v0.7.11: moved from "equip two weapons" to "buy rank 1" — equipping is too easy for 150pts
    dw_rank = hero.skill_ranks.get("dual_wielder", 0)
    if dual_wielding and dw_rank >= 1 and "dual_wielder" not in getattr(hero, "titles", set()):
        if not hasattr(hero, "titles"):
            hero.titles = set()
        hero.titles.add("dual_wielder")
        print()
        print(wrap("  🏅 ACHIEVEMENT UNLOCKED: Dual Wielder", WIDTH))
        print(wrap("     You've mastered the art of fighting with two blades.", WIDTH))
        print(wrap("     Off-hand now strikes for full damage. +1 ATK passive.", WIDTH))
        print(wrap("     (+150 end-of-run score)", WIDTH))
        # Re-run with the title now in place so the +1 bonus applies immediately
        apply_dual_wield_modifier(hero)


def get_main_hand_only_atk(hero):
    """
    Session 19 REWORK: since off-hand's atk is no longer pooled into
    hero.min_atk/max_atk while dual-wielding (see apply_dual_wield_modifier
    above), hero.min_atk/max_atk already IS the main-hand-only value at
    all times. This function is now a trivial passthrough — kept as a
    named call (rather than inlining hero.min_atk everywhere) purely so
    Power Strike/War Cry's intent stays self-documenting, and so there's
    one place to change if the underlying model shifts again.
    """
    return hero.min_atk, hero.max_atk


def get_off_hand_only_atk(hero):
    """
    Session 19: returns (min_atk, max_atk) for the off-hand weapon's own
    independent roll while dual-wielding — the non-weapon base (hero's
    level/stat/equipment contribution with main-hand's own atk and the
    Dual Wielder title's flat +1 stripped back out) plus the off-hand
    weapon's raw atk_min/atk_max. Returns (0, 0) when not dual-wielding,
    since there's no separate off-hand roll to make in that case.

    Used by warrior_dual_wield_attack_roll() in combat.py.
    """
    main = hero.equipment.get("main_hand")
    off  = hero.equipment.get("off_hand")

    def _is_weapon(item):
        return item is not None and getattr(item, "slot", None) == "weapon"

    if not (_is_weapon(main) and _is_weapon(off)):
        return 0, 0

    title_flat = 1 if "dual_wielder" in getattr(hero, "titles", set()) else 0
    base_min = hero.min_atk - main.atk_min - title_flat
    base_max = hero.max_atk - main.atk_max - title_flat
    return base_min + off.atk_min, base_max + off.atk_max


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
            # v0.7.02: If a 2H weapon is equipped, offer to swap it out rather
            # than hard-blocking. Player previously had to manually unequip the
            # 2H weapon before they could equip any 1H weapon or shield.
            for s in ("main_hand", "off_hand"):
                existing = hero.equipment.get(s)
                if existing is not None and getattr(existing, "two_handed", False):
                    print(wrap(f"\n  {existing.name} is two-handed and occupies both hands."))
                    print(wrap(f"  Unequip it and equip {item.name} instead?"))
                    confirm = input("  Proceed? (y/n): ").strip().lower()
                    if confirm != "y":
                        print("Cancelled.")
                        return False
                    unequip_item(hero, existing)
                    # Refresh hand state after unequipping 2H
                    h1 = hero.equipment.get("main_hand")
                    h2 = hero.equipment.get("off_hand")
                    break

            if h1 is None:
                slot = "main_hand"
            elif h2 is None:
                # v0.7.17: filling the off-hand with a SECOND weapon (not a
                # shield) creates a dual-wield setup. Untrained (rank 0),
                # the off-hand weapon rolls at half damage — previously this
                # branch silently equipped there with no warning, which could
                # dump a brand-new best-in-slot weapon straight into the
                # penalty slot. Now we ask first.
                creates_untrained_dual_wield = (
                    item.slot == "weapon"
                    and getattr(h1, "slot", None) == "weapon"
                    and hero.skill_ranks.get("dual_wielder", 0) == 0
                )
                if creates_untrained_dual_wield:
                    print(wrap(
                        f"\n  You aren't trained in Dual Wielder — an untrained "
                        f"off-hand weapon rolls at half damage."
                    ))
                    print(f"  1) Equip {item.name} to off-hand anyway (half damage until trained)")
                    print(f"  2) Replace main-hand instead ({h1.short_label()} goes to your bag)")
                    print("  0) Cancel")
                    pick = input("Choose: ").strip()
                    if pick == "1":
                        slot = "off_hand"
                    elif pick == "2":
                        slot = "main_hand"
                    else:
                        print("Cancelled.")
                        return False
                else:
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

    # --- Crafting materials aren't equippable at all (e.g. cured pelts —
    # they're meant for socketing into armor or feeding a recipe, not wearing) ---
    if slot not in hero.equipment:
        if slot == "material":
            print(wrap(
                f"\n  {item.name} is a crafting material, not wearable armor. "
                f"Socket it into a piece of armor, or use it in a recipe at the crafter."
            ))
        else:
            print(wrap(f"\n  {item.name} can't be equipped directly."))
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
    # v0.7.19 BUG FIX: atk_bonus was defined on Equipment and populated by
    # Sharpened Tusk (crafter upgrade of Javelina Tusk) but never actually
    # read anywhere — equipping a Sharpened Tusk applied its bleed effect
    # but silently dropped the entire "+X ATK" half of the item. Confirmed
    # empirically: a Mythril Sharpened Tusk (atk_bonus=4) left ATK unchanged
    # on equip. atk_min/atk_max are separate fields already used by every
    # other equipment type, so this doesn't touch or double-count anything.
    if getattr(item, "atk_bonus", 0):
        hero.min_atk += item.atk_bonus
        hero.max_atk += item.atk_bonus
    if item.max_hp:
        hero.max_hp += item.max_hp
        # v0.7.13: Only top up CURRENT hp on a positive max_hp bonus.
        # Negative max_hp (Tainted Breastplate corruption) shrinks the cap
        # only — it never rips current HP away from a hero who just won
        # a fight. If current hp now exceeds the new (lower) cap, clamp
        # it down instead of draining it.
        if item.max_hp > 0:
            hero.hp += item.max_hp
        hero.hp = min(hero.hp, hero.max_hp)
        hero.max_overheal = int(hero.max_hp * 1.10)
    if getattr(item, "max_ap_bonus", 0):
        hero.max_ap += item.max_ap_bonus
        # v0.7.18: Nathan's call — match level-up behavior: the new capacity
        # arrives CHARGED (+1 max AP means +1 current AP too), instead of
        # equipping an AP-crystal piece and staring at 3/4. Granted once per
        # item (flag lives on the item) so equip/unequip cycling can't be
        # used as a free mid-run AP battery — without the flag you could
        # re-equip the same hood repeatedly to refill AP between fights.
        if not getattr(item, "_ap_charge_granted", False):
            hero.ap = min(hero.ap + item.max_ap_bonus, hero.max_ap)
            item._ap_charge_granted = True
        else:
            hero.ap = min(hero.ap, hero.max_ap)
    if getattr(item, "max_rage_bonus", 0):
        hero.max_rage += item.max_rage_bonus

    # v0.7.17: cured-pelt armor socket reinforcement — applies whenever an
    # armor piece with filled sockets gets equipped (e.g. from the bag).
    # v0.7.20: crystals also grant stat bonuses at socket power.
    if item.slot == "armor" and getattr(item, "sockets", None):
        try:
            from crafter import armor_socket_stat_bonus
            _sock_def, _sock_hp, _sock_ap, _sock_atk = armor_socket_stat_bonus(item)
            if _sock_def:
                hero.defence += _sock_def
            if _sock_hp:
                hero.max_hp += _sock_hp
                hero.hp += _sock_hp
                hero.hp = min(hero.hp, hero.max_hp)
                hero.max_overheal = int(hero.max_hp * 1.10)
            if _sock_ap:
                hero.max_ap += _sock_ap
                hero.ap = min(hero.ap + _sock_ap, hero.max_ap)
            if _sock_atk:
                hero.min_atk += _sock_atk
                hero.max_atk += _sock_atk
        except ImportError:
            pass

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


def recalculate_defence(hero):
    """
    v0.7.12: Recompute hero.defence from scratch after Defence Warp.

    Formula:
        base_defence        (stat point investments, no gear)
      + gear_defence        (sum of defence from all equipped items)
      + wolf_hide_set_bonus (tracked in _wolf_hide_bonus_applied)
      + dire_wolf_set_bonus (tracked in _dire_wolf_bonus_applied)

    This replaces the old delta-restore pattern which broke when title
    buffs and set bonuses were stacked on top of the warped value.

    Also clears all Defence Warp state attributes so combat.py's
    cleanup loops become no-ops rather than applying stale deltas.
    """
    # Clear warp state first so nothing downstream re-applies it
    for attr in ("defence_warp_phase", "defence_warp_original_defence",
                 "defence_warp_snapshot"):
        if hasattr(hero, attr):
            delattr(hero, attr)

    # Base from stat point investments
    base = getattr(hero, "base_defence", 0)

    # Sum defence from all equipped gear (including cured-pelt armor sockets)
    def _gear_defence(item):
        total = getattr(item, "defence", 0)
        if getattr(item, "slot", None) == "armor" and getattr(item, "sockets", None):
            try:
                from crafter import armor_socket_stat_bonus
                total += armor_socket_stat_bonus(item)[0]
            except ImportError:
                pass
        return total

    gear = sum(
        _gear_defence(item)
        for item in hero.equipment.values()
        if item is not None
    )

    # Set bonuses — already tracked as applied deltas on the hero
    wolf_set  = getattr(hero, "_wolf_hide_bonus_applied",  {}).get("defence", 0)
    dire_set  = getattr(hero, "_dire_wolf_bonus_applied",  {}).get("defence", 0)

    # Title buffs that add flat defence (guardian, jack_of_all_trades, etc.)
    # These are already baked into base_defence via award_title_with_buff —
    # award_title_with_buff increments hero.defence AND we now also increment
    # base_defence in that path. See titles.py patch note v0.7.12.
    # So we do NOT add them separately here — they live in base_defence.

    hero.defence = base + gear + wolf_set + dire_set


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
    if getattr(item, "atk_bonus", 0):
        hero.min_atk -= item.atk_bonus
        hero.max_atk -= item.atk_bonus
    if item.max_hp:
        hero.max_hp -= item.max_hp
        hero.hp      = min(hero.hp, hero.max_hp)
        hero.max_overheal = int(hero.max_hp * 1.10)
    if getattr(item, "max_ap_bonus", 0):
        hero.max_ap = max(1, hero.max_ap - item.max_ap_bonus)
        hero.ap     = min(hero.ap, hero.max_ap)
    if getattr(item, "max_rage_bonus", 0):
        hero.max_rage = max(0, hero.max_rage - item.max_rage_bonus)

    # v0.7.17: reverse cured-pelt armor socket reinforcement (mirrors equip_item)
    # v0.7.20: also reverses crystal bonuses
    if item.slot == "armor" and getattr(item, "sockets", None):
        try:
            from crafter import armor_socket_stat_bonus
            _sock_def, _sock_hp, _sock_ap, _sock_atk = armor_socket_stat_bonus(item)
            if _sock_def:
                hero.defence -= _sock_def
            if _sock_hp:
                hero.max_hp = max(1, hero.max_hp - _sock_hp)
                hero.hp = min(hero.hp, hero.max_hp)
                hero.max_overheal = int(hero.max_hp * 1.10)
            if _sock_ap:
                hero.max_ap = max(1, hero.max_ap - _sock_ap)
                hero.ap = min(hero.ap, hero.max_ap)
            if _sock_atk:
                hero.min_atk -= _sock_atk
                hero.max_atk -= _sock_atk
        except ImportError:
            pass

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
            had_dual_wielder = "dual_wielder" in getattr(hero, "titles", set())
            equip_item(hero, item)
            # If Dual Wielder title was just awarded, pause long enough for player to see it
            just_unlocked = (not had_dual_wielder and
                             "dual_wielder" in getattr(hero, "titles", set()))
            if just_unlocked:
                print()
                input("  Press Enter to continue...")
            else:
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




RARITY_ORDER = ["poor", "normal", "uncommon", "rare", "epic", "legendary", "mythril"]

def roll_rarity(monster_level=1, round_num=0):
    """Returns a rarity string based on monster level and round.
    On Champion difficulty, poor drops are removed; normal/uncommon/rare only
    (50%/30%/20%). rare/epic/legendary/mythril otherwise require debug or boss drops."""
    if round_num == 1:
        thresholds = (30, 80)   # <=30 poor, <=80 normal, else uncommon
    elif monster_level >= 3:
        thresholds = (15, 65)
    elif monster_level == 2:
        thresholds = (40, 85)
    else:
        thresholds = (65, 90)

    # Champion difficulty: no poor drops; normal/uncommon/rare only
    # Base 50% normal, 30% uncommon, 20% rare  — v0.7.14 (was 60/30/10)
    # v0.7.15: higher variants (Hardened/Veteran/Elite) shift +10% into rare
    # per level above 1, taken out of normal. Uncommon stays flat at 30%.
    import sys
    _main = sys.modules.get("__main__")
    _diff = getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"
    if _diff == "champion":
        if monster_level >= 3:
            n_cut, u_cut = 30, 60    # 30% normal / 30% uncommon / 40% rare
        elif monster_level == 2:
            n_cut, u_cut = 40, 70    # 40% normal / 30% uncommon / 30% rare
        else:
            n_cut, u_cut = 50, 80    # 50% normal / 30% uncommon / 20% rare
        r = random.randint(1, 100)
        if r <= n_cut:   return "normal"
        elif r <= u_cut: return "uncommon"
        else:            return "rare"
    
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
    "mythril_plus": {"defence": 5, "max_hp": 5},
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
    "mythril_plus": {"defence": 6, "max_hp": 6},
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
# poor:      +1 atk
# normal:    +1 atk, 25% chance +1 bonus damage on hit  (proc_chance / proc_bonus)
# uncommon:  +2 atk, 50% chance +1 bonus damage on hit
# rare:      +3 atk, 60% chance +2 bonus damage on hit
# epic:      +4 atk, 70% chance +3 bonus damage on hit
# legendary: +5 atk, 80% chance +4 bonus damage on hit
# mythril:   +6 atk, 90% chance +5 bonus damage on hit
# v0.7.16: rare-through-mythril rebalanced into a clean +1 atk / +1 proc
# bonus / +10% chance staircase per tier — rare no longer duplicated
# uncommon's flat ATK.
# ----------------------------------------------------------------
IMP_TRIDENT_STATS = {
    "poor":     {"atk_min": 1, "atk_max": 1, "proc_chance": 0.0,  "proc_bonus": 0},
    "normal":   {"atk_min": 1, "atk_max": 1, "proc_chance": 0.25, "proc_bonus": 1},
    "uncommon": {"atk_min": 2, "atk_max": 2, "proc_chance": 0.50, "proc_bonus": 1},
    "rare":     {"atk_min": 3, "atk_max": 3, "proc_chance": 0.60, "proc_bonus": 2},
    "epic":     {"atk_min": 4, "atk_max": 4, "proc_chance": 0.70, "proc_bonus": 3},
    "legendary":{"atk_min": 5, "atk_max": 5, "proc_chance": 0.80, "proc_bonus": 4},
    "mythril":  {"atk_min": 6, "atk_max": 6, "proc_chance": 0.90, "proc_bonus": 5},
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

# Javelina Tusk  (accessory — raw tusk, causes bleed on hit)
# Worn as an accessory, procs bleed each time the player lands a hit.
# Weaker than the Sharpened Tusk (crafter upgrade).
# poor:     no bleed (just a raw tusk, not yet useful)
# normal:   1 turn, 1 dmg
# uncommon: 2 turns, 1-2 dmg
# rare:     2 turns, 2-3 dmg
# epic:     3 turns, 2-4 dmg
# legendary:3 turns, 3-5 dmg
# ----------------------------------------------------------------
JAVELINA_TUSK_STATS = {
    "poor":      {"bleed_turns": 0, "bleed_dmg_min": 0, "bleed_dmg_max": 0},
    "normal":    {"bleed_turns": 1, "bleed_dmg_min": 1, "bleed_dmg_max": 1},
    "uncommon":  {"bleed_turns": 2, "bleed_dmg_min": 1, "bleed_dmg_max": 2},
    "rare":      {"bleed_turns": 2, "bleed_dmg_min": 2, "bleed_dmg_max": 3},
    "epic":      {"bleed_turns": 3, "bleed_dmg_min": 2, "bleed_dmg_max": 4},
    "legendary": {"bleed_turns": 3, "bleed_dmg_min": 3, "bleed_dmg_max": 5},
    "mythril":   {"bleed_turns": 4, "bleed_dmg_min": 4, "bleed_dmg_max": 6},
}

# Sharpened Tusk  (accessory — crafter upgrade from Javelina Tusk)
# Honed to a fine edge by the crafter. Stronger bleed + bonus ATK on hit.
# normal:   +1 atk, 2 turns, 1-2 dmg
# uncommon: +1 atk, 3 turns, 2-3 dmg
# rare:     +2 atk, 3 turns, 2-4 dmg
# epic:     +2 atk, 4 turns, 3-5 dmg
# legendary:+3 atk, 5 turns, 4-6 dmg
# ----------------------------------------------------------------
SHARPENED_TUSK_STATS = {
    "poor":      {"atk_bonus": 0, "bleed_turns": 1, "bleed_dmg_min": 1, "bleed_dmg_max": 1},
    "normal":    {"atk_bonus": 1, "bleed_turns": 2, "bleed_dmg_min": 1, "bleed_dmg_max": 2},
    "uncommon":  {"atk_bonus": 1, "bleed_turns": 3, "bleed_dmg_min": 2, "bleed_dmg_max": 3},
    "rare":      {"atk_bonus": 2, "bleed_turns": 3, "bleed_dmg_min": 2, "bleed_dmg_max": 4},
    "epic":      {"atk_bonus": 2, "bleed_turns": 4, "bleed_dmg_min": 3, "bleed_dmg_max": 5},
    "legendary": {"atk_bonus": 3, "bleed_turns": 5, "bleed_dmg_min": 4, "bleed_dmg_max": 6},
    "mythril":   {"atk_bonus": 4, "bleed_turns": 6, "bleed_dmg_min": 5, "bleed_dmg_max": 7},
    # v0.7.16: bleed_turns/bleed_dmg_min/max above are no longer read by the
    # tusk-sharpening craft — those are now computed live from the raw
    # Javelina Tusk's own stats at input rarity (see scale_bleed_stat()
    # below), so the *output* bleed keeps scaling relative to what you fed
    # in rather than a fixed table. atk_bonus is still read straight from
    # here per output rarity. Rows kept in full for any other code path
    # that might reference this table directly.
}

# ----------------------------------------------------------------
# Extra rarity tiers beyond the standard 7-tier ladder ("+" tiers).
#
# Scoped PER ITEM on purpose — these do NOT get added to the global
# RARITY_ORDER, so merchant pricing, drop tables, and every other
# recipe's discount logic are untouched. Only the specific crafting
# path that checks this registry knows these tiers exist.
#
# To add a new "+" tier for another item later: add an entry here,
# then give it an atk_bonus (or whatever stat) in that item's stats
# table under the same key, and pass a `overrides` dict computed
# however that item's formula works when calling _make_component().
# ----------------------------------------------------------------
EXTRA_RARITY_TIERS = {
    "Javelina Tusk": {
        "trigger_rarity": "mythril",   # sharpening a tusk at this rarity unlocks the extra tier
        "key":            "mythril_plus",
        "label":          "Mythril+",
    },
    "Cured Wolf Pelt": {
        "trigger_rarity": "mythril",   # curing a mythril raw pelt bumps to mythril+
        "key":            "mythril_plus",
        "label":          "Mythril+",
    },
    "Cured Dire Wolf Pelt": {
        "trigger_rarity": "mythril",
        "key":            "mythril_plus",
        "label":          "Mythril+",
    },
}

# atk_bonus for extra "+" tiers — keyed the same way as SHARPENED_TUSK_STATS,
# just kept separate since these ranks don't exist in the base ladder.
SHARPENED_TUSK_STATS["mythril_plus"] = {"atk_bonus": 5}


def scale_bleed_stat(value, multiplier=1.5):
    """
    Round-up scaling for bleed turns / bleed damage, minimum 1.
    Used by the tusk-sharpening craft so output bleed stats scale
    relative to the raw tusk's OWN rarity stats rather than a fixed
    table — a Poor tusk sharpened gets a 50% bump off Poor's numbers,
    a Mythril tusk sharpened gets a 50% bump off Mythril's numbers.
    """
    return max(1, math.ceil(value * multiplier))

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
# Tainted Champion's Breastplate stats — now the dormant "potential" values
# for Chunk of Sol Metal (Patronus drop, evil path). See the redesign note
# further down (v0.7.19) for how this item actually works now — it's a raw
# material, not wearable armor. These numbers are what it becomes once the
# Beast Gods corrupt it; kept under the old name so nothing else has to
# change. The corruption bleeds power inward — strong defence but the
# taint slowly hollows you out (negative max HP).
#
# v0.7.13: Stats scale with difficulty, mirroring the Weapon Core pattern.
# DEF climbs +3 per tier; the corruption cost also deepens -2 HP per tier —
# higher difficulty means more raw power, but a steeper price for it.
# Matches the Void Metal potential's parallel scaling (see below), just
# inverted on the HP axis.
# ----------------------------------------------------------------
TAINTED_CHAMPIONS_BREASTPLATE_NOOB     = {"defence": 7,  "max_hp": -5}
TAINTED_CHAMPIONS_BREASTPLATE_WARRIOR  = {"defence": 10, "max_hp": -7}
TAINTED_CHAMPIONS_BREASTPLATE_CHAMPION = {"defence": 13, "max_hp": -9}

# Kept as an alias so any stray references don't crash — resolves via
# _get_tainted_breastplate_stats() at drop time instead.
TAINTED_CHAMPIONS_BREASTPLATE_STATS = TAINTED_CHAMPIONS_BREASTPLATE_NOOB

# ----------------------------------------------------------------
# Weapon Core — Solforged Steel (good path) / Voidforged (evil path)
# v0.7.12: Stats scale with difficulty. Champion rolls a random variant
# (uncommon or rare) BEFORE the player chooses 1H or 2H, so they see the
# actual numbers before committing.
#
# v0.7.19 REDESIGN — Nathan's call, matching the gear-is-penalty-free
# philosophy set for the Sol/Void armor set: Voidforged no longer carries
# a DEF penalty (was floor(ATK/2), a real cost). It's now a flat +2 ATK
# over its Solforged counterpart at every tier/variant, DEF always 0 for
# both. Sith/Jedi power-lean, not glass-cannon-vs-brick — gear only ever
# adds, it never takes away. Any "cost of power" for the evil path lives
# in move effects (Defence Break etc.), not baked into passive items.
#
# Good path (Solforged Steel):
#   Noob:     1H +6,  2H +9
#   Warrior:  1H +8,  2H +11
#   Champion: 1H +10 or +12,  2H +13 or +15  (random roll)
#
# Evil path (Voidforged) — always Solforged's ATK + 2, DEF 0:
#   Noob:     1H +8,  2H +11
#   Warrior:  1H +10, 2H +13
#   Champion: 1H +12 or +14,  2H +15 or +17
#
# The 2H variant is always 1H+3 ATK, matching the existing pattern.
# ----------------------------------------------------------------

# Noob — fixed, matches original Lightrender/Destiny Definer
WEAPON_CORE_NOOB = {
    "good": {
        "1h": {"atk": 6,  "def": 0},
        "2h": {"atk": 9,  "def": 0},
    },
    "evil": {
        "1h": {"atk": 8,  "def": 0},
        "2h": {"atk": 11, "def": 0},
    },
}

# Warrior — fixed
WEAPON_CORE_WARRIOR = {
    "good": {
        "1h": {"atk": 8,  "def": 0},
        "2h": {"atk": 11, "def": 0},
    },
    "evil": {
        "1h": {"atk": 10, "def": 0},
        "2h": {"atk": 13, "def": 0},
    },
}

# Champion — two possible variants, rolled before player chooses form
# "uncommon" = lower roll, "rare" = higher roll
WEAPON_CORE_CHAMPION = {
    "good": {
        "uncommon": {"1h": {"atk": 10, "def": 0},  "2h": {"atk": 13, "def": 0}},
        "rare":     {"1h": {"atk": 12, "def": 0},  "2h": {"atk": 15, "def": 0}},
    },
    "evil": {
        "uncommon": {"1h": {"atk": 12, "def": 0},  "2h": {"atk": 15, "def": 0}},
        "rare":     {"1h": {"atk": 14, "def": 0},  "2h": {"atk": 17, "def": 0}},
    },
}

# Keep old dicts as aliases so any remaining references don't crash
WEAPON_CORE_ONEHANDED_STATS = {"atk_min": 6, "atk_max": 6, "defence": 0}
WEAPON_CORE_TWOHANDED_STATS = {"atk_min": 9, "atk_max": 9, "defence": 0}
WEAPON_CORE_DEFENSIVE_STATS = {"fixed": WEAPON_CORE_ONEHANDED_STATS}
WEAPON_CORE_OFFENSIVE_STATS  = {"fixed": WEAPON_CORE_TWOHANDED_STATS}

# ----------------------------------------------------------------
# Chunk of Void Metal  (material) — Young Chimera drop
# Chunk of Sol Metal   (material) — Patronus drop
#
# v0.7.19 REDESIGN — Nathan's call. These replace the old Chimera Scale /
# Tainted Champion's Breastplate wearable drops. Both are now raw, inert
# crafting materials (slot "material", same as Cured Pelts/Crystals — not
# equippable, no sockets) rather than immediately-wearable armor. Piece 1
# of a future forged endgame set; the full set is meant to be a reward for
# completed missions later in the game, not something equipped the moment
# the boss dies.
#
# The metal is the WRONG alignment for the path that earned it — Void
# Metal (dark/chaotic) drops for the GOOD path, Sol Metal (light) drops
# for the EVIL path — and has to be reconciled before it's usable:
#   - Chunk of Void Metal  → PURIFIED by the Solari
#   - Chunk of Sol Metal   → CORRUPTED by the Beast Gods
# This isn't a guess — it's already locked into existing scene text: the
# evil path is explicitly tagged "Beast Gods" elsewhere in combat.py, the
# Tainted Breastplate's old flavour text said it was "warped by the Beast
# Gods' touch," and the corrupted Weapon Core drop already describes "the
# Beast Gods' mark bleeding through the metal." Solari purifying Void
# Metal follows by symmetry (light-aligned creators undoing a dark-aligned
# taint) but isn't independently confirmed in existing text the way the
# Beast Gods/Sol Metal pairing is.
#
# NOT YET BUILT: the actual purify/corrupt mechanic. Nathan's direction —
# gradual, task-gated purification tied to completing missions for the
# relevant faction, removing a small chunk of corruption/purity per
# milestone rather than all at once, so power grows across the game as
# more pieces of the set are earned and refined. That's a big system that
# should be designed alongside the Loyalty Trials / mission framework
# rather than bolted on separately — deferred until that's further along.
#
# In the meantime the raw chunk carries its difficulty-scaled "potential"
# stats as inert placeholders (void_potential / sol_potential below) so a
# future purify recipe has real numbers to scale from — same inheritance
# pattern as raw pelt -> cured pelt.
# ----------------------------------------------------------------
CHIMERA_SCALE_NOOB     = {"defence": 5,  "max_hp": 2}
CHIMERA_SCALE_WARRIOR  = {"defence": 8,  "max_hp": 4}
CHIMERA_SCALE_CHAMPION = {"defence": 11, "max_hp": 6}

# Kept as an alias so any stray references don't crash — resolves via
# _get_chimera_scale_stats() at drop time instead.
CHIMERA_SCALE_STATS = CHIMERA_SCALE_NOOB


def _get_difficulty():
    """Shared helper — reads current DIFFICULTY off __main__, defaults warrior."""
    import sys
    _main = sys.modules.get("__main__")
    return getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"


def _get_chimera_scale_stats():
    """Resolve Chunk of Void Metal's dormant potential stats for current difficulty."""
    diff = _get_difficulty()
    if diff == "noob":
        return CHIMERA_SCALE_NOOB
    elif diff == "champion":
        return CHIMERA_SCALE_CHAMPION
    else:  # warrior (default)
        return CHIMERA_SCALE_WARRIOR


def _get_tainted_breastplate_stats():
    """Resolve Chunk of Sol Metal's dormant potential stats for current difficulty."""
    diff = _get_difficulty()
    if diff == "noob":
        return TAINTED_CHAMPIONS_BREASTPLATE_NOOB
    elif diff == "champion":
        return TAINTED_CHAMPIONS_BREASTPLATE_CHAMPION
    else:  # warrior (default)
        return TAINTED_CHAMPIONS_BREASTPLATE_WARRIOR


def _with_potential(item, attr_name, potential_stats):
    """
    Stash a raw material's dormant "potential" stats as a plain extra
    attribute (not a real Equipment field) — inert until a future
    purify/corrupt recipe reads it. Returns the item for lambda chaining.
    """
    setattr(item, attr_name, dict(potential_stats))
    return item


def _get_weapon_core_stats(corrupted=False):
    """
    Resolve weapon core stats based on current difficulty.
    Returns (path_key, variant_label, 1h_stats, 2h_stats).
      path_key:      "good" or "evil"
      variant_label: "uncommon", "rare", or "" (non-champion)
      1h_stats:      {"atk": N, "def": N}
      2h_stats:      {"atk": N, "def": N}

    Champion difficulty rolls a random variant before the player
    chooses their weapon form so they can see the actual numbers.
    """
    import sys, random
    _main = sys.modules.get("__main__")
    diff = getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"
    path = "evil" if corrupted else "good"

    if diff == "noob":
        tbl = WEAPON_CORE_NOOB[path]
        return path, "", tbl["1h"], tbl["2h"]
    elif diff == "champion":
        variant = random.choice(["uncommon", "rare"])
        tbl = WEAPON_CORE_CHAMPION[path][variant]
        return path, variant, tbl["1h"], tbl["2h"]
    else:  # warrior (default)
        tbl = WEAPON_CORE_WARRIOR[path]
        return path, "", tbl["1h"], tbl["2h"]


def _make_weapon_core(corrupted=False):
    """
    Called after the Fallen Warrior's death scene.
    Good path  (corrupted=False): Lightrender (1H) or Destiny Definer (2H)
                                   Material: Solforged Steel
    Evil path  (corrupted=True):  Duskbringer (1H) or Destiny Destroyer (2H)
                                   Material: Voidforged

    v0.7.12: Stats scale with difficulty. Champion rolls variant first
    (uncommon or rare) so the player sees real numbers before choosing form.
    v0.7.19: No DEF penalty anymore — Voidforged is a flat +2 ATK over its
    Solforged counterpart, DEF 0 for both. See WEAPON_CORE_* tables above.
    """
    path, variant_label, s1h, s2h = _get_weapon_core_stats(corrupted)

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
            "A darkness seeps through it, the Beast Gods' mark bleeding into the metal. "
            "Voidforged — Solari steel corrupted by something that hates the sun."
        ))
        print()
        print(wrap("It writhes between two dark forms. Choose — it will not change again."))
        print()
        d_name = "Duskbringer"
        o_name = "Destiny Destroyer"
        d_flavour = "The cube blackens and elongates — Duskbringer takes shape. Its edge drinks light rather than reflects it."
        o_flavour = "The cube tears itself into a massive two-handed blade — Destiny Destroyer. It hums with borrowed rage."
    else:
        print(wrap(
            "The Fallen Warrior's weapon dissolves into a dense, humming cube "
            "that floats into your palm. It pulses faintly — waiting. "
            "You feel it reading you, deciding what to become. "
            "Solforged steel — shaped by hands that understood metal as a living thing."
        ))
        print()
        print(wrap("It can take one of two forms. Choose carefully — it will not change again."))
        print()
        d_name = "Lightrender"
        o_name = "Destiny Definer"
        d_flavour = "The cube flattens and elongates — Lightrender takes shape. Its edge catches light and holds it, as if the blade remembers the sun."
        o_flavour = "The cube unfolds into a massive two-handed sword — Destiny Definer. The weight of it is immense. This blade does not just cut. It decides."

    # Show variant label for Champion rolls
    if variant_label:
        variant_display = f"  ✨ {variant_label.capitalize()} Solforged resonance" if not corrupted else f"  🌑 {variant_label.capitalize()} Voidforged corruption"
        print(variant_display)
        print()

    def _def_str(d):
        return f"{'+' if d >= 0 else ''}{d}"

    print(f"  1) {d_name}  — One-Handed Sword  (Solforged Steel)" if not corrupted else f"  1) {d_name}  — One-Handed Sword  (Voidforged)")
    print(f"       ⚔️  ATK +{s1h['atk']}   🛡️  DEF {_def_str(s1h['def'])}")
    print(f"       Balanced. Lets you keep an accessory equipped.")
    print()
    print(f"  2) {o_name}  — Two-Handed Sword  (Solforged Steel)" if not corrupted else f"  2) {o_name}  — Two-Handed Sword  (Voidforged)")
    print(f"       ⚔️  ATK +{s2h['atk']}   🛡️  DEF {_def_str(s2h['def'])}")
    print(f"       Raw power. No room for accessories.")
    print()

    while True:
        choice = _real_input("Choose a form (1 or 2): ").strip()
        if choice == "1":
            stats = s1h
            form_name = d_name
            is_two_handed = False
            print(wrap(f"\n{d_flavour}"))
            break
        elif choice == "2":
            stats = s2h
            form_name = o_name
            is_two_handed = True
            print(wrap(f"\n{o_flavour}"))
            break
        else:
            print("Enter 1 or 2.")

    # Rarity label — Champion rolls get their variant, others legendary
    rarity_out = variant_label if variant_label else "legendary"

    print()
    return Equipment(
        name       = form_name,
        slot       = "weapon",
        rarity     = rarity_out,
        atk_min    = stats["atk"],
        atk_max    = stats["atk"],
        defence    = stats["def"],
        two_handed = is_two_handed,
    )


def make_loot(monster_name, monster_level=1, round_num=0, forced_rarity=None):
    # v0.7.12: forced_rarity lets debug menu bypass roll_rarity entirely,
    # fixing the globals() scope bug where the patch never reached equipment.py
    rarity = forced_rarity if forced_rarity else roll_rarity(monster_level=monster_level, round_num=round_num)

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
            flavour = "Wearable as-is for basic protection. Cure it at the crafter to reinforce armor sockets or craft it into a named Wolf-Hide piece.",
        ),

        "Dire Wolf Pup": lambda: Equipment(
            name    = "Dire Wolf Pelt",
            slot    = "armor",
            rarity  = rarity,
            defence = DIRE_WOLF_PELT_STATS[rarity]["defence"],
            max_hp  = DIRE_WOLF_PELT_STATS[rarity]["max_hp"],
            flavour = "Wearable as-is for basic protection. Cure it at the crafter to reinforce armor sockets or craft it into a named Dire Wolf piece.",
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
            slot          = "accessory",
            rarity        = rarity,
            tier          = 2,
            bleed_turns   = JAVELINA_TUSK_STATS[rarity]["bleed_turns"],
            bleed_dmg_min = JAVELINA_TUSK_STATS[rarity]["bleed_dmg_min"],
            bleed_dmg_max = JAVELINA_TUSK_STATS[rarity]["bleed_dmg_max"],
            flavour       = "A jagged javelina tusk. Rough but dangerous — wrapping it to your wrist leaves wounds that won't stop bleeding.",
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
        # v0.7.19: raw, uncorrupted material — see design note above.
        # Potential stats are stashed as inert attributes (sol_potential)
        # for a future corruption recipe to read; current defence/max_hp
        # are 0 since it isn't usable yet.
        "Patronus": lambda: _with_potential(
            Equipment(
                name    = "Chunk of Sol Metal",
                slot    = "material",
                rarity  = "legendary",
                flavour = "Light-forged metal, torn from a corrupted champion. It resists your touch — "
                          "this isn't yours to wield yet. The Beast Gods would need to claim it first.",
            ),
            "sol_potential", _get_tainted_breastplate_stats(),
        ),

        # ── Debug-only drops ───────────────────────────────────
        # v0.7.19: raw, unpurified material — see design note above.
        "Young Chimera": lambda: _with_potential(
            Equipment(
                name    = "Chunk of Void Metal",
                slot    = "material",
                rarity  = "legendary",
                flavour = "Dark, restless metal that shouldn't exist on this side of the fight. "
                          "It hums faintly, waiting on something. The Solari, perhaps.",
            ),
            "void_potential", _get_chimera_scale_stats(),
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
