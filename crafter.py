"""
crafter.py — Arena Crafter (the workshop in the interlude hub)

The crafter handles three things:
    1) COMPONENT STOCK   — sells raw crafting components (pelts, sacs, tusks,
       pendants). Each component type ALWAYS has a Normal-rarity listing,
       plus ONE wildcard variant (Poor / Uncommon / Rare) rolled per visit.
       So every component appears as exactly 2 listings per visit.
    2) RECIPES           — converts components (and gold) into crafted gear.
       Crafted gear has FIXED stats per recipe (no rarity rolls on output).
       Higher-rarity input gives a gold DISCOUNT, not better stats. This is
       Nathan's "rare drops are crafting fuel, not equipment competitors"
       design — rare pelts make crafting cheaper rather than building a
       better cloak.
    3) SET SYSTEM        — pieces belong to named sets (Wolf-Hide is the first).
       Wearing multiple pieces of the same set unlocks scaling bonuses. The
       4-piece set unlocks a named passive.

Available now:
    WOLF-HIDE SET (made from Wolf Pelts + 1 Javelina Tusk for the charm)
        Hood    (helm slot, NEW)      — 1 Wolf Pelt
        Cloak   (cape slot, NEW)      — 1 Wolf Pelt
        Jerkin  (armor slot)          — 2 Wolf Pelts
        Charm   (accessory slot)      — 1 Wolf Pelt + 1 Javelina Tusk

    Scaling bonuses:
        2 pieces: +5 max HP
        3 pieces: +5 max HP, +1 max AP
        4 pieces: +5 max HP, +1 max AP, +2 DEF, +2 ATK
                  PLUS passive "Pack Hunter":
                      - +10% basic-attack damage
                      - 50% chance per basic attack to apply +3 bleed for
                        2 turns. Stacks ADDITIVELY with weapon bleed (one
                        merged tick — your '+3 + +3 = +6' rule).

Public API:
    crafter_scene(warrior, stock=None)        — full UI loop, called from interlude
    generate_crafter_stock()                  — returns the stock dict
    wolf_set_active_pieces(warrior)           — count of equipped Wolf-Hide pieces
    apply_wolf_set_bonus(warrior)             — recalc set bonuses (call after equip/unequip)
    pack_hunter_active(warrior)               — True if 4-piece set worn

Why a separate module:
    Mirrors merchant.py / titles.py / gold.py. The interlude hub is already
    a large function — keeping crafter logic here makes it easy to extend
    with more sets (Dire-Wolf set is next on the roadmap).
"""

import random


# ============================================================
# NAVIGATION — jump straight back to the crafter main menu
# ============================================================
#
# v0.7.13: The crafter menu tree got deep (component tabs, recipe tabs,
# tusk upgrade, socket sub-menus) — backing out from a deep screen used
# to mean hitting "0" three or four times in a row. Any submenu loop can
# now raise this on "M" and it unwinds straight back to crafter_scene's
# top-level menu, skipping every intermediate "0) Back" screen.
# ============================================================
class _ReturnToCrafterMenu(Exception):
    pass


# ============================================================
# CONFIG — pricing for component stock
# ============================================================

# Component prices are intentionally independent from merchant equipment
# pricing as of v0.6.19. Equipment now uses a tier-aware price model
# (rarity_base × tier_multiplier) because two normal-rarity weapons can
# have wildly different power levels (Goblin Dagger 1-1 vs War Blade 3-3).
# Components don't have tiers — they're raw materials whose value is the
# crafter recipes they feed. Crafter recipe balance has been tuned to
# these specific component prices, so changing them would cascade.
COMPONENT_PRICES = {
    "poor":       8,
    "normal":    18,
    "uncommon":  35,
    "rare":      65,
    # v0.7.17: extended for curing raw pelts at higher rarities — continues
    # the existing ~1.8-2x per-tier curve rather than inventing a new one.
    "epic":     120,
    "legendary":220,
    "mythril":  400,
}

# v0.7.13: Sell components back to the crafter at half their buy price —
# mirrors the merchant's SELL_BACK_RATE pattern for equipment. Previously
# raw components had no sell path at all (the merchant explicitly refuses
# them — "that's a crafter's job, not mine").
COMPONENT_SELL_BACK_RATE = 0.5


def _component_sell_price(item):
    rarity = getattr(item, "rarity", "normal")
    base = COMPONENT_PRICES.get(rarity, COMPONENT_PRICES["normal"])
    return max(1, int(base * COMPONENT_SELL_BACK_RATE))

# Wildcard roll: every component gets a Normal-rarity listing guaranteed.
# On top of that, ONE additional listing rolls in at one of these rarities.
# Weights based on Nathan's "Poor or Uncommon usually, Rare on lucky days":
WILDCARD_RARITY_WEIGHTS = [
    ("poor",     40),
    ("uncommon", 40),
    ("rare",     20),
]

# v0.7.17: On Champion difficulty, a rolled "rare" component has this chance
# to upgrade to "epic" instead — mirrors MERCHANT_VARIANT_CHANCE's existing
# 20% epic-weapon-variant roll in merchant.py, reused here for consistency.
CHAMPION_EPIC_CHANCE = 0.20

# Per-listing stock. Nathan's call: "2 total wolf pup pelts if the crafter
# draws them" — so each rarity variant that appears has 2 in stock.
COMPONENT_STOCK_PER_VARIANT = 2

# v0.7.17: Nathan's call — nothing the crafter sells is guaranteed to show
# up at all. Each component TYPE independently rolls this chance to appear
# per visit; when it does, the existing guaranteed-Normal + wildcard
# structure still applies (so minimum 2 in stock, same as always — just
# the type itself might not be there this time). Deliberately higher than
# the merchant's "pick 3 of a big pool" scarcity: with only ~11 component
# types total, a low chance would too easily lock a player out of every
# recipe path at once rather than just reshuffling which piece is
# buildable this visit.
CRAFTER_ITEM_APPEAR_CHANCE = 0.75

# v0.7.18: Nathan's call — Cured Wolf Pelt is ALWAYS in stock (guaranteed
# Normal listing = 2 on the shelf, plus the usual wildcard). Reasoning:
# stock rolls ONCE per interlude and persists across revisits, so the old
# 75% appearance roll meant a 25% chance the entire Wolf-Hide recipe path
# (the tier-1 crafted set — the Jerkin alone needs 2 pelts) was locked out
# for the whole run with no way to re-roll. Every other component,
# including Cured Dire Wolf Pelt, still rolls the 75% as before — tier-2
# scarcity is fine, tier-1 lockout wasn't.
ALWAYS_STOCKED_COMPONENTS = {
    "Cured Wolf Pelt",
}

# All components the crafter trades in. Order matters — it's the display order.
#
# v0.7.19: Nathan's call — the crafter now sells Wolf Pelt / Dire Wolf Pelt
# PRE-CURED. Previously the crafter sold the RAW pelt (full COMPONENT_PRICES
# cost) and then charged the separate 5g Cure Pelts fee on top of that —
# double-dipping on a component you already paid market price for. Now the
# crafter's own stock skips straight to "Cured Wolf Pelt"/"Cured Dire Wolf
# Pelt" at the same price. The 5g curing fee still applies, but only to raw
# pelts earned as free Arena drops (Wolf Pup / Dire Wolf Pup kills) — see
# CURABLE_PELTS below, which is unchanged and still keys off the RAW names.
COMPONENT_TYPES = [
    "Cured Wolf Pelt",
    "Cured Dire Wolf Pelt",
    "Poison Sac",
    "Fire Sac",
    "Acid Sac",
    "Javelina Tusk",
    "Soul Pendant",
    "AP Crystal",
    "HP Crystal",
    "Defence Crystal",
    "ATK Crystal",
]


# ============================================================
# REINFORCEMENT CRYSTALS (v0.7.17)
# ============================================================
#
# Nathan's call: rather than making Hood/Cloak recipes consume a MERCHANT
# ring (Spirit Crystal, Stoneheart Pendant, etc.) — which would force an
# awkward "wear it or feed it to a recipe" choice with an item bought
# elsewhere — the crafter sells its OWN dedicated, non-wearable crystal
# components. One per basic stat (AP/HP/DEF/ATK).
#
# v0.7.17 follow-up: crystals now carry FULL rarity tiers, same as pelts —
# they're just another COMPONENT_TYPES entry, so they automatically get
# the standard guaranteed-Normal + wildcard stock roll AND the same
# difficulty-gated ceiling already built for pelts (Easy caps at Uncommon,
# Normal caps at Rare, Champion has a 20% shot at Epic — see
# _roll_wildcard_rarity). Price follows the same COMPONENT_PRICES curve
# as every other component — "each level increases in cost."
#
# The bonus a crystal grants is LINEAR by rarity tier — Nathan's exact
# call for AP Crystal (Poor=+1 ... Mythril=+7, i.e. tier index + 1), and
# the same shape applied to the other three so they stay internally
# consistent. This is INTENTIONALLY separate from CRAFT_RARITY_STAT_
# MULTIPLIER (which scales the pelt-driven base stats on a steeper curve)
# — crystals are a simple, predictable, linear add-on layered on top.
#
# Whichever SPECIFIC crystal copy actually gets consumed (lowest-rarity-
# first, same rule as every other component — see _consume_components)
# is what determines the bonus. A player holding both a Poor and a
# Mythril AP Crystal will burn the Poor one first unless they've already
# used it elsewhere — same "keep your best for later" logic that already
# governs pelts/tusks.
CRYSTAL_TYPES = ["AP Crystal", "HP Crystal", "Defence Crystal", "ATK Crystal"]

# Which Equipment field each crystal feeds. "atk" is special-cased to set
# both atk_min and atk_max to the same value (matches Tiger Fang's shape).
CRYSTAL_FIELD = {
    "AP Crystal":      "max_ap_bonus",
    "HP Crystal":       "max_hp",
    "Defence Crystal":  "defence",
    "ATK Crystal":      "atk",
}

# Linear per-tier value: base_unit * (tier_index + 1). Written out explicitly
# (rather than computed at runtime) to match the hand-authored style of
# every other *_STATS table in this file — easy to eyeball and retune.
CRYSTAL_RARITY_VALUE = {
    "AP Crystal":       {"poor": 1, "normal": 2, "uncommon": 3, "rare": 4, "epic": 5, "legendary": 6, "mythril": 7},
    "HP Crystal":       {"poor": 5, "normal": 10, "uncommon": 15, "rare": 20, "epic": 25, "legendary": 30, "mythril": 35},
    "Defence Crystal":  {"poor": 1, "normal": 2, "uncommon": 3, "rare": 4, "epic": 5, "legendary": 6, "mythril": 7},
    "ATK Crystal":      {"poor": 1, "normal": 2, "uncommon": 3, "rare": 4, "epic": 5, "legendary": 6, "mythril": 7},
}


def _lowest_rarity_copy(warrior, comp_name):
    """
    Preview which specific copy of a component would be consumed by
    _consume_components (which always takes the lowest rarity first).
    Used so the crafting preview/confirmation can show the crystal bonus
    the player will ACTUALLY get, matching what gets consumed exactly.
    Returns the item, or None if the player has none.
    """
    matching = _all_matching_items(warrior, comp_name)
    if not matching:
        return None
    matching.sort(key=lambda it: RARITY_ORDER.index(getattr(it, "rarity", "normal"))
                  if getattr(it, "rarity", "normal") in RARITY_ORDER else 0)
    return matching[0]


def _recipe_crystal_bonus(warrior, recipe):
    """
    Returns (field, value) for the crystal component this recipe needs,
    sized to whichever specific copy would actually be consumed. (None, 0)
    if this recipe doesn't use a crystal, or the player doesn't have one yet.
    """
    for comp_name in recipe["components"]:
        if comp_name in CRYSTAL_TYPES:
            copy = _lowest_rarity_copy(warrior, comp_name)
            if copy is None:
                return (CRYSTAL_FIELD[comp_name], 0)
            rarity = getattr(copy, "rarity", "normal")
            value = CRYSTAL_RARITY_VALUE[comp_name].get(rarity, 0)
            return (CRYSTAL_FIELD[comp_name], value)
    return (None, 0)


# ============================================================
# CRAFTED EQUIPMENT — Wolf-Hide Set
# ============================================================
#
# v0.7.17 REDESIGN — Nathan's call. Crafted gear now SCALES with the rarity
# of the Cured Pelt used to make it, rather than having fixed stats with a
# gold discount for better input. Reasoning: fixed output made curing a
# rare pelt for a recipe a waste (you'd get the same Hood as a Poor pelt
# would buy). Now rarity matters everywhere a pelt goes — socket
# reinforcement (already rarity-scaled) AND named gear pieces.
#
# Recipe format:
#     "atk_min"/"atk_max"/"defence"/"max_hp": the piece's stats at NORMAL
#         rarity input — the baseline the scaling multiplier applies to.
#     "gold_cost": base cost at Normal rarity input.
#     "components": {"Cured Wolf Pelt": 1, "Javelina Tusk": 1}
#
# The crafting rarity is whichever tier the player has ENOUGH of every
# required component at (same "highest common tier" logic as before,
# see _highest_input_rarity) — it now scales BOTH the output stats
# (CRAFT_RARITY_STAT_MULTIPLIER) and the gold cost
# (CRAFT_RARITY_COST_MULTIPLIER, which goes UP not down: better output
# costs more). Set-bonus thresholds (2pc/3pc/4pc) are untouched by this —
# those stay flat regardless of the rarity of the pieces worn.
#
# Non-pelt components (Javelina Tusk, Soul Pendant) don't drive rarity on
# their own high side — a recipe needing 1 Cured Pelt + 1 Tusk is scaled
# off whichever tier the player has enough of BOTH at, same as before.

WOLF_HIDE_RECIPES = {
    "Wolf-Hide Hood": {
        "slot":       "helm",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    1,
        "max_hp":     3,
        "set":        "wolf_hide",
        "components": {"Cured Wolf Pelt": 1, "AP Crystal": 1},
        "gold_cost":  15,
        "flavor":     "A snug hood cut from the pelt and lined with sinew. A faint crystal glow hums under the brow-band.",
    },
    "Wolf-Hide Cloak": {
        "slot":       "cape",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    1,
        "max_hp":     4,
        "set":        "wolf_hide",
        "components": {"Cured Wolf Pelt": 1, "HP Crystal": 1},
        "gold_cost":  20,
        "flavor":     "Heavy across the shoulders. Sheds the cold and most casual blades — a stitched-in crystal keeps the wearer standing.",
    },
    "Wolf-Hide Jerkin": {
        "slot":       "armor",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    2,
        "max_hp":     5,
        "set":        "wolf_hide",
        "components": {"Cured Wolf Pelt": 2},
        "gold_cost":  25,
        "flavor":     "Two pelts stitched into a layered jerkin. Lighter than mail, warmer than wool.",
    },
    "Wolf-Tooth Charm": {
        "slot":       "accessory",
        "atk_min":    1,
        "atk_max":    1,
        "defence":    0,
        "max_hp":     2,
        "set":        "wolf_hide",
        "components": {"Cured Wolf Pelt": 1, "Javelina Tusk": 1},
        "gold_cost":  22,
        "flavor":     "A wolf's tooth bound in tusk-ivory and pelt-strap. Hangs heavy at the throat.",
    },
}

