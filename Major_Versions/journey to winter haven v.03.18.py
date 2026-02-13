import textwrap
import os
import random
import time
import math
import sys
from colorama import init

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

_real_input = input

DEBUG = False


def input(prompt=""):
    raw = _real_input(prompt)

    if not isinstance(raw, str):
        return raw

    cleaned = raw.strip().lower()

    # Let BOTH keywords return the debug tuple
    # (story/combat will decide what to do with it)
    if cleaned in ("m", "monster"):
        monster = monster_select_menu()
        return ("monster_select", monster)

    return raw

# ============================================================
# GLOBAL DAMAGE BONUS POLICY (single source of truth)
# Drop this near your combat helpers (same area as adrenaline/berserk helpers)
# ============================================================

BONUS_POLICY_MODE = "STATIC"  # later you can switch to "SCALE"/"SOFTCAP" etc.

def get_damage_bonuses(attacker, context: str, *, ps_rank: int = 1):
    """
    Returns (total_bonus:int, parts:dict)

    context examples:
      - "basic_attack"
      - "power_strike_hit"        (hit portion: berserk should apply)
      - "power_strike_scaling"    (scaling base: berserk must NOT apply)
      - "skill_hit"              (future)
      - "dot_tick"               (future)
    """
    parts = {
        "adrenaline": 0,
        "berserk": 0,
        "war_cry": 0,
        "equipment": 0,
    }

    # --- Base sources (today's current behavior) ----------------
    parts["adrenaline"] = int(compute_adrenaline_bonus(attacker))

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




# ===============================
# Config / Globals
# ===============================
WIDTH = 65

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


def continue_text():
    """
    Story continue prompt that supports universal monster debug.

    - ENTER = continue story
    - 'monster' = developer battle, then return to continue point
    - 'm' = treated as normal input (ignored)
    """
    global GAME_WARRIOR

    while True:
        raw = input("\n(Press ENTER to continue)\n> ")

        # ----------------------------------------------------
        # 🧬 Story-mode monster select
        # ----------------------------------------------------
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            monster = raw[1]
            if monster:
                print(wrap("\n⚔️ Debug: Starting a custom battle...\n"))
                battle(GAME_WARRIOR, monster)
            continue  # return to the same continue prompt

        # ----------------------------------------------------
        # Normal ENTER handling
        # ----------------------------------------------------
        if isinstance(raw, str) and raw.strip() == "":
            return  # continue story

        # Any other text? Ignore it and continue
        print("Just press ENTER to continue.")



def check(prompt, options=None):
    """
    Story-mode input handler.

    - 'monster' → open monster select (debug dev battle)
    - 'm' → treated as normal text (safe for names and story options)
    - normal choices validated against 'options'
    - dev shortcuts:
        q → restart intro
        c / combat → jump to arena
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
        # Developer shortcuts (story-safe)
        # ----------------------------------------------------

        # Restart game
        if cleaned == "q":
            raise RestartException

        # Quick combat jump
        if cleaned in ("c", "combat"):
            if GAME_WARRIOR is None:
                print(wrap("⚔️ Cannot start combat yet — no warrior exists."))
                continue
            raise QuickCombatException

        # Debug menu
        if cleaned == "debug":
            if GAME_WARRIOR:
                debug_menu(GAME_WARRIOR)
            else:
                print("Debug unavailable — warrior not created yet.")
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
    - Ignores the universal 'm' / 'monster' debug inputs.
    - Always returns a proper string name.
    """
    global GAME_WARRIOR

    while True:
        # Use _real_input to bypass the overridden input() that triggers debug
        raw = _real_input(prompt)

        # Ensure raw is a string
        if isinstance(raw, str):
            cleaned = raw.strip()
            if cleaned != "":
                return cleaned  # valid name entered

        # Default if input is empty
        return "Adventurer"

        


def intro_story(warrior):
    """
    Wrapper for the intro story.
    This catches developer shortcut exceptions
    and cleanly restarts or jumps into combat.
    """
    try:
        return intro_story_inner(warrior)
    except RestartException:
        clear_screen()
        print(wrap("🔄 Restarting game..."))
        return intro_story(warrior)
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
    hero.hp = min(hero.max_hp, hero.hp + heal_amount)
    actual = hero.hp - old_hp
    print(f"You recover {actual} HP! ({int(percent*100)}% heal)")

def mana_percent(hero, percent):
    if not hasattr(hero, "mana") or hero.max_mana == 0:
        print("You don't have a mana pool yet.")
        return

    mana_amount = math.ceil(hero.max_mana * percent)
    old_mana = hero.mana
    hero.mana = min(hero.max_mana, hero.mana + mana_amount)
    actual = hero.mana - old_mana
    print(f"You restore {actual} MP! ({int(percent * 100)}% mana)")


def use_potion_menu(hero):
    clear_screen()
    print("🧪 Potion Bag\n")

    # Count all potions
    total_potions = sum(hero.potions.values())
    if total_potions == 0:
        print("🧪 You reach for your potion bag… but it's empty.")
        print("You have no potions left to use.")
        space()
        input("\n(Press ENTER to continue)")
        return


    # Build dynamic menu showing ONLY potions you actually have
    available_potions = [
        (name, count) for name, count in hero.potions.items() if count > 0
    ]

    

    for i, (potion, count) in enumerate(available_potions, start=1):
        label = potion.replace("_", " ").title()
        print(f"{i}) {label} x{count}")

    print(f"{len(available_potions) + 1}) Go back")

    # Choose potion
    choice = input("\nChoose: ").strip()

    # Exit
    if choice == str(len(available_potions) + 1):
        print("You close your potion bag.")
        space()
        return

    # Validate input
    if not choice.isdigit():
        print("Invalid choice.")
        space()
        return

    index = int(choice) - 1
    if index < 0 or index >= len(available_potions):
        print("Invalid choice.")
        space()
        return

    # Identify potion
    potion_type, _ = available_potions[index]

    # Consume potion ONCE
    hero.potions[potion_type] -= 1


    # ---------- Potion Effects ----------
        
    if potion_type == "heal":   # 25% heal
        heal_percent(hero, 0.25)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()

    elif potion_type == "super_potion":  # 50% heal
        heal_percent(hero, 0.50)
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()

    elif potion_type == "ap":
        old_ap = hero.ap
        hero.ap = min(hero.max_ap, hero.ap + 1)

        print(f"\nYou drink an AP potion and recover {hero.ap - old_ap} AP!")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
        continue_text()
        space()


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

    # 🔵 Greater Mana Potion (25%)
    elif potion_type == "greater_mana":
        mana_percent(hero, 0.25)
        print(f"Current MP: {hero.mana}/{hero.max_mana}")
        continue_text()
        space()

    # 💧 Antidote (cure poison)
    elif potion_type == "antidote":
        if hero.poison_active:
            hero.poison_active = False
            hero.poison_amount = 0
            print("\n💧 You drink an antidote — poison cured!")
        else:
            print("\n💧 You drink an antidote... but you're not poisoned.")
        continue_text()
        space()

    # 🔥🧴 Burn cream (cure fire stacks)
    elif potion_type == "burn_cream":
        if hasattr(hero, "fire_stacks") and hero.fire_stacks > 0:
            hero.fire_stacks = 0
            print("\n🔥🧴 You apply burn cream — all fire stacks removed!")
        else:
            print("\n🔥🧴 You apply burn cream... but you're not burning.")
        continue_text()
        space()

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

    while hero.stat_points > 0:
        print(f"You have {hero.stat_points} stat point(s).")
        print("1) +5 Max HP")
        print("2) +1 Attack (min/max +1)")
        print("3) +1 Defense")
        print("4) +1 AP")
        print("5) Done")

        choice = input("\nChoose: ").strip()

        if choice == "1":
            hero.max_hp += 5
            hero.hp += 5
            hero.max_overheal = int(hero.max_hp * 1.10)
            hero.stat_points -= 1
            print("Max HP increased!")

        elif choice == "2":
            hero.min_atk += 1
            hero.max_atk += 1
            hero.stat_points -= 1
            print("Attack increased!")

        elif choice == "3":
            hero.defence += 1
            hero.stat_points -= 1
            print("Defense increased!")

        elif choice == "4":
            hero.max_ap += 1
            hero.ap = min(hero.ap + 1, hero.max_ap)
            hero.stat_points -= 1
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
    Auto-exits when all points are spent (no back-button spam).
    """
    while True:
        # ✅ If everything is spent, give a clean continue and exit
        if hero.stat_points <= 0 and hero.skill_points <= 0:
            print("\n✅ All points spent.")
            input("Press Enter to continue...")
            return

        clear_screen()
        print("📈 Spend Points\n")
        print(f"Stat Points:  {hero.stat_points}")
        print(f"Skill Points: {hero.skill_points}\n")

        # Only show options that are actually usable
        if hero.stat_points > 0:
            print("1) Spend Stat Points")
        if hero.skill_points > 0:
            print("2) Spend Skill Points")
        print("0) Back")

        choice = input("> ").strip()

        if choice == "0":
            return

        elif choice == "1" and hero.stat_points > 0:
            level_up_menu(hero)

        elif choice == "2" and hero.skill_points > 0:
            show_skill_tree(hero)

        else:
            print("\nInvalid choice.")
            input("\nPress Enter...")

def has_unspent_points(hero) -> bool:
    return (getattr(hero, "stat_points", 0) + getattr(hero, "skill_points", 0)) > 0


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
            print(f"{option}) Use Heal")
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

        print(f"{option}) Review equipment (future)")
        equip_option = str(option)
        option += 1

        print(f"{option}) Continue to next opponent")
        cont_option = str(option)

        raw = input("\nChoose: ")

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
            print("\n🛡️ Equipment system coming soon!")
            space()
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
    warrior.hp = warrior.max_hp
    warrior.max_overheal = int(warrior.max_hp * 1.10)
    warrior.ap = warrior.max_ap

    # Clear combat stats
    reset_between_rounds(warrior)
    # Reset Death Defier for the new stage
   
   
    


    print(f"\n❤️ You are fully healed: {warrior.hp}/{warrior.max_hp} HP")
    print(f"🔵 AP restored: {warrior.ap}/{warrior.max_ap}")
    space(2)

    # -------- SMALL HUB LOOP (all dialogue is placeholder) --------
    talked_goblin = False
    talked_ogre = False
    talked_hooded = False
    talked_crafter = False
    talked_merchant = False
    talked_trainer = False
    talked_bo = False

    while True:
        print("What would you like to do before the next stage of the tournament?")
        print("1) Talk to the goblin bookie (wip)")
        print("2) Talk to the ogre guard (wip)")
        print("3) Talk to the hooded figure (wip)")
        print("4) Talk to crafter (wip)")
        print("5) Talk to merchant (wip)")
        print("6) Talk to trainer (wip)")
        print("7) Talk to Bo (wip)")
        print("8) Rest until you’re called")
        print("9) Check your status")

        raw = input("\nChoose: ")

        # Allow monster debug here too
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            monster = raw[1]
            if monster:
                battle(warrior, monster)
            clear_screen()
            continue

        choice = str(raw).strip()

        if choice == "1":
            clear_screen()
            # TODO: add goblin bookie dialogue here
            if not talked_goblin:
                talked_goblin = True
                print(wrap("(The goblin holds up an empty coin purse and glances upward impatiently.)"))

               
            else:
                print("(You get the feeling he’s far more excited about future winnings than you are.)")
            space(2)

        elif choice == "2":
            clear_screen()
            # TODO: add ogre guard dialogue here
            if not talked_ogre:
                talked_ogre = True
                print("(The guard makes a low annoyed grunt)")
            else:
                print("(The guard glares at you, What!)")
            space(2)

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

        elif choice == "4":
            clear_screen()
            if not talked_crafter:
                talked_crafter = True
                print("Im working on it. These things take time.")
            else:
               print("(He mutters something about 'days' and 'deadlines'.)")
        
        elif choice == "5":
            clear_screen()
            if not talked_merchant:
                talked_merchant = True
                print(wrap(
                    "The merchant stands behind an empty stall, hands folded patiently."
                ))
            else:
                print(wrap(
                    "(You get the sense he wishes he had more to sell.)"
                ))
            space(2)

        elif choice == "6":
            clear_screen()
            if not talked_trainer:
                talked_trainer = True
                print(wrap(
                    "The trainer looks at you and says, 'I wish I could teach you more'."
                ))
            else:
                print(wrap(
                    "(The trainer looks at you and says, 'Developing new skills takes a while, doesn't it'.)"
                ))
            space(2)

        elif choice == "7":
            clear_screen()
            if not talked_bo:
                talked_bo = True
                print(wrap("Bo glances at you and says, 'I knew you were a good choice for the tournament.'"))

            else: 
                print(wrap("Bo gives you a slow confident grin. 'Win this thing and i'll give you something special.'"))

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
        print("1) Force Berserk")
        print("2) Clear Berserk")
        print("3) Apply Blindness")
        print("4) Apply Burn (1 stack)")
        print("5) Apply Poison (2 dmg)")
        print("6) Heal to Full")
        print("7) Activate Death Defier")
        print("8) Trigger Death Defier (test)")
        print("9) Level Up")
        print("10) Defence Break")
        print("11) Skill Editor (set any skill rank)")  # ✅ NEW
        print("12) Exit Current Run")
        print("13) Exit Debug Menu")
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
            # Newer burn system uses warrior.burns; keep it compatible.
            if not hasattr(warrior, "burns"):
                warrior.burns = []
            warrior.burns.append({"turns": 2, "damage": 1})
            warrior.fire_stacks = len(warrior.burns)
            print("🔥 Debug: Burn stack applied.")
            input("\nPress Enter...")

        # --- 5) Poison ---
        elif choice == "5":
            warrior.poison_active = True
            warrior.poison_amount = 2
            warrior.poison_turns = 3
            warrior.poison_skip_first_tick = False
            print("☠️ Debug: Poison applied (2 dmg, 3 turns).")
            input("\nPress Enter...")

        # --- 6) Heal ---
        elif choice == "6":
            warrior.hp = warrior.max_hp
            print("💖 Debug: Healed to full.")
            input("\nPress Enter...")

        # --- 7) Activate Death Defier ---
        elif choice == "7":
            warrior.death_defier = True
            warrior.death_defier_river = True  # debug = free version
            warrior.death_defier_active = True
            warrior.death_defier_used = False
            print("💀 Debug: Death Defier granted (river/free) + activated.")
            input("\nPress Enter...")

        # --- 8) Trigger Death Defier test ---
        elif choice == "8":
            # This simulates a death to verify the hook works
            if "try_death_defier" in globals():
                warrior.hp = 0
                try_death_defier(warrior, source="debug")
            else:
                print("⚠️ try_death_defier() not found in globals().")
            input("\nPress Enter...")

        # --- 9) Level up ---
        elif choice == "9":
            if hasattr(warrior, "level_up"):
                warrior.level_up()
                print("📈 Debug: Level up triggered.")
            else:
                warrior.level += 1
                print("📈 Debug: Level increased by 1 (fallback).")
            input("\nPress Enter...")

        # --- 10) Defence Break ---
        elif choice == "10":
            warrior.defence_broken = True
            warrior.defence_break_turns = 2
            print("🛡️ Debug: Defence break applied (2 turns).")
            input("\nPress Enter...")

        # --- 11) Skill editor (NEW) ---
        elif choice == "11":
            _debug_skill_editor(warrior)

        # --- 12) Exit run ---
        elif choice == "12":
            sys.exit(0)

        # --- 13) Exit debug menu ---
        elif choice == "13":
            return


def monster_select_menu():
    clear_screen()
    print("===== MONSTER SELECT =====")
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
              }

    if choice in monster_map:
        monster = monster_map[choice]()
        print(f"⚔️ You selected: {monster.name}")

        # --- Start the debug battle immediately ---
        result = battle(GAME_WARRIOR, monster)

        # --- Check if player died ---
        if result is False or not GAME_WARRIOR.is_alive():
            print("\n💀 You were defeated in the debug battle!")
            GAME_WARRIOR.hp = GAME_WARRIOR.max_hp
            print(f"💖 HP restored to {GAME_WARRIOR.hp} for continued testing.")
            return None


        return monster

    print("Cancelled.")
    return None

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


def resolve_player_turn_stop(hero):
    """
    Returns True if the player's action is blocked this turn.
    Enforces: you cannot lose your action two turns in a row.
    """
    # Backward safety (in case something calls this on an older object)
    if not hasattr(hero, "turn_stop"):
        hero.turn_stop = 0
    if not hasattr(hero, "turn_stop_reason"):
        hero.turn_stop_reason = ""
    if not hasattr(hero, "turn_stop_chain_guard"):
        hero.turn_stop_chain_guard = False

    if hero.turn_stop <= 0:
        hero.turn_stop_chain_guard = False
        return False

    # Chain guard: if they already lost their action last player turn, they act now.
    if hero.turn_stop_chain_guard:
        hero.turn_stop = 0
        hero.turn_stop_reason = ""
        hero.turn_stop_chain_guard = False
        return False

    # Block action this turn
    hero.turn_stop -= 1
    hero.turn_stop_chain_guard = True
    return True

def simple_trainer_reaction(hero):
    """Checks 1–2 flags and prints the right message."""
    
    if "warrior_arena_escape" in hero.story_flags:
        print(wrap("I heard you tried to run. Hah! You made them work for it."))
        print(wrap("Use that fire out there — the crowd loves a fighter."))
        return
    
    if "warrior_arena_submit" in hero.story_flags:
        print(wrap("You just walked into the cell, huh?"))
        print(wrap("Being passive won't save you in the arena — find your spark."))
        return

    print(wrap("Whatever brought you here, it won't matter once the gates open."))

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
    If points remain, ask once. If none remain, just continue.
    """
    while True:
        stat = getattr(hero, "stat_points", 0)
        skill = getattr(hero, "skill_points", 0)

        if stat <= 0 and skill <= 0:
            return True

        print(f"\nYou still have points left to spend: Stat={stat}, Skill={skill}")
        ans = input(f"{prompt} (y/n): ").strip().lower()

        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
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

