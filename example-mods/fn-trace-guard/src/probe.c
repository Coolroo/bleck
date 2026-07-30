/*
    The negative for the self-healing detour, and a second table row.

    Two hooks on the SAME function, so the derived guard fails without anything
    bleck generated being edited: hook 0 installs and writes the branch, and
    hook 1 then reads that branch where it expected `mapDataPtr`'s prologue.
    Same construction as `fn-hook-guard` (D95), asking a different question --
    not "does the guard refuse" but "does a refused hook's TRACE record stay
    empty, while the traced hook beside it keeps working".

    What must be true if the trace is honest:

      * hook 1 is refused, and `traceNever` is never entered, so trace 1 stays
        all zeros -- `calls`, `blind` and `nested` alike;
      * hook 0 keeps counting and the game keeps loading maps;
      * `depth` is 0 at rest for both, and the word at `mapDataPtr` is the
        branch to `traceMapDataPtr` -- not to `traceNever`, which is what makes
        "refused" and "wrote something harmless" distinguishable rather than
        assumed apart.

    ⚠️ This build also materialises the hook table. With one hook GCC folds the
    row into constants (D95); with two it must index `bleck_function_hooks`, so
    the trace helpers are exercised against a real array here and not only
    against constant-folded copies of one.

    Report block, big-endian u32:

      +0x00 ( 0)  magic 'FTRG'
      +0x04 ( 1)  bleck_hook_count, expected 2
      +0x08 ( 2)  bleck_hook_status[0], expected 2 installed
      +0x0C ( 3)  bleck_hook_status[1], expected 3 refused
      +0x10 ( 4)  trace 0: calls
      +0x14 ( 5)  trace 0: blind
      +0x18 ( 6)  trace 0: depth
      +0x1C ( 7)  trace 1: calls, expected 0
      +0x20 ( 8)  trace 1: blind, expected 0
      +0x24 ( 9)  trace 1: nested, expected 0
      +0x28 (10)  trace 0: most recent argument 0
      +0x2C (11)  trace 0: most recent result
      +0x30 (12)  most recent name, bytes 0..3
      +0x34 (13)  most recent name, bytes 4..7
      +0x38 (14)  most recent name, bytes 8..11
      +0x3C (15)  first instruction of mapDataPtr, read back per frame
      +0x40 (16)  &traceMapDataPtr
      +0x44 (17)  &traceNever
      +0x48 (18)  bleck_hook_original(0)
      +0x4C (19)  bleck_hook_original(1)
      +0x50 (20)  SEQ_GAME frames
      +0x54 (21)  map changes seen
      +0x58 (22)  sentinel

    Run with:  scripts/ingame.py fn-trace-guard --words 24 --seconds 60
    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x46545247U /* 'FTRG' */
#define SENTINEL 0xB1ECB1ECU
#define REPORT_WORDS 23

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SEQ_MAPCHANGE 3

#define TRACE 0
#define TRACE_NEVER 1

#define NAME_BYTES 12
#define NAME_WORDS 3
#define TRACE_ARGS 4

#define RAM_LOW 0x80000000U
#define RAM_HIGH 0x94000000U

extern u32 bleck_hook_status[];
extern const u32 bleck_hook_count;

/* See runtime_c.TRACE_BLOCK; repeated here as probes repeat SeqDef. */
typedef struct
{
    u32 magic;
    u32 calls;
    u32 nested;
    u32 blind;
    u32 depth;
    u32 first[TRACE_ARGS];
    u32 last[TRACE_ARGS];
    u32 firstResult;
    u32 lastResult;
} BleckTrace;

extern BleckTrace bleck_traces[];
extern void bleck_trace_args(u32 index, u32 a0, u32 a1, u32 a2, u32 a3);
extern u32 bleck_trace_open(u32 index);
extern void bleck_trace_close(u32 index);
extern void bleck_trace_result(u32 index, u32 value);
extern u32 bleck_hook_original(u32 index);

extern void *mapDataPtr(const char *mapName);

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

void *traceMapDataPtr(const char *mapName)
{
    void *result = 0;

    bleck_trace_args(TRACE, (u32) mapName, 0, 0, 0);
    if (bleck_trace_open(TRACE))
    {
        result = mapDataPtr(mapName);
        bleck_trace_close(TRACE);
    }
    bleck_trace_result(TRACE, (u32) result);
    return result;
}

/*
    Hook 1's handler. Nothing should ever reach it: its hook is refused, so no
    branch to it is ever written.

    It is written as a real trace rather than a stub so that "refused" is the
    only reason trace 1 stays empty. `bleck_trace_open(1)` would itself refuse,
    because hook 1's status is not INSTALLED -- but that guard is second in
    line, and it would show up as `blind` rather than as silence.
*/
void *traceNever(const char *mapName)
{
    void *result = 0;

    bleck_trace_args(TRACE_NEVER, (u32) mapName, 0, 0, 0);
    if (bleck_trace_open(TRACE_NEVER))
    {
        result = mapDataPtr(mapName);
        bleck_trace_close(TRACE_NEVER);
    }
    bleck_trace_result(TRACE_NEVER, (u32) result);
    return result;
}

static void copyName(u32 at, u32 pointer)
{
    const u8 *text = (const u8 *) pointer;
    u32 word = 0;
    u32 i, byte;
    u32 done = 0;

    if (pointer < RAM_LOW || pointer >= RAM_HIGH || (pointer & 3) != 0)
    {
        for (i = 0; i < NAME_WORDS; i++)
            probe[at + i] = 0;
        return;
    }
    for (i = 0; i < NAME_BYTES; i++)
    {
        byte = done ? 0 : text[i];
        if (byte == 0)
            done = 1;
        word = (word << 8) | byte;
        if ((i & 3) == 3)
        {
            probe[at + (i >> 2)] = word;
            word = 0;
        }
    }
}

static u32 lastSeq = 0xFFFFFFFFU;

static void refreshReport(void)
{
    probe[4] = bleck_traces[TRACE].calls;
    probe[5] = bleck_traces[TRACE].blind;
    probe[6] = bleck_traces[TRACE].depth;
    probe[7] = bleck_traces[TRACE_NEVER].calls;
    probe[8] = bleck_traces[TRACE_NEVER].blind;
    probe[9] = bleck_traces[TRACE_NEVER].nested;
    probe[10] = bleck_traces[TRACE].last[0];
    probe[11] = bleck_traces[TRACE].lastResult;
    copyName(12, bleck_traces[TRACE].last[0]);
    probe[15] = *(volatile u32 *) mapDataPtr;
    probe[22] = SENTINEL;
}

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        probe[20] += 1;
    if (seq == SEQ_MAPCHANGE && lastSeq != SEQ_MAPCHANGE)
        probe[21] += 1;
    lastSeq = seq;
    refreshReport();

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
    probe[1] = bleck_hook_count;
    probe[2] = bleck_hook_status[TRACE];
    probe[3] = bleck_hook_status[TRACE_NEVER];
    probe[16] = (u32) traceMapDataPtr;
    probe[17] = (u32) traceNever;
    probe[18] = bleck_hook_original(TRACE);
    probe[19] = bleck_hook_original(TRACE_NEVER);

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
