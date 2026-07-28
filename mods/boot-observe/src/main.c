/*
    Is the generated boot watcher never *running*, or running and achieving
    nothing?

    D73 narrowed the failure to one cell: a module holding both the combination
    watcher and the generated boot block never changes maps. The generated C is
    correct by inspection, the boot script is in memory correctly relocated, and
    the called function binds to the right address -- so the remaining question
    is whether `evtEntry` is reached at all.

    Today that is unanswerable, because the only evidence is whether the map
    changed, and that conflates "the watcher never ran" with "it ran and the
    script did nothing".

    This replicates `bleck_boot_on_seq` exactly -- a `static u32 = 1` gate, one
    shot, on the first gameplay frame -- and reports each step instead of
    inferring. The combo block is pulled in by `code.combos` in the manifest, so
    the module has the same shape as the failing one.

    Report block, big-endian u32:

      +0x00  magic 'BOOT'          -- mod_prolog ran
      +0x04  gameplay frames       -- the sequence hook is live
      +0x08  watcher reached       -- the `if` was evaluated
      +0x0C  gate seen as          -- what bleck_boot_pending's twin read as
      +0x10  evtEntry called
      +0x14  evtEntry returned     -- non-zero means it did not hang
      +0x18  its return value      -- the EvtEntry pointer, or 0 on failure

    Read alongside gw[28], which the script itself writes: 1 started,
    2 settled, 3 survived its own map change (it should not -- D43).
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x424F4F54U /* 'BOOT' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *evtEntry(const s32 *script, u32 priority, unsigned char flags);

/* The compiled script, by the name bleck gives it. */
extern const s32 bleck_script_booter[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES (probe[1])
#define REACHED (probe[2])
#define GATE (probe[3])
#define CALLED (probe[4])
#define RETURNED (probe[5])
#define RESULT (probe[6])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

/* Same declaration as the generated `bleck_boot_pending`, deliberately. */
static u32 bootPending = 1;

static void onSequenceFrame(u32 seq, void *work)
{
    void *entry;

    if (seq == SEQ_GAME)
    {
        FRAMES += 1;
        REACHED += 1;
        GATE = bootPending;

        if (bootPending != 0)
        {
            bootPending = 0;
            CALLED = 1;
            entry = evtEntry(bleck_script_booter, 0, 0);
            RETURNED = 1;
            RESULT = (u32) entry;
        }
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

    for (i = 0; i < 8; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
