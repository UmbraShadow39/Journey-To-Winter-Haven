import random
import textwrap
import os
import time

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
    """Pause until player presses Enter."""
    input("Press enter to continue")


def check(prompt, options=None):
    global GAME_WARRIOR
    """
    Input checker with automatic developer shortcuts:
    - q → restart game
    - c / combat → jump straight into the arena
    """
    while True:
        choice = input(prompt).lower().strip()

        # Restart game
        if choice == "q":
            raise RestartException

        # Quick Combat
        if choice in ("c", "combat"):
            if GAME_WARRIOR is None:
                
                print(wrap("⚔️ Cannot start combat yet — no warrior exists."))
                continue
            raise QuickCombatException

        # Normal validation
        if options is None or choice in options:
            return choice

        print("Invalid choice, try again.")

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
def use_potion_menu(hero):
    clear_screen()
    print("🧪 Potion Bag\n")

    # Count all potions
    total_potions = sum(hero.potions.values())
    if total_potions == 0:
        print("You have no potions left!")
        space()
        return

    # Build dynamic menu
    potion_types = list(hero.potions.keys())
    for i, potion in enumerate(potion_types, start=1):
        print(f"{i}) {potion.title()} x{hero.potions[potion]}")

    print(f"{len(potion_types) + 1}) Go back")

    # Choose potion
    choice = input("\nChoose: ").strip()

    # Exit
    if choice == str(len(potion_types) + 1):
        print("You close your potion bag.")
        space()
        return

    # Validate input
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(potion_types):
        print("Invalid choice.")
        space()
        return

    # Identify potion
    index = int(choice) - 1
    potion_type = potion_types[index]

    # Check potion count
    if hero.potions[potion_type] <= 0:
        print(f"You have no {potion_type} potions left!")
        space()
        return

    # Consume potion
    hero.potions[potion_type] -= 1

    # ---------- Potion Effects ----------
    if potion_type == "heal":
        heal = 10
        old_hp = hero.hp
        hero.hp = min(hero.max_hp, hero.hp + heal)

        print(f"\nYou drink a healing potion and recover {hero.hp - old_hp} HP!")
        print(f"Current HP: {hero.hp}/{hero.max_hp}")
        continue_text()
        space()

    elif potion_type == "ap":
        old_ap = hero.move_points
        hero.move_points += 1

        print(f"\nYou drink an AP potion and recover {hero.move_points - old_ap} AP!")
        print(f"Current AP: {hero.move_points}")
        continue_text()
        space()

    elif potion_type == "mana":
        print("\n🔮 You drink a mana potion...")
        print("✨ Mana restoration coming soon in the Wizard update!")
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
            hero.ap += 1
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
    hero.hp = min(hero.max_hp, hero.hp + round_heal)

    print(wrap(
        f"You are allowed a brief respite in between rounds. "
        f"You recover {round_heal} HP.\n"
        f"Your HP is now {hero.hp}/{hero.max_hp}."
    ))
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

        # Only show stat option if stat points exist
        if hero.stat_points > 0:
            print("2) Spend level-up stat points")
            print("3) Review equipment (future)")
            print("4) Continue to next opponent")
            choice = input("\nChoose: ").strip()

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
            # No stat points — hide stat option
            print("2) Review equipment (future)")
            print("3) Continue to next opponent")
            choice = input("\nChoose: ").strip()

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

def full_defensive_block(attacker, defender):
    messages = [
        f"{attacker.name} swings hard but a quick block by {defender.name} absorbs all the damage.",
        f"{attacker.name}'s attack is not enough and is blocked by {defender.name}.",
        f"{defender.name} pivots just in time to avoid the damage from {attacker.name}'s attack.",
        f"{defender.name} blocks the attack, and takes no damage from {attacker.name}.",
        f"{attacker.name} tries to sucker punch {defender.name}, but {defender.name} lunges backward, avoiding the blow.",
        f"{attacker.name} lands a glancing blow, but {defender.name}'s tough exterior absorbs the impact.",
        f"{attacker.name} lunges at {defender.name}, but {defender.name} backsteps avoiding damage.",
        f"{defender.name} parries {attacker.name}'s attack, taking no damage.",
        f"{attacker.name} is quick, but {defender.name} is quicker, narrowly avoiding damage.",
        f"{attacker.name} charges {defender.name}, but in an unexpected display {defender.name} backflips out of the way."
    ]
    return wrap(random.choice(messages))

