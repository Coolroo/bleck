/*
    Spawn Super Dimentio into whatever map is running.

    The point is research, not play: the real fight is hours into the game, and
    an unattended boot only ever reaches `aa4_01` and `ls4_12`. If the boss can
    be created on demand there, everything about him becomes measurable.

    ⚠️ FIRST CONTACT. A boss may well assume state its own map sets up, so the
    honest expectation is that this either fails to spawn or misbehaves. The
    probe is built to tell those apart rather than to declare success:
    a null return, a live entry, and a live-then-vanished entry all look
    different.

    Spawn happens once, from the GAME sequence, well after the map settles --
    not at `mod_prolog`, where no map is loaded and the NPC system has nothing
    to attach to.
*/

typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern u8 npcEnemyTemplates[];

/* Measured, D154: takes a template POINTER and returns the entry, or 0. */
extern void *npcEntryFromTemplate(void *enemyTemplate);

#define TEMPLATE_STRIDE 0x68
#define SUPER_DIMENTIO_TEMPLATE 255
#define EXPECTED_TRIBE 309

/* ⚠️ THE POSITIVE CONTROL. The first run hung inside the spawn call, which on
   its own cannot distinguish "bosses are special" from "this mod calls the
   function wrongly". A Goomba is the simplest possible template; if it spawns,
   the calling convention is right and the hang is about the boss. */
#define GOOMBA_TEMPLATE 2

/* NPCEntry, from npcdrv.h. */
#define ENTRY_ID 0x000
#define ENTRY_FLAG8 0x008
#define ENTRY_NAME 0x024
#define ENTRY_POSITION 0x2A0
#define ENTRY_TRIBE_ID 0x49C
#define ENTRY_MAX_HP 0x4EC
#define ENTRY_HP 0x4F0
#define ENTRY_ACTIVE 0x1u

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define CONTROL_AT_FRAME 600
#define SPAWN_AT_FRAME 900

/*
      [0] magic              [ 6] entry->maxHp
      [1] game frames        [ 7] entry->hp
      [2] spawn attempts     [ 8] entry->flag8 now
      [3] returned pointer   [ 9] frames seen alive since spawn
      [4] entry->id          [10] CONTROL: goomba entry pointer
      [5] entry->tribeId     [11] assert line, 0 if none

    [12..] assert file, then the failing expression, if one fired.
*/
#define PROBE 0x80005000
#define MAGIC 0x5DE11005u
#define REPORT_WORDS 48

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define ATTEMPTS (probe[2])
#define ENTRY_PTR (probe[3])
#define GOT_ID (probe[4])
#define GOT_TRIBE (probe[5])
#define GOT_MAX_HP (probe[6])
#define GOT_HP (probe[7])
#define GOT_FLAG8 (probe[8])
#define ALIVE_FRAMES (probe[9])
#define CONTROL_PTR (probe[10])
#define ASSERT_LINE (probe[11])
#define NAME_HEAD (probe[12])
#define CONTROL_TRIBE (probe[13])
#define ASSERT_FILE 14 /* .. 21 */
#define ASSERT_EXPR 22 /* .. 45 */
#define ASSERT_FIRED (probe[46])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u8 *spawned = 0;

/* Shift-JIS in, raw words out: an assert message is decoded on the host, not
   here (D130). */
static void copyText(u32 at, const char *text, u32 words)
{
    u32 i;
    u32 word;
    u32 j;

    for (i = 0; i < words; i++)
    {
        word = 0;
        for (j = 0; j < 4; j++)
        {
            unsigned char c = text ? (unsigned char) text[i * 4 + j] : 0;
            word = (word << 8) | c;
        }
        probe[at + i] = word;
    }
}

/* ⚠️ `__assert2` names its own cause (D130). A hang with no assert and a hang
   caused by one are different problems, and this is the only thing that tells
   them apart. */
void on_assert(const char *file, s32 line, const char *func, const char *expr)
{
    (void) func;
    if (ASSERT_FIRED == 0)
    {
        ASSERT_LINE = (u32) line;
        copyText(ASSERT_FILE, file, 8);
        copyText(ASSERT_EXPR, expr, 24);
    }
    ASSERT_FIRED += 1;
}

/* The control: the simplest template there is. */
static void spawnControl(void)
{
    u8 *tpl = npcEnemyTemplates + GOOMBA_TEMPLATE * TEMPLATE_STRIDE;
    u8 *entry = (u8 *) npcEntryFromTemplate(tpl);

    CONTROL_PTR = (u32) entry;
    if (entry != 0)
        CONTROL_TRIBE = *(u32 *) (entry + ENTRY_TRIBE_ID);
}

static void trySpawn(void)
{
    u8 *tpl = npcEnemyTemplates + SUPER_DIMENTIO_TEMPLATE * TEMPLATE_STRIDE;
    u8 *entry;

    ATTEMPTS += 1;
    entry = (u8 *) npcEntryFromTemplate(tpl);
    ENTRY_PTR = (u32) entry;
    if (entry == 0)
        return;

    spawned = entry;
    GOT_ID = *(u32 *) (entry + ENTRY_ID);
    GOT_TRIBE = *(u32 *) (entry + ENTRY_TRIBE_ID);
    GOT_MAX_HP = *(u32 *) (entry + ENTRY_MAX_HP);
    GOT_HP = *(u32 *) (entry + ENTRY_HP);
    NAME_HEAD = *(u32 *) (entry + ENTRY_NAME);
}

/* ⚠️ Reported every frame, not once. "It spawned" and "it spawned and then
   tore itself down" are different results, and only a running count separates
   them. */
static void watch(void)
{
    if (spawned == 0)
        return;
    GOT_FLAG8 = *(u32 *) (spawned + ENTRY_FLAG8);
    GOT_HP = *(u32 *) (spawned + ENTRY_HP);
    if (GOT_FLAG8 & ENTRY_ACTIVE)
        ALIVE_FRAMES += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (GAME_FRAMES == CONTROL_AT_FRAME)
            spawnControl();
        if (GAME_FRAMES == SPAWN_AT_FRAME && spawned == 0)
            trySpawn();
        watch();
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
    u32 i;

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
