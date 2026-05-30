"""
titles.py
---------
Title system for Journey to Winter Haven.

Handles all earnable titles, fate titles, and achievements separately.
Each category serves a different purpose:

  titles       — equippable mid-run achievements (River Warrior, Jack of All Trades)
  fate_titles  — death/failure narrative markers (Drowned One, Flayed One)
  achievements — milestone completions (Champion of the Arena)

Exports:
    TITLE_DISPLAY           — display name lookup for all title keys
    award_title()           — earn a title and prompt to equip
    check_jack_of_all_trades() — fires after every skill upgrade
    switch_title_menu()     — rest-period title switcher (2+ titles required)

Usage in main file:
    from titles import (
        TITLE_DISPLAY,
        award_title,
        check_jack_of_all_trades,
        switch_title_menu,
    )
"""

import os


# ---------------------------------------------------------------
# Display name lookup — all title keys map to readable strings.
# Add new titles here. Fate titles and achievements included so
# the end screen can display them cleanly too.
# ---------------------------------------------------------------
TITLE_DISPLAY = {
    # --- Equippable titles ---
    "river_warrior":        "River Warrior",
    "jack_of_all_trades":   "Jack of All Trades",
    "champion_of_the_arena": "Champion of the Arena",
    "guardian":             "Guardian",
    "dark_champion":        "Dark Champion",
    "divine_blessing":      "Divine Blessing",
    "beast_gods_blessing":  "Beast Gods' Blessing",

    # --- Skill mastery titles ---
    "brawl_master":         "Brawl Master",
    "combat_medic":         "Combat Medic",
    "charismatic_speaker":  "Charismatic Speaker",
    "armor_piercer":        "Armor Piercer",
    "death_challenger":     "Death Challenger",

    # --- Skill breadth titles ---
    "chinker":              "Chinker",
    "death_delver":         "Death Delver",

    # --- Fate titles (death/failure markers) ---
    "drowned_one":          "Drowned One",
    "flayed_one":           "Flayed One",
    "coward":               "Coward",
    "fallen_champion":      "Fallen Champion",

    # --- Achievements (milestone completions) ---
}


# Stat buffs granted when each title is equipped (applied once on award)
TITLE_BUFFS = {
    "guardian":             {"max_hp": 2, "defence": 2},
    "dark_champion":        {"max_atk": 2, "min_atk": 2, "max_ap": 2},
    "divine_blessing":      {"max_hp": 5, "defence": 2, "max_atk": 1, "min_atk": 1, "max_ap": 1},
    "beast_gods_blessing":  {"max_hp": 1, "defence": 1, "max_atk": 2, "min_atk": 2, "max_ap": 2},
    "brawl_master":         {"max_atk": 2, "min_atk": 2},
    "chinker":              {"max_atk": 1, "min_atk": 1},
    "death_delver":         {"max_hp": 5},
    # combat_medic, charismatic_speaker, armor_piercer, death_challenger
    # are passive effects handled in combat — no one-time stat buff
}


def _clear_screen():
    """Local clear — avoids importing from main."""
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def award_title(hero, key):
    """
    Award an equippable title to the hero and prompt to set as active.

    Stat buffs must be applied BEFORE calling this — award_title only
    handles the collection, UI prompt, and active_title assignment.

    Only adds to hero.titles (equippable set). Fate titles and
    achievements have their own sets and don't go through this function.
    """
    hero.titles.add(key)
    display = TITLE_DISPLAY.get(key, key)
    print(f"\n🏅 Set '{display}' as your active title? (Y/N): ", end="")
    if input().strip().lower() == "y":
        hero.active_title = key
        print(f"✨ Title equipped: {display}")
    else:
        print("Title saved — you can equip it during a rest period.")


def award_title_with_buff(hero, key):
    """
    Apply any stat buffs for this title, then award it.
    Use this for Guardian and Dark Champion — buffs apply once on award.
    """
    buffs = TITLE_BUFFS.get(key, {})
    buff_lines = []

    if "max_hp" in buffs:
        hero.max_hp += buffs["max_hp"]
        hero.hp = min(hero.hp + buffs["max_hp"], hero.max_hp)
        buff_lines.append(f"+{buffs['max_hp']} Max HP")
    if "defence" in buffs:
        hero.defence += buffs["defence"]
        buff_lines.append(f"+{buffs['defence']} DEF")
    if "max_atk" in buffs:
        hero.max_atk += buffs["max_atk"]
        hero.min_atk += buffs.get("min_atk", 0)
        buff_lines.append(f"+{buffs['max_atk']} ATK")
    if "max_ap" in buffs:
        hero.max_ap += buffs["max_ap"]
        hero.ap = min(hero.ap + buffs["max_ap"], hero.max_ap)
        buff_lines.append(f"+{buffs['max_ap']} Max AP")

    if buff_lines:
        print("  " + "  |  ".join(buff_lines))

    award_title(hero, key)


def check_jack_of_all_trades(hero):
    """
    Check whether the hero has unlocked all 3 beginner skills.
    If so, apply stat buffs and award the Jack of All Trades title.

    Called automatically after every skill upgrade in show_skill_tree.
    The guard at the top ensures it never fires twice.
    """
    if "jack_of_all_trades" in hero.titles:
        return  # already earned

    beginner_skills = ["power_strike", "heal", "war_cry"]
    if all(hero.skill_ranks.get(s, 0) >= 1 for s in beginner_skills):
        hero.max_hp  += 1
        hero.hp       = min(hero.hp + 1, hero.max_hp)
        hero.max_atk += 1
        hero.min_atk += 1
        hero.defence += 1
        hero.max_ap += 1
        hero.ap      = min(hero.ap + 1, hero.max_ap)
        print("\n" + "=" * 45)
        print("🏅  TITLE UNLOCKED: Jack of All Trades!")
        print("=" * 45)
        print("You've mastered offense, defense, and healing.")
        print("\n  +1 HP  |  +1 ATK  |  +1 DEF  |  +1 AP")
        print("=" * 45)
        award_title(hero, "jack_of_all_trades")