def reset_between_rounds(hero):
    # DoTs / debuffs that should not persist between fights
    clear_all_burns(hero)

    hero.poison_active = False
    hero.poison_amount = 0
    hero.poison_turns = 0

    hero.war_cry_bonus = 0
    hero.war_cry_turns = 0

    hero.blind_turns = 0
    hero.blind_long = False

    hero.turn_stop = 0
    hero.turn_stop_chain_guard = False
    hero.paralyze_vulnerable = False

    # --- Fallen Warrior: Defence Warp cleanup (boss-only debuff) ---
    if hasattr(hero, "defence_warp_phase"):
        del hero.defence_warp_phase
    if hasattr(hero, "defence_warp_original_defence"):
        del hero.defence_warp_original_defence

    # Optional: clear “one-fight only” flags here if you have them
    # hero.defense_break = False   # example if you store something like this

def blind_damage_multiplier(hero):
    if hero.blind_turns >= 3:
        return 0.5
    elif hero.blind_turns == 2:
        return 0.25
    return 1.0




def space(line=1):
    for _ in range(line):
        print()

def wrap(text):
    return textwrap.fill(text, 
                         WIDTH, 
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



# ===============================
# Monster Special Moves
# ===============================
def slime_poison_spit(slime, hero):
    if slime.ap <= 0:
        return None

    slime.ap -= 1

    # ---- Physical hit ONLY (defence applies) ----
    roll = random.randint(1, 3)
    actual = hero.apply_defence(roll, attacker=slime)
    hero.hp = max(0, hero.hp - actual)
    

    # ---- Apply poison (NO damage yet) ----
    hero.poison_active = True
    hero.poison_amount = 2        # flat, ignores defence
    hero.poison_turns = 2
    hero.poison_skip_first_tick = True

    print(wrap(
        f"{slime.name} spits corrosive slime! "
        f"You take {actual} damage and are poisoned!"
    ))

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

    # 50% chance to fail
    if random.random() > 0.5:
        return None

    # Successful Fire Spit consumes AP
    slime.ap -= 1

    print(f"🔥 {slime.name} spits burning slime at you!")

    # --------------------------------
    # 1) PHYSICAL IMPACT (defense applies)
    # --------------------------------
    normal_roll = random.randint(slime.min_atk, slime.max_atk)
    normal_actual = hero.apply_defence(normal_roll, attacker=slime)
    hero.hp = max(0, hero.hp - normal_actual)

    if normal_actual > 0:
        print(f"💥 The impact splashes against you for {normal_actual} physical damage! "
              f"(rolled {normal_roll})")
    else:
        print(f"🛡️ You brace yourself and block the heated splash. "
              f"(rolled {normal_roll})")

    # --------------------------------
    # 2) FIRE DAMAGE (TRUE damage, ignores defence)
    # --------------------------------
    fire_damage = random.randint(2, 3)
    hero.hp = max(0, hero.hp - fire_damage)

    print(f"🔥 Burning slime scorches your skin for {fire_damage} fire damage!")

    # --------------------------------
    # 3) APPLY BURN STACK (DoT) — per-stack timers
    # --------------------------------
    if not hasattr(hero, "burns"):
        hero.burns = []

    if len(hero.burns) < 2:
        hero.burns.append({"turns_left": 2, "skip": True})
    else:
        weakest_idx = min(
            range(len(hero.burns)),
            key=lambda i: hero.burns[i]["turns_left"]
        )
        hero.burns[weakest_idx] = {"turns_left": 2, "skip": True}

    hero.fire_stacks = len(hero.burns)
    stack_text = "stack" if hero.fire_stacks == 1 else "stacks"
    print(f"🔥 Burning slime clings to your skin! ({hero.fire_stacks} burn {stack_text})")

    show_health(hero)

    # Return total immediate damage
    return normal_actual + fire_damage





def goblin_cheap_shot(enemy, warrior):
    """Goblin special move: blinds the warrior + deals max damage ignoring defence."""
    
    if enemy.ap <= 0:
        return None

    enemy.ap -= 1

    # Apply blindness
    warrior.blind_turns = 3
    warrior.blind_long = True

    print("\n🗡️ The goblin gets close and blows dust into your eyes!")
    print("😵 You are BLINDED! You cannot block or attack on your next turn!")

    # Max-damage, defence-break attack
    damage = enemy.max_atk
    actual = damage
    warrior.hp = max(0, warrior.hp - actual)
   
    

    print(f"👁️ The goblin strikes while you're vulnerable for {actual} MAX DAMAGE!")

    return actual

def paralyzing_shot(enemy, warrior):
    if enemy.ap <= 0:
        return None

    # Don't waste AP trying to paralyze if it can't meaningfully stick
    # (already turn-stopped, or chain guard prevents consecutive turn loss)
    if getattr(warrior, "turn_stop", 0) > 0 or getattr(warrior, "turn_stop_chain_guard", False):
        return None

    if random.random() > 0.5:
        return None

    enemy.ap -= 1
    print("\n🏹 The goblin archer fires a coated arrow!")
    print("🧪 A paralytic resin glistens on the tip...")

    roll = random.randint(enemy.min_atk, enemy.max_atk)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    # Unified turn-stop system (prevents chaining turn-loss)
    apply_turn_stop(warrior, turns=1, reason="Paralyzed")

    # Your existing "punish window" can stay if you like
    warrior.paralyze_vulnerable = True

    print(f"💥 The arrow hits for {actual} damage! (rolled {roll})")
    print("🧊⚡ You are PARALYZED! You will lose your next action!")
    show_health(warrior)
    return actual



def imp_sneak_attack(enemy, warrior):
    """
    Imp special move:
    Teleports behind the warrior and strikes for max damage on first turn.
    Deals +1 damage if the warrior has no defence.
    """

    if enemy.ap <= 0:
        return None

    enemy.ap -= 1

    print("\n👿 The imp vanishes in a puff of smoke!")
    print("⚡ It reappears behind you, striking before you can react!")

    # Guaranteed max base damage
    damage = enemy.max_atk  # 4

    # Bonus damage if no defence
    if warrior.defence == 0:
        damage += 1
        print("🩸 Your lack of defense leaves you wide open!")

    # Apply damage directly
    warrior.hp = max(0, warrior.hp - damage)

    print(f"🗡️ The imp deals {damage} damage!")

    return damage

def brittle_skeleton_thrust(self, target):
    if self.ap <= 0:
        return 0

    damage = 6
    if target.defence == 0:
        damage += 1

    print("The skeleton lunges with a precise thrust!")

    self.ap -= 1
    target.hp = max(0, target.hp - damage)

    print(f"You take {damage} damage!")
    return damage

def wolf_pup_bite(enemy, warrior):
    if enemy.ap <= 0:
        return None
    if random.random() > 0.5:
        return None

    enemy.ap -= 1

    print("🐺 The wolf pup lunges forward and viciously bites you!")

    # Base attack (defence applies)
    roll = random.randint(2, 5)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)


    # Bite bonus (ignores defence)
    bite_bonus = random.randint(1,5)
    warrior.hp = max(0, warrior.hp - bite_bonus)

    print(f"🩸 You take {actual} damage from the strike!")
    print(f"🩸 The bite rips flesh for {bite_bonus} extra damage!")

    # One-turn bleed
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

    # SAFEGUARD: only use if missing health
    if enemy.hp >= enemy.max_hp:
        return None

    # 50% chance to actually use the move
    if random.random() > 0.5:
        return None

    enemy.ap -= 1

    print("\n🐺 The dire wolf pup lunges with a DEVOURING BITE!")

    # Normal physical bite (defence applies)
    roll = random.randint(enemy.min_atk, enemy.max_atk)
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    print(f"🩸 You take {actual} damage! (rolled {roll})")

    # Lifesteal heal: half the damage dealt (rounded down)
    heal = actual // 2
    if heal > 0:
        before = enemy.hp
        enemy.hp = min(enemy.max_hp, enemy.hp + heal)
        gained = enemy.hp - before
        print(f"🧶 The dire wolf pup devours flesh and regains {gained} HP!")
    else:
        print("🛡️ Your defence denies the wolf its meal!")

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

    # 50% chance to use the move when AP is available
    if random.random() > 0.5:
        return None

    enemy.ap -= 1

    print("\n👻 The ghost's claws pass through your flesh, chilling your soul!")

    # ---------- Step 1: physical hit (defence applies) ----------
    roll = random.randint(enemy.min_atk, enemy.max_atk)
    physical = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - physical)

    print(f"🩸 You take {physical} damage from the ghostly strike! (rolled {roll})")

    # ---------- Step 2: life drain (ignores defence) ----------
    # drain is based on the *original* roll, not reduced damage
    drain = max(1, roll // 2)  # e.g. 6 → 3, 5 → 2
    before = warrior.hp
    warrior.hp = max(0, warrior.hp - drain)
    actual_drain = before - warrior.hp  # prevents healing more than was actually lost

    # Make sure ghost has an overheal cap
    if not hasattr(enemy, "max_overheal"):
        enemy.max_overheal = int(enemy.max_hp * 1.5)

    enemy.hp = min(enemy.max_overheal, enemy.hp + actual_drain)

    print(
        f"💀 Life Leech drains an additional {actual_drain} HP "
        f"(ignores defence) and empowers the ghost!"
    )
    show_health(warrior)
    # If you ever add an enemy HP HUD, it will reflect overheal too.

    # Total damage to the hero this turn
    return physical + actual_drain

def blinding_charge(self, hero):
    if self.ap <= 0:
        return None
    if random.random() > 0.33:
        return None

    self.ap -= 1

    print("\n👺 The goblin blinds you as the wolf pup charges!")

    damage = random.randint(4, 8)
    hero.hp = max(0, hero.hp - damage)

    # Only apply blind + turn-stop if the hero is NOT already blinded
    if getattr(hero, "blind_turns", 0) > 0:
        print("👁️‍🗨️ You're already blinded — the charge just hits HARD!")
    else:
        # Apply blind (your existing system)
        hero.blind_turns = 1
        hero.blind_long = False

        # NEW: costs the player's next action, but cannot chain (your loop handles that)
        apply_turn_stop(hero, turns=1, reason="Blinded")

    print(f"🐺 You take {damage} damage!")
    show_health(hero)
    return damage


def impact_bite(self, hero):
    if self.ap <= 0:
        return None
    
    if random.random() > 0.5 :
        return None
    self.ap -= 1
    print("\n🐗 The javelina barrels into you and snaps its jaws!")

    # Impact damage (defence applies)
    roll = random.randint(4, 6)
    actual = hero.apply_defence(roll, attacker=self)
    hero.hp = max(0, hero.hp - actual)

    print(f"💥 You take {actual} damage from the impact!")

    # Bite follow-up (pressure, not guaranteed)
    if hero.defence <= 1 and hero.hp > 0:
        bite = random.randint(2, 4)
        hero.hp = max(0, hero.hp - bite)
        print(f"🦷 The javelina bites down for {bite} extra damage!")

    show_health(hero)
    return actual

def fallen_defence_warp(enemy, warrior):
    """
    Fallen Warrior special: Defence Warp

    - 33% chance when he attacks
    - Costs 1 AP when it goes off
    - Heavy hit, 9–11 damage with current stats (5–9 base)
    - Hit itself uses NORMAL defence rules
    - THEN, if damage actually gets through and the hero has defence:
        * 1st warped enemy turn: defence = 0
        * 2nd warped enemy turn: defence = 50% of original
        * After that: defence fully restores
    """

    # No AP? No special.
    if enemy.ap <= 0:
        return None

    # 33% chance to trigger
    if random.random() >= 0.33:
        return None

    enemy.ap -= 1

    print(f"\n💀 {enemy.name} twists his blade with a warped defence-breaking technique!")
    print("🌀 Your armour shudders as the strike slips past your guard!")

    # With min_atk=5 and max_atk=9, this gives 9–11 damage BEFORE defence
    roll = random.randint(enemy.max_atk, enemy.max_atk + 2)

    # ⭐ IMPORTANT: NORMAL defence applies here
    # e.g. roll = 7, defence = 2 → 2 blocked, 5 damage taken
    actual = warrior.apply_defence(roll, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    print(f"🩸 The warped strike tears through you for {actual} damage! (rolled {roll})")
    show_health(warrior)

    # If no damage got through OR you have no defence, there is nothing to warp.
    if actual <= 0:
        return actual
    warp_active = hasattr(warrior, "defence_warp_phase")
    
    if warrior.defence <= 0 and not warp_active:
        return actual

    # Store original defence and start (or refresh) the warp phase sequence.
    # If the hero is already warped, DO NOT let the sequence "stabilise"—reset it.
    if warp_active:
        warrior.defence_warp_phase = 0
        print(wrap("🌀 The warped curse tightens again — your armour cannot stabilise yet."))
    else:
        warrior.defence_warp_original_defence = warrior.defence
        warrior.defence_warp_phase = 0


    print(wrap(
        "You feel your armour and body destabilising — seams creak and plates rattle. Your muscles warp and contort "
        "Your defence is coming apart. You no longer feel protected."
    ))

    return actual

def try_death_defier(hero, reason=""):
    # Only triggers if you'd die right now
    if hero.hp > 0:
        return False

    if hero.death_defier and hero.death_defier_active and not hero.death_defier_used:
        hero.hp = 1
        hero.death_defier_used = True
        hero.death_defier_active = False

        print()
        print(wrap("💀✨ Death Defier surges — you refuse to die!"))
        if reason:
            print(wrap(f"(Saved from: {reason})"))
        show_health(hero)
        return True

    return False



# =============================
# HERO MOVES
# =============================

def activate_death_defier(hero):
    """
    Uses the hero's turn to activate Death Defier.
    Costs 0 AP if unlocked from the river.
    Costs 1 AP if unlocked later by level.
    Does no damage, just sets the passive.
    """
    # Already primed or spent?
    if hero.death_defier_used:
        print("You've already used Death Defier this tournament.")
        return False

    if hero.death_defier_active:
        print("Death Defier is already active.")
        return False

    if not hero.death_defier:
        print("You don't have that ability.")
        return False

    # Cost based on how it was unlocked
    cost = 0 if hero.death_defier_river else 1

    if hero.ap < cost:
        print("You don't have enough AP.")
        return False

    hero.ap -= cost
    hero.death_defier_active = True

    print()
    print(wrap(
        "You close your eyes and chant, grounding your body and spirit to the land of the living."
        " You will not so easily succumb to death now."
    ))
    print(f"(Death Defier is now active. AP remaining: {hero.ap})")
    return True

def heal_ap_cost(rank: int) -> int:
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3
HEAL_PERCENTS = {
    1: 0.10,
    2: 0.20,
    3: 0.35,
    4: 0.50,
    5: 0.75,
}

def choose_heal_rank_smart(hero, learned_rank: int):
    learned_rank = min(learned_rank, 5)

    affordable = [
        r for r in range(1, learned_rank + 1)
        if hero.ap >= heal_ap_cost(r)
    ]

    if not affordable:
        print("You don't have enough AP to heal.")
        return None

    if len(affordable) == 1:
        return affordable[0]

    while True:
        print("\n💖 Choose Heal rank:")
        print(f"🔵 AP: {hero.ap}")
        print("0) Back")

        for r in range(learned_rank, 0, -1):
            cost = heal_ap_cost(r)
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
            if 1 <= r <= learned_rank and hero.ap >= heal_ap_cost(r):
                return r
        print("Invalid choice.")

def heal(hero, chosen_rank=None, mode="rest"):
    learned = hero.skill_ranks.get("heal", 0)

    if learned <= 0:
        print("You haven't learned Heal.")
        return False

    if hero.hp >= hero.max_hp:
        print("You're already at full health")
        if mode != "combat":
            continue_text()
        return False

    learned = min(learned, 5)

    # Choose rank
    if chosen_rank is None:
        if mode == "combat":
            affordable = [r for r in range(1, learned + 1) if hero.ap >= heal_ap_cost(r)]
            if not affordable:
                print("You don't have enough AP to heal.")
                return False

            chosen_rank = max(affordable)
            cost = heal_ap_cost(chosen_rank)

            if cost == 3:
                pct = int(HEAL_PERCENTS[chosen_rank] * 100)
                ans = input(
                    f"\n💖 Heal will use Rank {chosen_rank} ({pct}%) for {cost} AP. Use it? (y/n): "
                ).strip().lower()
                if ans not in ("y", "yes"):
                    print("You hold your healing for now.")
                    return False
        else:
            chosen_rank = choose_heal_rank_smart(hero, learned)
            if chosen_rank is None:
                return False

    # Sanitize chosen rank
    chosen_rank = max(1, min(int(chosen_rank), learned))

    # Spend AP
    ap_cost = heal_ap_cost(chosen_rank)
    if hero.ap < ap_cost:
        print("Not enough AP!")
        return False
    hero.ap -= ap_cost

    # Apply heal (no overheal)
    percent = HEAL_PERCENTS[chosen_rank]
    heal_amount = math.ceil(hero.max_hp * percent)

    before = hero.hp
    hero.hp = min(hero.max_hp, hero.hp + heal_amount)
    actual = hero.hp - before

    print()
    print(wrap(
        f"💖 You focus and mend your wounds. "
        f"You recover {actual} HP "
        f"({int(percent * 100)}% heal, Rank {chosen_rank})."
    ))
    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    show_health(hero)

    return True

def war_cry_ap_cost(rank: int) -> int:
    # Match your “tiered” AP pattern:
    # R1-2: 1 AP, R3-4: 2 AP, R5: 3 AP
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3


WAR_CRY_EFFECTS = {
    1: (1, 3),  # +1 for 3 turns
    2: (2, 3),  # +2 for 3 turns
    3: (3, 3),  # +3 for 3 turns
    4: (3, 4),  # +3 for 4 turns
    5: (5, 3),  # +5 for 3 turns (special burst)
}

def war_cry(hero, chosen_rank=None):
    learned = hero.skill_ranks.get("war_cry", 0)
    if learned <= 0:
        print("You haven't learned War Cry.")
        return False

    learned = min(learned, 5)

    # Pick rank: in combat we auto-pick highest affordable (like your Heal/PS pattern)
    if chosen_rank is None:
        affordable = [r for r in range(1, learned + 1) if hero.ap >= war_cry_ap_cost(r)]
        if not affordable:
            print("You don't have enough AP for War Cry.")
            return False
        chosen_rank = max(affordable)
    else:
        chosen_rank = max(1, min(int(chosen_rank), learned))

    cost = war_cry_ap_cost(chosen_rank)
    if hero.ap < cost:
        print("Not enough AP!")
        return False

    bonus, turns = WAR_CRY_EFFECTS[chosen_rank]

    hero.ap -= cost

    # Re-cast friendly: overwrite bonus & reset duration
    hero.war_cry_bonus = bonus
    hero.war_cry_turns = turns
    hero.war_cry_skip_first_tick = True

    print()
    print(wrap(
        f"🗣️ You unleash a WAR CRY! "
        f"(Rank {chosen_rank}, Cost {cost} AP)\n"
        f"Your attacks surge with power: +{bonus} to attack rolls for {turns} turns."
    ))
    print(f"🔵 AP remaining: {hero.ap}/{hero.max_ap}")
    return True



def power_strike_ap_cost(rank: int) -> int:
    if rank <= 2:
        return 1
    elif rank <= 4:
        return 2
    return 3


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

    affordable = [r for r in range(1, learned_rank + 1) if warrior.ap >= power_strike_ap_cost(r)]
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
            cost = power_strike_ap_cost(r)
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

        cost = power_strike_ap_cost(chosen)
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

    ap_cost = power_strike_ap_cost(chosen_rank)
    if warrior.ap < ap_cost:
        print("Not enough AP!")
        return False
    warrior.ap -= ap_cost

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
    # BLINDNESS scaling (keep your existing behavior)
    # --------------------------
    raw_for_defence = total_raw
    if getattr(warrior, "blind_turns", 0) > 0:
        mult = 0.5 if warrior.blind_turns >= 2 else 0.75
        raw_for_defence = max(1, int(raw_for_defence * mult))
        print(f"Blinded! Power Strike power reduced to {int(mult * 100)}%.")

    final = enemy.apply_defence(raw_for_defence, attacker=warrior)
    enemy.hp = max(0, enemy.hp - final)

    blocked = raw_for_defence - final

    # --------------------------
    # One-line breakdown
    # --------------------------
    print(f"\nPOWER STRIKE! (Rank {chosen_rank}, Cost {ap_cost} AP)")

    parts = [f"Roll {base_roll}"] + hit_parts_txt + [f"Power Strike {impact}"]
    if raw_for_defence != total_raw:
        parts.append(f"Blind Adjusted {raw_for_defence}")

    # this is where damage is calculated
    line = f"You smash {enemy.name} for {final} damage! (" + " + ".join(parts) + ")"
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

    return True




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
        # ---------------------------------------------
        if hasattr(self, "berserk_active") and self.berserk_active:
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
        # 🧮 Compute block ratio for flavor (BEFORE minimum damage rule)
        # ---------------------------------------------
        blocked_amount = min(self.defence, damage)
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
        actual = damage - self.defence
        actual = max(1, actual)

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
        special_move=None
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

    def attack(self, target):
        """Normal monster attack.
    Special moves are handled in enemy_attack().
    """
        damage = random.randint(self.min_atk, self.max_atk)
        actual = target.apply_defence(damage, attacker=self)
        target.hp = max(0, target.hp - actual)
        return actual

                    
                                
        
class Hero(Creator):
    def __init__(self, name, hp, min_atk, max_atk,
                 gold=0, xp=0, defence=0, potions=None):
        super().__init__(name, hp, min_atk, max_atk, gold, xp, defence)

        # AP system (default for Warrior — other classes can override)
        self.ap = 3
        self.max_ap = 3
        # 🛡️ Overheal cap (10% extra HP allowed)
        self.max_overheal = int(self.max_hp * 1.10)



        # Equipment and inventory
        self.inventory = []
        self.equipment = {
            "weapon": None,
            "armor": None,
            "trinket": None
        }

        # Potion dictionary
        if potions is None:
            self.potions = {
                "heal": 0,
                "super_potion": 0,
                "ap": 0,
                "mana": 0,
                "greater_mana": 0,
                "antidote": 0,
                "burn_cream": 0
            }
        else:
            self.potions = potions

        self.level = 1
        self.xp_to_lvl = 10
        self.titles = set ()
        self.achievements = set()
        self.bestiary = set()
        self.endings = set()
        self.monster_essence = []

        # ✅ NEW: shared story / trainer tracking for all hero classes
        # Flags like: "warrior_origin_duskhollow", "warrior_arena_escape",
        # "mage_origin_eldenspire", etc.
        self.story_flags = set()
        # Which trainer / special scenes have already fired (per context)
        self.trainer_seen = set()
        self.death_reason = None

        # NEW: pool of points to spend in rest_phase()
        self.stat_points = 0
        self.skill_points = 0

        # Rage System
        self.max_rage = 0
        self.rage_state = 0
        self.current_bonus_damage = 0

        # Status effects
        self.poison_active = False
        self.poison_amount = 0
        self.blind_turns = 0
        self.blind_long = False
        
        self.bleed_turns = 0
        
        self.paralyze_vulnerable = False

        # 🔥 Fire damage-over-time (per-stack tracking)
        self.burns = []          # one dict per burn stack
        self.fire_stacks = 0     # for UI (len(burns))

        # Turn stopers
        self.turn_stop = 0
        self.turn_stop_reason = ""
        self.turn_stop_chain_guard = False

        # War Cry (duration-based buff)
        self.war_cry_bonus = 0
        self.war_cry_turns = 0
        self.war_cry_skip_first_tick = False

                # 💀 Death Defier (one-save passive)
        self.death_defier = False          # owns the skill at all
        self.death_defier_river = False    # if True: activation costs 0 AP
        self.death_defier_active = False   # primed right now
        self.death_defier_used = False     # already triggered this run


        self.skills = set()
        self.skill_ranks = {
        "heal": 0,
        "power_strike": 0,
        # add later as you implement them:
        "war_cry": 0,
        # "berserk": 0,
}

        self.skill_progress = {}

        # Mana (default none — used for Mages)
        self.mana = 0
        self.max_mana = 0


        

        



    # ---------- Display ----------
    def show_game_stats(self, enemy=None):
        """Side-by-side HUD with hero info block and enemy HP block only."""

        hero_bar = hp_bar(
            self.hp,
            self.max_hp,
            size=10,
            max_overheal=getattr(self, "max_overheal", self.max_hp)
        )

        print("\n" + "=" * 40)

        # --- HERO / ENEMY HP SIDE BY SIDE ---
        if enemy is not None:
            ebar = hp_bar(
                enemy.hp,
                enemy.max_hp,
                size=10,
                max_overheal=getattr(enemy, "max_overheal", enemy.max_hp)
            )

            print(
                f"🧝 {self.name.title():<10} "
                f"❤️ [{hero_bar}] {self.hp}/{self.max_hp:<2}   |   "
                f"💚 {enemy.name.title():<10} "
                f"❤️ [{ebar}] {enemy.hp}/{enemy.max_hp:<2}"
            )
        else:
            # Fallback: hero only (no enemy)
            print(
                f"🧝 {self.name.title():<10} "
                f"❤️ [{hero_bar}] {self.hp}/{self.max_hp}"
            )

                # --- HERO INFO BELOW LEFT SIDE ---
        print(f"🔵 AP {self.ap}/{self.max_ap}")

        adr = getattr(self, "current_bonus_damage", 0)
        wc = getattr(self, "war_cry_bonus", 0)
        wc_turns = getattr(self, "war_cry_turns", 0)
        bers = getattr(self, "berserk_bonus", 0) if getattr(self, "berserk_active", False) else 0
        total = adr + wc + bers

        if total == 0:
            print("💥 Bonus: 0")
        else:
            parts = []
            if adr:  parts.append(f"Adrenaline {adr}")
            if wc:   parts.append(f"War Cry {wc}")
            if bers: parts.append(f"Berserk {bers}")
            print(f"💥 Bonus: {total} ({' | '.join(parts)})")

            # 💀 Death Defier status (quick HUD)
            if getattr(self, "death_defier", False):
                if getattr(self, "death_defier_used", False):
                    print("💀 Death Defier: USED")
                elif getattr(self, "death_defier_active", False):
                    print("💀 Death Defier: READY")
                else:
                    print("💀 Death Defier: available")


        print(berserk_meter(self))

        print("=" * 40)
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

        title_line = f" - {titles_list[-1]}" if titles_list else ""
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

        print("💥 Bonus: " + (" | ".join(parts) if parts else "0"))

        # Death Defier status
        if getattr(self, "death_defier", False):
            if getattr(self, "death_defier_used", False):
                dd = "USED"
            elif getattr(self, "death_defier_active", False):
                dd = "READY"
            else:
                cost = 0 if getattr(self, "death_defier_river", False) else 1
                dd = f"Available (activate {cost} AP)"
            print(f"💀 Death Defier: {dd}")

        # Key debuffs only if active
        if getattr(self, "blind_turns", 0) > 0:
            print(f"👁️ Blind: {self.blind_turns}T")
        if getattr(self, "poison_active", False) and getattr(self, "poison_turns", 0) > 0:
            print(f"☠️ Poison: {self.poison_amount}/tick ({self.poison_turns}T)")
        if getattr(self, "fire_stacks", 0) > 0:
            print(f"🔥 Burn: {self.fire_stacks} stack(s)")
        if getattr(self, "defence_broken", False) and getattr(self, "defence_break_turns", 0) > 0:
            print(f"🛡️ Defence Break: {self.defence_break_turns}T")
        if hasattr(self, "defence_warp_phase"):
            print("🌀 Defence Warp: ACTIVE")

        # Optional: show enemy quick line if provided
        if enemy is not None:
            try:
                print("-" * 40)
                print(f"💚 {enemy.name}: {enemy.hp}/{enemy.max_hp} HP  |  AP {enemy.ap}/{enemy.max_ap}")
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
        wc_bonus = getattr(self, "war_cry_bonus", 0)
        wc_turns = getattr(self, "war_cry_turns", 0)

        print("\n🗣️ War Cry:")
        if wc_turns > 0 and wc_bonus > 0:
            print("   Status: ACTIVE")
            print(f"   Bonus Damage: +{wc_bonus}")
            print(f"   Turns Remaining: {wc_turns}")
        else:
            print("   Status: Inactive")

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
    # ---------- Leveling ----------
        
    def level_up(self):
        """
        If XP >= threshold:
        - Level up once
        - Reduce XP
        - Increase next XP threshold
        - Grant 2 stat points to spend later in rest_phase()
        """
        while self.xp >= self.xp_to_lvl:
            self.level += 1
            
            self.xp -= self.xp_to_lvl
            self.xp_to_lvl = int(self.xp_to_lvl * 1.75)

           # grant points to pool
            STAT_POINTS_PER_LEVEL = 2
            SKILL_POINTS_PER_LEVEL = 2

            self.stat_points += STAT_POINTS_PER_LEVEL
            self.skill_points += SKILL_POINTS_PER_LEVEL

            print(f"\n[LEVEL UP] {self.name} reached level {self.level}!")
            print(f"You gained {STAT_POINTS_PER_LEVEL} stat points to spend during your next rest.")
            print(f"You gained {SKILL_POINTS_PER_LEVEL} skill points.")


            # 🔥 NEW: Full heal on level-up
            old_hp = self.hp
            self.hp = self.max_hp
            self.max_overheal = int(self.max_hp * 1.10)
            self.hp = min(self.hp, self.max_overheal)

            print(f"❤️ You feel completely rejuvenated! "
                f"HP restored from {old_hp} to {self.hp}.")
            
            choice = input("\nSpend level up points now? (y/n): ").strip().lower()
            if choice == "y":
                
                spend_points_menu(self)
            else:
                print("You can spend them later from your status menu.")

SKILL_DEFS = {
    "power_strike": {
        "name": "Power Strike",
        "min_level": 1,
        "max_rank": 10,
        # cost to go from rank N -> N+1 (rank 0->1 uses index 0)
        "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
        "desc": "A powerful single attack that converts AP into impact damage."

    },
    "heal": {
        "name": "Heal",
        "min_level": 1,
        "max_rank": 10,
        "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
        "desc": "Restore HP (10% per rank). Rank 10: party heal (later).",
    },
    "war_cry": {
        "name": "War CRY",
        "min_level": 1,
        "max_rank": 10,
        "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
        "desc": "Battle cry that buffs/debuffs (later).",
    },
}

def skill_visible(hero, key):
    """Hide skills until min_level, unless already unlocked."""
    rank = hero.skill_ranks.get(key, 0)
    req = SKILL_DEFS[key]["min_level"]
    return hero.level >= req or rank > 0

def next_skill_cost(hero, key):
    """Cost to go from current rank -> next rank."""
    rank = hero.skill_ranks.get(key, 0)
    costs = SKILL_DEFS[key]["upgrade_costs"]
    max_rank = SKILL_DEFS[key]["max_rank"]

    if rank >= max_rank:
        return None  # already maxed
    # rank 0->1 uses costs[0], rank 1->2 uses costs[1], etc.
    return costs[rank]

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

            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)

            if cost is None:
                cost_text = "MAX"
                prog_text = ""
            else:
                cost_text = f"{cost} SP"
                # show progress only if not maxed
                prog_text = f" | Progress: {bank}/{cost}" if (bank > 0 or cost > 1) else ""

            status = "Unlocked" if rank > 0 else "Locked"
            req = data["min_level"]
            if rank == 0 and hero.level < req:
                status = f"Locked (Requires Lv {req})"

            print(f"{i}) {name:<12}  Rank {rank}/{max_rank}  |  Next: {cost_text}{prog_text}  |  {status}")
            print(f"   {data['desc']}")

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
        if hero.skill_points <= 0:
            print("\nYou have no skill points to invest.")
            input("\nPress Enter...")
            continue

        # invest as much as possible into this skill (up to completing the next cost)
        bank = hero.skill_progress.get(key, 0)
        cost = next_skill_cost(hero, key)

        to_invest = min(hero.skill_points, max(0, cost - bank))
        hero.skill_points -= to_invest
        hero.skill_progress[key] = bank + to_invest

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
            upgraded = True

        if upgraded:
            print(f"\n✅ {SKILL_DEFS[key]['name']} upgraded to Rank {hero.skill_ranks[key]}!")
        elif to_invest > 0:
            cost = next_skill_cost(hero, key)
            bank = hero.skill_progress.get(key, 0)
            print(f"\n📘 Invested {to_invest} SP into {SKILL_DEFS[key]['name']} ({bank}/{cost}).")
        else:
            print("\n📘 No additional points needed for this skill right now.")

        input("\nPress Enter...")



def skill_menu(hero, enemy):
    while True:
        clear_screen()
        hero.show_game_stats(enemy)

        options = []  # (key, label, callable)

        # -------------------------
        # DEATH DEFIER
        # -------------------------
        if hero.death_defier and not hero.death_defier_active and not hero.death_defier_used:
            cost = 0 if hero.death_defier_river else 1

            if hero.ap < cost:
                label = f"Death Defier (Cost {cost} AP) [Not enough AP]"
                fn = None
            else:
                label = f"Death Defier (Cost {cost} AP)"
                fn = lambda: activate_death_defier(hero)

            options.append(("death_defier", label, fn))

        # -------------------------
        # POWER STRIKE (downcast-aware)
        # -------------------------
        ps_rank = hero.skill_ranks.get("power_strike", 0)
        if ps_rank > 0:
            max_rank = min(ps_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= power_strike_ap_cost(r)]

            if not affordable:
                label = f"Power Strike (Rank {ps_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = power_strike_ap_cost(default_rank)
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
                          if hero.ap >= heal_ap_cost(r)]

            if not affordable:
                label = f"Heal (Rank {heal_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = heal_ap_cost(default_rank)
                label = f"Heal (Rank {heal_rank} → {default_rank}, Cost {default_cost} AP)"
                fn = lambda h=hero: heal(h, mode="combat")


            options.append(("heal", label, fn))

        # -------------------------
        # WAR CRY
        # -------------------------
        wc_rank = hero.skill_ranks.get("war_cry", 0)
        if wc_rank > 0:
            max_rank = min(wc_rank, 5)

            affordable = [r for r in range(1, max_rank + 1)
                          if hero.ap >= war_cry_ap_cost(r)]

            if not affordable:
                label = f"War Cry (Rank {wc_rank}) [Not enough AP]"
                fn = None
            else:
                default_rank = max(affordable)
                default_cost = war_cry_ap_cost(default_rank)
                bonus, turns = WAR_CRY_EFFECTS[default_rank]
                label = (f"War Cry (Rank {wc_rank} → {default_rank}, "
                         f"Cost {default_cost} AP, +{bonus} for {turns} turns)")
                fn = lambda h=hero, r=default_rank: war_cry(h, r)

            options.append(("war_cry", label, fn))

        # -------------------------
        # DISPLAY MENU
        # -------------------------
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

        # >>> THIS WAS THE PART MISSING <<<
        if not berserk_block_messages:  
            if tier == 1:
                print("🔥 Your adrenaline spikes (+1 damage).")
            elif tier == 2:
                print("🔥🔥 Pain sharpens your focus (+2 damage).")
            elif tier == 3:
                print("🔥🔥🔥 You push past the pain (+3 damage).")
            elif tier == 0:
                print("You steady your breathing.")

    return tier + warrior.max_rage




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
        # Optionally clear any 'berserk_pending' flag if it still exists
        warrior.berserk_pending = False


