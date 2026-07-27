/*
    The native half of a mod.

    A script cannot do what is below. `USER_FUNC` only reaches the game's ~443
    declared evt builtins, and every one of them takes `(EvtEntry *, bool)` --
    so an ordinary game function like `pouchGetCoin` or `mapDataPtr` is simply
    out of reach from a script.

    That is the whole reason `code.sources` exists. Native C can:

      - call any function in the symbol list, by name
      - read and write game structures
      - attach a script to a map, door, item or NPC, which is how event mods
        are actually built

    Everything here is resolved by name at link time, exactly like the
    generated code. No addresses appear in this file.

    Target: eu0. Symbol names are shared across versions; addresses are not.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;
typedef float f32;

/* --- what we borrow from the game ---------------------------------------- */

/*
    spm/map_data.h. `initScript` is the evt script a map runs when it loads,
    which makes it the natural place to attach behaviour to one specific room.
*/
typedef struct
{
    const char *name;
    const char *filename;
    const char *fallbackDoorName;
    f32 fallbackSpawnPos[3];
    const s32 *initScript;
} MapData;

extern MapData *mapDataPtr(const char *name);

/* spm/mario_pouch.h -- ordinary functions, not evt builtins. */
extern s32 pouchGetCoin(void);
extern void pouchSetCoin(s32 coins);

/* --- our own state ------------------------------------------------------- */

/*
    Non-zero initialiser keeps this in .data rather than .bss. The loader
    allocates this module's bss but nothing documents whether it zeroes it,
    and depending on that would be a silent hazard.
*/
static const s32 *realFlipsideInit = (const s32 *) 1;

/* --- the hand-off from generated code ------------------------------------ */

/*
    `bleck` calls this once, from `_prolog`, after installing its own sequence
    hooks. The generated module owns `_prolog` so that ordering is guaranteed.

    ⚠️ This runs at load time, when the game is barely up. Patching pointers and
    reading tables is fine here; anything touching live engine state is not.
    See docs/hook-points.md for what is alive when.
*/
void mod_prolog(void)
{
    MapData *flipside = mapDataPtr("mac_01");

    if (flipside != 0)
    {
        /*
            Remember what was there. Replacing it outright would delete the
            map's own setup -- this only records it, so a future version can
            chain to it rather than discard it.
        */
        realFlipsideInit = flipside->initScript;
    }

    /*
        Round the player's coins down to a multiple of ten, once, at load.
        Pointless on its own; it is here because it demonstrates the thing a
        script cannot do -- calling a plain game function directly.
    */
    if (pouchGetCoin() % 10 != 0)
        pouchSetCoin(pouchGetCoin() / 10 * 10);
}
