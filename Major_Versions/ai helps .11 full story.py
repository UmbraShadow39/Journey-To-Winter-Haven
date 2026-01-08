import random
import textwrap
import os
import time

# ===============================
# Config / Globals
# ===============================
WIDTH = 65


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


def check(prompt, options):
    """
    Ask the player for input until they give a valid option.

    - prompt: text to show the player
    - options: list of valid lowercase strings, e.g. ["yes", "no", "q"]
    """
    choice = input(prompt).lower().strip()
    while choice not in options:
        print("Invalid choice, try again.")
        choice = input(prompt).lower().strip()
    return choice

def space(line=1):
    for _ in range(line):
        print()

def full_defensive_block(attacker, defender):
    defence_success =[f"{attacker.name}swings hard but a quick block by {defender.name} absorbs all the damage",
                      f"{attacker.name}'s attack is not enough and is blocked by {defender.name}",
                      f"{defender.name} pivots just in time to avoid the damage from {attacker.name}'s attack",
                      f"{defender.name} blocks the attack with their limbs taking no damage from {attacker.name}",
                      f"{attacker.name} try to sucker punch {defender.name}, but {defender.name} lungs backwards avoiding the blow",
                      f"{attacker.name} lands a glancing blow, but {defender.name} tough exterior absorbs the blow",
                      f"{attacker.name}, lunges at {defender.name}, but {defender.name}, back steps avoiding damage",
                      f"{defender.name}, paries {attacker.name} attack, taking no damage",
                      f"{attacker.name} is quick but {defender.name} is quicker, narrowly avoiding damage",
                      f"{attacker.name} charges {defender.name} but in an amazing acrobatic display {defender.name} back flips out of the way"
                      ]
    return random.choice(defence_success)
def partial_defensive_block(attacker, defender, damage_blocked):
    defence_partial_successs = [f"{attacker.name} charges forward wildly, {defender.name} manages to block some of the damge, but {attacker.name} still lands a few hit.",
                                f"{defender.name} raises their limbs to block {attacker.name} impact is reduced but {defender.name} still takes some damage",
                                f"{defender.name} try to pivot away from {attacker.name} attack, but is only partially successful, taking some damage",
                                f"{attacker.name} swings hard {defender.name} try to block but is a little to slow. Damage is reduced but not avoided",
    ]
    return random.choice(defence_partial_successs)


# ===============================
# Base Classes
# ===============================
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
    
    def apply_defence(self, damage, attacker=None):
        """Calculate actual damage after defence."""
        reduced_defence = min(self.defence, damage)
        actual = max(0, damage - self.defence)
        
        if actual == 0:
            print(full_defensive_block(attacker, self))
        elif reduced_defence > 0:
            print(partial_defensive_block(attacker, self, reduced_defence))
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
        print(f"Hero: {self.name}   |   Level: {self.level}")
        print(f"HP: {self.hp}/{self.max_hp}  |  ATK: {self.min_atk}-{self.max_atk}")
        print(f"AP: {self.move_points}  |  DEF: {self.defence}")
        print(f"XP: {self.xp}/{self.xp_to_lvl}")
        print(f"Gold: {self.gold}")
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
        """Spend 2 stat points on HP / ATK / AP / DEF."""
        stat_points = 2
        while stat_points > 0:
            print(f"\nYou have {stat_points} stat points remaining.")
            print("1) +5 HP   2) +1 ATK range   3) +1 AP   4) +1 Defense")
            choice = input("> ").strip()

            if choice == "1":
                self.max_hp += 5
                self.hp = self.max_hp
                print(f"Max HP → {self.max_hp}")
            elif choice == "2":
                self.min_atk += 1
                self.max_atk += 1
                print(f"Attack → {self.min_atk}-{self.max_atk}")
            elif choice == "3":
                self.move_points += 1
                print(f"AP → {self.move_points}")
            elif choice == "4":
                self.defence += 1
                print(f"Defense → {self.defence}")
            else:
                print("Invalid choice, try again.")
                continue

            stat_points -= 1

        print("\nAll stat points spent!\n")


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
          