# ===============================
# Monsters
# ===============================
# Ap currrntly goes up based on hp 13 hp = 2ap, 27 hp = 3 ap, 42 hp = 4ap for now
class Green_Slime(Monster):
    def __init__(self):
        super().__init__(
            name="green slime",
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
            name="young goblin",
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
            name="goblin archer",
            hp=15,
            min_atk=3,
            max_atk=5,
            gold=0,
            xp=17,
            essence=["goblin archer essence"],
            defence=1,
            ap=2
        )
        self.special_move = paralyzing_shot


class Brittle_Skeleton(Monster):
    def __init__(self):
        super().__init__(
            name="brittle skeleton",
            hp=12,
            min_atk=2,
            max_atk=5,
            gold=0,
            xp=9,
            essence=["skeleton essence"],
            defence=1,
            ap=1)

        self.special_move= brittle_skeleton_thrust
        
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
            name="wolf pup",
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
            name="dire wolf pup",
            hp=16,                       # lowered because DEF is 3 and it can heal
            min_atk=4,                   # 4–6 is chunky but fair
            max_atk=6,
            gold=0,
            xp=19,
            essence=["dire wolf pup essence"],
            defence=2,
            ap=2,
        )
        self.special_move = devouring_bite

            
class Red_Slime(Monster):
    def __init__(self):
        super().__init__(
            name = "red slime",
            hp=16,
            min_atk=2,
            max_atk=4,
            gold=0,
            xp=16,
            essence=["red slime essence"],
            defence=1,
            ap=2
        )
        self.special_move = red_slime_fire_spit         
          
