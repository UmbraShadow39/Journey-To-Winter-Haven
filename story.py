# story.py
# Story scenes, interludes, prologue, and narrative flow
# Extracted from main during v0.7 modular refactor (prep for pygame port)

import random
import math
import time
import sys

from shared import (
    wrap, space, clear_screen, continue_text,
    WHITE, RED, GREEN, YELLOW, RESET, WIDTH,
    RestartException, QuickCombatException, Equipment,
)
from titles import (
    award_title,
    check_skill_mastery, check_true_jack_of_all_trades,
)
from combat_log import COMBAT_LOG, view_combat_log
from leaderboard import display_at_end_of_run
from score import show_run_score
from gold import bookie_encounter
from combat import (
    battle,
    chimera_fight, patronus_fight,
    fallen_warrior_moral_choice,
    _ensure_level_5_for_final_boss,
    clear_rot, reset_between_rounds,
    has_unspent_points, _stone_usable,
    confirm_continue_if_points_left,
    use_waterlogged_stone, use_potion_menu,
)
from hero import Warrior, SKILL_DEFS

# --- Runtime callbacks injected by main (avoids circular imports) ---
spend_points_menu  = None
show_end_summary   = None
debug_menu         = None
check              = None
# Mutable ref so main can update GAME_WARRIOR at runtime
_gw_ref = [None]

def _get_gw():
    return _gw_ref[0]

def _set_gw(warrior):
    _gw_ref[0] = warrior
_real_input        = input
_try_dev_shortcut  = None
arena_battle       = None
prompt_play_again  = None

def get_name_input(prompt="\nWhat is your name, adventurer?\n> ", default="Umbra"):
    """
    Safe name prompt:
    - Bypasses the overridden input() so 'm' / 'monster' debug inputs are ignored.
    - Returns the entered name, or `default` if the player hits ENTER on an empty prompt.
    - Blocks profanity and non-alphanumeric characters.
    """
    try:
        from better_profanity import profanity as _profanity
        _profanity_available = True
    except (ImportError, Exception):
        _profanity_available = False

    while True:
        raw = _real_input(prompt)
        if not isinstance(raw, str) or raw.strip() == "":
            return default
        cleaned = raw.strip()
        if not all(c.isalnum() or c.isspace() for c in cleaned):
            print("  Name must contain letters, numbers, and spaces only. Try again.")
            continue
        if _profanity_available and _profanity.contains_profanity(cleaned):
            print("  That name isn't permitted, adventurer. Choose another.")
            continue
        return cleaned

        


def intro_story(warrior):
    """
    Wrapper for the intro story.
    This catches developer shortcut exceptions and cleanly restarts or
    jumps into combat.

    On RestartException ('q' shortcut), we replace _get_gw() with a
    completely fresh Warrior() — same as the entry path in __main__.
    Without this reset, leftover state from the previous run (the
    player's chosen name, potions, story flags, HP/level, etc.) would
    leak into the "restarted" intro: the framing scene's name gate
    `if _get_gw().name == "warrior"` would fail, the prologue would
    skip the name prompt entirely, and the player would land mid-story
    with stale inventory. Fresh warrior == fresh start.
    """
    try:
        return intro_story_inner(warrior)
    except RestartException:
        clear_screen()
        print(wrap("🔄 Restarting game..."))
        # Full reset — wipe the warrior so the framing/name prompt fires again
        _set_gw(Warrior())
        COMBAT_LOG.clear()
        return intro_story(_get_gw())
    except QuickCombatException:
        clear_screen()
        print(wrap("⚔️ Quick Combat Mode Activated!"))
        return arena_battle(_get_gw())
    

# ===============================
# UI display utilities — see ui.py
# ===============================
from ui import (
    berserk_meter,
    xp_bar,
    cjr_bar,
    animate_xp_results,
    refresh_special_state,
    _cjr_rock,
    _cjr_absorb,
    _flayed_charge_tick,
)


# ===============================
# Equipment system — see equipment.py
# ===============================
from equipment import (
    apply_dual_wield_modifier,
    equip_item,
    unequip_item,
    inventory_menu,
    RARITY_ORDER,
    roll_rarity,
    _make_weapon_core,
    make_loot,
)

# [Moved to combat.py] REST_EVENTS, heal_percent, ap_percent, mana_percent, use_potion_menu



def goblin_bookie_payout(warrior, base_gold):
    """
    Goblin bookie payout mini-game (WIP).
    base_gold will come from arena payout later.
    """
    print(wrap(f"The goblin bookie counts out your winnings: {base_gold} gold."))
    space()

    roll1 = random.randint(1, 5)

    if roll1 <= 2:
        print(wrap("He flashes a sharp grin. 'Pleasure doin’ business.'"))
        return base_gold

    print(wrap("Something feels… off. The goblin’s fingers move a little too fast."))
    space()

    roll2 = random.randint(1, 5)
    bonus = 0

    if roll2 == 4:
        bonus = math.floor(base_gold * 0.10)
        print(wrap("You catch him shaving coins off the stack. He sighs and adds a little more."))
    elif roll2 == 5:
        bonus = math.ceil(base_gold * 0.20)
        print(wrap("You slap his wrist mid-skim. He panics and coughs up extra gold."))
    else:
        print(wrap("He laughs it off. 'You accusing me? I’m hurt.'"))

    paid = base_gold + bonus
    print(wrap(f"You would receive {paid} gold."))

    return paid

def nob_interlude_scene(warrior):
    """
    One-time scene in the arena quarters where Nob offers to boost one skill rank.
    - Unique opening line based on story flags.
    - Player chooses any skill they have learned (rank > 0), capped at rank 5.
    - Tracked via trainer_seen so it only fires once.
    """

    # Repeat visit — scene already happened
    if "nob_interlude" in warrior.trainer_seen:
        print(wrap("Nob grins. 'To think you ran from Bo...' he chuckles. 'Now go out there and make me some gold.'"))
        return

    # --- Path-based opening dialogue ---
    if "warrior_arena_escape" in warrior.story_flags:
        print(wrap(
            "Nob crosses his arms and looks you up and down. "
            "'I don't see why you ran from Bo — you've been dominating out there.' "
            "He lets out a short laugh. 'Maybe you're smarter than you look. Or just lucky.'"
        ))
    elif "nob_submit_hit" in warrior.story_flags:
        print(wrap(
            "Nob looks at you with something that might be respect. "
            "'You hit me when I told you to. And you've been hitting everything else since. "
            "Use my training out there — don't waste what I gave you.'"
        ))
    elif "nob_submit_refrain" in warrior.story_flags:
        print(wrap(
            "Nob grunts. "
            "'You wouldn't hit me when you had the chance. I placed a bet against you "
            "after that.' He pauses. 'You've been fighting well enough in the arena "
            "to make me nervous about my gold. Maybe you just needed something uglier "
            "than me to swing at.'"
        ))
    elif "nob_submit_cower" in warrior.story_flags:
        print(wrap(
            "Nob grunts. "
            "'You cowered like a pup when I roared at you. I placed a bet against you "
            "right after that.' He shakes his head. 'But here you are, still breathing. "
            "Don't make me lose my gold out there.'"
        ))
    elif "nob_outran_trainer" in warrior.story_flags:
        print(wrap(
            "Nob crosses his arms and almost smiles. "
            "'You outran me. I don't forget that easily. "
            "Bo wasn't exaggerating — you've got real speed. "
            "Now let's see if you can fight as fast as you run.'"
        ))
    elif "nob_forest_runner" in warrior.story_flags:
        print(wrap(
            "Nob looks you over, almost impressed. "
            "'Bo tells me you nearly outran him in the dark. "
            "That kind of adrenaline can't be taught. "
            "Speed like that will definitely help you in the arena — "
            "if you can learn when to stop running and start fighting.'"
        ))
    elif "nob_forest_brave" in warrior.story_flags:
        print(wrap(
            "Nob looks you over with a hint of respect. "
            "'Bo tells me you broke his hold. Not many can do that. "
            "Most creatures freeze up and never move again.' "
            "He cracks his knuckles. 'Let's see if that willpower "
            "carries over to the arena.'"
        ))
    elif "nob_forest_captured" in warrior.story_flags:
        print(wrap(
            "Nob shrugs. "
            "'Bo says you tried to break his hold and failed. "
            "Can't fault you for trying, I suppose. "
            "But trying isn't enough in the arena — you either "
            "break through or you break.'"
        ))
    elif "nob_forest_caught" in warrior.story_flags:
        print(wrap(
            "Nob grunts. "
            "'You ran when I told you to. That's something. "
            "But I caught you without breaking a sweat. "
            "You'll need more than speed to survive out there.'"
        ))
    elif "nob_forest_defiant" in warrior.story_flags:
        print(wrap(
            "Nob stares at you. "
            "'You refused to run when I told you to. Stubborn. "
            "Stubborn gets you killed in the arena — or it keeps you alive. "
            "I haven't decided which one you are yet.'"
        ))
    elif "bo_stayed_fought_nob" in warrior.story_flags:
        print(wrap(
            "Nob steps over to you, arms crossed. "
            "'You didn't want any part of this. But when I put you "
            "on the spot, you threw a punch.' He almost grins. "
            "'That tells me more than you think.'"
        ))
    elif "bo_stayed_refused_nob" in warrior.story_flags:
        print(wrap(
            "Nob doesn't even look at you."
        ))
    elif "nob_submit_cower" in warrior.story_flags:
        print(wrap(
            "Nob steps over to you, arms crossed. "
            "'You didn't try when Bo found you. You didn't try when I "
            "gave you a second chance.' He pauses. 'The arena doesn't "
            "care about second chances. Whatever you've got left — use it.'"
        ))
    elif "warrior_arena_submit" in warrior.story_flags:
        print(wrap(
            "Nob steps over to you, arms crossed. "
            "'You submitted without a fight. I remember that. "
            "But the arena has a way of finding what's inside you. Let's see what's left.'"
        ))
    else:
        print(wrap(
            "Nob steps over to you, arms crossed. "
            "'You made it this far. Not many do. "
            "I'm going to sharpen one thing before you go back out there.'"
        ))

    space()
    continue_text()
    clear_screen()
    print(wrap(
        "'Pick a skill. I'll push your rank up one notch. "
        "Don't expect miracles — rank 5 is the ceiling and that's where it stays.'"
    ))
    space()
    continue_text()

    # --- Build list of eligible skills ---
    eligible = []
    for key, data in SKILL_DEFS.items():
        rank = warrior.skill_ranks.get(key, 0)
        if rank > 0 and rank < 5:
            eligible.append((key, data["name"], rank))

    if not eligible:
        print(wrap(
            "Nob looks you over and grunts. "
            "'Every skill you know is already maxed. Nothing left for me to teach you.'"
        ))
        warrior.trainer_seen.add("nob_interlude")
        space()
        continue_text()
        return

    # --- Skill choice menu ---
    while True:
        clear_screen()
        print("🏋️ Nob's Offer — Choose a skill to rank up:\n")
        for i, (key, name, rank) in enumerate(eligible, start=1):
            print(f"  {i}) {name:<16} Rank {rank} → {rank + 1}")
        print()

        choice = _real_input("> ").strip()
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(eligible):
            continue

        key, name, rank = eligible[idx]
        warrior.skill_ranks[key] = rank + 1
        warrior.trainer_seen.add("nob_interlude")
        # Death Defier: set passive flag on first rank
        if key == "death_defier" and warrior.skill_ranks[key] == 1:
            warrior.death_defier       = True
            warrior.death_defier_river = False
            warrior.death_defier_active = False
            warrior.death_defier_used   = False

        clear_screen()
        print(wrap(
            f"Nob puts you through a focused drill. "
            f"By the end of it your {name} has sharpened noticeably."
        ))
        print(f"\n✨ {name} is now Rank {rank + 1}.")

        # Fire mastery-title check — rank 5 awards Brawl Master / Combat Medic / etc.
        # Without this, hitting rank 5 via Nob silently skipped the title award.
        check_skill_mastery(warrior, key)
        # Also check the breadth capstone — Nob's free rank-up can be the
        # tipping point that gets the player to rank 2 in all five skills.
        check_true_jack_of_all_trades(warrior)

        # v0.7.14: Noob-difficulty tutorial note. Players were investing skill
        # points during spend_points_menu without realizing learned skills
        # don't fire automatically in combat — they have to be selected from
        # the "Special" option on the battle move menu each turn. Nob's the
        # natural place to spell that out once, right after a player has just
        # ranked something up. Gated to Noob so returning/experienced players
        # on Warrior or Champion don't get told something they already know.
        if getattr(warrior, "difficulty", "warrior") == "noob":
            space()
            print(wrap(
                "Nob adds one more thing before sending you off: "
                "'That skill won't do a thing for you sitting in your head. "
                "In a fight, pick \"Special\" off your move list and choose it there "
                "— same as picking Attack, it just costs AP instead. "
                "It doesn't happen on its own.'"
            ))

        space()
        continue_text()
        return

