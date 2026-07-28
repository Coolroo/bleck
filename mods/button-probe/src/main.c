/*
    Settling the Wii remote button masks by reading them out of the game.

    `bleck/common/config.py` carries a table of button names to masks. Those
    values are the published Revolution SDK ones and **nothing in the game or
    in spm-headers confirms them** -- `wii/kpad.h` documents the `buttonsHeld`
    field and stops there. D65 is a recent and expensive reminder of what
    happens when a plausible value is treated as a known one.

    This answers it directly: read the controller every frame, record every
    distinct value seen, and let a human press one button at a time.

    ⚠️ This is NOT the thing D48 ruled out. D48 says input cannot be *injected*
    into Dolphin from outside, which is about automating a test. The game reads
    its own controller every frame and so can a mod. Conflating the two closed
    off this whole area for several sessions.

    How the reading works, all from spm-headers:

      wpadGetWork()             spm/wpadmgr.h -- returns WpadWork *
      WpadWork.statuses         +0x006C, [controller][age], latest age is 0
      KPADStatus                wii/kpad.h -- 0x84 bytes
      KPADStatus.buttonsHeld    +0x00

    so controller 0's current buttons are at `work + 0x6C`.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'WPAD'    -- proves mod_prolog ran
      +0x04  hooks installed
      +0x08  gameplay frames -- liveness; if this stops, the game hung
      +0x0C  buttonsHeld right now
      +0x10  every bit seen so far, OR-ed together
      +0x14  how many distinct values were recorded
      +0x18  ring of the first 8 distinct non-zero values, in press order

    The ring is what identifies individual buttons: press one, release, press
    the next. Each press appends its mask. The accumulator and the ring both
    persist, so a single successful read at any point captures the whole
    session -- the reader polls every few seconds and would otherwise miss a
    press that started and ended between two polls.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

/* Unused TRK interrupt vector table, as everywhere else here. */
#define PROBE 0x80005000

#define MAGIC 0x57504144U /* 'WPAD' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* spm/wpadmgr.h: statuses[controller][age], latest age first. */
#define WPAD_STATUSES 0x6C

/* Enough to walk the face buttons and the d-pad without wrapping. */
#define RING_SLOTS 8

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

/*
    Resolved by name from the symbol list like everything else here.
    `0x8023697c` in spm.eu0.lst, so this links today.
*/
extern void *wpadGetWork(void);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES (probe[2])
#define CURRENT (probe[3])
#define SEEN (probe[4])
#define COUNT (probe[5])
#define RING(i) (probe[6 + (i)])

/* Non-zero so these land in .data, not .bss -- the loader's bss handling is
   undocumented and depending on it would be a hazard that only sometimes bites. */
static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 lastRecorded = 0xFFFFFFFFU;

static u32 buttonsHeld(void)
{
    u8 *work = (u8 *) wpadGetWork();

    /* Null before wpadInit has run. Reading through it would fault, and a
       fault here would look exactly like the feature being impossible. */
    if (work == 0)
        return 0;
    return *(volatile u32 *) (work + WPAD_STATUSES);
}

static void onSequenceFrame(u32 seq, void *work)
{
    u32 held;

    if (seq == SEQ_GAME)
    {
        FRAMES += 1;

        held = buttonsHeld();
        CURRENT = held;
        SEEN |= held;

        /*
            Record a value only when it changes, so holding a button for a
            second does not fill the ring with sixty copies of itself. A
            release reads 0 and is skipped, which is what separates one press
            from the next.
        */
        if (held != 0 && held != lastRecorded)
        {
            lastRecorded = held;
            if (COUNT < RING_SLOTS)
                RING(COUNT) = held;
            COUNT += 1;
        }
        else if (held == 0)
        {
            lastRecorded = 0;
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
    wrap them rather than replacing them.
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
