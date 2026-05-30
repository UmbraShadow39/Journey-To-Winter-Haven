# Journey To Winter Haven

Journey To Winter Haven is a text-based RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.6.21 — Demo

> **Status: Active Demo** — Playable from source. itch.io terminal release coming soon.

## Features

- Turn-based combat with attack, defence, AP, and special moves
- Full monster roster with unique special attack patterns, charge-based bosses, and tier-5 hidden bosses (Young Chimera, Patronus)
- Level-up system with stat points, skill points, and a full 5-skill tree (Power Strike, Heal, War Cry, Defence Break, Death Defier)
- Title system — equippable titles mid-run (River Warrior, Jack of All Trades, True Jack of All Trades, Death's Apprentice, and more)
- Fate titles and achievements tracked separately for end-of-run summaries
- Moral choice system — Guardian and Dark Champion endings with distinct stat identities
- Potions, consumables, and crafting materials
- Crafting system — recipe-based item creation from monster essences and loot
- Merchant shop with persistent inventory between rounds
- Gold and currency system
- Equipment and loot system with rarity tiers (poor through mythril)
- Trinket system — Charged Jagged Rock (offensive psychic pool) and Waterlogged Stone (defensive AP battery)
- Monster essence collection influencing story progression
- Multiple endings based on decisions, performance, and morality
- Story-driven narrative with branching choices and replay value
- Full combat log with pagination
- Leaderboard and scoring system
- Debug menu for testing and development

## How to Play

### Running From Source

Requires **Python 3.11+**. All files must be in the same folder.

```
python Journey_To_Winter_Haven_v_06_21.py
```

### Required Files

All of the following files must be present in the same directory:

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_06_21.py` | Main game |
| `monsters.py` | Monster classes, special moves, encounter logic |
| `merchant.py` | Merchant shop system |
| `crafter.py` | Crafting system |
| `gold.py` | Currency tracking |
| `shared.py` | Shared utilities and display helpers |
| `score.py` | Run scoring system |
| `leaderboard.py` | Leaderboard tracking |
| `combat_log.py` | Combat logging module |
| `titles.py` | Title and achievement system |

## Project Structure

```
Journey-To-Winter-Haven/
├── Journey_To_Winter_Haven_v_06_21.py   # Main game file (current)
├── monsters.py                           # Monster classes and special moves
├── merchant.py                           # Merchant shop
├── crafter.py                            # Crafting system
├── gold.py                               # Currency module
├── shared.py                             # Shared utilities
├── score.py                              # Scoring system
├── leaderboard.py                        # Leaderboard system
├── combat_log.py                         # Combat log module
├── titles.py                             # Title system module
├── Major_Versions/                       # Archive of major milestones
│   ├── v4.28/
│   └── v0.5.14/
├── CHANGELOG.md                          # High-level version history
├── DEVLOG.md                             # Detailed development notes
├── LORE.md                               # World and story bible
├── README.md
└── LICENSE
```

## Roadmap

### Demo — v0.6.21 (May 2026) ✅
- Full monster roster designed and implemented ✅
- Hidden boss fights tied to moral choice system ✅
- Fallen Warrior desperation phase fully tuned ✅
- Title and mastery system for all 5 skills ✅
- Crafting system ✅
- Merchant and gold system ✅
- Leaderboard and scoring system ✅

### v0.7 and Beyond
- itch.io terminal release
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