def partial_defensive_block(attacker, defender, reduced_amount):
    defence_partial_successs = [f"{attacker.name} charges forward wildly, {defender.name} manages to block some of the damge, but {attacker.name} still lands blows.",
                                f"{defender.name} uses their body to block {attacker.name} impact is reduced but {defender.name} still takes some damage",
                                f"{defender.name} try to pivot away from {attacker.name} attack, but is only partially successful, taking some damage",
                                f"{attacker.name} swings hard {defender.name} try to block but is a little to slow. Damage is reduced but not avoided",
                                f"{defender.name} sidesteps out of the way but {attacker.name} still  manages to inflict some damage.",
                                f"{attacker.name} goes in for a tackle {defender.name} braces for impact, reducing some of the damage",
                                f"{defender.name} jumps backwards to avoid {attacker.name} attack, but is to slow to avoid all damage.",
    ]
    return wrap(random.choice(defence_partial_successs) + f" ({reduced_amount} damage blocked)") 


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
    
    def apply_defence(self, damage, attacker=None, defence_break=False):
        """Calculate actual damage after defence."""

        attacker_name = attacker.name if attacker else "The attacker"

    # ---------------------------------------------
    # 💥 Berserk damage reduction (take half damage)
    # ---------------------------------------------
        if hasattr(self, "berserk_active") and self.berserk_active:
            damage = max(1, damage // 2)

        reduced_defence = min(self.defence, damage)
        actual = max(0, damage - self.defence)

    # ---------------------------------------------
    # 🔥 Defence-break attacks bypass normal logic
    # ---------------------------------------------
        if defence_break:
            print(wrap(f"{attacker_name}'s brutal strike shatters your defenses!"))
            print(wrap(f"{self.name} is knocked backwards by the impact!"))

            self.defence = max(0, self.defence - reduced_defence)
            self.hp = max(0, self.hp - actual)
            return actual

    # ---------------------------------------------
    # 🛡️ Full block (no damage taken)
    # ---------------------------------------------
        if actual == 0:
            print(full_defensive_block(attacker, self))
            return 0

        # ---------------------------------------------
        # 🛡️ Partial block (some damage reduced)
        # ---------------------------------------------
        if reduced_defence > 0:
            print(partial_defensive_block(attacker, self, reduced_defence))

    # ---------------------------------------------
    # Normal hit
    # ---------------------------------------------
        self.hp = max(0, self.hp - actual)
        return actual



class Monster(Creator):
    def __init__(self, name, hp, min_atk, max_atk, gold, xp, essence, defence=0):
        super().__init__(name, hp, min_atk, max_atk, gold, xp, defence)
        self.essence = essence


class Hero(Creator):
    def __init__(self, name, hp, min_atk, max_atk,
                 gold=0, xp=0, defence=0, move_special="ep", move_points=0, potions=None):
        super().__init__(name, hp, min_atk, max_atk, gold, xp, defence)
        
        #points and moves
        self.move_special = move_special
        self.move_points = move_points

        # Equitment and inventory
        self.inventory =[]
        self.equipment =[]

        # Potions dictionary so it's easy to expand
        if potions is None:
            self.potions = {"heal": 0, "ap": 0, "mana": 0}
        else:
            self.potions = potions

        self.level = 1
        self.xp_to_lvl = 10
        self.titles = []
        self.achievements = []
        self.monster_essence = []

    # ---------- Display ----------
    def show_game_stats(self):
        print("\n" + "=" * 40)
        print(f"🧝 Hero: {self.name}    |   ⭐ Level: {self.level}")
        print(f"❤️ HP: {self.hp}/{self.max_hp}   |   ⚔️ ATK: {self.min_atk}-{self.max_atk}")
        print(f"💥 Bonus Damage (Rage + Adrenaline): {self.current_bonus_damage}")
        print(f"🔥 Rage State: {self.max_rage}")

        print(f"🔵 AP: {self.move_points}        |   🛡️ DEF: {self.defence}")
        print(f"📘 XP: {self.xp}/{self.xp_to_lvl}")  
        print(f"💰 Gold: {self.gold}") 

        if self.potions:
            print("Potions:")
            for potion_type, count in self.potions.items():
                print(f"  • {potion_type.title()} x{count}")
        print("=" * 40)

        
    def show_all_game_stats(self):
        print("\n" + "=" * 40)
        print(f"Hero: {self.name}   |   Level: {self.level}")
        print(f"HP: {self.hp}/{self.max_hp}  |  ATK: {self.min_atk}-{self.max_atk}")
        print(f"AP: {self.move_points}  |  DEF: {self.defence}")
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

        print("=" * 45 + "\n")
    # ---------- Leveling ----------
    def level_up(self):
        """
        Single-step level up.
        If XP >= threshold: level once, adjust XP, increase next threshold,
        then let the player allocate stat points.
        """
        if self.xp >= self.xp_to_lvl:
            self.level += 1
            self.xp -= self.xp_to_lvl
            self.xp_to_lvl = int(self.xp_to_lvl * 1.75)
            print(f"\n[LEVEL UP] {self.name} reached level {self.level}!")
            self.level_up_bonus()

    def level_up_bonus(self):
        """Spend 2 stat points on HP / ATK / AP / DEF / Rage."""
        stat_points = 2

        while stat_points > 0:
            print(f"\nYou have {stat_points} stat points remaining.")
            print("1) +5 HP   |   2) +1 ATK range   |   3) +1 AP   |   4) +1 Defense   |   5) +1 Rage")

            # Use the new dev-friendly check() function
            choice = check("> ", ["1", "2", "3", "4", "5"])

            if choice == "1":
                self.max_hp += 5
                self.hp = self.max_hp
                print(f"❤️ Max HP → {self.max_hp}")

            elif choice == "2":
                self.min_atk += 1
                self.max_atk += 1
                print(f"⚔️ ATK Range → {self.min_atk}-{self.max_atk}")

            elif choice == "3":
                self.move_points += 1
                print(f"🔵 AP → {self.move_points}")

            elif choice == "4":
                self.defence += 1
                print(f"🛡️ Defense → {self.defence}")

            elif choice == "5":
                self.max_rage += 1
                print(f"🔥 Rage → {self.max_rage}")

            stat_points -= 1

        print("\nAll stat points spent!\n")

def compute_adrenaline_bonus(warrior):
    """
    Returns bonus damage from adrenaline tiers, rage stat,
    and berserk mode. Fully corrected version.
    """

    hp_percent = warrior.hp / warrior.max_hp

    # -----------------------------
    # Determine adrenaline tier
    # -----------------------------
    if hp_percent <= 0.10:
        tier = 4   # Berserk
    elif hp_percent <= 0.25:
        tier = 3
    elif hp_percent <= 0.50:
        tier = 2
    elif hp_percent <= 0.75:
        tier = 1
    else:
        tier = 0

    # -----------------------------
    # Handle Berserk (Tier 4)
    # -----------------------------
    if tier == 4:

        # Trigger berserk one time only
        if not warrior.berserk_active and not warrior.berserk_used:
            warrior.berserk_active = True
            warrior.berserk_turns = 1
            warrior.berserk_used = True

            print(wrap("🩸🔥 **BERSERK MODE ACTIVATED!** "
                       "Your survival instinct explodes in pure adrenaline!"))

        else:# While active → fade normally
            if warrior.berserk_active:
                warrior.berserk_turns -= 1
                if warrior.berserk_turns <= 0:
                    warrior.berserk_active = False
                    print(wrap("Your berserk fury fades as clarity returns."))

        # Berserk bonus always:
        # +6 adrenaline boost + rage stat
        return 6 + warrior.max_rage

    # -----------------------------
    # Reset 'used' flag only if HP is safely above berserk zone
    # -----------------------------
    if hp_percent > 0.20:
        warrior.berserk_used = False

    # -----------------------------
    # Normal adrenaline tier messages
    # -----------------------------
    if tier != warrior.rage_state:
        warrior.rage_state = tier

        if tier == 1:
            print(wrap("🔥 You grit your teeth—your adrenaline surges (+1 Damage)."))
        elif tier == 2:
            print(wrap("🔥🔥 Pain sharpens your focus (+2 Damage)."))
        elif tier == 3:
            print(wrap("🔥🔥🔥 You push through the agony (+3 Damage)."))
        elif tier == 0:
            print(wrap("You steady your breathing as the adrenaline ebbs."))

    # -----------------------------
    # Normal bonus = tier + rage stat
    # -----------------------------
    if tier > 0:
        return tier + warrior.max_rage
    else:
        return 0




# ===============================
# Monsters
# ===============================
class Slime(Monster):
    def __init__(self):
        super().__init__(
            name="green slime",
            hp=10,
            min_atk=1,
            max_atk=2,
            gold=3,
            xp=3,
            essence=["slime essence"],
            defence=0
        )


class Goblin(Monster):
    def __init__(self):
        super().__init__(
            name="green goblin",
            hp=8,
            min_atk=1,
            max_atk=3,
            gold=3,
            xp=4,
            essence=["goblin essence"],
            defence=1
        )



class Skeleton(Monster):
    def __init__(self):
        super().__init__(
            name="brittle skeleton",
            hp=12,
            min_atk=2,
            max_atk=5,
            gold=5,
            xp=5,
            essence=["skeleton essence"],
            defence=1
        )


class Wolf(Monster):
    def __init__(self):
        super().__init__(
            name="wolf pup",
            hp=11,
            min_atk=3,
            max_atk=5,
            gold=6,
            xp=7,
            essence=["wolf essence"],
            defence=2)
          
class Fallen_Warrior(Monster):
    def __init__(self):
        super().__init__(
            name="fallen warrior",
            hp=25,
            min_atk=2,
            max_atk=6,
            gold=7,
            xp=10,
            essence=["fallen warrior essence"],
            defence=1
        )
        self.ap = 2

    def attack(self, target):
        if self.ap > 0 and random.randint(1, 3) == 1:
            print(f"💀 {self.name} remembers a special defence breaking technique, and strikes at {target.name} defences!")
            damage = random.randint(self.min_atk + 2, self.max_atk + 5)
            self.ap -= 1

            actual = target.apply_defence(damage, attacker=self, defence_break=True)
            print(f"{self.name} hits {target.name} for {actual} damage! (rolled {damage})")
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
            gold=9,
            xp=9,
            essence=["ghost essence"],
            defence=0
        )
        