class Fallen_Warrior(Monster):
    def __init__(self):
        super().__init__(
            name="fallen warrior",
            hp=43,
            min_atk=5,
            max_atk=9,
            gold=0,
            xp=43,
            essence=["fallen warrior essence"],
            defence=3,
            ap=4
        )
        self.special_move = fallen_defence_warp
        


   

            
        

class Noob_Ghost(Monster):
    def __init__(self):
        super().__init__(
            name="noob ghost",
            hp=16,
            min_atk=3,
            max_atk=6,
            gold=0,
            xp=13,
            essence=["ghost essence"],
            defence=0,
            ap=2
        )

        # 👻 Overheal pool so life drain is never "wasted"
        self.max_overheal = int(self.max_hp * 1.5)

        # Hook up the life leech special
        self.special_move = ghost_life_leech

        

class Wolf_Pup_Rider(Monster):
    def __init__(self):
        super().__init__(name= "wolf pup rider",
                         hp=21,
                         min_atk=3,
                         max_atk=7,
                         gold=0,
                         xp=23,
                         essence=["young goblin essence", "wolf pup essence"],
                         defence=3,
                         ap = 2
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
            hp=18,
            min_atk=3,
            max_atk=6,
            gold= 0,
            xp=18,
            essence=["Javelina essence"],
            defence=2,
            ap=2,
            
            
        )
        self.special_move = impact_bite

    






