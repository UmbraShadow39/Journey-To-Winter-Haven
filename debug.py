# debug.py
# Debug menu, skill editor, loot/potion/title grant menus, monster select
# Can be stripped from production builds — no gameplay logic lives here

import random
import math
import sys

from shared import (
    Monster,
    wrap, space, clear_screen, WIDTH,
    WHITE, RED, GREEN, YELLOW, RESET,
    Equipment,
    ap_from_hp, scaled_xp_step,
)
from titles import TITLE_DISPLAY, award_title_with_buff
from combat import (
    get_ap_inflation, inflated_ap_cost,
    activate_death_defier,
    deactivate_berserk,
    try_death_defier,
)
from combat_log import view_combat_log
from leaderboard import warn_debug_mode_score_impact
from story import arena_quarters_interlude
from equipment import RARITY_ORDER, make_loot, equip_item, unequip_item
from monsters import (
    MONSTER_TYPES, TIER4_BOSSES, weight_to_tier, apply_difficulty_scaling,
    title_for_level,
    Green_Slime, Red_Slime, Young_Goblin, Wolf_Pup, Brittle_Skeleton,
    Imp, Fallen_Warrior, Wolf_Pup_Rider, Javelina, Goblin_Archer,
    Noob_Ghost, Dire_Wolf_Pup, Hydra_Hatchling, Young_Chimera,
    Flayed_One, Drowned_One, Goblin_Warrior, Patronus,
)
from hero import SKILL_DEFS, Warrior, compute_adrenaline_bonus, check_berserk_trigger
from ui import refresh_special_state


def has_unspent_points(hero) -> bool:
    return (getattr(hero, "stat_points", 0) + getattr(hero, "skill_points", 0)) > 0


def get_tier_for_monster_class(cls):
    """Proxy — looks up tier from MONSTER_TYPES (debug UI only)."""
    for c, w in MONSTER_TYPES:
        if c is cls: return weight_to_tier(w)
    for c, _w in TIER4_BOSSES:
        if c is cls: return 4
    return 1

# --- Runtime callbacks injected by main ---
_real_input       = input
GAME_WARRIOR      = None
DIFFICULTY        = "warrior"
award_gold        = None
spend_points_menu = None
animate_xp_results = None

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
    if not getattr(warrior, "debug_mode", False):
        warrior.debug_mode = True
        warn_debug_mode_score_impact()
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
            warrior.berserk_active  = True
            warrior.berserk_bonus   = 6 + getattr(warrior, "max_rage", 0)
            warrior.berserk_turns   = 99   # debug — won't expire naturally
            warrior.berserk_used    = True
            warrior.berserk_pending = False
            warrior.berserk_natural = True   # v0.7.11: give debug berserk damage reduction too
            print("⚡ Debug: Berserk forced ON (99 turns, damage halved).")
            input("\nPress Enter...")

        elif choice == "2":
            deactivate_berserk(warrior)   # clears berserk_natural too via v0.7.11 fix
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
            # v0.7.18 fix: only flag + warn on the FIRST debug action of the
            # run — this used to re-show the full score-impact banner on
            # every Level Up, even though debug_menu()'s own entry gate
            # already handles the first-time case.
            if not getattr(warrior, "debug_mode", False):
                warrior.debug_mode = True
                warn_debug_mode_score_impact()
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


