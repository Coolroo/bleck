/*
    Can a mod load a save slot by itself?

    Every attended test so far has cost a human at the title screen picking a
    file. `nandLoadSave(s32 saveId)` is a plain function in the DOL, so the rig
    could do it -- which would turn the item hook, the door hook and anything
    needing player state into unattended runs.

    Two questions, and the first must be answered before the second is even
    safe to ask:

      1. Does `nandGetSaveFiles()` return a usable array, and which slots hold
         a real save? Read-only. `flags` and the checksum pair distinguish a
         written slot from an empty one, so this reports both rather than
         guessing from either.

      2. Is there a point at which `nandLoadSave` can be called without wedging
         the game? `code.boot` needed 120 frames before `evt_seq_mapchange` or
         the map loader stalled at stage 11 (D72). A save load is likely fussier,
         not less, so this waits on the TITLE sequence and reports what the game
         does afterwards rather than assuming it worked.

    ⚠️ The load is attempted ONCE and only if a slot looks written. Calling it
    on an empty slot would load garbage into player state, which is a worse
    failure than not calling it -- it would look like a working load.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'SAVE'
      +0x04 ( 1)  nandGetSaveFiles()
      +0x08 ( 2)  slot 0 flags        -- the user's save is slot 1 on screen,
      +0x0C ( 3)  slot 1 flags           which is index 0 here if it is 0-based
      +0x10 ( 4)  slot 2 flags
      +0x14 ( 5)  slot 3 flags
      +0x18 ( 6)  slot 0 checksum
      +0x1C ( 7)  slot 1 checksum
      +0x20 ( 8)  slot 2 checksum
      +0x24 ( 9)  slot 3 checksum
      +0x28 (10)  which index the load was attempted on, else -1
      +0x2C (11)  the first frame nandGetSaveFiles() was non-null
      +0x30 (12)  SEQ_GAME frames AFTER the load -- the answer. Climbing means
                  the game survived and reached gameplay
      +0x34 (13)  a bitmask of every sequence seen, so a wedge is visible as
                  "stopped on TITLE" rather than inferred from silence
      +0x38 (14)  total frames, all sequences. The control: zero invalidates

    Run with:  scripts/ingame.py save-probe --words 16 --seconds 120
    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x53415645U /* 'SAVE' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define SAVE_SLOTS 4
#define SAVEFILE_SIZE 0x25B8
#define SAVEFILE_FLAGS 0x0000
#define SAVEFILE_CHECKSUM 0x25B0

/* Long enough that the title screen is genuinely settled. D72's 120 frames was
   the floor for a map change; this doubles it rather than finding the edge. */
/* Frames to wait after the array appears, before touching it. */
#define LOAD_DELAY 240

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *nandGetSaveFiles(void);
extern void nandLoadSave(s32 saveId);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FILES_PTR (probe[1])
#define FLAGS(i) (probe[2 + (i)])
#define CHECKSUM(i) (probe[6 + (i)])
#define LOADED_INDEX (probe[10])
#define READY_AT (probe[11])
#define GAME_AFTER (probe[12])
#define SEQ_SEEN (probe[13])
#define TOTAL_FRAMES (probe[14])

static SeqFunc *realMain[SEQ_COUNT];
static u32 attempted;

static void readSlots(void)
{
    unsigned char *files = (unsigned char *) nandGetSaveFiles();
    u32 i;

    FILES_PTR = (u32) files;
    if (files == 0)
        return;
    for (i = 0; i < SAVE_SLOTS; i++)
    {
        unsigned char *slot = files + i * SAVEFILE_SIZE;

        FLAGS(i) = *(u32 *) (slot + SAVEFILE_FLAGS);
        CHECKSUM(i) = *(u32 *) (slot + SAVEFILE_CHECKSUM);
    }
}

/* A slot with no flags and no checksum was never written. Both, because either
   alone could plausibly be zero in a real save. */
static u32 slotLooksWritten(u32 index)
{
    return (FLAGS(index) != 0 || CHECKSUM(index) != 0) ? 1u : 0u;
}

static void onSequenceFrame(u32 seq, void *work)
{
    TOTAL_FRAMES += 1;
    SEQ_SEEN |= (1u << seq);

    /*
        SAMPLE EVERY FRAME, whatever the sequence.

        Run 1 gated all of this on SEQ_TITLE and learned nothing: SEQ_SEEN came
        back 0x0D -- LOGO, GAME, MAPCHANGE -- so the attract demo never reaches
        TITLE at all, and the whole instrument sat behind a branch that never
        ran. A null `nandGetSaveFiles()` was then reported as if it had been
        measured, when it had simply never been called.

        Reading unconditionally also answers a question the gated version could
        not: WHEN the save array becomes available. `readyAt` is the first frame
        it was non-null, which is the thing a `--save-slot` feature needs to
        know.
    */
    readSlots();
    if (FILES_PTR != 0 && READY_AT == 0)
        READY_AT = TOTAL_FRAMES;

    if (attempted == 0 && READY_AT != 0 && TOTAL_FRAMES >= READY_AT + LOAD_DELAY)
    {
        attempted = 1;
        if (slotLooksWritten(0))
        {
            LOADED_INDEX = 0;
            nandLoadSave(0);
        }
    }

    if (seq == SEQ_GAME && attempted != 0)
        GAME_AFTER += 1;

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
    u32 i;

    for (i = 0; i < 15; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    LOADED_INDEX = 0xFFFFFFFFU;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