class Wolf_Rider(Monster):
    def __init__(self):
        super().__init__(name= "wolf pup rider",
                         hp=19,
                         min_atk=3,
                         max_atk=7,
                         gold=12,
                         xp=13,
                         essence=["goblin essence", "wolf pup essence"],
                         defence=2
                         )
        self.loot_drop = "Wolf Pup Pelt"
        self.ap=1
    
    def drop_loot(self):
        print(f"\n🎁 Loot dropped: {self.loot_drop}!")
        
        return self.loot_drop





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
            potions=None,
            move_points=3
        )

        # ---------------------------
        # Potion Initialization
        # ---------------------------
        # Ensure the potions dict exists
        if self.potions is None:
            self.potions = {"heal": 0, "ap": 0}

        # Start with 1 healing potion
        self.potions["heal"] = 1  

        # ---------------------------
        # Adrenaline / Rage System
        # ---------------------------
        self.max_rage = 0       # permanent bonus attack from stat points
        self.rage_state = 0     # which adrenaline spike you're in (0–4)

        # Berserk flags (NEW)
        self.berserk_active = False     # <-- REQUIRED
        self.berserk_turns = 0          # <-- REQUIRED
        self.berserk_used = False
        self.berserk_pending = False

        # ---------------------------
        # Level-up stat points
        # ---------------------------
        self.stat_points = 0
        self.current_bonus_damage = 0  # Track current bonus damage from adrenaline




