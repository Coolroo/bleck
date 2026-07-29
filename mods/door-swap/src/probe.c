/*
    Can a vanilla script be replaced by SWAPPING THE POINTER, rather than
    patching the bytecode it points at?

    `code.patches` mutates the bytecode in place, which limits it to same-size
    replacement -- the one mutation that moves no jump-table label (D89, D90).
    Swapping the pointer instead would give arbitrary logic with no jump-table
    problem at all, because the replacement is built whole.

    ⛔ **This is known to fail for a map's init script.** D51 swapped
    `MapData.initScript`, every mechanical check passed, and the map froze
    mid-load. The untested explanation is that the loader waits on the specific
    `EvtEntry` it created from that pointer, which a replacement never satisfies.

    🔶 **The question here is whether that reasoning extends to a DOOR.** A
    door's interact script is started by the player using the door, not by the
    map-load sequence, so there may be nothing waiting on a particular entry.
    If so, this is the MIT-clean route to what `evtpatch` (GPL-3) does.

    THE SWAP

    A map registers its doors by calling `evt_door_set_door_descs(descs, count)`
    from its init script, so the array's address is a constant sitting in the
    bytecode -- readable at `_prolog`, before the script has ever run, which is
    why `code.patches` can already reach doors. This writes the field instead of
    reading through it.

    ⚠️ THE CONTROL IS THE ORIGINAL POINTER. Reporting "we wrote it" proves
    nothing: D51 passed every such check and still froze. probe[6] holds what was
    there before and probe[7] what is there after, so "the write landed" and
    "the script ran" stay separate claims.

    Report block at PROBE, big-endian u32:

      +0x000 ( 0)  magic 'DSWP'
      +0x004 ( 1)  SEQ_MAPCHANGE frames
      +0x008 ( 2)  SEQ_GAME frames -- nonzero means the map finished loading
      +0x00C ( 3)  times the replacement script's USER_FUNC ran
      +0x010 ( 4)  times __assert2 fired, and
      +0x014 ( 5)  the line of the first one -- a freeze that is really an
                   assert names itself (D130)
      +0x018 ( 6)  the door's ORIGINAL interact script pointer, 0 if unresolved
      +0x01C ( 7)  what the field holds after the swap
      +0x020 ( 8)  address of the field itself
      +0x024 ( 9)  the replacement script's address
      +0x028 (10)  the field re-read EVERY GAME FRAME
      +0x02C (11)  frame the replacement was run directly, 0 if never

    ⚠️ Word 11 disambiguates the human test. If a player uses the door and
    word 3 stays 0, that could mean the bytecode is malformed OR that the door
    never reads this field -- two very different answers. Running the script
    directly through `evtEntry` settles the first, so whatever the door does,
    the result is readable.

    ⚠️ Word 10 is the one that matters. Word 7 only says the write happened at
    `_prolog`; the descriptor array lives in data the map loads, so the load
    could put the original back and nothing so far would notice. Re-reading it
    during gameplay is the difference between "we wrote it" and "it is still
    ours when the player could use the door".

    Read all 11 words.

    ⚠️ Success is probe[2] climbing AND probe[3] nonzero after the door is used.
    Using a door needs a human: input cannot be injected (D48). An unattended run
    can only show the map still loads, which is the half D51 failed.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x44535750U /* 'DSWP' */

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SEQ_MAPCHANGE 3

#define REPORT_WORDS 12

/* Which door, and which of its three scripts. `he1_01` door 0 is the one D104
   drove by hand, so its interact script is known to be reachable. */
#define DOOR_MAP "he1_01"
#define DOOR_INDEX 0

/* DoorDesc is 0x58 bytes: interactScript +0x40, initScript +0x50,
   moveScript +0x54 (spm-headers `evt_door.h`, MIT). */
#define DOORDESC_SIZE 0x58
#define DOOR_INTERACT 0x40

#define MAP_INIT_SCRIPT 0x18

/* `evt_door_set_door_descs(descs, count)` -- argc 3, MEASURED (D102).
   `evt_door.h` declares 1, meaning argc 2, and is wrong. */
#define DOOR_SETTER_HEADER 0x0003005Cu

#define EVT_END_SCRIPT 0x0001u
#define EVT_END_EVT 0x0002u
#define EVT_USER_FUNC 0x005Cu
#define EVT_MAX_OPCODE 0x0077u
#define EVT_MAX_ARGC 16u
#define DOOR_WALK_LIMIT 4096