# Names of all Wolf-Hide pieces (for set-detection)
WOLF_HIDE_PIECE_NAMES = set(WOLF_HIDE_RECIPES.keys())


# ============================================================
# CRAFTED EQUIPMENT — Dire Wolf Set (v0.6.16)
# ============================================================
#
# Tier-2 crafted set. Made from Dire Wolf Pelts (and a Soul Pendant for
# the accessory). Each piece is Wolf-Hide +1 DEF, +1 HP. Set bonuses are
# Wolf-Hide +3 HP per tier, +1 AP at 3pc tier, +1 ATK and +1 DEF at 4pc.
#
# 4-piece passive APEX PREDATOR: +10% basic attack damage AND 5% lifesteal
# on basic attacks (heal for 5% of damage dealt, minimum 1 if any damage
# landed). Apex Predator is the dire wolf's healing-special made player-
# facing — the pack hunts to feed, the alpha bleeds the wound and drinks.
#
# Compared to Wolf-Hide's Pack Hunter (bleed proc), Apex Predator is more
# sustain-oriented — every basic attack heals a small amount. Strong in
# long fights against bulky enemies, weaker in burst situations.
#
# Like Wolf-Hide, this set CANNOT be worn alongside Wolf-Hide (shares
# helm/cape/armor/accessory slots). Choosing between them is the commit.

DIRE_WOLF_RECIPES = {
    "Dire Wolf Hood": {
        "slot":       "helm",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    2,
        "max_hp":     4,
        "set":        "dire_wolf",
        "components": {"Cured Dire Wolf Pelt": 1, "AP Crystal": 1},
        "gold_cost":  20,
        "flavor":     "A heavy hood crowned with the alpha's skull-plate. Eyes peer out from a snarl frozen in death — a crystal set behind them still pulses faintly.",
    },
    "Dire Wolf Cloak": {
        "slot":       "cape",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    2,
        "max_hp":     5,
        "set":        "dire_wolf",
        "components": {"Cured Dire Wolf Pelt": 1, "HP Crystal": 1},
        "gold_cost":  25,
        "flavor":     "The full hide draped across both shoulders. Even the cold remembers what it was — a crystal woven into the lining keeps the wearer's heart steady.",
    },
    "Dire Wolf Jerkin": {
        "slot":       "armor",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    3,
        "max_hp":     6,
        "set":        "dire_wolf",
        "components": {"Cured Dire Wolf Pelt": 2},
        "gold_cost":  30,
        "flavor":     "Two dire pelts layered and reinforced. The seams alone could turn a blade.",
    },
    "Dire Wolf Talisman": {
        "slot":       "accessory",
        "atk_min":    1,
        "atk_max":    1,
        "defence":    0,
        "max_hp":     3,
        "set":        "dire_wolf",
        "components": {"Cured Dire Wolf Pelt": 1, "Soul Pendant": 1},
        "gold_cost":  27,
        "flavor":     "A soul-bound pendant wrapped in dire wolf hide. The pendant hums; the hide remembers the hunt.",
    },
}

# Names of all Dire Wolf pieces (for set-detection)
DIRE_WOLF_PIECE_NAMES = set(DIRE_WOLF_RECIPES.keys())

# Combined catalog so the recipe menu can iterate both sets cleanly
ALL_RECIPES = {}
ALL_RECIPES.update(WOLF_HIDE_RECIPES)
ALL_RECIPES.update(DIRE_WOLF_RECIPES)

# --------------------------------------------------------
# Sharpened Tusk — upgrade a raw Javelina Tusk at the crafter
# Cost: 1 Javelina Tusk + 15 gold. Output inherits the tusk's rarity.
# --------------------------------------------------------
TUSK_RECIPES = {
    "Sharpened Tusk": {
        "label":      "Sharpened Tusk  (accessory — bleed + atk bonus)",
        "components": {"Javelina Tusk": 1},
        "gold_cost":  15,
        "result":     "Sharpened Tusk",
        "flavour":    "The crafter hones the tusk to a razor edge. It bites deeper now.",
    },
}
ALL_RECIPES.update(TUSK_RECIPES)


# v0.7.17: full 7-tier order — was truncated to poor/normal/uncommon/rare
# back when this only drove a gold discount. Now it also drives the
# crafted piece's stat scaling and rarity (see CRAFT_RARITY_STAT_MULTIPLIER
# below), so it needs to recognize epic/legendary/mythril cured pelts too.
RARITY_ORDER = ["poor", "normal", "uncommon", "rare", "epic", "legendary", "mythril"]

# v0.7.17: crafted Wolf-Hide/Dire Wolf piece stats scale with the rarity of
# the Cured Pelt used. Recipe stat fields (atk/defence/max_hp) are the
# Normal-rarity baseline; this multiplier scales them up or down from there.
# Tunable — this is a first-pass curve, not a locked balance decision.
CRAFT_RARITY_STAT_MULTIPLIER = {
    "poor":      0.6,
    "normal":    1.0,
    "uncommon":  1.3,
    "rare":      1.6,
    "epic":      2.0,
    "legendary": 2.5,
    "mythril":   3.2,
    "mythril_plus": 4.0,
}

# v0.7.17: gold cost multiplier — climbs FASTER than the stat curve above.
# Nathan's call: better output should cost meaningfully more, not just a
# little more — this is the inverse of the old discount-for-rarity model.
CRAFT_RARITY_COST_MULTIPLIER = {
    "poor":      0.5,
    "normal":    1.0,
    "uncommon":  1.5,
    "rare":      2.25,
    "epic":      3.5,
    "legendary": 5.5,
    "mythril":   9.0,
    "mythril_plus": 14.0,
}


def _scale_craft_stat(base_value, rarity):
    """Scale a recipe's Normal-rarity baseline stat to the given rarity.
    0 stays 0 (no bonus to invent). Nonzero floors at 1 in its own sign."""
    if base_value == 0:
        return 0
    mult = CRAFT_RARITY_STAT_MULTIPLIER.get(rarity, 1.0)
    scaled = round(base_value * mult)
    return max(1, scaled) if base_value > 0 else min(-1, scaled)


def _scale_craft_cost(base_cost, rarity):
    """Scale a recipe's Normal-rarity base gold cost to the given rarity."""
    mult = CRAFT_RARITY_COST_MULTIPLIER.get(rarity, 1.0)
    return max(1, round(base_cost * mult))


# ============================================================
# HELPERS — small wrappers around main's console helpers
# ============================================================

def _wrap(text):
    """Use main's wrap helper if available, fall back to identity."""
    import sys
    main = sys.modules.get("__main__")
    if main and hasattr(main, "wrap"):
        return main.wrap(text)
    return text


def _clear_screen():
    import sys
    main = sys.modules.get("__main__")
    if main and hasattr(main, "clear_screen"):
        main.clear_screen()
    else:
        print("\n" * 2)


def make_crafted_item(name, recipe, rarity="normal", crystal_bonus=None):
    """
    Build a shared.Equipment instance from a recipe dict. Imported lazily
    to avoid a circular import at module load time.

    v0.7.17: stats now scale with `rarity` (the Cured Pelt tier used —
    see _highest_input_rarity / CRAFT_RARITY_STAT_MULTIPLIER) instead of
    being fixed. The output item's own rarity is stamped to match, so a
    Legendary-cured Hood actually displays and plays as Legendary gear.

    `crystal_bonus`: optional (field, value) tuple — see
    _recipe_crystal_bonus. Applied ON TOP of the pelt-scaled baseline,
    NOT itself re-scaled by `rarity` — the crystal's own rarity already
    determined `value` via CRYSTAL_RARITY_VALUE's linear curve, which is
    intentionally separate from the pelt's CRAFT_RARITY_STAT_MULTIPLIER.

    Public API (v0.6.16) — also callable from the debug menu's loot grant
    flow to give crafted set pieces directly without going through the
    crafter UI. Debug callers that don't pass `rarity`/`crystal_bonus` get
    the old Normal-baseline, no-crystal behavior.
    """
    from shared import Equipment
    kwargs = dict(
        name         = name,
        slot         = recipe["slot"],
        rarity       = rarity,
        atk_min      = _scale_craft_stat(recipe["atk_min"], rarity),
        atk_max      = _scale_craft_stat(recipe["atk_max"], rarity),
        defence      = _scale_craft_stat(recipe["defence"], rarity),
        max_hp       = _scale_craft_stat(recipe["max_hp"], rarity),
        max_ap_bonus = _scale_craft_stat(recipe.get("max_ap_bonus", 0), rarity),
    )
    if crystal_bonus:
        field, value = crystal_bonus
        if value:
            if field == "atk":
                kwargs["atk_min"] += value
                kwargs["atk_max"] += value
            elif field:
                kwargs[field] = kwargs.get(field, 0) + value
    return Equipment(**kwargs)


# Internal alias kept so existing calls inside crafter.py don't break.
# Can be removed if you grep and replace all _make_equipment( -> make_crafted_item(
_make_equipment = make_crafted_item


# ============================================================
# STOCK GENERATION
# ============================================================

def _roll_wildcard_rarity():
    """Weighted pick: poor 40 / uncommon 40 / rare 20.
    Difficulty adjusts the ceiling (Nathan's table):
      Easy (noob):     rare re-rolls down to uncommon — uncommon is the ceiling.
      Normal (warrior): unchanged — rare is the ceiling.
      Champion:        independent CHAMPION_EPIC_CHANCE (20%) roll bumps
                        whatever tier was picked up to epic — mirrors the
                        merchant's existing independent "20% chance for an
                        epic weapon variant on Champion" (see
                        MERCHANT_VARIANT_CHANCE usage in merchant.py) rather
                        than being nested inside the rare branch. Special
                        enough to feel like a find, common enough that it
                        isn't a myth.  — v0.7.17
    """
    import sys
    _main = sys.modules.get("__main__")
    _diff = getattr(_main, "DIFFICULTY", "warrior") if _main else "warrior"

    total = sum(w for _, w in WILDCARD_RARITY_WEIGHTS)
    r = random.randint(1, total)
    cum = 0
    picked = "poor"
    for rarity, weight in WILDCARD_RARITY_WEIGHTS:
        cum += weight
        if r <= cum:
            picked = rarity
            break

    if picked == "rare" and _diff == "noob":
        picked = "uncommon"

    if _diff == "champion" and random.random() < CHAMPION_EPIC_CHANCE:
        picked = "epic"

    return picked


def generate_crafter_stock():
    """
    Build a fresh stock dict for one crafter visit.

    Each component type INDEPENDENTLY rolls CRAFTER_ITEM_APPEAR_CHANCE to
    show up at all this visit (v0.7.17 — nothing's guaranteed). When it
    does appear, it gets:
      - a guaranteed Normal-rarity listing (stock = 2)
      - one wildcard listing at Poor/Uncommon/Rare/(Epic on Champion) — 2

    Returns:
        {
          "components": {
            "Cured Wolf Pelt": [
              {"rarity": "normal", "price": 18, "stock": 2, "sold": 0},
              {"rarity": "uncommon", "price": 35, "stock": 2, "sold": 0},
            ],
            "Fire Sac": [],   # rolled absent this visit
            ...
          },
        }
    """
    stock = {"components": {}}
    for comp_name in COMPONENT_TYPES:
        # v0.7.18: guaranteed components skip the appearance roll entirely —
        # see ALWAYS_STOCKED_COMPONENTS above for reasoning.
        if (comp_name not in ALWAYS_STOCKED_COMPONENTS
                and random.random() >= CRAFTER_ITEM_APPEAR_CHANCE):
            stock["components"][comp_name] = []  # absent this visit
            continue

        listings = []
        # Guaranteed Normal listing
        listings.append({
            "rarity": "normal",
            "price":  COMPONENT_PRICES["normal"],
            "stock":  COMPONENT_STOCK_PER_VARIANT,
            "sold":   0,
        })
        # Wildcard listing
        wildcard = _roll_wildcard_rarity()
        listings.append({
            "rarity": wildcard,
            "price":  COMPONENT_PRICES[wildcard],
            "stock":  COMPONENT_STOCK_PER_VARIANT,
            "sold":   0,
        })
        stock["components"][comp_name] = listings


    return stock


# ============================================================
# COMPONENT BUYING
# ============================================================

