/*
    What map objects exist in Flipside, and what models do they use?

    The Pure Heart is geometry inside `map.dat`, which is undecoded (D165), so
    its object cannot be read off the disc. But a live one exists in the first
    heart pillar once a save with progress is loaded -- so this asks the running
    game rather than guessing names, which is what the previous attempt did and
    it found nothing (5 tried, 0 found).

    ⚠️ SAVE SLOT FIRST. On-screen "slot 1" is index 0 (D108), and `nandLoadSave`
    is safe from the first frame a sequence hook runs -- no delay, unlike
    `code.boot`. Without it the pillars are empty and there is nothing to find.

    The object list is walked through `MobjWork`, whose pointer sits at
    0x805ADF10 -- read out of `mobjNameToPtrNoAssert`, since the symbol list
    does not name it (D165).
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
extern void nandLoadSave(s32 slot);
extern const char *mobjGetModelName(void *mobj);

/* ⚠️ Hard-coded because spm.eu0.lst has no `mobjdrv_wp`. Measured, D165. */
#define MOBJ_WP 0x805ADF10
#define WORK_MAX 0x00
#define WORK_ENTRIES 0x04
#define ENTRY_STRIDE 0x2A8
#define ENTRY_FLAG0 0x000
#define ENTRY_NAME 0x008
#define ENTRY_ACTIVE 0x1u

#define SAVE_SLOT 0 /* on-screen "slot 1" */

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define LOOK_EVERY 120

#define PROBE 0x80005000
#define MAGIC 0x9EA27EEDu
#define REPORT_WORDS 64

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define SAVE_LOADED (probe[2])
#define OBJ_MAX (probe[3])
#define OBJ_ACTIVE (probe[4])
#define HEART_HITS (probe[5])
#define OBJ_NAMED (probe[6])
#define LOOKS (probe[7])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};
static u32 loaded = 0;

static void copyText(u32 at, const char *text, u32 words)
{
    u32 i, j, word;

    for (i = 0; i < words; i++)
    {
        word = 0;
        for (j = 0; j < 4; j++)
            word = (word << 8) | (text ? (unsigned char) text[i * 4 + j] : 0);
        probe[at + i] = word;
    }
}

/* Case-insensitive "does this name contain 'heart' or 'hart'". */
static u32 looksLikeHeart(const char *s)
{
    u32 i;

    for (i = 0; i < 12 && s[i]; i++)
    {
        char a = s[i] | 0x20;
        char b = s[i + 1] | 0x20;
        char c = s[i + 2] | 0x20;
        char d = s[i + 3] | 0x20;

        if (a == 'h' && b == 'e' && c == 'a' && d == 'r')
            return 1;
        if (a == 'h' && b == 'a' && c == 'r' && d == 't')
            return 1;
    }
    return 0;
}

static void look(void)
{
    u8 *work = *(u8 **) MOBJ_WP;
    u8 *entries;
    s32 max;
    s32 i;
    u32 active = 0;
    u32 named = 0;
    u32 slot = 16;

    LOOKS += 1;
    if (work == 0)
        return;
    max = *(s32 *) (work + WORK_MAX);
    entries = *(u8 **) (work + WORK_ENTRIES);
    OBJ_MAX = (u32) max;
    if (entries == 0 || max <= 0 || max > 512)
        return;

    for (i = 0; i < max; i++)
    {
        u8 *e = entries + i * ENTRY_STRIDE;
        const char *name;

        name = (const char *) (e + ENTRY_NAME);
        /* ⚠️ Counted two ways. The flag0 test is what mobjNameToPtr uses, but
           if it undercounts, a non-empty name still says the slot is in use. */
        if (*(u32 *) (e + ENTRY_FLAG0) & ENTRY_ACTIVE)
            active += 1;
        if (name[0] != 0)
            named += 1;
        /* ⚠️ POSITIVE CONTROL. Dump the first few names whatever they are: if
           they read as sensible strings the walk is right, and if they are
           garbage the pointer or stride is wrong -- which "0 hearts" alone
           cannot distinguish. */
        if (name[0] == 0)
            continue;
        if (slot <= REPORT_WORDS - 8)
        {
            copyText(slot, name, 4);
            copyText(slot + 4, mobjGetModelName(e), 4);
            slot += 8;
        }
        if (!looksLikeHeart(name))
            continue;
        HEART_HITS += 1;
    }
    /* Peaks, not the latest sample: the map populates over time and an early
       look sees almost nothing -- which is what the first run reported. */
    if (active > OBJ_ACTIVE)
        OBJ_ACTIVE = active;
    if (named > OBJ_NAMED)
        OBJ_NAMED = named;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (loaded == 0)
        {
            /* No delay needed; the save array is live on frame 1 (D108). */
            nandLoadSave(SAVE_SLOT);
            loaded = 1;
            SAVE_LOADED = 1;
        }
        if ((GAME_FRAMES % LOOK_EVERY) == 0)
            look();
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
