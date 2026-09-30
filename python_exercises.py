# python_exercises.py — JTWH Learning Module
# Fill-in-the-blank exercises based on code worked on in sessions.
# Difficulty: ★ (beginner) through ★★★★★ (expert)
# Each exercise is SELF-CONTAINED — no codebase knowledge needed.
# DO NOT look at answers — work through them yourself!

# ============================================================
# SESSION: September 20, 2026
# Topics: D&D-style dice rolls, story flags (sets), random weighted
#         selection, Equipment attributes, combat state tracking
# ============================================================

# ── EXERCISE 1 ── ★★
# CONCEPT: Using sets for one-time event tracking (story flags)
#
# A game uses a set called `story_flags` to track events that
# should only happen once per run. Write a function that checks
# if a scene has played, and if not, marks it as played and
# returns True. If it already played, return False.
#
# Fill in the blanks:

def should_play_scene(story_flags, scene_name):
    if scene_name _____ story_flags:    # check if already in the set
        return _____
    story_flags._____(scene_name)       # add it to the set
    return _____


# ── EXERCISE 2 ── ★★
# CONCEPT: D20 dice rolls with modifiers (D&D-style checks)
#
# In D&D, a strength check rolls a 20-sided die and adds a
# modifier. The total is compared against a DC (difficulty class).
# If total >= DC, the check succeeds.
#
# Write a function that takes a modifier and a DC, rolls a d20,
# and returns a tuple of (roll, total, succeeded).
#
# Fill in the blanks:

import random

def strength_check(modifier, dc):
    roll = random._____(1, _____)       # roll 1-20
    total = roll _____ modifier         # add the modifier
    succeeded = total _____ dc          # compare against DC
    return (roll, total, succeeded)


# ── EXERCISE 3 ── ★★★
# CONCEPT: Deriving a modifier from a stat (lookup table pattern)
#
# Monsters don't have a STR stat, so we derive one from their
# max attack value. Low ATK = weak = negative modifier.
# High ATK = strong = positive modifier.
#
# Complete the function using if/elif/else:
#   ATK 1-4  → modifier -1
#   ATK 5-7  → modifier  0
#   ATK 8-11 → modifier +2
#   ATK 12+  → modifier +4

def get_str_modifier(max_atk):
    if max_atk _____ 4:
        return _____
    _____ max_atk <= 7:
        return _____
    elif max_atk _____ _____:
        return _____
    _____:
        return _____


# ── EXERCISE 4 ── ★★★
# CONCEPT: Weighted random selection (trick-or-treat mechanic)
#
# A candy has a 70% chance of giving a buff and a 30% chance
# of giving a debuff. If it's a buff, pick a random stat from
# a weighted list. If it's a debuff, pick a random core stat.
#
# Fill in the blanks:

def eat_candy_corn():
    roll = random._____()                    # random float 0.0-1.0
    if roll _____ 0.70:                       # 70% chance
        # Buff — pick from weighted options
        buff_table = ["hp", "hp", "hp",       # 30% weight (3/10)
                      "atk", "atk",            # 20% weight
                      "def", "def",            # 20% weight
                      "ap", "ap",              # 20% weight
                      "magic_res"]             # 10% weight
        stat = random._____(buff_table)        # pick one at random
        return ("buff", stat)
    else:
        # Debuff — equal chance across 4 core stats
        core = ["hp", "atk", "def", "ap"]
        stat = random._____(core)
        return ("_____", stat)


# ── EXERCISE 5 ── ★★★★
# CONCEPT: Multi-turn combat state machine (entangle mechanic)
#
# An entangle effect lasts multiple turns. Each turn:
#   - Turn 1: enemy is locked, no damage
#   - Turn 2+: deal vine damage, then enemy tries to break free
#   - If turns run out, entangle ends automatically
#
# Fill in the blanks to process one tick of entangle:

