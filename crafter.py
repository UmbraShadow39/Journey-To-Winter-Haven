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
    "poor":     8,
    "normal":  18,
    "uncommon": 35,
    "rare":     65,
}

# Wildcard roll: every component gets a Normal-rarity listing guaranteed.
# On top of that, ONE additional listing rolls in at one of these rarities.
# Weights based on Nathan's "Poor or Uncommon usually, Rare on lucky days":
WILDCARD_RARITY_WEIGHTS = [
    ("poor",     40),
    ("uncommon", 40),
    ("rare",     20),
]

# Per-listing stock. Nathan's call: "2 total wolf pup pelts if the crafter
# draws them" — so each rarity variant that appears has 2 in stock.
COMPONENT_STOCK_PER_VARIANT = 2

# All components the crafter trades in. Order matters — it's the display order.
COMPONENT_TYPES = [
    "Wolf Pelt",
    "Dire Wolf Pelt",
    "Poison Sac",
    "Fire Sac",
    "Acid Sac",
    "Javelina Tusk",
    "Soul Pendant",
]


# ============================================================
# CRAFTED EQUIPMENT — Wolf-Hide Set
# ============================================================
#
# Crafted gear has FIXED stats — no rarity on the output. Nathan's design:
# different rarities of crafted gear is "kinda silly." The rarity of the
# INPUT pelt instead determines the gold cost (discount for higher rarity).
#
# Recipe cost format:
#     "components": {"Wolf Pelt": 1, "Javelina Tusk": 1}
#     "gold_costs": {"poor": 30, "normal": 22, "uncommon": 15, "rare": 8}
#
# When the recipe needs multiple component TYPES (the charm needs both a
# pelt and a tusk), the discount is based on whichever input rarity is
# HIGHEST — rewards using your best component to save gold.

WOLF_HIDE_RECIPES = {
    "Wolf-Hide Hood": {
        "slot":       "helm",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    1,
        "max_hp":     3,
        "set":        "wolf_hide",
        "components": {"Wolf Pelt": 1},
        "gold_costs": {"poor": 20, "normal": 15, "uncommon": 10, "rare": 6},
        "flavor":     "A snug hood cut from the pelt and lined with sinew.",
    },
    "Wolf-Hide Cloak": {
        "slot":       "cape",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    1,
        "max_hp":     4,
        "set":        "wolf_hide",
        "components": {"Wolf Pelt": 1},
        "gold_costs": {"poor": 25, "normal": 20, "uncommon": 12, "rare": 7},
        "flavor":     "Heavy across the shoulders. Sheds the cold and most casual blades.",
    },
    "Wolf-Hide Jerkin": {
        "slot":       "armor",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    2,
        "max_hp":     5,
        "set":        "wolf_hide",
        "components": {"Wolf Pelt": 2},
        "gold_costs": {"poor": 35, "normal": 25, "uncommon": 18, "rare": 10},
        "flavor":     "Two pelts stitched into a layered jerkin. Lighter than mail, warmer than wool.",
    },
    "Wolf-Tooth Charm": {
        "slot":       "accessory",
        "atk_min":    1,
        "atk_max":    1,
        "defence":    0,
        "max_hp":     2,
        "set":        "wolf_hide",
        "components": {"Wolf Pelt": 1, "Javelina Tusk": 1},
        "gold_costs": {"poor": 30, "normal": 22, "uncommon": 15, "rare": 8},
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
        "components": {"Dire Wolf Pelt": 1},
        "gold_costs": {"poor": 25, "normal": 20, "uncommon": 15, "rare": 10},
        "flavor":     "A heavy hood crowned with the alpha's skull-plate. Eyes peer out from a snarl frozen in death.",
    },
    "Dire Wolf Cloak": {
        "slot":       "cape",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    2,
        "max_hp":     5,
        "set":        "dire_wolf",
        "components": {"Dire Wolf Pelt": 1},
        "gold_costs": {"poor": 30, "normal": 25, "uncommon": 17, "rare": 12},
        "flavor":     "The full hide draped across both shoulders. Even the cold remembers what it was.",
    },
    "Dire Wolf Jerkin": {
        "slot":       "armor",
        "atk_min":    0,
        "atk_max":    0,
        "defence":    3,
        "max_hp":     6,
        "set":        "dire_wolf",
        "components": {"Dire Wolf Pelt": 2},
        "gold_costs": {"poor": 40, "normal": 30, "uncommon": 23, "rare": 15},
        "flavor":     "Two dire pelts layered and reinforced. The seams alone could turn a blade.",
    },
    "Dire Wolf Talisman": {
        "slot":       "accessory",
        "atk_min":    1,
        "atk_max":    1,
        "defence":    0,
        "max_hp":     3,
        "set":        "dire_wolf",
        "components": {"Dire Wolf Pelt": 1, "Soul Pendant": 1},
        "gold_costs": {"poor": 35, "normal": 27, "uncommon": 20, "rare": 13},
        "flavor":     "A soul-bound pendant wrapped in dire wolf hide. The pendant hums; the hide remembers the hunt.",
    },
}