extern void *mapDataPtr(const char *name);
extern void *evtEntry(const s32 *script, u32 priority, u8 flags);
extern void evt_door_set_door_descs(void);
extern void bleck_dump_door_names(const char *map);
extern void bleck_dump_map_doors(const char *map);

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define MAPCHANGE_FRAMES (probe[1])
#define GAME_FRAMES (probe[2])
#define RAN (probe[3])
#define ASSERTS (probe[4])
#define ASSERT_LINE (probe[5])
#define ORIGINAL (probe[6])
#define AFTER (probe[7])
#define FIELD (probe[8])
#define REPLACEMENT (probe[9])
#define LIVE (probe[10])
#define SELFTEST (probe[11])

static SeqFunc *realMain[SEQ_COUNT];

/*
    The replacement script: one USER_FUNC into `on_door_used`, then end.

    `{2, 1}` is END_EVT then END_SCRIPT -- exactly what `bleck` emits for an
    empty compiled script, copied rather than invented. ⚠️ Two terminators, not
    one: END_SCRIPT ends the instruction *list* and END_EVT ends the running
    *entry*, and emitting only one froze the game once already (D-scripting).

    ⚠️ argc counts the function pointer. `evt_door_set_door_descs` is argc 3 for
    a pointer plus two arguments, so a bare call is argc 1.

    Filled at run time rather than statically initialised, so no relocation of a
    function address into a data array is involved -- one fewer thing to be
    wrong about if this fails.
*/
static s32 replacement[4];

static s32 on_door_used(void *entry, s32 firstCall)
{
    (void) entry;
    (void) firstCall;
    RAN += 1;
    return 2; /* advance the script */
}

/* Address OF the descriptor field, where `bleck_door_script` returns the value
   IN it. That one difference is the whole experiment. */
static u32 **door_field(const char *map, s32 index, s32 offset)
{
    unsigned char *data = (unsigned char *) mapDataPtr(map);
    u32 *script;
    u32 at = 0;

    if (data == 0)
        return 0;
    script = *(u32 **) (data + MAP_INIT_SCRIPT);
    if (script == 0)
        return 0;

    while (at < DOOR_WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFu;

        if (opcode == EVT_END_SCRIPT)
            return 0;
        if (opcode > EVT_MAX_OPCODE || argc > EVT_MAX_ARGC)
            return 0;

        if (header == DOOR_SETTER_HEADER
            && script[at + 1] == (u32) &evt_door_set_door_descs)
        {
            unsigned char *descs = (unsigned char *) script[at + 2];
            s32 count = (s32) script[at + 3];

            if (descs == 0 || index >= count)
                return 0;
            return (u32 **) (descs + index * DOORDESC_SIZE + offset);
        }
        at += 1 + argc;
    }
    return 0;
}

void on_assert(const char *file, s32 line, const char *func, const char *expr)
{
    (void) file;
    (void) func;
    (void) expr;
    if (ASSERTS == 0)
        ASSERT_LINE = (u32) line;
    ASSERTS += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_MAPCHANGE)
        MAPCHANGE_FRAMES += 1;
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        /* Re-resolved from scratch, not cached: a stale pointer would report
           our own write back to us and prove nothing. */
        {
            u32 **field = door_field(DOOR_MAP, DOOR_INDEX, DOOR_INTERACT);
            LIVE = field ? (u32) *field : 0;

            /* Once, well after the map settles, run what the door would run.
               Not at frame 0: the evt manager is up by SEQ_GAME but the map is
               still assembling itself for a while after. */
            if (SELFTEST == 0 && GAME_FRAMES > 600 && LIVE != 0)
            {
                SELFTEST = GAME_FRAMES;
                evtEntry((const s32 *) LIVE, 0, 0);
            }
        }
    }
    if (realMain[seq] != 0)
        realMain[seq](work);
}

static void seq0(void *w) { onSequenceFrame(0, w); }
static void seq1(void *w) { onSequenceFrame(1, w); }
static void seq2(void *w) { onSequenceFrame(2, w); }
static void seq3(void *w) { onSequenceFrame(3, w); }
static void seq4(void *w) { onSequenceFrame(4, w); }
static void seq5(void *w) { onSequenceFrame(5, w); }

static SeqFunc *const hooks[SEQ_COUNT] = {seq0, seq1, seq2, seq3, seq4, seq5};

void mod_prolog(void)
{
    u32 **field;
    u32 i;

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    replacement[0] = (s32) ((1u << 16) | EVT_USER_FUNC);
    replacement[1] = (s32) &on_door_used;
    replacement[2] = (s32) EVT_END_EVT;
    replacement[3] = (s32) EVT_END_SCRIPT;
    REPLACEMENT = (u32) replacement;

    bleck_dump_door_names(DOOR_MAP);
    bleck_dump_map_doors(DOOR_MAP);

    field = door_field(DOOR_MAP, DOOR_INDEX, DOOR_INTERACT);
    FIELD = (u32) field;
    if (field != 0)
    {
        ORIGINAL = (u32) *field;
        *field = (u32 *) replacement;
        AFTER = (u32) *field;
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
