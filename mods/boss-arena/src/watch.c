/*
    Watch for Super Dimentio in the live NPC list.

    ⛔ Three runs were spent trying to create him with `npcEntryFromTemplate`
    from a sequence hook. It hangs -- for a Goomba as readily as for the boss,
    with no assert -- so it is the *call*, not the boss. That is recorded in the
    decision log; the setup file is the path D127 already proved.

    So this mod places nothing itself. `tables/enemies.csv` puts template 255
    into an1_02's setup, the game spawns it the way it spawns any enemy, and
    this only reports what turned up.
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

/* NPCWork holds the live list. `npcGetWorkPtr` is in spm.eu0.lst; there is no
   `npcEntries` or `npcGetCount` symbol, which a first draft assumed. */
extern void *npcGetWorkPtr(void);
extern u8 npcEnemyTemplates[];

/* ⚠️ THE CONTROL FOR THE HANG. His attack loop is
   `do { <attack>; evt_npc_wait_for("me", 1000) } while`, and word 28 of the
   move script is that 1000 (D151, and boss-harder already rewrites it in
   game). Setting it enormous means he attacks once and then waits out the
   run. If the freeze survives that, the attack is not the cause. */
#define TEMPLATE_STRIDE 0x68
#define TEMPLATE_MOVE_SCRIPT 0x38
#define SUPER_DIMENTIO_TEMPLATE 255
#define COOLDOWN_HEADER_AT 25
#define COOLDOWN_HEADER 0x0003005Cu
#define COOLDOWN_AT 28
#define COOLDOWN_QUIET 600000

#define WORK_NUM 0x004
#define WORK_ENTRIES 0x008
#define ENTRY_STRIDE 0x748
#define ENTRY_FLAG8 0x008
#define ENTRY_TRIBE_ID 0x49C
#define ENTRY_MAX_HP 0x4EC
#define ENTRY_HP 0x4F0
#define ENTRY_POSITION 0x2A0
#define ENTRY_ACTIVE 0x1u

#define SUPER_DIMENTIO_TRIBE 309
/* ⚠️ NPCWork.num is the array CAPACITY (measured: 80), not the live
   count. A 64 guard silently skipped the whole scan. */
#define MAX_SCAN 96

#define SEQ_COUNT 6
#define SEQ_GAME 2

/*
      [0] magic          [5] boss maxHp        [ 8] boss position x bits
      [1] game frames    [6] boss hp           [ 9] boss position y bits
      [2] npc count      [7] boss flag8        [10] frames the boss was active
      [3] active npcs                          [11] tribe of the last npc seen
      [4] boss entry pointer, 0 if never found
*/
#define PROBE 0x80005000
#define MAGIC 0xB055A5EAu
#define REPORT_WORDS 48

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define NPC_COUNT (probe[2])
#define ACTIVE_NPCS (probe[3])
#define BOSS_PTR (probe[4])
#define BOSS_MAX_HP (probe[5])
#define BOSS_HP (probe[6])
#define BOSS_FLAG8 (probe[7])
#define BOSS_X (probe[8])
#define BOSS_Y (probe[9])
#define BOSS_ALIVE_FRAMES (probe[10])
#define LAST_TRIBE (probe[11])
#define ASSERT_LINE (probe[12])
#define ASSERT_FIRED (probe[13])
#define ASSERT_FILE 14 /* .. 21 */
#define ASSERT_EXPR 22 /* .. 45 */
#define PEAK_ACTIVE (probe[46])
#define LAST_SCAN_FRAME (probe[47])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

/* Shift-JIS stays raw; it is decoded on the host (D130). */
static void copyText(u32 at, const char *text, u32 words)
{
    u32 i;
    u32 j;
    u32 word;

    for (i = 0; i < words; i++)
    {
        word = 0;
        for (j = 0; j < 4; j++)
            word = (word << 8) | (text ? (unsigned char) text[i * 4 + j] : 0);
        probe[at + i] = word;
    }
}

/* ⚠️ The reason this mod exists in its second form. A hang that is really an
   assert names its own file and line (D130); one that is not says nothing, and
   that distinction is itself the result. */
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

static void scan(void)
{
    u8 *work = (u8 *) npcGetWorkPtr();
    u8 *entries;
    u32 active = 0;
    s32 count;
    s32 i;

    if (work == 0)
        return;
    count = *(s32 *) (work + WORK_NUM);
    entries = *(u8 **) (work + WORK_ENTRIES);
    NPC_COUNT = (u32) count;
    if (entries == 0 || count < 0 || count > MAX_SCAN)
        return;

    for (i = 0; i < count; i++)
    {
        u8 *entry = entries + i * ENTRY_STRIDE;
        u32 flag8 = *(u32 *) (entry + ENTRY_FLAG8);
        u32 tribe = *(u32 *) (entry + ENTRY_TRIBE_ID);

        if ((flag8 & ENTRY_ACTIVE) == 0)
            continue;
        active += 1;
        LAST_TRIBE = tribe;

        if (tribe != SUPER_DIMENTIO_TRIBE)
            continue;

        BOSS_PTR = (u32) entry;
        BOSS_FLAG8 = flag8;
        BOSS_MAX_HP = *(u32 *) (entry + ENTRY_MAX_HP);
        BOSS_HP = *(u32 *) (entry + ENTRY_HP);
        BOSS_X = *(u32 *) (entry + ENTRY_POSITION);
        BOSS_Y = *(u32 *) (entry + ENTRY_POSITION + 4);
        if (flag8 & ENTRY_ACTIVE)
            BOSS_ALIVE_FRAMES += 1;
    }
    ACTIVE_NPCS = active;
    /* ⚠️ Peak, not current: if the pool fills and the game dies, the last
       sample before the freeze is the number that matters. */
    if (active > PEAK_ACTIVE)
        PEAK_ACTIVE = active;
    LAST_SCAN_FRAME = GAME_FRAMES;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        /* Every 30 frames: the list is walked, not sampled once, so a boss
           that appears late or vanishes early is still visible. */
        if ((GAME_FRAMES % 10) == 0)
            scan();
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

    {
        u8 *tpl = npcEnemyTemplates
                  + SUPER_DIMENTIO_TEMPLATE * TEMPLATE_STRIDE;
        u32 *script = *(u32 **) (tpl + TEMPLATE_MOVE_SCRIPT);

        if (script != 0 && script[COOLDOWN_HEADER_AT] == COOLDOWN_HEADER)
        {
            script[COOLDOWN_AT] = COOLDOWN_QUIET;
            probe[45] = COOLDOWN_QUIET;
        }
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