# Names of all Dire Wolf pieces (for set-detection)
DIRE_WOLF_PIECE_NAMES = set(DIRE_WOLF_RECIPES.keys())

# Combined catalog so the recipe menu can iterate both sets cleanly
ALL_RECIPES = {}
ALL_RECIPES.update(WOLF_HIDE_RECIPES)
ALL_RECIPES.update(DIRE_WOLF_RECIPES)


# Discount tier order — used to find the highest-rarity input across components
RARITY_ORDER = ["poor", "normal", "uncommon", "rare"]


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


def make_crafted_item(name, recipe):
    """
    Build a shared.Equipment instance from a recipe dict. Imported lazily
    to avoid a circular import at module load time.

    Public API (v0.6.16) — also callable from the debug menu's loot grant
    flow to give crafted set pieces directly without going through the
    crafter UI.
    """
    from shared import Equipment
    return Equipment(
        name     = name,
        slot     = recipe["slot"],
        rarity   = "normal",        # crafted gear is always rarityless — "normal" is the display token
        atk_min  = recipe["atk_min"],
        atk_max  = recipe["atk_max"],
        defence  = recipe["defence"],
        max_hp   = recipe["max_hp"],
    )


# Internal alias kept so existing calls inside crafter.py don't break.
# Can be removed if you grep and replace all _make_equipment( -> make_crafted_item(
_make_equipment = make_crafted_item


# ============================================================
# STOCK GENERATION
# ============================================================

def _roll_wildcard_rarity():
    """Weighted pick: poor 40 / uncommon 40 / rare 20."""
    total = sum(w for _, w in WILDCARD_RARITY_WEIGHTS)
    r = random.randint(1, total)
    cum = 0
    for rarity, weight in WILDCARD_RARITY_WEIGHTS:
        cum += weight
        if r <= cum:
            return rarity
    return "poor"  # safety fallback


def generate_crafter_stock():
    """
    Build a fresh stock dict for one crafter visit.

    Each component type gets:
      - a guaranteed Normal-rarity listing (stock = 2)
      - one wildcard listing at Poor/Uncommon/Rare (stock = 2)

    Returns:
        {
          "components": {
            "Wolf Pelt": [
              {"rarity": "normal", "price": 18, "stock": 2, "sold": 0},
              {"rarity": "uncommon", "price": 35, "stock": 2, "sold": 0},
            ],
            ...
          },
        }
    """
    stock = {"components": {}}
    for comp_name in COMPONENT_TYPES:
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