# ===============================
# Hero Type
# ===============================
class Warrior(Hero):
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

        # ---------- Warrior-Specific: Berserk System ----------
        self.berserk_active = False
        self.berserk_pending = False
        self.berserk_used = False
        self.berserk_turns = 0
        
        self.berserk_bonus = 0  # extra damage while berserk

               # ---------- Warrior-Specific: Death Defier ----------
        self.death_defier = False
        self.death_defier_river = False
        self.death_defier_active = False
        self.death_defier_used = False

        # ---------- Warrior-Specific: War Cry ----------
        self.war_cry_bonus = 0
        self.war_cry_turns = 0

        # ---------- Warrior-Specific: Adrenaline ----------
        self.current_bonus_damage = 0






# ===============================
# Encounter Helpers
# ===============================

# Main monster list used for both arena + debug
# Weight determines tier (3=T1, 2=T2, 1=T3, <1=T4)
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
    
    


def get_monsters_by_tier(tier):
    return [cls for cls, weight in MONSTER_TYPES if weight_to_tier(weight) == tier]


def random_encounter_by_tier(tier):
    pool = get_monsters_by_tier(tier)
    if not pool:
        raise ValueError(f"No monsters defined for tier {tier}")
    return random.choice(pool)()


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
            return cls()
    return TIER4_BOSSES[-1][0]()  # fallback
  

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
        return pick_tier_from_weights({1: 0.6, 2: 0.4})
    if round_num == 3:
        return pick_tier_from_weights({1: 0.1, 2: .8, 3: 0.1})
    if round_num == 4:
        return pick_tier_from_weights({2: .1, 3: .9})
    
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
        return random_encounter_by_tier(tier)


# ---------- Debug: fully random by weight ----------
def random_encounter():
    """
    Legacy debug encounter using the raw weighted list.
    Great for testing new monsters quickly.
    """
    types, weights = zip(*MONSTER_TYPES)
    chosen_cls = random.choices(types, weights=weights, k=1)[0]
    return chosen_cls()

# ===============================
# Combat System
# ===============================
def warrior_attack_roll(warrior):
    return random.randint(warrior.min_atk, warrior.max_atk)





def enemy_attack(enemy, warrior):
    """Enemy performs one attack. Handles all monster special moves safely."""
    enemy.rounds_in_combat +=1

    # -------------------------------------------------------------
    # 1. GREEN GOBLIN — Guaranteed cheap-shot on first turn only
    # -------------------------------------------------------------
    if enemy.name == "young goblin":
        if not getattr(enemy, "used_cheap_shot", False):
            enemy.used_cheap_shot = True
            # Goblin special_move() already prints + returns damage
            return enemy.special_move(enemy, warrior)

    # -------------------------------------------------------------
    # 2. GREEN SLIME — Guarnteed to use poison spit on turn 1
    # -------------------------------------------------------------
    if enemy.name == "green slime":
        if enemy.rounds_in_combat ==1 and enemy.ap > 0:
            return enemy.special_move(enemy, warrior)
        # No AP left → fallback to normal hit
        damage = enemy.attack_roll()
        actual = warrior.apply_defence(damage, attacker=enemy)
        warrior.hp = max(0, warrior.hp - actual)
        print(f"{enemy.name} attacks you for {actual} damage! (rolled {damage})")
        show_health(warrior)
        if warrior.hp <= 0:
            if try_death_defier(warrior, f"{enemy.name} attack"):
                return 0
        return actual

    # -------------------------------------------------------------
    # 3. GENERIC SPECIAL MOVE (Fallen Warrior, etc.)
    # -------------------------------------------------------------
    special = getattr(enemy, "special_move", None)
    if enemy.ap > 0 and callable(special):
        result = special(enemy, warrior)
        if result is not None:
            # Specials handle their own printing and HP changes
            if warrior.hp <= 0:
                try_death_defier(warrior, f"{enemy.name} special")
            return result

        # -------------------------------------------------------------
    # 🧊⚡ PARALYSIS VULNERABILITY (one-time max damage on next hit)
    # -------------------------------------------------------------
    force_max = False
    if getattr(warrior, "paralyze_vulnerable", False):
        force_max = True
        warrior.paralyze_vulnerable = False
        print("🧊⚡ You’re still stiff from paralysis — you can’t brace properly!")


    # -------------------------------------------------------------
    # 4. NORMAL ATTACK (any monster with no specials, or no AP left)
    # -------------------------------------------------------------
    damage = enemy.max_atk if force_max else enemy.attack_roll()

    actual = warrior.apply_defence(damage, attacker=enemy)
    warrior.hp = max(0, warrior.hp - actual)

    print(wrap(f"{enemy.name} attacks you for {actual} damage! (rolled {damage})"))
    show_health(warrior)
    # --- Death Defier (monster damage)
    if warrior.hp <= 0:
        if try_death_defier(warrior, f"{enemy.name} attack"):
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


def player_basic_attack(warrior, enemy):
    # 1) Roll
    roll = warrior_attack_roll(warrior)

    # 2) Bonuses (single source of truth)
    bonus_total, parts = get_damage_bonuses(warrior, "basic attack")
    bonus_parts = bonus_parts_to_text(parts)

    # If other code expects this to be a NUMBER, keep it updated correctly:
    warrior.current_bonus_damage = parts.get("adrenaline", 0)

    # 3) Total + defence
    total = roll + bonus_total
    actual = enemy.apply_defence(total, attacker=warrior)
    enemy.hp = max(0, enemy.hp - actual)

    blocked = total - actual

    # 4) One-line breakdown
    line_parts = [f"Roll {roll}"] + bonus_parts
    line = f"You attack {enemy.name} for {actual} damage! (" + " + ".join(line_parts) + ")"
    if blocked > 0:
        line += f"  [Blocked {blocked}]"
    print(wrap(line))


    #print(f"You attack {enemy.name} for {actual} damage! (" + " + ".join(parts) + ")")
    print(f"❤️ {enemy.name.title()} HP: {enemy.hp}/{enemy.max_hp}")

    # 5) Berserk extension + tick (unchanged)
    if enemy.hp <= 0 and getattr(warrior, "berserk_active", False):
        warrior.berserk_turns += 1
        print("🩸 Your killing blow feeds the frenzy! Berserk is extended!")

    if getattr(warrior, "berserk_active", False):
        warrior.berserk_turns -= 1
        if warrior.berserk_turns <= 0:
            deactivate_berserk(warrior)
            print("💤 Your Berserk fury subsides...")

    return actual