def tick_entangle(enemy_hp, current_turn, turns_remaining, vine_dmg, dc):
    """
    Returns: (new_hp, new_turn, new_remaining, result)
    result is 'skip', 'broke_free', or 'expired'
    """
    current_turn _____ 1                        # increment turn counter
    turns_remaining _____ 1                      # decrement remaining

    if current_turn == _____:                    # first turn = pure lockdown
        if turns_remaining <= 0:
            return (enemy_hp, current_turn, 0, "expired")
        return (enemy_hp, current_turn, turns_remaining, "_____")

    # Turns 2+: vine damage first
    enemy_hp _____ vine_dmg                      # subtract vine damage

    # Strength check to break free
    roll = random.randint(1, 20)
    if roll _____ dc:                            # meet or beat DC = escape
        return (enemy_hp, current_turn, 0, "_____")

    # Failed check
    if turns_remaining _____ 0:                  # out of turns
        return (enemy_hp, current_turn, 0, "expired")

    return (enemy_hp, current_turn, turns_remaining, "skip")


# ── EXERCISE 6 ── ★★★★★
# CONCEPT: Charge-based item with rarity scaling
#
# A Pumpkin Vine Totem has charges that scale with rarity.
# The player can reload charges for 1 candy each.
# Write a function that tries to reload N charges, spending
# candy, without exceeding max_charges.
# Returns (charges_added, candy_spent).

def reload_totem(current_charges, max_charges, requested, candy_available):
    # Can't add more than max allows
    room = max_charges _____ current_charges     # how many slots are open
    # Can't add more than player can afford
    affordable = _____(requested, candy_available) # min of requested and affordable
    # Can't add more than room allows
    actual = _____(affordable, _____)             # min of affordable and room
    return (actual, _____)                         # charges added = candy spent


# ============================================================
# SESSION: September 25, 2026
# Topics: range() function, accumulator pattern (running totals),
#         modulus operator (%), FizzBuzz logic, if/elif ordering
# ============================================================

# ── EXERCISE 7 ── ★
# CONCEPT: range() bounds — inclusive lower, exclusive upper
#
# The range(a, b) function gives numbers from a up to but NOT
# including b. Fill in the range so this loop prints 1 through 50
# (including 50).
#
# Fill in the blanks:

# for number in range(_____, _____):
#     print(number)


# ── EXERCISE 8 ── ★★
# CONCEPT: Accumulator pattern — building a running total
#
# You need a variable OUTSIDE the loop that survives between
# iterations. The loop adds to it each pass.
#
# Calculate the sum of all numbers from 1 to 200 (inclusive).
# Fill in the blanks:

# total = _____                        # start the bucket at zero
# for number in range(1, _____):       # include 200
#     total _____ number               # add current number to bucket
# print(total)


# ── EXERCISE 9 ── ★★
# CONCEPT: Modulus operator — checking divisibility
#
# The % operator gives the REMAINDER of division.
# A number is divisible by another when the remainder is 0.
#
# Write a function that returns True if a number divides evenly
# by a given divisor, False otherwise.
#
# Fill in the blanks:

def is_divisible(number, divisor):
    return number _____ divisor _____ 0    # remainder equals zero?


# ── EXERCISE 10 ── ★★★
# CONCEPT: FizzBuzz — ordering conditional checks correctly
#
# Print numbers 1-30. If divisible by 3, print "Fizz".
# If divisible by 7, print "Buzz". If divisible by BOTH
# 3 and 7, print "FizzBuzz".
#
# IMPORTANT: The order of checks matters! The hardest
# condition to satisfy must be checked FIRST.
#
# Fill in the blanks:

# for number in range(1, _____):
#     if number % _____ == 0:           # check BOTH first (hardest)
#         print("_____")
#     _____ number % 3 == 0:            # then check 3
#         print("Fizz")
#     _____ number % _____ == 0:        # then check 7
#         print("Buzz")
#     _____:                            # everything else
#         print(number)


# ── EXERCISE 11 ── ★★★
# CONCEPT: Accumulator + conditional — counting specific items
#
# Count how many numbers between 1 and 100 are divisible by
# BOTH 3 and 5. Use the accumulator pattern but only add to
# the counter when the condition is met.
#
# Fill in the blanks:

# count = _____
# for number in range(_____, _____):
#     if number % _____ == 0 _____ number % _____ == 0:
#         count _____ 1
# print(f"There are {count} numbers divisible by both 3 and 5")


