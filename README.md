# Journey To Winter Haven

Journey To Winter Haven is a text-based RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.6.14

## Features

- Turn-based combat with attack, defence, AP, and special moves
- Full monster roster with unique special attack patterns, charge-based bosses, and tier-5 hidden bosses (Young Chimera, Patronus)
- Level-up system with stat points, skill points, and a full 5-skill tree (Power Strike, Heal, War Cry, Defence Break, Death Defier)
- Title system — equippable titles mid-run (River Warrior, Jack of All Trades, True Jack of All Trades, Death's Apprentice, and more)
- Fate titles and achievements tracked separately for end-of-run summaries
- Moral choice system — Guardian and Dark Champion endings with distinct stat identities
- Potions, consumables, and crafting materials (crafting system coming next)
- Equipment and loot system with rarity tiers (poor through mythril)
- Trinket system — Charged Jagged Rock (offensive psychic pool) and Waterlogged Stone (defensive AP battery)
- Monster essence collection influencing story progression
- Merchant shop with persistent inventory between rounds
- Multiple endings based on decisions, performance, and morality
- Story-driven narrative with branching choices and replay value
- Full combat log with pagination
- Debug menu for testing and development

## How to Play

### Running From Source

Requires **Python 3.11+**. All files must be in the same folder.

```
python Journey_To_Winter_Haven_v_06_10.py
```

### Required Files

The following files must be present in the same directory as the main script:

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_06_10.py` | Main game |
| `combat_log.py` | Combat logging module |
| `titles.py` | Title and achievement system |
| `monsters.py` | Monster classes, special moves, encounter logic |
| `score.py` | Run scoring system |
| `merchant.py` | Merchant shop system |
| `gold.py` | Currency tracking |
| `shared.py` | Shared utilities and display helpers |

### Windows Executable

A `.exe` build is available on the Releases page for players who don't have Python installed:
https://github.com/UmbraShadow39/Journey-To-Winter-Haven/releases/latest

## Project Structure

```
Journey To Winter Haven V.06/
├── Journey_To_Winter_Haven_v_06_10.py   # Main game file (current)
├── combat_log.py                         # Combat log module
├── titles.py                             # Title system module
├── monsters.py                           # Monster classes and special moves
├── score.py                              # Scoring system
├── merchant.py                           # Merchant shop
├── gold.py                               # Currency module
├── shared.py                             # Shared utilities
├── Old .6 builds/                        # Patch-level history (v0.6.01 through v0.6.09)
├── Major_Versions/                       # Archive of major milestones
│   ├── v0.1.2/
│   ├── v3.18/
│   ├── v4.28/
│   └── v0.5.14/
├── CHANGELOG.md                          # High-level version history
├── DEVLOG.md                             # Detailed development notes
├── LORE.md                               # World and story bible
├── README.md
└── LICENSE
```

## Roadmap

### Demo Target — May 2026 (itch.io terminal release) — in progress
- Remaining monsters designed and implemented ✅
- Hidden boss fights tied to moral choice system ✅
- Fallen Warrior desperation phase fully tuned ✅
- Title system foundation ✅
- Mastery titles for all 5 skills ✅
- Crafting system (next major feature)

### v0.7 and Beyond
- Crafting system — recipe-based item creation from monster essences and loot
- pygame conversion — December 2026
- Godot 2D / Steam Early Access — May 2027
- Additional skill tiers (tier 2 and 3 unlocks gated behind Jack of All Trades)
- Multiple playable classes (Mage, Thief)
- Arena tier system with named arenas and tier-specific champion titles
- Prologue arena (20 years prior, playing as Umbra)
- Game 2 — playing as the son after the arena, inheriting parent's stat bumps but not active passives
- Save/load functionality
- Roguelike arena mode

## License

All Rights Reserved.
See the LICENSE file for details.