# ===============================
# Encounter Helpers
# ===============================
# Each fight uses fresh monsters so HP/xp don’t leak between rounds.
MONSTER_TYPES = [
    (Slime, 3),
    (Goblin, 3),
    (Skeleton, 2),
    (Wolf,2),
    (Fallen_Warrior, 1),
    (Ghost, 1),
    (Wolf_Rider, .75)
]


def random_encounter():
    """Pick a monster based on weights and return a NEW instance."""
    types, weights = zip(*MONSTER_TYPES)
    chosen_cls = random.choices(types, weights=weights, k=1)[0]
    return chosen_cls()


# ===============================
# Combat System
# ===============================
def warrior_attack_roll(warrior):
    return random.randint(warrior.min_atk, warrior.max_atk)




def enemy_attack(enemy, warrior):
    """Enemy attacks once. Uses special attack if defined"""
    if  "attack" in enemy.__class__.__dict__:
        actual = enemy.attack(warrior)  # Already applies defence
        damage = actual
    else:
        damage = enemy.attack_roll()
  

        actual = warrior.apply_defence(damage, attacker=enemy)
        
    
    print(f"{enemy.name} attacks you for {actual} damage! (rolled {damage})")
    print(f"Your HP: {warrior.hp}/{warrior.max_hp}")





