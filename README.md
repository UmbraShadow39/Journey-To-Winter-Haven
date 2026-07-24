# Journey to Winter Haven: A New Champion Rises

A choice-driven dark fantasy RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.7.18

## Play Now

- **Windows Executable** — [Download on itch.io](https://umbra41.itch.io/journey-to-winter-haven)
- **Browser Version** — [Play on Replit](https://replit.com/@Umbra41/Winter-Haven-Journey)
- **Source Code** — [Latest Release](https://github.com/UmbraShadow39/Journey-To-Winter-Haven/releases/latest)
- **GitHub Repository** — [UmbraShadow39/Journey-To-Winter-Haven](https://github.com/UmbraShadow39/Journey-To-Winter-Haven)

## Features

- Turn-based combat with attack, defence, AP, and special moves
- Three difficulty modes: Noob, Warrior, Champion — with full stat/score/gold scaling at 1.5x on Champion
- Full monster roster with unique special attack patterns, charge-based bosses, and tier-5 hidden bosses (Young Chimera, Patronus)
- Level-up system with stat points, skill points, and a full 5-skill tree (Power Strike, Heal, War Cry, Defence Break, Death Defier)
- Assassin's Strike hidden capstone (Power Strike R5 + Dual Wielder R5)
- Mastery system — Rank 5 unlocks permanent passive titles (Brawl Master +20% ATK, Combat Medic +10% HP regen, Charismatic Speaker +15% ATK buff, Armor Piercer -1 DEF on hit, Death's Apprentice cheaper Death Defier)
- Title system — equippable titles mid-run (River Warrior, Jack of All Trades, True Jack of All Trades, Death's Apprentice, Big Spender, Penny Pincher, and more)
- Moral choice system — Guardian and Dark Champion endings with distinct stat identities
- Full armor socket system — Cured Pelts (+DEF/HP), Elemental Sacs (resistance), Reinforcement Crystals (stat bonuses), Javelina Tusks (retaliation bleed), Soul Pendants (heal on hit)
- Crafting system — Wolf-Hide and Dire Wolf armor sets, pelt curing, weapon socketing, hand slots, helm and cape slots
- Dual-wield system with visibility helpers and combat detail toggle
- Equipment and loot system with rarity tiers (poor through mythril)
- Merchant shop with persistent inventory between rounds
- Gold and scoring economy with rank ladder (F through SS "God Champion")
- Leaderboard system (Supabase-powered)
- Full combat log with pagination
- Color-coded HP/AP bars (via rich library)
- Python lessons module (unlocks after first victory)
- Rich lore and world building — Chapter 1 of a planned trilogy

## How to Play

### Windows Executable (Recommended)
Download the `.exe` from the [itch.io page](https://umbra41.itch.io/journey-to-winter-haven) — no installation required.

For the best experience with full visuals, use **Windows Terminal** (free on the Microsoft Store).

### Running From Source

Requires **Python 3.11+**. All `.py` files must be in the same folder.

```
pip install -r requirements.txt
python Journey_To_Winter_Haven_v_07_18.py
```

### Required Files

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_07_18.py` | Main game |
| `combat.py` | Combat engine, boss fights, arena loop |
| `combat_log.py` | Combat logging and run stats |
| `crafter.py` | Crafting system, pelt curing, sockets |
| `debug.py` | Debug menu and dev tools |
| `equipment.py` | Equipment, loot, inventory, socketing |
| `gold.py` | Currency tracking |
| `hero.py` | Hero class and stat management |
| `leaderboard.py` | Leaderboard system |
| `merchant.py` | Merchant shop system |
| `monsters.py` | Monster classes and encounter logic |
| `movable hero.py` | Hero movement helpers |
| `python_lessons.py` | Python lessons module (unlocks on first win) |
| `score.py` | Run scoring system |
| `shared.py` | Shared utilities and display helpers |
| `story.py` | Story sequences and narrative |
| `titles.py` | Title and achievement system |
| `ui.py` | UI utilities |
| `ui_bars.py` | Rich HP/AP/SP bar rendering |

### Dependencies

```
colorama          # Terminal colors
rich              # HP/AP bar rendering (optional — falls back to plain text)
better-profanity  # Chat filter for leaderboard names
supabase          # Global leaderboard
python-dotenv     # Environment variable management
```

Dev tools (not required to play):
```
ruff              # Python linter
```

## Project Structure

```
Journey to Winter Haven v0.7/
├── Journey_To_Winter_Haven_v_07_18.py   # Main game file
├── combat.py                             # Combat engine
├── combat_log.py                         # Combat logging
├── crafter.py                            # Crafting system
├── debug.py                              # Debug tools
├── equipment.py                          # Equipment & loot
├── gold.py                               # Currency
├── hero.py                               # Hero class
├── leaderboard.py                        # Leaderboard
├── merchant.py                           # Merchant shop
├── monsters.py                           # Monster roster
├── movable hero.py                       # Movement helpers
├── python_lessons.py                     # Python lessons
├── score.py                              # Scoring system
├── shared.py                             # Shared utilities
├── story.py                              # Story & narrative
├── titles.py                             # Title system
├── ui.py                                 # UI utilities
├── ui_bars.py                            # Rich bar rendering
├── requirements.txt
├── custom_badwords.txt
├── Major_Versions/                       # Archive of major milestones
│   ├── v0.1.2/
│   ├── v0.5.14/
│   ├── v0.6.21/
│   ├── v3.18/
│   └── v4.28/
├── Code changes/                         # Historical code change docs
├── CHANGELOG.md
├── DEVLOG.md
├── LORE.md
├── QUEST_DESIGN.md
├── TECHNICAL_DOC.md
├── TODO.md
├── README.md
└── LICENSE
```

## Roadmap

### v0.7.18 — Current
- Full modular architecture (20 modules) ✅
- Crafting system with pelt curing, armor sockets, Reinforcement Crystals ✅
- Full armor socket system — pelts, sacs, crystals, tusks, soul pendants ✅
- Dual-wield system with Assassin's Strike capstone ✅
- Brawl Master mastery reworked to 20% ATK multiplier ✅
- Three difficulty modes with full scaling ✅
- Champion difficulty tuning — boss/score/gold multipliers fixed to intended 1.50x ✅
- Boss fight intervention keyed to rounds survived ✅
- Big Spender title latch (survives Patronus path gold) ✅
- Weapon-weakening foreshadowing on both victory endings ✅
- SS rank rebalanced to 9,500 ✅
- Color-coded HP/AP bars (rich library) ✅
- Python lessons module ✅
- Leaderboard system ✅
- Windows executable ✅
- itch.io launch ✅

### Beyond v0.7
- Weapon points system (post-arena leveling track)
- Multiple playable classes (Mage, Thief)
- pygame conversion — targeting December 2026
- Godot 2D / Steam Early Access — targeting 2027
- Prologue arena (playing as Umbra, 20 years prior)
- Game 2 — playing as the son, inheriting parent's legacy via genetic signature
- Save/load functionality
- Roguelike arena mode

## License

All Rights Reserved.
See the LICENSE file for details.