def _debug_title_menu(warrior):
    """
    Debug submenu — grant any title to the warrior.
    Equippable titles apply their stat buffs via award_title_with_buff.
    Fate titles and achievements go into their respective sets directly.
    Duplicate check: granting an already-owned title skips the buff
    and just sets it as the active title.
    """
    TITLES = [
        # (key, category, display_name, buff_note)
        # --- Equippable: no stat buff ---
        ("champion_of_the_arena", "equippable", "Champion of the Arena",     "no buff"),
        ("river_warrior",         "equippable", "River Warrior",              "no buff"),
        ("dual_wielder",          "equippable", "Dual Wielder",               "requires rank 1 dual_wielder skill — auto-sets if missing"),
        ("wolf_hide_crafter",     "equippable", "Wolf-Hide Crafter",          "no buff"),
        ("dire_wolf_crafter",     "equippable", "Dire Wolf Crafter",          "no buff"),
        # --- Equippable: stat buffs ---
        ("jack_of_all_trades",    "equippable", "Jack of All Trades",         "+1 HP/ATK/DEF/AP"),
        ("true_jack_of_all_trades","equippable","True Jack of All Trades",    "+5 HP, +1 ATK/DEF/AP, +1 special/berserk"),
        ("guardian",              "equippable", "Guardian",                   "+10 HP, +4 DEF, +1 ATK/AP"),
        ("dark_champion",         "equippable", "Dark Champion",              "+5 HP, +4 ATK, +4 AP, +1 DEF"),
        ("brawl_master",          "equippable", "Brawl Master",               "+2 min/max ATK"),
        ("chinker",               "equippable", "Chinker",                    "+1 min/max ATK"),
        ("death_delver",          "equippable", "Death Delver",               "+5 max HP"),
        # --- Equippable: passive effects (no stat buff) ---
        ("combat_medic",          "equippable", "Combat Medic",               "passive: heal 10% HP/turn"),
        ("charismatic_speaker",   "equippable", "Charismatic Speaker",        "passive: +15% ATK per fight"),
        ("armor_piercer",         "equippable", "Armor Piercer",              "passive: -1 DEF per hit"),
        ("death_apprentice",      "equippable", "Death's Apprentice",         "passive: DD costs -1 AP + psychic rebound"),
        # --- Fate titles ---
        ("drowned_one",           "fate",       "Drowned One",                ""),
        ("flayed_one",            "fate",       "Flayed One",                 ""),
        ("coward",                "fate",       "Coward",                     ""),
        ("fallen_champion",       "fate",       "Fallen Champion",            ""),
        ("gooed_one",             "fate",       "The Gooed One",              ""),
        # --- Achievements ---
        ("champion_of_the_arena", "achievement","Champion of the Arena",      "achievement"),
        ("wolf_hide_crafter",     "achievement","Wolf-Hide Crafter",          "achievement"),
        ("dire_wolf_crafter",     "achievement","Dire Wolf Crafter",          "achievement"),
    ]

    # Titles that use award_title_with_buff (have one-time stat buffs)
    BUFFED_TITLES = {
        "guardian", "dark_champion", "jack_of_all_trades",
        "true_jack_of_all_trades", "brawl_master", "chinker", "death_delver",
    }

    while True:
        clear_screen()
        print("=" * 55)
        print("🏅  DEBUG — TITLE GRANT MENU")
        print("=" * 55)
        print()

        sections = [
            ("── Equippable Titles ──", "equippable"),
            ("── Fate Titles ──",       "fate"),
            ("── Achievements ──",      "achievement"),
        ]

        i = 1
        indexed = {}
        for section_label, section_cat in sections:
            print(f"  {section_label}")
            for key, cat, label, note in TITLES:
                if cat != section_cat:
                    continue
                # Duplicate check
                if cat == "equippable":
                    owned = key in getattr(warrior, "titles", set())
                elif cat == "fate":
                    owned = key in getattr(warrior, "fate_titles", set())
                else:
                    owned = key in getattr(warrior, "achievements", set())

                owned_tag = " ✅" if owned else ""
                note_str  = f"  [{note}]" if note else ""
                print(f"  {i:>2}) {label:<30}{note_str}{owned_tag}")
                indexed[str(i)] = (key, cat, label)
                i += 1
            print()

        print("   0) Back")
        print()
        choice = _real_input("> ").strip()

        if choice == "0":
            return
        if choice not in indexed:
            continue

        key, cat, label = indexed[choice]

        if cat == "equippable":
            if key in getattr(warrior, "titles", set()):
                # Duplicate — skip buff, just activate
                print(f"\n  ⚠️  Already own '{label}' — no buff applied, set as active title.")
                warrior.active_title = key
            else:
                if key in BUFFED_TITLES:
                    award_title_with_buff(warrior, key)
                else:
                    if not hasattr(warrior, "titles"):
                        warrior.titles = set()
                    warrior.titles.add(key)
                    warrior.active_title = key
                    print(f"\n  ✅ Granted: {label}")
                    # v0.7.12: Dual Wielder requires skill rank >= 1 to function.
                    # Auto-set rank 1 if missing so the title actually does something.
                    if key == "dual_wielder":
                        if not hasattr(warrior, "skill_ranks"):
                            warrior.skill_ranks = {}
                        if warrior.skill_ranks.get("dual_wielder", 0) < 1:
                            warrior.skill_ranks["dual_wielder"] = 1
                            print("  (dual_wielder skill rank set to 1 automatically)")

        elif cat == "fate":
            if key in getattr(warrior, "fate_titles", set()):
                print(f"\n  ⚠️  Already have fate title '{label}'.")
            else:
                warrior.fate_titles.add(key)
                print(f"\n  ✅ Fate title granted: {label}")

        elif cat == "achievement":
            if key in getattr(warrior, "achievements", set()):
                print(f"\n  ⚠️  Already have achievement '{label}'.")
            else:
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
        ("13",  "Lightrender        (1H Solforged — good path)",  "DEBUG_LIGHTRENDER"),
        ("13b", "Destiny Definer    (2H Solforged — good path)",  "DEBUG_DESTINY_DEFINER"),
        ("13c", "Duskbringer        (1H Voidforged — evil path)", "DEBUG_DUSKBRINGER"),
        ("13d", "Destiny Destroyer  (2H Voidforged — evil path)", "DEBUG_DESTINY_DESTROYER"),
        ("14", "Chunk of Void Metal (material) — Young Chimera", "Young Chimera"),
        ("15", "Charged Jagged Rock (trinket) — Flayed One",       "Flayed One"),
        ("16", "Waterlogged Stone   (trinket)   — Drowned One",     "Drowned One"),
        ("17", "Goblin War Blade    (weapon)    — Goblin Warrior",   "Goblin Warrior"),
        ("18", "Chunk of Sol Metal (material) — Patronus", "Patronus"),
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

        print("  A) Give item to inventory  (pick item + rarity, goes to bag)")
        print("  B) Equip directly          (pick item + rarity, instant equip)")
        print("  C) Unequip a slot          (removes item, reverses stats)")
        print("  R) Resistance Test Kit     (mythril armor equipped + every Sac, every rarity)")
        print("  0) Back")

        mode = _real_input("\n  Choose mode > ").strip().upper()

        # ── R: Resistance Test Kit ───────────────────────────────────────
        # v0.7.19: one-shot grant for testing the armor-socket resistance
        # system without navigating the rarity picker 21 times by hand.
        # Equips a 4-socket Mythril armor piece and drops every rarity of
        # Poison/Fire/Acid Sac straight into the bag, ready to socket at
        # the Crafter. Also tops up gold so socket ops (5g each) don't run dry.
        if mode == "R":
            clear_screen()
            print("===== RESISTANCE TEST KIT =====\n")

            armor_item = make_loot("Wolf Pup Rider", forced_rarity="mythril")
            if armor_item:
                warrior.inventory.append(armor_item)
                if equip_item(warrior, armor_item):
                    print(f"  ✅ Equipped: {armor_item.short_label()}  (4 sockets)")
                else:
                    print(f"  ⚠️ Equip blocked — left in bag: {armor_item.short_label()}")
            else:
                print("  ⚠️ Could not create test armor.")

            sac_sources = [
                ("Green Slime",     "Poison Sac"),
                ("red slime",       "Fire Sac"),
                ("Hydra Hatchling", "Acid Sac"),
            ]
            granted = 0
            for monster_key, sac_name in sac_sources:
                for rarity in RARITY_MAP.values():
                    sac = make_loot(monster_key, forced_rarity=rarity)
                    if sac:
                        warrior.inventory.append(sac)
                        granted += 1
                    else:
                        print(f"  ⚠️ Could not create {rarity} {sac_name}.")

            warrior.gold += 500
            print(f"  ✅ Granted {granted} Sacs (Poison/Fire/Acid × all 7 rarities) to your bag.")
            print(f"  ✅ +500 gold (now {warrior.gold}g) for socket operations.")
            print("\n  Head to the Crafter → Armor Sockets to slot Sacs and test resistance.")
            _real_input("\nPress Enter...")
            continue

        # ── B: Equip Directly ────────────────────────────────────────────
        if mode == "B":
            while True:
                clear_screen()
                print("===== EQUIP DIRECTLY =====\n")
                eq = warrior.equipment
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

                if monster_key.startswith("DEBUG_"):
                    from crafter import (WOLF_HIDE_RECIPES, DIRE_WOLF_RECIPES,
                                         make_crafted_item)
                    from equipment import _make_weapon_core
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
                    # v0.7.12: Weapon core keys — bypass make_loot path dependency
                    weapon_core_map = {
                        "DEBUG_LIGHTRENDER":       (False, False),  # (corrupted, two_handed)
                        "DEBUG_DESTINY_DEFINER":   (False, True),
                        "DEBUG_DUSKBRINGER":       (True,  False),
                        "DEBUG_DESTINY_DESTROYER": (True,  True),
                    }
                    if monster_key in crafted_map:
                        name, recipes = crafted_map[monster_key]
                        item = make_crafted_item(name, recipes[name])
                    elif monster_key in shield_map:
                        name, defence, max_hp = shield_map[monster_key]
                        item = Equipment(name=name, slot="shield", rarity="normal",
                                         defence=defence, max_hp=max_hp)
                    elif monster_key in weapon_core_map:
                        # Build weapon core directly using current difficulty stats
                        corrupted, two_handed = weapon_core_map[monster_key]
                        from equipment import _get_weapon_core_stats, WEAPON_CORE_NOOB, WEAPON_CORE_WARRIOR
                        _path, _variant, s1h, s2h = _get_weapon_core_stats(corrupted)
                        stats = s2h if two_handed else s1h
                        names_map = {
                            "DEBUG_LIGHTRENDER":       "Lightrender",
                            "DEBUG_DESTINY_DEFINER":   "Destiny Definer",
                            "DEBUG_DUSKBRINGER":       "Duskbringer",
                            "DEBUG_DESTINY_DESTROYER": "Destiny Destroyer",
                        }
                        rarity_out = _variant if _variant else "legendary"
                        item = Equipment(
                            name       = names_map[monster_key],
                            slot       = "weapon",
                            rarity     = rarity_out,
                            atk_min    = stats["atk"],
                            atk_max    = stats["atk"],
                            defence    = stats["def"],
                            two_handed = two_handed,
                        )
                    else:
                        print(f"  Unknown debug key: {monster_key}")
                        _real_input("\nPress Enter...")
                        continue
                else:
                    chosen_rarity = _pick_rarity()
                    if not chosen_rarity:
                        print("Invalid rarity.")
                        _real_input("\nPress Enter...")
                        continue
                    # v0.7.12: pass rarity directly to make_loot — the old
                    # globals() patch only affected debug.py's namespace, not
                    # equipment.py's, so chosen rarity was silently ignored.
                    item = make_loot(monster_key, forced_rarity=chosen_rarity)
                    if not item:
                        print("⚠️ Could not create item.")
                        _real_input("\nPress Enter...")
                        continue

                # Always add to inventory first so equip_item can properly
                # track and remove it — skipping this step causes the item to
                # vanish if unequipped later via the normal inventory menu.
                warrior.inventory.append(item)
                if equip_item(warrior, item):
                    print(f"\n  ✅ Equipped: {item.short_label()}")
                    print(f"  Stats — ATK: {warrior.min_atk}-{warrior.max_atk}  "
                          f"DEF: {warrior.defence}  HP: {warrior.hp}/{warrior.max_hp}")
                else:
                    print(f"\n  ⚠️ Equip blocked — item kept in inventory: {item.short_label()}")
                _real_input("\nPress Enter...")

        # ── A: Give to Inventory ─────────────────────────────────────────
        elif mode == "A":
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
                    # v0.7.12: Weapon core keys
                    weapon_core_map = {
                        "DEBUG_LIGHTRENDER":       (False, False),
                        "DEBUG_DESTINY_DEFINER":   (False, True),
                        "DEBUG_DUSKBRINGER":       (True,  False),
                        "DEBUG_DESTINY_DESTROYER": (True,  True),
                    }
                    if monster_key in crafted_map:
                        name, recipes = crafted_map[monster_key]
                        item = make_crafted_item(name, recipes[name])
                    elif monster_key in shield_map:
                        name, defence, max_hp = shield_map[monster_key]
                        item = Equipment(name=name, slot="shield", rarity="normal",
                                         defence=defence, max_hp=max_hp)
                    elif monster_key in weapon_core_map:
                        corrupted, two_handed = weapon_core_map[monster_key]
                        from equipment import _get_weapon_core_stats
                        _path, _variant, s1h, s2h = _get_weapon_core_stats(corrupted)
                        stats = s2h if two_handed else s1h
                        names_map = {
                            "DEBUG_LIGHTRENDER":       "Lightrender",
                            "DEBUG_DESTINY_DEFINER":   "Destiny Definer",
                            "DEBUG_DUSKBRINGER":       "Duskbringer",
                            "DEBUG_DESTINY_DESTROYER": "Destiny Destroyer",
                        }
                        rarity_out = _variant if _variant else "legendary"
                        item = Equipment(
                            name       = names_map[monster_key],
                            slot       = "weapon",
                            rarity     = rarity_out,
                            atk_min    = stats["atk"],
                            atk_max    = stats["atk"],
                            defence    = stats["def"],
                            two_handed = two_handed,
                        )
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

                # v0.7.12: pass rarity directly — globals() patch only affected
                # debug.py's namespace, not equipment.py's where roll_rarity lives
                item = make_loot(monster_key, forced_rarity=chosen_rarity)

                if not item:
                    print("⚠️ Could not create item.")
                    _real_input("\nPress Enter...")
                    continue

                warrior.inventory.append(item)
                print(f"\n  ✅ Added to inventory: {item.short_label()}")
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

# [Moved to shared.py] show_health



# [Moved to combat.py] apply_turn_stop, resolve_player_turn_stop, simple_trainer_reaction_stub



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