def check_breadth_titles(hero, skill_key):
    """
    Award breadth titles based on how many skills are unlocked and which
    skill was just unlocked.

    4 skills unlocked:
      - 4th skill = defence_break → Chinker (+1 ATK)
      - 4th skill = death_defier  → Death Delver (+5 HP)

    5 skills unlocked:
      - Award whichever of the two they don't have yet.
    Both bonuses always earned eventually — order depends on build path.
    """
    all_skills = ["power_strike", "heal", "war_cry", "defence_break", "death_defier"]
    unlocked = sum(1 for s in all_skills if hero.skill_ranks.get(s, 0) >= 1)

    def _award_chinker():
        hero.max_atk += 1
        hero.min_atk += 1
        print("\n" + "=" * 45)
        print("🏅  TITLE UNLOCKED: Chinker!")
        print("=" * 45)
        print("You've found the gaps in every defence.")
        print("\n  +1 ATK")
        print("=" * 45)
        award_title(hero, "chinker")

    def _award_death_delver():
        hero.max_hp += 5
        hero.hp = min(hero.hp + 5, hero.max_hp)
        print("\n" + "=" * 45)
        print("🏅  TITLE UNLOCKED: Death Delver!")
        print("=" * 45)
        print("You have begun to understand death itself.")
        print("\n  +5 Max HP")
        print("=" * 45)
        award_title(hero, "death_delver")

    if unlocked == 4:
        if skill_key == "defence_break" and "chinker" not in hero.titles:
            _award_chinker()
        elif skill_key == "death_defier" and "death_delver" not in hero.titles:
            _award_death_delver()

    elif unlocked == 5:
        if "chinker" not in hero.titles:
            _award_chinker()
        if "death_delver" not in hero.titles:
            _award_death_delver()


def check_skill_mastery(hero, skill_key):
    """
    Check if a skill just hit rank 5 and award the matching mastery title.
    Call this after every skill upgrade in show_skill_tree.

    Mastery titles and their passive effects:
      power_strike  → Brawl Master        (+2 min/max ATK — applied on award)
      heal          → Combat Medic        (passive: +10% HP regen end of player turn — flagged)
      war_cry       → Charismatic Speaker (passive: +15% ATK whole fight — flagged)
      defence_break → Armor Piercer       (passive: -1 enemy DEF on basic ATK — flagged)
      death_defier  → Death Challenger    (passive: Death Defier costs -1 AP — flagged)
    """
    MASTERY_MAP = {
        "power_strike":   "brawl_master",
        "heal":           "combat_medic",
        "war_cry":        "charismatic_speaker",
        "defence_break":  "armor_piercer",
        "death_defier":   "death_challenger",
    }

    title_key = MASTERY_MAP.get(skill_key)
    if not title_key:
        return
    if title_key in hero.titles:
        return  # already earned
    if hero.skill_ranks.get(skill_key, 0) < 5:
        return

    MASTERY_NAMES = {
        "brawl_master":        "Brawl Master",
        "combat_medic":        "Combat Medic",
        "charismatic_speaker": "Charismatic Speaker",
        "armor_piercer":       "Armor Piercer",
        "death_challenger":    "Death Challenger",
    }

    MASTERY_DESC = {
        "brawl_master":        "+2 Min/Max ATK permanently.",
        "combat_medic":        "Passive: Restore 10% max HP at the end of each of your combat turns.",
        "charismatic_speaker": "Passive: +15% ATK bonus for the entire fight (applied at fight start).",
        "armor_piercer":       "Passive: Your basic attacks reduce enemy DEF by 1 each hit.",
        "death_challenger":    "Passive: Death Defier costs 1 less AP to cast.",
    }

    print("\n" + "=" * 50)
    print(f"🏅  SKILL MASTERED: {MASTERY_NAMES[title_key]}!")
    print("=" * 50)
    print(f"  {MASTERY_DESC[title_key]}")
    print("=" * 50)

    # Apply one-time stat buffs where applicable
    award_title_with_buff(hero, title_key)


def switch_title_menu(hero):
    """
    Let the player swap their active displayed title.
    Only shown in rest_phase when hero.titles has 2+ entries.
    Filters to equippable titles only — fate titles never appear here.
    """
    _clear_screen()
    print("🏅 Your Titles\n")
    title_list = list(hero.titles)

    if not title_list:
        print("You haven't earned any titles yet.")
        input("\nPress Enter...")
        return

    for i, key in enumerate(title_list, 1):
        display = TITLE_DISPLAY.get(key, key)
        active_marker = " ◀ active" if key == hero.active_title else ""
        print(f"{i}) {display}{active_marker}")

    print("0) Back")
    choice = input("\nChoose a title to equip: ").strip()

    if choice == "0":
        return
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(title_list):
            hero.active_title = title_list[idx]
            display = TITLE_DISPLAY.get(hero.active_title, hero.active_title)
            print(f"\n✨ Active title set to: {display}")
            input("\nPress Enter...")
