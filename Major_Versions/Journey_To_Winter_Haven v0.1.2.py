import textwrap
import os
import random
import time
import math
import sys


# === Color Constants for HP Bar ===
WHITE = "\033[97m"
RED   = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

# ============================================================
#  UNIVERSAL INPUT OVERRIDE  (enables M anywhere in the game)
# ============================================================

_real_input = input

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
        # 🚨 THIS IS THE FIX
        if cleaned == "":
            print("Please enter a choice.")
            continue

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
    Builds a single HP bar where overheal overlaps the right side in RED.
    Normal HP = white
    Overheal = red (overwrites from the right)
    Empty = gray
    """

    if max_overheal is None:
        max_overheal = maximum

    # ----- NORMAL HP -----
    normal_hp = min(current, maximum)
    normal_slots = int((normal_hp / maximum) * size)

    # ----- OVERHEAL -----
    overheal_hp = max(0, current - maximum)
    overheal_capacity = max_overheal - maximum

    if overheal_capacity > 0:
        overheal_slots = int((overheal_hp / overheal_capacity) * size)
    else:
        overheal_slots = 0

    # ----- Start with empty bar -----
    bar = ["░"] * size

    # ----- Fill normal HP (left) -----
    for i in range(normal_slots):
        bar[i] = WHITE + "█" + RESET

    # ----- Overlap overheal (right) -----
    for i in range(overheal_slots):
        idx = size - 1 - i
        bar[idx] = RED + "█" + RESET

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
            hero.ap = hero.max_ap
            hero.stat_points -= 1
            print("AP increased!")

        elif choice == "5":
            print("You finish allocating stat points.")
            break

        else:
            print("Invalid choice.")
            clear_screen()

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
    if hero.max_ap > 3:  # Means they invested stat points into AP
        hero.ap = hero.max_ap
        print(f"🔵 Your AP fully restores to {hero.ap}/{hero.max_ap}.")
    else:
        old_ap = hero.ap
        hero.ap = min(hero.max_ap, hero.ap + 1)
        print(f"🔵 You recover {hero.ap - old_ap} AP from resting.")
        print(f"Current AP: {hero.ap}/{hero.max_ap}")
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
        print("What would you like to do before the next fight?")
        print("1) Use a potion")

        if hero.stat_points > 0:
            print(f"(You have {hero.stat_points} unspent stat point(s))")
            print("2) Spend level-up (spend stat points)")
            print("3) Review equipment (future)")
            print("4) Continue to next opponent")

            raw = input("\nChoose: ")

            # --- DEV ONLY: monster select during rest ---
            if isinstance(raw, tuple) and raw[0] == "monster_select":
                monster = raw[1]
                if monster:
                    return battle(hero, monster)
                continue

            choice = raw.strip()

            if choice == "1":
                use_potion_menu(hero)
                clear_screen()

            elif choice == "2":
                level_up_menu(hero)
                clear_screen()

            elif choice == "3":
                print("\n🛡️ Equipment system coming soon!")
                space()
                clear_screen()

            elif choice == "4":
                print("You steel yourself for the next battle...")
                space()
                break

            else:
                print("Invalid choice.\n")

        else:
            print("2) Review equipment (future)")
            print("3) Continue to next opponent")

            raw = input("\nChoose: ")

            # --- DEV ONLY: monster select during rest ---
            if isinstance(raw, tuple) and raw[0] == "monster_select":
                monster = raw[1]
                if monster:
                    return battle(hero, monster)
                continue  

            choice = raw.strip()

            if choice == "1":
                use_potion_menu(hero)
                clear_screen()

            elif choice == "2":
                print("\n🛡️ Equipment system coming soon!")
                space()
                clear_screen()

            elif choice == "3":
                print("You steel yourself for the next battle...")
                space()
                break

            else:
                print("Invalid choice.\n")



def debug_menu(warrior, enemy=None):
    clear_screen()
    print("===== DEBUG MENU =====")
    print("1) Force Berserk")
    print("2) Apply Blindness")
    print("3) Apply Burn (1 stacks)")
    print("4) Apply Poison (2 dmg)")
    print("5) Heal to Full")
    print("6) Activate Dealth Defier")
    print("7) Trigger death defier")
    print("8) Level Up")
    print("9) Exit Current Run")
    print("10) Exit Debug Menu")

    print("======================")

    choice = _real_input("> ").strip()

    if choice == "":
        print("Please enter a choice.")

    if choice == "1":
        warrior.hp = max(1, int(warrior.max_hp * 0.05))
        warrior.blind_turns = 0
        warrior.blind_long = False
        warrior.berserk_pending = True
        print("⚡ Debug: Forced Berserk conditions applied.")

    elif choice == "2":
        warrior.blind_turns = 3
        warrior.blind_long = True
        warrior.berserk_pending = False
        print("👁️‍🗨️ Debug: Applied Blindness.")

    elif choice == "3":
        warrior.fire_stacks = 1
        warrior.fire_turns = 2
        warrior.fire_skip_first_tick = True
        print("🔥 Debug: Applied 1 burn stacks.")

    elif choice == "4":
        warrior.poison_active = True
        warrior.poison_amount = 1
        warrior.poison_skip_first_tick = False
        print("☠️ Debug: Applied poison (2 dmg per turn).")

    elif choice == "5":
        warrior.hp = warrior.max_hp
        print("❤️ Debug: Healed warrior to full.")

    elif choice == "6":
        warrior.death_defier = True
        warrior.death_defier_river = True   # give free version
        warrior.death_defier_active = False
        warrior.death_defier_used = False
        print("💀 Debug: Death Defier granted & activated!")


    elif choice=="7":
        warrior.hp = 1
        print("Debug: HP set to 1. Ready for instant Death Defier test.")

    elif choice == "8":
        if warrior.level >= 5:
            print("⚙️ Debug: Level cap reached (Level 5).")
        else:
            warrior.level += 1

            # Grant stat points only
            warrior.stat_points += 2

            # Optional convenience: heal without changing max HP
            warrior.hp = warrior.max_hp
            warrior.ap = warrior.max_ap

            print(f"⚙️ Debug: Warrior leveled up to {warrior.level}")
            print(f"Stat Points available: {warrior.stat_points}")
            print(f"HP: {warrior.hp}/{warrior.max_hp} | AP: {warrior.ap}/{warrior.max_ap}")

            spend = _real_input("Spend stat points now? (y/n): ").strip().lower()
            if spend == "y":
                level_up_menu(warrior) 

    elif choice == "9":
        print("Exiting current run...")
        sys.exit(0)
        

    elif choice == "10":
        print("Exiting debug menu...")
        return

    else:
        print("Invalid input.")

    input("\nPress Enter to return to battle...")

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
              }

    if choice in monster_map:
        monster = monster_map[choice]()
        print(f"⚔️ You selected: {monster.name}")

        # --- Start the debug battle immediately ---
        result = battle(GAME_WARRIOR, monster)

        # --- Check if player died ---
        if not result or not GAME_WARRIOR.is_alive():
            print("\n💀 You were defeated in the debug battle!")
            # Optionally, reset health for testing
            GAME_WARRIOR.hp = GAME_WARRIOR.max_hp
            print(f"💖 HP restored to {GAME_WARRIOR.hp} for continued testing.")
            return None  # back to the menu

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
    hero.hp -= fire_damage
    hero.hp = max(0, hero.hp)

    print(f"🔥 Burning slime scorches your skin for {fire_damage} fire damage!")

    # --------------------------------
    # 3) APPLY BURN STACK (DoT)
    # --------------------------------
    if not hasattr(hero, "fire_turns"):
        hero.fire_stacks = 0
        hero.fire_turns = 0

    # Max 2 stacks
    hero.fire_stacks = min(hero.fire_stacks + 1, 2)

    if hero.fire_turns <= 0:
        hero.fire_turns = 2
        hero.fire_skip_first_tick = True


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

def blinding_charge(self, hero):
    if self.ap <= 0:
        return None
    if random.random() > 0.5:
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



# =============================
# HERO MOVES
# =============================

def activate_death_defier():
    """
    Uses the hero's turn to activate Death Defier.
    Costs 0 AP if unlocked from the river.
    Costs 1 AP if unlocked later by level.
    Does no damage, just sets the passive.
    """

    # Already primed or spent?
    if GAME_WARRIOR.death_defier_used:
        print("You've already used Death Defier this tournament.")
        return False

    if GAME_WARRIOR.death_defier_active:
        print("Death Defier is already active.")
        return False

    if not GAME_WARRIOR.death_defier:
        print("You don't have that ability.")
        return False

    # Cost based on how it was unlocked
    cost = 0 if GAME_WARRIOR.death_defier_river else 1

    if GAME_WARRIOR.ap < cost:
        print("You don't have enough AP.")
        return False

    GAME_WARRIOR.ap -= cost
    GAME_WARRIOR.death_defier_active = True

    print()
    print(wrap(
        "You close your eyes and chant, grounding your body and spirit to the land of the living." \
        " You will not so easily succumb to death now."
        
    ))
    print(f"(Death Defier is now active. AP remaining: {GAME_WARRIOR.ap})")
    return True



    



# ===============================
# Base Classes
# ===============================
# we are creating a better way to incorperate dev shortcuts
class RestartException(Exception):
    pass

class QuickCombatException(Exception):
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

        # NEW: pool of points to spend in rest_phase()
        self.stat_points = 0

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

        # Turn stopers
        self.turn_stop = 0
        self.turn_stop_reason = ""
        self.turn_stop_chain_guard = False
        

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
        print(f"💥 Bonus: {self.current_bonus_damage}")
        print(f"Berserk: {berserk_meter(self)}")

        print("=" * 40)
        print()







        
    def show_all_game_stats(self):
        print("\n" + "=" * 40)
        print(f"Hero: {self.name}   |   Level: {self.level}")
        print(f"HP: {self.hp}/{self.max_hp}  |  ATK: {self.min_atk}-{self.max_atk}")
        print(f"AP: {self.ap}/{self.max_ap}  |  DEF: {self.defence}")
        print(f"XP: {self.xp}/{self.xp_to_lvl}")
        print(f"Gold: {self.gold}")
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
            gained = 2
            self.stat_points += gained

            print(f"\n[LEVEL UP] {self.name} reached level {self.level}!")
            print(f"You gained {gained} stat points to spend during your next rest.")

            # 🔥 NEW: Full heal on level-up
            old_hp = self.hp
            self.hp = self.max_hp
            self.max_overheal = int(self.max_hp * 1.10)
            self.hp = min(self.hp, self.max_overheal)

            print(f"❤️ You feel completely rejuvenated! "
                f"HP restored from {old_hp} to {self.hp}.")
            
            choice = input("\nSpend stat points now? (y/n): ").strip().lower()
            if choice == "y":
                
                level_up_menu(self)
            else:
                print("You can spend them later from your status menu.")

       

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

        # If blinded → delay until vision clears
        if warrior.blind_turns > 0 or warrior.blind_long:
            print("💤 Your rage builds… but blindness delays Berserk!")
            warrior.berserk_pending = True
            return

        # Otherwise activate immediately
        print("🩸🔥 BERSERK MODE ACTIVATED!")
        warrior.berserk_active = True
        warrior.berserk_bonus = 6 + warrior.max_rage
        warrior.berserk_turns = 2      # <-- lasts a FULL ROUND
        warrior.berserk_used = True










# ===============================
# Monsters
# ===============================
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
            hp=33,
            min_atk=5,
            max_atk=9,
            gold=0,
            xp=25,
            essence=["fallen warrior essence"],
            defence=2
        )
        self.ap = 3

    def attack(self, target):
        if self.ap > 0 and random.randint(1, 3) == 1:
            print(f"💀 {self.name} remembers a special defence breaking technique, and strikes at {target.name} defences!")
            damage = random.randint(self.min_atk + 3, self.max_atk + 6)
            self.ap -= 1

            actual = target.apply_defence(damage, attacker=self, defence_break=True)
            
            return actual
            
        else:
            damage = random.randint(self.min_atk, self.max_atk)

            actual = target.apply_defence(damage, attacker=self)
            
            # attack message is printed father down
            return actual


            
        

class Ghost(Monster):
    def __init__(self):
        super().__init__(
            name="noob ghost",
            hp=16,
            min_atk=3,
            max_atk=6,
            gold=0,
            xp=10,
            essence=["ghost essence"],
            defence=0,
            ap=2
        )
        

class Wolf_Pup_Rider(Monster):
    def __init__(self):
        super().__init__(name= "wolf pup rider",
                         hp=21,
                         min_atk=3,
                         max_atk=7,
                         gold=0,
                         xp=21,
                         essence=["young goblin essence", "wolf pup essence"],
                         defence=2,
                         ap = 2
                         )
        self.loot_drop = "wolf_pup_rider"
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
        self.berserk_bonus = 0   # default Berserk damage

                # ---------- Warrior-Specific: Death Defier ----------
        self.death_defier = False            # ability unlocked at all?
        self.death_defier_river = False      # river version? (0 AP)
        self.death_defier_active = False     # currently primed
        self.death_defier_used = False       # already triggered this tournament?


        # ---------- Warrior-Specific: Leveling ----------
        self.stat_points = 0
        self.death_reason = None

        # ---------- Warrior-Specific: Damage-over-Time ----------
        self.fire_stacks = 0
        self.fire_turns = 0
        self.fire_skip_first_tick = False

        self.poison_active = False
        self.poison_turns = 0
        self.poison_amount = 0
        self.poison_skip_first_tick = False






# ===============================
# Encounter Helpers
# ===============================

# Main monster list used for both arena + debug
# Weight determines tier (3=T1, 2=T2, 1=T3, <1=T4)
MONSTER_TYPES = [
    (Green_Slime, 3),
    (Young_Goblin, 3),
    (Imp, 3),
    (Brittle_Skeleton, 3),
    (Wolf_Pup, 3),
    (Red_Slime, 2),
    (Fallen_Warrior, 1.0),
    (Ghost, 2),
    (Wolf_Pup_Rider, 1),
    (Javelina, 2),
    (Goblin_Archer, 2),
]


# ---------- Tier helpers ----------
def weight_to_tier(weight):
    if weight >= 3:
        return 1
    elif weight >= 2:
        return 2
    elif weight >= 1:
        return 3
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
    (Fallen_Warrior, 1.0),
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
        return pick_tier_from_weights({1: 0.1, 2: 0.8, 3: 0.1})
    if round_num == 3:
        return pick_tier_from_weights({2: 0.1, 3: 0.9})
    if round_num == 4:
        return 4  # Fallen boss only
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
        return actual

    # -------------------------------------------------------------
    # 3. GENERIC SPECIAL MOVE (Fallen Warrior, etc.)
    # -------------------------------------------------------------
    special = getattr(enemy, "special_move", None)
    if enemy.ap > 0 and callable(special):
        result = special(enemy, warrior)
        if result is not None:
            # Specials handle their own printing and HP changes
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

    print(f"{enemy.name} attacks you for {actual} damage! (rolled {damage})")
    show_health(warrior)
    # --- Death Defier (monster damage)
    if warrior.hp <= 0:
        if warrior.death_defier_active and not warrior.death_defier_used:
            warrior.hp = 1
            warrior.death_defier_used = True
            warrior.death_defier_active = False
            print()
            print("💀✨ DEATH DEFIER! You refuse to die and cling to life!")
            print(f"❤️ Your HP is now {warrior.hp}/{warrior.max_hp}")

            return 0  # tell caller the attack was "handled" without death

    return actual



def player_basic_attack(warrior, enemy):
    # -----------------------------------------
    # 1. Roll base attack + adrenaline bonus
    # -----------------------------------------
    bonus = compute_adrenaline_bonus(warrior)
    warrior.current_bonus_damage = bonus

    base_roll = warrior_attack_roll(warrior)
    
    # Store original (before blind + berserk)
    base_damage = base_roll + bonus
    berserk_bonus = 0

    # -----------------------------------------
    # 2. Berserk activation
    # -----------------------------------------
    if warrior.berserk_pending and warrior.blind_turns == 0 and not warrior.blind_long:
        print(f"🔥 Your vision clears — your rage explodes unleashing devastating damage upon {enemy.name}!")
        warrior.berserk_pending = False
        warrior.berserk_active = True
        warrior.berserk_turns = 2
        warrior.berserk_used = True

    # -----------------------------------------
    # 3. Blindness effects (3 stage recovery)
    # -----------------------------------------

    # blind multiplier is the number we are going to multiply to determine stages of blind
    blind_multiplier = 1.0

    if warrior.blind_turns == 3:
        print("😵 Fully blinded! You swing wildly!")
        base_damage = 0
        return 0
    elif warrior.blind_turns == 2:
        print("👁️‍🗨️ Your vision is blurred — base damage halved.")
        blind_multiplier = 0.5
        

    elif warrior.blind_turns == 1:
        print("👁 Your vision sharpens — base damage reduced slightly.")
        blind_multiplier = 0.75
        
    base_damage = max(0, int(base_damage * blind_multiplier))
    
    # -----------------------------------------
    # 4. Berserk bonus
    # -----------------------------------------
    if warrior.berserk_active:
        berserk_bonus = warrior.berserk_bonus
        print(f"🩸🔥 Berserk adds +{berserk_bonus} bonus damage!")


    # -----------------------------------------
    # 5. Final combined damage
    # -----------------------------------------
    final_damage = base_damage + berserk_bonus

    # -----------------------------------------
    # 6. Apply defence
    # -----------------------------------------
    actual = enemy.apply_defence(final_damage, attacker=warrior)

    enemy.hp = max(0, enemy.hp - actual)

    

    # NEW CLEAR DAMAGE MESSAGE
    blocked = final_damage - actual
    if blocked > 0:
        print(f"You attack {enemy.name} for {actual} damage! (rolled {final_damage}, blocked {blocked})")
    else:
        print(f"You attack {enemy.name} for {actual} damage! (rolled {final_damage})")

    print(f"❤️ {enemy.name.title()} HP: {enemy.hp}/{enemy.max_hp}")

    

    # BERSERK TURN TICK
    if warrior.berserk_active:
        warrior.berserk_turns -= 1
        if warrior.berserk_turns <= 0:
            warrior.berserk_active = False
            print("💤 Your Berserk fury subsides...")

    return actual


def battle(warrior, enemy):
    """
    Wrapper for the battle system.
    Catches developer shortcuts from anywhere inside the fight.
    """
    try:
        return battle_inner(warrior, enemy)
    except RestartException:
        clear_screen()
        print(wrap("🔄 Restarting game..."))
        return intro_story(GAME_WARRIOR)
    except QuickCombatException:
        clear_screen()
        print(wrap("⚔️ Quick Combat Mode Activated!"))
        return arena_battle(GAME_WARRIOR)


def battle_inner(warrior, enemy):

    print(f"\n{warrior.name} enters the arena!")
    print(f"You face a {enemy.name}!")

    # Decide who starts
    warrior_turn = random.choice([True, False])

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

        # After their opening strike, it becomes the warrior's turn
        warrior_turn = True


    # ==============================
    # MAIN COMBAT LOOP
    # ==============================
    while warrior.is_alive() and enemy.is_alive():
        # Reset per-turn Dealth Defier flag
        warrior.death_defier_triggered = False

        # ---------------------------------------
        # PLAYER TURN
        # ---------------------------------------
        if warrior_turn:
            # ---------------------------------------
            # TURN STOP (stun/freeze/paralyze/etc.)
            # Anti-chain rule: cannot lose action twice in a row
            # ---------------------------------------
            if resolve_player_turn_stop(warrior):
                print(f"🧊⚡ Your muscles lock up — you're {warrior.turn_stop_reason.upper()} and lose your action!")
                warrior_turn = False
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
                    warrior.poison_turns -= 1
                    warrior.poison_turns = max(0, warrior.poison_turns)

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
            if getattr(warrior, "fire_stacks", 0) > 0 and getattr(warrior, "fire_turns", 0) > 0:

                # Skip first burn tick
                if getattr(warrior, "fire_skip_first_tick", False):
                    warrior.fire_skip_first_tick = False
                else:
                    print("🔥 The lingering burn continues to heat your skin…")

                    fire_damage = 0

                    # Burn per stack
                    for i in range(warrior.fire_stacks):
                        tick = random.randint(1, 3)
                        fire_damage += tick
                        print(f"🔥 Burn stack {i+1} scorches you lightly for {tick} fire damage.")

                    warrior.hp = max(0, warrior.hp - fire_damage)
                    show_health(warrior)

                    print(f"🔥 Total burn damage: {fire_damage}")

                    # Track stacks before expiration (for messaging)
                    expired_stacks = warrior.fire_stacks

                    # 🔥 decrement duration
                    warrior.fire_turns -= 1

                    # 🔥 burn expires cleanly
                    if warrior.fire_turns <= 0:
                        warrior.fire_stacks = 0
                        print(
                            f"💨 The flames finally die out "
                            f"({expired_stacks} burn stack{'s' if expired_stacks > 1 else ''} fade)."
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
            # DOT Death Check
            # ==========================

            # ==========================
            # DOT Death Defier (DOT save)
            # ==========================

            # --- after applying poison/fire damage ---

            # Death Defier intercept
            # Death Defier intercept (after poison/fire)
            if warrior.hp <= 0:
                if warrior.death_defier_active and not getattr(warrior, "death_defier_triggered", False):
                    warrior.hp = 1
                    warrior.death_defier_triggered = True
                    # Optionally do not set death_defier_active to False here if you want multi-turn passive
                    print()
                    print("💀✨ DEATH DEFIER! You refuse to die and cling to life!")
                    print(f"❤️ Your HP is now {warrior.hp}/{warrior.max_hp}")

                    # Continue to allow remaining DOTs to process safely


                    continue

            # If still dead normally
            if not warrior.is_alive():
                print("\nYou succumb to your wounds...")
                
                return False


            # ==========================
            # 4) RESOLVE PENDING BERSERK
            # ==========================
            if getattr(warrior, "berserk_pending", False) and warrior.blind_turns == 0 and not warrior.blind_long:
                print("🔥 Your vision clears — your Berserk erupts!")
                warrior.berserk_pending = False
                warrior.berserk_active = True

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
                "2) Special (WIP)\n"
                "3) Use Potion\n"
                "4) Run Away\n"
                "(Type 1-4)",
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
            if cleaned not in ("1", "2", "3", "4"):
                print("Invalid choice, try again.")
                continue

            choice = cleaned


            # ==========================
            # 9) PLAYER ACTIONS
            # ==========================
            if choice == "4":
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

            elif choice == "2":
                # SPECIAL MOVES MENU
                while True:
                    print("\nSpecial Moves:")

                    # DEATH DEFIER
                    if warrior.death_defier and not warrior.death_defier_active and not warrior.death_defier_used:
                        cost = 0 if warrior.death_defier_river else 1
                        print(f"1) Death Defier (Cost {cost} AP)")

                    print("0) Back")

                    sub = input("> ").strip()

                    # Back to main combat options
                    if sub == "0":
                        break

                    # Death Defier
                    elif sub == "1" and warrior.death_defier:
                        used = activate_death_defier()
                        if used:
                            warrior_turn = False
                            break  # end turn, go to monster

                    else:
                        print("Invalid option.")
                        continue

                continue  # back to main combat loop


            elif choice == "3":
                use_potion_menu(warrior)
                warrior_turn = False
                continue

            # ==========================
            #  BLINDNESS TICK DOWN
            # ==========================
            if warrior.blind_turns > 0:
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

                if len(warrior.monster_essence) >= 4:
                    print("\n✨ You have collected four essences!")
                    GAME_WARRIOR.titles.add("Champion of the Arena")
                    GAME_WARRIOR.endings.add("champion_ending")
                    warrior.show_game_stats()
                    return "win"

                input("Press Enter to continue.")
                warrior.level_up()
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

            if not warrior.is_alive():
                print("\nYou collapse as the arena roars...")
                return False

            # Berserk fade on ENEMY turn
            if warrior.berserk_active:
                warrior.berserk_turns -= 1
                if warrior.berserk_turns <= 0:
                    warrior.berserk_active = False
                    print(wrap("🩸🔥 Your berserk fury subsides."))

        # Alternate turns
        warrior_turn = not warrior_turn





def arena_battle(warrior, rounds_to_win=4):
    """
    Tournament:
    - Fight `rounds_to_win` random monsters in a row.
    - Lose or run once → run ends.
    """

    champion = False  # <-- Tracks if final victory was achieved

    print(textwrap.fill(
        "You are pushed out onto the arena floor. Magical torches flare to life around the ring. "
        "The stands are packed with monsters of every shape and size, all howling for blood.",
        WIDTH
    ))

    defeated_names = []

    for round_num in range(1, rounds_to_win + 1):
        print(f"\n--- Round {round_num} ---")
        enemy = select_arena_enemy(round_num)
        result = battle(warrior, enemy)

        if result == "win":
            champion = True
            break
            
        if result == "tournament":
            return
       


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
        

        defeated_names.append(enemy.name)

    print("\n🏆 You are victorious in the arena!")
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
        continue_text()
        clear_screen()

        print(textwrap.fill(
            "Your foot catches on the stump and you tumble forward. Your torch flies from your "
            "hand and lands in the mouth of a nearby cave.",
            WIDTH
        ))
        print(textwrap.fill(
            "A deep, angry voice echoes from within, \"Who goes there?\"",
            WIDTH
        ))

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
                    "against three different monsters of varying strength. "
                    "Defeat all three in single combat, then fight the champion and you win your freedom.\"",
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

                tournament_inquiry = check(
                    "\nDo you inquire further? (yes/no)\n> ",
                    ["yes", "no"]
                )

                
                if tournament_inquiry == "yes":
                    print("\n\"Roll a persuasion check,\" the beastman grins.")
                    persuasion_roll = random.randint(1, 20)
                    print(f"You roll a {persuasion_roll}.")

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
                    "You are thrown into a damp cell. After a rough night of sleep, "
                    "you awaken to a cold, pitiful breakfast.",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    "You can understand some of the monsters speaking outside. Most of them "
                    "are placing bets on your chances of survival. The odds are overwhelmingly "
                    "stacked against you.",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    f"You do overhear the beastman who captured you placing a bet in your favor, {warrior.name}.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "Night falls. The cage door creaks open. You are led toward the roaring sound "
                    "of a crowd.",
                    WIDTH
                ))

                space()
                print(textwrap.fill(
                    "You step into the arena. Let the tournament begin!",
                    WIDTH
                ))
                continue_text()
                clear_screen()
                arena_battle(GAME_WARRIOR)
                return

            # tournament_knowledge == "no"
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
                            "\"The tournament pits you against three monsters in solo combat. "
                            "If you defeat all three you fight the champion, beat him and you win. Each monster you defeat rewards you "
                            "with a monster essence. Turn in the essences, and you are set free.\"",
                            WIDTH
                        ))

                        bo_questions = check(
                            textwrap.fill(
                                "Bo asks if you have any questions.\n"
                                "Type '(1' to ask about essences,\n"
                                "or '(2' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["1", "2"]
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
                        

                    print()
                    print(textwrap.fill(
                        "Soon after, you are shackled and escorted to a fortified arena. "
                        "The crowd's distant roar vibrates through the stone beneath your feet.",
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
                            return  # exits the current story function safely

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
                            if survival_roll >= 16:
                                print(wrap(
                                    "You dig deep and muster every ounce of strength you have left. "
                                    "If you can't make it to shore, you will die."
                                ))

                                space()
                                print(wrap(
                                    "With your the last of your reolve, fueled by pure adrenaline, you find your footing, "
                                    "and painstakingly fight the raging river toward the shoreline."
                                ))

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


                                space()
                                print(wrap(
                                    "'You have to be the most stubborn human I've ever met. Consider me impressed, adventurer. "
                                    "You're a survivor. You'll make an excellent addition to our tournament.'"
                                ))

                                space()
                                print(wrap(f"I think you have a pretty decent chance to win the monster" 
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
                                return
                       


            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return



if __name__ == "__main__":
    GAME_WARRIOR = Warrior()
    intro_story(GAME_WARRIOR)

'''✅ Dungeon Adventure – Version History Summary

(based on everything we’ve built together in the past )

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