def _make_component(comp_name, rarity):
    """
    Build a component Equipment instance. Components are normal drop items
    (Wolf Pelt etc.) — we mirror the make_loot() construction over in main,
    but simplified since the crafter doesn't deal with effects, just stats.

    For components that have rarity-scaled stat tables in main (pelts, sacs,
    tusks, pendants), we look up the table from __main__. If main is not
    importable (testing context), we return a stub Equipment with no stats.
    """
    import sys
    from shared import Equipment
    main = sys.modules.get("__main__")

    # Pelts (armor slot)
    if comp_name == "Wolf Pelt" and main and hasattr(main, "WOLF_PELT_STATS"):
        stats = main.WOLF_PELT_STATS[rarity]
        return Equipment(name="Wolf Pelt", slot="armor", rarity=rarity,
                         defence=stats["defence"], max_hp=stats["max_hp"])
    if comp_name == "Dire Wolf Pelt" and main and hasattr(main, "DIRE_WOLF_PELT_STATS"):
        stats = main.DIRE_WOLF_PELT_STATS[rarity]
        return Equipment(name="Dire Wolf Pelt", slot="armor", rarity=rarity,
                         defence=stats["defence"], max_hp=stats["max_hp"])

    # Sacs (accessory slot)
    if comp_name == "Poison Sac" and main and hasattr(main, "POISON_SAC_STATS"):
        s = main.POISON_SAC_STATS[rarity]
        return Equipment(name="Poison Sac", slot="accessory", rarity=rarity,
                         element="poison", element_damage=s[0],
                         element_turns=s[1], element_max_dots=s[3])
    if comp_name == "Fire Sac" and main and hasattr(main, "FIRE_SAC_STATS"):
        s = main.FIRE_SAC_STATS[rarity]
        return Equipment(name="Fire Sac", slot="accessory", rarity=rarity,
                         element="fire", element_damage=s[0],
                         element_turns=s[1], element_max_dots=s[3])
    if comp_name == "Acid Sac" and main and hasattr(main, "ACID_SAC_STATS"):
        s = main.ACID_SAC_STATS[rarity]
        return Equipment(name="Acid Sac", slot="accessory", rarity=rarity,
                         element="acid", element_damage=s[0],
                         element_turns=s[1], element_restore=s[2],
                         element_max_dots=s[3], element_erosion=s[4])

    # Javelina Tusk (weapon slot — already in main)
    if comp_name == "Javelina Tusk" and main and hasattr(main, "JAVELINA_TUSK_STATS"):
        s = main.JAVELINA_TUSK_STATS[rarity]
        return Equipment(name="Javelina Tusk", slot="weapon", rarity=rarity,
                         atk_min=s["atk_min"], atk_max=s["atk_max"],
                         bleed_turns=s["bleed_turns"],
                         bleed_dmg_min=s["bleed_dmg_min"],
                         bleed_dmg_max=s["bleed_dmg_max"])

    # Soul Pendant (accessory)
    if comp_name == "Soul Pendant" and main and hasattr(main, "SOUL_PENDANT_STATS"):
        s = main.SOUL_PENDANT_STATS[rarity]
        return Equipment(name="Soul Pendant", slot="accessory", rarity=rarity,
                         drain_bonus=s["drain_bonus"],
                         drain_heal_min=s["drain_heal_min"],
                         drain_heal_max=s["drain_heal_max"])

    # Fallback: bare Equipment with no stats (shouldn't hit in normal play)
    return Equipment(name=comp_name, slot="accessory", rarity=rarity)


# ============================================================
# RECIPE EXECUTION
# ============================================================

def _count_inventory(warrior, name):
    """Count how many items with this name the warrior has in inventory."""
    return sum(1 for it in warrior.inventory if getattr(it, "name", "") == name)


def _highest_input_rarity(warrior, recipe):
    """
    For the components this recipe needs, find the HIGHEST rarity the player
    has enough of in inventory. That determines the crafting discount.

    Returns rarity string, or None if the player doesn't have enough components.
    """
    # For each rarity tier (high to low), check whether the player has
    # enough of EVERY required component at that tier or higher.
    for tier in reversed(RARITY_ORDER):  # rare, uncommon, normal, poor
        ok = True
        for comp_name, needed in recipe["components"].items():
            # Count items of this name at this tier OR HIGHER
            higher_tiers = RARITY_ORDER[RARITY_ORDER.index(tier):]
            have = sum(1 for it in warrior.inventory
                       if getattr(it, "name", "") == comp_name
                       and getattr(it, "rarity", "normal") in higher_tiers)
            if have < needed:
                ok = False
                break
        if ok:
            return tier
    return None