def _make_component(comp_name, rarity, overrides=None):
    """
    Build a component Equipment instance. Components are normal drop items
    (Wolf Pelt etc.) — we mirror the make_loot() construction over in main,
    but simplified since the crafter doesn't deal with effects, just stats.

    Rarity-scaled stat tables (pelts, sacs, tusks, pendants) are imported
    directly from equipment.py where they're defined. (v0.7.19: this used
    to reach for them via sys.modules["__main__"] instead — see the bug-fix
    note below the pelt branches for why that never actually worked.)

    overrides: optional dict of stat values that take priority over the
    table lookup — lets formula-driven crafts (e.g. tusk sharpening)
    supply computed numbers without needing every possible rarity/tier
    pre-populated in the static table. Currently used by Sharpened Tusk;
    safe to reuse the same pattern for future "+"-tier crafts on other items.
    """
    from shared import Equipment

    # v0.7.19 BUG FIX: this whole block used to gate on
    # `main and hasattr(main, "WOLF_PELT_STATS")` (and the same pattern for
    # every Sac and Soul Pendant below). WOLF_PELT_STATS etc. only ever
    # existed as module-level names in equipment.py — nothing ever copied
    # them onto __main__ (unlike DIFFICULTY, which genuinely IS a main-script
    # global, so that half of the pattern happened to work elsewhere and
    # masked this one). hasattr(main, "WOLF_PELT_STATS") was always False,
    # so EVERY purchase of Wolf Pelt/Dire Wolf Pelt/Poison Sac/Fire Sac/Acid
    # Sac/Soul Pendant from the crafter's component stock silently fell
    # through to the "bare Equipment, no stats" fallback at the bottom of
    # this function — wrong slot, zero stats, and (for pelts) not even
    # recognized as curable/socketable since the name didn't match.  Fixed
    # by importing the tables directly from equipment.py, same as Javelina
    # Tusk already does a few lines down (that one was never broken).

    # v0.7.19: Crafter stock sells pelts PRE-CURED (slot "material", same
    # shape _cure_pelt() produces) — no separate curing fee on top of the
    # purchase price. Raw pelts still exist as Arena drops and still need
    # the Cure Pelts service; this only changes what the crafter's own
    # component stock hands over.
    if comp_name == "Cured Wolf Pelt":
        from equipment import WOLF_PELT_STATS
        stats = WOLF_PELT_STATS[rarity]
        return Equipment(name="Cured Wolf Pelt", slot="material", rarity=rarity,
                         defence=stats["defence"], max_hp=stats["max_hp"],
                         flavour="Cured and stiffened — ready to reinforce a piece of armor or feed a recipe.")
    if comp_name == "Cured Dire Wolf Pelt":
        from equipment import DIRE_WOLF_PELT_STATS
        stats = DIRE_WOLF_PELT_STATS[rarity]
        return Equipment(name="Cured Dire Wolf Pelt", slot="material", rarity=rarity,
                         defence=stats["defence"], max_hp=stats["max_hp"],
                         flavour="Cured and stiffened — ready to reinforce a piece of armor or feed a recipe.")

    # v0.7.17: Reinforcement crystals — non-wearable, rarity-scaled recipe
    # ingredients (linear per-tier value, see CRYSTAL_RARITY_VALUE above).
    if comp_name in CRYSTAL_TYPES:
        value = CRYSTAL_RARITY_VALUE[comp_name].get(rarity, CRYSTAL_RARITY_VALUE[comp_name]["normal"])
        field = CRYSTAL_FIELD[comp_name]
        kwargs = dict(name=comp_name, slot="material", rarity=rarity,
                      flavour=f"A raw {comp_name.lower()} — feeds a recipe, doesn't hold together worn on its own.")
        if field == "atk":
            kwargs["atk_min"] = value
            kwargs["atk_max"] = value
        else:
            kwargs[field] = value
        return Equipment(**kwargs)

    # Sacs (accessory slot)
    if comp_name == "Poison Sac":
        from equipment import POISON_SAC_STATS
        s = POISON_SAC_STATS[rarity]
        return Equipment(name="Poison Sac", slot="accessory", rarity=rarity,
                         element="poison", element_damage=s[0],
                         element_turns=s[1], element_max_dots=s[3])
    if comp_name == "Fire Sac":
        from equipment import FIRE_SAC_STATS
        s = FIRE_SAC_STATS[rarity]
        return Equipment(name="Fire Sac", slot="accessory", rarity=rarity,
                         element="fire", element_damage=s[0],
                         element_turns=s[1], element_max_dots=s[3])
    if comp_name == "Acid Sac":
        from equipment import ACID_SAC_STATS
        s = ACID_SAC_STATS[rarity]
        return Equipment(name="Acid Sac", slot="accessory", rarity=rarity,
                         element="acid", element_damage=s[0],
                         element_turns=s[1], element_restore=s[2],
                         element_max_dots=s[3], element_erosion=s[4])

    # Javelina Tusk (accessory)
    if comp_name == "Javelina Tusk":
        from equipment import JAVELINA_TUSK_STATS
        s = JAVELINA_TUSK_STATS[rarity]
        return Equipment(name="Javelina Tusk", slot="accessory", rarity=rarity,
                         bleed_turns=s["bleed_turns"],
                         bleed_dmg_min=s["bleed_dmg_min"],
                         bleed_dmg_max=s["bleed_dmg_max"])

    # Sharpened Tusk (accessory — crafter upgrade from Javelina Tusk)
    if comp_name == "Sharpened Tusk":
        from equipment import SHARPENED_TUSK_STATS
        s = dict(SHARPENED_TUSK_STATS.get(rarity, SHARPENED_TUSK_STATS["mythril"]))
        if overrides:
            s.update(overrides)
        return Equipment(name="Sharpened Tusk", slot="accessory", rarity=rarity,
                         atk_bonus=s["atk_bonus"],
                         bleed_turns=s["bleed_turns"],
                         bleed_dmg_min=s["bleed_dmg_min"],
                         bleed_dmg_max=s["bleed_dmg_max"],
                         flavour="A tusk honed to a razor edge by the crafter. Bites deep and bleeds long.")

    # Soul Pendant (accessory)
    if comp_name == "Soul Pendant":
        from equipment import SOUL_PENDANT_STATS
        s = SOUL_PENDANT_STATS[rarity]
        return Equipment(name="Soul Pendant", slot="accessory", rarity=rarity,
                         drain_bonus=s["drain_bonus"],
                         drain_heal_min=s["drain_heal_min"],
                         drain_heal_max=s["drain_heal_max"])

    # Fallback: bare Equipment with no stats (shouldn't hit in normal play)
    return Equipment(name=comp_name, slot="accessory", rarity=rarity)


# ============================================================
# RECIPE EXECUTION
# ============================================================

def _all_matching_items(warrior, name):
    """
    v0.7.13: Every component-consuming path (affordability check, rarity
    check, actual consumption) now looks at BOTH the bag AND currently
    equipped gear. Previously a player wearing their only Wolf Pelt had
    to manually unequip it before the crafter would even recognize they
    had one — annoying busywork with no real purpose. Consumption still
    prefers the lowest-rarity copy first; if that copy happens to be
    equipped, _consume_components unequips it properly before removing it.
    """
    items = [it for it in warrior.inventory if getattr(it, "name", "") == name]
    items += [it for it in warrior.equipment.values()
              if it is not None and getattr(it, "name", "") == name]
    return items


def _count_inventory(warrior, name):
    """Count how many items with this name the warrior has — bag AND equipped."""
    return len(_all_matching_items(warrior, name))


def _highest_input_rarity(warrior, recipe):
    """
    For the components this recipe needs, find the HIGHEST rarity the player
    has enough of in inventory. That determines the crafted piece's
    PELT-driven stat scaling and gold cost (see CRAFT_RARITY_STAT_MULTIPLIER).

    v0.7.17: Reinforcement crystals (CRYSTAL_TYPES) DO have real rarity
    tiers now, but they're still skipped here — their bonus is tracked
    completely independently via _recipe_crystal_bonus, on its own linear
    curve (CRYSTAL_RARITY_VALUE), rather than folding into this "highest
    common tier" calculation. Reasoning: a Poor pelt + a Mythril crystal
    should still get the Mythril crystal's full bonus rather than having
    the pelt drag it down (or vice versa) — the two ingredients scale the
    piece in genuinely separate ways, so they're kept on separate tracks.
    _can_afford_recipe's quantity check still requires the crystal be
    present — this only affects which rarity drives the PELT side.

    Returns rarity string, or None if the player doesn't have enough components.
    """
    # For each rarity tier (high to low), check whether the player has
    # enough of EVERY required (non-crystal) component at that tier or higher.
    #
    # v0.7.19: check mythril_plus first — cured pelts can now sit at this
    # tier after the curing rarity bump, and it's above the standard ladder.
    extended_order = RARITY_ORDER + ["mythril_plus"]
    for tier in reversed(extended_order):  # mythril_plus down to poor
        ok = True
        for comp_name, needed in recipe["components"].items():
            if comp_name in CRYSTAL_TYPES:
                continue
            # Count items of this name at this tier OR HIGHER — bag + equipped
            higher_tiers = extended_order[extended_order.index(tier):]
            have = sum(1 for it in _all_matching_items(warrior, comp_name)
                       if getattr(it, "rarity", "normal") in higher_tiers)
            if have < needed:
                ok = False
                break
        if ok:
            return tier
    return None


def _can_afford_recipe(warrior, recipe):
    """
    Returns (can_craft: bool, missing_components: list[str], craft_rarity: str|None, cost: int)

    v0.7.17: cost now scales UP from the recipe's base gold_cost using
    CRAFT_RARITY_COST_MULTIPLIER, driven by the highest rarity tier the
    player has enough of every required component at (same tier that also
    determines the output stats — see make_crafted_item).
    """
    missing = []
    for comp_name, needed in recipe["components"].items():
        have = _count_inventory(warrior, comp_name)
        if have < needed:
            missing.append(f"{needed - have}x {comp_name}")
    if missing:
        return (False, missing, None, _scale_craft_cost(recipe["gold_cost"], "poor"))

    craft_rarity = _highest_input_rarity(warrior, recipe)
    cost = _scale_craft_cost(recipe["gold_cost"], craft_rarity or "poor")
    return (warrior.gold >= cost, [], craft_rarity, cost)


def _consume_components(warrior, recipe, prefer_rarity):
    """
    Remove the recipe's required components from inventory OR equipped
    slots.

    v0.7.19: When a recipe needs pelts and the player has more available
    than required at mixed rarities, the player is asked which ones to
    use rather than the system choosing automatically. If all available
    copies are the same rarity, or there are exactly enough, no prompt
    is shown.

    v0.7.13: If the matching copy happens to be currently equipped, it's
    unequipped properly first (via equipment.unequip_item so stat bonuses
    reverse cleanly) rather than just stripped out from under the hero.
    """
    from equipment import unequip_item

    extended = RARITY_ORDER + ["mythril_plus"]

    for comp_name, needed in recipe["components"].items():
        matching = _all_matching_items(warrior, comp_name)
        matching.sort(key=lambda it: extended.index(getattr(it, "rarity", "normal"))
                      if getattr(it, "rarity", "normal") in extended else 0,
                      reverse=True)   # highest rarity first (default)

        # --- Player choice: only when there are MORE items than needed
        # AND they differ in rarity (otherwise there's nothing to choose) ---
        unique_rarities = set(getattr(it, "rarity", "normal") for it in matching)
        if len(matching) > needed and len(unique_rarities) > 1:
            chosen = _pick_components(matching, comp_name, needed, extended)
            if chosen is not None:
                matching = chosen  # player's selection replaces the auto-sort

        for _ in range(needed):
            item = matching.pop(0)
            is_equipped = any(eq_item is item for eq_item in warrior.equipment.values())
            if is_equipped:
                unequip_item(warrior, item)  # reverses stats, moves item into inventory
            if item in warrior.inventory:
                warrior.inventory.remove(item)


def _pick_components(available, comp_name, needed, extended):
    """
    Let the player choose which copies of a component to consume.
    Returns the chosen items in a list, or None to fall through to
    the default (highest-first) behavior.
    """
    print()
    print(_wrap(
        f"  You have {len(available)} {comp_name}(s) at different qualities "
        f"and need {needed}. Which do you want to use?"
    ))
    print()
    for i, it in enumerate(available):
        rarity = getattr(it, "rarity", "normal")
        label = rarity.replace("_", " ").title()
        print(f"    {i+1}) {label} {comp_name}")
    print()
    if needed == 1:
        print(_wrap(f"  Pick one (1-{len(available)}), or press Enter for best:"))
    else:
        print(_wrap(
            f"  Pick {needed} — enter numbers separated by commas "
            f"(e.g. 1,3), or press Enter for best:"
        ))
    raw = input("  > ").strip()
    if not raw:
        return None  # default behavior

    try:
        indices = [int(x.strip()) - 1 for x in raw.split(",")]
        if len(indices) != needed:
            print(_wrap(f"  Need exactly {needed} — using best available."))
            return None
        if any(i < 0 or i >= len(available) for i in indices):
            print(_wrap("  Invalid selection — using best available."))
            return None
        if len(set(indices)) != len(indices):
            print(_wrap("  Duplicate selection — using best available."))
            return None
        return [available[i] for i in indices]
    except ValueError:
        print(_wrap("  Couldn't read that — using best available."))
        return None


def _check_set_completion_titles(warrior, just_crafted_name):
    """
    v0.6.18: After a successful craft, check whether the player has now
    completed a full crafted set (Wolf-Hide or Dire Wolf — 4 pieces each).
    If so, award the matching achievement title for the +250 score bonus.

    Tracking is per-run on warrior._pieces_crafted_this_run so that swapping
    or selling a crafted piece later doesn't strip the achievement.
    """
    # Initialise per-run tracker on first craft of the run
    if not hasattr(warrior, "_pieces_crafted_this_run"):
        warrior._pieces_crafted_this_run = set()
    warrior._pieces_crafted_this_run.add(just_crafted_name)

    # Make sure warrior.titles exists (it should already, but guard anyway)
    if not hasattr(warrior, "titles"):
        warrior.titles = set()

    crafted = warrior._pieces_crafted_this_run

    # Wolf-Hide set complete?
    if WOLF_HIDE_PIECE_NAMES.issubset(crafted) and "wolf_hide_crafter" not in warrior.titles:
        warrior.titles.add("wolf_hide_crafter")
        print()
        print(_wrap("  🏅 ACHIEVEMENT UNLOCKED: Wolf-Hide Crafter"))
        print(_wrap("     You crafted every piece of the Wolf-Hide set."))
        print(_wrap("     (+250 end-of-run score)"))

    # Dire Wolf set complete?
    if DIRE_WOLF_PIECE_NAMES.issubset(crafted) and "dire_wolf_crafter" not in warrior.titles:
        warrior.titles.add("dire_wolf_crafter")
        print()
        print(_wrap("  🏅 ACHIEVEMENT UNLOCKED: Dire Wolf Crafter"))
        print(_wrap("     You crafted every piece of the Dire Wolf set."))
        print(_wrap("     (+250 end-of-run score)"))


def _crystal_field_label(field):
    return {"max_ap_bonus": "Max AP", "max_hp": "HP", "defence": "DEF", "atk": "ATK"}.get(field, field)


def _craft_recipe(warrior, recipe_name, recipe):
    """Execute one craft. Assumes affordability has already been checked."""
    can, missing, craft_rarity, cost = _can_afford_recipe(warrior, recipe)
    if not can:
        if missing:
            print(_wrap(f"  You need more: {', '.join(missing)}"))
        else:
            print(_wrap(f"  You can't afford it. Cost: {cost}g, you have {warrior.gold}g."))
        input("\n  Press Enter...")
        return

    # v0.7.13: Warn if any component that will be consumed is currently
    # equipped — crafting will unequip it automatically, but the player
    # should see that coming rather than be surprised mid-fight later.
    equipped_names_used = set()
    for comp_name in recipe["components"]:
        for it in warrior.equipment.values():
            if it is not None and getattr(it, "name", "") == comp_name:
                equipped_names_used.add(comp_name)

    # v0.7.17: preview which specific crystal will be consumed and what it
    # grants — the player should see this BEFORE committing gold, since
    # it's determined by whichever copy they happen to have (lowest
    # rarity first, same rule as every other component).
    crystal_field, crystal_value = _recipe_crystal_bonus(warrior, recipe)

    print()
    print(_wrap(
        f"  Craft {recipe_name} at {craft_rarity.title()} rarity for {cost}g?"
    ))
    if crystal_field and crystal_value:
        print(_wrap(f"  💎 Crystal reinforcement: +{crystal_value} {_crystal_field_label(crystal_field)}"))
    if equipped_names_used:
        print(_wrap(
            f"  ⚠️  Currently equipped and will be unequipped for this craft: "
            f"{', '.join(sorted(equipped_names_used))}"
        ))
    confirm = input("  Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        return

    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, cost)  # v0.7.18: tracks total_gold_spent
    _consume_components(warrior, recipe, craft_rarity)

    crafted = _make_equipment(recipe_name, recipe, rarity=craft_rarity,
                               crystal_bonus=(crystal_field, crystal_value))
    warrior.inventory.append(crafted)

    print()
    print(_wrap(f"  ✅ Crafted: {craft_rarity.title()} {recipe_name}"))
    print(_wrap(f"     {recipe['flavor']}"))

    # v0.6.18: Check if this craft completed a 4-piece set
    _check_set_completion_titles(warrior, recipe_name)

    # v0.7.13: Offer to equip immediately — no more crafting a piece and
    # then having to separately dig through the equipment menu to wear it.
    from equipment import equip_item
    current = warrior.equipment.get(crafted.slot)
    print()
    if current is not None:
        print(_wrap(f"  Equip {recipe_name} now? It'll swap out {current.short_label()}. (y/n): "), end="")
    else:
        print(_wrap(f"  Equip {recipe_name} now? (y/n): "), end="")
    equip_now = input("").strip().lower()
    if equip_now == "y":
        equip_item(warrior, crafted)

    input("\n  Press Enter...")


