"""
merchant.py
-----------
Arena merchant — the round 4-5 interlude shop.

Single-visit store. Stock is generated once when the merchant scene fires
and persists for the duration of that visit. The player can buy items,
sell unwanted equipment back at half price, and stock up on potions
before the final fight.

What the merchant SELLS:
    - 3 weapons   — random from MERCHANT_WEAPONS pool, each with rarity roll
    - 2 armors    — random from 4 fixed-tier merchant-only basics
    - 2 rings     — random from 5 fixed-stat merchant-only basics (includes
                    Adrenaline Ring, which used to be a trinket)
    - 1 trinket   — Trinket of Berserk (one-shot crush-for-berserk)
    - Potions     — full tier 1-2 lineup + Cure-All, Elixir, and the new
                    Skill/Stat progression potions, 2-3 each

What the merchant DOES NOT sell or buy:
    - Crafting components (pelts, sacs, tusks, etc.) — the future crafter
      will handle those. Merchant politely refuses with a flavor line.
    - Mega/Full potions — too premium for an arena vendor.
    - Boss drops (Patronus / Chimera / Weapon Core) — story significance.

Pricing is anchored against ~60g typical run payout: basic potions 5-10g,
mid-tier items 15-30g, premium items 50-80g. Tier 4 armor at 80g is
intentionally aspirational.

Sell-back is half buy-price (rounded down on each item). Crafting components
in inventory are listed in the sell menu but blocked from sale, with a hint
that they're for the crafter.

DESIGN PHILOSOPHY:
- Merchant armors are DEF-only — the crafted armors (using pelts and other
  components) will provide HP. This keeps store-bought as the dependable
  baseline and crafted as the upgrade path.
- Merchant rings are single-stat, no rarity. They're the "I need
  exactly +2 ATK right now" option and live in the two finger slots.
- Merchant trinkets buy into the adrenaline/berserk systems
  (passive +adrenaline cap, or one-shot crush-for-berserk). Drop-table
  trinkets (Charged Jagged Rock, Waterlogged Stone) carry the rarity
  rolls and complex charge effects.

Public API:
    merchant_scene(warrior)       — full UI loop, called from the interlude
    generate_merchant_stock()     — returns the stock dict {equipment, potions}

Why this lives in its own module:
    The arena_quarters_interlude in main.py is already a large hub. Keeping
    the shop logic here mirrors gold.py / score.py / titles.py.
"""

import random


# ============================================================
# CONFIG — pricing
# ============================================================

# v0.6.19: Equipment price is now (rarity_base × tier_multiplier).
# Pre-v0.6.19 every weapon at the same rarity cost the same gold —
# a Goblin Dagger normal (1-1 ATK) cost the same as a Goblin War Blade
# normal (3-3 + bleed), which made shopping decisions pointless. New
# scheme tags weapons with a tier (1, 2, or 3) and multiplies the
# rarity base.
#
#   Tier 1 (×1.0): basic weapons — Rusted Sword, Imp Trident, Goblin Dagger
#   Tier 2 (×2.0): mid weapons — Javelina Tusk
#   Tier 3 (×3.0): top weapons — Goblin War Blade, Goblin Shortbow
#
# Anchored to 10/20/30 at normal rarity, curve scales smoothly to mythril.
# Sell-back is half of buy price (SELL_BACK_RATE = 0.5).

EQUIPMENT_RARITY_BASE_PRICES = {
    "poor":       5,
    "normal":    10,
    "uncommon":  20,
    "rare":      35,
    "epic":      60,
    "legendary":100,
    "mythril":  160,
}

# Tier multipliers — applied to the rarity base.
EQUIPMENT_TIER_MULTIPLIERS = {
    1: 1.0,
    2: 2.0,
    3: 3.0,
}

# Legacy table retained for any code paths that haven't been migrated to
# the tier-aware helper. Values match T1 (×1.0). Prefer _equipment_price().
EQUIPMENT_RARITY_PRICES = {
    "poor":      5,
    "normal":   10,
    "uncommon": 20,
    "rare":     35,
    "epic":     60,
    "legendary":100,
    "mythril":  160,
}


def _equipment_price(item):
    """
    Compute buy-price for an Equipment using its rarity AND tier.
    Falls back to T1 multiplier if tier attribute is missing or unknown.
    """
    rarity = getattr(item, "rarity", "normal")
    tier   = getattr(item, "tier", 1) or 1
    base   = EQUIPMENT_RARITY_BASE_PRICES.get(rarity, 10)
    mult   = EQUIPMENT_TIER_MULTIPLIERS.get(tier, 1.0)
    return max(1, int(round(base * mult)))

POTION_PRICES = {
    "heal":           8,    # 25% HP
    "super_potion":  20,   # 50% HP
    "ap":            10,    # 25% AP
    "super_ap":      25,    # 50% AP
    "antidote":       5,    # cure poison
    "burn_cream":     5,    # clear fire stacks
    "cure_all":      15,    # all physical statuses
    "elixir":        30,    # 50% HP + 50% AP combo
    # ── Progression potions (v0.6.13) — out-of-combat only ──
    "skill_rank_up": 50,    # rank up one learned skill by 1 (bypasses SP cost)
    "stat_point":    50,    # +2 stat points (player assigns immediately)
    "skill_point":   35,    # +2 skill points (player spends immediately)
}

POTION_STOCK_COUNT = {
    "heal":          3,
    "super_potion":  2,
    "ap":            3,
    "super_ap":      2,
    "antidote":      2,
    "burn_cream":    2,
    "cure_all":      2,
    "elixir":        2,
    # Progression potions are rarer — premium offering
    "skill_rank_up": 1,
    "stat_point":    1,
    "skill_point":   1,
}

SELL_BACK_RATE = 0.5