class Fallen_hero(Monster):
    def __init__(self):
        super().__init__(
            name="fallen hero",
            hp=21,
            min_atk=1,
            max_atk=5,
            gold=7,
            xp=8,
            essence=["fallen hero essence"],
            defence=0
        )
        self.ap = 2

    def attack(self, target):
        if self.ap > 0 and random.randint(1, 3) == 1:
            print(f"💀 {self.name} remembers a special technique and swings wildly, annilating  {target.name} defences!")
            damage = random.randint(self.min_atk + 2, self.max_atk + 5)
            self.ap -= 1

            actual = target.apply_defence(damage)
            

            if not hasattr(target, "original_defence"):
                target.original_defence = target.defence
            defence_reduction = min(2, target.defence)
            target.defence -= defence_reduction
            print(f"{self.name} hits {target.name} for {actual} damage! (rolled {damage})")
            print(f"{target.name}'s defence is crushed. Defense is reduced by {defence_reduction} for this battle!")
            return actual
        else:
            damage = random.randint(self.min_atk, self.max_atk)

            actual = target.apply_defence(damage)
            
            print(f"{self.name} hits {target.name} for {actual} damage! (rolled {damage})")
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
        
        return self.essence, self.loot_drop





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
        # Start with 1 healing potion
        self.potions["heal"] = 1