# ============================================================
# UI — COMPONENT STOCK MENU
# ============================================================

def _buy_component(warrior, stock, comp_name, listing_idx):
    listing = stock["components"][comp_name][listing_idx]
    if listing["sold"] >= listing["stock"]:
        return
    if warrior.gold < listing["price"]:
        print(_wrap(f"  You can't afford it. ({listing['price']}g, you have {warrior.gold}g)"))
        input("\n  Press Enter...")
        return

    rarity_word = listing["rarity"].title()
    print()
    print(_wrap(f"  Buy {rarity_word} {comp_name} for {listing['price']}g?"))
    confirm = input("  Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        return

    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, listing["price"])  # v0.7.18: tracks total_gold_spent
    listing["sold"] += 1
    item = _make_component(comp_name, listing["rarity"])
    warrior.inventory.append(item)
    print()
    print(_wrap(f"  ✅ Bought: {rarity_word} {comp_name}"))
    input("\n  Press Enter...")


# v0.7.13: Component categories for the tabbed stock menu — was one flat
# list of 14 lines the player had to scroll through every visit.
COMPONENT_CATEGORIES = [
    ("🐺 Wolf-Hide Materials", ["Cured Wolf Pelt"]),
    ("🐗 Dire Wolf Materials", ["Cured Dire Wolf Pelt"]),
    # v0.7.18: Nathan's call — Javelina Tusk (javelina drop) and Soul Pendant
    # (Noob Ghost drop) don't belong under wolf categories; both moved here.
    # Renamed from "Elemental Sacs" since it's no longer sacs-only.
    ("☠️  Sacs & Components", ["Poison Sac", "Fire Sac", "Acid Sac", "Javelina Tusk", "Soul Pendant"]),
    ("💎 Reinforcement Crystals", CRYSTAL_TYPES),
]