# Weapon variant rolls.
#
# For each weapon TYPE drawn into the merchant's stock, the merchant always
# offers a NORMAL rarity version (guaranteed). On top of that, two
# independent rolls determine whether the same weapon also appears at
# higher tiers:
#   - UNCOMMON variant: 50% chance
#   - RARE variant:     25% chance
#
# So each weapon slot expands into 1-3 listings of the same item type,
# letting the player pick the rarity their gold can afford. This replaces
# the old "one rarity per slot, weighted random" model.
#
# Example outcomes per weapon type:
#   - normal only                    (75% × 50% = ~37.5%)
#   - normal + uncommon              (50% × 75% = ~37.5%)
#   - normal + rare                  (50% × 25% = ~12.5%)
#   - normal + uncommon + rare       (50% × 25% = ~12.5%)
#
# Across 3 weapon types per visit:
#   - Min total weapon listings:  3 (3 normals only)
#   - Max total weapon listings:  9 (every variant rolls yes)
#   - Avg total weapon listings:  3 + 1.5 + 0.75 = 5.25
#
# This is a single-visit shop (round 4-5 only), so the buff has no
# compounding effect — the player gets one shot at this rolling.
MERCHANT_VARIANT_CHANCE = {
    "uncommon": 0.50,
    "rare":     0.25,
}


# ============================================================
# CONFIG — what the merchant carries (and won't)
# ============================================================

CRAFTING_COMPONENT_NAMES = {
    "Wolf Pelt",
    "Dire Wolf Pelt",       # was armor in v0.6.x — now component
    "Poison Sac",
    "Fire Sac",
    "Acid Sac",
    "Soul Pendant",
    "Javelina Tusk",
}

NO_RESALE_NAMES = {
    "Tainted Champion's Breastplate",
    "Chimera Scale",
    "Lightrender",
    "Destiny Definer",
    "Walking Staff",
    "Frostpine Tonic",
}


# ============================================================
# MERCHANT-ONLY ARMORS — 4 fixed tiers, no rarity, DEF-only
# ============================================================
#
# Tier 1-3 follow copper / bronze / iron metallurgy. Tier 4 (Frost-iron)
# ties to the world's frost-and-ash atmosphere — aspirational buy.
#
# DEF-only — crafted armors (using Wolf Pelt etc.) will provide HP. Keeps
# store-bought as the baseline, crafted as the upgrade path.
#
# Format: (name, defence, max_hp, price)
MERCHANT_ARMORS = [
    ("Copper Scale Vest",   1, 0, 10),  # v0.6.16: 30% cut to fit ~60g/run economy
    ("Bronze Hauberk",      2, 0, 20),
    ("Iron Cuirass",        3, 0, 35),
    ("Frost-iron Cuirass",  4, 0, 55),
]


# ============================================================
# MERCHANT-ONLY SHIELDS — wooden shield line, 4 fixed tiers, no rarity
# ============================================================
#
# Shields occupy a hand slot (main_hand or off_hand). Equipping a shield while
# a 2-handed weapon is held is blocked at equip-time.
#
# Wood-themed across the line: from soft pine through near-magical ashen.
# Mirrors merchant armor in DEF and price, so the player can layer armor+
# shield for total DEF, paying per-slot. 2H weapon users lose shield access
# entirely — that's the offensive/defensive tradeoff.
#
# Stocked 2-per-visit, weighted toward cheap (Pine/Oak most common, Ashen
# rarest). Always normal rarity, no variants.
#
# Format: (name, defence, max_hp, price, draw_weight)
MERCHANT_SHIELDS = [
    ("Pine Shield",     1, 0, 10, 40),  # cheapest, most common in stock
    ("Oak Shield",      2, 0, 20, 30),
    ("Ironwood Shield", 3, 0, 35, 20),
    ("Ashen Shield",    4, 0, 55, 10),  # premium, rarest in stock
]


# ============================================================
# MERCHANT-ONLY RINGS — 5 fixed-stat, no rarity variants
# ============================================================
#
# Rings occupy the two finger slots. Each gives a clean single-stat
# boost. Use case: "I need +2 ATK right now" or "I need a flat HP
# bump for the final fight." Two rings can be worn at once.
#
# Most of these used to be merchant trinkets — they got moved to the ring slot
# when the dedicated trinket slot was reserved for charge/consumable
# mechanics (Charged Jagged Rock, Waterlogged Stone, Trinket of Berserk).
#
# Adrenaline Ring (was "Trinket of Adrenaline") joined the rings in v0.6.13.
# It's a passive max_rage cap boost — slot-agnostic on equip, so it works
# perfectly on a finger. Berserk stayed as a trinket because its "crush"
# one-shot mechanic is the trinket slot's defining feature.
#
# Format: (name, defence, max_hp, atk_min, atk_max, max_ap_bonus, max_rage_bonus, price)
MERCHANT_RINGS = [
    ("Stoneheart Pendant",  0, 10, 0, 0, 0, 0, 25),  # +10 max HP
    ("Tiger Fang",          0,  0, 2, 2, 0, 0, 30),  # +2 min/max ATK
    ("Stoneskin Band",      2,  0, 0, 0, 0, 0, 25),  # +2 DEF  (was "Stoneskin Trinket")
    ("Spirit Crystal",      0,  0, 0, 0, 2, 0, 30),  # +2 max AP
    ("Adrenaline Ring",     0,  0, 0, 0, 0, 2, 20),  # +2 adrenaline cap (was "Trinket of Adrenaline")
]