# ── EXERCISE 12 ── ★★★★
# CONCEPT: Combining range, accumulator, and modulus
#
# A Halloween vendor charges candy based on monster tier.
# Given a list of defeated monster tiers, calculate the
# total candy earned. Rules:
#   - Tier 1 monsters: 1 candy each
#   - Tier 2 monsters: 2 candy each
#   - Tier 3 monsters: 3 candy each
#   - Bonus: if the kill number is divisible by 5 (every
#     5th kill), award 1 extra candy
#
# Fill in the blanks:

def calculate_candy(tier_list):
    total_candy = _____
    for kill_number in range(_____, len(tier_list) + _____):
        tier = tier_list[kill_number _____ 1]     # lists are 0-indexed
        total_candy _____ tier                     # add tier-based candy
        if kill_number _____ 5 == _____:           # every 5th kill
            total_candy += _____                   # bonus candy
    return total_candy


# ============================================================
# SESSION: September 29, 2026
# Topics: for loops with functions, attribute name matching,
#         flag-based flow control, getattr with defaults,
#         conditional display (HUD pattern)
# ============================================================

# ── EXERCISE 13 ── ★
# CONCEPT: for loops calling functions (Reeborg's World pattern)
#
# You have a function `harvest_row()` that picks all the crops
# in one row of a farm. Write a for loop that calls it for
# every row in a 6-row field. Use the variable name `row`.
#
def harvest_row():
    pass  # pretend this picks crops

for _____ in _____(6):
    _____()


# ── EXERCISE 14 ── ★★
# CONCEPT: getattr with defaults for safe attribute access
#
# A player object might or might not have a `halloween_candy`
# attribute. Write code that safely reads it (defaulting to 0)
# and prints "🎃 Halloween Candy: X" ONLY if they have some.
# Use getattr.
#
class Player:
    pass

p = Player()
p.halloween_candy = 12

candy = _____(p, "_____", _____)
if _____ > _____:
    print(f"🎃 Halloween Candy: {_____}")


# ── EXERCISE 15 ── ★★★
# CONCEPT: Flag-based flow control (Halloween tournament pattern)
#
# A game picks enemies from a normal pool OR a special pool
# based on a flag. Fill in the blanks so the function returns
# "Goblin" normally, but "Pumpkin" when the warrior has
# `halloween_mode` set to True.
#
def pick_enemy(warrior):
    if _____(warrior, "___________", _____):
        pool = ["Pumpkin", "Ghost", "Witch"]
    _____:
        pool = ["Goblin", "Rat", "Wolf"]
    import random
    return random.choice(_____)


# ── EXERCISE 16 ── ★★★
# CONCEPT: Attribute name consistency (the Vine Totem bug)
#
# A weapon builder sets `vine_dc` on an item, but the combat
# code checks `entangle_dc`. This is a real bug pattern.
# Fix the combat function to check the CORRECT attribute name.
#
class Weapon:
    def __init__(self):
        self.vine_dc = 15       # builder sets this
        self.vine_charges = 3   # builder sets this

def try_entangle(weapon, enemy):
    # BUG: these attribute names don't match the builder!
    dc = getattr(weapon, "entangle_dc", 0)
    charges = getattr(weapon, "entangle_charges", 0)
    if charges > 0 and dc > 0:
        print(f"Entangle at DC {dc}!")
        return True
    print("No entangle available.")
    return False

# Fix: change the getattr calls to use "________" and "_____________"


# ── EXERCISE 17 ── ★★★★
# CONCEPT: Building something AND using it (import + call pattern)
#
# This is the pattern you hit THREE times this session:
# importing but not calling, building but not printing.
# Fill in the blanks to make the set bonus actually apply.
#
def apply_wolf_bonus(warrior):
    warrior.defence += 2

def apply_halloween_bonus(warrior):
    warrior.max_hp += 6

def apply_all_bonuses(warrior):
    apply_wolf_bonus(warrior)
    # Import the Halloween bonus (pretend it's in another file)
    # For this exercise, it's already defined above.
    # The mistake is: we reference it but never CALL it.
    # Fill in the blank to actually run it:
    _____(warrior)

class Warrior:
    def __init__(self):
        self.defence = 5
        self.max_hp = 30

w = Warrior()
apply_all_bonuses(w)
# After running: w.defence should be 7, w.max_hp should be 36
# print(f"DEF: {w.defence}, HP: {w.max_hp}")
