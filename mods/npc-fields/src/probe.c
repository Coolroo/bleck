/*
    Do a setup entry's undocumented fields matter?

    D122 added two Goombas to he1_01 and both spawned -- one built from the
    zeroed slot with only `template` and `position` written, one a byte-copy of
    slot 0 with the same two fields overwritten. Spawning was never the open
    question. This is:

    Every *shipped* slot in this map carries three values a bare slot does not:

        entry +0x14  0x000000DC  (220)
        entry +0x18  0x0000012C  (300)
        entry +0x68  0x00000002

    ⚠️ spm-headers does NOT name any of them. `SetupEnemyV6` is pos, `type`, then
    `MiscSetupDataV6`; +0x14 and +0x18 fall inside `unknown_0x4[]` and +0x68
    inside `unknown_0x50[]`. So there is nothing to look up, and D102 is the
    standing reminder that looking it up would not settle it anyway.

    220 and 300 have the shape of distances or timers, so the fear is a Goomba
    that spawns and then never notices Mario -- which is invisible to an NPC
    count, and would have looked like success in D122.

    THE COMPARISON, and why three and not two:

        slot 0  shipped with the game        the reference
        slot 4  a byte-copy of slot 0        should differ from it only in the
                                             things that are meant to differ
        slot 3  bare: template + position    differs in those, PLUS anywhere the
                                             three unknown fields reach

    ⚠️ Two entries would not do. slot 3 against slot 0 alone cannot separate
    "the unknown fields matter" from "any two NPCs differ at runtime" -- they sit
    at different coordinates and hold live animation state. slot 4 is the
    control that measures that baseline noise, and only what slot 3 has *beyond*
    it is evidence.

    LATCHED ON THE FIRST FRAME ALL THREE EXIST, because an NPCEntry changes
    every frame. All three spawn together and are therefore the same age.

    Report block at PROBE, big-endian u32:

      +0x000 (  0)  magic 'NPCX'
      +0x004 (  1)  SEQ_GAME frames. The control: zero invalidates the run
      +0x008 (  2)  frame the comparison was latched on, 0 if never
      +0x00C (  3)  live NPC count when it was
      +0x010 (  4)  found bitmask: 1 slot0, 2 slot3, 4 slot4. MUST be 7
      +0x014 (  5)  entry pointer, slot 0
      +0x018 (  6)  entry pointer, slot 3
      +0x01C (  7)  entry pointer, slot 4
      +0x020 (  8)  words differing, slot 3 vs slot 0
      +0x024 (  9)  words differing, slot 4 vs slot 0   -- the noise floor
      +0x028 ( 10) .. ( 81)  slot3-vs-slot0: 24 x (word offset, slot3, slot0)
      +0x0E8 ( 82) .. (153)  slot4-vs-slot0: 24 x (word offset, slot4, slot0)

    Read all 154 words.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4E504358U /* 'NPCX' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* npcdrv_wp -> NPCWork: num at +0x04, entries at +0x08 (scripts/ingame.py). */
#define NPC_WORK_NUM 0x04
#define NPC_WORK_ENTRIES 0x08

/* NPCEntry: setupFileIndex at +0x04, 1-based, 0 when not from a setup file. */
#define NPC_ENTRY_SIZE 0x748
#define NPC_SETUP_INDEX 0x04
#define ENTRY_WORDS (NPC_ENTRY_SIZE / 4)

/* Setup slots, as the manifest numbers them. The probe wants 1-based. */
#define SLOT_SHIPPED 0
#define SLOT_BARE 3
#define SLOT_CLONE 4

#define PAIRS 24
#define REPORT_WORDS 154

/* A garbage `num` must not turn into a million reads. */
#define SCAN_LIMIT 256

extern void *npcdrv_wp;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define LATCHED (probe[2])
#define LIVE (probe[3])
#define FOUND (probe[4])
#define PTR(i) (probe[5 + (i)])
#define DIFFS(i) (probe[8 + (i)])
#define PAIR(set, n, field) (probe[10 + (set) * (PAIRS * 3) + (n) * 3 + (field)])

static SeqFunc *realMain[SEQ_COUNT];

static u32 *entryFor(u32 slot)
{
    unsigned char *work = (unsigned char *) npcdrv_wp;
    unsigned char *entries;
    s32 count;
    s32 i;

    if (work == 0)
        return 0;
    count = *(s32 *) (work + NPC_WORK_NUM);
    entries = *(unsigned char **) (work + NPC_WORK_ENTRIES);
    if (entries == 0 || count <= 0 || count > SCAN_LIMIT)
        return 0;

    for (i = 0; i < count; i++)
    {
        unsigned char *at = entries + i * NPC_ENTRY_SIZE;

        /* setupFileIndex is 1-based; the manifest's slots are 0-based. */
        if (*(s32 *) (at + NPC_SETUP_INDEX) == (s32) slot + 1)
            return (u32 *) at;
    }
    return 0;
}

/*
    Record where two entries disagree.

    Returns the total number of differing words, which is reported separately
    from the recorded pairs: a count far above PAIRS means the first 24 are a
    sample rather than the whole answer, and reading them as complete would be
    the mistake.
*/
static u32 compare(u32 set, const u32 *a, const u32 *b)
{
    u32 total = 0;
    u32 i;

    for (i = 0; i < ENTRY_WORDS; i++)
    {
        if (a[i] == b[i])
            continue;
        if (total < PAIRS)
        {
            PAIR(set, total, 0) = i * 4;
            PAIR(set, total, 1) = a[i];
            PAIR(set, total, 2) = b[i];
        }
        total += 1;
    }
    return total;
}

static void latchOnce(void)
{
    u32 *shipped;
    u32 *bare;
    u32 *clone;
    unsigned char *work;

    if (LATCHED != 0)
        return;

    shipped = entryFor(SLOT_SHIPPED);
    bare = entryFor(SLOT_BARE);
    clone = entryFor(SLOT_CLONE);

    /* Reported every frame, so "never all three" is distinguishable from
       "found them and the comparison was empty". */
    FOUND = (shipped ? 1u : 0u) | (bare ? 2u : 0u) | (clone ? 4u : 0u);
    PTR(0) = (u32) shipped;
    PTR(1) = (u32) bare;
    PTR(2) = (u32) clone;
    if (FOUND != 7u)
        return;

    work = (unsigned char *) npcdrv_wp;
    LIVE = work ? (u32) *(s32 *) (work + NPC_WORK_NUM) : 0u;
    DIFFS(0) = compare(0, bare, shipped);
    DIFFS(1) = compare(1, clone, shipped);
    LATCHED = GAME_FRAMES;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        latchOnce();
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