def _show_component_categories(stock, warrior):
    """v0.7.13: Top-level component menu — pick a category tab instead of
    scrolling one long list. Returns nothing; caller reads input directly."""
    print("=" * 52)
    print(f"  🪡 Crafter — Component Stock   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()
    print(_wrap("  'These are what I can spare today. Every visit's different —"))
    print(_wrap("   what's here is here. Use it or come back tomorrow.'"))
    print()

    for cat_idx, (label, comp_names) in enumerate(COMPONENT_CATEGORIES, start=1):
        avail = sum(
            (li["stock"] - li["sold"])
            for comp_name in comp_names
            for li in stock["components"][comp_name]
        )
        print(f"  {cat_idx}) {label:<28} ({avail} available)")

    tusk_count = len(_tusk_upgrade_candidates(warrior))
    print(f"  {len(COMPONENT_CATEGORIES) + 1}) ⚔️  Tusk Upgrade{'':<15} ({tusk_count} tusk{'s' if tusk_count != 1 else ''} owned)")
    print()
    print("  0) Back to crafter menu")


def _show_component_category_menu(stock, warrior, comp_names):
    """v0.7.13: Scoped component listing — only the component types passed
    in comp_names. Same buy-listing logic as before, just filtered."""
    print("=" * 52)
    print(f"  🪡 Crafter — Component Stock   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1
    any_shown = False
    for comp_name in comp_names:
        listings = stock["components"][comp_name]
        if not listings:
            print(_wrap(f"      ({comp_name} — none in stock today)"))
            continue
        any_shown = True
        for li_idx, li in enumerate(listings):
            rarity_word = li["rarity"].title()
            remaining   = li["stock"] - li["sold"]
            label       = f"{rarity_word} {comp_name}"
            if remaining <= 0:
                print(f"  {idx:>2}) {label:<32}  {li['price']}g   ── SOLD OUT ──")
            elif warrior.gold >= li["price"]:
                print(f"  {idx:>2}) {label:<32}  {li['price']}g   x{remaining}")
            else:
                short = li["price"] - warrior.gold
                print(f"  {idx:>2}) {label:<32}  {li['price']}g   x{remaining}  (need {short} more)")
            actions[str(idx)] = (comp_name, li_idx)
            idx += 1
    if not any_shown:
        print()
        print(_wrap("  Slim pickings — none of this category's materials came in today."))
    print()
    print("  Enter component number to buy, or 0 to go back.")
    return actions


def _tusk_upgrade_candidates(warrior):
    """v0.7.13: All Javelina Tusks available to upgrade — bag + equipped."""
    return _all_matching_items(warrior, "Javelina Tusk")


# Gold cost scales with the INPUT tusk's rarity — sharpening a Mythril
# tusk costs more than sharpening a Poor one. +5g per rarity step.
TUSK_UPGRADE_GOLD_BY_RARITY = {
    "poor": 5, "normal": 10, "uncommon": 15, "rare": 20,
    "epic": 25, "legendary": 30, "mythril": 35,
}


def _upgrade_tusk(warrior, item):
    """
    v0.7.13: Wires up the previously-orphaned TUSK_RECIPES entry. Consumes
    one Javelina Tusk (unequipping it first if worn).

    v0.7.16 rework:
      - Gold cost now scales with the INPUT tusk's rarity (see
        TUSK_UPGRADE_GOLD_BY_RARITY) instead of a flat 15g.
      - Output rarity bumps ONE tier above the consumed tusk (capped via
        the EXTRA_RARITY_TIERS registry — a Mythril tusk becomes the
        item-exclusive "Mythril+" tier instead of just staying Mythril).
      - Bleed turns / bleed damage are computed live: 50% up from the RAW
        Javelina Tusk's own stats at the INPUT rarity, rounded up, min 1.
        So the bleed boost scales with what you fed in, not a fixed table.
      - ATK bonus still comes from SHARPENED_TUSK_STATS at the OUTPUT
        rarity (including the "mythril_plus" entry for the extra tier).
    """
    from equipment import (RARITY_ORDER as _FULL_RARITY_ORDER, JAVELINA_TUSK_STATS,
                            SHARPENED_TUSK_STATS, EXTRA_RARITY_TIERS, scale_bleed_stat)

    recipe = TUSK_RECIPES["Sharpened Tusk"]
    input_rarity = getattr(item, "rarity", "normal")
    rarity_word = input_rarity.title()
    cost = TUSK_UPGRADE_GOLD_BY_RARITY.get(input_rarity, recipe["gold_cost"])

    # Determine output rarity: normally one tier up, but a registered
    # "+" tier (currently only Javelina Tusk → Mythril+) overrides that
    # when the input matches its trigger rarity.
    extra = EXTRA_RARITY_TIERS.get("Javelina Tusk")
    if extra and input_rarity == extra["trigger_rarity"]:
        output_rarity = extra["key"]
        output_word = extra["label"]
    else:
        idx = _FULL_RARITY_ORDER.index(input_rarity) if input_rarity in _FULL_RARITY_ORDER else 1
        output_rarity = _FULL_RARITY_ORDER[min(idx + 1, len(_FULL_RARITY_ORDER) - 1)]
        output_word = output_rarity.title()
    bumped = output_rarity != input_rarity

    # Bleed stats: 50% up from the RAW tusk's own numbers at input rarity.
    raw = JAVELINA_TUSK_STATS.get(input_rarity, JAVELINA_TUSK_STATS["normal"])
    new_bleed_turns   = scale_bleed_stat(raw["bleed_turns"])
    new_bleed_dmg_min = scale_bleed_stat(raw["bleed_dmg_min"])
    new_bleed_dmg_max = max(new_bleed_dmg_min, scale_bleed_stat(raw["bleed_dmg_max"]))

    atk_bonus = SHARPENED_TUSK_STATS.get(output_rarity, SHARPENED_TUSK_STATS["mythril"])["atk_bonus"]

    overrides = {
        "atk_bonus":     atk_bonus,
        "bleed_turns":   new_bleed_turns,
        "bleed_dmg_min": new_bleed_dmg_min,
        "bleed_dmg_max": new_bleed_dmg_max,
    }

    if warrior.gold < cost:
        print(_wrap(f"  You can't afford it. ({cost}g, you have {warrior.gold}g)"))
        input("\n  Press Enter...")
        return

    is_equipped = any(eq_item is item for eq_item in warrior.equipment.values())
    print()
    if bumped:
        print(_wrap(f"  Upgrade {rarity_word} Javelina Tusk into a {output_word} Sharpened Tusk for {cost}g?"))
    else:
        print(_wrap(f"  Upgrade {rarity_word} Javelina Tusk into a {output_word} Sharpened Tusk for {cost}g? (already at max rarity)"))
    print(_wrap(f"     +{atk_bonus} ATK, {new_bleed_turns} turn bleed, {new_bleed_dmg_min}-{new_bleed_dmg_max} dmg"))
    if is_equipped:
        print(_wrap(f"  ⚠️  This tusk is currently EQUIPPED — it will be unequipped and consumed."))
    confirm = input("  Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        return

    from equipment import unequip_item, equip_item
    if is_equipped:
        unequip_item(warrior, item)
    if item in warrior.inventory:
        warrior.inventory.remove(item)
    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, cost)  # v0.7.18: tracks total_gold_spent

    sharpened = _make_component("Sharpened Tusk", output_rarity, overrides=overrides)
    warrior.inventory.append(sharpened)

    print()
    if bumped:
        print(_wrap(f"  ✅ Crafted: {output_word} Sharpened Tusk  (rarity boosted from {rarity_word})"))
    else:
        print(_wrap(f"  ✅ Crafted: {output_word} Sharpened Tusk"))
    print(_wrap(f"     {recipe['flavour']}"))

    current = warrior.equipment.get(sharpened.slot)
    print()
    if current is not None:
        print(_wrap(f"  Equip Sharpened Tusk now? It'll swap out {current.short_label()}. (y/n): "), end="")
    else:
        print(_wrap(f"  Equip Sharpened Tusk now? (y/n): "), end="")
    equip_now = input("").strip().lower()
    if equip_now == "y":
        equip_item(warrior, sharpened)

    input("\n  Press Enter...")


def _tusk_upgrade_loop(warrior):
    """v0.7.13: Component-tab UI for upgrading Javelina Tusk → Sharpened Tusk."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  ⚔️  Tusk Upgrade   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(_wrap(f"  'Bring me a tusk, I'll hone it sharp. Costs more for the "
                    f"finer ones — but the edge gets keener, and the rarity climbs "
                    f"right along with it.'"))
        print()

        equipped_items = set(i for i in warrior.equipment.values() if i is not None)
        candidates = _tusk_upgrade_candidates(warrior)

        if not candidates:
            print("  (You don't have any Javelina Tusks to upgrade.)")
            print()
            input("  Press Enter to go back...")
            return

        from equipment import RARITY_ORDER as _FULL_RARITY_ORDER, EXTRA_RARITY_TIERS
        extra = EXTRA_RARITY_TIERS.get("Javelina Tusk")
        for i, item in enumerate(candidates, start=1):
            in_rarity = getattr(item, "rarity", "normal")
            rarity_word = in_rarity.title()
            row_cost = TUSK_UPGRADE_GOLD_BY_RARITY.get(in_rarity, TUSK_RECIPES["Sharpened Tusk"]["gold_cost"])
            if extra and in_rarity == extra["trigger_rarity"]:
                out_word = extra["label"]
            else:
                idx = _FULL_RARITY_ORDER.index(in_rarity) if in_rarity in _FULL_RARITY_ORDER else 1
                out_rarity = _FULL_RARITY_ORDER[min(idx + 1, len(_FULL_RARITY_ORDER) - 1)]
                out_word = out_rarity.title()
            equipped_tag = " [EQUIPPED]" if item in equipped_items else ""
            print(f"  {i:>2}) {rarity_word} Javelina Tusk{equipped_tag:<12}  → {out_word} Sharpened Tusk  ({row_cost}g)")
        print()
        print("  Enter tusk number to upgrade, or 0 to go back.")
        print("  M) Main menu")

        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(candidates):
            continue

        _upgrade_tusk(warrior, candidates[idx])


def _sell_components_menu(warrior):
    """
    v0.7.13: Sell raw crafting components back to the crafter at half
    price. Mirrors the merchant's _sell_back_menu pattern — also lists
    equipped components (e.g. a Wolf Pelt worn as raw armor), unequipping
    with confirmation before the sale.
    """
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  🪡 Sell Components   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(_wrap(
            "  'Raw materials, half of what I'd charge for them. "
            "Fair's fair — I still have to sort and cure them again.'"
        ))
        print()

        equipped_items = set(i for i in warrior.equipment.values() if i is not None)
        candidates = []
        for item in warrior.inventory:
            if getattr(item, "name", "") in COMPONENT_TYPES:
                candidates.append(item)
        for item in equipped_items:
            if getattr(item, "name", "") in COMPONENT_TYPES and item not in candidates:
                candidates.append(item)

        if not candidates:
            print("  (You don't have any raw components to sell.)")
            print()
            input("  Press Enter to go back...")
            return

        listing = [(item, _component_sell_price(item)) for item in candidates]
        for i, (item, price) in enumerate(listing, start=1):
            rarity_word = getattr(item, "rarity", "normal").title()
            label = f"{rarity_word} {item.name}"
            equipped_tag = " [EQUIPPED]" if item in equipped_items else ""
            print(f"  {i:>2}) {label:<32}{equipped_tag:<12}  +{price}g")
        print()
        print("  Enter item number to sell, or 0 to go back.")
        print("  M) Main menu")

        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(listing):
            continue

        item, price = listing[idx]
        is_equipped = item in equipped_items
        label = f"{getattr(item, 'rarity', 'normal').title()} {item.name}"
        print()
        if is_equipped:
            print(_wrap(
                f"  ⚠️  {label} is currently EQUIPPED. Selling it will unequip "
                f"the piece first — its stat bonuses will be removed."
            ))
        print(f"  Sell {label} for {price}g?")
        confirm = input("  Confirm? (y/n): ").strip().lower()
        if confirm != "y":
            continue

        if is_equipped:
            from equipment import unequip_item
            unequip_item(warrior, item)
        if item in warrior.inventory:
            warrior.inventory.remove(item)
        warrior.gold += price

        print()
        print(_wrap(f"  ✅ Sold {label} for {price}g."))
        input("\n  Press Enter...")


def _component_category_loop(warrior, stock, comp_names):
    """v0.7.13: Inner loop for a single component category tab. Stays here
    until the player backs out to the category picker."""
    while True:
        _clear_screen()
        actions = _show_component_category_menu(stock, warrior, comp_names)
        print("  M) Main menu")
        raw = input("  > ").strip().lower()
        if raw == "0" or raw == "":
            return
        if raw == "m":
            raise _ReturnToCrafterMenu()
        action = actions.get(raw)
        if not action:
            continue
        comp_name, li_idx = action
        _buy_component(warrior, stock, comp_name, li_idx)


def _component_stock_loop(warrior, stock):
    """v0.7.13: Top-level component menu — pick a category tab, then browse
    just that tab's listings. Replaces the old single 14-line scroll."""
    while True:
        _clear_screen()
        _show_component_categories(stock, warrior)
        raw = input("  > ").strip()
        if raw == "0" or raw == "":
            return
        if not raw.isdigit():
            continue
        cat_idx = int(raw) - 1
        if cat_idx == len(COMPONENT_CATEGORIES):   # the Tusk Upgrade tab
            _tusk_upgrade_loop(warrior)
            continue
        if cat_idx < 0 or cat_idx >= len(COMPONENT_CATEGORIES):
            continue
        _, comp_names = COMPONENT_CATEGORIES[cat_idx]
        _component_category_loop(warrior, stock, comp_names)


# ============================================================
# PELT CURING (v0.7.17)
# ============================================================
#
# Raw Wolf Pelt / Dire Wolf Pelt drops ARE wearable as-is (slot "armor") —
# basic, immediate protection, no crafter visit required. Curing is a
# separate, optional upgrade path that unlocks the pelt's BETTER uses:
#   1) Recipe components for the Wolf-Hide / Dire Wolf gear sets — recipes
#      now require the CURED name ("Cured Wolf Pelt" / "Cured Dire Wolf
#      Pelt") and the crafted piece's stats scale with the cured pelt's
#      rarity (see WOLF_HIDE_RECIPES / DIRE_WOLF_RECIPES and
#      CRAFT_RARITY_STAT_MULTIPLIER above). Raw, uncured pelts can no
#      longer feed a recipe directly.
#   2) Socketing — cured pelts are socketable into ARMOR (see
#      SOCKETABLE_INTO_ARMOR below) — a small always-on reinforcement
#      (+DEF, +HP) at 75% power, floored at +1/+1 minimum, same
#      SOCKET_POWER_RATIO already used for weapons.
#
# Curing consumes the raw pelt (so you can't wear it AND use the cured
# version — it's one or the other) for a flat 5g fee (matches
# SOCKET_OPERATION_COST; curing is prep work, not a rarity-scaled service).
# The cured item keeps the raw pelt's rarity and stats, which is what
# drives both the recipe scaling and the socket reinforcement above.

CURABLE_PELTS = {"Wolf Pelt", "Dire Wolf Pelt"}
# ^ Deliberately still the RAW names — these are what Arena kills (Wolf Pup /
# Dire Wolf Pup) drop via make_loot(), not what the crafter's own component
# stock sells anymore (that's "Cured Wolf Pelt"/"Cured Dire Wolf Pelt" now,
# see COMPONENT_TYPES / _make_component above). The Cure Pelts service below
# only ever has raw pelts to act on, since store-bought ones skip that step.

# v0.7.17: flat fee, independent of pelt rarity — Nathan's call.
CURE_COST = 5


def cure_cost(item):
    """Gold cost to cure one raw pelt — flat, regardless of rarity."""
    return CURE_COST


def _curable_pelts_in_inventory(warrior):
    """Raw (uncured) pelts ready to cure — bag AND currently equipped (a
    player may be wearing one as basic armor; mirrors how recipes already
    look at both bag and equipped slots)."""
    pelts = [it for it in warrior.inventory if getattr(it, "name", "") in CURABLE_PELTS]
    pelts += [it for it in warrior.equipment.values()
              if it is not None and getattr(it, "name", "") in CURABLE_PELTS]
    return pelts


def _cure_pelt(warrior, raw_pelt):
    """Consume one raw pelt + gold, produce its Cured counterpart in the bag.

    v0.7.19: curing now BUMPS the rarity by one tier — an uncommon raw pelt
    produces a rare Cured Pelt, etc. A mythril raw pelt produces a Mythril+
    Cured Pelt (via EXTRA_RARITY_TIERS). This gives better-quality drops a
    meaningful payoff through the entire crafting chain: raw pelt rarity →
    cured pelt rarity (bumped) → crafted piece stat scaling.
    """
    from shared import Equipment
    from equipment import unequip_item, RARITY_ORDER, EXTRA_RARITY_TIERS
    cost = cure_cost(raw_pelt)
    if warrior.gold < cost:
        print(_wrap(f"  Not enough gold to cure this (need {cost}g)."))
        input("\n  Press Enter...")
        return False

    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, cost)  # v0.7.18: tracks total_gold_spent
    is_equipped = any(eq is raw_pelt for eq in warrior.equipment.values())
    if is_equipped:
        unequip_item(warrior, raw_pelt)  # reverses stats, moves it into inventory
    if raw_pelt in warrior.inventory:
        warrior.inventory.remove(raw_pelt)

    # --- Rarity bump: one tier up, mythril → mythril+ via EXTRA_RARITY_TIERS ---
    input_rarity = getattr(raw_pelt, "rarity", "normal")
    cured_name = f"Cured {raw_pelt.name}"
    extra = EXTRA_RARITY_TIERS.get(cured_name)
    if extra and input_rarity == extra["trigger_rarity"]:
        output_rarity = extra["key"]
        rarity_label = extra["label"]
    elif input_rarity in RARITY_ORDER:
        idx = RARITY_ORDER.index(input_rarity)
        output_rarity = RARITY_ORDER[min(idx + 1, len(RARITY_ORDER) - 1)]
        rarity_label = output_rarity.title()
    else:
        output_rarity = input_rarity
        rarity_label = output_rarity.title()

    cured = Equipment(
        name    = cured_name,
        slot    = "material",
        rarity  = output_rarity,
        defence = raw_pelt.defence,
        max_hp  = raw_pelt.max_hp,
        flavour = "Cured and stiffened — ready to reinforce a piece of armor. Won't hold up worn on its own.",
    )
    warrior.inventory.append(cured)
    print()
    print(_wrap(
        f"  ✅ Cured the {raw_pelt.name} for {cost}g — you now have a "
        f"{cured.short_label().splitlines()[0]}."
    ))
    if output_rarity != input_rarity:
        print(_wrap(
            f"  ⬆️  Rarity bumped: {input_rarity.title()} → {rarity_label}"
        ))
    print(_wrap(
        "  Bring it to Socket items into your gear to reinforce a piece of armor."
    ))
    input("\n  Press Enter...")
    return True


def _cure_pelts_menu(warrior):
    """Crafter menu: pick a raw pelt from the bag and cure it for gold."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  🧪 Crafter — Cure Pelts   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        pelts = _curable_pelts_in_inventory(warrior)
        if not pelts:
            print(_wrap(
                "  You have no raw pelts to cure. Wolf and Dire Wolf kills "
                "drop them, or buy one from the component stock."
            ))
            input("\n  Press Enter...")
            return
        print(_wrap("  Pick a pelt to cure (consumes the pelt + gold, produces a Cured version):"))
        print()
        for i, it in enumerate(pelts):
            cost = cure_cost(it)
            print(f"  {i+1}) {it.short_label().splitlines()[0]}  —  {cost}g to cure")
        print()
        print("  0) Back")
        print("  M) Main menu")
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        pi = int(choice) - 1
        if 0 <= pi < len(pelts):
            _cure_pelt(warrior, pelts[pi])


# ============================================================
# UI — RECIPE MENU
# ============================================================

# Set bonus reference tables — shared by the picker and both set tabs
SET_BONUSES = {
    "wolf_hide": [
        (1, "no bonus yet"),
        (2, "+5 max HP"),
        (3, "+5 max HP, +1 max AP"),
        (4, "+5 max HP, +1 max AP, +2 DEF, +2 ATK  [Pack Hunter unlocked]"),
    ],
    "dire_wolf": [
        (1, "no bonus yet"),
        (2, "+8 max HP"),
        (3, "+8 max HP, +2 max AP"),
        (4, "+8 max HP, +2 max AP, +3 DEF, +3 ATK  [Apex Predator unlocked]"),
    ],
}


def _show_recipe_categories(warrior):
    """v0.7.13: Top-level recipe menu — pick a set tab instead of scrolling
    both sets on one long screen."""
    print("=" * 52)
    print(f"  🔨 Crafter — Recipes   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    wolf_pieces = wolf_set_active_pieces(warrior)
    dire_pieces = dire_wolf_set_active_pieces(warrior)
    print(f"  1) 🐺 Wolf-Hide Set  (Tier 1)   — {wolf_pieces}/4 pieces equipped")
    print(f"  2) 🐗 Dire Wolf Set  (Tier 2)   — {dire_pieces}/4 pieces equipped")
    print()
    print("  0) Back to crafter menu")


def _render_recipe_set_menu(warrior, set_label, recipes_dict, header_text):
    """v0.7.13: Renders ONE set's recipes (was _render_set_section, now
    scoped to a single tab instead of both sets back-to-back)."""
    print("=" * 52)
    print(f"  🔨 Crafter — Recipes   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1

    equipped_count = (wolf_set_active_pieces(warrior) if set_label == "wolf_hide"
                       else dire_wolf_set_active_pieces(warrior))

    print(_wrap(f"  {header_text}"))
    print(f"  Pieces equipped: {equipped_count}/4")

    thresholds = SET_BONUSES.get(set_label, [])
    current_bonus = "none"
    next_bonus    = None
    for pieces, bonus in thresholds:
        if equipped_count >= pieces:
            current_bonus = bonus
        elif next_bonus is None:
            next_bonus = (pieces, bonus)

    print(f"  Active bonus:    {current_bonus}")
    if next_bonus:
        needed = next_bonus[0] - equipped_count
        print(f"  Next threshold:  {next_bonus[0]} pieces → {next_bonus[1]}  ({needed} more needed)")
    print()

    for name, recipe in recipes_dict.items():
        can, missing, craft_rarity, cost = _can_afford_recipe(warrior, recipe)

        req = " + ".join(f"{n}x {c}" for c, n in recipe["components"].items())

        if missing:
            status = f"need {', '.join(missing)}"
        elif not can:
            status = f"{cost}g (need {cost - warrior.gold} more)"
        else:
            status = f"{cost}g  [crafts at {craft_rarity.title()}]"

        equipped = any(it is not None and getattr(it, "name", "") == name
                       for it in warrior.equipment.values())
        owned    = any(getattr(it, "name", "") == name for it in warrior.inventory)
        marker = " [EQUIPPED]" if equipped else (" [in bag]" if owned else "")

        # v0.7.17: stats now scale with the rarity the player can currently
        # craft at (or Normal baseline if they don't have components yet),
        # so this preview shows what they'd ACTUALLY get, not a fixed number.
        preview_rarity = craft_rarity or "normal"
        p_def = _scale_craft_stat(recipe.get("defence", 0), preview_rarity)
        p_hp  = _scale_craft_stat(recipe.get("max_hp", 0), preview_rarity)
        p_min = _scale_craft_stat(recipe.get("atk_min", 0), preview_rarity)
        p_max = _scale_craft_stat(recipe.get("atk_max", 0), preview_rarity)
        p_ap  = _scale_craft_stat(recipe.get("max_ap_bonus", 0), preview_rarity)

        # Crystal bonus (if this recipe uses one) — separate linear scaling,
        # layered on top, based on whichever specific crystal copy is owned.
        c_field, c_value = _recipe_crystal_bonus(warrior, recipe)
        if c_field == "max_hp":
            p_hp += c_value
        elif c_field == "defence":
            p_def += c_value
        elif c_field == "max_ap_bonus":
            p_ap += c_value
        elif c_field == "atk":
            p_min += c_value
            p_max += c_value

        stat_parts = []
        if p_def:
            stat_parts.append(f"🛡️ +{p_def} DEF")
        if p_hp:
            stat_parts.append(f"❤️ +{p_hp} HP")
        if p_min or p_max:
            atk_str = f"+{p_min}" if p_min == p_max else f"+{p_min}-{p_max}"
            stat_parts.append(f"⚔️ {atk_str} ATK")
        if p_ap:
            stat_parts.append(f"🔵 +{p_ap} Max AP")
        stats_line = "  ".join(stat_parts) if stat_parts else "(no stat bonus)"
        stats_line += f"   (at {preview_rarity.title()} — varies with pelt/crystal used)"

        print(f"  {idx:>2}) {name:<22}{marker}")
        print(f"      {stats_line}")
        print(f"      {req:<32} {status}")
        actions[str(idx)] = name
        idx += 1
        print()

    print("  0) Back to set picker")
    return actions


def _show_wolf_hide_recipes_menu(warrior):
    return _render_recipe_set_menu(
        warrior, "wolf_hide", WOLF_HIDE_RECIPES,
        "WOLF-HIDE SET — Tier 1 (full set unlocks Pack Hunter)")


def _show_dire_wolf_recipes_menu(warrior):
    return _render_recipe_set_menu(
        warrior, "dire_wolf", DIRE_WOLF_RECIPES,
        "DIRE WOLF SET — Tier 2 (full set unlocks Apex Predator)")


def _recipe_category_loop(warrior, menu_fn):
    """v0.7.13: Inner loop for one recipe set tab. Stays here until the
    player backs out to the set picker."""
    while True:
        _clear_screen()
        actions = menu_fn(warrior)
        print("  M) Main menu")
        raw = input("  > ").strip().lower()
        if raw == "0" or raw == "":
            return
        if raw == "m":
            raise _ReturnToCrafterMenu()
        recipe_name = actions.get(raw)
        if not recipe_name:
            continue
        recipe = ALL_RECIPES[recipe_name]
        _craft_recipe(warrior, recipe_name, recipe)


def _recipe_loop(warrior):
    """v0.7.13: Top-level recipe menu — pick Wolf-Hide or Dire Wolf tab,
    then browse just that set. Replaces the old both-sets-on-one-screen view."""
    while True:
        _clear_screen()
        _show_recipe_categories(warrior)
        raw = input("  > ").strip()
        if raw == "0" or raw == "":
            return
        if raw == "1":
            _recipe_category_loop(warrior, _show_wolf_hide_recipes_menu)
        elif raw == "2":
            _recipe_category_loop(warrior, _show_dire_wolf_recipes_menu)


# ============================================================
# SET DETECTION & BONUS APPLICATION
# ============================================================

def wolf_set_active_pieces(warrior):
    """Count how many Wolf-Hide pieces the warrior currently has EQUIPPED."""
    return sum(1 for it in warrior.equipment.values()
               if it is not None and getattr(it, "name", "") in WOLF_HIDE_PIECE_NAMES)


def pack_hunter_active(warrior):
    """True iff the full 4-piece Wolf-Hide set is equipped."""
    return wolf_set_active_pieces(warrior) >= 4


def dire_wolf_set_active_pieces(warrior):
    """v0.6.16: Count how many Dire Wolf pieces the warrior currently has EQUIPPED."""
    return sum(1 for it in warrior.equipment.values()
               if it is not None and getattr(it, "name", "") in DIRE_WOLF_PIECE_NAMES)


def apex_predator_active(warrior):
    """v0.6.16: True iff the full 4-piece Dire Wolf set is equipped."""
    return dire_wolf_set_active_pieces(warrior) >= 4


def _previous_set_bonus_state(warrior, attr_name):
    """
    Returns the dict of currently-applied set bonuses on the warrior under
    the given attribute name. Generic helper used for both Wolf-Hide and
    Dire Wolf set tracking. Each set has its OWN bonus state attribute so
    they don't clobber each other when (briefly) a player has pieces of
    both sets equipped during inventory shuffling.
    """
    return getattr(warrior, attr_name, {
        "max_hp": 0, "max_ap": 0, "defence": 0,
        "atk_min": 0, "atk_max": 0,
    })


def apply_wolf_set_bonus(warrior):
    """
    Recalculate the Wolf-Hide set bonus on the warrior. Removes the
    previously-applied bonus, then applies the new one based on current
    piece count. Safe to call after every equip/unequip.

    Bonuses (cumulative, NOT per-piece):
        2 pieces: +5 max HP
        3 pieces: +5 max HP, +1 max AP
        4 pieces: +5 max HP, +1 max AP, +2 DEF, +2 ATK (min and max)

    The Pack Hunter passive (+10% basic-attack damage and 50% bleed-on-hit)
    is read live from pack_hunter_active() during combat — not applied here.
    """
    pieces = wolf_set_active_pieces(warrior)

    # Compute NEW bonus
    new = {"max_hp": 0, "max_ap": 0, "defence": 0, "atk_min": 0, "atk_max": 0}
    if pieces >= 2:
        new["max_hp"] += 5
    if pieces >= 3:
        new["max_ap"] += 1
    if pieces >= 4:
        new["defence"] += 2
        new["atk_min"] += 2
        new["atk_max"] += 2

    # Remove OLD bonus
    old = _previous_set_bonus_state(warrior, "_wolf_hide_bonus_applied")
    warrior.max_hp  -= old["max_hp"]
    warrior.hp       = min(warrior.hp, warrior.max_hp)
    warrior.max_ap  -= old["max_ap"]
    warrior.ap       = min(warrior.ap, warrior.max_ap)
    warrior.defence -= old["defence"]
    warrior.min_atk -= old["atk_min"]
    warrior.max_atk -= old["atk_max"]

    # Apply NEW bonus
    warrior.max_hp  += new["max_hp"]
    if new["max_hp"] > 0 and old["max_hp"] == 0:
        # Newly gained set HP — heal up to it (don't penalize the player for crossing the threshold mid-interlude)
        warrior.hp = min(warrior.max_hp, warrior.hp + new["max_hp"])
    warrior.max_ap  += new["max_ap"]
    warrior.defence += new["defence"]
    warrior.min_atk += new["atk_min"]
    warrior.max_atk += new["atk_max"]

    # Recompute overheal cap
    warrior.max_overheal = int(warrior.max_hp * 1.10)

    # Stash for next call
    warrior._wolf_hide_bonus_applied = new


def apply_dire_wolf_set_bonus(warrior):
    """
    v0.6.16: Recalculate the Dire Wolf set bonus on the warrior. Mirrors
    apply_wolf_set_bonus exactly but uses Dire Wolf's stronger curve:
        2 pieces: +8 max HP
        3 pieces: +8 max HP, +2 max AP
        4 pieces: +8 max HP, +2 max AP, +3 DEF, +3 ATK (min and max)

    The Apex Predator passive (+10% basic-attack damage and 5% lifesteal)
    is read live from apex_predator_active() during combat — not applied
    here.

    Note: Dire Wolf shares helm/cape/armor/accessory slots with Wolf-Hide,
    so they cannot both be at 4-piece simultaneously. If a player briefly
    has mixed pieces equipped, both set-bonus calculations run with the
    pieces of their own set — there's no cross-contamination because each
    set tracks its own bonus state under a separate attribute name.
    """
    pieces = dire_wolf_set_active_pieces(warrior)

    # Compute NEW bonus
    new = {"max_hp": 0, "max_ap": 0, "defence": 0, "atk_min": 0, "atk_max": 0}
    if pieces >= 2:
        new["max_hp"] += 8
    if pieces >= 3:
        new["max_ap"] += 2
    if pieces >= 4:
        new["defence"] += 3
        new["atk_min"] += 3
        new["atk_max"] += 3

    # Remove OLD bonus
    old = _previous_set_bonus_state(warrior, "_dire_wolf_bonus_applied")
    warrior.max_hp  -= old["max_hp"]
    warrior.hp       = min(warrior.hp, warrior.max_hp)
    warrior.max_ap  -= old["max_ap"]
    warrior.ap       = min(warrior.ap, warrior.max_ap)
    warrior.defence -= old["defence"]
    warrior.min_atk -= old["atk_min"]
    warrior.max_atk -= old["atk_max"]

    # Apply NEW bonus
    warrior.max_hp  += new["max_hp"]
    if new["max_hp"] > 0 and old["max_hp"] == 0:
        warrior.hp = min(warrior.max_hp, warrior.hp + new["max_hp"])
    warrior.max_ap  += new["max_ap"]
    warrior.defence += new["defence"]
    warrior.min_atk += new["atk_min"]
    warrior.max_atk += new["atk_max"]

    # Recompute overheal cap
    warrior.max_overheal = int(warrior.max_hp * 1.10)

    # Stash for next call
    warrior._dire_wolf_bonus_applied = new


def apply_all_set_bonuses(warrior):
    """
    v0.6.16: Convenience function that recalculates ALL crafted-set bonuses.
    Call this from equip_item / unequip_item — it's cheaper than the player
    is going to notice and guarantees no set goes stale. Future sets just
    add another apply_*_set_bonus(warrior) call here.
    """
    apply_wolf_set_bonus(warrior)
    apply_dire_wolf_set_bonus(warrior)


# ============================================================
# SOCKETING SYSTEM (v0.6.16)
# ============================================================
#
# Weapons gain rarity-based sockets. Players slot accessory-type items
# (sacs, tusks, pendants) into weapons to make their effects ride along
# with basic attacks. Frees up the accessory slot for crafted-set pieces.
#
# Phase 1 in v0.6.16: weapon sockets only.
# Phase 2 (later): armor sockets with defensive procs.
#
# RULES:
#   - 0/1/1/2 sockets for Poor/Normal/Uncommon/Rare weapons
#   - Socketable items: Poison Sac, Fire Sac, Acid Sac, Javelina Tusk,
#     Soul Pendant
#   - Socketing happens at the crafter, 5g per insert/remove operation
#   - Socketed items work AT 75% POWER of worn versions:
#       * Chance procs: chance × 0.75
#       * Damage values: int(dmg × 0.75)
#       * DoT per-turn damage: int(dmg × 0.75)
#     Worn is always slightly better than socketed — that's the tradeoff
#     for freeing the accessory slot.
#   - Socketed items live INSIDE the equipment; not in inventory.
#   - Sockets travel with the item (un/equip, sale, save/load).

# ============================================================
# PHASE 2 DESIGN NOTES — ARMOR SOCKETS (deferred; UI preview only in v0.6.20)
# ============================================================
#
# Status: NOT IMPLEMENTED. v0.6.20 adds a "What to socket?" front-menu
# in the crafter with an armor preview path that lists the player's
# armor pieces and their socket capacity, then shows "Coming Soon" and
# returns. The Equipment class already spawns armor with empty sockets
# based on _SOCKET_COUNTS_ARMOR — they're inert until Phase 2 wires up
# combat hooks.
#
# Socket count table (v0.7.17):
#   Poor/Normal              → 0 sockets
#   Uncommon                 → 1 socket
#   Rare/Epic                → 2 sockets
#   Legendary                → 3 sockets
#   Mythril                  → 4 sockets
#   (Poor armor can drop as raw crafting-component pelts, e.g. Wolf Pelt,
#   which ARE equippable directly — this table still gives them 0 sockets.)
#
# PLANNED ARMOR-SOCKETABLE ITEMS:
#
#   Javelina Tusk — RETALIATION BLEED
#     When the player is hit by a basic attack (or any attack that
#     lands physical damage past defence), the attacker takes a bleed
#     DoT. Numbers TBD — start with 2 dmg/tick × 2 turns at 75% socket
#     power and tune from there. Stacks like other bleeds (per-stack
#     timers). Does NOT proc on DoT damage to the player, only on
#     direct hits — otherwise it cascades infinitely.
#
#   Soul Amulet — DAMAGE ABSORB + HEAL
#     When the player takes a hit, absorb a portion of incoming damage
#     and convert it to a small heal. Numbers TBD — probably absorb
#     20–25% of the hit (after defence) and heal half of that amount
#     back. At 75% socket power that's roughly 15–18% absorb, half
#     converted to heal. Soul Pendant on the weapon side gives drain
#     on the player's hits; Soul Amulet on the armor side gives the
#     defensive mirror — they pair as a "lifesteal build" archetype.
#
# OPEN DESIGN QUESTIONS (resolve before implementing):
#   - Should Tusk retaliation count as the player attacking the enemy?
#     (For purposes of bleed mastery title, score, etc.) Lean: yes,
#     it's the player's tusk causing it.
#   - Should Soul Amulet heal trigger Pack Hunter / Apex Predator
#     basic-atk multipliers? Lean: no, it's not a basic attack.
#   - Damage source attribution on Tusk retaliation — does it print
#     as "Your tusk retaliates" or just as a bleed tick? Lean: one-time
#     "tusk retaliates" line on application, then normal bleed ticks.
#   - Future "resistance" system: poison/fire/acid sacs in armor sockets
#     could grant resistance to the matching element. This is a whole
#     new system (resistance tracking, damage type tags on all DoTs).
#     Deferred — not part of Phase 2.

# Cost per socket operation (insert or remove)
SOCKET_OPERATION_COST = 5

# Nerf multiplier for socketed accessory effects
SOCKET_POWER_RATIO = 0.75

# Names that can be socketed into a weapon. Soul Pendant is included for
# weapon-side drain — armor-side pendant procs are Phase 2.
#
# v0.7.19 BUG FIX: Sharpened Tusk (the crafter's upgrade of a raw Javelina
# Tusk) was missing from this set entirely — a raw Tusk could be socketed,
# but sharpening it made it un-socketable, which is backwards for an
# upgrade. Added below. Note: weapon sockets only carry PROC-style effects
# (bleed/element/drain — see get_weapon_socket_procs), not static stat
# bonuses, so a socketed Sharpened Tusk gives the (nerfed) bleed only, same
# as a raw Tusk would — its +ATK bonus is the accessory-slot-exclusive perk,
# the trade-off for not freeing up a weapon socket instead.
SOCKETABLE_INTO_WEAPON = {
    "Poison Sac", "Fire Sac", "Acid Sac",
    "Javelina Tusk", "Sharpened Tusk", "Soul Pendant",
}

# v0.7.17: Armor sockets go live — Cured Wolf/Dire Wolf Pelts are the first
# armor-socketable items. See "PELT CURING" section above for how raw
# pelts become these.
#
# v0.7.19: Elemental resistance system — Poison/Fire/Acid Sacs can now ALSO
# be socketed into armor (they remain weapon-socketable too, for offense).
# Socketed into armor, a Sac no longer deals damage — it grants % resistance
# to its matching element instead, scaled by the SAC'S OWN rarity (Nathan's
# call): Poor 10%, Normal 20%, Uncommon 30%, Rare 40%, Epic 50%,
# Legendary 60%, Mythril 70%.
#
# Resistance does NOT stack same-element — two Poor Acid Sacs in one armor
# piece still only grant 10% (the better of the two), not 20%. Nathan's call:
# duplicate same-element Sacs don't compound. Different elements in
# different sockets DO both apply independently — a Poison Sac + an Acid Sac
# in a 2-socket piece grants both resistances at once, if the armor has the
# slots for it.
#
# Only DoT/tick damage of the matching element is reduced (poison ticks,
# burn ticks, acid ticks) — it does not touch the flat physical hit that
# often accompanies an elemental attack (e.g. Chimera's Elemental Strike is
# a physical hit + an elemental DoT; resistance only softens the DoT half).
SOCKETABLE_INTO_ARMOR = {
    "Cured Wolf Pelt", "Cured Dire Wolf Pelt",
    "Poison Sac", "Fire Sac", "Acid Sac",
    "Javelina Tusk", "Sharpened Tusk",  # v0.7.20: retaliation bleed — see combat.py
    "AP Crystal", "HP Crystal", "Defence Crystal", "ATK Crystal",  # v0.7.20: stat reinforcement
    "Soul Pendant",  # v0.7.20: armor = heal-on-hit (defensive mirror of weapon drain)
}

# Cured pelts are the only armor-socketables that reinforce DEF/HP directly;
# Sacs socketed into armor grant resistance instead (see armor_socket_resistance).
# v0.7.20: Crystals also grant stat reinforcement (at socket power ratio).
_ARMOR_DEF_HP_SOCKETABLES = {"Cured Wolf Pelt", "Cured Dire Wolf Pelt"}
_ARMOR_CRYSTAL_NAMES = {"AP Crystal", "HP Crystal", "Defence Crystal", "ATK Crystal"}

# Elemental resistance granted by a Sac, keyed by the SAC'S OWN rarity —
# this is independent of the armor piece's rarity/socket count.
ELEMENT_RESISTANCE_BY_RARITY = {
    "poor":      0.10,
    "normal":    0.20,
    "uncommon":  0.30,
    "rare":      0.40,
    "epic":      0.50,
    "legendary": 0.60,
    "mythril":   0.70,
}


def armor_socket_resistance(item, element):
    """
    The elemental resistance (0.0-1.0) an armor piece grants for a given
    element ("poison"/"fire"/"acid"), from any Poison/Fire/Acid Sacs socketed
    into it whose .element matches. Does NOT stack same-element duplicates —
    takes the single best matching Sac's resistance, not the sum. Different
    elements each contribute independently (handled by the caller, which
    calls this once per element).
    """
    best = 0.0
    for socketed in getattr(item, "sockets", []) or []:
        if socketed is None:
            continue
        if getattr(socketed, "name", "") not in ("Poison Sac", "Fire Sac", "Acid Sac"):
            continue
        if getattr(socketed, "element", None) != element:
            continue
        best = max(best, ELEMENT_RESISTANCE_BY_RARITY.get(socketed.rarity, 0.0))
    return best


def get_hero_element_resistance(hero, element):
    """
    Public helper: the player's total resistance (0.0-1.0) to a given element,
    read live from whatever Sacs are socketed into their equipped chest armor.
    Returns 0.0 if the hero has no armor equipped, no sockets, or isn't a
    player-shaped object (monsters don't have .equipment).
    """
    equipment = getattr(hero, "equipment", None)
    if equipment is None:
        return 0.0
    armor = equipment.get("armor")
    if armor is None or not getattr(armor, "sockets", None):
        return 0.0
    return armor_socket_resistance(armor, element)


def socket_nerf_chance(base_chance):
    """Apply the 75% nerf to a chance value (0.0-1.0)."""
    return base_chance * SOCKET_POWER_RATIO


def socket_nerf_damage(base_damage):
    """Apply the 75% nerf to a damage value, rounded down, min 1 if base > 0."""
    if base_damage <= 0:
        return 0
    return max(1, int(base_damage * SOCKET_POWER_RATIO))


def armor_socket_reinforcement(base_value):
    """
    75% power for a cured-pelt armor socket, floored at +1 regardless of the
    base stat — Nathan's call: even a Poor cure (which may have 0 in one
    stat raw) still reinforces armor by at least +1/+1 once socketed.
    """
    return max(1, int(base_value * SOCKET_POWER_RATIO))


def armor_socket_stat_bonus(item):
    """
    Sum the stat bonuses an armor piece gets from its currently socketed items.

    Cured pelts contribute DEF/HP at 75% socket power.
    Crystals contribute their specific stat at 75% socket power:
      - HP Crystal → HP bonus
      - Defence Crystal → DEF bonus
      - ATK Crystal → ATK bonus (applied as min/max ATK on the hero)
      - AP Crystal → AP bonus (applied as max_ap on the hero)
    Sacs grant resistance (see armor_socket_resistance), not stat bonuses.
    Tusks and Soul Pendants have combat-time effects, not stat bonuses.
    """
    def_bonus = 0
    hp_bonus  = 0
    ap_bonus  = 0
    atk_bonus = 0
    for socketed in getattr(item, "sockets", []):
        if socketed is None:
            continue
        sock_name = getattr(socketed, "name", "")
        sock_rarity = getattr(socketed, "rarity", "normal")

        if sock_name in _ARMOR_DEF_HP_SOCKETABLES:
            def_bonus += armor_socket_reinforcement(getattr(socketed, "defence", 0))
            hp_bonus  += armor_socket_reinforcement(getattr(socketed, "max_hp", 0))

        elif sock_name in _ARMOR_CRYSTAL_NAMES:
            # v0.7.20: crystals in armor grant their stat at socket power
            crystal_value = CRYSTAL_RARITY_VALUE.get(sock_name, {}).get(sock_rarity, 0)
            socketed_value = max(1, int(crystal_value * SOCKET_POWER_RATIO))
            if sock_name == "HP Crystal":
                hp_bonus += socketed_value
            elif sock_name == "Defence Crystal":
                def_bonus += socketed_value
            elif sock_name == "ATK Crystal":
                atk_bonus += socketed_value
            elif sock_name == "AP Crystal":
                ap_bonus += socketed_value

    return def_bonus, hp_bonus, ap_bonus, atk_bonus


def get_weapon_socket_procs(weapon):
    """
    Aggregate socketed accessory effects on the given weapon into a list
    of proc dicts. Combat code reads this list and applies each proc
    independently (with the 75% nerf already baked in).

    Returns a list of dicts. Each dict has a "type" key telling combat
    code what kind of proc it is. Empty list if no sockets are filled.

    Proc types and their fields:
        "element":  {type, element, damage, turns, restore, max_dots,
                     erosion, chance}
                    — fires from Poison/Fire/Acid Sacs
        "bleed":    {type, turns, dmg_min, dmg_max, chance}
                    — fires from Javelina Tusk
        "drain":    {type, bonus, heal_min, heal_max}
                    — Soul Pendant adds drain effect to attacks

    Notes on nerf application:
        Element damage and bleed dmg are int(dmg * 0.75), min 1.
        Chances are chance * 0.75 (or 0.75 if base was implicit 100%).
        Sac element_damage is the per-tick damage; turns are unchanged.
        Bleed turns are unchanged; only damage and chance are reduced.
        Drain bonus is reduced; heal range floors at min 1.
    """
    procs = []
    if not weapon or not hasattr(weapon, "sockets"):
        return procs
    for socketed in weapon.sockets:
        if socketed is None:
            continue
        name = socketed.name
        if name in ("Poison Sac", "Fire Sac", "Acid Sac"):
            # Sacs have implicit 100% application — apply 75% as the chance
            procs.append({
                "type":       "element",
                "element":    socketed.element,
                "damage":     socket_nerf_damage(socketed.element_damage),
                "turns":      socketed.element_turns,
                "restore":    socketed.element_restore,
                "max_dots":   socketed.element_max_dots,
                "erosion":    socketed.element_erosion,
                "chance":     SOCKET_POWER_RATIO,
                "source":     name,
            })
        elif name in ("Javelina Tusk", "Sharpened Tusk"):
            # Tusk has implicit 100% bleed — apply 75% chance, 75% damage.
            # Sharpened Tusk's atk_bonus does NOT carry over when socketed
            # (see SOCKETABLE_INTO_WEAPON note) — bleed only, same as raw Tusk.
            procs.append({
                "type":    "bleed",
                "turns":   socketed.bleed_turns,
                "dmg_min": socket_nerf_damage(socketed.bleed_dmg_min),
                "dmg_max": socket_nerf_damage(socketed.bleed_dmg_max),
                "chance":  SOCKET_POWER_RATIO,
                "source":  name,
            })
        elif name == "Soul Pendant":
            # Pendant drain — bonus damage + heal both nerfed
            procs.append({
                "type":      "drain",
                "bonus":     socket_nerf_damage(socketed.drain_bonus),
                "heal_min":  socket_nerf_damage(socketed.drain_heal_min),
                "heal_max":  socket_nerf_damage(socketed.drain_heal_max),
                "source":    name,
            })
    return procs


def migrate_legacy_sockets(item):
    """
    Save-migration helper. Called on every Equipment instance after loading
    an old save that predates the socket system.

    Backfill rule (Nathan's call): items get sockets based on their rarity.
    A pre-v0.6.16 Rare Goblin Dagger gets 2 sockets, retroactively.

    Idempotent — if sockets already present, this is a no-op.
    """
    if not hasattr(item, "sockets") or item.sockets is None:
        # Reconstruct using the same logic as __init__
        if item.slot not in ("weapon", "armor"):
            item.sockets = []
            return
        if item.slot == "weapon":
            count = item._SOCKET_COUNTS_WEAPON.get(item.rarity, 0)
        else:
            count = item._SOCKET_COUNTS_ARMOR.get(item.rarity, 0)
        item.sockets = [None] * count


def _socketable_items_in_inventory(warrior):
    """Return list of inventory items that can be inserted into a weapon socket."""
    return [it for it in warrior.inventory
            if getattr(it, "name", "") in SOCKETABLE_INTO_WEAPON]


def _socket_source_candidates(warrior, name_set):
    """
    v0.7.18: All insertable components for a socket, as (item, is_equipped)
    tuples — bag items first, then the currently-equipped accessory if its
    name is in `name_set`. Nathan's call: an equipped Poison Sac (or Tusk,
    Pendant, etc.) can be slotted straight from the equipment screen — the
    menu auto-unequips it first instead of making the player do a separate
    unequip round-trip through the inventory menu.
    """
    out = [(it, False) for it in warrior.inventory
           if getattr(it, "name", "") in name_set]
    acc = warrior.equipment.get("accessory")
    if acc is not None and getattr(acc, "name", "") in name_set:
        out.append((acc, True))
    return out


def _unequip_for_socketing(warrior, item):
    """
    v0.7.18: cleanly unequip `item` (stat/proc removal via the standard
    equipment path) so it lands in the bag ready to be socketed. Returns
    True on success. Kept separate so the socket menus can gold-check
    BEFORE unequipping — an insufficient-gold socket attempt shouldn't
    strip the player's accessory as a side effect.
    """
    from equipment import unequip_item
    unequip_item(warrior, item)
    return item in warrior.inventory


def _weapons_with_sockets_in_inventory(warrior):
    """
    Return list of (label, item) tuples for items that have sockets
    (count > 0). Includes both inventory weapons AND currently-equipped
    weapons — players need to socket the weapon they're using.
    """
    candidates = []
    # Equipped weapon — handle both old 'weapon' key and new 'main_hand'/'off_hand'
    for slot_key in ("weapon", "main_hand", "off_hand"):
        equipped = warrior.equipment.get(slot_key)
        if equipped is None:
            continue
        if getattr(equipped, "slot", None) != "weapon":
            continue
        if equipped.socket_count() > 0:
            candidates.append((f"{equipped.short_label()} [equipped]", equipped))
    # Inventory weapons
    for it in warrior.inventory:
        if getattr(it, "slot", "") != "weapon":
            continue
        if it.socket_count() > 0:
            candidates.append((f"{it.short_label()} [in bag]", it))
    return candidates


def _format_sockets(item):
    """One-line socket display string. e.g. '[💎 Poison Sac, 💎 empty]'"""
    if not item.sockets:
        return "[no sockets]"
    parts = []
    for s in item.sockets:
        if s is None:
            parts.append("empty")
        else:
            parts.append(s.short_label() if hasattr(s, "short_label") else s.name)
    return "[💎 " + ", 💎 ".join(parts) + "]"


def _socket_item_into_weapon(warrior, weapon, socket_idx, component):
    """Insert a component into a specific weapon socket. Charges 5g."""
    if warrior.gold < SOCKET_OPERATION_COST:
        print(_wrap(f"  Not enough gold (need {SOCKET_OPERATION_COST}g)."))
        input("\n  Press Enter...")
        return False
    if weapon.sockets[socket_idx] is not None:
        print(_wrap("  That socket is already filled — remove it first."))
        input("\n  Press Enter...")
        return False
    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, SOCKET_OPERATION_COST)  # v0.7.18: tracks total_gold_spent
    weapon.sockets[socket_idx] = component
    if component in warrior.inventory:
        warrior.inventory.remove(component)
    print()
    print(_wrap(f"  ✅ Slotted {component.short_label()} into {weapon.name}."))
    input("\n  Press Enter...")
    return True


def _unsocket_item_from_weapon(warrior, weapon, socket_idx):
    """Pop a component out of a socket back into inventory. Charges 5g."""
    if warrior.gold < SOCKET_OPERATION_COST:
        print(_wrap(f"  Not enough gold (need {SOCKET_OPERATION_COST}g)."))
        input("\n  Press Enter...")
        return False
    component = weapon.sockets[socket_idx]
    if component is None:
        return False
    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, SOCKET_OPERATION_COST)  # v0.7.18: tracks total_gold_spent
    weapon.sockets[socket_idx] = None
    warrior.inventory.append(component)
    print()
    print(_wrap(f"  ✅ Removed {component.short_label()} from {weapon.name}."))
    input("\n  Press Enter...")
    return True


def pop_sockets_to_inventory(warrior, item):
    """
    Public helper: empty all of an item's sockets, putting the components
    back into the warrior's inventory. Used by the MERCHANT when the
    player tries to SELL a socketed item — components come back first,
    then the sale proceeds on the now-empty item.

    Returns the list of components that were popped (for the caller to
    show a message like "Recovered: Poison Sac, Javelina Tusk").
    """
    if not hasattr(item, "sockets") or not item.sockets:
        return []
    popped = []
    for i, s in enumerate(item.sockets):
        if s is not None:
            warrior.inventory.append(s)
            popped.append(s)
            item.sockets[i] = None
    return popped


def _show_socket_menu_for_weapon(warrior, weapon):
    """Show the per-weapon socket UI: list sockets, let player fill or empty each."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💎 Socketing: {weapon.short_label()}   |   Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(_wrap(f"  Operation cost: {SOCKET_OPERATION_COST}g per insert or remove."))
        print(_wrap(f"  Socketed items run at {int(SOCKET_POWER_RATIO * 100)}% effectiveness."))
        print()
        for idx, s in enumerate(weapon.sockets):
            label = "empty" if s is None else s.short_label()
            print(f"  {idx+1}) Socket {idx+1}: {label}")
        print()
        print("  0) Back")
        print("  M) Main menu")
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        socket_idx = int(choice) - 1
        if socket_idx < 0 or socket_idx >= len(weapon.sockets):
            continue

        if weapon.sockets[socket_idx] is None:
            # Empty socket — show socketable inventory items
            _clear_screen()
            print(_wrap(f"  Socket {socket_idx+1} of {weapon.name} is empty."))
            print()
            sockables = _socket_source_candidates(warrior, SOCKETABLE_INTO_WEAPON)
            if not sockables:
                print(_wrap("  You have nothing socketable in your bag or equipped."))
                print(_wrap("  Try buying Sacs, Tusks, or a Soul Pendant from the component stock."))
                input("\n  Press Enter...")
                continue
            print(_wrap(f"  Pick something to slot in (costs {SOCKET_OPERATION_COST}g):"))
            for i, (it, is_eq) in enumerate(sockables):
                tag = "  [equipped — will be unequipped first]" if is_eq else ""
                print(f"    {i+1}) {it.short_label()}{tag}")
            print("    0) Cancel")
            pick = input("  > ").strip()
            if pick == "0" or pick == "":
                continue
            if not pick.isdigit():
                continue
            pi = int(pick) - 1
            if 0 <= pi < len(sockables):
                item, is_eq = sockables[pi]
                # v0.7.18: gold-check BEFORE auto-unequip so a failed insert
                # doesn't strip the accessory as a side effect.
                if is_eq and warrior.gold >= SOCKET_OPERATION_COST:
                    if not _unequip_for_socketing(warrior, item):
                        continue
                _socket_item_into_weapon(warrior, weapon, socket_idx, item)
        else:
            # Filled socket — confirm remove
            _clear_screen()
            current = weapon.sockets[socket_idx]
            print(_wrap(f"  Socket {socket_idx+1}: {current.short_label()}"))
            print()
            print(_wrap(f"  Remove for {SOCKET_OPERATION_COST}g? (the component returns to your bag)"))
            confirm = input("  (y/n): ").strip().lower()
            if confirm == "y":
                _unsocket_item_from_weapon(warrior, weapon, socket_idx)


