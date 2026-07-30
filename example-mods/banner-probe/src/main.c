/*
    Verifying that the generated `mod_loaded` banner actually works.

    The banner normally draws on the title screen, which an unattended boot
    never reaches -- the game plays its attract demo instead (D47), and input
    cannot be injected on a locked machine (D48). So this mod's manifest also
    puts the banner on SEQ_GAME, which a boot *does* reach on its own after
    about 45 seconds.

    That turns an unobservable feature into a measurable one. Three things get
    reported, and together they cover the ways the banner could be broken:

      - **gameplay frames keep climbing.** The generated banner draws once per
        frame from a `seq_data[].main` hook. If that call sequence were invalid
        the game would hang or crash, and the count would stop.
      - **FontGetMessageWidth returns a plausible width.** Measured from the
        same context the banner draws in, so a non-zero, roughly-proportional
        result proves the font subsystem is up and really did process our
        string -- rather than merely proving nothing crashed.
      - **the width is measured twice**, early and late, to catch a font that
        is only ready some of the time.

    ⚠️ What this cannot check is where the text lands on screen. Screen
    placement is inferred from `spm-rel-loader`'s centring maths and stays a
    hypothesis until someone looks. See D49.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'BANR'      -- proves mod_prolog ran
      +0x04  hooks installed
      +0x08  frames[6], one per sequence
      +0x20  width measured on the first gameplay frame
      +0x24  width measured once gameplay has been running a while
      +0x28  measurement count

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned short u16;

/* Unused TRK interrupt vector table, as everywhere else here. */
#define PROBE 0x80005000

#define MAGIC 0x42414E52U /* 'BANR' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* Late enough that the map is fully up, early enough to see within a run. */
#define LATE_FRAME 600

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

/*
    The same measurement call the generated banner uses to right-align itself.
    Resolved by name from the symbol list, like everything else.
*/
extern u16 FontGetMessageWidth(const char *text);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES(seq) (probe[2 + (seq)])
#define WIDTH_EARLY (probe[8])
#define WIDTH_LATE (probe[9])
#define MEASURES (probe[10])

/*
    Must match what `bleck` generates from this mod's name, so the width being
    measured is the width the banner actually asks for.
*/
static const char sample[] = "mod_loaded: banner-probe";

/* Non-zero so this lands in .data, not .bss -- the loader's bss handling is
   undocumented and depending on it would be a hazard that only sometimes bites. */
static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void onSequenceFrame(u32 seq, void *work)
{
    FRAMES(seq) += 1;

    if (seq == SEQ_GAME)
    {
        if (FRAMES(seq) == 1)
        {
            WIDTH_EARLY = FontGetMessageWidth(sample);
            MEASURES += 1;
        }
        else if (FRAMES(seq) == LATE_FRAME)
        {
            WIDTH_LATE = FontGetMessageWidth(sample);
            MEASURES += 1;
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

/*
    Runs after the generated `_prolog` has installed its own hooks, so these
    wrap them: our counter runs, then the banner draws, then the game's real
    sequence main. Both layers are exercised.
*/
void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 16; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
    probe[1] = 1;
}