# ===============================
# Encounter Helpers
# ===============================
# Each fight uses fresh monsters so HP/xp don’t leak between rounds.
MONSTER_TYPES = [
    (Slime, 3),
    (Goblin, 3),
    (Skeleton, 2),
    (Wolf,2),
    (Fallen_hero, 1),
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
    """
    Your HP-based scaling idea:
    Lower HP → generally higher roll floor.
    """
    if warrior.hp <= 1:
        return random.randint(4, 8)
    elif warrior.hp <= 10:
        return random.randint(3, 7)
    elif warrior.hp <= 20:
        return random.randint(2, 6)
    else:
        return random.randint(1, 5)


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
    """Standard warrior basic attack."""
    damage = warrior_attack_roll(warrior)
    actual = enemy.apply_defence(damage, attacker=warrior)

    print(f"You attack {enemy.name} for {actual} damage! (rolled {damage})")
    print(f"{enemy.name} HP: {enemy.hp}/{enemy.max_hp}")


def use_potion(warrior):
    """
    Simple potion menu.
    Returns True if a potion was used (consumes turn),
    False if player backed out.
    """
    while True:
        print("\nPotions:")
        print(f"1) Heal (+10 HP) x{warrior.potions['heal']}")
        print(f"2) AP (+1 AP)   x{warrior.potions['ap']}")
        print("3) Back")
        choice = input("> ").strip()

        if choice == "1":
            if warrior.potions["heal"] > 0:
                warrior.potions["heal"] -= 1
                heal = 10
                warrior.hp = min(warrior.max_hp, warrior.hp + heal)
                print(f"You drink a healing potion and recover {heal} HP!")
                print(f"HP: {warrior.hp}/{warrior.max_hp}")
                return True
            else:
                print("You have no healing potions!")
        elif choice == "2":
            if warrior.potions["ap"] > 0:
                warrior.potions["ap"] -= 1
                warrior.move_points += 1
                print("You drink an AP potion. +1 AP!")
                return True
            else:
                print("You have no AP potions!")
        elif choice == "3":
            return False
        else:
            print("Invalid choice.")


def battle(warrior, enemy):
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
        print("You get the first move!")
    else:
        print(f"{enemy.name} makes the first move!")

    while warrior.is_alive() and enemy.is_alive():
        if warrior_turn:
            # ---------- Player Turn ----------
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
                        essence_list,item = loot
                        warrior.inventory.append(item)
                        print(f"{item} has been added to your inventory!")
                if len(warrior.monster_essence) >= 3:
                    print("\n✨ You have collected three essences and won the Tournament of Beasts!")
                    warrior.titles.append("Champion of the Arena")
                    warrior.show_game_stats()
                    return "win"
                input("Press enter to continue.")
                warrior.level_up()
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
def intro_story(warrior):
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
        ["yes", "no", "q"]
    )

    if winter_heaven_info == "q":
        print("You decide this story is not for you... for now.")
        return

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
        print(textwrap.fill(
            "There is a rumor that whenever a dungeon floor is fully cleared, the resources "
            "mysteriously replenish themselves. According to legend, that hasn't happened "
            "in nearly a century.",
            WIDTH
        ))
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
        warrior.name = name

        print(textwrap.fill(
            "A burly beastman steps out of the cave, towering over you. "
            "He snorts and says, \"Looks like we have another volunteer for our monster tournament.\"",
            WIDTH
        ))

        tournament_entrance = check(
            f"\nWhat do you do, {name}? Do you try to escape, or submit?\n"
            "Type 'escape' to try to escape, or 'submit' to accept your fate.\n> ",
            ["escape", "submit", "q"]
        )

        if tournament_entrance == "q":
            print(textwrap.fill(
                "You close your eyes and hope this is all a bad dream... It isn't.",
                WIDTH
            ))
            return

        # --------------------------------------------
        # TRY TO ESCAPE
        # --------------------------------------------
        if tournament_entrance == "escape":
            clear_screen()
            print(textwrap.fill(
                "You turn and sprint into the forest, but the beastman is far too fast. "
                "He charges after you with terrifying speed. You can feel his bloodlust behind you. "
                "Dread fills your heart as you realize you have become the prey.",
                WIDTH
            ))
            print(textwrap.fill(
                "A short chase ensues, but the beastman's strength and animalistic aggression "
                "are overwhelming. He slams into you with a brutal tackle.",
                WIDTH
            ))

            beast_man_tackle = random.randint(1, 4)
            warrior.hp = max(0, warrior.hp - beast_man_tackle)
            print(textwrap.fill(
                f"Pain sears through your body. You take {beast_man_tackle} damage.",
                WIDTH
            ))
            print(textwrap.fill(
                f"You have {warrior.hp} HP remaining.",
                WIDTH
            ))
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

            print(textwrap.fill("The beast man slips you a healing potion. 'I'll be betting on, you dont let me down'", WIDTH))
        # this rewards player with an extra heal potion for being brave
            warrior.potions["heal"] += 1

            tournament_knowledge = check(
                "\nWould you like to learn about the tournament? (yes/no)\n> ",
                ["yes", "no", "q"]
            )
            clear_screen()

            if tournament_knowledge == "q":
                intro_story()
               
                

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
                    ["yes", "no", "q"]
                )

                if tournament_inquiry == "q":
                    print("You decide you've heard enough—for now.")
                elif tournament_inquiry == "yes":
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
                            ["essence", "victory", "q"]
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
                        else:  # 'q'
                            print(textwrap.fill(
                                "You decide not to push your luck any further.",
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
                print(textwrap.fill(
                    "You can understand some of the monsters speaking outside. Most of them "
                    "are placing bets on your chances of survival. The odds are overwhelmingly "
                    "stacked against you.",
                    WIDTH
                ))
                print(textwrap.fill(
                    f"You do overhear the beastman who captured you placing a bet in your favor, {name}.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "Night falls. The cage door creaks open. You are led toward the roaring sound "
                    "of a crowd.",
                    WIDTH
                ))
                print(textwrap.fill(
                    "You step into the arena. Let the tournament begin!",
                    WIDTH
                ))
                continue_text()
                clear_screen()
                arena_battle(warrior)
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
            arena_battle(warrior)
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
            arena_battle(warrior)
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
            ["rest", "search", "q"]
        )

        if night_choice == "q":
            print("You curl up in the dark and let sleep, or something like it, take you.")
            return

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
                ["call", "silent", "q"]
            )

            if footsteps_choice == "q":
                print(textwrap.fill(
                    "You freeze, doing nothing, as the darkness and the footsteps close in...",
                    WIDTH
                ))
                return

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
                warrior.name = name

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
                    ["run", "stay", "q"]
                )

                if fading_darkness == "q":
                    print(textwrap.fill(
                        "You hesitate, doing nothing, as the creature's shadow looms over you.",
                        WIDTH
                    ))
                    return

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
                    warrior.hp = max(0, warrior.hp - tree_attack)
                    print(textwrap.fill(
                        f"You take {tree_attack} damage from the impact. Your head throbs and your vision fades.",
                        WIDTH
                    ))
                    print(textwrap.fill(
                        f"You have {warrior.hp} HP remaining.",
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
                        WIDTH
                    ))
                    print(textwrap.fill(
                        "\"I think you'll be a top-tier competitor in our upcoming tournament. "
                        "My name is Boar, but most call me Bo.\"",
                        WIDTH
                    ))

                    tournament_info = check(
                        "\nWould you like to learn more about the tournament? (yes/no)\n> ",
                        ["yes", "no", "q"]
                    )

                    if tournament_info == "q":
                        print(textwrap.fill(
                            "You shake your head, too overwhelmed to ask anything.",
                            WIDTH
                        ))
                    elif tournament_info == "yes":
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
                            ["essence", "victory", "q"]
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
                        else:
                            print(textwrap.fill(
                                "You decide you've heard enough for now.",
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
                    arena_battle(warrior)
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
                    name = warrior.name or "Adventurer"
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
                    arena_battle(warrior)
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
                arena_battle(warrior)
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
            warrior.hp = max(0, warrior.hp - stream_attack)
            print(textwrap.fill(
                "As you step onto the muddy embankment, your foot slips. "
                "You tumble into the ice-cold mountain stream.",
                WIDTH
            ))
            print(textwrap.fill(
                f"You take {stream_attack} damage from the fall and the frigid water. "
                f"You now have {warrior.hp} HP remaining.",
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
            arena_battle(warrior)
            return



if __name__ == "__main__":
    warrior = Warrior()
    intro_story(warrior)

