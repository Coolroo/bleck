/*
    A Chaos Heart at the player's shoulder.

    ⛔ THE CHAOS HEART IS NOT ON THE DISC. 397 archives, every file, all 383
    map archives and all 169 MOBJ names were searched: `MOBJ_broken_heart` --
    Chapter 6's stone heart -- is the only heart asset that exists.

    So this makes one. The overlay carries that texture recoloured to dark
    violet, and Mr. L wears the model: repointing a tribe's model is one guarded
    word (D162), and only template 137 uses tribe 295 so nothing else is
    restyled.

    The recolour is `scripts/tint_tpl.py`, which rewrites CMPR endpoints and
    copies the indices untouched -- exact, and no recompression.
*/

typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;
typedef float f32;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *npcGetWorkPtr(void);
extern void *marioGetPtr(void);
extern u8 npcTribes[];

#define MARIO_POSITION 0x5C

#define WORK_NUM 0x004
#define WORK_ENTRIES 0x008
#define ENTRY_STRIDE 0x748
#define ENTRY_FLAG8 0x008
#define ENTRY_POSITION 0x2A0
#define ENTRY_TRIBE_ID 0x49C
#define ENTRY_ACTIVE 0x1u

#define MARKER_TRIBE 295 /* Mr. L, and only template 137 uses it */

/*
    ⚠️ THE COLOUR IS SET AT RUNTIME, NOT IN THE TEXTURE.

    `MOBJ_broken_heart` is the model the game itself uses for the Pure Heart --
    it sits beside the instance name `pure_heart` in the map REL, and its own
    mesh is called `pureheartShape`. It renders grey because NPCAnim carries
    red/green/blue/alpha at +0x0B8 and the game tints it per instance.

    So retinting its TPL was solving the wrong problem. NPCEntry.m_Anim is at
    +0x044, so the colour bytes are at entry +0x0FC.
*/
#define ENTRY_COLOUR 0x0FC
#define TRIBE_STRIDE 0x68
#define MODEL_WAS 0x8033B950u /* "e_dark_luigi" */
#define MODEL_NOW 0x8034F9A5u /* "MOBJ_broken_heart" */

/* Beside the player and a little above, so it does not sit inside him. */
#define OFFSET_X (140.0f)
#define OFFSET_Y (60.0f)

/* The Chaos Heart: near-black violet with a magenta cast. */
#define HEART_R 70
#define HEART_G 10
#define HEART_B 130

#define SEQ_COUNT 6
#define SEQ_GAME 2

/*
      [0] magic        [3] marker found     [5] model after
      [1] game frames  [4] model before     [6] frames the marker was placed
      [2] npcs seen
*/
#define PROBE 0x80005000
#define MAGIC 0xC4A05EA7u
#define REPORT_WORDS 8

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define NPCS_SEEN (probe[2])
#define MARKER_FOUND (probe[3])
#define MODEL_BEFORE (probe[4])
#define MODEL_AFTER (probe[5])
#define PLACED_FRAMES (probe[6])
#define COLOUR_SET (probe[7])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void placeMarker(void)
{
    u8 *work = (u8 *) npcGetWorkPtr();
    u8 *mario = (u8 *) marioGetPtr();
    u8 *entries;
    f32 *from;
    s32 count;
    s32 i;

    if (work == 0 || mario == 0)
        return;
    count = *(s32 *) (work + WORK_NUM);
    entries = *(u8 **) (work + WORK_ENTRIES);
    if (entries == 0 || count <= 0 || count > 96)
        return;
    NPCS_SEEN = (u32) count;
    from = (f32 *) (mario + MARIO_POSITION);

    MARKER_FOUND = 0;
    for (i = 0; i < count; i++)
    {
        u8 *entry = entries + i * ENTRY_STRIDE;
        f32 *pos;

        if ((*(u32 *) (entry + ENTRY_FLAG8) & ENTRY_ACTIVE) == 0)
            continue;
        if (*(u32 *) (entry + ENTRY_TRIBE_ID) != MARKER_TRIBE)
            continue;

        {
            unsigned char *rgba = (unsigned char *) (entry + ENTRY_COLOUR);

            rgba[0] = HEART_R;
            rgba[1] = HEART_G;
            rgba[2] = HEART_B;
            rgba[3] = 255;
            COLOUR_SET += 1;
        }
        pos = (f32 *) (entry + ENTRY_POSITION);
        pos[0] = from[0] + OFFSET_X;
        pos[1] = from[1] + OFFSET_Y;
        pos[2] = from[2];
        MARKER_FOUND = 1;
        PLACED_FRAMES += 1;
        break;
    }
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;

    /* The game's own update first, or its move script undoes the placement in
       the same frame (D160). */
    if (realMain[seq] != 0)
        realMain[seq](work);

    if (seq == SEQ_GAME)
        placeMarker();
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
    u32 *pose = (u32 *) (npcTribes + MARKER_TRIBE * TRIBE_STRIDE);
    u32 i;

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    MODEL_BEFORE = *pose;
    /* Refuse rather than write if this is not the tribe that was measured. */
    if (*pose == MODEL_WAS)
        *pose = MODEL_NOW;
    MODEL_AFTER = *pose;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