def _armor_with_sockets_in_inventory(warrior):
    """
    Mirror of _weapons_with_sockets_in_inventory for armor. Returns
    (label, item) for armor pieces with socket capacity — equipped chest
    armor plus any in the bag.

    "Armor" here means slot == "armor" specifically. Crafted helm/cape
    pieces (slot == "helm" / "cape") aren't socketable — only the chest
    armor slot is.
    """
    candidates = []
    equipped = warrior.equipment.get("armor")
    if equipped is not None and getattr(equipped, "slot", None) == "armor":
        if equipped.socket_count() > 0:
            candidates.append((f"{equipped.short_label()} [equipped]", equipped))
    for it in warrior.inventory:
        if getattr(it, "slot", "") != "armor":
            continue
        if it.socket_count() > 0:
            candidates.append((f"{it.short_label()} [in bag]", it))
    return candidates


def _socketable_armor_items_in_inventory(warrior):
    """Cured pelts in the bag, ready to slot into an armor piece."""
    return [it for it in warrior.inventory
            if getattr(it, "name", "") in SOCKETABLE_INTO_ARMOR]


def _apply_equipped_armor_socket_delta(hero, item, def_delta, hp_delta):
    """
    If `item` is the CURRENTLY EQUIPPED armor piece, apply a live stat
    delta to the hero (mirrors equip_item's direct-delta style). If it's
    just sitting in the bag, do nothing — the bonus applies naturally
    whenever the player equips it, since equip_item/unequip_item now read
    armor_socket_stat_bonus() themselves.
    """
    if hero.equipment.get("armor") is not item:
        return
    if def_delta:
        hero.defence += def_delta
    if hp_delta:
        hero.max_hp = max(1, hero.max_hp + hp_delta)
        if hp_delta > 0:
            hero.hp += hp_delta
        hero.hp = min(hero.hp, hero.max_hp)
        hero.max_overheal = int(hero.max_hp * 1.10)


