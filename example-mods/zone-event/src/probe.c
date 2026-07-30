/*
    Can a script be attached to a LOADING ZONE?

    `door:` reaches `DoorDesc` only -- 35 in the whole game (D141) -- while the
    691 `MapDoorDesc` loading zones have no script fields at all. But the game
    ships `evt_door_set_event(char *door, int which, EvtScriptCode *script)`,
    and D138's disassembly showed what it does:

        800e4620  lwz r0, 876(work)    ; MapDoorDesc array, work+0x36C
        800e4618  lwz r28, 880(work)   ; count,             work+0x370
        800e462c  lwz r3, 4(entry)     ; match on name_l
        800e4674  stw r31, 884(r4)     ; work+0x374 + index*8 + which*4

    So there IS a per-zone slot array, two slots each, and the setter finds the
    zone by name. This calls it and reads the slot back.

    ⚠️ It is an **evt user func**, so it cannot be called from C directly -- it
    reads its arguments out of an `EvtEntry`. The script below is built by hand
    and handed to `evtEntry`, the same way D135's replacement was.

    ⚠️ argc counts the function pointer, so three arguments is argc 4
    (`evt_door_set_door_descs` is argc 3 for a pointer plus two, D102).

    THE CONTROL IS THE SLOT BEFORE. If the game already stores something there
    the read-back proves nothing, so both are reported.

    Report block at PROBE, big-endian u32:

      +0x000 ( 0)  magic 'ZEVT'
      +0x004 ( 1)  SEQ_GAME frames
      +0x008 ( 2)  door work pointer
      +0x00C ( 3)  zone count the game registered
      +0x010 ( 4)  slot 0 for zone 0 BEFORE the call
      +0x014 ( 5)  slot 1 for zone 0 BEFORE
      +0x018 ( 6)  our script's address
      +0x01C ( 7)  frame the setter was run
      +0x020 ( 8)  what evtEntry returned
      +0x024 ( 9)  slot 0 AFTER  -- equal to word 6 means it took
      +0x028 (10)  slot 1 AFTER
      +0x02C (11)  times our attached script actually ran
      +0x030 (12)  __assert2 count, and
      +0x034 (13)  the line of the first

    Read all 14 words.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x5A455654U /* 'ZEVT' */

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define REPORT_WORDS 14

/* r13 (0x805B5F00) - 32480, computed not eyeballed: getting this wrong froze
   the game once already (D139). */
#define DOOR_WORK 0x805AE020
#define ZONE_ARRAY 0x36C
#define ZONE_COUNT 0x370
#define ZONE_EVENTS 0x374
#define ZONE_SLOTS 2

/* `MapDoorDesc[0]` on he1_01 is `doa2_l`, the star door out to he1_02 (D138). */
#define ZONE_NAME "doa2_l"
#define ZONE_INDEX 0
#define ZONE_WHICH 0

#define EVT_USER_FUNC 0x005Cu
#define EVT_END_SCRIPT 0x0001u
#define EVT_END_EVT 0x0002u

#define FIRE_AT 600

extern void *evtEntry(const s32 *script, u32 priority, u8 flags);
extern void evt_door_set_event(void);

typedef void(SeqFunc)(void *);
typedef struct { SeqFunc *init; SeqFunc *main; SeqFunc *exit; } SeqDef;
extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define WORK (probe[2])
#define COUNT (probe[3])
#define BEFORE0 (probe[4])
#define BEFORE1 (probe[5])
#define OURS (probe[6])
#define FIRED (probe[7])
#define ENTRY (probe[8])
#define AFTER0 (probe[9])
#define AFTER1 (probe[10])
#define RAN (probe[11])
#define ASSERTS (probe[12])
#define ASSERT_LINE (probe[13])

static SeqFunc *realMain[SEQ_COUNT];

/* What we attach: one USER_FUNC into `attached`, then end. */
static s32 attached_script[4];
static s32 setter_script[7];
static const char zone_name[] = ZONE_NAME;

static s32 attached(void *entry, s32 firstCall)
{
    (void) entry;
    (void) firstCall;
    RAN += 1;
    return 2;
}

void on_assert(const char *file, s32 line, const char *func, const char *expr)
{
    (void) file; (void) func; (void) expr;
    if (ASSERTS == 0)
        ASSERT_LINE = (u32) line;
    ASSERTS += 1;
}

static u32 *slot(unsigned char *work, u32 index, u32 which)
{
    return (u32 *) (work + ZONE_EVENTS + index * (ZONE_SLOTS * 4) + which * 4);
}

static void onSequenceFrame(u32 seq, void *work_unused)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (FIRED == 0 && GAME_FRAMES > FIRE_AT)
        {
            unsigned char *work = *(unsigned char **) DOOR_WORK;

            /* Refuse an implausible pointer rather than writing through it
               (D139): a freeze reports nothing. */
            if ((u32) work < 0x80000000u || (u32) work >= 0x81800000u)
                return;

            WORK = (u32) work;
            COUNT = *(u32 *) (work + ZONE_COUNT);
            BEFORE0 = *slot(work, ZONE_INDEX, 0);
            BEFORE1 = *slot(work, ZONE_INDEX, 1);

            attached_script[0] = (s32) ((1u << 16) | EVT_USER_FUNC);
            attached_script[1] = (s32) &attached;
            attached_script[2] = (s32) EVT_END_EVT;
            attached_script[3] = (s32) EVT_END_SCRIPT;
            OURS = (u32) attached_script;

            /* evt_door_set_event(name, which, script) -- argc 4 counting the
               function pointer itself. */
            setter_script[0] = (s32) ((4u << 16) | EVT_USER_FUNC);
            setter_script[1] = (s32) &evt_door_set_event;
            setter_script[2] = (s32) zone_name;
            setter_script[3] = (s32) ZONE_WHICH;
            setter_script[4] = (s32) attached_script;
            setter_script[5] = (s32) EVT_END_EVT;
            setter_script[6] = (s32) EVT_END_SCRIPT;

            FIRED = GAME_FRAMES;
            ENTRY = (u32) evtEntry(setter_script, 0, 0);
        }
        if (FIRED != 0 && WORK != 0)
        {
            unsigned char *work = (unsigned char *) WORK;

            AFTER0 = *slot(work, ZONE_INDEX, 0);
            AFTER1 = *slot(work, ZONE_INDEX, 1);
        }
    }
    if (realMain[seq] != 0)
        realMain[seq](work_unused);
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
