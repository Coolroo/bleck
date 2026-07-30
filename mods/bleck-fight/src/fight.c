/*
    Play Count Bleck's fight, and capture the heart the moment it appears.

    Static analysis cannot finish this. A REL passes the instance name to
    `evt_npc_set_color` as a RELOCATION, so the call site holds no string and
    no colour can be attributed to an object by reading the file (D169). The
    values have to be read off the live entity.

    So: your save is loaded, HP is pinned so the fight cannot be lost, and every
    entity is scanned twice a second for anything heart-shaped. When one turns
    up, its name, model, tribe and exact RGBA are latched and kept -- the first
    sighting wins, so a prop that exists for two seconds is not overwritten by
    whatever came after.

    ⚠️ Boot map is `ls4_10`. If his fight is one room further, change
    `code.boot` to `ls4_11` and rebuild -- both were named beside `e_jigen` in
    the map REL and only playing tells them apart.
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
extern void nandLoadSave(s32 slot);
extern void *pouchGetPtr(void);
extern s32 pouchGetHp(void);
extern void pouchSetHp(s32 hp);

#define POUCH_MAX_HP 0x010
#define SAVE_SLOT 0 /* on-screen slot 1 (D108) */

#define NPC_WORK_NUM 0x004
#define NPC_WORK_ENTRIES 0x008
#define NPC_STRIDE 0x748
#define NPC_FLAG8 0x008
#define NPC_NAME 0x024
#define NPC_POSE 0x048  /* m_Anim.animPoseName */
#define NPC_COLOUR 0x0FC /* m_Anim.red/green/blue/alpha */
#define NPC_TRIBE 0x49C
#define ACTIVE 0x1u

#define MOBJ_WP 0x805ADF10
#define MOBJ_WORK_MAX 0x00
#define MOBJ_WORK_ENTRIES 0x04
#define MOBJ_STRIDE 0x2A8
#define MOBJ_NAME 0x008

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SCAN_EVERY 30

/*
      [0] magic         [3] npcs now        [6..9]   name
      [1] game frames   [4] found already   [10..17] model (animPoseName)
      [2] save loaded   [5] tribe           [18]     RGBA packed
                                            [19]     mobj hit, not npc
*/
#define PROBE 0x80005000
#define MAGIC 0xB1EC4F16u
#define REPORT_WORDS 20

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define SAVE_LOADED (probe[2])
#define NPCS_NOW (probe[3])
#define FOUND (probe[4])
#define GOT_TRIBE (probe[5])
#define GOT_RGBA (probe[18])
#define WAS_MOBJ (probe[19])

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

/* Anything a heart might be called: heart, hart, pure, konton. */
static u32 interesting(const char *s)
{
    u32 i;

    for (i = 0; i < 20 && s[i]; i++)
    {
        char a = s[i] | 0x20, b = s[i + 1] | 0x20;
        char c = s[i + 2] | 0x20, d = s[i + 3] | 0x20;

        if (a == 'h' && b == 'e' && c == 'a' && d == 'r') return 1;
        if (a == 'h' && b == 'a' && c == 'r' && d == 't') return 1;
        if (a == 'p' && b == 'u' && c == 'r' && d == 'e') return 1;
        if (a == 'k' && b == 'o' && c == 'n' && d == 't') return 1;
    }
    return 0;
}

static void keepAlive(void)
{
    unsigned char *pouch = (unsigned char *) pouchGetPtr();
    s32 max;

    if (pouch == 0) return;
    max = *(s32 *) (pouch + POUCH_MAX_HP);
    if (max > 0 && max < 999 && pouchGetHp() < max)
        pouchSetHp(max);
}

static void scan(void)
{
    u8 *work = (u8 *) npcGetWorkPtr();
    u8 *entries;
    s32 count, i;

    if (work != 0)
    {
        count = *(s32 *) (work + NPC_WORK_NUM);
        entries = *(u8 **) (work + NPC_WORK_ENTRIES);
        if (entries != 0 && count > 0 && count <= 96)
        {
            u32 live = 0;

            for (i = 0; i < count; i++)
            {
                u8 *e = entries + i * NPC_STRIDE;
                const char *name = (const char *) (e + NPC_NAME);
                const char *pose = (const char *) (e + NPC_POSE);

                if ((*(u32 *) (e + NPC_FLAG8) & ACTIVE) == 0) continue;
                live += 1;
                /* ⚠️ First sighting wins: the heart may last seconds. */
                if (FOUND || (!interesting(name) && !interesting(pose))) continue;
                FOUND = 1;
                copyText(6, name, 4);
                copyText(10, pose, 8);
                GOT_TRIBE = *(u32 *) (e + NPC_TRIBE);
                GOT_RGBA = *(u32 *) (e + NPC_COLOUR);
            }
            NPCS_NOW = live;
        }
    }

    work = *(u8 **) MOBJ_WP;
    if (work == 0 || FOUND) return;
    count = *(s32 *) (work + MOBJ_WORK_MAX);
    entries = *(u8 **) (work + MOBJ_WORK_ENTRIES);
    if (entries == 0 || count <= 0 || count > 512) return;
    for (i = 0; i < count; i++)
    {
        u8 *e = entries + i * MOBJ_STRIDE;
        const char *name = (const char *) (e + MOBJ_NAME);

        if ((*(u32 *) e & ACTIVE) == 0 || !interesting(name)) continue;
        FOUND = 1;
        WAS_MOBJ = 1;
        copyText(6, name, 4);
        return;
    }
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (loaded == 0)
        {
            nandLoadSave(SAVE_SLOT);
            loaded = 1;
            SAVE_LOADED = 1;
        }
        keepAlive();
        if ((GAME_FRAMES % SCAN_EVERY) == 0)
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
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