def _socket_item_into_armor(warrior, armor, socket_idx, component):
    """Insert a cured pelt into a specific armor socket. Charges 5g."""
    if warrior.gold < SOCKET_OPERATION_COST:
        print(_wrap(f"  Not enough gold (need {SOCKET_OPERATION_COST}g)."))
        input("\n  Press Enter...")
        return False
    if armor.sockets[socket_idx] is not None:
        print(_wrap("  That socket is already filled — remove it first."))
        input("\n  Press Enter...")
        return False

    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, SOCKET_OPERATION_COST)  # v0.7.18: tracks total_gold_spent
    armor.sockets[socket_idx] = component
    if component in warrior.inventory:
        warrior.inventory.remove(component)

    if component.name in ("Poison Sac", "Fire Sac", "Acid Sac"):
        # Sacs grant resistance (read live from sockets) — no stat delta to apply.
        pct = int(ELEMENT_RESISTANCE_BY_RARITY.get(component.rarity, 0.0) * 100)
        print()
        print(_wrap(
            f"  ✅ Slotted {component.short_label().splitlines()[0]} into {armor.name} "
            f"— granting {pct}% {component.element} resistance."
        ))
        input("\n  Press Enter...")
        return True

    # v0.7.20: Tusks and Soul Pendant are combat-time effects (no stat delta).
    if component.name in ("Javelina Tusk", "Sharpened Tusk"):
        print()
        print(_wrap(
            f"  ✅ Slotted {component.short_label().splitlines()[0]} into {armor.name} "
            f"— enemies that hit you will bleed! (Spiked Armor)"
        ))
        input("\n  Press Enter...")
        return True

    if component.name == "Soul Pendant":
        print()
        print(_wrap(
            f"  ✅ Slotted {component.short_label().splitlines()[0]} into {armor.name} "
            f"— you'll recover HP when enemies hit you! (Soul Ward)"
        ))
        input("\n  Press Enter...")
        return True

    # v0.7.20: Crystals grant stat bonuses at socket power.
    if component.name in _ARMOR_CRYSTAL_NAMES:
        crystal_value = CRYSTAL_RARITY_VALUE.get(component.name, {}).get(component.rarity, 0)
        socketed_value = max(1, int(crystal_value * SOCKET_POWER_RATIO))
        stat_name = {"AP Crystal": "AP", "HP Crystal": "HP",
                     "Defence Crystal": "DEF", "ATK Crystal": "ATK"}[component.name]
        # Apply live stat delta if armor is equipped
        if component.name == "HP Crystal":
            _apply_equipped_armor_socket_delta(warrior, armor, 0, socketed_value)
        elif component.name == "Defence Crystal":
            _apply_equipped_armor_socket_delta(warrior, armor, socketed_value, 0)
        elif component.name == "ATK Crystal" and warrior.equipment.get("armor") is armor:
            warrior.min_atk += socketed_value
            warrior.max_atk += socketed_value
        elif component.name == "AP Crystal" and warrior.equipment.get("armor") is armor:
            warrior.max_ap += socketed_value
            warrior.ap = min(warrior.ap + socketed_value, warrior.max_ap)
        print()
        print(_wrap(
            f"  ✅ Slotted {component.short_label().splitlines()[0]} into {armor.name} "
            f"— reinforcing +{socketed_value} {stat_name}."
        ))
        input("\n  Press Enter...")
        return True

    # Fallback: cured pelts (original behavior)
    def_bonus = armor_socket_reinforcement(getattr(component, "defence", 0))
    hp_bonus  = armor_socket_reinforcement(getattr(component, "max_hp", 0))
    _apply_equipped_armor_socket_delta(warrior, armor, def_bonus, hp_bonus)

    print()
    print(_wrap(
        f"  ✅ Slotted {component.short_label().splitlines()[0]} into {armor.name} "
        f"— reinforcing +{def_bonus} DEF, +{hp_bonus} HP."
    ))
    input("\n  Press Enter...")
    return True


