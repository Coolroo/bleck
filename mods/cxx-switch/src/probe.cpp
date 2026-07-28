/*
    C++ in-game, in a build that does not freeze.

    The earlier C++ runs read correct values and then the game stopped -- but
    the bisection found the freeze was a `script main` that RETURNS, not C++ at
    all. Those readings were taken at `mod_prolog`, before the script starts, so
    they were never wrong; they were just taken in a build that died afterwards,
    which is not a state to record a capability from.

    So this is the same measurement with the script's `main` looping forever.

    A global with a constructor lands in .bss, which the loader leaves zero, so
    0 and the marker are different answers rather than two ways of reporting
    nothing. The virtual call is the second half: a REL's relocations are where
    C++ is most likely to be silently wrong, and a vtable pointer is one.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'CXXS'
      +0x04 ( 1)  the constructed field. 0x0C70FA11 if the ctor ran, 0 if not
      +0x08 ( 2)  a virtual call's result -- 0x1234 if the vtable relocated
      +0x0C ( 3)  constructors that ran, counted by the ctor itself
      +0x10 ( 4)  SEQ_GAME frames -- must CLIMB, or the game froze again
*/

typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x43585853U

#define SEQ_COUNT 6
#define SEQ_GAME 2

extern "C"
{
    typedef void(SeqFunc)(void *);

    struct SeqDef
    {
        SeqFunc *init;
        SeqFunc *main;
        SeqFunc *exit;
    };

    extern SeqDef seq_data[];
}

static volatile u32 *const probe = (volatile u32 *) PROBE;

static u32 ctorsRan;

struct Marker
{
    u32 value;
    virtual u32 tag() const { return 0x1234U; }
    Marker();
};

Marker::Marker()
{
    value = 0x0C70FA11U;
    ctorsRan += 1;
}

static Marker marker;

static SeqFunc *realMain[SEQ_COUNT];

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        probe[4] += 1;
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

extern "C" void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 5; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    probe[1] = marker.value;
    probe[2] = marker.tag();
    probe[3] = ctorsRan;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
