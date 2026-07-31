/*
    Read effdata.dat's index sections out of memory, to see what the loader
    rewrote.

    D199 established that all sixteen header offsets become absolute pointers
    when the file loads. That reframes what stalled in D196: section 8's
    `offset` field is always a multiple of 32 and stops at 64,960, and three
    sections would be 86-90% filled by it -- but if that field is *also*
    relocated, the search was for something that only exists on disc.

    ## Wide on purpose

    This dumps sections 7, 8 and 10 together rather than the one that seems most
    likely. Following a single hypothesis has cost a whole run twice here (D198,
    D199), and the words are free. Whichever field turns out to matter, the
    comparison against the disc is offline and needs no second boot.

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
#define STAMP_WORD 0x54756520u
#define MAGIC_AT 0x40

#define MEM1_START 0x80004000u
#define MEM1_END 0x817FFFF0u
#define MEM2_START 0x90000000u
#define MEM2_END 0x93FFFFF0u

#define PROBE 0x80005000
#define MAGIC 0xEFDA7A02u

#define SEQ_COUNT 6
#define SEQ_GAME 2

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define FRAMES (probe[1])
#define BASE (probe[2])
#define RELOCATED (probe[3])

/* Generous and fixed, so the reader can index without guessing. */
#define HEADER_AT 4
#define HEADER_WORDS 16
#define SEC7_AT 20
#define SEC7_WORDS 9  /* 6 records of 6 bytes = 36 bytes */
#define SEC8_AT 29
#define SEC8_WORDS 16 /* 8 records of 8 bytes */
#define SEC10_AT 45
#define SEC10_WORDS 16 /* 8 pairs of 8 bytes */

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 done = 0;

static u32 *scan(u32 from, u32 to)
{
    u32 at;

    for (at = from; at < to; at += 4)
        if (*(u32 *) at == EFDT_MAGIC && *(u32 *) (at + 4) == STAMP_WORD)
            return (u32 *) at;
    return 0;
}

static void copy(u32 slot, u32 *from, u32 words)
{
    u32 i;

    for (i = 0; i < words; i++)
        probe[slot + i] = from[i];
}

static void capture(void)
{
    u32 *hit = scan(MEM2_START, MEM2_END);
    u32 *base;

    if (hit == 0)
        hit = scan(MEM1_START, MEM1_END);
    if (hit == 0)
    {
        done = 1;
        return;
    }

    base = (u32 *) ((u32) hit - MAGIC_AT);
    BASE = (u32) base;
    RELOCATED = (base[0] == (u32) hit) ? 1 : 0;

    copy(HEADER_AT, base, HEADER_WORDS);
    /* The header now holds pointers, so a section is reached directly. */
    copy(SEC7_AT, (u32 *) base[7], SEC7_WORDS);
    copy(SEC8_AT, (u32 *) base[8], SEC8_WORDS);
    copy(SEC10_AT, (u32 *) base[10], SEC10_WORDS);
    done = 1;
}

static void watch(void *arg)
{
    FRAMES += 1;
    if (!done && FRAMES > 600)
        capture();
    if (realMain[SEQ_GAME] != (SeqFunc *) 1 && realMain[SEQ_GAME] != 0)
        realMain[SEQ_GAME](arg);
}

void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 64; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    realMain[SEQ_GAME] = seq_data[SEQ_GAME].main;
    seq_data[SEQ_GAME].main = watch;
}
