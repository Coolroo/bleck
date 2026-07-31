/*
    Read the effect system's work struct out of a running game.

    D197 found the effdata loader inside `effSubMain` (0x8005BF08) and saw it
    store the loaded file's pointer at +12 of a global reached as `r13-30492`.
    The symbol list names `effsub_wp` at 0x805AE7E4, and 0x805AE7E4 + 30492 is
    0x805B5F00 -- a clean small-data base, which is what says they are the same
    global.

    ⚠️ This probe is the check for that, not an assumption of it. If +0x0C
    really is the loaded `effdata.dat`, the words there begin with the sixteen
    section offsets -- 0x40, 0x1860, 0x4F60 ... -- and `EFDT` at 0x40. Those are
    values measured from the file on disc (D190), so nothing here can produce
    them by accident.

    ⛔ Reads only. Ten sections of that file are undecoded and this is trying to
    find out what parses them; writing anything would be guessing with the
    game's own memory.
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

/* Named in spm.eu0.lst. The pointer the loader writes through. */
#define EFFSUB_WP 0x805AE7E4
#define EFFDRV_WP 0x805ADF90

/* Measured from the file on disc (D190): what a loaded effdata.dat starts with. */
#define SECTION0_OFFSET 0x40
#define EFDT_MAGIC 0x45464454u

#define PROBE 0x80005000
#define MAGIC 0xEFDA7A00u

#define WORDS_OF_WORK 24
#define WORDS_OF_FILE 20

#define SEQ_COUNT 6
#define SEQ_GAME 2

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES (probe[1])
#define WP_VALUE (probe[2])
#define FILE_PTR (probe[3])
#define LOOKS_RIGHT (probe[4])
#define WORK_AT 8
#define FILE_AT (WORK_AT + WORDS_OF_WORK)

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 done = 0;

static void capture(void)
{
    u8 *work = *(u8 **) EFFSUB_WP;
    u8 *file;
    u32 i;

    WP_VALUE = (u32) work;
    if (work == 0)
        return;

    for (i = 0; i < WORDS_OF_WORK; i++)
        probe[WORK_AT + i] = *(u32 *) (work + i * 4);

    /* +0x0C is where the loader stored what it read (D197). */
    file = *(u8 **) (work + 0x0C);
    FILE_PTR = (u32) file;
    if (file == 0)
        return;

    for (i = 0; i < WORDS_OF_FILE; i++)
        probe[FILE_AT + i] = *(u32 *) (file + i * 4);

    /* The whole point: does it look like the file measured on disc? Two
       independent marks, so one coincidence is not enough. */
    LOOKS_RIGHT = 0;
    if (*(u32 *) file == SECTION0_OFFSET)
        LOOKS_RIGHT |= 1;
    if (*(u32 *) (file + SECTION0_OFFSET) == EFDT_MAGIC)
        LOOKS_RIGHT |= 2;

    done = 1;
}

static void watch(void *arg)
{
    FRAMES += 1;
    if (!done)
        capture();
    if (realMain[SEQ_GAME] != (SeqFunc *) 1 && realMain[SEQ_GAME] != 0)
        realMain[SEQ_GAME](arg);
}

void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 32; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    probe[5] = EFFSUB_WP;
    probe[6] = *(u32 *) EFFDRV_WP;

    realMain[SEQ_GAME] = seq_data[SEQ_GAME].main;
    seq_data[SEQ_GAME].main = watch;
}
