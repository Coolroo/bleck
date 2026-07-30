/*
    Using the trace to learn something: functions spm-headers does not describe,
    watched while the attract demo runs.

    None of the first three appear in any header under
    `work/upstream/spm-headers`. Hooks 0 and 1 are listed in `spm.eu0.lst` under
    a literal comment of `// somewhere` -- the decomp knows an address and
    nothing else.

      hook 0  func_800b426c    0x800B426C  prologue 9421FFA0
      hook 1  func_800cd554    0x800CD554  first word 4BFF480C -- a BRANCH
      hook 2  GetBasicPlayer   0x8030AFC0  first word 386300D8, under
                                           `// nw4r::snd.cpp`
      hook 3  effMain          0x800618B0  the control

    ⚠️ THE CONTROL IS THE POINT. An earlier build of this probe used
    `marioCheckStatusPauseMot` as its control and every one of its four counters
    read zero, which said nothing at all: a rig that cannot see a call happening
    cannot report that one did not. `effMain` replaces it because D94 already
    measured it at 104,419 entries in 90 s, so a zero there is a broken trace
    and nothing else. Only while hook 3 is climbing does a zero elsewhere mean
    "not called".

    ⚠️ effMain IS ALSO THE DEMONSTRATION. D94 recorded ⛔ do not stub `effMain`:
    replacing it wedged the game in SEQ_MAPCHANGE for 90 s. A trace calls the
    original, so the same function that could not be replaced can be watched.

    ⚠️ hook 1 is worth reading twice. `func_800cd554`'s first word is
    `4BFF480C` = `b 0x800C1D60` = `effSmallStarEntry`, so it is a tail branch
    rather than a prologue. That is exactly the instruction D37 says a blind
    trampoline copies and breaks on -- PC-relative, meaningless once moved. The
    self-healing detour copies nothing: it restores the word where it belongs,
    so a branch-first function traces like any other.

    ⚠️ THE SIGNATURES ARE UNKNOWN, which is the hazard. Each handler is declared
    with eight `u32` parameters and forwards all eight, because the PowerPC EABI
    puts the first eight integer or pointer arguments in r3-r10: forwarding
    those registers is correct for any function taking eight or fewer of them,
    whatever it actually declares.

    What that does NOT cover, and what would corrupt rather than mis-record:

      * more than eight integer arguments -- the rest are on the caller's stack,
        and the handler builds its own frame before forwarding;
      * a variadic function -- the EABI uses CR bit 6 to say whether float
        arguments were passed, and a non-variadic handler clears it;
      * a float or struct return, which does not come back in r3.

    Float *arguments* survive by construction rather than by care: f1-f8 are
    argument registers assigned independently of r3-r10, and a handler holding
    no floating-point code never writes them. They are still not recorded.

    Only the first two arguments reach the report. Eight are forwarded.

    Report block, big-endian u32:

      +0x00 ( 0)  magic 'FTRS'
      +0x04 ( 1)  bleck_hook_count
      +0x08 ( 2)  SEQ_GAME frames
      +0x0C ( 3)  map changes seen
      +0x10 ( 4)  bleck_hook_status[0]   1 pending 2 installed 3 refused
      +0x14 ( 5)  bleck_hook_status[1]
      +0x18 ( 6)  bleck_hook_status[2]
      +0x1C ( 7)  bleck_hook_status[3]

      then twelve words per trace: hook 0 at word 8, 1 at 20, 2 at 32, 3 at 44

        +0  calls        +1  nested       +2  blind        +3  depth
        +4  first arg 0  +5  first arg 1  +6  last arg 0   +7  last arg 1
        +8  first result +9  last result
        +10 ticks in open + close, summed   +11 ticks in the original, summed

      +0xE0 (56)  first instruction of func_800b426c, read back per frame
      +0xE4 (57)  first instruction of func_800cd554
      +0xE8 (58)  first instruction of GetBasicPlayer
      +0xEC (59)  first instruction of effMain
      +0xF0 (60)  sentinel, rewritten every frame

    Run with:  scripts/ingame.py fn-trace-somewhere --words 62 --seconds 110
    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x46545253U /* 'FTRS' */
#define SENTINEL 0xB1ECB1ECU
#define REPORT_WORDS 61

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SEQ_MAPCHANGE 3

#define HOOKS 4
#define TRACE_ARGS 4

/* Where each trace's twelve words start. */
#define RECORD_BASE 8
#define RECORD_WORDS 12

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