def _can_afford_recipe(warrior, recipe):
    """
    Returns (can_craft: bool, missing_components: list[str], discount_rarity: str|None, cost: int)
    """
    missing = []
    for comp_name, needed in recipe["components"].items():
        have = _count_inventory(warrior, comp_name)
        if have < needed:
            missing.append(f"{needed - have}x {comp_name}")
    if missing:
        return (False, missing, None, recipe["gold_costs"]["poor"])

    discount_rarity = _highest_input_rarity(warrior, recipe)
    cost = recipe["gold_costs"][discount_rarity] if discount_rarity else recipe["gold_costs"]["poor"]
    return (warrior.gold >= cost, [], discount_rarity, cost)


def _consume_components(warrior, recipe, prefer_rarity):
    """
    Remove the recipe's required components from inventory. Prefers the
    LOWEST-rarity items first (so the player keeps their best drops for
    discount on future crafts).
    """
    for comp_name, needed in recipe["components"].items():
        # Sort the player's matching items by rarity (lowest first)
        matching = [it for it in warrior.inventory if getattr(it, "name", "") == comp_name]
        matching.sort(key=lambda it: RARITY_ORDER.index(getattr(it, "rarity", "normal"))
                      if getattr(it, "rarity", "normal") in RARITY_ORDER else 0)
        for _ in range(needed):
            warrior.inventory.remove(matching[0])
            matching.pop(0)


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