def arena_quarters_interlude(warrior):
    """
    Called after the initial arena rounds are won.
    - Full heal + AP restore
    - Clears nasty status effects
    - Short hub where you can add custom dialogue later
    """
    clear_screen()

    # --- Basic placeholder intro text (you can rewrite this later) ---
    print(wrap(
        "You are escorted to a quieter room to rest between arena rounds."
    ))
    space()

    # -------- FULL HEAL & AP RESET --------
    # Clear rot with full restore before the heal so max_hp is correct
    clear_rot(warrior, restore_hp=True, source="long_rest")
    warrior.hp = warrior.max_hp
    warrior.max_overheal = int(warrior.max_hp * 1.10)
    warrior.ap = warrior.max_ap

    # Clear combat stats — full_rest=True is THE round 4-5 "day passes" moment.
    # This is the only place berserk fully wipes regardless of remaining charges.
    reset_between_rounds(warrior, full_rest=True)
    # Reset Death Defier for the new stage
   
   
    


    print(f"\n❤️ You are fully healed: {warrior.hp}/{warrior.max_hp} HP")
    print(f"🔵 AP restored: {warrior.ap}/{warrior.max_ap}")
    space(2)

    # -------- SMALL HUB LOOP (all dialogue is placeholder) --------
    talked_goblin = False
    talked_orc = False
    talked_hooded = False
    talked_crafter = False
    merchant_stock = None     # holds the merchant's stock across revisits within this interlude
    crafter_stock = None      # v0.6.16: same pattern for crafter stock
    talked_bo = False
    talked_tom = False

    while True:
        clear_screen()
        print("What would you like to do before the next stage of the tournament?")
        print("1) Talk to the goblin bookie (arena accountant)")
        print("2) Talk to Nob (trainer)")
        print("3) Talk to merchant")
        print("4) Visit the crafter")
        print("5) Inventory & Equipment")
        # v0.6.15: Use a potion option added so players can drink progression
        # potions (skill_point, stat_point, skill_rank_up) during the interlude.
        # Previously the only way to drink potions outside the per-round rest
        # was inventory_menu, and progression potions weren't accessible there.
        print("6) Use a potion")
        print("7) Check your status")
        print("8) View all game stats")
        print("9) Talk to the orc guard (wip)")
        print("10) Talk to the hooded figure (wip)")
        print("11) Talk to Bo (wip)")
        if has_unspent_points(warrior):
            print("12) Spend points (stats & skills)")
        if COMBAT_LOG:
            print("13) Review Combat Log")
        _stone = _stone_usable(warrior)
        if _stone:
            print(f"14) Use Waterlogged Stone ({_stone.stone_charges}/{_stone.stone_max_charges} charges) — restore AP")
        from collectibles import is_october
        if is_october() or getattr(warrior, "halloween_candy", 0) > 0:
            print("H) 🎃 Visit Tom\'s Emporium of Darkness")
        print("15) Rest until you’re called")

        raw = input("\nChoose: ")

        # Allow monster debug here too
        if isinstance(raw, tuple) and raw[0] == "monster_select":
            monster = raw[1]
            if monster:
                battle(warrior, monster)
            clear_screen()
            continue

        # v0.6.19: route 'debug' / 'q' / 'c' through the shared dev-shortcut
        # helper so the interlude has the same shortcuts as story prompts.
        # Without this, typing 'debug' in the interlude was a no-op — only
        # story prompts (continue_text / check) handled it.
        if isinstance(raw, str) and _try_dev_shortcut(raw):
            clear_screen()
            continue

        choice = str(raw).strip()

        if choice == "1":
            clear_screen()
            bookie_encounter(warrior)
            talked_goblin = True
            space(2)

        elif choice == "2":
            clear_screen()
            nob_interlude_scene(warrior)
           
            space(2)

        elif choice == "3":
            clear_screen()
            # Stock persists across visits within this interlude — first
            # visit rolls fresh inventory, subsequent visits reopen the same
            # catalog with sold items still sold and potion counts intact.
            # Prevents re-roll exploits while letting the player leave to
            # check gear and come back.
            from merchant import merchant_scene
            merchant_stock = merchant_scene(warrior, stock=merchant_stock)
            space(2)

        elif choice == "4":
            clear_screen()
            # v0.6.16: replaces WIP placeholder. Stock persists across re-visits.
            from crafter import crafter_scene
            crafter_stock = crafter_scene(warrior, stock=crafter_stock)
            talked_crafter = True
            space(2)

        elif choice == "5":
            clear_screen()
            inventory_menu(warrior)

        # v0.6.15: Use a potion (interlude version). All non-combat potions
        # work here — heal, AP, antidote, cure-all, elixir, frostpine, and
        # the progression potions (skill_point, stat_point, skill_rank_up).
        # Calls use_potion_menu with in_combat=False so progression handlers
        # take their successful out-of-combat path.
        elif choice == "6":
            clear_screen()
            use_potion_menu(warrior, in_combat=False)
            space()

        elif choice == "7":
            clear_screen()
            warrior.show_combat_stats()
            space()
            # v0.6.20: pause so stats don't vanish on loop restart (which calls clear_screen())
            _real_input("Press Enter to return to the menu...")

        elif choice == "8":
            clear_screen()
            warrior.show_all_game_stats()
            space()
            # v0.6.20: pause so stats don't vanish on loop restart (which calls clear_screen())
            _real_input("Press Enter to return to the menu...")

        elif choice == "9":
            clear_screen()
            # TODO: add orc guard dialogue here
            if not talked_orc:
                talked_orc = True
                print(wrap("(The guard makes a low annoyed grunt)"))
            else:
                print(wrap("(The guard glares at you. What!)"))
            space(2)
            continue_text()

        elif choice == "10":
            clear_screen()
            if not talked_hooded:
                talked_hooded = True
                if _get_gw().sex == "male":
                    print(wrap(
                        "The hooded figure studies you intently. "
                        "'I wonder what choice you will make,' the mysterious figure whispers. "
                        "Her angelic voice soothes your body and soul. You wonder who she is."
                    ))
                else:
                    print(wrap(
                        "The hooded figure glances at you. His golden eyes are both powerful and kind. "
                        "You struggle to hold his gaze. His eyes seem to cut through all your barriers. "
                        "He is reading you like an open book. You feel a strange connection to him."
                    ))

            else:
                if _get_gw().sex == "male":
                    print(wrap("The hooded figure remains still, her presence calm and otherworldly."))
                else:
                    print(wrap("The hooded figure remains still, his golden eyes watching from beneath the hood."))
            space(2)
            continue_text()

        elif choice == "11":
            clear_screen()
            if not talked_bo:
                talked_bo = True
                print(wrap("Bo glances at you and says, 'I knew you were a good choice for the tournament.'"))

            else: 
                print(wrap("Bo gives you a slow confident grin. 'Win this thing and I'll give you something special.'"))
            space(2)
            continue_text()

        elif choice == "12":
            if has_unspent_points(warrior):
                spend_points_menu(warrior)
            else:
                print("Invalid choice.\n")

        elif choice == "13":
            if COMBAT_LOG:
                view_combat_log()

        elif choice == "14":
            if _stone_usable(warrior):
                use_waterlogged_stone(warrior)
                input("\nPress Enter...")
            else:
                print("Invalid choice.\n")

        elif choice.lower() == "h":
            from collectibles import is_october, halloween_vendor_scene
            if is_october() or getattr(warrior, "halloween_candy", 0) > 0:
                clear_screen()
                halloween_vendor_scene(warrior, first_visit=not talked_tom)
                talked_tom = True
                space(2)
            else:
                print("Invalid choice.\n")

        elif choice == "15":
            confirm = input(
                "\n⚠️ This rest will send you directly into the championship fight.\n"
                "Are you sure you want to rest now? (y/n): "
            ).strip().lower()

            if confirm != "y":
                clear_screen()
                print(wrap(
                    "You decide to stay awake a little longer."
                ))
                space()
                continue  # back to hub menu
            if not confirm_continue_if_points_left(warrior, "Head into the championship with unused loot or points?"):
                continue


            clear_screen()
            print(wrap(
                "You rest for the day, gathering your strength for the coming championship fight."
            ))
            space()
            print(wrap(
                "Eventually, you are summoned back toward the arena."
            ))
            space()
            return  # back to caller (arena_battle)

        else:
            print("Invalid choice.\n")







def simple_trainer_reaction(warrior):
    """Trainer reaction based on story flags — checks most specific first."""

    if "warrior_arena_escape" in warrior.story_flags:
        print(wrap("I heard you tried to run. Hah."))
        print(wrap("At least you made Bo work for it. Use that fire out there."))
        return

    if "nob_submit_hit" in warrior.story_flags:
        print(wrap("You hit me when I told you to. That took guts."))
        print(wrap("Use my training out there. Make it count."))
        return

    if "nob_submit_refrain" in warrior.story_flags:
        print(wrap("You wouldn't swing when I told you to. I'm placing a bet against you."))
        print(wrap("The arena won't give you that option. Swing first or don't swing at all."))
        return

    if "broke_bo_hold" in warrior.story_flags:
        # Broke Bo's hold — the hardest check
        print(wrap(
            "\"Your mental fortitude is impressive,\" Nob says. "
            "\"Focus on your physical performance out there.\""
        ))
        return

    if "nob_forest_brave" in warrior.story_flags:
        # Failed Bo but broke Nob's weaker hold
        print(wrap(
            "\"You have some room to grow,\" Nob says, "
            "\"but you definitely have some potential.\""
        ))
        return

    if "nob_forest_captured" in warrior.story_flags:
        # Failed both holds but tried
        print(wrap(
            "\"You may be weak,\" Nob says, "
            "\"but at least you don't give up.\""
        ))
        return

    if "bo_stayed_fought_nob" in warrior.story_flags:
        # Stayed with Bo, refused tournament, but fought Nob in training
        print(wrap(
            "\"You didn't want to be here,\" Nob says. "
            "\"But you swung when it mattered. Hold onto that.\""
        ))
        return

    if "bo_stayed_refused_nob" in warrior.story_flags:
        # Stayed with Bo, refused tournament, refused Nob — no acknowledgment
        return

    if "nob_submit_cower" in warrior.story_flags:
        # Refused to even try
        print(wrap("Nob grunts, barely acknowledging your presence."))
        return

    if "warrior_arena_submit" in warrior.story_flags:
        print(wrap("You just walked into the cell, huh?"))
        print(wrap("Being passive won't save you in the arena. Find your spark."))
        return

    # Fallback if no flag matched
    print(wrap("Whatever dragged you here, it won't matter once the gates open."))

def trainer_stat_point_scene(warrior):
    """
    One-time pre-tournament trainer scene.
    - Reacts to how you arrived (story_flags).
    - Grants 1 stat point and 1 skill point UNLESS already trained by Nob.
    - Uses the normal spend_points_menu to spend them.
    """

    # Only run once
    if "warrior_arena_trainer" in warrior.trainer_seen:
        return
    warrior.trainer_seen.add("warrior_arena_trainer")

    clear_screen()
    print(wrap(
        "Just before the first gate opens, a scarred arena trainer steps in front of you."
    ))
    space()

    already_trained = "warrior_trained_by_nob" in warrior.story_flags

    # Path-specific dialogue always fires -- Nob reacts to HOW you arrived
    simple_trainer_reaction(warrior)
    space()
    continue_text()

    space()
    time.sleep(2)

    # If you already did the Nob training scene, don't "double-dip" rewards
    if already_trained:
        # No new points granted here.
        spend_points_menu(warrior)
        space()
        return

    # Escape path — Nob already reacted above, just award points
    if "warrior_arena_escape" in warrior.story_flags:
        warrior.stat_points += 1
        warrior.skill_points += 1
        print(wrap("✨ You gain 1 stat point AND 1 skill point to spend before the tournament begins."))
        space()
        continue_text()
        spend_points_menu(warrior)
        space()
        return

    # Catch-all for paths not yet flagged (Dark Forest, etc.)
    print(wrap(
        "He studies you for a long moment, then grunts. "
        "'Fine. You've earned one last adjustment before you go out there.'"
    ))
    space()
    continue_text()

    warrior.stat_points += 1
    warrior.skill_points += 1
    print(wrap("✨ You gain 1 stat point AND 1 skill point to spend before the tournament begins."))
    space()
    continue_text()

    spend_points_menu(warrior)
    space()