# ============================================================
# MERCHANT-ONLY TRINKETS — one-shot consumable utility
# ============================================================
#
# Trinkets are the "active utility" slot. Drop-table trinkets carry
# charges or complex mechanics (Charged Jagged Rock, Waterlogged Stone).
# The Berserk trinket gives a one-shot panic-button for the rage system.
#
# Adrenaline migrated to MERCHANT_RINGS in v0.6.13 — passive stats fit the
# ring slot, while the trinket slot now exclusively holds active mechanics.
#
# Format: (name, max_rage_bonus, consume_on_use, price)
MERCHANT_TRINKETS = [
    ("Trinket of Berserk",    0, True,  45),  # one-shot: crush → 2-turn berserk
]


# ============================================================
# MAIN-MODULE INTEROP
# ============================================================

_FACTORIES_CACHE = None


def _find_main_module():
    """Locate the loaded main game module via __main__ or sys.modules scan."""
    import sys
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "Equipment") and hasattr(main, "make_loot"):
        return main
    for mod in sys.modules.values():
        if mod is None:
            continue
        if hasattr(mod, "Equipment") and hasattr(mod, "make_loot"):
            return mod
    return None


def _make_fixed_armor_factory(name, defence, max_hp):
    """Build a factory closure for a fixed-stat merchant armor."""
    def factory(rarity):  # rarity ignored — fixed tier
        Equipment = _find_main_module().Equipment
        return Equipment(
            name    = name,
            slot    = "armor",
            rarity  = "normal",
            defence = defence,
            max_hp  = max_hp,
        )
    return factory


def _make_fixed_shield_factory(name, defence, max_hp):
    """v0.6.16: Factory for fixed-stat merchant shield. Slot='shield' —
    Equipment carries the shield slot type, but equip_item routes shields
    into main_hand or off_hand just like rings route to finger_1/2."""
    def factory(rarity):  # rarity ignored — fixed tier
        Equipment = _find_main_module().Equipment
        return Equipment(
            name    = name,
            slot    = "shield",
            rarity  = "normal",
            defence = defence,
            max_hp  = max_hp,
        )
    return factory


def _make_fixed_ring_factory(name, defence, max_hp, atk_min, atk_max, max_ap_bonus, max_rage_bonus):
    """Build a factory closure for a fixed-stat merchant ring."""
    def factory(rarity):  # rarity ignored — fixed stats
        Equipment = _find_main_module().Equipment
        return Equipment(
            name           = name,
            slot           = "ring",
            rarity         = "normal",
            defence        = defence,
            max_hp         = max_hp,
            atk_min        = atk_min,
            atk_max        = atk_max,
            max_ap_bonus   = max_ap_bonus,
            max_rage_bonus = max_rage_bonus,
        )
    return factory


def _make_fixed_trinket_factory(name, max_rage_bonus, consume_on_use):
    """Build a factory closure for a fixed-stat merchant trinket."""
    def factory(rarity):  # rarity ignored — fixed stats
        Equipment = _find_main_module().Equipment
        return Equipment(
            name           = name,
            slot           = "trinket",
            rarity         = "normal",
            max_rage_bonus = max_rage_bonus,
            consume_on_use = consume_on_use,
        )
    return factory


def _build_factories():
    """
    Build the slot → list of (item_name, factory) registry. Each factory
    takes a rarity string and returns an Equipment instance.

    Not refactoring main.make_loot's lambdas. The merchant pool is curated:
      - Javelina Tusk is now a crafting component (excluded).
      - Sacs / Soul Pendant / pelts moved to crafting components.
      - Boss / legendary drops excluded.
      - Plus 4 brand-new merchant-only armors and trinkets.
    """
    main = _find_main_module()
    if main is None:
        raise ImportError(
            "merchant.py could not locate the main game module. "
            "Make sure merchant_scene is called from within the running game."
        )

    Equipment = main.Equipment

    return {
        "weapon": [
            ("Rusted Sword", lambda r: Equipment(
                name             = "Rusted Sword",
                slot             = "weapon",
                rarity           = r,
                atk_min          = main.RUSTED_SWORD_STATS[r]["atk_min"],
                atk_max          = main.RUSTED_SWORD_STATS[r]["atk_max"],
                defence          = main.RUSTED_SWORD_STATS[r]["defence"],
                rot_chance       = main.RUSTED_SWORD_STATS[r]["rot_chance"],
                rot_stacks       = main.RUSTED_SWORD_STATS[r]["rot_stacks"],
                rot_hp_per_stack = main.RUSTED_SWORD_STATS[r]["rot_hp_per_stack"],
            )),
            ("Imp Trident", lambda r: Equipment(
                name        = "Imp Trident",
                slot        = "weapon",
                rarity      = r,
                atk_min     = main.IMP_TRIDENT_STATS[r]["atk_min"],
                atk_max     = main.IMP_TRIDENT_STATS[r]["atk_max"],
                proc_chance = main.IMP_TRIDENT_STATS[r]["proc_chance"],
                proc_bonus  = main.IMP_TRIDENT_STATS[r]["proc_bonus"],
            )),
            ("Goblin Dagger", lambda r: Equipment(
                name         = "Goblin Dagger",
                slot         = "weapon",
                rarity       = r,
                atk_min      = main.GOBLIN_DAGGER_STATS[r]["atk_min"],
                atk_max      = main.GOBLIN_DAGGER_STATS[r]["atk_max"],
                blind_chance = main.GOBLIN_DAGGER_STATS[r]["blind_chance"],
            )),
            ("Goblin Shortbow", lambda r: Equipment(
                name            = "Goblin Shortbow",
                slot            = "weapon",
                rarity          = r,
                atk_min         = main.GOBLIN_SHORTBOW_STATS[r]["atk_min"],
                atk_max         = main.GOBLIN_SHORTBOW_STATS[r]["atk_max"],
                paralyze_chance = main.GOBLIN_SHORTBOW_STATS[r]["paralyze_chance"],
                paralyze_turns  = main.GOBLIN_SHORTBOW_STATS[r]["paralyze_turns"],
            )),
            ("Goblin War Blade", lambda r: Equipment(
                name          = "Goblin War Blade",
                slot          = "weapon",
                rarity        = r,
                atk_min       = main.GOBLIN_WAR_BLADE_STATS[r]["atk_min"],
                atk_max       = main.GOBLIN_WAR_BLADE_STATS[r]["atk_max"],
                bleed_turns   = main.GOBLIN_WAR_BLADE_STATS[r]["bleed_turns"],
                bleed_dmg_min = main.GOBLIN_WAR_BLADE_STATS[r]["bleed_dmg_min"],
                bleed_dmg_max = main.GOBLIN_WAR_BLADE_STATS[r]["bleed_dmg_max"],
            )),
            # Javelina Tusk REMOVED — now a crafting component.
        ],
        "armor": [
            (name, _make_fixed_armor_factory(name, defence, max_hp))
            for (name, defence, max_hp, _price) in MERCHANT_ARMORS
        ],
        "shield": [
            (name, _make_fixed_shield_factory(name, defence, max_hp))
            for (name, defence, max_hp, _price, _weight) in MERCHANT_SHIELDS
        ],
        "ring": [
            (name, _make_fixed_ring_factory(name, defence, max_hp, atk_min, atk_max, max_ap_bonus, max_rage_bonus))
            for (name, defence, max_hp, atk_min, atk_max, max_ap_bonus, max_rage_bonus, _price)
            in MERCHANT_RINGS
        ],
        "trinket": [
            (name, _make_fixed_trinket_factory(name, max_rage_bonus, consume_on_use))
            for (name, max_rage_bonus, consume_on_use, _price)
            in MERCHANT_TRINKETS
        ],
    }