def _craft_recipe(warrior, recipe_name, recipe):
    """Execute one craft. Assumes affordability has already been checked."""
    can, missing, discount_rarity, cost = _can_afford_recipe(warrior, recipe)
    if not can:
        if missing:
            print(_wrap(f"  You need more: {', '.join(missing)}"))
        else:
            print(_wrap(f"  You can't afford it. Cost: {cost}g, you have {warrior.gold}g."))
        input("\n  Press Enter...")
        return

    print()
    print(_wrap(f"  Craft {recipe_name} for {cost}g using {discount_rarity}-tier materials?"))
    confirm = input("  Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        return

    warrior.gold -= cost
    _consume_components(warrior, recipe, discount_rarity)

    crafted = _make_equipment(recipe_name, recipe)
    warrior.inventory.append(crafted)

    print()
    print(_wrap(f"  ✅ Crafted: {recipe_name}"))
    print(_wrap(f"     {recipe['flavor']}"))

    # v0.6.18: Check if this craft completed a 4-piece set
    _check_set_completion_titles(warrior, recipe_name)

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

    warrior.gold -= listing["price"]
    listing["sold"] += 1
    item = _make_component(comp_name, listing["rarity"])
    warrior.inventory.append(item)
    print()
    print(_wrap(f"  ✅ Bought: {rarity_word} {comp_name}"))
    input("\n  Press Enter...")


def _show_components_menu(stock, warrior):
    print("=" * 52)
    print(f"  🪡 Crafter — Component Stock   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()
    print(_wrap("  'These are what I can spare today. Every visit's different —"))
    print(_wrap("   what's here is here. Use it or come back tomorrow.'"))
    print()

    actions = {}
    idx = 1
    for comp_name in COMPONENT_TYPES:
        listings = stock["components"][comp_name]
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
    print()
    print("  Enter component number to buy, or 0 to go back.")
    return actions


def _component_stock_loop(warrior, stock):
    while True:
        _clear_screen()
        actions = _show_components_menu(stock, warrior)
        raw = input("  > ").strip()
        if raw == "0" or raw == "":
            return
        action = actions.get(raw)
        if not action:
            continue
        comp_name, li_idx = action
        _buy_component(warrior, stock, comp_name, li_idx)


# ============================================================
# UI — RECIPE MENU
# ============================================================

def _show_recipes_menu(warrior):
    print("=" * 52)
    print(f"  🔨 Crafter — Recipes   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1

    # ----- Helper: render one set's section -----
    def _render_set_section(set_label, recipes_dict, header_text):
        nonlocal idx
        print(_wrap(f"  {header_text}"))
        print()
        for name, recipe in recipes_dict.items():
            can, missing, discount_rarity, cost = _can_afford_recipe(warrior, recipe)

            # Component requirement line
            req = " + ".join(f"{n}x {c}" for c, n in recipe["components"].items())

            # Build the status segment
            if missing:
                status = f"need {', '.join(missing)}"
            elif not can:
                status = f"{cost}g (need {cost - warrior.gold} more)"
            else:
                disc_word = discount_rarity.title() if discount_rarity else "Poor"
                status = f"{cost}g  [{disc_word}-tier discount]"

            # Equipped marker
            equipped = any(it is not None and getattr(it, "name", "") == name
                           for it in warrior.equipment.values())
            owned    = any(getattr(it, "name", "") == name for it in warrior.inventory)
            marker = " [EQUIPPED]" if equipped else (" [in bag]" if owned else "")

            print(f"  {idx:>2}) {name:<22}{marker}")
            print(f"      {req:<32} {status}")
            actions[str(idx)] = name
            idx += 1
            print()

    # ----- Wolf-Hide set (tier 1) -----
    _render_set_section("wolf_hide",
                        WOLF_HIDE_RECIPES,
                        "WOLF-HIDE SET — Tier 1 (full set unlocks Pack Hunter)")

    # ----- Dire Wolf set (tier 2) - v0.6.16 -----
    _render_set_section("dire_wolf",
                        DIRE_WOLF_RECIPES,
                        "DIRE WOLF SET — Tier 2 (full set unlocks Apex Predator)")

    print(f"  Wolf-Hide pieces equipped: {wolf_set_active_pieces(warrior)}/4")
    print(f"  Dire Wolf pieces equipped: {dire_wolf_set_active_pieces(warrior)}/4")
    print()
    print("  Enter recipe number to craft, or 0 to go back.")
    return actions


def _recipe_loop(warrior):
    while True:
        _clear_screen()
        actions = _show_recipes_menu(warrior)
        raw = input("  > ").strip()
        if raw == "0" or raw == "":
            return
        recipe_name = actions.get(raw)
        if not recipe_name:
            continue
        recipe = ALL_RECIPES[recipe_name]   # v0.6.16: look up from combined catalog
        _craft_recipe(warrior, recipe_name, recipe)


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
# Socket count table (unchanged from v0.6.16):
#   Normal/Uncommon  → 1 socket
#   Rare/Epic/Legendary/Mythril → 2 sockets
#   (Poor armor doesn't exist in the loot tables, so no Poor entry.)
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
SOCKETABLE_INTO_WEAPON = {
    "Poison Sac", "Fire Sac", "Acid Sac",
    "Javelina Tusk", "Soul Pendant",
}


def socket_nerf_chance(base_chance):
    """Apply the 75% nerf to a chance value (0.0-1.0)."""
    return base_chance * SOCKET_POWER_RATIO


def socket_nerf_damage(base_damage):
    """Apply the 75% nerf to a damage value, rounded down, min 1 if base > 0."""
    if base_damage <= 0:
        return 0
    return max(1, int(base_damage * SOCKET_POWER_RATIO))


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
        elif name == "Javelina Tusk":
            # Tusk has implicit 100% bleed — apply 75% chance, 75% damage
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
    warrior.gold -= SOCKET_OPERATION_COST
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
    warrior.gold -= SOCKET_OPERATION_COST
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
        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return
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
            sockables = _socketable_items_in_inventory(warrior)
            if not sockables:
                print(_wrap("  You have nothing socketable in your bag."))
                print(_wrap("  Try buying Sacs, Tusks, or a Soul Pendant from the component stock."))
                input("\n  Press Enter...")
                continue
            print(_wrap(f"  Pick something to slot in (costs {SOCKET_OPERATION_COST}g):"))
            for i, it in enumerate(sockables):
                print(f"    {i+1}) {it.short_label()}")
            print("    0) Cancel")
            pick = input("  > ").strip()
            if pick == "0" or pick == "":
                continue
            if not pick.isdigit():
                continue
            pi = int(pick) - 1
            if 0 <= pi < len(sockables):
                _socket_item_into_weapon(warrior, weapon, socket_idx, sockables[pi])
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
    v0.6.20: Mirror of _weapons_with_sockets_in_inventory for armor.
    Returns list of (label, item) for armor pieces with socket capacity.
    Scans both equipped armor slots and inventory. Used by the Phase-2
    coming-soon preview only — no combat hooks read this yet.

    "Armor" here means any item with slot == "armor". Crafted helm/cape
    pieces use slot == "helm" / "cape" and aren't socketable in the
    Phase 2 design (only the chest armor slot is). Adjust this filter
    when Phase 2 expands the slot list.
    """
    candidates = []
    # Equipped armor (just the chest slot for now)
    equipped = warrior.equipment.get("armor")
    if equipped is not None and getattr(equipped, "slot", None) == "armor":
        if equipped.socket_count() > 0:
            candidates.append((f"{equipped.short_label()} [equipped]", equipped))
    # Inventory armor
    for it in warrior.inventory:
        if getattr(it, "slot", "") != "armor":
            continue
        if it.socket_count() > 0:
            candidates.append((f"{it.short_label()} [in bag]", it))
    return candidates


def _armor_socket_preview(warrior):
    """
    v0.6.20: Coming-soon UI for armor sockets. Lists the player's
    socketable armor with current socket counts so they can see what
    Phase 2 will activate. Always returns to the socket front-menu.

    No mutation, no charges, no equipment changes. Pure preview.
    """
    _clear_screen()
    print("=" * 52)
    print(f"  💎 Crafter — Armor Sockets   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()
    print(_wrap(
        "  The crafter shakes their head. 'Armor sockets — aye, the "
        "thought's there. Got the holes punched, but the runes to "
        "make them sing? Not yet. Come back later.'"
    ))
    print()
    print("  ── COMING SOON ──")
    print()

    candidates = _armor_with_sockets_in_inventory(warrior)
    if not candidates:
        print(_wrap(
            "  You have no socketable armor. Normal-rarity and higher "
            "armor pieces have sockets; Poor-quality armor (rare to "
            "find) does not."
        ))
    else:
        print(_wrap("  Your socketable armor (preview — sockets inert until Phase 2):"))
        print()
        for label, item in candidates:
            n = item.socket_count()
            socket_word = "socket" if n == 1 else "sockets"
            print(f"  • {label}")
            print(f"      {n} {socket_word}  {_format_sockets(item)}")
        print()
        print(_wrap(
            "  Planned items for armor sockets: Javelina Tusk "
            "(retaliation bleed when you're hit) and Soul Amulet "
            "(absorb incoming damage, heal back a portion)."
        ))

    print()
    input("  Press Enter to return to the socketing menu...")


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
        print("  2) Armor  💤 (coming soon)")
        print()
        print("  0) Back")
        print()
        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return
        elif choice == "1":
            _weapon_socket_loop(warrior)
        elif choice == "2":
            _armor_socket_preview(warrior)


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
        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return
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
        print("  0) Leave")
        print()
        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            print()
            print(_wrap("  'Come back when you have more materials.'"))
            input("\n  Press Enter...")
            return stock
        elif choice == "1":
            _component_stock_loop(warrior, stock)
        elif choice == "2":
            _recipe_loop(warrior)
        elif choice == "3":   # v0.6.16
            _socket_loop(warrior)
