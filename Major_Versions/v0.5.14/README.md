# Journey To Winter Haven

Journey To Winter Haven is a text-based RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.5.14

## Features

- Turn-based combat with attack, defence, AP, and special moves
- 14 unique monsters, each with their own special attack patterns
- Level-up system with stat points, skill points, and a full skill tree
- Title system — earn equippable titles mid-run (River Warrior, Jack of All Trades)
- Fate titles and achievements tracked separately for end-of-run summaries
- Potions and consumables to manage survival
- Equipment and loot system with rarity tiers
- Monster essence collection influencing story progression
- Multiple endings based on decisions, performance, and morality
- Story-driven narrative with branching choices and replay value
- Full combat log with pagination
- Debug menu for testing and development

## How to Play

### Running From Source

Requires **Python 3.11+**. All files must be in the same folder.

```
python Journey_To_Winter_Haven_v_05_14.py
```

### Required Files

The following files must be present in the same directory as the main script:

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_05_14.py` | Main game |
| `combat_log.py` | Combat logging module |
| `titles.py` | Title system module |

### Windows Executable

A `.exe` build is available on the Releases page for players who don't have Python installed:
https://github.com/UmbraShadow39/Journey-To-Winter-Haven/releases/latest

## Project Structure

```
Journey To Winter Haven v.05/
├── Journey_To_Winter_Haven_v_05_14.py   # Main game file
├── combat_log.py                         # Combat log module
├── titles.py                             # Title system module
├── Major_Versions/                       # Archive of major milestones
│   ├── v0.1.2/
│   ├── v3.18/
│   └── v4.28/
├── CHANGELOG.md                          # Full version history
├── DEVLOG.md                             # Development notes
├── LORE.md                               # World and story bible
├── README.md
└── LICENSE
```

## Roadmap

### Demo Target — May 2026 (itch.io terminal release)
- Remaining 4 monsters designed and implemented
- Hidden boss fights tied to moral choice system ✅
- Fallen Warrior desperation phase fully tuned ✅
- Jack of All Trades title + skill tree foundation

### v0.6 and Beyond
- pygame conversion — December 2026
- Godot 2D / Steam Early Access — May 2027
- Additional skill tiers (tier 2 and 3 unlocks gated behind Jack of All Trades)
- Multiple playable classes (Mage, Thief)
- Arena tier system with named arenas and tier-specific champion titles
- Prologue arena (30 years prior, playing as Umbra)
- Save/load functionality
- Roguelike arena mode

## License

All Rights Reserved.
See the LICENSE file for details.