def _get_factories():
    global _FACTORIES_CACHE
    if _FACTORIES_CACHE is None:
        _FACTORIES_CACHE = _build_factories()
    return _FACTORIES_CACHE


def _roll_weapon_variants():
    """
    For a single weapon type, decide which rarity variants appear at the
    merchant. Normal is always included. Uncommon and rare are independent
    yes/no rolls per MERCHANT_VARIANT_CHANCE.

    Returns:
        list of rarity strings, in display order: ["normal", ...] possibly
        plus "uncommon" and/or "rare". Always at least one entry.
    """
    variants = ["normal"]
    if random.random() < MERCHANT_VARIANT_CHANCE["uncommon"]:
        variants.append("uncommon")
    if random.random() < MERCHANT_VARIANT_CHANCE["rare"]:
        variants.append("rare")
    return variants


def _potion_label(potion_key):
    """Display name for a potion key."""
    labels = {
        "heal":         "Potion (25% HP)",
        "super_potion": "Super Potion (50% HP)",
        "ap":           "AP Potion (25% AP)",
        "super_ap":     "Super AP Potion (50% AP)",
        "antidote":     "Antidote",
        "burn_cream":   "Burn Cream",
        "cure_all":     "Cure-All Tonic",
        "elixir":       "Elixir (50% HP + 50% AP)",
    }
    return labels.get(potion_key, potion_key.replace("_", " ").title())


# ============================================================
# STOCK GENERATION
# ============================================================

def generate_merchant_stock():
    """
    Roll fresh merchant inventory.

    Equipment:
        Weapons:  3 distinct weapon types drawn. Each type always yields
                  a normal-rarity variant, plus independent rolls for
                  uncommon (50%) and rare (25%) variants of the same
                  weapon. Total weapon listings: 3 (min) to 9 (max),
                  averaging ~5.25. Weapons with multiple variants render
                  as expandable groups in the menu.
        Armors:   2 distinct from the 4 fixed-tier merchant-only armors.
        Rings:    2 distinct from the 5 fixed-stat merchant-only rings.
        Trinkets: 1 (the only merchant trinket: Trinket of Berserk).

    Potions:
        Full POTION_PRICES lineup, each at POTION_STOCK_COUNT count.

    Returns:
        dict with four keys:
            "weapon_groups": list of dicts:
                {
                    "type_name": str,                    # e.g. "Goblin Dagger"
                    "variants": list of dicts:
                        {"item": Equipment, "price": int,
                         "rarity": str, "sold": bool},
                    "expanded": bool,                    # menu-display state
                }
            "armors":   list of {"item": Equipment, "price": int, "sold": bool}
            "trinkets": list of {"item": Equipment, "price": int, "sold": bool}
            "potions":  dict of {potion_key: {"price": int, "stock": int}}
    """
    factories = _get_factories()

    armor_prices   = {a[0]: a[3] for a in MERCHANT_ARMORS}
    shield_prices  = {s[0]: s[3] for s in MERCHANT_SHIELDS}
    shield_weights = {s[0]: s[4] for s in MERCHANT_SHIELDS}
    ring_prices    = {r[0]: r[7] for r in MERCHANT_RINGS}
    trinket_prices = {t[0]: t[3] for t in MERCHANT_TRINKETS}

    # ── WEAPONS — 3 types, each with variant rolls ──
    weapon_groups = []
    weapon_pool   = factories["weapon"]
    weapon_picks  = random.sample(weapon_pool, k=min(3, len(weapon_pool)))
    for type_name, factory in weapon_picks:
        rarities = _roll_weapon_variants()  # always at least ["normal"]
        variants = []
        for rarity in rarities:
            item = factory(rarity)
            variants.append({
                "item":   item,
                # v0.6.19: price now factors weapon tier, not just rarity.
                # Goblin Dagger normal (T1) = 10g, War Blade normal (T3) = 30g.
                "price":  _equipment_price(item),
                "rarity": rarity,
                "sold":   False,
            })
        weapon_groups.append({
            "type_name": type_name,
            "variants":  variants,
            "expanded":  False,
        })

    # ── ARMORS — 2 picks, fixed-tier, no rarity ──
    armors = []
    armor_pool   = factories["armor"]
    armor_picks  = random.sample(armor_pool, k=min(2, len(armor_pool)))
    for name, factory in armor_picks:
        armors.append({
            "item":  factory(None),
            "price": armor_prices.get(name, 30),
            "sold":  False,
        })

    # ── SHIELDS — 2 picks, weighted random (cheap shields appear more often) ──
    # v0.6.16: weighted-without-replacement draw using draw_weight from MERCHANT_SHIELDS.
    # Pine 40 / Oak 30 / Ironwood 20 / Ashen 10 -> Pine ~40% per slot, Ashen ~10%.
    shields = []
    shield_pool = list(factories["shield"])
    for _ in range(min(2, len(shield_pool))):
        if not shield_pool:
            break
        # Weighted pick
        names_left   = [n for n, _ in shield_pool]
        weights_left = [shield_weights.get(n, 10) for n in names_left]
        pick_name    = random.choices(names_left, weights=weights_left, k=1)[0]
        pick_idx     = next(i for i, (n, _) in enumerate(shield_pool) if n == pick_name)
        name, factory = shield_pool.pop(pick_idx)
        shields.append({
            "item":  factory(None),
            "price": shield_prices.get(name, 20),
            "sold":  False,
        })

    # ── RINGS — 2 picks, fixed-stat, no rarity ──
    rings = []
    ring_pool   = factories["ring"]
    ring_picks  = random.sample(ring_pool, k=min(2, len(ring_pool)))
    for name, factory in ring_picks:
        rings.append({
            "item":  factory(None),
            "price": ring_prices.get(name, 25),
            "sold":  False,
        })

    # ── TRINKETS — both available each visit (only 2 in the pool currently) ──
    trinkets = []
    trinket_pool   = factories["trinket"]
    trinket_picks  = random.sample(trinket_pool, k=min(2, len(trinket_pool)))
    for name, factory in trinket_picks:
        trinkets.append({
            "item":  factory(None),
            "price": trinket_prices.get(name, 25),
            "sold":  False,
        })

    potions = {
        key: {"price": POTION_PRICES[key], "stock": POTION_STOCK_COUNT[key]}
        for key in POTION_PRICES
    }

    return {
        "weapon_groups": weapon_groups,
        "armors":        armors,
        "shields":       shields,   # v0.6.16
        "rings":         rings,
        "trinkets":      trinkets,
        "potions":       potions,
    }


