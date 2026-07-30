/*
    Reports whether the map attachment actually installed.

    `gw[31]` tells us the attached script *ran*. This tells us whether it was
    ever *installed*, which is a different question with a different fix. If
    `mapDataPtr` returns null at `_prolog` -- because the map table is not
    populated that early, say -- nothing downstream can work, and without this
    that failure looks exactly like a script that ran and did nothing.

    ⚠️ `mod_prolog` runs *after* the generated `bleck_install_maps()`, so the
    values read here are post-install by construction.

    It also captures map names, which is the regression signal for this whole
    feature: an unattended boot normally goes `aa4_01` then `ls4_12`. The
    wrapper runs the map's own init script before ours precisely so the map
    still works -- so if `ls4_12` never arrives, we broke `aa4_01`.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'GOTO'
      +0x04  mapDataPtr("aa4_01"), or 0
      +0x08  its initScript after install -- should be our wrapper
      +0x0C  the wrapper's word 1, i.e. the map's original script
      +0x10  map changes seen
      +0x14  name[3][16]

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x474F544FU /* 'GOTO' */

#define MAP_INIT_OFFSET 0x18
#define SEQ_COUNT 6
#define SEQ_MAPCHANGE 3
#define MAPS_MAX 4

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

typedef struct
{
    s32 seq;
    s32 stage;
    const char *p0;
    const char *p1;
} SeqWork;

extern SeqDef seq_data[];
extern SeqWork seqWork;
extern void *mapDataPtr(const char *name);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define MAP_PTR (probe[1])
#define MAP_INIT (probe[2])
#define MAP_ORIGINAL (probe[3])
#define MAPS_SEEN (probe[4])
#define MAPNAME(i) (probe[5 + (i) * 4])

static const char watched[] = "he1_01";

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 lastSeq = 0xFFFFFFFFU;

/* By hand: the module links -nostdlib, so there is no strncpy to call. */
static void recordMapName(u32 slot, const char *name)
{
    volatile u32 *out = &MAPNAME(slot);
    u32 i;

    for (i = 0; i < 4; i++)
        out[i] = 0;
    if (name == 0)
        return;
    for (i = 0; i < 15 && name[i] != 0; i++)
        ((volatile unsigned char *) out)[i] = (unsigned char) name[i];
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq != lastSeq)
    {
        if (seq == SEQ_MAPCHANGE && MAPS_SEEN < MAPS_MAX)
        {
            recordMapName(MAPS_SEEN, seqWork.p0);
            MAPS_SEEN += 1;
        }
        lastSeq = seq;
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
    unsigned char *entry;
    u32 i;

    for (i = 0; i < 20; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    entry = (unsigned char *) mapDataPtr(watched);
    MAP_PTR = (u32) entry;
    if (entry != 0)
    {
        s32 *slot = (s32 *) (entry + MAP_INIT_OFFSET);
        MAP_INIT = (u32) *slot;
        /* Word 1 of the wrapper is the original script the generated code
           saved. Reading it back proves the preserve-then-append actually
           captured something rather than patching in a zero. */
        MAP_ORIGINAL = (u32) ((s32 *) *slot)[1];
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
