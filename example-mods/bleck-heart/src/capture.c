/*
    Dump everything live, every scan, from all three drivers.

    Four runs narrowed it by elimination and each one lost the hearts a
    different way -- not NPCs, crowded out of a latched table by scenery, then
    crowded out again. So this latches nothing and filters nothing:

      NPCs        instance name + the model it renders   16 entries
      map objects instance name                          32 entries
      effects     instance name                          24 entries

    The effect list is the one never looked at, and it is where a thing that is
    neither an NPC nor a map object has to be.

      NPCWork  via npcGetWorkPtr; EffWork at 0x805ADF90; MobjWork at 0x805ADF10
      EffEntry is 0x2c, flags bit 0 = in use, instanceName at +0x18
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
extern void *pouchGetPtr(void);
extern s32 pouchGetHp(void);
extern void pouchSetHp(s32 hp);

#define POUCH_MAX_HP 0x010

#define NPC_NUM 0x004
#define NPC_ENTRIES 0x008
#define NPC_STRIDE 0x748
#define NPC_FLAG8 0x008
#define NPC_NAME 0x024
#define NPC_POSE 0x048

#define MOBJ_WP 0x805ADF10
#define MOBJ_MAX 0x00
#define MOBJ_ENTRIES 0x04
#define MOBJ_STRIDE 0x2A8
#define MOBJ_NAME 0x008

#define EFF_WP 0x805ADF90
#define EFF_COUNT 0x000
#define EFF_ENTRIES 0x004
#define EFF_STRIDE 0x2C
#define EFF_NAME 0x018
#define EFF_TYPE 0x002
#define EFF_USERWORK 0x00C
#define EFF_MAINFUNC 0x010

#define ACTIVE 0x1u
#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SCAN_EVERY 15

/*
      [0] magic   [1] frames   [2] npcs  [3] mobjs  [4] effs
      [176..335]  16 NPCs   x (name 4 + model 6)
      [336..463]  32 mobjs  x name 4
      [8  ..175]  24 effs   x (name 4 + mainFunc + userWork + type)
*/
#define PROBE 0x80005000
#define MAGIC 0x0A11DA7Au
#define EFF_AT 8
#define EFF_SLOTS 24
#define EFF_WORDS 7
#define NPC_AT 176
#define NPC_SLOTS 16
#define MOBJ_AT 336
#define MOBJ_SLOTS 32
#define REPORT_WORDS 464

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define NPCS (probe[2])
#define MOBJS (probe[3])
#define EFFS (probe[4])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void put(u32 at, const char *t, u32 words)
{
    u32 i, j, w;

    for (i = 0; i < words; i++)
    {
        w = 0;
        for (j = 0; j < 4; j++)
            w = (w << 8) | (t ? (unsigned char) t[i * 4 + j] : 0);
        probe[at + i] = w;
    }
}

static void scan(void)
{
    u8 *work;
    u8 *entries;
    s32 count, i;
    u32 slot;

    for (i = NPC_AT; i < REPORT_WORDS; i++) probe[i] = 0;

    work = (u8 *) npcGetWorkPtr();
    slot = 0;
    if (work != 0)
    {
        count = *(s32 *) (work + NPC_NUM);
        entries = *(u8 **) (work + NPC_ENTRIES);
        if (entries != 0 && count > 0 && count <= 96)
            for (i = 0; i < count && slot < NPC_SLOTS; i++)
            {
                u8 *e = entries + i * NPC_STRIDE;

                if ((*(u32 *) (e + NPC_FLAG8) & ACTIVE) == 0) continue;
                put(NPC_AT + slot * 10, (const char *) (e + NPC_NAME), 4);
                put(NPC_AT + slot * 10 + 4, (const char *) (e + NPC_POSE), 6);
                slot += 1;
            }
    }
    NPCS = slot;

    work = *(u8 **) MOBJ_WP;
    slot = 0;
    if (work != 0)
    {
        count = *(s32 *) (work + MOBJ_MAX);
        entries = *(u8 **) (work + MOBJ_ENTRIES);
        if (entries != 0 && count > 0 && count <= 512)
            for (i = 0; i < count && slot < MOBJ_SLOTS; i++)
            {
                u8 *e = entries + i * MOBJ_STRIDE;

                if ((*(u32 *) e & ACTIVE) == 0) continue;
                put(MOBJ_AT + slot * 4, (const char *) (e + MOBJ_NAME), 4);
                slot += 1;
            }
    }
    MOBJS = slot;

    work = *(u8 **) EFF_WP;
    slot = 0;
    if (work != 0)
    {
        count = *(s32 *) (work + EFF_COUNT);
        entries = *(u8 **) (work + EFF_ENTRIES);
        if (entries != 0 && count > 0 && count <= 512)
            for (i = 0; i < count && slot < EFF_SLOTS; i++)
            {
                u8 *e = entries + i * EFF_STRIDE;

                u32 at = EFF_AT + slot * EFF_WORDS;

                if ((*(unsigned short *) e & ACTIVE) == 0) continue;
                put(at, (const char *) (e + EFF_NAME), 4);
                /* mainFunc is what identifies the KIND of effect -- `type` is
                   only 0 or 1, an entry-limit group (D171). */
                probe[at + 4] = *(u32 *) (e + EFF_MAINFUNC);
                probe[at + 5] = *(u32 *) (e + EFF_USERWORK);
                probe[at + 6] = *(unsigned short *) (e + EFF_TYPE);
                slot += 1;
            }
    }
    EFFS = slot;
}

static void keepAlive(void)
{
    unsigned char *p = (unsigned char *) pouchGetPtr();
    s32 max;

    if (p == 0) return;
    max = *(s32 *) (p + POUCH_MAX_HP);
    if (max > 0 && max < 999 && pouchGetHp() < max) pouchSetHp(max);
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        keepAlive();
        if ((GAME_FRAMES % SCAN_EVERY) == 0) scan();
    }
    if (realMain[seq] != 0) realMain[seq](work);
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

    for (i = 0; i < REPORT_WORDS; i++) probe[i] = 0;
    probe[0] = MAGIC;
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