def player_basic_attack(warrior, enemy):
    
    bonus = compute_adrenaline_bonus(warrior)
    warrior.current_bonus_damage = bonus
    base_roll = warrior_attack_roll(warrior)
    damage = base_roll + bonus

    actual = enemy.apply_defence(damage, attacker=warrior)
    if bonus > 0:
        print(f"You roled a {base_roll} + {bonus} bonus damage!")
    else:
        print(f"You roled a {base_roll}!")

    print(f"You attack {enemy.name} for {actual} damage! (rolled {damage})")
    print(f"{enemy.name} HP: {enemy.hp}/{enemy.max_hp}")



def use_potion(warrior):
    print("\nPotions:")
    print(f"1) Heal (+10 HP) x{warrior.potions['heal']}")
    print("2) Back")

    choice = input("> ").strip()

    if choice == "1":
        if warrior.potions["heal"] > 0:
            warrior.potions["heal"] -= 1
            heal = 10
            old_hp = warrior.hp
            warrior.hp = min(warrior.max_hp, warrior.hp + heal)

            print(f"You drink a healing potion and recover {warrior.hp - old_hp} HP!")
            print(f"HP: {warrior.hp}/{warrior.max_hp}")
            return True
        else:
            print("You have no healing potions!")
            return False

    elif choice == "2":
        return False

    else:
        print("Invalid choice.")
        return False

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
    """
    Core 1v1 battle.

    - First turn: random (warrior or enemy).
    - After that: strictly alternate. No extra hidden damage.
    """
    
    print(f"\n{warrior.name} enters the arena!")
    print(f"You face a {enemy.name}!")
    print(f"{warrior.name} HP: {warrior.hp}/{warrior.max_hp}  |  "
          f"{enemy.name} HP: {enemy.hp}/{enemy.max_hp}")

    # True  = warrior's turn, False = enemy's turn
    warrior_turn = random.choice([True, False])
    if warrior_turn:
        warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)
        #warrior.show_game_stats()
        print("You get the first move!")
    else:
        print(f"{enemy.name} makes the first move!")

    while warrior.is_alive() and enemy.is_alive():
        if warrior_turn:
            # ---------- Player Turn ----------
            
            warrior.current_bonus_damage = compute_adrenaline_bonus(warrior)   # <-- UPDATE BONUS FIRST
            warrior.show_game_stats()
            prompt = textwrap.fill(
                "Your move:\n"
                "1) Attack\n"
                "2) Special (WIP)\n"
                "3) Use Potion\n"
                "4) Run Away\n"
                "(Type 1-4)",
                WIDTH
            )
            choice = check(prompt + "\n> ", ["1", "2", "3", "4"])
            clear_screen()

            if choice == "4":
                print(textwrap.fill("You turn your back on the crowd and atemp to flee the arena! The crowd boos and you are shot in the back", WIDTH))
                space()
                print(textwrap.fill("Dealth comes slowly. The arrow you were shot with contains a lethal posion. Five minutes of pain insues, every minute more painful than the last", WIDTH))
                space()
                print(textwrap.fill("As you take you final breath the monster shaman looks at you and says'You are not even worthy of resurection'", WIDTH))
                warrior.titles.append("Coward")
                print("[Title Unlocked: Coward]")
                continue_text()
                warrior.show_all_game_stats()
                print("\nCowardice is not welcome in this arena")
                print("\nYour story ends in discgrace")
                input("\nPress enter to quit")
                quit()

                #return False  # retreat ends the run

            if choice == "1":
                player_basic_attack(warrior, enemy)

            elif choice == "2":
                # Hook your Block / Battle Cry / Double Strike here later
                print("You attempt a special move, but it's not implemented yet.")
                # Still consumes your turn for now.

            elif choice == "3":
                used = use_potion(warrior)
                if not used:
                    # If they cancel, don't lose the turn.
                    continue

            # Check if enemy died
            if not enemy.is_alive():
                if hasattr(warrior, "original_defence"):
                    warrior.defence = warrior.original_defence
                    del warrior.original_defence
                print(f"\nYou have defeated {enemy.name}!")
                warrior.gold += enemy.gold
                warrior.xp += enemy.xp
                warrior.monster_essence.extend(enemy.essence)
                print(f"You loot {enemy.gold} gold and gain {enemy.xp} XP.")
                # Handle loot drops if enemy has them
                # hasattr is a special function that checks if an object has a certain attribute. In the example below "drop_loot" is referening drop.loot."
                if hasattr(enemy, "drop_loot"):
                    loot = enemy.drop_loot()
                    if loot:
                        warrior.inventory.append(loot)
                        print(f"{loot} has been added to your inventory!")
                if len(warrior.monster_essence) >= 3:
                    print("\n✨ You have collected three essences and won the Tournament of Beasts!")
                    warrior.titles.append("Champion of the Arena")
                    warrior.show_game_stats()
                    return "win"
                input("Press enter to continue.")
                warrior.level_up()
                # warrior is called here because it is a representation of the warrior object created earlier in the code
                rest_phase(warrior)
                return True

        else:
            # ---------- Enemy Turn ----------
            enemy_attack(enemy, warrior)
            if not warrior.is_alive():
                print("\nYou collapse as the arena roars in bloodthirsty delight...")
                print("You have been defeated.")
                return False

        # Strict alternation: always flip after one side acts
        warrior_turn = not warrior_turn