def _unsocket_item_from_armor(warrior, armor, socket_idx):
    """Pop a cured pelt out of an armor socket back into inventory. Charges 5g."""
    if warrior.gold < SOCKET_OPERATION_COST:
        print(_wrap(f"  Not enough gold (need {SOCKET_OPERATION_COST}g)."))
        input("\n  Press Enter...")
        return False
    component = armor.sockets[socket_idx]
    if component is None:
        return False

    from gold import spend_gold as _spend_gold
    _spend_gold(warrior, SOCKET_OPERATION_COST)  # v0.7.18: tracks total_gold_spent
    armor.sockets[socket_idx] = None
    warrior.inventory.append(component)

    if component.name not in ("Poison Sac", "Fire Sac", "Acid Sac",
                              "Javelina Tusk", "Sharpened Tusk", "Soul Pendant"):
        if component.name in _ARMOR_CRYSTAL_NAMES:
            # v0.7.20: reverse crystal stat delta
            crystal_value = CRYSTAL_RARITY_VALUE.get(component.name, {}).get(component.rarity, 0)
            socketed_value = max(1, int(crystal_value * SOCKET_POWER_RATIO))
            if component.name == "HP Crystal":
                _apply_equipped_armor_socket_delta(warrior, armor, 0, -socketed_value)
            elif component.name == "Defence Crystal":
                _apply_equipped_armor_socket_delta(warrior, armor, -socketed_value, 0)
            elif component.name == "ATK Crystal" and warrior.equipment.get("armor") is armor:
                warrior.min_atk -= socketed_value
                warrior.max_atk -= socketed_value
            elif component.name == "AP Crystal" and warrior.equipment.get("armor") is armor:
                warrior.max_ap = max(1, warrior.max_ap - socketed_value)
                warrior.ap = min(warrior.ap, warrior.max_ap)
        else:
            # Cured pelts — original behavior
            def_bonus = armor_socket_reinforcement(getattr(component, "defence", 0))
            hp_bonus  = armor_socket_reinforcement(getattr(component, "max_hp", 0))
            _apply_equipped_armor_socket_delta(warrior, armor, -def_bonus, -hp_bonus)

    print()
    print(_wrap(f"  ✅ Removed {component.short_label().splitlines()[0]} from {armor.name}."))
    input("\n  Press Enter...")
    return True


def _show_socket_menu_for_armor(warrior, armor):
    """Per-armor socket UI: list sockets, let player fill or empty each."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💎 Socketing: {armor.short_label().splitlines()[0]}   |   Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print(_wrap(f"  Operation cost: {SOCKET_OPERATION_COST}g per insert or remove."))
        print(_wrap(f"  Cured pelts reinforce at {int(SOCKET_POWER_RATIO * 100)}% power (min +1 DEF/+1 HP each)."))
        print(_wrap(f"  Poison/Fire/Acid Sacs instead grant elemental resistance, scaled by "
                     f"the SAC's own rarity (Poor 10% up to Mythril 70%). Same-element Sacs "
                     f"don't stack — different elements in different sockets do."))
        print()
        for idx, s in enumerate(armor.sockets):
            label = "empty" if s is None else s.short_label().splitlines()[0]
            print(f"  {idx+1}) Socket {idx+1}: {label}")
        print()
        print("  0) Back")
        print("  M) Main menu")
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        socket_idx = int(choice) - 1
        if socket_idx < 0 or socket_idx >= len(armor.sockets):
            continue

        if armor.sockets[socket_idx] is None:
            _clear_screen()
            print(_wrap(f"  Socket {socket_idx+1} of {armor.name} is empty."))
            print()
            sockables = _socket_source_candidates(warrior, SOCKETABLE_INTO_ARMOR)
            if not sockables:
                print(_wrap("  You have nothing socketable in your bag or equipped."))
                print(_wrap("  Cure a raw pelt (Cure Pelts, from the crafter's main menu), or bring a "
                             "Poison/Fire/Acid Sac for resistance instead."))
                input("\n  Press Enter...")
                continue
            print(_wrap(f"  Pick something to slot in (costs {SOCKET_OPERATION_COST}g):"))
            for i, (it, is_eq) in enumerate(sockables):
                tag = "  [equipped — will be unequipped first]" if is_eq else ""
                print(f"    {i+1}) {it.short_label().splitlines()[0]}{tag}")
            print("    0) Cancel")
            pick = input("  > ").strip()
            if pick == "0" or pick == "":
                continue
            if not pick.isdigit():
                continue
            pi = int(pick) - 1
            if 0 <= pi < len(sockables):
                item, is_eq = sockables[pi]
                # v0.7.18: gold-check BEFORE auto-unequip so a failed insert
                # doesn't strip the accessory as a side effect.
                if is_eq and warrior.gold >= SOCKET_OPERATION_COST:
                    if not _unequip_for_socketing(warrior, item):
                        continue
                _socket_item_into_armor(warrior, armor, socket_idx, item)
        else:
            _clear_screen()
            current = armor.sockets[socket_idx]
            print(_wrap(f"  Socket {socket_idx+1}: {current.short_label().splitlines()[0]}"))
            print()
            print(_wrap(f"  Remove for {SOCKET_OPERATION_COST}g? (the cured pelt returns to your bag)"))
            confirm = input("  (y/n): ").strip().lower()
            if confirm == "y":
                _unsocket_item_from_armor(warrior, armor, socket_idx)


def _armor_socket_loop(warrior):
    """Armor socket UI — pick an armor piece, then drop into per-armor menu."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💎 Crafter — Armor Sockets   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()

        candidates = _armor_with_sockets_in_inventory(warrior)
        if not candidates:
            print(_wrap("  You have no socketable armor. Uncommon-rarity and higher"))
            print(_wrap("  armor pieces have sockets; Poor/Normal armor does not."))
            input("\n  Press Enter...")
            return

        print(_wrap("  Pick an armor piece to socket:"))
        for i, (label, _it) in enumerate(candidates):
            print(f"  {i+1}) {label}")
        print()
        print("  0) Back")
        print("  M) Main menu")
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        ci = int(choice) - 1
        if 0 <= ci < len(candidates):
            _, armor = candidates[ci]
            _show_socket_menu_for_armor(warrior, armor)


def _socket_loop(warrior):
    """
    v0.6.20: Front-menu for socketing. Player picks Weapon or Armor;
    Armor drops into the Phase-2 preview (coming-soon) and returns.
    The original weapon-picker flow now lives in _weapon_socket_loop.
    """
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💎 Crafter — Socketing   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print("  What would you like to socket?")
        print()
        print("  1) Weapon")
        print("  2) Armor")
        print()
        print("  0) Back")
        print("  M) Main menu")
        print()
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        elif choice == "1":
            _weapon_socket_loop(warrior)
        elif choice == "2":
            _armor_socket_loop(warrior)


def _weapon_socket_loop(warrior):
    """Weapon socket UI — pick a weapon, then drop into per-weapon menu.
    Renamed from _socket_loop in v0.6.20 when the front-menu was added."""
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💎 Crafter — Weapon Sockets   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()

        candidates = _weapons_with_sockets_in_inventory(warrior)
        if not candidates:
            print(_wrap("  You have no socketable weapons. Normal-rarity and higher"))
            print(_wrap("  weapons have sockets; Poor-quality weapons do not."))
            input("\n  Press Enter...")
            return

        print(_wrap("  Pick a weapon to socket:"))
        for i, (label, _it) in enumerate(candidates):
            print(f"  {i+1}) {label}")
        print()
        print("  0) Back")
        print("  M) Main menu")
        choice = input("  > ").strip().lower()
        if choice == "0" or choice == "":
            return
        if choice == "m":
            raise _ReturnToCrafterMenu()
        if not choice.isdigit():
            continue
        ci = int(choice) - 1
        if 0 <= ci < len(candidates):
            _, weapon = candidates[ci]
            _show_socket_menu_for_weapon(warrior, weapon)


# ============================================================
# PUBLIC ENTRY POINT — full crafter scene
# ============================================================

def crafter_scene(warrior, stock=None):
    """
    Main crafter UI loop. Called from the arena interlude hub.

    Returns the stock dict so the interlude can persist it across re-visits
    within the same interlude (mirrors merchant pattern).
    """
    _clear_screen()
    if stock is None:
        print(_wrap(
            "The crafter looks up from a half-stitched piece of hide. "
            "'Bring me materials, I'll make them into something useful. "
            "Or pick from what I've got on the table — what's here is what's here.'"
        ))
        print()
        stock = generate_crafter_stock()
    else:
        print(_wrap(
            "The crafter nods. 'Back already? Same stock as before — "
            "haven't had time to gather more.'"
        ))
        print()

    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  🔨 Crafter   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print()
        print("  1) Browse component stock")
        print("  2) Browse recipes (Wolf-Hide / Dire Wolf sets)")
        print("  3) Socket items into your gear  💎")   # v0.6.16
        print("  4) Sell components to the crafter (half price)")  # v0.7.13
        print("  5) Cure raw pelts  🧪")  # v0.7.17
        print("  0) Leave")
        print()
        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            print()
            print(_wrap("  'Come back when you have more materials.'"))
            input("\n  Press Enter...")
            return stock
        elif choice == "1":
            try:
                _component_stock_loop(warrior, stock)
            except _ReturnToCrafterMenu:
                pass
        elif choice == "2":
            try:
                _recipe_loop(warrior)
            except _ReturnToCrafterMenu:
                pass
        elif choice == "3":   # v0.6.16
            try:
                _socket_loop(warrior)
            except _ReturnToCrafterMenu:
                pass
        elif choice == "4":   # v0.7.13
            try:
                _sell_components_menu(warrior)
            except _ReturnToCrafterMenu:
                pass
        elif choice == "5":   # v0.7.17
            try:
                _cure_pelts_menu(warrior)
            except _ReturnToCrafterMenu:
                pass
