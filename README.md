# Journey To Winter Haven

Journey To Winter Haven is a choice-driven dark fantasy RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.6.21

## Play Now

- **Windows Executable** — [Download on itch.io](https://umbra41.itch.io/journey-to-winter-haven)
- **Browser Version** — [Play on Replit](https://replit.com/@Umbra41/Winter-Haven-Journey)
- **Source Code** — [Latest Release](https://github.com/UmbraShadow39/Journey-To-Winter-Haven/releases/latest)
- **GitHub Repository** — [UmbraShadow39/Journey-To-Winter-Haven](https://github.com/UmbraShadow39/Journey-To-Winter-Haven)

## Features

- Turn-based combat with attack, defence, AP, and special moves
- Full monster roster with unique special attack patterns, charge-based bosses, and tier-5 hidden bosses (Young Chimera, Patronus)
- Level-up system with stat points, skill points, and a full 5-skill tree (Power Strike, Heal, War Cry, Defence Break, Death Defier)
- Title system — equippable titles mid-run (River Warrior, Jack of All Trades, True Jack of All Trades, Death's Apprentice, and more)
- Moral choice system — Guardian and Dark Champion endings with distinct stat identities
- Crafting system — Wolf-Hide and Dire Wolf armor sets, weapon socketing, hand slots, helm and cape slots
- Dual-wield system with visibility helpers
- Equipment and loot system with rarity tiers (poor through mythril)
- Merchant shop with persistent inventory between rounds
- Gold and scoring economy
- Leaderboard system
- Full combat log with pagination
- Rich lore and world building — Chapter 1 of a planned trilogy

## How to Play

### Windows Executable (Recommended)
Download the `.exe` from the [itch.io page](https://umbra41.itch.io/journey-to-winter-haven) — no installation required.

For the best experience with full visuals, use **Windows Terminal** (free on the Microsoft Store).

### Running From Source

Requires **Python 3.11+** and **colorama**. All files must be in the same folder.

```
pip install colorama
python Journey_To_Winter_Haven_v_06_21.py
```

### Required Files

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_06_21.py` | Main game |
| `combat_log.py` | Combat logging module |
| `titles.py` | Title and achievement system |
| `monsters.py` | Monster classes and encounter logic |
| `score.py` | Run scoring system |
| `merchant.py` | Merchant shop system |
| `gold.py` | Currency tracking |
| `shared.py` | Shared utilities and display helpers |
| `crafter.py` | Crafting system |
| `leaderboard.py` | Leaderboard system |
| `movable hero.py` | Hero movement helpers |

## Project Structure

```
Journey To Winter Haven V0.6/
├── Journey_To_Winter_Haven_v_06_21.py   # Main game file (current)
├── combat_log.py
├── titles.py
├── monsters.py
├── score.py
├── merchant.py
├── gold.py
├── shared.py
├── crafter.py
├── leaderboard.py
├── movable hero.py
├── Major_Versions/                       # Archive of major milestones
│   ├── v0.1.2/
│   ├── v0.5.14/
│   ├── v3.18/
│   └── v4.28/
├── CHANGELOG.md
├── DEVLOG.md
├── LORE.md
├── README.md
└── LICENSE
```

## Roadmap

### v0.6.21 — Current (itch.io demo release)
- Modular architecture ✅
- Crafting system with armor sets and socketing ✅
- Dual-wield system ✅
- Merchant reorganization ✅
- Leaderboard system ✅
- Windows executable ✅
- itch.io launch ✅

### v0.7 and Beyond
- Balance pass — boss difficulty and loot drop rate tuning
- Additional skill tiers
- Multiple playable classes (Mage, Thief)
- pygame conversion — targeting December 2026
- Godot 2D / Steam Early Access — targeting 2027
- Prologue arena (playing as Umbra, 20 years prior)
- Game 2 — playing as the son, inheriting parent's legacy
- Save/load functionality
- Roguelike arena mode

## License

All Rights Reserved.
See the LICENSE file for details.
