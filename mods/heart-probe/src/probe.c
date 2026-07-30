/*
    What is the Pure Heart, in the game's own terms?

    `mac_12` (Flipside) is where one actually exists -- the REL bundle holds
    `heart_01`, `A2_heart_01`, `A3_heart_iwa` and `pure_heart` right beside
    `mac_12_init_evt`. The model itself lives inside that map's `map.dat`, which
    is not decoded, so it cannot be read off the disc.

    So this asks the running game instead. For each candidate instance name it
    calls `mobjNameToPtrNoAssert` and, when something answers, copies the
    MODEL name back out with `mobjGetModelName`.

    ⚠️ `NoAssert` deliberately: `mobjNameToPtr` asserts on a miss, and a probe
    whose job is to try names must not halt on the first wrong one.
*/

typedef unsigned char u8;
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
extern void *mobjNameToPtrNoAssert(const char *instanceName);
extern const char *mobjGetModelName(void *mobj);

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define LOOK_AT_FRAME 300

#define PROBE 0x80005000
#define MAGIC 0x9EA27EEDu
#define REPORT_WORDS 48

static volatile u32 *const probe = (volatile u32 *) PROBE;
#define GAME_FRAMES (probe[1])
#define TRIED (probe[2])
#define FOUND (probe[3])

/* Candidates, from the strings sitting next to mac_12_init_evt. */
static const char *const NAMES[] = {
    "heart_01", "A2_heart_01", "A3_heart_iwa", "A2_heart_01a", "before_iwa",
};
#define NAME_COUNT 5

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};
static u32 done = 0;

static void copyText(u32 at, const char *text, u32 words)
{
    u32 i, j, word;

    for (i = 0; i < words; i++)
    {
        word = 0;
        for (j = 0; j < 4; j++)
            word = (word << 8) | (text ? (unsigned char) text[i * 4 + j] : 0);
        probe[at + i] = word;
    }
}

static void look(void)
{
    u32 i;
    u32 slot = 8;

    for (i = 0; i < NAME_COUNT; i++)
    {
        void *mobj = mobjNameToPtrNoAssert(NAMES[i]);

        TRIED += 1;
        if (mobj == 0)
            continue;
        FOUND += 1;
        /* 4 words of instance name, then 4 of model name, per hit. */
        copyText(slot, NAMES[i], 4);
        copyText(slot + 4, mobjGetModelName(mobj), 4);
        slot += 8;
        if (slot > REPORT_WORDS - 8)
            break;
    }
    done = 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (GAME_FRAMES == LOOK_AT_FRAME && done == 0)
            look();
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
