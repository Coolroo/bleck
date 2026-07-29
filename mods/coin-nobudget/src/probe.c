/*
    Can a map with NO coin budget take a coin?

    D130 found the limit: a coin needs a save flag, flags come from a per-map
    budget in `assign_tbl`, and `he1_01` (budget 4) and `he2_02` (budget 29)
    both asserted on ONE added coin because block coins had already spent theirs.

    But `assign_tbl` holds only 32 maps. **204 maps have a setup file and no
    entry at all**, and the allocator handles that differently -- it returns -1
    instead of asserting (`0x800386d8`). And the "already collected?" check
    reads -1 as "no":

        8003875c  cmpwi r3, -1
        80038760  bne   0x8003876c   ; a real id -> bit test
        80038764  li    r3, 0        ; -1 -> not collected
        80038768  blr

    PREDICTION, written before the run: the coin spawns and the map loads.

    ⚠️ If that holds it is not simply good news. A flag id of -1 has nowhere to
    record the coin being picked up, so the coin would come back on every map
    load -- present, collectable, and never permanently gone. The rig cannot see
    that; it needs a human to collect one, save, and reload.

    `an1_02` places 15 enemies. **That is the control**: if they do not spawn
    either, the run says nothing about the coin.

    Report block at PROBE, big-endian u32:

      +0x000 (  0)  magic 'ASRT'
      +0x004 (  1)  SEQ_MAPCHANGE frames -- alive check
      +0x008 (  2)  SEQ_GAME frames. Nonzero means the map finished loading
      +0x00C (  3)  how many times __assert2 was entered
      +0x010 (  4)  the line number of the FIRST one
      +0x014 (  5) .. ( 20)  file, 64 bytes, NUL padded
      +0x054 ( 21) .. ( 36)  func, 64 bytes
      +0x094 ( 37) .. ( 52)  expr, 64 bytes

    Read all 53 words.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x41535254U /* 'ASRT' */

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SEQ_MAPCHANGE 3

#define TEXT_BYTES 64
#define REPORT_WORDS 53

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define MAPCHANGE_FRAMES (probe[1])
#define GAME_FRAMES (probe[2])
#define FIRED (probe[3])
#define LINE (probe[4])

static SeqFunc *realMain[SEQ_COUNT];

/* Bounded and NUL padded. A null pointer records nothing rather than faulting
   inside the probe. */
static void copyText(u32 slot, const char *text)
{
    volatile unsigned char *out = (volatile unsigned char *) (probe + slot);
    u32 i;

    for (i = 0; i < TEXT_BYTES; i++)
        out[i] = 0;
    if (text == 0)
        return;
    for (i = 0; i < TEXT_BYTES - 1 && text[i] != 0; i++)
        out[i] = (unsigned char) text[i];
}

/*
    Runs before the real __assert2, which then halts as usual.

    ⚠️ The prototype must match the target exactly or the call is corrupted, and
    nothing can check that -- a symbol list has no signatures (D96).
*/
void on_assert(const char *file, s32 line, const char *func, const char *expr)
{
    if (FIRED == 0)
    {
        LINE = (u32) line;
        copyText(5, file);
        copyText(21, func);
        copyText(37, expr);
    }
    FIRED += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_MAPCHANGE)
        MAPCHANGE_FRAMES += 1;
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;
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

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
