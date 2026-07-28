/*
    Does `mode` actually decide which side of the original the mod runs on?

    A hook that installs and a handler that counts prove neither half of what
    `before` and `after` claim. Both would read identically if bleck emitted the
    same wrapper for each, or if the original were never called at all -- which
    is exactly what `replace` does, and what a broken interception degrades to.

    So this probe is built around one question: CAN IT TELL THE TWO APART?

    HOW ORDER IS OBSERVED. The wrapper calls `bleck_trace_result` when the
    original returns. So at the moment a handler runs:

      before  the original has not been called yet, so `lastResult` still holds
              the PREVIOUS call's value -- 0 on the very first entry;
      after   the original has just returned, so `lastResult` holds ITS result.

    Each handler records `lastResult` as it found it on its first entry.
    `beforeSaw` must be 0 and `afterSaw` must not be, and no arrangement of a
    broken wrapper produces that pair by accident: emitting `before` for both
    gives two zeroes, emitting `after` for both gives two non-zeroes, and never
    calling the original gives two zeroes and a dead game.

    WHY THESE TWO FUNCTIONS. Each is load-bearing, so "the original still runs"
    is not something the report has to be trusted about:

      mapDataPtr       the game cannot load a map without it. Its argument is a
                       map name, so a correct capture spells readable text and a
                       corrupted one does not.
      GetBasicPlayer   called constantly, and returns arg0 + 0xD8 (D96) -- a
                       result this probe can check arithmetically rather than
                       merely record. It is also reliably NON-ZERO, which is
                       what makes it usable as the `after` side.

    ⚠️ The check that matters most is not in this block at all: if interception
    were broken, mapDataPtr would return garbage and the attract demo would not
    reach aa4_01 and ls4_12. A run that never reaches gameplay says nothing
    about ordering no matter what these words hold.

    Report block, big-endian u32:

      +0x00 ( 0)  magic 'ICPT'
      +0x04 ( 1)  bleck_hook_count -- 2
      +0x08 ( 2)  bleck_hook_status[0]  1 pending 2 installed 3 refused
      +0x0C ( 3)  bleck_hook_status[1]
      +0x10 ( 4)  beforeCalls  -- entries into the mapDataPtr handler
      +0x14 ( 5)  afterCalls   -- entries into the GetBasicPlayer handler
      +0x18 ( 6)  beforeSaw    -- traces[0].lastResult at first entry. MUST be 0
      +0x1C ( 7)  afterSaw     -- traces[1].lastResult at first entry. MUST NOT
      +0x20 ( 8)  afterSawArg  -- the argument that produced afterSaw
      +0x24 ( 9)  offsetOk     -- afterSaw - afterSawArg, expected 0xD8 (D96)
      +0x28 (10)  traces[0].calls
      +0x2C (11)  traces[0].depth   -- must be 0 at rest
      +0x30 (12)  traces[0].blind   -- must be 0; non-zero means no guard word
      +0x34 (13)  traces[0].nested
      +0x38 (14)  traces[1].calls
      +0x3C (15)  traces[1].depth
      +0x40 (16)  traces[1].blind
      +0x44 (17)  first map name, bytes 0..3
      +0x48 (18)  first map name, bytes 4..7
      +0x4C (19)  first map name, bytes 8..11
      +0x50 (20)  most recent map name, bytes 0..3
      +0x54 (21)  most recent map name, bytes 4..7
      +0x58 (22)  most recent map name, bytes 8..11
      +0x5C (23)  traces[0].lastResult -- a MapData *, at rest
      +0x60 (24)  SEQ_GAME frames -- the health check. Zero invalidates the run

    A map change needs no counter: the first and last names are captured
    separately, so `aa4_01` in one and `ls4_12` in the other IS the map change,
    and is readable rather than merely counted.

    Run with:  scripts/ingame.py intercept-probe --words 28 --seconds 120
    No --map: the attract demo's own aa4_01 -> ls4_12 is the health check.
    Target: eu0. Nothing here writes to game memory.
*/

typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x49435054U /* 'ICPT' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define NAME_WORDS 3

/* Repeated from the generated runtime, exactly as probes repeat SeqDef. */
#define BLECK_TRACE_ARGS 4

typedef struct
{
    u32 magic;
    u32 calls;
    u32 nested;
    u32 blind;
    u32 depth;
    u32 first[BLECK_TRACE_ARGS];
    u32 last[BLECK_TRACE_ARGS];
    u32 firstResult;
    u32 lastResult;
} BleckTrace;

extern BleckTrace bleck_traces[];
extern u32 bleck_hook_status[];
extern const u32 bleck_hook_count;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define HOOK_COUNT (probe[1])
#define STATUS(i) (probe[2 + (i)])
#define BEFORE_CALLS (probe[4])
#define AFTER_CALLS (probe[5])
#define BEFORE_SAW (probe[6])
#define AFTER_SAW (probe[7])
#define AFTER_SAW_ARG (probe[8])
#define OFFSET_OK (probe[9])
#define T0(f) (probe[10 + (f)])
#define T1(f) (probe[14 + (f)])
#define FIRST_NAME(i) (probe[17 + (i)])
#define LAST_NAME(i) (probe[20 + (i)])
#define LAST_RESULT (probe[23])
#define GAME_FRAMES (probe[24])

static SeqFunc *realMain[SEQ_COUNT];

/* Copied, not pointed at: an address proves nothing about what it points to,
   and a map name is only evidence if the bytes are readable as text. */
static void copyName(const char *name, volatile u32 *out)
{
    const u8 *bytes = (const u8 *) name;
    u32 i;

    for (i = 0; i < NAME_WORDS; i++)
        out[i] = 0;
    if (name == 0)
        return;
    for (i = 0; i < NAME_WORDS * 4; i++)
    {
        if (bytes[i] == 0)
            break;
        out[i / 4] |= ((u32) bytes[i]) << (24 - 8 * (i % 4));
    }
}

/*
    `before`: this runs FIRST, and the original has not been called yet.

    The signature has to match what mapDataPtr takes. The wrapper preserves
    every argument register around this call, so the original still receives
    what the caller passed -- but a handler declaring the wrong prototype
    still reads the wrong thing here.
*/
void beforeMapDataPtr(const char *name)
{
    if (BEFORE_CALLS == 0)
    {
        /* The order evidence. Read before anything else touches the record. */
        BEFORE_SAW = bleck_traces[0].lastResult;
        copyName(name, &probe[17]);
    }
    copyName(name, &probe[20]);
    BEFORE_CALLS += 1;
}

/*
    `after`: this runs LAST, and the original has already returned.

    Its return value is discarded either way -- the caller receives the
    ORIGINAL's result, so a handler cannot change what the game sees.
*/
void afterGetBasicPlayer(u32 arg0)
{
    if (AFTER_CALLS == 0)
    {
        AFTER_SAW = bleck_traces[1].lastResult;
        AFTER_SAW_ARG = arg0;
        OFFSET_OK = bleck_traces[1].lastResult - arg0;
    }
    AFTER_CALLS += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;

    HOOK_COUNT = bleck_hook_count;
    STATUS(0) = bleck_hook_status[0];
    STATUS(1) = bleck_hook_status[1];

    T0(0) = bleck_traces[0].calls;
    T0(1) = bleck_traces[0].depth;
    T0(2) = bleck_traces[0].blind;
    T0(3) = bleck_traces[0].nested;
    T1(0) = bleck_traces[1].calls;
    T1(1) = bleck_traces[1].depth;
    T1(2) = bleck_traces[1].blind;
    LAST_RESULT = bleck_traces[0].lastResult;

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

    for (i = 0; i < 25; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
