/*
    Catch `konton` while it exists.

    The Chaos Heart has no asset, model, tribe, map object or geometry node
    anywhere on the disc (D162-D167). In the REL it appears as a bare name beside
    `prorogue4`, `wedding` and `book`, right after `ls4_12_init_evt` -- and
    `wedding` IS a geometry node in that map, so these are names the map's own
    script addresses. So the heart is built by the cutscene and torn down after.

    This watches both lists every 30 frames and records every distinct instance
    name it ever sees, rather than looking for one name and reporting a zero.
    A name that only exists for a few seconds is exactly what a single sample
    misses -- which is how the last four probes failed.

      NPCEntry.name is at +0x024, MobjEntry.instanceName at +0x008.
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
extern void *npcGetWorkPtr(void);

#define NPC_WORK_NUM 0x004
#define NPC_WORK_ENTRIES 0x008
#define NPC_STRIDE 0x748
#define NPC_FLAG8 0x008
#define NPC_NAME 0x024
#define NPC_TRIBE_ID 0x49C

/* Measured, D165 -- spm.eu0.lst has no mobjdrv_wp. */
#define MOBJ_WP 0x805ADF10
#define MOBJ_WORK_MAX 0x00
#define MOBJ_WORK_ENTRIES 0x04
#define MOBJ_STRIDE 0x2A8
#define MOBJ_FLAG0 0x000
#define MOBJ_NAME 0x008
#define ACTIVE 0x1u

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define LOOK_EVERY 30

#define PROBE 0x80005000
#define MAGIC 0x40A05EA7u
#define REPORT_WORDS 64
#define SLOTS 6 /* distinct names kept, 4 words each, from word 16 */

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define NPC_SEEN (probe[2])
#define MOBJ_SEEN (probe[3])
#define DISTINCT (probe[4])
#define KONTON_SEEN (probe[5])
#define LOOKS (probe[6])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static char kept[SLOTS][16];
static u32 keptCount = 0;

static u32 sameText(const char *a, const char *b)
{
    u32 i;

    for (i = 0; i < 15; i++)
    {
        if (a[i] != b[i])
            return 0;
        if (a[i] == 0)
            return 1;
    }
    return 1;
}

static void remember(const char *name, u32 tribe)
{
    u32 i, j;

    if (name[0] == 0)
        return;
    for (i = 0; i < keptCount; i++)
        if (sameText(kept[i], name))
            return;
    if (keptCount >= SLOTS)
        return;
    for (j = 0; j < 15; j++)
        kept[keptCount][j] = name[j];
    kept[keptCount][15] = 0;

    /* 4 words per name, from word 16. */
    for (j = 0; j < 4; j++)
    {
        u32 word = 0;
        u32 k;

        for (k = 0; k < 4; k++)
            word = (word << 8) | (unsigned char) name[j * 4 + k];
        probe[16 + keptCount * 4 + j] = word;
    }
    /* Tribe id beside the name: it is what identifies the model, and a name
       alone cannot be looked up in the committed catalog. */
    probe[40 + keptCount] = tribe;
    keptCount += 1;
    DISTINCT = keptCount;
}

/* "kon" anywhere in the name, which is all the Chaos Heart needs to announce. */
static u32 looksLikeKonton(const char *s)
{
    u32 i;

    for (i = 0; i < 12 && s[i]; i++)
        if ((s[i] | 0x20) == 'k' && (s[i + 1] | 0x20) == 'o'
            && (s[i + 2] | 0x20) == 'n')
            return 1;
    return 0;
}

static void look(void)
{
    u8 *work = (u8 *) npcGetWorkPtr();
    u8 *entries;
    s32 count;
    s32 i;
    u32 npcs = 0;
    u32 mobjs = 0;

    LOOKS += 1;

    if (work != 0)
    {
        count = *(s32 *) (work + NPC_WORK_NUM);
        entries = *(u8 **) (work + NPC_WORK_ENTRIES);
        if (entries != 0 && count > 0 && count <= 96)
            for (i = 0; i < count; i++)
            {
                u8 *e = entries + i * NPC_STRIDE;
                const char *name;

                if ((*(u32 *) (e + NPC_FLAG8) & ACTIVE) == 0)
                    continue;
                npcs += 1;
                name = (const char *) (e + NPC_NAME);
                remember(name, *(u32 *) (e + NPC_TRIBE_ID));
                if (looksLikeKonton(name))
                    KONTON_SEEN += 1;
            }
    }

    work = *(u8 **) MOBJ_WP;
    if (work != 0)
    {
        count = *(s32 *) (work + MOBJ_WORK_MAX);
        entries = *(u8 **) (work + MOBJ_WORK_ENTRIES);
        if (entries != 0 && count > 0 && count <= 512)
            for (i = 0; i < count; i++)
            {
                u8 *e = entries + i * MOBJ_STRIDE;
                const char *name;

                if ((*(u32 *) (e + MOBJ_FLAG0) & ACTIVE) == 0)
                    continue;
                mobjs += 1;
                name = (const char *) (e + MOBJ_NAME);
                remember(name, 0xFFFFFFFFu);
                if (looksLikeKonton(name))
                    KONTON_SEEN += 1;
            }
    }

    if (npcs > NPC_SEEN)
        NPC_SEEN = npcs;
    if (mobjs > MOBJ_SEEN)
        MOBJ_SEEN = mobjs;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
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