def ashenveil_prologue(warrior):
    """
    New v0.6 prologue — sendoff from Ashenveil before the forest and Bo encounter.
    Called at the start of intro_story_inner before the forest scene.
    Opens with a brief framing scene, then asks for the player's name.
    """
    # --- OPENING FRAMING (only on a fresh run) ---
    # Brief atmospheric setup before the name prompt — gives the player
    # a moment to settle into the world before being asked who they are.
    if _get_gw().name == "warrior":
        clear_screen()
        print(wrap(
            "Cold morning light filters through the eastern gate of Ashenveil. "
            "Ash drifts down from Frostveil Peak in the distance — fine grey flakes "
            "carried on the wind from somewhere high on the mountain that has never "
            "fully gone quiet. It settles on your shoulders, on the cobblestones, "
            "on the worn leather of your traveling pack.",
            WIDTH
        ))
        space()
        continue_text()

        print(wrap(
            "You are nineteen. A greenhorn of the Ashen Vanguard, the city's storied adventurer guild. "
            "Today you leave on your first quest — a scouting run through the Ashen Frost Forest "
            "to a place called Winter Haven.",
            WIDTH
        ))
        space()
        continue_text()

        print(wrap(
            "But before any of that — before the road, before the forest, before what waits at "
            "the foot of Frostback Mountain — there is one question still left to answer.",
            WIDTH
        ))
        space()
        continue_text()

        # --- SEX PROMPT (v0.7.18) ---
        clear_screen()
        sex_choice = check(
            "\nAre you playing as a man or a woman?\n"
            "1) Male\n"
            "2) Female\n"
            "> ",
            ["1", "2"]
        )
        _get_gw().sex = "male" if sex_choice == "1" else "female"

        # v0.8.01: full stat profile by sex.
        #   Male   — 30 HP, ATK 1-6 (swingier), 0 DEF, 3 AP
        #            Raw power with high variance; no innate armour.
        #   Female — 27 HP, ATK 2-4 (steadier), 1 DEF, 4 AP
        #            Tighter damage, innate armour, extra action point.
        # Neither is strictly stronger — Male has +3 HP and bigger spikes,
        # Female has +1 DEF, +1 AP, and a narrower ATK floor.
        w = _get_gw()
        if w.sex == "male":
            w.max_hp  = 30;  w.hp = 30
            w.min_atk = 1;   w.max_atk = 6
            w.defence = 0;   w.base_defence = 0
            w.max_ap  = 3;   w.ap = 3
            stat_note = "30 HP · ATK 1-6 · 0 DEF · 3 AP"
        else:
            w.max_hp  = 27;  w.hp = 27
            w.min_atk = 2;   w.max_atk = 4
            w.defence = 1;   w.base_defence = 1
            w.max_ap  = 4;   w.ap = 4
            stat_note = "27 HP · ATK 2-4 · 1 DEF · 4 AP"
        w.max_overheal = int(w.max_hp * 1.10)

        print(f"\nPlaying as: {w.sex.title()}  ({stat_note})")
        space()
        continue_text()

        # --- NAME PROMPT ---
        # v0.7.18: default name now depends on chosen sex — Umbra (male)
        # or Tarranatrix (female) — since sex is picked first.
        clear_screen()
        name_default = "Tarranatrix" if _get_gw().sex == "female" else "Umbra"
        _get_gw().name = get_name_input(default=name_default)

    clear_screen()
    print(wrap(
        "The Ash Hall of Ashenveil stands at the heart of the city, its stone walls blackened "
        "by decades of torchlight and the slow drift of ash from the forest beyond. "
        "You have spent the last year training inside those walls.",
        WIDTH
    ))
    space()
    child_word = "Daughter" if _get_gw().sex == "female" else "Son"
    print(wrap(
        f"You are {_get_gw().name}. Greenhorn rank, Ashen Vanguard. "
        f"{child_word} of Aldric — A-rank adventurer, senior Vanguard member, and the man "
        "whose name people say when they want to explain what a real warrior looks like.",
        WIDTH
    ))
    space()
    print(wrap(
        "Today is your first quest.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ALDRIC'S SENDOFF ---
    print(wrap(
        "Aldric finds you at the gate, arms crossed, looking you over the way he always does "
        "— checking for the small things. Buckles that catch light. A pack strap that might rattle. "
        "Anything that announces you before you announce yourself.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"Winter Haven.\" He hands you the quest parchment without ceremony. "
        "\"Confirm the dungeon entrance exists. Watch what comes in and out for a day or two. "
        "Take notes. Then get back here.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "He fixes you with a hard look. "
        "Something flickers behind his eyes — there and gone before you can name it. "
        "The road to Winter Haven has been quiet lately. Too quiet, some of the returning "
        "merchants have said. He hasn't mentioned it to you.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"Eyes only. You don't go inside. You don't pick a fight. You don't try to be a hero. "
        "Rumors have been floating around the hall for years — someone needs to actually go look. "
        "Should be simple enough even for a greenhorn.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "He clasps you on the shoulder and holds it a moment longer than necessary.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()
    if _get_gw().sex == "female":
        print(wrap(
            "\"Come back and make your old man proud.\" A rare hint of a smile crosses his face. "
            "\"I know you've been eyeing that young blacksmith down at the forge — or was it "
            "the fruit stand lady's son? Make a little gold on this run and maybe you'll "
            "finally work up the nerve to ask him out on a date.\"",
            WIDTH
        ))
    else:
        print(wrap(
            "\"Come back and make your old man proud.\" A rare hint of a smile crosses his face. "
            "\"I know you've been eyeing that girl in the market district. "
            "Make a little gold on this run and maybe you can finally ask her out on a date.\"",
            WIDTH
        ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Before you can respond he is already walking back toward the Ash Hall.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ELWYN'S SENDOFF ---
    print(wrap(
        "Elwyn is waiting for you just past the gate. She presses a small flask into your hand.",
        WIDTH
    ))
    space()
    print(wrap(
        "\"I made it myself,\" she says quietly. "
        "\"Your father never took one when he left for his first quest. "
        "You're smarter than he was.\"",
        WIDTH
    ))
    space()
    print(wrap(
        "You turn the flask over in your hands. It smells like pine and frost — "
        "like the forest on a cold morning. Like home.",
        WIDTH
    ))
    space()
    print(wrap(
        "She wraps you in a warm hug, kisses you on the cheek, and then says quietly, "
        "\"Stay out of trouble. And don't dawdle.\"",
        WIDTH
    ))
    space()

    # Grant starting consumable — seasonal-aware (v0.8.04).
    # In August: Birthday Cake replaces the Frostpine Tonic.
    # All other months: Frostpine Tonic as normal.
    from collectibles import grant_seasonal_starting_item
    grant_seasonal_starting_item(warrior)

    # Grant Walking Staff — the traveler's weapon carried the whole road.
    # Weaker than any arena drop (no procs, no element) but keeps early fights
    # from being a slog against high-defence enemies before a weapon drops.
    # v0.6.18: marked two-handed — a staff is canonically a two-hander, and
    # without this flag the player could equip a sword + staff for stat
    # stacking (bug surfaced when a tester equipped both).
    walking_staff = Equipment(
        name       = "Walking Staff",
        slot       = "weapon",
        rarity     = "starter",
        atk_min    = 0,
        atk_max    = 1,
        defence    = 1,
        two_handed = True,
    )
    equip_item(warrior, walking_staff)
    print(wrap(
        "\U0001fab5 You've had your walking staff the whole journey. "
        "It's not a weapon — but it'll do until something better turns up.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    # --- ASHEN FROST FOREST ---
    print(wrap(
        "The road out of Ashenveil cuts through the Ashen Frost Forest — "
        "tall ash trees with pale grey bark rising on either side, frost crunching "
        "under your boots even in the early afternoon. The locals call it Ashen Frost "
        "for a reason. It never fully warms up in here.",
        WIDTH
    ))
    space()
    print(wrap(
        "You have traveled this stretch of road before, but never alone. "
        "Never with a guild parchment in your pack.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "The first night you make camp off the road, sheltered behind a fallen ash trunk. "
        "Cold rations — hard bread, dried meat, a strip of cured fruit. You eat without "
        "tasting it. You sleep with one hand on your walking staff and one ear on the wind.",
        WIDTH
    ))
    space()
    print(wrap(
        "The forest is quiet. Not peaceful quiet — something else. "
        "No owl calls. No rustle of small things in the undergrowth. "
        "Just the creak of frost-heavy branches and your own breathing. "
        "You tell yourself it's the cold keeping the animals down. "
        "You almost believe it.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Day two. The forest deepens. The road narrows. "
        "Something moves in the trees to your left. You stop. Silence. "
        "Then nothing — just the wind pulling frost off the branches.",
        WIDTH
    ))
    space()
    print(wrap(
        "You keep walking. The forest has always felt like it was watching. "
        "Today it feels like it is waiting.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "Day three. You haven't seen another traveler since you left Ashenveil. "
        "Not a merchant cart. Not a hunter. Not even a pilgrim taking the long road. "
        "The Ashen Frost is a known route — people use it. "
        "People should be using it.",
        WIDTH
    ))
    space()
    print(wrap(
        "The quiet that felt like nothing on the first night feels like something now. "
        "A slow dread settles into your chest that you can't quite name. "
        "You find yourself glancing back down the road more than you glance forward. "
        "The trees stand perfectly still. The sky is the colour of old ash. "
        "It is too quiet. It has been too quiet since you left.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "By the fourth day the fear has worn down into something worse — loneliness. "
        "A deep, hollow ache you weren't expecting. "
        "You catch yourself wanting to talk to someone. Anyone. "
        "You'd give up your boots for a hot meal and your rations for ten minutes of "
        "conversation with a stranger heading the other way.",
        WIDTH
    ))
    space()
    print(wrap(
        "You think about the market district back in Ashenveil. The noise of it. "
        "The smell of bread and tallow and too many people in one place. "
        "You never thought you'd miss that.",
        WIDTH
    ))
    space()
    print(wrap(
        "Something is wrong with the world. You can't say what. "
        "You don't have the words for it yet. "
        "But the road feels emptier than it should, the forest feels older than it should, "
        "and somewhere deep in your bones there is a pull — like the air itself is "
        "holding its breath before something breaks.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()

    print(wrap(
        "By the time the trees thin the lights of Winter Haven are visible at the base "
        "of Frostback Mountain — still hours away, but there. You stop walking and just "
        "look at them for a moment. Somewhere down there people are talking. Laughing. "
        "Arguing over the price of something. Living their ordinary lives without a second "
        "thought. The thought of it almost makes you want to run.",
        WIDTH
    ))
    space()
    print(wrap(
        "You can hear it faintly on the wind. The distant hum of a city at night — "
        "a cart somewhere, voices carried up the road, the muffled sound of an inn "
        "that hasn't closed yet. You hadn't realised how much you missed the sound "
        "of other people until just now.",
        WIDTH
    ))
    space()
    print(wrap(
        "You make camp a few hours outside the city. Too tired to push through tonight, "
        "too relieved to care. The lights are still there when you close your eyes.",
        WIDTH
    ))
    space()
    print(wrap(
        "They are still there when you open them.",
        WIDTH
    ))
    space()
    print(wrap(
        "You sit up. The fire is cold ash. The sky is wrong — deep amber, the sun "
        "already dragging itself toward the horizon. You slept through the entire day. "
        "Not a few hours. The whole day.",
        WIDTH
    ))
    space()
    print(wrap(
        "For a moment something prickles at the back of your neck. A wrongness you "
        "can't quite name. Then your stomach growls, your legs ache, and your head is "
        "thick with the fog of too-deep sleep. You rub your face and reach for your pack.",
        WIDTH
    ))
    space()
    print(wrap(
        "You must have been more tired than you thought. Four days alone on a silent "
        "road — of course you crashed. That's all it was.",
        WIDTH
    ))
    space()
    print(wrap(
        "You never make it to the dungeon entrance.",
        WIDTH
    ))
    space()
    continue_text()
    clear_screen()


def intro_story_inner(warrior):
    """Long-form intro story leading into the arena_battle(warrior)."""

    # v0.6 — Ashenveil prologue: Aldric & Elwyn sendoff, Frostpine Tonic, forest travel
    ashenveil_prologue(warrior)

    clear_screen()
    print(wrap(
        "You find yourself stumbling through the last stretch of Ashen Frost Forest "
        "as the last light bleeds out of the sky. Winter Haven's lights glow ahead — "
        "the same lights you fell asleep looking at. Your torch flickers against the "
        "dark closing in around you.",
        WIDTH
    ))

    space()
    print(wrap(
        "Almost there. Hungry, stiff, but almost there.",
        WIDTH
    ))
    space()
    winter_heaven_info = check(
        "Would you like more information about Winter Haven? (y/n)\n> ",
        ["y", "n"]
    )

    

    # ============================================================
    # BRANCH: LEARN ABOUT WINTER HAVEN
    # ============================================================
    if winter_heaven_info == "y":
        clear_screen()
        print(wrap(
            "Winter Haven is a small, poor but industrious mountain town located on the edge of the Frostback Mountains. It isn't the most exciting place, "
            "but there is a dungeon nearby.",
            WIDTH
        ))
        print(wrap(
            "It used to be the mining powerhouse of the Kingdom of Arkium, but now most of the ore veins have been exhausted.",
            WIDTH
        ))

        space()
        print(wrap(
            "The dungeon of Winter Haven is special and rumored to be blessed by the gods. Many adventurers travel to Winter Haven " 
            "in search of riches. The dungeon routinely replenishes its treasures. Nothing compares to the big prize though. Every adventurer dreams of clearing a dungeon floor. " 
            "When that happens, exhausted ore veins refill and random pockets of exotic ores also appear.",
            
            WIDTH
        ))

        space()
        print(wrap("The deeper you go the more floors you clear the better the rewards. " 
        "However, no adventurer has cleared past the first floor in over a century. A brave few have explored parts of the second floor, but only a few have returned, and those who do are often silent about their experience." 
        " Despite that Winter Haven has created some of the best black smiths this side of the Frostback Mountains.", WIDTH))
        space()
        continue_text()
        clear_screen()

        print(wrap(
            "You find yourself contemplating what could cause such a miracle.",
            WIDTH
        ))
        print(wrap(
            "Lost in thought, you fail to notice a tree stump in front of you.",
            WIDTH
        ))
        
        
    

        print(wrap(
            "Your foot catches on the stump and you tumble forward. Your torch flies from your "
            "hand and lands in the mouth of a nearby cave.",
            WIDTH
        ))
        print(wrap(
            "A deep, angry voice echoes from within, \"Who goes there?\"",
            WIDTH
        ))
        continue_text()

        #continue_text()
        clear_screen()
        if _get_gw().name == "warrior":
            _get_gw().name = get_name_input()


        print(wrap(
            "A burly beastman steps out of the cave, towering over you. "
            "He snorts and says, \"Looks like we have another volunteer for our monster tournament.\"",
            WIDTH
        ))

        tournament_entrance = check(
            f"\nWhat do you do, {warrior.name}? Do you try to escape, or submit?\n"
            "Type '(1' to try to escape, or '(2' to accept your fate.\n> ",
            ["1", "2"]
        )

        

        # --------------------------------------------
        # TRY TO ESCAPE
        # --------------------------------------------
        if tournament_entrance == "1":
            warrior.arena_origin = "escape_attempt"
            warrior.story_flags.add("warrior_arena_escape")
            clear_screen()
            print(wrap(
                "You turn and sprint into the forest, but the beastman is far too fast. "
                "He charges after you with terrifying speed. "
                "Your mind begins to cloud you as you realize your pursuer now controls your fate.",
                WIDTH
            ))

            space()
            print(wrap(
                "A short chase ensues, but the beastman's agility and animalistic aggression "
                "are overwhelming. He slams into you with a brutal tackle.",
                WIDTH
            ))

            space()
            beast_man_tackle = random.randint(1, 4)
            _get_gw().hp = max(0, _get_gw().hp - beast_man_tackle)
            print(wrap(
                f"Pain sears through your body. You take {beast_man_tackle} damage.",
                WIDTH
            ))
            print(wrap(
                f"You have {_get_gw().hp} HP remaining.",
                WIDTH
            ))

            space()
            
            print(wrap(
                "The beastman roars in triumph and laughs. "
                "\"Nice try,\" he says. \"That's the most fun I've had in a while. "
                "You might actually have a chance in our tournament.\"",
                WIDTH
            ))
            space()
            continue_text()
            clear_screen()

            space()
            print(wrap("'Here is something to help you out.' Bo hands you a healing potion." \
            " Your hands are tied and Bo escorts you to a nearby monster stronghold. " \
            "A grizzled bear folk meets you at the gates. 'This is Nob, our current Arena Trainer. He will be taking care of you.' Bo gestures.", WIDTH))
            _get_gw().potions["heal"] += 1

            tournament_knowledge = check(
                "\nWould you like to learn about the tournament? (y/n)\n> ",
                ["y", "n"]
            )
            clear_screen()

           
                

            # Learn about tournament
            if tournament_knowledge == "y":
                print(wrap(
                    "You ask the beastman about the tournament.",
                    WIDTH
                ))
                print(wrap(
                    "\"Ah, the tournament,\" he rumbles. "
                    "\"As you adventurers train to kill monsters, "
                    "our monsters also train to kill adventurers.\"",
                    WIDTH
                ))

                space()
                print(wrap(
                    "\"We gain new skills, just like you do. The tournament is a test for our young warriors.\"",
                    WIDTH
                ))
                print(wrap(
                    f"\"The tournament pits a random adventurer— you, {warrior.name} — "
                    "against four different monsters of varying strength. "
                    "Defeat all four in single combat, then fight the champion and you win your freedom.\"",
                    WIDTH
                ))

                space()
                print(wrap(
                    "\"Every monster contains an essence. Those essences are the price of your freedom.\"",
                    WIDTH
                ))
                print(wrap(
                    "You feel like the beastman might be willing to share more information "
                    "if you can persuade him.",
                    WIDTH
                ))
                continue_text()
                clear_screen()
               

                tournament_inquiry = check(
                    "\nDo you inquire further? (y/n)\n> ",
                    ["y", "n"]
                )

                
                if tournament_inquiry == "y":
                    
                    persuasion_roll = random.randint(1, 20)
                    

                    if persuasion_roll >= 12:
                        # Successful persuasion
                        extra_info_choice = check(
                            wrap(
                                "What else would you like to know?\n"
                                "Type '(1' for more about monster essences,\n"
                                "or ('2' to ask what happens if you win.\n> ",
                                WIDTH
                            ),
                            ["1", "2"]
                        )

                        if extra_info_choice == "1":
                            clear_screen()
                            print(wrap(
                                "\"You're a curious one,\" the beastman says.\n\n"
                                "\"A monster's essence is like its soul. "
                                "It allows us to revive them. You adventurers kill so many of us "
                                "that we'd go extinct without them.\"",
                                WIDTH
                            ))
                            print(wrap(
                                f"\"The tournament starts tomorrow night. Rest up, {warrior.name}. You'll need it.\"",
                                WIDTH
                            ))
                        elif extra_info_choice == "2":
                            clear_screen()
                            print(wrap(
                                "\"A fair question,\" he nods. "
                                "\"Obviously we can't have you spreading the word "
                                "about our tournaments. Other adventurers would hunt us down.\"",
                                WIDTH
                            ))
                            print(wrap(
                                "\"If you win, your memories of this place will be wiped. "
                                "You'll be left where we found you— "
                                "possibly a little stronger, with some extra gold in your pack.\"",
                                WIDTH
                            ))
                            print(wrap(
                                "\"The tournament starts tomorrow night. Good luck.\"",
                                WIDTH
                            ))
                        
                    else:
                        # Failed persuasion
                        clear_screen()
                        print(wrap(
                            "\"The only extra information I'm going to share,\" he growls, "
                            "\"is that the tournament is tomorrow night. That should be enough for you.\"",
                            WIDTH
                        ))

                # Common wrap-up for this path
                print()
                print(wrap(
                    "You are thrown into a damp cell. After a few hours of rough sleep, "
                    "you are harshly awakened by the arena trainer, Nob. 'Get up,' he says, 'it's time for training. The beast gods want a show and you are going to give it to them.' " \
                    "Nob puts you through an intensive regimen of sprinting. Your legs burn and your breathing becomes heavy.",
                    WIDTH
                ))
                # Story-only training — no menus yet

                warrior.story_flags.add("warrior_trained_by_nob")
                warrior.trainer_seen.add("trainer_intro_arena")

                # Reward for surviving the night
                warrior.stat_points += 1
                warrior.skill_points += 1

                

                space()
                print(wrap(
                    "After a few hours of training you are put back in your cell. Monsters pass your cell." 
                    "You can understand some of the monsters speaking outside. Most of them "
                    "are placing bets on your chances of survival. The odds are overwhelmingly "
                    "stacked against you.",
                    WIDTH
                ))
                continue_text()
                clear_screen()

                space()
                print(wrap(
                    f"You do overhear the beastman who captured you placing a bet in your favor.",
                    WIDTH
                ))
                print(wrap(
                    "Night falls. The cage door creaks open. You are led toward the roaring sound "
                    "of a crowd.",
                    WIDTH
                ))

                
                continue_text()
                clear_screen()
                arena_battle(_get_gw())
                return

            if tournament_knowledge == "n":
                clear_screen()
                print(wrap(
                    "You decide to wing it. Whatever this tournament is, you'll just survive it "
                    "the same way you survive everything else: one fight at a time.",
                    WIDTH
                ))
                space()

                print(wrap(
                    "You are thrown into a small cell. After a few hours of restless sleep you are rudely awakened by the arena trainer, Nob. " 
                    "'Get up,' he says, 'it's time to train.' You spend the next few hours being trained by Nob. After a few hours of intense and abusive training you are led back to your cell." \
                    " 'Sleep,' Nob growls, 'you fight soon.' As the sun sets and the moon rises you are grabbed by some nearby Orc guards and shoved out of your cell and down a stone hallway " 
                    "towards the sound of many voices.",
                    WIDTH
                ))
                space()

                print(wrap(
                    "The crowd roars as you step onto the blood-soaked sand.",
                    WIDTH
                ))
                continue_text()
                clear_screen()
                arena_battle(_get_gw())
                return

        # --------------------------------------------
        # SUBMIT TO THE TOURNAMENT
        # --------------------------------------------
        if tournament_entrance == "2":
            warrior.arena_origin = "submitted"
            warrior.story_flags.add("warrior_arena_submit")
            clear_screen()
            print(wrap(
                "The beastman looks disappointed. \"I always prefer when they run,\" he mutters.",
                WIDTH
            ))
            print(wrap(
                "\"Still,\" he says, eyeing you, \"I don't think you have much of a shot. "
                "Try to at least provide some entertainment.\"",
                WIDTH
            ))

            space()
            print(wrap(
                "The beastman ties your wrists and solemnly leads you toward Winter Haven. "
                "A few miles later he veers off the main road and leads you down a hidden "
                "passage underneath the town.",
                WIDTH
            ))
            space()
            print(wrap(
                "He knocks three times on a heavy iron door. It swings open and a grizzled, "
                "scarred bear folk meets you on the other side.",
                WIDTH
            ))
            space()
            print(wrap(
                "'This is Nob, our current Arena Trainer. Hopefully he can do something "
                "with you.' The beastman shoves you forward and disappears back down the passage.",
                WIDTH
            ))
            space()
            continue_text()
            clear_screen()

            # --- Nob takes over ---
            print(wrap(
                "Nob looks you up and down without a word. He grabs you by the shoulder "
                "and escorts you down a narrow corridor to a damp, rocky hole in the wall "
                "barely large enough to lie down in. He shoves you inside and slams the "
                "iron gate shut.",
                WIDTH
            ))
            space()
            print(wrap(
                "'Sleep,' he grunts. The torch light retreats with his footsteps.",
                WIDTH
            ))
            space()
            continue_text()
            clear_screen()

            # --- Nob wakes you ---
            print(wrap(
                "A few hours later you are jolted awake by the sound of iron scraping "
                "against stone. Nob stands over you, torch in hand.",
                WIDTH
            ))
            space()
            print(wrap(
                "'Get up.' He drags you to your feet and plants himself directly in front "
                "of you, close enough that you can smell the smoke on his fur.",
                WIDTH
            ))
            space()
            print(wrap(
                "'Let's see if you are a coward or just adverse to conflict.'",
                WIDTH
            ))
            space()
            print(wrap(
                "Nob roars directly in your face — a full, deafening, animalistic roar "
                "that echoes off the stone walls.",
                WIDTH
            ))
            space()

            # --- CHOICE 1: Cower or Stand Firm ---
            nob_roar = check(
                "\nWhat do you do?\n"
                "1) Cower\n"
                "2) Stand firm\n> ",
                ["1", "2"]
            )
            clear_screen()

            if nob_roar == "1":
                # --- COWER PATH ---
                warrior.story_flags.add("nob_submit_cower")
                print(wrap(
                    "You flinch and stumble backward, pressing yourself against the cold stone wall. "
                    "Your hands come up instinctively to shield your face.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "Nob stares at you for a long, uncomfortable moment. Then he shakes his head.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "'Hopeless.' He turns and walks back toward the corridor. 'Back to your cell. "
                    "Try not to embarrass yourself too badly out there.'",
                    WIDTH
                ))
                space()
                warrior.xp += 2
                print("📖 +2 XP from Nob's assessment.")
                warrior.story_flags.add("warrior_trained_by_nob")
                warrior.trainer_seen.add("trainer_intro_arena")
                space()
                continue_text()
                clear_screen()

            else:
                # --- STAND FIRM PATH ---
                print(wrap(
                    "You plant your feet and lock eyes with the bear folk. Your heart is "
                    "hammering, but you don't move. You don't blink.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "Nob holds the stare for a long moment. Then the corner of his mouth "
                    "twitches — not quite a smile.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "'Maybe you're not a coward after all.'",
                    WIDTH
                ))
                space()
                print(wrap(
                    "He takes a step back and squares up, arms loose at his sides.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "'Hit me.'",
                    WIDTH
                ))
                space()

                # --- CHOICE 2: Hit Nob or Refrain ---
                nob_hit = check(
                    "\nWhat do you do?\n"
                    "1) Hit Nob\n"
                    "2) Refrain\n> ",
                    ["1", "2"]
                )
                clear_screen()

                if nob_hit == "1":
                    # --- HIT NOB PATH ---
                    warrior.story_flags.add("nob_submit_hit")
                    print(wrap(
                        "You swing at Nob with everything you have. His paw comes up and "
                        "catches your fist like it's nothing — but he felt it. You can tell "
                        "by the way his eyes narrow.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "'OK. Maybe you are worth something.'",
                        WIDTH
                    ))
                    space()
                    warrior.min_atk += 1
                    print("⚔️ Nob's approval: +1 min ATK")
                    space()
                    print(wrap(
                        "Nob spends the next few hours running you through basic combat drills — "
                        "footwork, how to throw your weight behind a punch, where to aim when "
                        "something bigger than you is trying to kill you. He is not gentle, "
                        "but he is thorough.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "'That's enough. Back to your cell.' Nob escorts you back to the damp "
                        "hole and locks the gate. 'Rest. You fight tonight.'",
                        WIDTH
                    ))
                    space()
                    warrior.xp += 2
                    warrior.stat_points += 1
                    warrior.skill_points += 1
                    print("📖 +2 XP from Nob's training.")
                    print("✨ +1 stat point, +1 skill point from Nob's drills.")
                    warrior.story_flags.add("warrior_trained_by_nob")
                    warrior.trainer_seen.add("trainer_intro_arena")
                    space()
                    continue_text()
                    clear_screen()

                else:
                    # --- REFRAIN PATH ---
                    warrior.story_flags.add("nob_submit_refrain")
                    print(wrap(
                        "You hold your ground but keep your hands at your sides. You don't swing.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Nob watches you for a moment, then drops his arms.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "'That's unfortunate. You stood your ground, I'll give you that. "
                        "But if you won't hit when you have the chance, you will probably "
                        "die in that arena.'",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "He walks you back to your cell without another word.",
                        WIDTH
                    ))
                    space()
                    warrior.xp += 2
                    print("📖 +2 XP from Nob's assessment.")
                    warrior.story_flags.add("warrior_trained_by_nob")
                    warrior.trainer_seen.add("trainer_intro_arena")
                    space()
                    continue_text()
                    clear_screen()

            # --- Common submit ending: led to arena ---
            print(wrap(
                "Night falls. The iron gate screeches open. Orc guards haul you out of "
                "your cell and march you down a coarse stone hallway toward the sound "
                "of a roaring crowd.",
                WIDTH
            ))
            space()
            continue_text()
            clear_screen()
            arena_battle(_get_gw())
            return

    # ============================================================
    # BRANCH: NO WINTER HAVEN LORE (DARK FOREST PATH)
    # ============================================================
    if winter_heaven_info == "n":
        warrior.story_flags.add("skipped_winter_haven_lore")
        clear_screen()
        print(wrap(
            "You trip on a cleverly camouflaged rock and your torch flies from your hand, "
            "landing in a nearby mountain river. The splash echoes through the trees.",
            WIDTH
        ))
        print(wrap(
            "For a moment, only the faint gurgle of the river fills the silence. "
            "Then the darkness thickens — not gradually, but all at once, as if "
            "something swallowed the last trace of light. Even the stars above the "
            "canopy vanish. The air grows heavy and still. Something is very wrong.",
            WIDTH
        ))
        continue_text()
        clear_screen()

        space()
        print(wrap(
            "You have no other source of light, and a soaked torch won't light easily.",
            WIDTH
        ))
        print(wrap(
            "Why tonight? You're tired, hungry, and this unnatural darkness makes you feel uneasy. You were looking forward to spending the night in Winter Haven.",
            WIDTH
           ))
        
        space ()
        print(wrap("You have been traveling through the Ashen Frost Forest for the last few days, surviving off traveler's rations, and sleeping on the cold ground", WIDTH))

       
        space()
        print(wrap("The rations are cold and bland, and sleeping on a bedroll is far from comfortable", WIDTH))
        print(wrap("You can't travel without a torch. That sweet bowl of lamb stew, a warm cider, and a soft bed will have to wait until tomorrow. Or will they?", WIDTH))
      
        continue_text()
        clear_screen()

        night_choice = check(
            wrap(
                "\nWhat do you do?\n"
                "Type '1' to rest against the trees until first light,\n"
                "or '2' to feel your way toward where the torch fell.\n> ",
                WIDTH
            ),
            ["1", "2"]
        )

        

        # ------------------------------
        # REST PATH
        # ------------------------------
        if night_choice == "1":
            clear_screen()
            print(wrap(
                "Blundering around in this deep darkness seems like a bad idea. "
                "You decide to try to get a few hours of sleep before first light.",
                WIDTH
            ))

            space()
            print(wrap(
                "As you lie down, you hear distant, heavy footsteps. "
                "Your body reacts before your mind does — muscles tense, breathing shallow, "
                "every instinct screaming at you to move. The footsteps grow closer. "
                "Deliberate. Unhurried. Whatever is out there isn't lost — it knows "
                "exactly where you are.",
                WIDTH
            ))

            footsteps_choice = check(
                wrap(
                    "What do you do?\n"
                    "Type '1' to whisper 'Who is there?',\n"
                    "or '2' to remain silent and motionless.\n> ",
                    WIDTH
                ),
                ["1", "2"]
            )

           

            # CALL OUT
            if footsteps_choice == "1":
                clear_screen()
                print(wrap(
                    "Your voice, a whisper. 'Who... who is there?'",
                    WIDTH
                ))
                continue_text()
               

                print(wrap(
                    "A deep, predatory voice responds, 'Yes, Terran.'",
                    WIDTH
                ))
                if _get_gw().name == "warrior":
                    _get_gw().name = get_name_input()


                print(wrap(
                    "The creature snaps its fingers. The magical darkness begins to lift. "
                    "It's still night, but you can now make out the shape of a towering figure, "
                    "like a bear standing on two legs.",
                    WIDTH
                ))

                fading_darkness = check(
                    wrap(
                        f"What do you do, {warrior.name}? Do you (1) run or (2) stay?\n> ",
                        WIDTH
                    ),
                    ["1", "2"]
                )
                clear_screen()

                

                # RUN FROM BO
                if fading_darkness == "1":
                    clear_screen()
                    print(wrap(
                        "Your adrenaline spikes and you bolt into the trees. "
                        "Behind you, an excited roar shakes the forest.",
                        WIDTH
                    ))
                    print(wrap(
                        "You glance back and see the bear-like creature charging on all fours, "
                        "rapidly closing the distance.",
                        WIDTH
                    ))

                    space()
                    print(wrap(
                        "The adrenaline coursing through your body, fueled by sheer panic, gives you the edge. You're breaking away.",
                        WIDTH
                    ))
                    print(wrap(
                        "Then you hear a frustrated growl, followed by a sharp snap. "
                        "The forest goes dark again.",
                        WIDTH
                    ))

                    space()
                    print(wrap(
                        "With your vision suddenly obscured, you run hard, face-first into a thick tree branch.",
                        WIDTH
                    ))

                    tree_attack = random.randint(2, 5)
                    _get_gw().hp = max(0, _get_gw().hp - tree_attack)
                    print(wrap(
                        f"You take {tree_attack} damage from the impact. Your head throbs and your vision fades.",
                        WIDTH
                    ))
                    print(wrap(
                        f"You have {_get_gw().hp} HP remaining.",
                        WIDTH
                    ))
                    continue_text()
                    space()
                    clear_screen()

                    print(wrap(
                        "When your vision clears, a massive bearman looms over you.",
                        WIDTH
                    ))
                    print(wrap(
                        f"\"Nice try, {warrior.name},\" he rumbles. \"You almost got away. "
                        "I haven't failed a pursuit in a long time. If it weren't for my magic, "
                        "you would have escaped.\"",
                        WIDTH))
                    
                    space()
                    print(wrap("'Here is a little something to help you out.' Bo hands you two potions — one healing potion and one action point potion.",WIDTH))
                    _get_gw().potions["heal"] += 1
                    _get_gw().potions["ap"] += 1
                    
                    print(wrap(
                        "\"I think you'll be a top-tier competitor in our upcoming tournament. "
                        "My name is Boar, but most call me Bo.\"",
                        WIDTH
                    ))
                   

                    tournament_info = check(
                        "\nWould you like to learn more about the tournament? (y/n)\n> ",
                        ["y", "n"]
                    )

                   
                    if tournament_info == "y":
                        clear_screen()
                        print(wrap(
                            "\"Ah yes, the monster tournament,\" Bo says proudly. "
                            "\"It's a training ground for our young who come of age. "
                            "It gives them real combat experience. Since we are constantly "
                            "being hunted by adventurers, we want our young to have the "
                            "best chance of survival.\"",
                            WIDTH
                        ))

                        space()
                        print(wrap(
                            "\"The tournament pits you against four monsters in solo combat. "
                            "If you defeat all four you fight the champion, beat him and you win. Each monster you defeat rewards you "
                            "with a monster essence. Turn in the essences, and you are set free.\"",
                            WIDTH
                        ))

                        bo_questions = check(
                            wrap(
                                "Bo asks if you have any questions.\n"
                                "Type '1' to ask about essences,\n"
                                "'2' to ask what happens if you win,\n"
                                "or '3' to continue on.\n> ",
                                WIDTH
                            ),
                            ["1", "2", "3"]
                        )
                        continue_text()
                        clear_screen()
                        if bo_questions == "1":
                            clear_screen()
                            print(wrap(
                                "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                "\"With them, we can revive fallen monsters. The essences, "
                                "provided by the beast gods provide us with a way to come back, learn hard lessons, and still live to fight another day.\"",
                                WIDTH
                            ))
                        elif bo_questions == "2":
                            clear_screen()
                            print(wrap(
                                "\"If you win,\" Bo says, \"your memories of this place will be wiped, "
                                "and you'll be returned to where we found you. "
                                "You might be stronger, richer... but you won't remember why.\"",
                                WIDTH
                            ))
                        elif bo_questions == "3":
                            print(wrap("Very well, it's just about time for you to meet the Arena Trainer, Nob."))

                    space()
                    print(wrap(
                        "Soon after, you are shackled and escorted to a fortified arena. "
                        "The crowd's distant roar vibrates through the stone beneath your feet.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "You rest for a few hours and are violently woken up by a scarred, "
                        "battle-hardened beast folk named Nob.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "'Get up,' he growls. He drags you out of your cell and into a walled "
                        "training field. The stone walls are too high to climb, the gate behind "
                        "you already shut.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "'I'm told you're fast. Let's see how fast you truly are.' "
                        "Nob squares up, eyes locked on you.",
                        WIDTH
                    ))
                    space()
                    print(wrap("'Run.'", WIDTH))

                    continue_text()
                    clear_screen()

                    nob_run_choice = check(
                        wrap(
                            "\nWhat do you do?\n"
                            "Type '1' to run,\n"
                            "or '2' to stay put.\n> ",
                            WIDTH
                        ),
                        ["1", "2"]
                    )

                    # --- STAY PUT (refuse to run) ---
                    if nob_run_choice == "2":
                        clear_screen()
                        warrior.story_flags.add("nob_forest_defiant")
                        warrior.story_flags.add("warrior_trained_by_nob")
                        warrior.trainer_seen.add("trainer_intro_arena")

                        nob_shove_damage = random.randint(1, 3)
                        _get_gw().hp = max(0, _get_gw().hp - nob_shove_damage)

                        print(wrap(
                            "You stand your ground and stare back at Nob. You're done being "
                            "told what to do.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob's eyes narrow. In one swift motion he shoves you hard to the "
                            "ground. Dust kicks up around you.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            f"You take {nob_shove_damage} damage from the impact.",
                            WIDTH
                        ))
                        print(f"You have {_get_gw().hp} HP remaining.")
                        space()
                        print(wrap(
                            "'Hopeless,' Nob growls. 'You won't survive the tournament.'",
                            WIDTH
                        ))
                        space()
                        warrior.xp += 3
                        print("📖 +3 XP from Nob's assessment.")
                        space()
                        print(wrap(
                            "Nob grabs you by the collar and drags you back to your cell. "
                            "'Rest — you're going to need it,' he mutters.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

                    # --- RUN ---
                    if nob_run_choice == "1":
                        clear_screen()
                        warrior.story_flags.add("warrior_trained_by_nob")
                        warrior.trainer_seen.add("trainer_intro_arena")

                        print(wrap(
                            "You take off. Your legs burn but the adrenaline is already "
                            "familiar — the same fire that carried you through the forest. "
                            "Behind you, Nob gives chase.",
                            WIDTH
                        ))
                        space()

                        # Weighted roll: 1-25 outrun, 26-75 keeps pace, 76-100 overwhelmed
                        nob_speed_roll = random.randint(1, 100)

                        # --- OUTRUN NOB (1-25) ---
                        if nob_speed_roll <= 25:
                            warrior.story_flags.add("nob_outran_trainer")
                            print(wrap(
                                "You push harder. The wall is coming up fast but you cut left, "
                                "then right — Nob's heavy frame can't match your agility. "
                                "You hear his footsteps falling behind. You're pulling away.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob slows to a stop. You circle back, breathing hard. "
                                "He stares at you for a long moment.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Not bad. Not bad at all.' A rare grin crosses his scarred face. "
                                "'You have potential. Bo wasn't exaggerating.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob reaches into a pouch on his belt and pulls out a small, "
                                "dark vial. 'My own recipe. Save it for when it matters.'",
                                WIDTH
                            ))
                            space()
                            _get_gw().potions["nobs_secret_sauce"] = _get_gw().potions.get("nobs_secret_sauce", 0) + 1
                            print("🧪 Received: Nob's Secret Sauce!")
                            print("   (Double attack + 15% ATK, +1 min ATK, +1 DEF, +1 AP for 2 turns)")
                            warrior.xp += 5
                            warrior.stat_points += 1
                            warrior.skill_points += 1
                            print("✨ +1 stat point, +1 skill point from Nob's training.")
                            print("📖 +5 XP from Nob's training.")

                        # --- KEEPS PACE (26-75) ---
                        elif nob_speed_roll <= 75:
                            warrior.story_flags.add("nob_forest_runner")
                            print(wrap(
                                "You push harder, cutting across the field. Nob matches you "
                                "stride for stride — impossibly fast for his size. Neither of "
                                "you pulls ahead.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "After several laps Nob raises a paw and calls it off. "
                                "You both stand there, breathing hard.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'You're quick,' Nob says. 'Quick enough to stay alive, maybe.'",
                                WIDTH
                            ))
                            space()
                            warrior.stat_points += 1
                            warrior.skill_points += 1
                            warrior.xp += 4
                            print("✨ +1 stat point, +1 skill point from Nob's training.")
                            print("📖 +4 XP from Nob's training.")

                        # --- OVERWHELMED (76-100) ---
                        else:
                            warrior.story_flags.add("nob_forest_caught")
                            nob_tackle_damage = random.randint(1, 3)
                            _get_gw().hp = max(0, _get_gw().hp - nob_tackle_damage)
                            print(wrap(
                                "You push as hard as you can, but Nob closes the gap like "
                                "it's nothing. A massive paw slams into your back and you "
                                "hit the dirt hard.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                f"You take {nob_tackle_damage} damage from the tackle.",
                                WIDTH
                            ))
                            print(f"You have {_get_gw().hp} HP remaining.")
                            space()
                            print(wrap(
                                "'Fast for a Terran,' Nob grunts. 'Not fast enough.'",
                                WIDTH
                            ))
                            space()
                            warrior.stat_points += 1
                            warrior.skill_points += 1
                            warrior.xp += 3
                            print("✨ +1 stat point, +1 skill point from Nob's training.")
                            print("📖 +3 XP from Nob's training.")

                        space()
                        print(wrap(
                            "Nob escorts you back to your cell. 'Rest — you're going to "
                            "need it,' he mutters.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

                # STAY WITH BO
                if fading_darkness == "2":
                    clear_screen()
                    print(wrap(
                        "You stay where you are, forcing yourself not to run.",
                        WIDTH
                    ))
                    print(wrap(
                        "The bear-like creature steps into view. \"Brave, or frozen?\" he asks with a chuckle.",
                        WIDTH
                    ))
                    name = _get_gw().name or "Adventurer"
                    print(wrap(
                        f"\"Either way, {warrior.name}, you'll do nicely for our tournament.\"",
                        WIDTH
                    ))
                    print(wrap(
                        "He introduces himself as Bo and explains the basics of the tournament: "
                        "four monsters and one champion, one competitor, and freedom as the prize. "
                        "What do you say? Are you going to be a willing participant?",
                        WIDTH
                    ))
                    space()

                    willing = check(
                        "Type 'y' for yes, or 'n' for no.\n> ",
                        ["y", "n"]
                    )

                    # ── YES — willing participant ──
                    if willing == "y":
                        warrior.story_flags.add("bo_stayed_willing")
                        clear_screen()
                        print(wrap(
                            "Bo nods approvingly. \"All right. It's easier this way — "
                            "for both of us.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "He reaches into a leather pouch and produces a small vial "
                            "of dark amber liquid. \"Drink this. Consider it a reward "
                            "for not making me chase you.\"",
                            WIDTH
                        ))
                        space()
                        _get_gw().current_bonus_damage += 1
                        print("⚔️ Bo hands you a Might Draught.")
                        print(f"   +1 permanent bonus damage (Now {_get_gw().current_bonus_damage}).")
                        space()
                        print(wrap(
                            "Bo binds your hands — loosely, almost as a formality — "
                            "and escorts you through the dark forest toward Under-Haven.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()

                        print(wrap(
                            "At the gates, a scarred beastman named Nob meets you "
                            "with a scowl.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"This one came willingly,\" Bo says.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob raises an eyebrow. \"Willingly? That's a first.\" "
                            "He looks you over. \"We'll see how willing you are "
                            "after the first round.\"",
                            WIDTH
                        ))
                        space()
                        warrior.xp += 3
                        print("📖 +3 XP.")
                        continue_text()
                        clear_screen()

                        print(wrap(
                            "A group of orc guards arrive and escort you down a "
                            "coarse stone hallway toward the sounds of a roaring crowd.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "At the arena entrance, Nob leans against the wall. "
                            "He gives you a short nod.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"You have potential. Try not to die.\"",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

                    # ── NO — unwilling participant ──
                    if willing == "n":
                        warrior.story_flags.add("bo_stayed_unwilling")
                        clear_screen()
                        print(wrap(
                            "Bo sighs. \"Well, that's unfortunate. But it really "
                            "isn't an option.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Before you can react, Bo grabs you by the arm and "
                            "binds your hands with thick rope. He drags you through "
                            "the dark forest without another word.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()

                        print(wrap(
                            "A stone fortress emerges from the trees — Under-Haven. "
                            "A scarred beastman named Nob meets you at the gate.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"This one didn't want to come,\" Bo grunts.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob barely glances at you. \"They never do.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "You are shoved into a holding cell. The stone is cold. "
                            "The crowd's distant roar vibrates through the walls.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()

                        # ── Nob wakes you ──
                        print(wrap(
                            "A few hours later you are jolted awake by a heavy boot "
                            "kicking the bars of your cell. Nob stands in the doorway.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"Get up,\" he growls. \"Bo says you don't want to "
                            "participate. You know that's not an option.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "He drags you out of the cell and escorts you to a "
                            "walled training ground. The dirt is packed hard, "
                            "stained dark in patches.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob squares up and cracks his knuckles. "
                            "\"Show me what you've got.\"",
                            WIDTH
                        ))
                        space()

                        nob_combat = check(
                            "Type 'y' to fight Nob, or 'n' to refuse.\n> ",
                            ["y", "n"]
                        )

                        # ── Player fights Nob ──
                        if nob_combat == "y":
                            warrior.story_flags.add("bo_stayed_fought_nob")
                            clear_screen()
                            print(wrap(
                                "You throw everything you have into a swing. Nob "
                                "catches it with one paw like he's swatting a fly.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"So there is some fire in you,\" Nob says, almost "
                                "smiling. \"Good. Let's see if we can fan it.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob spends the next hour running you through basic "
                                "combat drills — footwork, guard positions, how to "
                                "read an attack before it lands.",
                                WIDTH
                            ))
                            space()
                            _get_gw().max_atk += 1
                            warrior.xp += 4
                            print("⚔️ +1 Max Attack from Nob's training.")
                            print(f"   ATK: {_get_gw().min_atk}-{_get_gw().max_atk}")
                            print("📖 +4 XP.")
                            continue_text()
                            clear_screen()

                            print(wrap(
                                "A group of orc guards arrive and escort you down a "
                                "coarse stone hallway toward the sounds of a "
                                "roaring crowd.",
                                WIDTH
                            ))
                            continue_text()
                            clear_screen()
                            arena_battle(_get_gw())
                            return

                        # ── Player refuses to fight Nob ──
                        if nob_combat == "n":
                            warrior.story_flags.add("bo_stayed_refused_nob")
                            clear_screen()
                            print(wrap(
                                "Nob stares at you for a long moment.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"Suit yourself. You're as good as dead.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He turns and walks away without another word. "
                                "The guards drag you back to your cell.",
                                WIDTH
                            ))
                            space()
                            warrior.xp += 3
                            warrior.score_multiplier_penalty = getattr(
                                warrior, "score_multiplier_penalty", 0.0
                            ) + 0.10
                            print("📖 +3 XP.")
                            print("📉 +0.10 score multiplier (hardship bonus).")
                            continue_text()
                            clear_screen()

                            print(wrap(
                                "A group of orc guards arrive and drag you down a "
                                "coarse stone hallway toward the sounds of a "
                                "roaring crowd.",
                                WIDTH
                            ))
                            continue_text()
                            clear_screen()
                            arena_battle(_get_gw())
                            return

            # STAY SILENT
            if footsteps_choice == "2":
                clear_screen()
                print(wrap(
                    "You hold your breath, praying that whatever is out there "
                    "hasn't sensed you. The silence stretches — then breaks.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "A dark silhouette emerges from the treeline. Massive. "
                    "Moving with a predator's patience. Something primordial "
                    "echoes under its voice when it speaks.",
                    WIDTH
                ))
                space()
                print(wrap(
                    "Your body stiffens. Not from fear — something deeper. "
                    "Your muscles lock. You can't move.",
                    WIDTH
                ))
                continue_text()
                clear_screen()

                print(wrap(
                    "\"Terran,\" the voice rumbles. \"I sensed you long before "
                    "you sensed me.\"",
                    WIDTH
                ))
                space()

                struggle_choice = check(
                    wrap(
                        "Do you try to break free?\n"
                        "Type '1' to fight against the hold,\n"
                        "or '2' to stay still.\n> ",
                        WIDTH
                    ),
                    ["1", "2"]
                )

                # ── TRY TO BREAK FREE ──
                if struggle_choice == "1":
                    clear_screen()
                    print(wrap(
                        "Every fiber in your body screams against the invisible force. "
                        "You grit your teeth and push.",
                        WIDTH
                    ))
                    space()

                    struggle_roll = random.randint(1, 100)

                    # --- SUCCESS (1-33): broke the hold ---
                    if struggle_roll <= 33:
                        warrior.story_flags.add("nob_forest_brave")
                        warrior.story_flags.add("broke_bo_hold")
                        print(wrap(
                            "Something gives. Your arm jerks forward — then your leg. "
                            "The hold shatters like glass and you stumble free, gasping.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "A massive paw reaches out and grabs you by the shoulder "
                            "before you can take a single step.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"Impressive, Terran,\" the creature says, and you hear "
                            "something like genuine surprise in its voice. \"Most creatures "
                            "can't break my hold. Maybe this isn't a waste of my time.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "The creature snaps its fingers. The magical darkness lifts. "
                            "Standing before you is a towering bearman — easily twice your "
                            "height. He reaches into a leather pouch and hands you a small "
                            "vial of glowing red liquid.",
                            WIDTH
                        ))
                        space()
                        _get_gw().max_rage += 1
                        print("🔥 Bo hands you an Adrenaline Draught.")
                        print("   +1 permanent Adrenaline Boost (bonus damage when wounded).")
                        space()

                        print(wrap(
                            "\"My name is Boar. Most call me Bo. There is a local tournament "
                            "and you have just been entered into it.\"",
                            WIDTH
                        ))
                        if _get_gw().name == "warrior":
                            _get_gw().name = get_name_input()
                        continue_text()
                        clear_screen()

                        tournament_info = check(
                            "\nWould you like to learn more about the tournament? (y/n)\n> ",
                            ["y", "n"]
                        )

                        if tournament_info == "y":
                            clear_screen()
                            print(wrap(
                                "\"Ah yes, the monster tournament,\" Bo says proudly. "
                                "\"It's a training ground for our young who come of age. "
                                "It gives them real combat experience. Since we are constantly "
                                "being hunted by adventurers, we want our young to have the "
                                "best chance of survival.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"The tournament pits you against four monsters in solo combat. "
                                "If you defeat all four you fight the champion, beat him and you win. "
                                "Each monster you defeat rewards you with a monster essence. "
                                "Turn in the essences, and you are set free.\"",
                                WIDTH
                            ))
                            space()

                            bo_questions = check(
                                wrap(
                                    "Bo asks if you have any questions.\n"
                                    "Type '1' to ask about essences,\n"
                                    "'2' to ask what happens if you win,\n"
                                    "or '3' to continue on.\n> ",
                                    WIDTH
                                ),
                                ["1", "2", "3"]
                            )
                            continue_text()
                            clear_screen()
                            if bo_questions == "1":
                                clear_screen()
                                print(wrap(
                                    "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                    "\"With them, we can revive fallen monsters. The essences, "
                                    "provided by the beast gods, provide us with a way to come back, "
                                    "learn hard lessons, and still live to fight another day.\"",
                                    WIDTH
                                ))
                            elif bo_questions == "2":
                                clear_screen()
                                print(wrap(
                                    "\"If you win,\" Bo says, \"your memories of this place will be wiped, "
                                    "and you'll be returned to where we found you. "
                                    "You might be stronger, richer... but you won't remember why.\"",
                                    WIDTH
                                ))
                            elif bo_questions == "3":
                                print(wrap(
                                    "Very well, it's just about time for you to meet "
                                    "the Arena Trainer, Nob.",
                                    WIDTH
                                ))

                    # --- FAIL (34-100): couldn't break the hold ---
                    else:
                        warrior.story_flags.add("nob_forest_captured")
                        print(wrap(
                            "You strain with everything you have. Your arms tremble, "
                            "your jaw clenches — but the hold doesn't budge. Not even "
                            "a flicker.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "The creature lets out a low, rumbling chuckle.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"At least you tried. I suppose that counts for something. "
                            "Maybe you have a chance in this tournament.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "The creature snaps its fingers. The magical darkness lifts. "
                            "A towering bearman stands before you, arms folded.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"My name is Boar. Most call me Bo. There is a local tournament "
                            "and you have just been entered into it.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Bo hands you a small potion.",
                            WIDTH
                        ))
                        _get_gw().potions["ap"] += 1
                        print("⚡ Received: Action Point Potion.")
                        space()

                        if _get_gw().name == "warrior":
                            _get_gw().name = get_name_input()
                        continue_text()
                        clear_screen()

                        tournament_info = check(
                            "\nWould you like to learn more about the tournament? (y/n)\n> ",
                            ["y", "n"]
                        )

                        if tournament_info == "y":
                            clear_screen()
                            print(wrap(
                                "\"Ah yes, the monster tournament,\" Bo says proudly. "
                                "\"It's a training ground for our young who come of age. "
                                "It gives them real combat experience. Since we are constantly "
                                "being hunted by adventurers, we want our young to have the "
                                "best chance of survival.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"The tournament pits you against four monsters in solo combat. "
                                "If you defeat all four you fight the champion, beat him and you win. "
                                "Each monster you defeat rewards you with a monster essence. "
                                "Turn in the essences, and you are set free.\"",
                                WIDTH
                            ))
                            space()

                            bo_questions = check(
                                wrap(
                                    "Bo asks if you have any questions.\n"
                                    "Type '1' to ask about essences,\n"
                                    "'2' to ask what happens if you win,\n"
                                    "or '3' to continue on.\n> ",
                                    WIDTH
                                ),
                                ["1", "2", "3"]
                            )
                            continue_text()
                            clear_screen()
                            if bo_questions == "1":
                                clear_screen()
                                print(wrap(
                                    "\"Essences are fragments of a monster's soul,\" Bo explains. "
                                    "\"With them, we can revive fallen monsters. The essences, "
                                    "provided by the beast gods, provide us with a way to come back, "
                                    "learn hard lessons, and still live to fight another day.\"",
                                    WIDTH
                                ))
                            elif bo_questions == "2":
                                clear_screen()
                                print(wrap(
                                    "\"If you win,\" Bo says, \"your memories of this place will be wiped, "
                                    "and you'll be returned to where we found you. "
                                    "You might be stronger, richer... but you won't remember why.\"",
                                    WIDTH
                                ))
                            elif bo_questions == "3":
                                print(wrap(
                                    "Very well, it's just about time for you to meet "
                                    "the Arena Trainer, Nob.",
                                    WIDTH
                                ))

                    # ── Shared escort to arena (both struggle outcomes) ──
                    space()
                    print(wrap(
                        "Bo binds your hands with thick rope and escorts you through "
                        "the dark forest. After what feels like hours, a stone fortress "
                        "emerges from the trees — Under-Haven.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "At the gates, a scarred, battle-hardened beastman named Nob "
                        "meets you with a scowl.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Bo nods to Nob. \"This one held still in the dark. "
                        "Tried to hide from me.\"",
                        WIDTH
                    ))
                    space()

                    if "nob_forest_brave" in warrior.story_flags:
                        print(wrap(
                            "\"But,\" Bo adds, \"it broke free of my hold. "
                            "That doesn't happen often.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob raises an eyebrow. \"Is that so?\" He looks you over "
                            "with something that might be interest. \"Mentally strong, "
                            "then. Let's see if your body can keep up.\"",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()

                        print(wrap(
                            "Nob spends the next hour running you through basic combat "
                            "drills — footwork, guard positions, how to read an attack "
                            "before it lands. He doesn't go easy on you.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"You won't overpower anything in that arena,\" Nob says, "
                            "resetting your stance for the third time. \"But if you can "
                            "read them and react, you might survive long enough to "
                            "figure out how to win.\"",
                            WIDTH
                        ))
                        space()
                        warrior.xp += 5
                        
                        print("📖 +5 XP from Nob's training.")
                        
                    elif "nob_forest_captured" in warrior.story_flags:
                        print(wrap(
                            "Nob grunts. \"Tried to fight the hold and failed?\" "
                            "He looks you over, eyes narrowing. \"Could be weak. "
                            "Could be that Bo's just that strong.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob steps closer. \"Only one way to find out.\"",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "He raises a paw and mutters something under his breath. "
                            "A familiar pressure clamps down — but it's not the same. "
                            "Bo's hold was iron. This one has seams. You can feel "
                            "the edges where it doesn't quite grip.",
                            WIDTH
                        ))
                        space()

                        nob_retest = check(
                            wrap(
                                "Nob watches you. \"Break it.\"\n"
                                "Type '1' to fight the hold,\n"
                                "or '2' to refuse.\n> ",
                                WIDTH
                            ),
                            ["1", "2"]
                        )

                        if nob_retest == "1":
                            clear_screen()
                            print(wrap(
                                "You grit your teeth and push. The hold bends — "
                                "you can feel it giving where Bo's never did.",
                                WIDTH
                            ))
                            space()

                            nob_retest_roll = random.randint(1, 100)

                            if nob_retest_roll <= 75:
                                warrior.story_flags.discard("nob_forest_captured")
                                warrior.story_flags.add("nob_forest_brave")
                                print(wrap(
                                    "The hold snaps. Your arms swing free and you "
                                    "stumble forward, chest heaving.",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "Nob nods slowly. \"So it was Bo, not you. "
                                    "That's something I can work with.\"",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "He reaches into his belt pouch and produces a "
                                    "small vial of shimmering violet liquid. "
                                    "\"Drink this. The arena is full of things that "
                                    "burn, poison, and rot. This'll help.\"",
                                    WIDTH
                                ))
                                space()
                                _get_gw().magic_resistance = getattr(_get_gw(), "magic_resistance", 0) + 1
                                print("🔮 Nob hands you an Arcane Ward.")
                                print(f"   +1 permanent Elemental Resistance (Now {_get_gw().magic_resistance}).")
                                space()
                                warrior.xp += 4
                                print("📖 +4 XP from Nob's training.")

                            else:
                                print(wrap(
                                    "You strain hard. Your arms tremble, your neck "
                                    "burns — but the hold doesn't break. After a long "
                                    "moment, Nob releases it with a wave of his paw.",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "\"Not strong enough yet,\" Nob says. \"But you "
                                    "fought Bo's hold and mine. That's not nothing.\"",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "Nob spends the next hour drilling you through "
                                    "basic combat stances — how to plant your feet, "
                                    "how to guard your center, how to take a hit "
                                    "without folding.",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "When he's done, he tosses you a healing potion. "
                                    "\"You'll need it.\"",
                                    WIDTH
                                ))
                                space()
                                _get_gw().potions["heal"] += 1
                                print("❤️ Received: Healing Potion.")
                                space()
                                warrior.xp += 3
                                print("📖 +3 XP from Nob's training.")

                        elif nob_retest == "2":
                            warrior.story_flags.discard("nob_forest_captured")
                            warrior.story_flags.add("nob_submit_cower")
                            clear_screen()
                            print(wrap(
                                "You don't move. You don't even try.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob stares at you for a long moment. His expression "
                                "shifts from disappointment to something colder.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"You fought Bo's hold but won't fight mine?\" "
                                "He shakes his head. \"Hopeless.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He turns away without another word. The cell door "
                                "slams shut.",
                                WIDTH
                            ))
                            space()
                            warrior.xp += 2
                            print("📖 +2 XP.")

                        continue_text()
                        clear_screen()

                        print(wrap(
                            "A group of orc guards arrive at your cell and drag you "
                            "down the coarse stone hallway toward the sounds of a "
                            "roaring crowd.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

                    continue_text()
                    clear_screen()
                    arena_battle(_get_gw())
                    return

                # ── REFUSE TO MOVE ──
                if struggle_choice == "2":
                    clear_screen()
                    print(wrap(
                        "You stay still. Whether it's the hold or your own fear, "
                        "you don't fight it.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "The creature waits. Seconds stretch into eternity.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "\"Well, that's unfortunate,\" the voice says flatly. "
                        "\"You'll be easy prey in this tournament.\"",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "The creature snaps its fingers. The magical darkness lifts. "
                        "A towering bearman stands before you, arms folded, unimpressed.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Without another word, he binds your hands and drags you "
                        "through the forest. You don't even learn his name.",
                        WIDTH
                    ))

                    if _get_gw().name == "warrior":
                        _get_gw().name = get_name_input()

                    continue_text()
                    clear_screen()

                    # ── Nob's second-chance training ──
                    print(wrap(
                        "You are hauled to a stone fortress called Under-Haven. "
                        "A scarred beastman named Nob meets you at the gate.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "\"This one didn't even try,\" your captor grunts.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Nob barely glances at you. \"Then it'll be a short tournament.\"",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "You are shoved into a holding cell. The stone is cold. "
                        "The crowd's distant roar vibrates through the walls.",
                        WIDTH
                    ))
                    continue_text()
                    clear_screen()

                    print(wrap(
                        "A few hours later, you are jolted awake by a heavy boot "
                        "kicking the bars of your cell. Nob stands in the doorway, "
                        "torch in hand.",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "\"Bo said you didn't even try to resist his hold,\" Nob says, "
                        "stepping inside. \"Are you scared, or just not very mentally strong?\"",
                        WIDTH
                    ))
                    space()
                    print(wrap(
                        "Before you can answer, Nob raises a paw and mutters something "
                        "under his breath. A familiar pressure clamps down on your body — "
                        "your muscles lock, your breath catches. It's the same hold, "
                        "but weaker. You can feel the edges of it, the seams where it "
                        "doesn't quite grip.",
                        WIDTH
                    ))
                    space()

                    nob_hold_choice = check(
                        wrap(
                            "Nob watches you. \"Try to break it.\"\n"
                            "Type '1' to fight the hold,\n"
                            "or '2' to refuse.\n> ",
                            WIDTH
                        ),
                        ["1", "2"]
                    )

                    # ── Player tries to resist Nob's hold ──
                    if nob_hold_choice == "1":
                        clear_screen()
                        print(wrap(
                            "You grit your teeth and push against the invisible force. "
                            "It's weaker than Bo's — you can feel it giving.",
                            WIDTH
                        ))
                        space()

                        nob_hold_roll = random.randint(1, 100)

                        # --- SUCCESS (1-75): broke Nob's hold ---
                        if nob_hold_roll <= 75:
                            warrior.story_flags.add("nob_forest_brave")
                            print(wrap(
                                "The hold snaps. Your arms swing free and you stumble "
                                "forward, chest heaving.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob nods slowly. \"So you're weak, but not defenseless. "
                                "That's something I can work with.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He reaches into his belt pouch and produces a small "
                                "vial of shimmering violet liquid. \"Drink this. The "
                                "arena is full of things that burn, poison, and rot. "
                                "This'll help.\"",
                                WIDTH
                            ))
                            space()
                            _get_gw().magic_resistance = getattr(_get_gw(), "magic_resistance", 0) + 1
                            print("🔮 Nob hands you an Arcane Ward.")
                            print(f"   +1 permanent Elemental Resistance (Now {_get_gw().magic_resistance}).")
                            space()
                            warrior.xp += 4
                            print("📖 +4 XP from Nob's training.")

                        # --- FAIL (76-100): couldn't break it ---
                        else:
                            warrior.story_flags.add("nob_forest_captured")
                            print(wrap(
                                "You strain hard. Your arms tremble, your neck burns — "
                                "but the hold doesn't break. After a long moment, "
                                "Nob releases it with a wave of his paw.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "\"Not strong enough yet,\" Nob says. \"But you tried. "
                                "That matters more than you think.\"",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Nob spends the next hour drilling you through basic combat "
                                "stances — how to plant your feet, how to guard your center, "
                                "how to take a hit without folding.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "When he's done, he tosses you a healing potion. "
                                "\"You'll need it.\"",
                                WIDTH
                            ))
                            space()
                            _get_gw().potions["heal"] += 1
                            print("❤️ Received: Healing Potion.")
                            space()
                            warrior.xp += 3
                            print("📖 +3 XP from Nob's training.")

                        continue_text()
                        clear_screen()

                        print(wrap(
                            "A group of orc guards arrive at your cell and drag you "
                            "down the coarse stone hallway toward the sounds of a "
                            "roaring crowd.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

                    # ── Player refuses to try (again) ──
                    if nob_hold_choice == "2":
                        warrior.story_flags.add("nob_submit_cower")
                        clear_screen()
                        print(wrap(
                            "You don't move. You don't even try.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "Nob stares at you for a long moment. His expression shifts "
                            "from disappointment to something colder.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "\"Hopeless,\" he says quietly. He releases the hold and "
                            "turns away without another word.",
                            WIDTH
                        ))
                        space()
                        print(wrap(
                            "The cell door slams shut. You sit in the dark, alone with "
                            "the distant roar of the crowd and the growing certainty "
                            "that no one is coming to help you.",
                            WIDTH
                        ))
                        space()
                        warrior.xp += 2
                        print("📖 +2 XP.")
                        continue_text()
                        clear_screen()

                        print(wrap(
                            "Hours later, the orc guards drag you from your cell "
                            "and shove you toward the arena. No training. No gifts. "
                            "No advice.",
                            WIDTH
                        ))
                        continue_text()
                        clear_screen()
                        arena_battle(_get_gw())
                        return

        # ------------------------------
        # SEARCH FOR THE TORCH PATH
        # ------------------------------
        if night_choice == "2":
            clear_screen()
            print(wrap(
                "You rise and carefully feel your way toward the sound of the gently flowing river, "
                "hoping to recover your torch.",
                WIDTH
            ))
            river_attack = random.randint(1, 2)
            _get_gw().hp = max(0, _get_gw().hp - river_attack)
            print(wrap(
                "As you step onto the muddy embankment, your foot slips. "
                "You tumble into the ice-cold mountain river.",
                WIDTH
            ))

            space()
            print(wrap(
                f"You take {river_attack} damage from the fall and the frigid water. "
                f"You now have {_get_gw().hp} HP remaining.",
                WIDTH
            ))
            print(wrap(
                "The freezing water shocks your body."
                
            ))
            print(wrap(
                "Soaked, shivering, and still without a torch, you mutter a few choice words "
                "about your luck.",
                WIDTH
            ))

            space()
            print(wrap(
                "Before you can regain your bearings, a beastly voice rings out. 'Do you want some help?' " \
                "A furry paw reaches down toward you",
                WIDTH
            ))
            accept_help = check(
                "\nDo you accept the help? (y/n)\n> ",
                ["y", "n"]
            )
            clear_screen()
            if accept_help == "y":
                print(wrap("You cautiously accept the creature's paw and are lifted out " 
                "of the water.", WIDTH))

                space()
                print(wrap("You should be cautious of who you trust. That river would probably have eventually killed you. "
                "Anyway, perhaps that would have been a better way to go. Regardless, we need more fighters "
                "for our tournament. Congratulations on being selected. Try not to die too fast.", WIDTH))
                space()

                print(wrap("The creature binds your hands and escorts you to a nearby monster stronghold of Under-Haven. On the way to the stronghold the creature introduces himself as Bo. "
                "As the moon is starting to set you reach the stronghold and a cantankerous old beast man named Nob meets you at the gates. "
                " Bo introduces Nob as the arena trainer. Nob looks at you and mumbles 'Is this really the best you could find? Fine.' "
                "You are escorted into a holding cell and allowed to rest. A few hours later Nob shows up in your cell and yells at you to get up and train.", WIDTH))
                space()
                continue_text()
                clear_screen()

                print(wrap("Nob puts you through an intense sequence of upper body exercises and rapid leg workouts. 'Falling in the water and needing help"
                " to get out, disgraceful.' Finally you are allowed to go back to sleep, your clothes damp from the exertion. As the moon rises a group of orc guards come into your cell and drag"
                " you down the coarse stone hallway and towards the sounds of a roaring crowd.", WIDTH))

            if accept_help == "n":
                print(wrap("You decline the help and the creature says 'Very well. The river banks "
                " remain pretty steep for a while, and there are some serious rapids "
                "farther downstream. Good luck finding your way out, it being dark and all'."))

                continue_text()
                clear_screen()
                accept_help_2 = check(
                    "\nDo you reconsider and accept the help? (y/n)\n> ",
                    ["y", "n"]
                )
                if accept_help_2 == "y":
                    print(wrap("You reluctantly accept help. The creature introduces himself as Boar, Bo for short. " 
                    "What is your name?"))
                    if _get_gw().name == "warrior":
                        _get_gw().name = get_name_input()
                    print(wrap("I respect your courage, adventurer, so I am going to give you a little something special. " 
                    "Boar hands you a potion of AP."))
                    _get_gw().potions["ap"] += 1
                    print(wrap("The creature's eyes intensify. 'You're going to need it for the tournament.'"))
                if accept_help_2 == "n":
                    damage = river_attack*2 + 2
                    _get_gw().hp = max(0, _get_gw().hp - damage)
                    print(wrap("Suit yourself. You continue downstream trying to find a place to climb out." \
                    " Your body's core temperature starts to drop. Your limbs begin to go numb." \
                    " If you don't get out of the water soon the elements could kill you."))

                    space()
                    print(wrap(f"You take {damage} damage from nearby floating debris as the river picks" \
                               " up speed. Boar walks alongside you, striking up a conversation. He" \
                               " says his friends call him Bo and he is looking for new competitors in a local" \
                               " tournament."))
                    print(wrap(f"You have {_get_gw().hp} HP remaining."))
                    if _get_gw().hp <= 0:
                        print("You die")
                        exit()
                    accept_help_final = check("I can see you are getting pretty cold. Are you sure you don't want" \
                    " my help? (y/n)\n> ",
                    ["y", "n"]
                    )
                    if accept_help_final == "y":
                        print(wrap("I can see you are very brave. I will rescue you if you agree to fight in my tournament"))
                        accept_tournament = check("Do you accept? (y/n)\n> ",
                        ["y", "n"]
                        )
                        if accept_tournament == "y":
                            print(wrap("Bo reaches down and effortlessly pulls you out of the frigid river. What is your name, adventurer?"))
                            if _get_gw().name == "warrior":
                                _get_gw().name = get_name_input()
                            print(wrap(f"I respect your stubbornness, {_get_gw().name}. Let me give you a fighting chance in our tournament. Bo hands you two potions — one for healing and one for AP."))
                            _get_gw().potions["heal"] += 1
                            _get_gw().potions["ap"] += 1

                            space()
                            continue_text()
                            clear_screen()

                            # --- Bo escorts the stubborn river survivor to Under-Haven ---
                            print(wrap(
                                "Bo walks beside you as you make your way through the forest. "
                                "Soaked, shivering, and barely standing, you stumble along. "
                                "Bo doesn't bind your hands — he's already decided you won't run.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "As the moon begins to set you reach the monster stronghold of Under-Haven. "
                                "A cantankerous old beast man named Nob meets you at the gates. "
                                "Bo introduces Nob as the arena trainer. "
                                "Nob looks you up and down, water still dripping from your clothes. "
                                "'Half-drowned. Wonderful. Fine.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "You are escorted into a holding cell and allowed to rest. "
                                "A few hours later Nob shows up in your cell and yells at you to get up and train.",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Path-specific Nob training: BALANCE (you fell in the river)
                            print(wrap(
                                "Nob marches you out to a stone yard ringed with weathered wooden posts. "
                                "'You fell in a river,' he says flatly. 'That tells me everything I need "
                                "to know about your footing. We're going to fix that, or you're going to "
                                "die in there. Up.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He has you stand on a single foot until your standing leg burns. "
                                "Then the other foot. Then a narrow beam set between two of the posts — "
                                "walk it, turn at the end, walk it back, do not fall. "
                                "You fall. Nob makes you climb back up without a word.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Your centre of gravity is where your enemy puts it,' he barks. "
                                "'Until you take it back.' He shoves you off the beam mid-step to prove it. "
                                "You hit the dirt. You climb back up. You do it again. And again.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "By the time he lets you stop, your legs are shaking and the sky is paling. "
                                "Your clothes are finally dry. 'Better,' Nob grunts. 'Not good. Better. "
                                "Back to your cell. The crowd will be here soon.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Bo returns to escort — personal interest in the stubborn one
                            print(wrap(
                                "You sit on the cot in your cell, legs trembling, listening to the slow "
                                "rise of voices somewhere above. A crowd gathering. The sound of it "
                                "settles into your chest the way cold water did, hours ago.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Footsteps in the corridor. Not orc-guard footsteps — heavier, calmer. "
                                "Bo appears at the bars, looks you over once, and unlocks the cell himself.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                f"'On your feet, {_get_gw().name}. I picked you out of that river. "
                                "I'd like to walk you in myself.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo leads you down the coarse stone hallway toward the sounds of a roaring crowd. "
                                "He doesn't say anything else. He doesn't have to.",
                                WIDTH
                            ))

                        if accept_tournament == "n":
                            # --- Player refuses the tournament. Bo overrides with holding magic. ---
                            clear_screen()
                            print(wrap(
                                "'Well, that's unfortunate. That really wasn't a question, adventurer.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo mumbles something low under his breath — a sound that feels older than "
                                "language, the kind of noise that lives in an animal's chest before it lives "
                                "in any word. Your body starts to tingle. Then your muscles stop answering.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Can't have you freezing to death either.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Fire surrounds your body. You panic — but the fire is warm, not hot. "
                                "It dries you quickly and is gone before you've fully understood what happened.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Off to the tournament then. I still think you have a fair shot.'",
                                WIDTH
                            ))
                            space()
                            print(wrap("What is your name, adventurer?", WIDTH))
                            if _get_gw().name == "warrior":
                                _get_gw().name = get_name_input()
                            space()
                            print(wrap(
                                f"'Speaking of the tournament, {_get_gw().name} — would you like to "
                                "learn about it?'",
                                WIDTH
                            ))
                            learn_tournament = check(
                                "(y/n)\n> ",
                                ["y", "n"]
                            )
                            clear_screen()
                            if learn_tournament == "y":
                                print(wrap(
                                    "Bo lifts you onto his shoulder with insulting ease and begins to walk. "
                                    "The forest passes sideways in your vision. As he walks, he talks.",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'It's a monster tournament. We need fighters — terrans, mostly. "
                                    "The crowd likes terrans. You'll fight what we put in front of you, "
                                    "and if you win, you fight again. If you lose, well. You won't have "
                                    "to worry about a third fight.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'There's a trainer at the stronghold — Nob. Cranky old beast. "
                                    "He'll work you over before the crowd does. Don't take it personal. "
                                    "It's his job to find out what's wrong with you before the arena does.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "'I think you have a fair shot. I really do. You fought the river "
                                    "longer than most. That counts for something where we're going.'",
                                    WIDTH
                                ))
                            if learn_tournament == "n":
                                print(wrap(
                                    "Bo huffs. 'Suit yourself. It's easier when they don't know what's "
                                    "coming, anyway.'",
                                    WIDTH
                                ))
                                space()
                                print(wrap(
                                    "He lifts you onto his shoulder and begins to walk. The forest "
                                    "passes sideways in your vision. Bo says nothing else for a long time.",
                                    WIDTH
                                ))
                            space()
                            continue_text()
                            clear_screen()

                            # Arrival at Under-Haven. Hold breaks. Brief Nob intro.
                            print(wrap(
                                "Some long time later the world tilts. Stone floor. Cell bars. The smell "
                                "of straw and old sweat. Bo lowers you onto a rough cot with surprising "
                                "care and crouches to look you in the eye.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Hold breaks in a few minutes. By then Nob will be here. He's going to "
                                "be unkind. That's just how he is.'",
                                WIDTH
                            ))
                            space()
                            # Bo's wordless gesture of respect — the stubborn one's reward
                            print(wrap(
                                "Bo pauses. Reaches into a pouch at his hip and sets something small on the "
                                "cot beside you — a vial that glows faintly blue in the cell's dim light. "
                                "He doesn't say anything about it. He doesn't have to.",
                                WIDTH
                            ))
                            _get_gw().potions["super_ap"] += 1
                            print("🏅 You received: Super AP Potion (50% AP restore)")
                            space()
                            print(wrap(
                                "Bo stands. The cell door closes. His footsteps recede down the corridor. "
                                "You lie on the cot, fully aware, completely still, and wait for your body "
                                "to remember it belongs to you.",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Tingling returns. Nob arrives.
                            print(wrap(
                                "Feeling returns to your fingers first, then your arms, then your legs — "
                                "a slow pins-and-needles thaw. You sit up just as a cantankerous old beast "
                                "man named Nob appears at the bars.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'You're the one Bo had to carry in.' Nob looks you up and down. "
                                "'Wonderful. Fine. On your feet. We have work to do.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Path-specific Nob training: BALANCE (you fell in the river)
                            print(wrap(
                                "Nob marches you out to a stone yard ringed with weathered wooden posts. "
                                "'You fell in a river,' he says flatly. 'That tells me everything I need "
                                "to know about your footing. We're going to fix that, or you're going to "
                                "die in there. Up.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "He has you stand on a single foot until your standing leg burns. "
                                "Then the other foot. Then a narrow beam set between two of the posts — "
                                "walk it, turn at the end, walk it back, do not fall. "
                                "You fall. Nob makes you climb back up without a word.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "'Your centre of gravity is where your enemy puts it,' he barks. "
                                "'Until you take it back.' He shoves you off the beam mid-step to prove it. "
                                "You hit the dirt. You climb back up. You do it again. And again.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "By the time he lets you stop, your legs are shaking and the sky is paling. "
                                "'Better,' Nob grunts. 'Not good. Better. Back to your cell. The crowd will "
                                "be here soon.'",
                                WIDTH
                            ))
                            space()
                            continue_text()
                            clear_screen()

                            # Bo returns to escort — personal interest in the stubborn one
                            print(wrap(
                                "You sit on the cot in your cell, legs trembling, listening to the slow "
                                "rise of voices somewhere above. A crowd gathering. The sound of it "
                                "settles into your chest the way cold water did, hours ago.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Footsteps in the corridor. Not orc-guard footsteps — heavier, calmer. "
                                "Bo appears at the bars, looks you over once, and unlocks the cell himself.",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                f"'On your feet, {_get_gw().name}. I picked you out of that river. "
                                "I'd like to walk you in myself.'",
                                WIDTH
                            ))
                            space()
                            print(wrap(
                                "Bo leads you down the coarse stone hallway toward the sounds of a roaring crowd. "
                                "He doesn't say anything else. He doesn't have to.",
                                WIDTH
                            ))

                    if accept_help_final == "n":
                        clear_screen()
                        jagged_rocks_attack = random.randint(1,6) + random.randint(1,8) + random.randint(1,10) + 6
                        _get_gw().hp = max(0, _get_gw().hp - jagged_rocks_attack)
                        print(wrap("You refuse the help for the final time. You slip and lose your footing and the river carries you. " \
                        "Jagged rocks tear into your skin."))

                        space()
                        print(f"You take {jagged_rocks_attack} damage from the surrounding sharp rocks in the water.")
                        print(f"You have {_get_gw().hp} HP remaining.")
                        if _get_gw().hp <= 0:
                            print("Your body is flayed and you die")
                            _get_gw().fate_titles.add("flayed_one")
                            _get_gw().endings.add("flayed_ending")
                            # v0.6.11: route through normal end-of-run flow
                            # (was sys.exit(0) — player never saw score/leaderboard)
                            show_end_summary(_get_gw())
                            _final_score = show_run_score(_get_gw(), outcome="flayed_one")
                            view_combat_log()
                            display_at_end_of_run(_get_gw(), _final_score or 0, outcome="flayed_one")
                            prompt_play_again()
                        
                        if _get_gw().hp > 0:
                            print(wrap("Blood slowly drips down your body as the rushing water continues to pick up speed. " \
                            "'At least the worst is over now,' you think to yourself as your body goes numb." \
                            " You can see the river banks shrinking."))

                            space()
                            print(wrap("The mountain river begins to bubble and churn, and before you know it you are surrounded by white water."
                            " Keeping afloat is almost impossible as the water continuously drags you under, and then"
                            " you hear it — a distant roaring growing ever louder."))

                            continue_text()
                            clear_screen()

                            space()
                            print(wrap("You realise what you are hearing. It's the sound of a waterfall."
                            " Panic grips you. You try to swim against the current, but you are weakened from"
                            " prolonged exposure to cold water and the numerous cuts you sustained among"
                            " the jagged rocks."))

                            space()
                            survival_roll = random.randint(1,20)
                            if survival_roll >= 15:
                                print(wrap(
                                    "You dig deep and muster every ounce of strength you have left. "
                                    "If you can't make it to shore, you will die."
                                ))

                                space()
                                print(wrap(
                                    "With the last of your resolve, fueled by pure adrenaline, you find your footing, "
                                    "and painstakingly fight the raging river toward the shoreline."
                                ))

                                continue_text()
                                space()
                                print(wrap(
                                    "As you struggle across the raging water you spot a figure racing along the shoreline. "
                                    "To your relief, it's Bo. The bank is only a few feet away now. "
                                    "You can see the edge of the waterfall, a few hundred more feet and you would have gone over its edge. "
                                    "That terrifying thought distracts you, and you lose your footing as the current overwhelms you again."
                                ))

                                space()
                                print(wrap(
                                    "The tumultuous waters drag you under, and right as you are about to accept your fate, "
                                    "a furry paw reaches in and rips you out of the water. You cough and take a ragged breath, "
                                    "as Bo sets you down on solid ground. You collapse onto the forest floor, exhausted."
                                ))

                                continue_text()

                                space()
                                print(wrap(
                                    "'You have to be the most stubborn teraan I've ever met. Consider me impressed, adventurer. "
                                    "You're a survivor. You'll make an excellent addition to our tournament.'"
                                ))

                                space()
                                print(wrap(f"'I think you have a pretty decent chance to win the monster " 
                                "tournament, adventurer, but not in your current state.' " 
                                "Bo begins to chant and your wounds fully heal. He also hands you a super potion. " 
                                "These are quite rare, especially for new adventurers to come upon. Use it wisely."))
                                _get_gw().hp = _get_gw().max_hp
                                _get_gw().potions["super_potion"] += 1
                                #print(f"{_get_gw().max_hp} max hp")
                                _get_gw().death_defier = True
                                _get_gw().death_defier_river = True
                                _get_gw().death_defier_used = False
                                _get_gw().death_defier_active = False

                                space()

                                print(wrap(
                                    "Through sheer determination and unyielding willpower not to give up, you have earned the title: River Warrior!"
                                ))
                                _get_gw().max_hp += 1  # River Warrior: +1 max HP
                                award_title(_get_gw(), "river_warrior")
                                print(f"✨ +1 Permanent Max HP! (now {_get_gw().max_hp})")
                                print("🏅 New Ability Learned: River Spirit! (0 AP to activate — revives at 1 HP)")

                                continue_text()
                                clear_screen()

                                space()       

                                
                                if _get_gw().name == "warrior":
                                    _get_gw().name = get_name_input()

                                print(wrap("Despite your incredible display of bravery I still have to escort you to our arena. As long as you promise " \
                                "not to run, I'll guide you to where we are going."))



                                
                            
                            else:
                                    
                                print(wrap("You struggle to no avail. You can see the edge of the waterfall directly ahead."
                                " Your final strength fails, and you are dragged under the water, your back grazing"
                                " the now smooth bottom of the river. You are thrown off the waterfall and for a few seconds"
                                " you take in the beautiful surroundings."))

                                space() 
                                print(wrap("The sun is just starting to rise and you can make out snow-covered mountains" \
                                " covered in pine trees. You see the town of Winter Haven on the distant marble-covered cliffs, smoke" \
                                " rising from its chimneys, and then your free fall ends. Sharp pain pounds your body as you" \
                                " land hard in the icy water below the waterfall."))
                            
                                space()
                                waterfall_damage = 30
                                _get_gw().hp = max(0, _get_gw().hp - waterfall_damage)
                                print(wrap(f"You take {waterfall_damage} damage from the fall. You have {_get_gw().hp} HP remaining."))
                            if _get_gw().hp <= 0:
                                print(wrap("The impact kills you"))
                                continue_text()
                                _get_gw().fate_titles.add("drowned_one")
                                _get_gw().endings.add("Broken_one")
                                # v0.6.11: route through normal end-of-run flow
                                # (was sys.exit(0) — player never saw score/leaderboard)
                                show_end_summary(_get_gw())
                                _final_score = show_run_score(_get_gw(), outcome="drowned_one")
                                view_combat_log()
                                display_at_end_of_run(_get_gw(), _final_score or 0, outcome="drowned_one")
                                prompt_play_again()

                                
                                               


            continue_text()
            clear_screen()
            arena_battle(_get_gw())
            return






# ============================================================
# WEREWOLF DEFEAT SCENE — Halloween Seasonal (v0.08)
# ============================================================
# Fires once per run after defeating the Female Werewolf.
# She reverts to Teraan form, loses her cloak (player already
# received it via roll_halloween_drop), screams in rage, and
# bolts toward her masters. Plants the seed: the Beast Gods
# have operatives in the field, and this one got away.
#
# Called from combat.py after the Halloween drop rolls.
# Gated by story_flags so it only plays once per run.
# ============================================================

def werewolf_defeat_scene(warrior):
    """
    Post-combat cinematic for the Female Werewolf.
    Self-contained horror beat — no branching, no NPC system needed.
    """
    if "werewolf_scene_played" in warrior.story_flags:
        return  # only once per run

    warrior.story_flags.add("werewolf_scene_played")

    space()
    time.sleep(0.5)

    # ── Phase 1: The collapse and transformation ──
    print(wrap(
        "The werewolf staggers, claws scraping the dirt. "
        "A low, broken whine escapes her throat — not the sound "
        "of a beast, but something closer to a voice."
    ))
    continue_text()

    print(wrap(
        "Her body convulses. Fur recedes like shadow retreating "
        "from torchlight. Claws shrink into fingers. The massive "
        "frame folds inward, bones cracking and reshaping with "
        "sounds that make your stomach turn."
    ))
    continue_text()

    print(wrap(
        "Where a werewolf lay moments ago, a young woman now "
        "crouches in the dirt. She can't be older than twenty. "
        "Torn rags cling to her frame — what's left of the "
        "handler-issued gear she wore before the transformation."
    ))
    continue_text()

    # ── Phase 2: The cloak pickup ──
    print(wrap(
        "Her silver-grey cloak lies in the mud beside her — thick "
        "fur armor, too well-crafted to be natural. This was made "
        "for her. Issued to her. You pick it up."
    ))
    continue_text()

    # ── Phase 3: The scream ──
    print(wrap(
        "You turn to leave."
    ))
    time.sleep(0.8)

    print()
    print(f"   {RED}🐺 A scream cuts through the forest.{RESET}")
    print()
    time.sleep(0.6)

    print(wrap(
        "Not pain. Not fear. Rage — raw and absolute. "
        "The kind of sound that comes from something that has "
        "never known failure until this moment."
    ))
    continue_text()

    # ── Phase 4: She's on her feet ──
    print(wrap(
        "She's on her feet. Teeth bared, eyes burning with "
        "something between fury and humiliation. Her fists "
        "clench at her sides. For a heartbeat, you think she "
        "might lunge."
    ))
    continue_text()

    print(wrap(
        "But she doesn't. Her eyes flick over you — your "
        "weapon, your stance, the blood on your armor that "
        "isn't yours. She's calculating. And the calculation "
        "comes back wrong for her."
    ))
    continue_text()

    # ── Phase 5: She bolts ──
    print(wrap(
        "She turns and runs. Not away — toward something. "
        "Into the treeline, bare feet silent on the forest "
        "floor, moving with a speed that reminds you she is "
        "not entirely teraan."
    ))
    continue_text()

    print(wrap(
        "The forest swallows her. The silence that follows "
        "is heavier than the fight that came before it."
    ))
    time.sleep(0.5)

    print()
    print(f"   {YELLOW}You have a feeling this isn't over.{RESET}")
    print()
    continue_text()
    space()
