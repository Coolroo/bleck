/*
    Reports the coin count so the name probe can run unattended.

    `scripts/main.evt` signals which geometry names answered by adding distinct
    coin amounts; this copies the counter into the report block so the rig reads
    it instead of a human. MarioPouchWork.coins is at +0x01C (mario_pouch.h).

    Coins are also zeroed at the start, so the total is this run's signal and not
    whatever the loaded save happened to hold.
*/

typedef unsigned int u32;
typedef int s32;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *pouchGetPtr(void);
extern void pouchSetCoin(s32 coins);

#define POUCH_COINS 0x01C
#define SEQ_COUNT 6
#define SEQ_GAME 2

#define PROBE 0x80005000
#define MAGIC 0xF1D8EA27u
#define REPORT_WORDS 6

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define COINS (probe[2])
#define ZEROED (probe[3])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};
static u32 zeroed = 0;

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        unsigned char *pouch = (unsigned char *) pouchGetPtr();

        GAME_FRAMES += 1;
        if (pouch != 0)
        {
            /* Once, before the script's first award: the signal must be this
               run's, not the save's balance. */
            if (zeroed == 0 && GAME_FRAMES > 60)
            {
                pouchSetCoin(0);
                zeroed = 1;
                ZEROED = 1;
            }
            COINS = *(u32 *) (pouch + POUCH_COINS);
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

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
