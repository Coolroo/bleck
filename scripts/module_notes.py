"""What each builtin module covers, for the generated reference.

⚠️ **These are the only hand-written prose in `builtins.md`.** Everything else
on that page is derived from `catalog.json`. They live apart from the generator
so that the one file needing human judgement is the one file a reviewer has to
read.

⛔ **Per-*function* descriptions are deliberately absent.** The upstream headers
carry no prose -- 443 builtins, zero descriptions -- so a blurb each would be
443 inferences from names, published as fact. D179 already recorded why that is
worse than saying nothing: a reference is believed. A module is a claim about
~13 functions at once, cross-checkable against the names it contains in a way a
single guess is not, and each one below was written by reading its whole list.

🔶 marks a module whose purpose is inferred rather than established.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleNote:
    """One module's description, and how sure of it we are."""

    summary: str
    confident: bool = True

    def render(self) -> str:
        return self.summary if self.confident else f"🔶 {self.summary}"


def _sure(text: str) -> ModuleNote:
    return ModuleNote(text)


def _guess(text: str) -> ModuleNote:
    return ModuleNote(text, confident=False)


NOTES: dict[str, ModuleNote] = {
    "an": _sure(
        "Helpers for the `an*` maps: area darkness, texture-palette setup, and "
        "clearing a map's NPCs."
    ),
    "an2_08": _sure(
        "**The Underchomp battle** -- SPM's one turn-based, traditional Paper "
        "Mario fight. Damage calculation for both sides, XP, status effects, "
        "and the battle menu. Named for the map it happens in."
    ),
    "bos_01": _sure("Moving the Pure Heart around during a boss map's cutscenes."),
    "dan": _sure(
        "**The Pit of 100 Trials.** Per-floor enemy spawn tables, which room "
        "holds the chest and what is in it, door naming between floors, and the "
        "Wracktail countdown."
    ),
    "evt_ac": _guess(
        "Something that is started, waited on, and yields a result -- "
        "`entry`, `return_results`, `delete`. The shape of a prompt, but what "
        "kind is unestablished."
    ),
    "evt_cam": _sure(
        "The camera: position and look-at target, zooming to coordinates or a "
        "door, shake, and which dimension it is rendering. ⚠️ 13 of its 21 "
        "entries are still unnamed."
    ),
    "evt_case": _sure(
        "Running a script as a *case* -- started, exited and deleted "
        "independently of the script that launched it."
    ),
    "evt_door": _sure(
        "Doors and pipes (`dokan`). Registering the descriptor tables a map's "
        "doors come from, enabling and disabling individual ones, and attaching "
        "the script a door runs when used."
    ),
    "evt_eff": _sure(
        "Named visual effects: spawning one, deleting it, and a soft delete "
        "that lets it finish. ⚠️ Not the same as the effect *entry points* "
        "`scripts/dump_effects.py` lists -- those are called from C."
    ),
    "evt_env": _sure("Environmental blur."),
    "evt_fade": _sure(
        "Screen transitions: starting one, waiting for it to finish, and where "
        "it centres."
    ),
    "evt_fairy": _sure(
        "The pixl following the player -- position, flight to a point, "
        "animation, and per-pixl flags."
    ),
    "evt_frame": _sure(
        "2D image frames: entry and deletion, position, colour, rotation, draw "
        "speed, image animation, and a wireframe variant. The layout system "
        "cutscenes draw with."
    ),
    "evt_guide": _sure("Flags controlling the in-game guidance and hint system."),
    "evt_hit": _sure(
        "Collision objects: binding one to a map object, toggling it and its "
        "attributes, and reading its position."
    ),
    "evt_img": _sure(
        "Screen capture and the paper effect -- allocating a capture buffer, "
        "applying it as paper, and waiting for the animation to end."
    ),
    "evt_item": _sure(
        "Item entities placed in a map: spawning, position, and waiting until "
        "the player collects one."
    ),
    "evt_map": _sure(
        "The map itself -- playing and checking its animations, display "
        "toggles, ladders and blending -- plus colour, flags and position for "
        "map objects addressed by group."
    ),
    "evt_mario": _sure(
        "The player: position, height, facing (a point or an NPC), pose and "
        "animation, jumping and walking to a point, taking damage, which "
        "character is active, and locking control."
    ),
    "evt_mobj": _sure(
        "Map objects -- blocks, save blocks, arrows, pipes and their kin. Most "
        "spawn functions take a position **and the script to run on "
        "interaction**, which is what makes a block do anything. Also "
        "position, rotation, scale and animation."
    ),
    "evt_msg": _sure(
        "Dialogue windows: printing a message by id, appending to an open one, "
        "inserting values, and the selection prompt."
    ),
    "evt_npc": _sure(
        "**The largest module.** NPCs by instance name: spawning (including "
        "from a template id), movement, animation, HP, per-part attack power, "
        "flags, scale, colour, and the generic property get/set pair."
    ),
    "evt_offscreen": _sure("Offscreen render targets and their bounding boxes."),
    "evt_paper": _sure("Paper-mode entities: entry and deletion."),
    "evt_pouch": _sure(
        "The player's inventory and stats: coins, HP, attack, items, shop "
        "points and charms. Everything the pause menu shows."
    ),
    "evt_seq": _sure(
        "The game sequence. **`evt_seq_mapchange` is how a script sends the "
        "game to another map**, and is what makes any map reachable without "
        "playing there -- see [Testing a mod](../guides/testing.md)."
    ),
    "evt_shop": _sure(
        "Shops: building each shopkeeper's item table, buying and selling, "
        "charms, and shop points. ⚠️ 53 of its 54 entries have no recorded "
        "signature, the worst coverage of any module."
    ),
    "evt_snd": _sure(
        "Music and sound: background music on and off with fades, sound "
        "effects, and per-channel control."
    ),
    "evt_sub": _sure(
        "Odds and ends that fit nowhere else -- **reading the controller**, "
        "distance between two points, displaying the room name, and animation "
        "groups."
    ),
    "item_event_data": _sure("Where a pipe returns the player to, for one item event."),
    "machi": _sure("Elevator descriptors for the town map."),
    "npc_dimeen_l": _guess(
        "Behaviour for a Dimentio-family NPC: damage from its box attack, and "
        "choosing where to move next."
    ),
    "npc_ninja": _sure("A bomb that damages the player."),
    "npc_shadoo": _guess(
        "**Shadoo**, the Flopside Pit of 100 Trials boss. 5 of its 7 entries "
        "are unnamed, so the module is placed by name alone."
    ),
    "sp4_13": _guess("One unnamed function belonging to map `sp4_13`."),
}