def battle(warrior, enemy, skip_rest=False):
    """
    Wrapper that runs battle_inner and handles control-flow exceptions.
    Returns:
      True  -> warrior won
      False -> warrior lost
      "win" -> special tournament win condition (fallen warrior)
    """
    try:
        result = battle_inner(warrior, enemy, skip_rest=skip_rest)

        # ✅ Normalize results so None never counts as a "loss by accident"
        if result is None:
            # If battle_inner ever falls through (shouldn't), treat as loss-safe:
            # you can also raise an error here if you'd rather catch it in testing.
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
        print(wrap("🛡️ Your defeneces collapses under the warped curse — you lose all defence!"))

    elif phase == 1:
        if orig > 0:
            half = max(1, orig // 2)
        else:
            half = 0
        warrior.defence = half
        warrior.defence_warp_phase = 2
        print(wrap("🛡️ Your defences begins to stabilise, partially restoring your defence."))

    elif phase == 2:
        warrior.defence = orig
        print(wrap("🛡️ Your defences fully stabilises — your defence returns to normal."))
        del warrior.defence_warp_phase
        if hasattr(warrior, "defence_warp_original_defence"):
            del warrior.defence_warp_original_defence


def battle_inner(warrior, enemy, skip_rest=False):


    print(f"\n{warrior.name} enters the arena!")
    print(f"You face a {enemy.name}!")

    # Decide who starts
    warrior_turn = random.choice([True, False])
    player_turn_started = False

    if warrior_turn:
        warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)
        print("You get the first move!")
        
        # Show HUD immediately
        

    else:
        print(f"{enemy.name} makes the first move!")

        # Enemy attacks immediately BEFORE the loop
        enemy_attack(enemy, warrior)

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
    while warrior.is_alive() and enemy.is_alive():
        turn_spent = False
        # Reset per-turn Dealth Defier flag
       
        

        # ---------------------------------------
        # PLAYER TURN
        # ---------------------------------------
        if warrior_turn:

            
            

            # ---------------------------------------
            # TURN STOP (stun/freeze/paralyze/etc.)
            # Anti-chain rule: cannot lose action twice in a row
            # ---------------------------------------
            if not player_turn_started:
                player_turn_started = True
                if resolve_player_turn_stop(warrior):
                    print(f"🧊⚡ Your muscles lock up — you're {warrior.turn_stop_reason.upper()} and lose your action!")
                    warrior_turn = False
                    player_turn_started = False
                    continue


                

                # ==========================
                # 1) APPLY POISON DAMAGE
                # ==========================
                if warrior.poison_active:
                    if getattr(warrior, "poison_skip_first_tick", False):
                        # Do not tick on the same round poison is applied
                        warrior.poison_skip_first_tick = False
                    else:
                        warrior.hp = max(0, warrior.hp - warrior.poison_amount)

                        # ✅ Death Defier can trigger on poison deaths
                        if warrior.hp <= 0:
                            try_death_defier(warrior, "poison")

                        warrior.poison_turns -= 1

                        print(wrap(
                            f"☠️ The lingering poison irritates your skin and lungs. "
                            f"You take {warrior.poison_amount} poison damage."
                        ))
                        show_health(warrior)

                        # Poison expires cleanly
                        if warrior.poison_turns <= 0:
                            warrior.poison_active = False
                            print("💨 The poison fades from your body.")

                # ==========================
                # 2) APPLY FIRE DAMAGE (DoT)
                # ==========================
                burns = getattr(warrior, "burns", [])

                if burns:
                    fire_damage = 0
                    any_tick = False
                    new_burns = []

                    for idx, burn in enumerate(burns, start=1):
                        # First turn after application: skip damage, just clear the flag
                        if burn.get("skip", False):
                            burn["skip"] = False
                            new_burns.append(burn)
                            continue

                        # Stack is now active
                        if not any_tick:
                            print("🔥 The lingering burn continues to heat your skin…")
                            any_tick = True

                        tick = random.randint(1, 3)
                        fire_damage += tick
                        print(f"🔥 Burn stack {idx} scorches you lightly for {tick} fire damage.")

                        burn["turns_left"] -= 1
                        if burn["turns_left"] > 0:
                            new_burns.append(burn)
                        # if turns_left <= 0, this stack expires

                    # Apply total burn damage
                    if fire_damage > 0:
                        warrior.hp = max(0, warrior.hp - fire_damage)

                        # ✅ Death Defier can trigger on burn deaths
                        if warrior.hp <= 0:
                            try_death_defier(warrior, "burn")

                        show_health(warrior)
                        print(f"🔥 Total burn damage: {fire_damage}")


                    # Update remaining stacks
                    warrior.burns = new_burns
                    warrior.fire_stacks = len(new_burns)

                    # Message if ALL burns are gone this turn
                    if not new_burns and burns:
                        expired_count = len(burns)
                        print(
                            f"💨 The flames finally die out "
                            f"({expired_count} burn stack{'s' if expired_count > 1 else ''} fade)."
                        )

                            


                            

                # ==========================
                # 3) APPLY BLEED DAMAGE (1 turn only)
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
            # DOT Death Defier (DOT save)
            # ==========================

            # --- after applying poison/fire damage ---
            if warrior.hp <= 0:
                try_death_defier(warrior, "DOT")

            if not warrior.is_alive():
                print("\nYou succumb to your wounds...")
                return False



            

            # ==========================
            # 5) CHECK BERSERK TRIGGER
            # ==========================
            check_berserk_trigger(warrior)

            # ==========================
            # 6) ADRENALINE UPDATE
            # ==========================
            warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)

            # ==========================
            # 7) SHOW UI
            # ==========================
            warrior.show_game_stats(enemy=enemy)

            # ==========================
            # 8) INPUT + DEBUG + Monster Select COMMANDS
            # ==========================
            prompt = textwrap.fill(
                "Your move:\n"
                "1) Attack\n"
                "2) Special \n"
                "3) Use Potion\n"
                "4) Run Away\n"
                "5) Check Stats\n"
                "(Type 1-5)",
                WIDTH
            )
            raw = input(prompt + "\n> ")

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

            # --- Developer shortcut: quit / pause ---
            if cleaned == "q":
                print("\n🔄 Developer Shortcut: Quit / Pause triggered.")
                raise RestartException


            # ----------------------------------------------------
            # Debug console shortcut
            # ----------------------------------------------------
            if cleaned == "debug":
                debug_menu(warrior, enemy)
                continue

            # ----------------------------------------------------
            # Validate combat choices
            # ----------------------------------------------------
            if cleaned not in ("1", "2", "3", "4", "5"):
                print("Invalid choice, try again.")
                continue

            choice = cleaned


            # ==========================
            # 9) PLAYER ACTIONS
            # ==========================

            if choice == "5":
                clear_screen()
                warrior.show_combat_stats()
                input("\nPress Enter...")
                continue

            elif choice == "4":
                print(textwrap.fill(
                    "You turn your back on the crowd and attempt to flee the arena! "
                    "The crowd boos and you are shot in the back.", WIDTH))
                space()
                print(textwrap.fill(
                    "Death comes slowly. The arrow drips with lethal poison. "
                    "Five minutes of agony follow.", WIDTH))
                space()
                print(textwrap.fill(
                    "As you take your final breath, the monster shaman whispers:"
                    " 'You are not even worthy of resurrection.'", WIDTH))
                warrior.hp = 0
                warrior.death_reason = "ran away"
                continue_text()

                warrior.titles.add("Coward")
                warrior.endings.add("Disgraced One")
                warrior.show_all_game_stats()
                input("\nPress Enter to quit.")
                quit()

            elif choice == "1":
                player_basic_attack(warrior, enemy)
                turn_spent = True

            elif choice == "2":  # Special
                used = skill_menu(warrior, enemy)
                if used:
                    turn_spent = True
                    
                   
                    
                



            elif choice == "3":
                use_potion_menu(warrior)
                turn_spent = True
                

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
                if hasattr(warrior, "original_defence"):
                    warrior.defence = warrior.original_defence
                    del warrior.original_defence

                print(f"\nYou have defeated {enemy.name}!")
                warrior.gold += enemy.gold
                warrior.xp += enemy.xp
                warrior.monster_essence.extend(enemy.essence)
                print(f"You gain {enemy.xp} XP.")

                if hasattr(enemy, "drop_loot"):
                    loot = enemy.drop_loot()
                    if loot:
                        warrior.inventory.append(loot)
                        print(f"{loot} added to inventory!")

                    # 🏟️ Victory is now tied to defeating the Fallen Warrior
                    if enemy.name == "fallen warrior":
                        print("\n✨ The arena falls silent as the Fallen Warrior collapses!")
                        print("🏆 The crowd roars — you are the Champion of the Arena!")
                        GAME_WARRIOR.titles.add("Champion of the Arena")
                        GAME_WARRIOR.endings.add("champion_ending")
                        warrior.show_game_stats()
                        return "win"


                input("Press Enter to continue.")
                warrior.level_up()
                if not skip_rest:
                    rest_phase(warrior)

                warrior.blind_turns = 0
                warrior.blind_long = False
                warrior.poison_active = False
                warrior.poison_amount = 0
                warrior.fire_stacks = 0
                warrior.fire_skip_first_tick = False

                return True

        # ---------------------------------------
        # ENEMY TURN
        # ---------------------------------------
        else:
            enemy_attack(enemy, warrior)
            turn_spent = True

            if not warrior.is_alive():
                print("\nYou collapse as the arena roars...")
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

            warrior_turn = not warrior_turn # chatgpt always wants to change this my way is the correct way
            player_turn_started = False






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
            "Nob’s eyes flick over your bruises like numbers on a ledger. "
            "'You already got your lesson in the cell,' he mutters. "
            "'Now spend what you’ve earned — and don’t waste it.'"
        ))
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
    print("✨ You gain 1 stat point AND 1 skill point to spend before the tournament begins.")
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

    
    # 🔸 One-time pre-tournament trainer scene
    trainer_stat_point_scene(warrior)

    champion = False  # <-- Tracks if final victory was achieved

    print(textwrap.fill(
        "You are pushed out onto the arena floor. Magical torches flare to life around the ring. "
        "The stands are packed with monsters of every shape and size, all howling for blood.",
        WIDTH
    ))


    defeated_names = []

    for round_num in range(1, rounds_to_win + 1):
        print(f"\n--- Round {round_num} ---")

        if round_num == rounds_to_win:
            # Allow Death Defier to be primed again for the final fight
            warrior.death_defier_used = False

        enemy = select_arena_enemy(round_num)
        result = battle(warrior, enemy, skip_rest=(round_num >= rounds_to_win - 1))


        # If this result means "you beat the Fallen and won the whole thing"
        if result == "win":
            champion = True
            defeated_names.append(enemy.name)  # count the Fallen (or final enemy)
            break
            
        if result == "tournament":
            return

        # Normal arena death (not the special Fallen ending from battle())
        if not result or not warrior.is_alive():
            print(textwrap.fill(
                f"{enemy.name} stands victorious over your fallen body. "
                "As your vision fades to black, you hear a voice proclaim, "
                "'You will serve the beast gods for all eternity!'",
                WIDTH
            ))
            space()
            print("The last thing you hear is the crowd roaring in truimph")
            GAME_WARRIOR.titles.add("Fallen Champion")
            GAME_WARRIOR.endings.add("fallen_ending")
            print("You acquired the Title: Fallen Champion")

            GAME_WARRIOR.show_all_game_stats()
            return
        
        # You won this round but the tournament isn't over yet
        defeated_names.append(enemy.name)

        # 🔸 After the 4th round (penultimate), send the player to the quarters
        if round_num == rounds_to_win - 1 and warrior.is_alive():
            arena_quarters_interlude(warrior)
            clear_screen()
            # TODO: add sunrise / under-arena transition text here if you want

    # --------- POST-TOURNAMENT SUMMARY ---------
    print("\n🏆 You are victorious in the arena!")
    if defeated_names:
        print("You defeated:", ", ".join(defeated_names))
    print(f"You leave with {warrior.gold} gold and {len(warrior.monster_essence)} essences.")
    # Perfect place to plug in endings / titles later.

    if champion:
        # --- Champion Victory Rewards ---
        warrior.titles.add("Champion of the Arena")
        warrior.endings.add("champion_ending")

        warrior.show_game_stats()

        print("\n🏆 Title Earned: Champion of the Arena")
        print("📜 Ending Unlocked: champion_ending")
        print(textwrap.fill(
            "Your triumph echoes throughout the arena! The monsters fall silent for a moment, "
            "then unleash a deafening roar of approval. Your legend begins here.",
            WIDTH
        ))