# ============================================================
# UI HELPERS
# ============================================================

def _clear_screen():
    import os
    os.system("cls" if os.name == "nt" else "clear")


def _wrap(text):
    """Use main's wrap helper if available, fall back to identity."""
    main = _find_main_module()
    if main and hasattr(main, "wrap"):
        return main.wrap(text)
    return text


def _is_crafting_component(item):
    return getattr(item, "name", "") in CRAFTING_COMPONENT_NAMES


def _is_resale_blocked(item):
    return getattr(item, "name", "") in NO_RESALE_NAMES


def _sell_price(item):
    """
    Resale = half of buy-price. Floor of 1g.

    v0.6.19: factors weapon tier so selling a War Blade no longer pays
    the same as selling a Rusted Sword. Uses the same helper as the buy
    listings so the round-trip math is consistent.
    """
    return max(1, int(_equipment_price(item) * SELL_BACK_RATE))


def _label_for_catalog(item):
    """Single-line label safe for catalog rows."""
    label = item.short_label() if hasattr(item, "short_label") else getattr(item, "name", "???")
    return label.replace("\n", " ").strip()


def _parse_menu_choice(raw):
    """
    Parse a menu input string into (number, suffix).

    Examples:
        "1"   → (1, None)
        "1a"  → (1, "a")
        "12b" → (12, "b")
        "S"   → None      (caller handles non-numeric prefixes)
        ""    → None
        "abc" → None

    Returns None for anything that doesn't start with at least one digit.
    """
    s = raw.strip().lower()
    if not s:
        return None
    # Split: leading digits, then optional single letter
    digits = ""
    i = 0
    while i < len(s) and s[i].isdigit():
        digits += s[i]
        i += 1
    if not digits:
        return None
    suffix = s[i:] if i < len(s) else None
    # Suffix must be a single letter a-z (or None)
    if suffix is not None:
        if len(suffix) != 1 or not suffix.isalpha():
            return None
    return (int(digits), suffix)


# ============================================================
# UI — BUY MENU
# ============================================================

