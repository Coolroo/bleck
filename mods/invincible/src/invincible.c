/*
    An invincible hero, so a boss can be studied without dying to it.

    HP is restored to max every frame of the GAME sequence. Chosen over hooking
    the damage function because it FAILS SAFE: a missed frame means the player
    took a hit, never that the game hung. A damage hook with a wrong prototype
    corrupts the call and nothing can check that (D97).

    ⛔ NOT a death-proof mod. Pits, crushes and scripted deaths do not go
    through HP, so this survives damage, not everything.

    Addresses come from the symbol list via `extern`; the two struct offsets are
    from `spm-headers`' MIT `mario_pouch.h`.
*/

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

/* All four are in spm.eu0.lst. There is no `pouchGetMaxHp`, so max comes from
   the struct `pouchGetPtr` returns. */
extern void *pouchGetPtr(void);
extern s32 pouchGetHp(void);
extern void pouchSetHp(s32 hp);
extern void pouchAddHp(s32 increase);

/* MarioPouchWork, from mario_pouch.h. */
#define POUCH_HP 0x00C
#define POUCH_MAX_HP 0x010

#define SEQ_COUNT 6
#define SEQ_GAME 2

/*
    ⚠️ 0x80005000 is what `ingame.py` reads. The loader parks a memcpy at
    0x80004000, so anything lower collides.

      [0] magic            [5] lowest hp ever seen
      [1] game frames      [6] current hp
      [2] restores done    [7] max hp
      [3] self-test hits   [8] pouch pointer, 0 if never resolved
      [4] damage absorbed
*/
#define PROBE 0x80005000
#define MAGIC 0x1A010E00u
#define REPORT_WORDS 9

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define RESTORES (probe[2])
#define SELF_TEST_HITS (probe[3])
#define ABSORBED (probe[4])
#define LOWEST_HP (probe[5])
#define CURRENT_HP (probe[6])
#define MAX_HP (probe[7])
#define POUCH_PTR (probe[8])

/*
    ⚠️ THE POSITIVE CONTROL. "HP stayed at max" is exactly what a mod that does
    nothing also reports, so this hurts the player on purpose and checks the
    damage was undone. Without it the run cannot tell working from inert.

    Fires well after the attract demo has settled, so a dip is this mod's doing
    and not the demo taking a hit.
*/
#define SELF_TEST_FIRST 600
#define SELF_TEST_EVERY 300
#define SELF_TEST_DAMAGE 5

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void keepAlive(void)
{
    unsigned char *pouch = (unsigned char *) pouchGetPtr();
    s32 hp;
    s32 max;

    if (pouch == 0)
        return;
    POUCH_PTR = (u32) pouch;

    max = *(s32 *) (pouch + POUCH_MAX_HP);
    hp = pouchGetHp();
    MAX_HP = (u32) max;

    /* Sane bounds, or a bad read would have us writing nonsense into the save. */
    if (max <= 0 || max > 999)
        return;

    if (hp > 0 && (u32) hp < LOWEST_HP)
        LOWEST_HP = (u32) hp;

    if (hp < max)
    {
        ABSORBED += (u32) (max - hp);
        pouchSetHp(max);
        RESTORES += 1;
    }
    CURRENT_HP = (u32) pouchGetHp();
}

static void selfTest(void)
{
    if (GAME_FRAMES < SELF_TEST_FIRST)
        return;
    if ((GAME_FRAMES - SELF_TEST_FIRST) % SELF_TEST_EVERY != 0)
        return;

    pouchAddHp(-SELF_TEST_DAMAGE);
    SELF_TEST_HITS += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        /* Damage first, restore second, both in the same frame: the dip is
           recorded by `keepAlive` before it is undone. */
        selfTest();
        keepAlive();
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
    LOWEST_HP = 0xFFFFFFFFu;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