def arena_battle(warrior, rounds_to_win=3):
    """
    Tournament:
    - Fight `rounds_to_win` random monsters in a row.
    - Lose or run once → run ends.
    """
    print(textwrap.fill(
        "You are pushed out onto the arena floor. Magical torches flare to life around the ring. "
        "The stands are packed with monsters of every shape and size, all howling for blood.",
        WIDTH
    ))

    defeated_names = []

    for round_num in range(1, rounds_to_win + 1):
        print(f"\n--- Round {round_num} ---")
        enemy = random_encounter()
        result = battle(warrior, enemy)

        if result == "win":
            print("\n🎉 The crowd erupts! You are the Champion of the Arena!")
            warrior.show_all_game_stats()
           
            return
       


        if not result or not warrior.is_alive():
            print(textwrap.fill(
                f"{enemy.name} stands victorious over your fallen body. "
                "As darkness closes in, you hear a voice whisper, "
                "'You will serve the beast gods for all eternity...'",
                WIDTH
            ))
            return

        defeated_names.append(enemy.name)

    print("\n🏆 You are victorious in the arena!")
    print("You defeated:", ", ".join(defeated_names))
    print(f"You leave with {warrior.gold} gold and {len(warrior.monster_essence)} essences.")
    # Perfect place to plug in endings / titles later.


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

        name = input("\nWhat is your name, adventurer?\n> ").strip() or "Adventurer"
        GAME_WARRIOR.name = name

        print(textwrap.fill(
            "A burly beastman steps out of the cave, towering over you. "
            "He snorts and says, \"Looks like we have another volunteer for our monster tournament.\"",
            WIDTH
        ))

        tournament_entrance = check(
            f"\nWhat do you do, {name}? Do you try to escape, or submit?\n"
            "Type 'escape' to try to escape, or 'submit' to accept your fate.\n> ",
            ["escape", "submit"]
        )

        

        # --------------------------------------------
        # TRY TO ESCAPE
        # --------------------------------------------
        if tournament_entrance == "escape":
            clear_screen()
            print(textwrap.fill(
                "You turn and sprint into the forest, but the beastman is far too fast. "
                "He charges after you with terrifying speed. "
                "Fear seizes you as you realize you have become the prey.",
                WIDTH
            ))

            space()
            print(textwrap.fill(
                "A short chase ensues, but the beastman's strength and animalistic aggression "
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
                    f"\"The tournament pits a random adventurer— you, {name} — "
                    "against three different monsters of varying strength. "
                    "Defeat all three in single combat, and you win your freedom.\"",
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
                                "Type 'essence' for more about monster essences,\n"
                                "or 'victory' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["essence", "victory"]
                        )

                        if extra_info_choice == "essence":
                            clear_screen()
                            print(textwrap.fill(
                                "\"You're a curious one,\" the beastman says.\n\n"
                                "\"A monster's essence is like its soul. "
                                "It allows us to revive them. You adventurers kill so many of us "
                                "that we'd go extinct without them.\"",
                                WIDTH
                            ))
                            print(textwrap.fill(
                                f"\"The tournament starts tomorrow night. Rest up, {name}. You'll need it.\"",
                                WIDTH
                            ))
                        elif extra_info_choice == "victory":
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
                    f"You do overhear the beastman who captured you placing a bet in your favor, {name}.",
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
        if tournament_entrance == "submit":
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
            "landing in a nearby stream and sputtering out.",
            WIDTH
        ))
        print(textwrap.fill(
            "The forest is swallowed by darkness. The canopy above blocks out the night sky, "
            "and the silence feels oppressive.",
            WIDTH
        ))
        print(textwrap.fill(
            "You have no other source of light, and a soaked torch won't light easily.",
            WIDTH
        ))
        print(textwrap.fill(
            "Why tonight? You're tired, hungry, and this unnatural darkness gnaws at your nerves.",
            WIDTH
        ))

        night_choice = check(
            textwrap.fill(
                "\nWhat do you do?\n"
                "Type 'rest' to rest against the trees until first light,\n"
                "or 'search' to feel your way toward where the torch fell.\n> ",
                WIDTH
            ),
            ["rest", "search"]
        )

        

        # ------------------------------
        # REST PATH
        # ------------------------------
        if night_choice == "rest":
            clear_screen()
            print(textwrap.fill(
                "Blundering around in unnatural darkness seems like a bad idea. "
                "You decide to try to get a few hours of sleep before first light.",
                WIDTH
            ))
            print(textwrap.fill(
                "As you lie down, you hear distant, heavy footsteps. "
                "Fear slowly creeps into your mind. Your adrenaline rises "
                "as the footsteps grow closer.",
                WIDTH
            ))

            footsteps_choice = check(
                textwrap.fill(
                    "What do you do?\n"
                    "Type 'call' to call out, or 'silent' to stay perfectly still.\n> ",
                    WIDTH
                ),
                ["call", "silent"]
            )

           

            # CALL OUT
            if footsteps_choice == "call":
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
                name = input("\nWhat is your name, adventurer?\n> ").strip() or "Adventurer"
                GAME_WARRIOR.name = name

                print(textwrap.fill(
                    "The creature snaps its fingers. The magical darkness begins to lift. "
                    "It's still night, but you can now make out the shape of a towering figure, "
                    "like a bear standing on two legs.",
                    WIDTH
                ))

                fading_darkness = check(
                    textwrap.fill(
                        f"What do you do, {name}? Do you 'run' or 'stay'?\n> ",
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
                    print(textwrap.fill(
                        "Your panic gives you unnatural speed. For a moment, it feels like you're gaining ground.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "Then you hear a frustrated growl, followed by a sharp snap. "
                        "The magical darkness slams back into place.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "Blinded, you run face-first into a thick tree branch.",
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

                    print(textwrap.fill(
                        "When your vision clears, a massive bearman looms over you.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        f"\"Nice try, {name},\" he rumbles. \"You almost got away. "
                        "I haven't failed a pursuit in a long time. If it weren't for my magic, "
                        "you would have escaped.\"",
                        WIDTH))
                    print(textwrap.fill("here is a little somthing to help you out Bo hands you 2 potions one healing and one ap",WIDTH))
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
                        print(textwrap.fill(
                            "\"The tournament pits you against three monsters in solo combat. "
                            "If you defeat all three, you win. Each monster you defeat rewards you "
                            "with gold and a monster essence. Turn in the essences, and you are set free.\"",
                            WIDTH
                        ))

                        bo_questions = check(
                            textwrap.fill(
                                "Bo asks if you have any questions.\n"
                                "Type 'essence' to ask about essences,\n"
                                "or 'victory' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["essence", "victory"]
                        )

                        if bo_questions == "essence":
                            clear_screen()
                            print(textwrap.fill(
                                "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                "\"With them, we can revive fallen monsters. Without essences, "
                                "our people would dwindle with every hunt.\"",
                                WIDTH
                            ))
                        elif bo_questions == "victory":
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
                        f"\"Either way, {name}, you'll do nicely for our tournament.\"",
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
            if footsteps_choice == "silent":
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
        if night_choice == "search":
            clear_screen()
            print(textwrap.fill(
                "You rise and carefully feel your way toward the sound of the stream, "
                "hoping to recover your torch.",
                WIDTH
            ))
            stream_attack = random.randint(1, 2)
            GAME_WARRIOR.hp = max(0, GAME_WARRIOR.hp - stream_attack)
            print(textwrap.fill(
                "As you step onto the muddy embankment, your foot slips. "
                "You tumble into the ice-cold mountain stream.",
                WIDTH
            ))
            print(textwrap.fill(
                f"You take {stream_attack} damage from the fall and the frigid water. "
                f"You now have {GAME_WARRIOR.hp} HP remaining.",
                WIDTH
            ))
            print(textwrap.fill(
                "The freezing water shocks your body, but you manage to claw your way back to the shore.",
                WIDTH
            ))
            print(textwrap.fill(
                "Soaked, shivering, and still without a torch, you mutter a few choice words "
                "about your luck.",
                WIDTH
            ))
            print(textwrap.fill(
                "Before you can regain your bearings, a massive shadow looms over you. "
                "A beastman seizes you and drags you away, muttering something about "
                "a 'late entry' to the tournament.",
                WIDTH
            ))
            continue_text()
            clear_screen()
            arena_battle(GAME_WARRIOR)
            return



if __name__ == "__main__":
    GAME_WARRIOR = Warrior()
    intro_story(GAME_WARRIOR)

'''✅ Dungeon Adventure – Version History Summary

(based on everything we’ve built together in the past )

version.12 added rest mechanice inbetween rounds of combat
    * fine tuned rage mechanic

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

Added Fallen Hero moral choice (free or destroy essence)

Added consequences: stat point or gold

Added ability to remove Fallen Hero from monster pool after saving

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

