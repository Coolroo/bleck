/*
    A native-only mod that reports what the game's sequence machine actually
    does, and proves native C runs.

    Why this exists: D43 observed the game going LOGO -> GAME directly, never
    entering SEQ_TITLE, which meant a hook placed on the title screen sat
    correctly installed and never fired. That was inferred from watching
    `seqWork` from outside. This checks it from the inside, by counting the
    frames each sequence actually runs.

    There is no script in this mod, so `bleck` emits only the REL entry points
    and the `mod_prolog` hand-off -- the sequence table is entirely ours.

    Everything is reported through a fixed memory block so the whole test runs
    unattended; nothing here draws to the screen.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'MODC'          -- proves mod_prolog ran at all
      +0x04  hooks installed
      +0x08  frames[6], one per sequence
      +0x20  transition count
      +0x24  order[8]              -- the first eight sequences entered
      +0x44  map names seen
      +0x48  name[4][16]           -- destination of the first four map changes

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

/* Unused TRK interrupt vector table: free, and at the same address in every
   region. The Gecko loader parks a memcpy at 0x80004000, well below this. */
#define PROBE 0x80005000

#define MAGIC 0x4D4F4443U /* 'MODC' */

#define SEQ_COUNT 6
#define SEQ_MAPCHANGE 3
#define ORDER_MAX 8
#define MAPS_MAX 4

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

/*
    spm/seqdrv.h. `p0` carries the destination map name during a map change,
    which is the only place the game says out loud where it is going.
*/
typedef struct
{
    s32 seq;
    s32 stage;
    const char *p0;
    const char *p1;
} SeqWork;

/* Both resolved by name from the symbol list, like everything else. */
extern SeqDef seq_data[];
extern SeqWork seqWork;

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES(seq) (probe[2 + (seq)])
#define TRANSITIONS (probe[8])
#define ORDER(i) (probe[9 + (i)])
#define MAPS_SEEN (probe[17])
/* Four words per name, so 16 bytes each. */
#define MAPNAME(i) (probe[18 + (i) * 4])

/*
    Non-zero initialisers keep these in .data rather than .bss. The loader
    allocates this module's bss but nothing documents whether it zeroes it, and
    depending on that would be a hazard that only shows up sometimes.
*/
static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 lastSeq = 0xFFFFFFFFU;

/*
    Copy a map name into the report block, 16 bytes, NUL padded.

    Done by hand rather than with strncpy because the module links with
    -nostdlib: there is no libc here, and pulling one in for eight lines would
    be a poor trade.
*/
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
    FRAMES(seq) += 1;

    /* Record the order sequences are entered, not every frame of them. */
    if (seq != lastSeq)
    {
        if (TRANSITIONS < ORDER_MAX)
            ORDER(TRANSITIONS) = seq;
        /* Every map change names its destination; capture the first few. */
        if (seq == SEQ_MAPCHANGE && MAPS_SEEN < MAPS_MAX)
        {
            recordMapName(MAPS_SEEN, seqWork.p0);
            MAPS_SEEN += 1;
        }
        TRANSITIONS += 1;
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

/*
    Called once by the generated scaffolding, from `_prolog`.

    ⚠️ The game is barely up here. Writing to a table and swapping pointers is
    safe; touching live engine state is not. See docs/hook-points.md.
*/
void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 34; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
    probe[1] = 1;
}
