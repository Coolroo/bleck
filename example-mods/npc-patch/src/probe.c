/*
    Does `npcdrv:` reach a real enemy script?

    Three patches, and the third is the point. Template 999 is past the searched
    range, so it must report NO_SCRIPT while the other two do not -- a run where
    all three agree proves nothing, whichever way they agree.

    `expect` is USER_FUNC argc 4, a guess. REFUSED would still be informative:
    it means the script was FOUND and the guard declined, so resolution worked.
    NO_SCRIPT on template 2 would mean it did not. The probe also reports each
    resolved pointer, so a wrong guess costs no second run.

      +0x00 ( 0)  magic 'NPCP'
      +0x04 ( 1)  status, npcdrv:2:onhit    2 applied, 3 refused, 4 no script
      +0x08 ( 2)  status, npcdrv:2:death
      +0x0C ( 3)  status, npcdrv:999:onhit  MUST be 4
      +0x10 ( 4)  sharers of 2:onhit  -- templates pointing at the same script
      +0x14 ( 5)  sharers of 2:death
      +0x18 ( 6)  template 2's onhit pointer, read here
      +0x1C ( 7)  its first word -- what `expect` should have been
      +0x20 ( 8)  template 2's death pointer
      +0x24 ( 9)  its first word
      +0x28 (10)  times the handler ran
      +0x2C (11)  SEQ_GAME frames. The control
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4E504350U /* 'NPCP' */
#define SEQ_COUNT 6
#define SEQ_GAME 2

#define TEMPLATE_SIZE 0x68
#define ONHIT 0x3C
#define DEATH 0x48

typedef void(SeqFunc)(void *);
typedef struct { SeqFunc *init; SeqFunc *main; SeqFunc *exit; } SeqDef;

extern SeqDef seq_data[];
extern u32 npcEnemyTemplates[];
extern u32 bleck_patch_status[];
extern u32 bleck_patch_shared[];

static volatile u32 *const probe = (volatile u32 *) PROBE;
static SeqFunc *realMain[SEQ_COUNT];

s32 on_npc(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    probe[10] += 1;
    return 2;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        probe[11] += 1;
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
    unsigned char *base = (unsigned char *) npcEnemyTemplates;
    unsigned char *t2 = base + 2 * TEMPLATE_SIZE;
    u32 i;

    for (i = 0; i < 12 + TEMPLATE_SIZE / 4; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < 3; i++)
        probe[1 + i] = bleck_patch_status[i];
    probe[4] = bleck_patch_shared[0];
    probe[5] = bleck_patch_shared[1];

    /*
        Dump template 2's whole entry rather than two guessed offsets.

        t2 + 0x40 read 0x8043B39C, but D107 measured onHitScript as 0x80494E28
        off a live entry. One of those is wrong, and D111's offsets came from a
        hex dump I reformatted by hand -- a shift of one word would move every
        field by 4 and still look self-consistent.

        So: the entry verbatim, checked against addresses measured elsewhere.
    */
    for (i = 0; i < TEMPLATE_SIZE / 4; i++)
        probe[12 + i] = *(u32 *) (t2 + i * 4);

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