def _show_category_picker(stock, warrior):
    """
    v0.6.16: Top-level merchant menu — pick a category.
    Reorganized from one massive list into 4 focused submenus:
        1) Weapons
        2) Armor & Shields
        3) Accessories & Trinkets (rings + trinkets)
        4) Potions

    Returns the category key the player picked, or 'sell'/'leave'.
    """
    print("=" * 52)
    print(f"  🛒 Arena Merchant   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()
    print(_wrap("  'Greetings, fighter. What are you after today?'"))
    print()

    # Count available items per category for quick visibility
    weapon_avail = sum(
        1 for grp in stock["weapon_groups"]
        for v in grp["variants"] if not v["sold"]
    )
    armor_shield_avail = (
        sum(1 for a in stock["armors"]    if not a["sold"]) +
        sum(1 for s in stock.get("shields", []) if not s["sold"])
    )
    acc_avail = (
        sum(1 for r in stock["rings"]    if not r["sold"]) +
        sum(1 for t in stock["trinkets"] if not t["sold"])
    )
    potion_avail = sum(
        1 for data in stock["potions"].values() if data["stock"] > 0
    )

    print(f"  1) ⚔️  Weapons              ({weapon_avail} available)")
    print(f"  2) 🛡️  Armor & Shields      ({armor_shield_avail} available)")
    print(f"  3) 💍 Accessories & Trinkets ({acc_avail} available)")
    print(f"  4) 🧪 Potions               ({potion_avail} available)")
    print()
    print(f"  S) Sell items from your bag")
    print(f"  0) Leave the merchant")
    print()


def _show_weapons_menu(stock, warrior):
    """Category 1 — weapons only. Returns action dict for the buy dispatcher."""
    print("=" * 52)
    print(f"  ⚔️  Weapons   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1
    for grp_idx, group in enumerate(stock["weapon_groups"]):
        variants = group["variants"]
        all_sold = all(v["sold"] for v in variants)

        if len(variants) == 1:
            v = variants[0]
            label = _label_for_catalog(v["item"])
            if v["sold"]:
                print(f"  {idx:>2}) {label:<46}  ── SOLD ──")
            elif warrior.gold >= v["price"]:
                print(f"  {idx:>2}) {label:<46}  {v['price']}g")
            else:
                short = v["price"] - warrior.gold
                print(f"  {idx:>2}) {label:<46}  {v['price']}g  (need {short} more)")
            actions[str(idx)] = ("buy_weapon_variant", (grp_idx, 0))
        else:
            indicator = "[-]" if group["expanded"] else "[+]"
            avail_count = sum(1 for v in variants if not v["sold"])
            sold_marker = "  ── ALL SOLD ──" if all_sold else f"  ({avail_count} of {len(variants)} variants)"
            print(f"  {idx:>2}) {group['type_name']:<40}  {indicator}{sold_marker}")
            actions[str(idx)] = ("toggle_weapon", grp_idx)

            if group["expanded"]:
                for var_idx, v in enumerate(variants):
                    code = f"{idx}{chr(ord('a') + var_idx)}"
                    label = _label_for_catalog(v["item"])
                    if v["sold"]:
                        print(f"      {code}) {label:<42}  ── SOLD ──")
                    elif warrior.gold >= v["price"]:
                        print(f"      {code}) {label:<42}  {v['price']}g")
                    else:
                        short = v["price"] - warrior.gold
                        print(f"      {code}) {label:<42}  {v['price']}g  (need {short} more)")
                    actions[code] = ("buy_weapon_variant", (grp_idx, var_idx))
        idx += 1

    print()
    print(f"  0) Back to merchant menu")
    return actions


def _show_armor_shields_menu(stock, warrior):
    """Category 2 — armor and shields together."""
    print("=" * 52)
    print(f"  🛡️  Armor & Shields   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1

    print("  ── ARMORS ──")
    for armor_idx, a in enumerate(stock["armors"]):
        label = _label_for_catalog(a["item"])
        if a["sold"]:
            print(f"  {idx:>2}) {label:<46}  ── SOLD ──")
        elif warrior.gold >= a["price"]:
            print(f"  {idx:>2}) {label:<46}  {a['price']}g")
        else:
            short = a["price"] - warrior.gold
            print(f"  {idx:>2}) {label:<46}  {a['price']}g  (need {short} more)")
        actions[str(idx)] = ("buy_armor", armor_idx)
        idx += 1

    print()
    print("  ── SHIELDS ──")
    for shield_idx, s in enumerate(stock.get("shields", [])):
        label = _label_for_catalog(s["item"])
        if s["sold"]:
            print(f"  {idx:>2}) {label:<46}  ── SOLD ──")
        elif warrior.gold >= s["price"]:
            print(f"  {idx:>2}) {label:<46}  {s['price']}g")
        else:
            short = s["price"] - warrior.gold
            print(f"  {idx:>2}) {label:<46}  {s['price']}g  (need {short} more)")
        actions[str(idx)] = ("buy_shield", shield_idx)
        idx += 1

    print()
    print(f"  0) Back to merchant menu")
    return actions


def _show_accessories_menu(stock, warrior):
    """Category 3 — rings and trinkets together. They both share the
    'small jewelry-ish stat boost' identity, so grouping them is cleaner."""
    print("=" * 52)
    print(f"  💍 Accessories & Trinkets   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1

    print("  ── RINGS ──")
    for ring_idx, r in enumerate(stock["rings"]):
        label = _label_for_catalog(r["item"])
        if r["sold"]:
            print(f"  {idx:>2}) {label:<46}  ── SOLD ──")
        elif warrior.gold >= r["price"]:
            print(f"  {idx:>2}) {label:<46}  {r['price']}g")
        else:
            short = r["price"] - warrior.gold
            print(f"  {idx:>2}) {label:<46}  {r['price']}g  (need {short} more)")
        actions[str(idx)] = ("buy_ring", ring_idx)
        idx += 1

    print()
    print("  ── TRINKETS ──")
    for tr_idx, t in enumerate(stock["trinkets"]):
        label = _label_for_catalog(t["item"])
        if t["sold"]:
            print(f"  {idx:>2}) {label:<46}  ── SOLD ──")
        elif warrior.gold >= t["price"]:
            print(f"  {idx:>2}) {label:<46}  {t['price']}g")
        else:
            short = t["price"] - warrior.gold
            print(f"  {idx:>2}) {label:<46}  {t['price']}g  (need {short} more)")
        actions[str(idx)] = ("buy_trinket", tr_idx)
        idx += 1

    print()
    print(f"  0) Back to merchant menu")
    return actions


def _show_potions_menu(stock, warrior):
    """Category 4 — potions."""
    print("=" * 52)
    print(f"  🧪 Potions   |   Your Gold: {warrior.gold}g")
    print("=" * 52)
    print()

    actions = {}
    idx = 1
    for key, data in stock["potions"].items():
        if data["stock"] <= 0:
            continue
        label = _potion_label(key)
        if warrior.gold >= data["price"]:
            print(f"  {idx:>2}) {label:<46}  {data['price']}g  x{data['stock']}")
        else:
            short = data["price"] - warrior.gold
            print(f"  {idx:>2}) {label:<46}  {data['price']}g  x{data['stock']}  (need {short} more)")
        actions[str(idx)] = ("buy_potion", key)
        idx += 1

    print()
    print(f"  0) Back to merchant menu")
    return actions


def _buy_variant(warrior, variant_dict):
    """
    Confirm and execute a purchase from a variant dict (used for weapon
    variants, armors, and trinkets — they all share the same shape:
    {"item": ..., "price": ..., "sold": ...}).
    """
    if variant_dict["sold"]:
        print("\n  (That one's already sold.)")
        input("\n  Press Enter...")
        return

    item  = variant_dict["item"]
    price = variant_dict["price"]

    if warrior.gold < price:
        print(f"\n  Not enough gold. Need {price}g, have {warrior.gold}g.")
        input("\n  Press Enter...")
        return

    _clear_screen()
    print("=" * 52)
    label = _label_for_catalog(item)
    print(f"  Purchase: {label}")
    print("=" * 52)
    if hasattr(item, "full_detail"):
        print(item.full_detail())
    print()
    print(f"  Price: {price}g    Your gold: {warrior.gold}g    After: {warrior.gold - price}g")
    print()
    confirm = input("  Confirm purchase? (y/n): ").strip().lower()
    if confirm != "y":
        return

    # Spend gold (NOT total_gold_earned — gold.py convention).
    warrior.gold -= price
    warrior.inventory.append(item)
    variant_dict["sold"] = True

    print(f"\n  ✅ Purchased. {warrior.gold}g remaining.")

    # Offer to equip immediately — y/n prompt on every gear purchase.
    # Gear items have a `slot` attribute (weapon / armor / trinket / etc.)
    if hasattr(item, "slot") and item.slot:
        equip_choice = input(_wrap(f"  Equip the {getattr(item, 'name', 'item')} now? (y/n): ")).strip().lower()
        if equip_choice == "y":
            main_mod = _find_main_module()
            if main_mod and hasattr(main_mod, "equip_item"):
                main_mod.equip_item(warrior, item)
            else:
                # Fallback: leave it in inventory if we can't find the helper
                print(_wrap("  'Set it aside for now — you can equip it later.'"))
        else:
            print(_wrap("  'Suit yourself. It'll be there when you want it.'"))
    else:
        print(_wrap("  'Tuck it away safely.'"))

    input("\n  Press Enter...")


def _buy_potion(warrior, stock, potion_key):
    """Execute a potion purchase. No confirm screen — they're cheap."""
    data = stock["potions"][potion_key]

    if data["stock"] <= 0:
        print("\n  (Sold out.)")
        input("\n  Press Enter...")
        return

    if warrior.gold < data["price"]:
        print(f"\n  Not enough gold. Need {data['price']}g, have {warrior.gold}g.")
        input("\n  Press Enter...")
        return

    warrior.gold -= data["price"]
    warrior.potions[potion_key] = warrior.potions.get(potion_key, 0) + 1
    data["stock"] -= 1

    print(f"\n  ✅ Bought 1× {_potion_label(potion_key)}. {warrior.gold}g remaining.")
    input("\n  Press Enter...")


# ============================================================
# UI — SELL MENU
# ============================================================

def _sell_back_menu(warrior):
    """
    Show inventory and let the player sell at half price. Now also lists
    EQUIPPED gear — selling an equipped piece unequips it first (with confirm).
    Loops until they exit. Crafting components listed but blocked from sale
    with a "see crafter" message.
    """
    while True:
        _clear_screen()
        print("=" * 52)
        print(f"  💰 Sell Back   |   Your Gold: {warrior.gold}g")
        print("=" * 52)
        print(_wrap(
            "  'Whatever you don't need, I'll take it off your hands. "
            "Half price, mind you — I've got mouths to feed.'"
        ))
        print()

        equipped_items = set(i for i in warrior.equipment.values() if i is not None)
        candidates = []
        for item in warrior.inventory:
            if _is_resale_blocked(item):
                continue
            candidates.append(item)
        # Also include equipped items so they can be sold (after unequip confirm)
        for item in equipped_items:
            if _is_resale_blocked(item):
                continue
            if item not in candidates:
                candidates.append(item)

        if not candidates:
            print("  (Nothing in your bag worth selling.)")
            print()
            input("  Press Enter to go back...")
            return

        listing = []
        for item in candidates:
            if _is_crafting_component(item):
                listing.append((item, False, 0))
            else:
                listing.append((item, True, _sell_price(item)))

        for i, (item, can_sell, price) in enumerate(listing, start=1):
            label = _label_for_catalog(item)
            equipped_tag = " [EQUIPPED]" if item in equipped_items else ""
            if can_sell:
                print(f"  {i:>2}) {label:<40}{equipped_tag:<12}  +{price}g")
            else:
                print(f"  {i:>2}) {label:<40}{equipped_tag:<12}  (crafting — see crafter)")
        print()
        print("  Enter item number to sell, or 0 to go back.")

        choice = input("  > ").strip()
        if choice == "0" or choice == "":
            return
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(listing):
            continue

        item, can_sell, price = listing[idx]
        if not can_sell:
            print()
            print(_wrap(
                "  The merchant turns the piece over and shakes his head. "
                "'That's a crafter's job, not mine. Take it to the workshop.'"
            ))
            input("\n  Press Enter...")
            continue

        label = _label_for_catalog(item)
        is_equipped = item in equipped_items
        print()
        if is_equipped:
            print(_wrap(
                f"  ⚠️  {label} is currently EQUIPPED. "
                f"Selling it will unequip the piece first — its stat bonuses will be removed."
            ))
            print(f"  Sell {label} for {price}g?")
        else:
            print(f"  Sell {label} for {price}g?")
        confirm = input("  Confirm? (y/n): ").strip().lower()
        if confirm != "y":
            continue

        # Auto-unequip if needed before sale
        # v0.6.19: rewritten to be defensive against duplicate state.
        # The old flow called unequip_item (which appends to inventory)
        # then removed from inventory — fragile if the item already had
        # a duplicate entry in inventory (e.g. from pre-v0.6.19 unequip
        # silent-corruption bug). Now we explicitly clear from equipment
        # AND remove all instances from inventory, in that order.
        if is_equipped:
            # Reverse stats BEFORE clearing the slot — unequip_item normally
            # handles this, but we're bypassing it to avoid the re-append.
            main_mod = _find_main_module()
            if main_mod and hasattr(main_mod, "unequip_item"):
                main_mod.unequip_item(warrior, item)
                # unequip_item appends to inventory; we'll remove all
                # instances (including any pre-existing duplicates) below.
            else:
                # Fallback: clear the slot directly (shouldn't normally hit this)
                for slot, equipped in warrior.equipment.items():
                    if equipped is item:
                        warrior.equipment[slot] = None
                        break

        # v0.6.16: pop socketed components back to inventory before sale
        try:
            from crafter import pop_sockets_to_inventory
            popped = pop_sockets_to_inventory(warrior, item)
            if popped:
                names = ", ".join(p.short_label() for p in popped)
                print(_wrap(f"  Recovered from sockets: {names}"))
        except ImportError:
            pass

        # Add gold (NOT total_gold_earned — sell-back is repurposed wealth).
        warrior.gold += price
        # v0.6.19: remove ALL instances of this item object from inventory,
        # not just the first. Defensive against duplicate state that could
        # leave a phantom copy after sale (the "infinite gold via dupe" risk).
        while item in warrior.inventory:
            warrior.inventory.remove(item)
        print(f"\n  ✅ Sold for {price}g. You have {warrior.gold}g.")
        input("\n  Press Enter...")


# ============================================================
# MAIN SCENE
# ============================================================

def merchant_scene(warrior, stock=None):
    """
    Full merchant UI loop. Runs buy/sell/expand loops until the player exits.

    Args:
        warrior: the hero object
        stock:   optional dict from a prior call. If None, fresh stock is
                 generated (first visit this interlude). If provided, the
                 same stock is reopened — sold items stay sold, potion
                 counts stay decremented. This lets the player leave to
                 check gear and come back without re-rolling the catalog.

    Returns:
        the stock dict, so the caller (arena_quarters_interlude) can hold
        onto it and pass it back if the player chooses option 5 again.

    Menu codes:
        Plain digits (1, 2, ...)  — top-level row (parent weapon group,
                                     armor, trinket, or potion type)
        Digit + letter (1a, 2b)  — variant row (only valid when the parent
                                     weapon group is currently expanded)
        S                         — open sell-back menu
        0                         — leave the merchant
    """
    _clear_screen()

    if stock is None:
        # First visit — fresh stock and the full intro line
        print(_wrap(
            "The merchant unfolds a heavy cloth across his stall. "
            "'I've been holding back the good stock — figured you'd earn it. "
            "Take a look. Coin's coin.'"
        ))
        print()
        stock = generate_merchant_stock()
    else:
        # Returning visitor — shorter line, no re-roll
        print(_wrap(
            "The merchant looks up. 'Back already? Take another look — "
            "stock's the same as you left it.'"
        ))
        print()

    while True:
        _clear_screen()
        _show_category_picker(stock, warrior)
        raw = input("  > ").strip().lower()

        if raw == "0" or raw == "":
            print()
            print(_wrap("  'Pleasure doing business. Win one for the stall.'"))
            print()
            input("  Press Enter...")
            return stock

        if raw == "s":
            _sell_back_menu(warrior)
            continue

        # Dispatch into the chosen category submenu. Each category submenu
        # has its own inner loop until the player picks 0 (back).
        if raw == "1":
            _category_loop(warrior, stock, _show_weapons_menu)
        elif raw == "2":
            _category_loop(warrior, stock, _show_armor_shields_menu)
        elif raw == "3":
            _category_loop(warrior, stock, _show_accessories_menu)
        elif raw == "4":
            _category_loop(warrior, stock, _show_potions_menu)
        # Any other input — just re-show the picker


def _category_loop(warrior, stock, menu_fn):
    """
    v0.6.16: Inner loop for a single merchant category. Stays in that
    category's submenu until the player enters 0 (back to picker) or
    runs out of items to buy. Shared by all 4 category submenus — the
    only thing that varies is which menu function renders the catalog.
    """
    while True:
        _clear_screen()
        actions = menu_fn(stock, warrior)
        print()
        raw = input("  > ").strip()

        if raw == "0" or raw == "":
            return

        parsed = _parse_menu_choice(raw)
        if parsed is None:
            continue

        number, suffix = parsed
        key = f"{number}{suffix}" if suffix else str(number)
        action = actions.get(key)
        if action is None:
            continue

        action_type, action_key = action

        if action_type == "toggle_weapon":
            grp_idx = action_key
            stock["weapon_groups"][grp_idx]["expanded"] = not stock["weapon_groups"][grp_idx]["expanded"]

        elif action_type == "buy_weapon_variant":
            grp_idx, var_idx = action_key
            variant = stock["weapon_groups"][grp_idx]["variants"][var_idx]
            _buy_variant(warrior, variant)

        elif action_type == "buy_armor":
            _buy_variant(warrior, stock["armors"][action_key])

        elif action_type == "buy_shield":
            _buy_variant(warrior, stock["shields"][action_key])

        elif action_type == "buy_ring":
            _buy_variant(warrior, stock["rings"][action_key])

        elif action_type == "buy_trinket":
            _buy_variant(warrior, stock["trinkets"][action_key])

        elif action_type == "buy_potion":
            _buy_potion(warrior, stock, action_key)