# ===============================
# Story / Intro
# ===============================
def intro_story_inner(warrior):
    """Long-form intro story leading into the arena_battle(warrior)."""

    clear_screen()
    print(textwrap.fill(
        "You find yourself stumbling through a forest late at night. "
        "Your torch flickers against the shadows of the trees.",
        WIDTH
    ))

    space()
    print(textwrap.fill(
        "You are hungry and exhausted, trying to reach the nearest town: Winter Haven.",
        WIDTH
    ))
    space()
    winter_heaven_info = check(
        "Would you like more information about Winter Haven? (yes/no)\n> ",
        ["yes", "no"]
    )

    

    # ============================================================
    # BRANCH: LEARN ABOUT WINTER HAVEN
    # ============================================================
    if winter_heaven_info == "yes":
        clear_screen()
        print(textwrap.fill(
            "Winter Haven is a small, poor mountain town. It isn't the most exciting place, "
            "but there is a dungeon nearby.",
            WIDTH
        ))
        print(textwrap.fill(
            "It used to be a mining town, but most of the resources have long since dried up.",
            WIDTH
        ))

        space()
        print(textwrap.fill(
            "There is a rumor that whenever a dungeon floor is fully cleared, the resources "
            "mysteriously replenish themselves. According to legend, that hasn't happened "
            "in nearly a century.",
            WIDTH
        ))

        space()
        print(textwrap.fill(
            "You find yourself contemplating what could cause such a miracle.",
            WIDTH
        ))
        print(textwrap.fill(
            "Lost in thought, you fail to notice a tree stump in front of you.",
            WIDTH
        ))
        
        
    

        print(textwrap.fill(
            "Your foot catches on the stump and you tumble forward. Your torch flies from your "
            "hand and lands in the mouth of a nearby cave.",
            WIDTH
        ))
        print(textwrap.fill(
            "A deep, angry voice echoes from within, \"Who goes there?\"",
            WIDTH
        ))

        continue_text()
        clear_screen()
        GAME_WARRIOR.name = get_name_input()


        print(textwrap.fill(
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
            print(textwrap.fill(
                "You turn and sprint into the forest, but the beastman is far too fast. "
                "He charges after you with terrifying speed. "
                "Your mind begins to cloud you as you realize you are now the prey.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                "A short chase ensues, but the beastman's agility and animalistic aggression "
                "are overwhelming. He slams into you with a brutal tackle.",
                WIDTH
            ))

            space()
            beast_man_tackle = random.randint(1, 4)
            GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - beast_man_tackle)
            print(textwrap.fill(
                f"Pain sears through your body. You take {beast_man_tackle} damage.",
                WIDTH
            ))
            print(textwrap.fill(
                f"You have {GAME_WARRIOR.hp} HP remaining.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                "Perhaps trying to escape wasn't the best decision after all.",
                WIDTH
            ))

            print(textwrap.fill(
                "The beastman roars in triumph and laughs. "
                "\"Nice try,\" he says. \"That's the most fun I've had in a while. "
                "You might actually have a chance in our tournament.\"",
                WIDTH
            ))

            space()
            print(textwrap.fill("The beast man slips you a healing potion. 'I'll be betting on, you dont let me down'", WIDTH))
        # this rewards player with an extra heal potion for being brave
            GAME_WARRIOR.potions["heal"] += 1

            tournament_knowledge = check(
                "\nWould you like to learn about the tournament? (yes/no)\n> ",
                ["yes", "no"]
            )
            clear_screen()

           
                

            # Learn about tournament
            if tournament_knowledge == "yes":
                print(textwrap.fill(
                    "You ask the beastman about the tournament.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "\"Ah, the tournament,\" he rumbles. "
                    "\"As you adventurers train to kill monsters, "
                    "our monsters also train to kill adventurers.\"",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    "\"We gain new skills, just like you do. The tournament is a test for our young warriors.\"",
                    WIDTH
                ))
                print(textwrap.fill(
                    f"\"The tournament pits a random adventurer— you, {warrior.name} — "
                    "against four different monsters of varying strength. "
                    "Defeat all four in single combat, then fight the champion and you win your freedom.\"",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    "\"Every monster contains an essence. Those essences are the price of your freedom.\"",
                    WIDTH
                ))
                print(textwrap.fill(
                    "You feel like the beastman might be willing to share more information "
                    "if you can persuade him.",
                    WIDTH
                ))
                continue_text()
                clear_screen()
               

                tournament_inquiry = check(
                    "\nDo you inquire further? (yes/no)\n> ",
                    ["yes", "no"]
                )

                
                if tournament_inquiry == "yes":
                    
                    persuasion_roll = random.randint(1, 20)
                    

                    if persuasion_roll >= 12:
                        # Successful persuasion
                        extra_info_choice = check(
                            textwrap.fill(
                                "What else would you like to know?\n"
                                "Type '(1' for more about monster essences,\n"
                                "or ('2' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["1", "2"]
                        )

                        if extra_info_choice == "1":
                            clear_screen()
                            print(textwrap.fill(
                                "\"You're a curious one,\" the beastman says.\n\n"
                                "\"A monster's essence is like its soul. "
                                "It allows us to revive them. You adventurers kill so many of us "
                                "that we'd go extinct without them.\"",
                                WIDTH
                            ))
                            print(textwrap.fill(
                                f"\"The tournament starts tomorrow night. Rest up, {warrior.name}. You'll need it.\"",
                                WIDTH
                            ))
                        elif extra_info_choice == "2":
                            clear_screen()
                            print(textwrap.fill(
                                "\"A fair question,\" he nods. "
                                "\"Obviously we can't have you spreading the word "
                                "about our tournaments. Other adventurers would hunt us down.\"",
                                WIDTH
                            ))
                            print(textwrap.fill(
                                "\"If you win, your memories of this place will be wiped. "
                                "You'll be left where we found you— "
                                "possibly a little stronger, with some extra gold in your pack.\"",
                                WIDTH
                            ))
                            print(textwrap.fill(
                                "\"The tournament starts tomorrow night. Good luck.\"",
                                WIDTH
                            ))
                        
                    else:
                        # Failed persuasion
                        clear_screen()
                        print(textwrap.fill(
                            "\"The only extra information I'm going to share,\" he growls, "
                            "\"is that the tournament is tomorrow night. That should be enough for you.\"",
                            WIDTH
                        ))

                # Common wrap-up for this path
                print()
                print(textwrap.fill(
                    "You are thrown into a damp cell. After a few hours of rough sleep, "
                    "you are harshly awakened by the arena trainer, Nob. 'Get up' he says 'its time for training. The beast gods want a show and you are going to give it to them.' ",
                    WIDTH
                ))
                # Story-only training — no menus yet
                warrior.story_flags.add("warrior_trained_by_nob")
                warrior.trainer_seen.add("trainer_intro_arena")

                # Reward for surviving the night
                warrior.stat_points += 1
                warrior.skill_points += 1

                

                space()
                print(textwrap.fill(
                    "After a few hours of trainng you are put back in your cell. Monster pass your cell." 
                    "You can understand some of the monsters speaking outside. Most of them "
                    "are placing bets on your chances of survival. The odds are overwhelmingly "
                    "stacked against you.",
                    WIDTH
                ))
                continue_text()
                clear_screen()

                space()
                print(textwrap.fill(
                    f"You do overhear the beastman who captured you placing a bet in your favor.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "Night falls. The cage door creaks open. You are led toward the roaring sound "
                    "of a crowd.",
                    WIDTH
                ))

                
                continue_text()
                clear_screen()
                arena_battle(GAME_WARRIOR)
                return

            if tournament_knowledge == "no":
                clear_screen()
                print(textwrap.fill(
                    "You decide to wing it. Whatever this tournament is, you'll just survive it "
                    "the same way you survive everything else: one fight at a time.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "You are thrown into a small cell. After a restless night, "
                    "you are dragged out and shoved toward the blinding light of the arena.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "The crowd roars as you step onto the bloodstained sand.",
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
            print(textwrap.fill(
                "The beastman looks disappointed. \"I always prefer when they run,\" he mutters.",
                WIDTH
            ))
            print(textwrap.fill(
                "\"Still,\" he says, eyeing you, \"I don't think you have much of a shot. "
                "Try to at least provide some entertainment.\"",
                WIDTH
            ))

            space()
            print(textwrap.fill(
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
    if winter_heaven_info == "no":
        clear_screen()
        print(textwrap.fill(
            "You trip on a cleverly camouflaged rock and your torch flies from your hand, "
            "landing in a nearby mountain river and sputtering out.",
            WIDTH
        ))
        print(textwrap.fill(
            "The forest is swallowed by darkness. The canopy above blocks out the night sky, "
            "and the silence feels oppressive.",
            WIDTH
        ))
    

        space()
        print(textwrap.fill(
            "You have no other source of light, and a soaked torch won't light easily.",
            WIDTH
        ))
        print(textwrap.fill(
            "Why tonight? You're tired, hungry, and this distorted darkness makes you feel uneasy. You were looking forward to spending the night in winter haven.",
            WIDTH
           ))
        
        space ()
        print(textwrap.fill("You have been traveling through the thick forests of the winter haven for the last few days, surviving off travelers rations, and sleeping of the cold ground", WIDTH))

        space()
        print(textwrap.fill("The rations are cold and bland, and sleeping on a bedroll is far from comfortable", WIDTH))
        print(textwrap.fill("You cant travel without a tourch. That sweet bowl of lamb stew, a warm cider and a soft bed will have to what till tomorow. Or do they?", WIDTH))

        space()

        night_choice = check(
            textwrap.fill(
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
            print(textwrap.fill(
                "Blundering around in this deep darkness seems like a bad idea. "
                "You decide to try to get a few hours of sleep before first light.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                "As you lie down, you hear distant, heavy footsteps. "
                "Fear slowly creeps into your mind. Your adrenaline rises "
                "as the footsteps grow closer.",
                WIDTH
            ))

            footsteps_choice = check(
                textwrap.fill(
                    "What do you do?\n"
                    "Type '(1' to call out, or '(2' to stay perfectly still.\n> ",
                    WIDTH
                ),
                ["1", "2"]
            )

           

            # CALL OUT
            if footsteps_choice == "1":
                clear_screen()
                print(textwrap.fill(
                    "You call out into the darkness, \"Hello? Is someone there?\"",
                    WIDTH
                ))
                continue_text()
                clear_screen()

                print(textwrap.fill(
                    "A deep, animalistic voice responds, \"Who goes there?\"",
                    WIDTH
                ))
                GAME_WARRIOR.name = get_name_input()


                print(textwrap.fill(
                    "The creature snaps its fingers. The magical darkness begins to lift. "
                    "It's still night, but you can now make out the shape of a towering figure, "
                    "like a bear standing on two legs.",
                    WIDTH
                ))

                fading_darkness = check(
                    textwrap.fill(
                        f"What do you do, {warrior.name}? Do you 'run' or 'stay'?\n> ",
                        WIDTH
                    ),
                    ["run", "stay"]
                )

                

                # RUN FROM BO
                if fading_darkness == "run":
                    clear_screen()
                    print(textwrap.fill(
                        "Your adrenaline spikes and you bolt into the trees. "
                        "Behind you, an excited roar shakes the forest.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "You glance back and see the bear-like creature charging on all fours, "
                        "rapidly closing the distance.",
                        WIDTH
                    ))

                    space()
                    print(textwrap.fill(
                        "Your panic gives you unnatural speed. For a moment, it feels like you're gaining ground.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "Then you hear a frustrated growl, followed by a sharp snap. "
                        "The forest goes dark again.",
                        WIDTH
                    ))

                    space()
                    print(textwrap.fill(
                        "With you vision suddenly obscured, you run hard, face-first into a thick tree branch.",
                        WIDTH
                    ))

                    tree_attack = random.randint(2, 5)
                    GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - tree_attack)
                    print(textwrap.fill(
                        f"You take {tree_attack} damage from the impact. Your head throbs and your vision fades.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        f"You have {GAME_WARRIOR.hp} HP remaining.",
                        WIDTH
                    ))

                    space()
                    print(textwrap.fill(
                        "When your vision clears, a massive bearman looms over you.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        f"\"Nice try, {warrior.name},\" he rumbles. \"You almost got away. "
                        "I haven't failed a pursuit in a long time. If it weren't for my magic, "
                        "you would have escaped.\"",
                        WIDTH))
                    
                    space()
                    print(textwrap.fill("here is a little somthing to help you out Bo hands you 2 potions one potion of healing and one action point potion",WIDTH))
                    GAME_WARRIOR.potions["heal"] += 1
                    GAME_WARRIOR.potions["ap"] += 1
                    
                    print(textwrap.fill(
                        "\"I think you'll be a top-tier competitor in our upcoming tournament. "
                        "My name is Boar, but most call me Bo.\"",
                        WIDTH
                    ))
                   

                    tournament_info = check(
                        "\nWould you like to learn more about the tournament? (yes/no)\n> ",
                        ["yes", "no"]
                    )

                   
                    if tournament_info == "yes":
                        clear_screen()
                        print(textwrap.fill(
                            "\"Ah yes, the monster tournament,\" Bo says proudly. "
                            "\"It's a training ground for our young who come of age. "
                            "It gives them real combat experience. Since we are constantly "
                            "being hunted by adventurers, we want our young to have the "
                            "best chance of survival.\"",
                            WIDTH
                        ))

                        space()
                        print(textwrap.fill(
                            "\"The tournament pits you against four monsters in solo combat. "
                            "If you defeat all four you fight the champion, beat him and you win. Each monster you defeat rewards you "
                            "with a monster essence. Turn in the essences, and you are set free.\"",
                            WIDTH
                        ))

                        bo_questions = check(
                            textwrap.fill(
                                "Bo asks if you have any questions.\n"
                                "Type '(1' to ask about essences,\n"
                                "or '(2' to ask what happens if you win.\n> " \
                                "or '3(' to continue on)",
                                WIDTH
                            ),
                            ["1", "2", "3"]
                        )

                        if bo_questions == "1":
                            clear_screen()
                            print(textwrap.fill(
                                "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                "\"With them, we can revive fallen monsters. The essences, "
                                "provide our people with a safe place to practice, learn hard lessons, and still live to fight another day.\"",
                                WIDTH
                            ))
                        elif bo_questions == "2":
                            clear_screen()
                            print(textwrap.fill(
                                "\"If you win,\" Bo says, \"your memories of this place will be wiped, "
                                "and you'll be returned to where we found you. "
                                "You might be stronger, richer... but you won't remember why.\"",
                                WIDTH
                            ))
                        elif bo_questions == "3":
                            print("Very well its just about time for you to meet the arena trainer Nob")

                    
                    print(textwrap.fill(
                        "Soon after, you are shackled and escorted to a fortified arena. "
                        "The crowd's distant roar vibrates through the stone beneath your feet."
                        "you rest for a few hours and are vilently woken up by a scarred, battle hardened beast folk named Nob",
                        WIDTH
                    ))
                    continue_text()
                    clear_screen()
                    arena_battle(GAME_WARRIOR)
                    return

                # STAY WITH BO
                if fading_darkness == "stay":
                    clear_screen()
                    print(textwrap.fill(
                        "You stay where you are, forcing yourself not to run.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "The bear-like creature steps into view. \"Brave, or frozen?\" he asks with a chuckle.",
                        WIDTH
                    ))
                    name = GAME_WARRIOR.name or "Adventurer"
                    print(textwrap.fill(
                        f"\"Either way, {warrior.name}, you'll do nicely for our tournament.\"",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "He introduces himself as Bo and explains the basics of the tournament: "
                        "three monsters, one human, and freedom as the prize.",
                        WIDTH
                    ))
                    continue_text()
                    clear_screen()
                    arena_battle(GAME_WARRIOR)
                    return

            # STAY SILENT
            if footsteps_choice == "2":
                clear_screen()
                print(textwrap.fill(
                    "You hold your breath and stay as still as possible. "
                    "The footsteps stop just a few paces away.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "A low growl rumbles in the darkness. \"I can smell you, human,\" "
                    "a deep voice says. \"Hiding won't help.\"",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    "A moment later, a heavy hand grabs you by the collar and hoists you off the ground.",
                    WIDTH
                ))
                print(textwrap.fill(
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
            print(textwrap.fill(
                "You rise and carefully feel your way toward the sound of the gently flowing river, "
                "hoping to recover your torch.",
                WIDTH
            ))
            river_attack = random.randint(1, 2)
            GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - river_attack)
            print(textwrap.fill(
                "As you step onto the muddy embankment, your foot slips. "
                "You tumble into the ice-cold mountain river.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                f"You take {river_attack} damage from the fall and the frigid water. "
                f"You now have {GAME_WARRIOR.hp} HP remaining.",
                WIDTH
            ))
            print(textwrap.fill(
                "The freezing water shocks your body."
                
            ))
            print(textwrap.fill(
                "Soaked, shivering, and still without a torch, you mutter a few choice words "
                "about your luck.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                "Before you can regain your bearings, a beastly voice rings out. Do you want some help? " \
                "A furry paw reaches down toward you",
                WIDTH
            ))
            accept_help = check(
                "\nDo you accept the help? (yes/no)\n> ",
                ["yes", "no"]
            )
            clear_screen()
            if accept_help == "yes":
                print(wrap("You cautiously accept the creatues paw and are lifted out " 
                "of the water."))

                space()
                print(wrap("You should be cauious of who trust. That river would have eventually killed you. "
                "Anyways, perhaps that would have been a better way to go. Regradless, we need more fighters "
                "for our tournament. Congradulations on being selcted I guess. Try not to die to fast"))
            if accept_help == "no":
                print(wrap("You decline the help and the creature says very well. The river banks " 
                " remain pretty steep for a while and there are some serious rappids " 
                "farther downstream. Good luck climbing your way out"))
                accept_help_2 = check(
                    "\nDo you reconsider and accept the help? (yes/no)\n> ",
                    ["yes", "no"]
                )
                if accept_help_2 == "yes":
                    print(wrap("You relecutently accept help. The creature introduces himself as boar. " 
                    "What is your name?"))
                    GAME_WARRIOR.name = get_name_input()
                    print(wrap("I resepct your courage aventure so I am goin give you little something special. " 
                    "Boar hands you an potion of ap."))
                    GAME_WARRIOR.potions["ap"] += 1
                    print(wrap("The creatures eyes intensify your going need it for the tournement."))
                if accept_help_2 == "no":
                    damage = river_attack*2 + 2
                    GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - damage)
                    print(wrap("Suite yourself. You continue downstream trying to find a place to climb out." \
                    " Your bodies core temperature starts to drop. Your limbs begin to go numb." \
                    " If you dont get out of the water soon the elements could kill you."))

                    space()
                    print(wrap(f"You take {damage} damage from nearby floating debris as the river picks" \
                               "up speed. Boar walks along side of you striking up a conversation he" \
                               " says his friend call him Bo and he is looking for new competers in a local" \
                               " tournament."))
                    print(wrap(f"You have {GAME_WARRIOR.hp} HP remaining."))
                    if GAME_WARRIOR.hp <= 0:
                        print("You die")
                        exit()
                    accept_help_final = check("I can see you are getting pretty cold are you sure you dont want" \
                    " my help? (yes/no)\n> ",
                    ["yes", "no"]
                    )
                    if accept_help_final == "yes":
                        print(wrap("I can see you are very brave. I will rescue you if you agree to fightin my tournament"))
                        accept_tournament = check("Do you accept? (yes/no)\n> ",
                        ["yes", "no"]
                        )
                        if accept_tournament == "yes":
                            print(wrap("Bo reaches down and effortleessly pulls you out of the fridget river. What is your name adventurer?"))
                            GAME_WARRIOR.name = get_name_input()
                            print(wrap(f"I respect your stuborness {warrior.name} let me give you a fighting chance in our tournament. Bo hands you 2 potion one for healing and one for ap"))
                            GAME_WARRIOR.potions["heal"] += 1
                            GAME_WARRIOR.potions["ap"] += 1
                                       
                                    
                                       
                                       
                    if accept_help_final ==  "no":
                        clear_screen()
                        jagged_rocks_attack = random.randint(1,6) + random.randint(1,8) + random.randint(1,10) + 6
                        GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - jagged_rocks_attack)
                        print(wrap("You refuse the help for the final time. You slip and loose your footing and the river carriers you" \
                        " jagged rock tear in to your skin."))

                        space()
                        print(f"You take {jagged_rocks_attack} damage from the surrounding sharp rocks in the water")
                        print(f"You have {GAME_WARRIOR.hp} Hp remaining")
                        if GAME_WARRIOR.hp <= 0:
                            print("Your body is flayed and you die")
                            GAME_WARRIOR.titles.add("Flayed One")
                            GAME_WARRIOR.endings.add("flayed_ending")
                            GAME_WARRIOR.show_all_game_stats()
                            input("\nPress Enter to end the game.")
                            sys.exit(0)
                        
                        if GAME_WARRIOR.hp > 0:
                            print(wrap("Blood slowly drips down your body as the rushing water continues to pick up speed" \
                            "'At least the worst is over now' you think to yourself as you body goes numb." \
                            " You can see the river banks shrinking."))

                            space()
                            print(wrap("The mountain river begins to bubble and churn, and before you know it you are surrounded by white waters."
                            " keeping afloat is almost imposible as the water continously drags you under, and then"
                            " you hear it a distant roaring growing ever louder"))

                            continue_text()
                            clear_screen()

                            space()
                            print(wrap("You realise what your are hearing. It's the sound of a waterfall"
                            " panic grips you. You try to swim against the current, but you are weakened from"
                            " prolonged exposure to cold waters and the numerous cuts you sustained amongst"
                            " the jagged rocks. "))

                            space()
                            survival_roll = random.randint(1,20)
                            if survival_roll >= 15:
                                print(wrap(
                                    "You dig deep and muster every ounce of strength you have left. "
                                    "If you can't make it to shore, you will die."
                                ))

                                space()
                                print(wrap(
                                    "With your the last of your reolve, fueled by pure adrenaline, you find your footing, "
                                    "and painstakingly fight the raging river toward the shoreline."
                                ))

                                continue_text()
                                space()
                                print(wrap(
                                    "As you struggle across the raging water you spot a figure racing along the shoreline. "
                                    "To your relief, it's Bo. The bank is only a few feet away now. "
                                    "You can see the edge of the waterfall, a few hundred more feet and you would have gone over its edge. "
                                    "That terrifying thought distracks you, and you lose your footing as the current overwhelms you again."
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
                                print(wrap(f"I think you have a pretty decent chance to win the monster " 
                                "tournament adventurer, but not in your current state. " 
                                "Bo begins to chant and your wounds fully heal. He also hands you a super_potion. " 
                                "These are kinda rare especially for new adventures to come upon. Use it wisely."))
                                GAME_WARRIOR.max_hp +=1
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
                                print(f"🏷️ Title Earned: River Warrior")
                                print(f"✨ +1 Permanent Max HP! (now {GAME_WARRIOR.max_hp})")
                                print("🏅 New Ability Learned: Death Defier! (0 AP to activate)")
                                continue_text()

                                space()       

                                
                                GAME_WARRIOR.name = get_name_input()

                                
                            
                            else:
                                    
                                print(wrap("You struggle to no avail. You can see the edge of the waterfall directly ahead."
                                " Your final strengh fails, and you are dragged under the water, your back grazinng"
                                " the now smooth bottom of the river your are thrown off the water fall and for a few seconts"
                                " you take in the beautiful surroudings."))

                                space() 
                                print(wrap("The sun is just starting to rise and you can make out snow covered mountains" \
                                " covered in pine trees. You see the town of Winter Haven on the distant marble covered cliffs smoke" \
                                " rising from its chimineys, and then your free fall ends. Sharp pain pounds your body as you" \
                                " land hard in the icy water below the waterfall"))
                            
                                space()
                                waterfall_damage = 30
                                GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - waterfall_damage)
                                print(wrap(f"You take {waterfall_damage} from the fall. You have {GAME_WARRIOR.hp} Hp remaining"))
                            if GAME_WARRIOR.hp <= 0:
                                print(wrap("The impact kills you"))
                                continue_text()
                                GAME_WARRIOR.titles.add("Drowned One")
                                GAME_WARRIOR.endings.add("Broken_one")
                                GAME_WARRIOR.show_all_game_stats()

                                input("\nPress enter to end the game.")
                                sys.exit(0)

                                
                                               


            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return



if __name__ == "__main__":
    GAME_WARRIOR = Warrior()
    intro_story(GAME_WARRIOR)
    

'''✅ Dungeon Adventure – Version History Summary

(based on everything we’ve built together in the past )
¤ we switched to executable. Game now has become Journey To Winter Haven
⚙️Version Journey To Winter Haven version v0.3 
* Took combat from 4 to 5 rounds
* added a rest period for full heal and future plot points and game mechanics in between 4th and 5th rounds of combat
* Fixed burn move for fire slime
* expanded berserk to two turn and an addition turn if a creature is killed while in berserk
* adjusted player overheal bar so it dosnt turn completly red when overhealed
* currently the only move that interfears with beserk is paralize
* fixed some other minor bugs
* added a breif scene where player is awarded with stat point and skill point by arena trainer before tournament begins
* added flags to arena entry points to allow for unique chats with arena trainer
* added skill points
* added player lvl 1 moves that are unlocked by trainer
* added a rank system evry move goes to 5 currently and takes increased skill point to level it up
* power strike rank system is functinal
* stat points spend on ap increase max ap by 1 and also allow for player to recover 1 additonal ap
* combined stats and skill points into a new menu
* game now check if stat/skill points are available and if not asks player if they are ready to continue
* fixed beserk and burn again
* added cast down feature if ranked ap cost is more than player currently has
* added special move heal
* expanded debug menu to include all current and eventually futire moves
* added special move war cry to players skills
* set up the ground work for a future system where beserk damage and adrenaline damage can be expanded
* fixed power strike. It was op using beserk to bump its damage way to high
* fixed combat log so everything is clearly defined
* wraped combat breakdownbecause it got to long 

⚙️Version Journey To Winter Haven version v0.2 
* we incorperated the tier combat system with weightsa to restrick fights so hopefull player isnt overwhelemed
*player now fights through 4 rounds of combat to win
*victory is now tied to beating fallen not essences.
*fixed mistyping ended game early.
* Completed tier 2 monster line up and ther moves (dire wolf pup, javelina, goblin archer, noob ghost)

⚙️Version journey to winter haven v0.1 did some minor ui fixes

⚙️Version .14 added new titles and endings
    * Hopefully corrected river path
    * fixed some possible future bugs
    * finished all curent tier 1 monster moves(imp, wolf_pup, brittle_skelton, green slime,young goblin)
    * added debug levle up menu
    * added wolf pup rider special move blind charge
    * added javalina and goblin archer and there moves
    * added a check so turn takers dont trigger twice in a row.
    * arena now will intervene if move stoper are triggered twice in a row

⚙️ Version .13 building special moves for monsters
    * added and stabalised blind
    * added new player move dealth defier
    * Updated potion system and added new types
    * added over heal
    * turned ap into a refreshable resourse
    * finally stabilised burn dot
    * added debug menu that could be easily expanded
    * added monster universal select m during combat or monster in story
    * Extended search for torch story mode


version.12 added rest mechanice inbetween rounds of combat
    * fine tuned rage mechanic
    * created beserk mode for rage mechanic
    * tried to clear every bug
    * made story text look better
    * created rest mechanic
    

⚙️ Version .111 

Major Features Added

Rage System (complete)

HP-based rage tiers at 75%, 50%, 25%, 10%

Tier-based extra damage

Level-up stat “Rage” permanently increases rage bonus

Rage flavor messages added, triggered only once per tier

Attack roll updated to exclude permanent rage (now applied through get_rage_bonus)

Developer Shortcuts (global)

q — restart entire game from anywhere

c or combat — jump straight to arena

Implemented via RestartException, QuickCombatException, and global GAME_WARRIOR

Defense System Rewrite (finalized)

Full block flavor text

Partial block flavor text

Defense-break system for Fallen Warrior using defence_break=True

Global Fixes

GAME_WARRIOR global reference created

Removed need to pass warrior through every check()

Fixed many incorrect warrior references

Fixed Fallen Warrior attack override

Added emoji-enhanced stat screen

Textwrap unified with new safe wrap() function

Fixed multiple crash bugs from missing args in check() and intro_story_inner

🛡️ Version .10 — Defense System Overhaul

Defense now actually reduces damage

apply_defence() system created

Added full block / partial block mechanics

Introduced flavor text system for blocks

Fixed bug where defense could go negative

Added Fallen Hero/Fallen Warrior defense-breaking attack

Fixed original_defence restoration after battle

⚔️ Version .09 — Combat Stability Pass

Fixed double damage print bug

Fixed NoneType attacker in defensive messages

Fixed incorrect alternating turn logic

Fixed runaway bloodlust stacking bug

Adjusted monster weights so Fallen Hero appears less often

Cleaned up battle loop structure

Improved story text formatting

Fixed level-up not triggering in older builds

Added strict alternation between warrior/enemy turns

📘 Version .08 — Story System Improvements

Most story segments wrapped with textwrap.fill()

Reformatted intro story spacing and structure

Unified input check() system

Cleaned up several deep nested if-blocks

Added new story branches (Forest Path, Bo encounter)

Added potion reward for bravery

Added persuasion check mechanic

Gameplay flow from story → arena stabilized

💀 Version .07 — Fallen Hero Path sorta more like brainstormed about it

Added consequences: stat point or gold

Added Fallen Hero’s defense-break special

Added essences to victory conditions

Tournament victory requires 3 essences

🧪 Version .06 — Monster & Essence System

Monster essence system created

Inventory for loot items

Wolf Rider now drops pelt + dual essence

Unified monster class with proper XP/gold/essence fields

Random encounter system weighted via random.choices

🧱 Version .05 — Leveling System

Added XP thresholds

xp_to_lvl scales ×1.75

Level-up bonus menu

Added AP, Defense, HP, ATK upgrades

Added achievements and titles

Added full stat display (show_all_game_stats)

⚗️ Version .04 — Potion System Rework

Added healing, AP, and mana potions

Simplified potion selection menu

Added inventory management

Added potion reward in story branches

👊 Version .03 — Combat Improvements

Refactored base classes (Creator, Monster, Hero)

Standardized attack rolls

Created battle() and battle_inner() separation

Added run-away consequences and death messages

Fixed duplicated damage printing in several places

📜 Version .02 — Story Prototype

First draft of intro story

Cave encounter

Beastman introduction

Forked paths (run/submit/escape)

Basic arena structure established

🌱 Version .01 — Original Build

Warrior class created

Basic monster classes

Barebones attack loop

Basic HP, XP, gold, inventory

Text only, no story branching'''