/*
    The targets, declared with the widest signature the EABI passes in
    registers. Bound by elf2rel against the symbol list; no address appears
    here, so a wrong name fails the build rather than branching into unrelated
    code.
*/
typedef u32(Unknown)(u32, u32, u32, u32, u32, u32, u32, u32);

extern Unknown func_800b426c;
extern Unknown func_800cd554;
extern Unknown GetBasicPlayer;
extern Unknown effMain;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

/*
    The 750's time base, read directly -- no OS symbol is needed and none is
    trusted.

    ⚠️ Under Dolphin this advances by the emulator's own cycle accounting, so
    what it measures is a Dolphin cost, not a Wii one.
*/
static u32 ticks(void)
{
    u32 value;

    __asm__ __volatile__("mftb %0" : "=r"(value));
    return value;
}

/* Both start at 1 so they land in .data; 1 is subtracted when reported. */
static u32 patchTicks[HOOKS] = {1, 1, 1, 1};
static u32 bodyTicks[HOOKS] = {1, 1, 1, 1};

/*
    One handler body, four times over. Written through a macro because the four
    differ only in which row they use, and expanded rather than shared through a
    function pointer so each `bl` is a direct call to a named symbol and the
    disassembly of each handler can be read on its own.
*/
#define TRACE_BODY(index, original)                                            \
    u32 result = 0;                                                            \
    u32 t0, t1, t2, t3;                                                        \
                                                                               \
    bleck_trace_args((index), a0, a1, a2, a3);                                 \
    t0 = ticks();                                                              \
    if (bleck_trace_open(index))                                               \
    {                                                                          \
        t1 = ticks();                                                          \
        result = (original)(a0, a1, a2, a3, a4, a5, a6, a7);                   \
        t2 = ticks();                                                          \
        bleck_trace_close(index);                                              \
        t3 = ticks();                                                          \
        patchTicks[(index)] += (t1 - t0) + (t3 - t2);                          \
        bodyTicks[(index)] += (t2 - t1);                                       \
    }                                                                          \
    bleck_trace_result((index), result);                                       \
    return result;

u32 traceA(u32 a0, u32 a1, u32 a2, u32 a3, u32 a4, u32 a5, u32 a6, u32 a7)
{
    TRACE_BODY(0, func_800b426c)
}

u32 traceB(u32 a0, u32 a1, u32 a2, u32 a3, u32 a4, u32 a5, u32 a6, u32 a7)
{
    TRACE_BODY(1, func_800cd554)
}

u32 traceC(u32 a0, u32 a1, u32 a2, u32 a3, u32 a4, u32 a5, u32 a6, u32 a7)
{
    TRACE_BODY(2, GetBasicPlayer)
}

u32 traceD(u32 a0, u32 a1, u32 a2, u32 a3, u32 a4, u32 a5, u32 a6, u32 a7)
{
    TRACE_BODY(3, effMain)
}

static u32 lastSeq = 0xFFFFFFFFU;

static void reportTrace(u32 index)
{
    const BleckTrace *trace = &bleck_traces[index];
    u32 at = RECORD_BASE + index * RECORD_WORDS;

    probe[at + 0] = trace->calls;
    probe[at + 1] = trace->nested;
    probe[at + 2] = trace->blind;
    probe[at + 3] = trace->depth;
    probe[at + 4] = trace->first[0];
    probe[at + 5] = trace->first[1];
    probe[at + 6] = trace->last[0];
    probe[at + 7] = trace->last[1];
    probe[at + 8] = trace->firstResult;
    probe[at + 9] = trace->lastResult;
    probe[at + 10] = patchTicks[index] - 1;
    probe[at + 11] = bodyTicks[index] - 1;
}

static void refreshReport(void)
{
    u32 i;

    for (i = 0; i < HOOKS; i++)
        reportTrace(i);
    /* At rest each of these is the branch. A prologue word here would say a
       detour was left open, which is the failure `depth` also reports. */
    probe[56] = *(volatile u32 *) func_800b426c;
    probe[57] = *(volatile u32 *) func_800cd554;
    probe[58] = *(volatile u32 *) GetBasicPlayer;
    probe[59] = *(volatile u32 *) effMain;
    probe[60] = SENTINEL;
}

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        probe[2] += 1;
    if (seq == SEQ_MAPCHANGE && lastSeq != SEQ_MAPCHANGE)
        probe[3] += 1;
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
    for (i = 0; i < HOOKS; i++)
        probe[4 + i] = bleck_hook_status[i];

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
