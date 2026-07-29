/*
    Are NPC behaviour scripts reachable as STATIC data?

    D107 read four script pointers off a live NPCEntry in he1_01 and stopped
    there, concluding npcdrv: could not be a build-time patch because the
    pointers are copied in at spawn. That may be the wrong conclusion: the
    setup enemy record carries no script references at all -- 112 bytes of
    position, a template id and two numbers -- and `NPCTribe` has no script
    fields either. So they come from somewhere else, and `npcEnemyTemplates`
    (0x80449888) is a table in DOL data.

    THE METHOD. Rather than guess a struct layout for a type that is in no
    header, search the table for the four addresses D107 already measured:

      0x8043B8F8  templateinitScript
      0x804938E8  templatemoveScript
      0x80494E28  templateonHitScript
      0x80439F10  templatedeathScript

    Finding them gives the offsets AND confirms the table in one step -- and a
    hit cannot be coincidence, because these are four specific words measured in
    a different run by a different probe.

    ⚠️ Read at `mod_prolog`, deliberately. The whole question is whether this is
    available BEFORE anything spawns. D107's values were read during gameplay in
    a specific map; if the same words are here at load time, they are static and
    a declaration can reach them.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'NTPL'
      +0x04 ( 1)  &npcEnemyTemplates
      +0x08 ( 2)  byte offset of the init script pointer, or -1
      +0x0C ( 3)  ... move
      +0x10 ( 4)  ... onHit
      +0x14 ( 5)  ... death
      +0x18 ( 6)  words scanned
      +0x1C ( 7)  the table's first word, so "found nothing" can be told from
                  "read nothing"
      +0x20 ( 8)  SEQ_GAME frames. The control

    Target: eu0. Nothing here writes to game memory.
*/

typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4E54504CU /* 'NTPL' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define WANTED 4
#define SCAN_WORDS 0x4000

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern u32 npcEnemyTemplates[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define BASE (probe[1])
#define FOUND(i) (probe[2 + (i)])
#define SCANNED (probe[6])
#define FIRST_WORD (probe[7])
#define GAME_FRAMES (probe[8])

/* Measured in he1_01 by mods/npc-probe (D107). */
static const u32 wanted[WANTED] = {
    0x8043B8F8U, 0x804938E8U, 0x80494E28U, 0x80439F10U,
};

static SeqFunc *realMain[SEQ_COUNT];

static void onSequenceFrame(u32 seq, void *work)
{
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
    u32 *table = npcEnemyTemplates;
    u32 i;
    u32 w;

    for (i = 0; i < 9; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    for (i = 0; i < WANTED; i++)
        FOUND(i) = 0xFFFFFFFFU;

    BASE = (u32) table;
    FIRST_WORD = table[0];

    for (i = 0; i < SCAN_WORDS; i++)
    {
        for (w = 0; w < WANTED; w++)
            if (table[i] == wanted[w] && FOUND(w) == 0xFFFFFFFFU)
                FOUND(w) = i * 4;
    }
    SCANNED = SCAN_WORDS;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
