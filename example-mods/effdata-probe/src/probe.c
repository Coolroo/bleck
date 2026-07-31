/*
    Find the loaded effdata.dat in memory and read its header back.

    ⚠️ **Wide on purpose.** The previous probe followed one pointer, found a
    file handle instead of a buffer, and cost a run to learn it (D198). This
    one does not follow anything: it scans for a signature that cannot occur by
    accident and reports generously around whatever it finds.

    ## What is being tested

    A RAM search found `EFDT` plus its build stamp at 0x91E66F40, and did NOT
    find the file's first sixteen bytes anywhere. In the file, `EFDT` sits at
    offset 0x40 and those sixteen bytes are the section offsets -- so if the
    buffer began at 0x91E66F00 the two searches disagree about the same memory.

    🔶 The reading: **the header is relocated at load time**, each section
    offset rewritten to an absolute pointer. That predicts header[0] equals the
    address of `EFDT` itself, which is exactly the thing to read back rather
    than assume.

    ⛔ Reads only.
*/

typedef unsigned char u8;
typedef unsigned int u32;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

#define EFDT_MAGIC 0x45464454u

/* The file's own layout (D190), for checking what is found against it. */
#define HEADER_WORDS 16
#define MAGIC_AT 0x40

/* MEM2 on the Wii. The buffer was seen here; MEM1 is swept too in case a
   different boot puts it elsewhere. */
#define MEM1_START 0x80004000u
#define MEM1_END 0x817FFFF0u
#define MEM2_START 0x90000000u
#define MEM2_END 0x93FFFFF0u

#define PROBE 0x80005000
#define MAGIC 0xEFDA7A01u

#define SEQ_COUNT 6
#define SEQ_GAME 2

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES (probe[1])
#define FOUND_AT (probe[2])
#define BASE (probe[3])
#define RELOCATED (probe[4])
#define SWEPT (probe[5])
#define HEADER_AT 8

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 done = 0;

/* The date string's first word, so a bare "EFDT" elsewhere cannot match. */
#define STAMP_WORD 0x54756520u

static u32 *scan(u32 from, u32 to)
{
    u32 at;

    for (at = from; at < to; at += 4)
    {
        if (*(u32 *) at != EFDT_MAGIC)
            continue;
        if (*(u32 *) (at + 4) != STAMP_WORD)
            continue;
        return (u32 *) at;
    }
    return 0;
}

static void capture(void)
{
    u32 *hit = scan(MEM2_START, MEM2_END);
    u32 *base;
    u32 i;

    SWEPT = 1;
    if (hit == 0)
    {
        hit = scan(MEM1_START, MEM1_END);
        SWEPT = 2;
    }
    if (hit == 0)
    {
        done = 1;
        return;
    }

    FOUND_AT = (u32) hit;
    base = (u32 *) ((u32) hit - MAGIC_AT);
    BASE = (u32) base;

    for (i = 0; i < HEADER_WORDS; i++)
        probe[HEADER_AT + i] = base[i];

    /* The prediction: every section offset became an absolute pointer, so
       header[0] is the address of the magic we just matched. */
    RELOCATED = (base[0] == (u32) hit) ? 1 : 0;
    done = 1;
}

static void watch(void *arg)
{
    FRAMES += 1;
    /* One sweep, once gameplay has had time to load the effect data. */
    if (!done && FRAMES > 600)
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

    realMain[SEQ_GAME] = seq_data[SEQ_GAME].main;
    seq_data[SEQ_GAME].main = watch;
}
