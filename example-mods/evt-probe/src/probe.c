/*
    D87 step 3: write one same-size instruction into a vanilla script and see
    whether it takes effect.

    Target: `he1_01`'s init script, whose first instruction is
    `DEBUG_PUT_MSG <msg>` -- opcode 0x72, argc 1, so two words. `USER_FUNC f`
    with no extra arguments is `EVT_HELPER_CMD(1, 92)` plus the pointer, also
    two words (`spm-headers/mod/evt_cmd.h`). So the message can be replaced by a
    call into this module with no instruction moving, which is what keeps the
    per-`EvtEntry` `jumptable[]` valid (D87).

    Chosen because it is the one instruction here that is not load-bearing. The
    rest of the script is `evt_hitobj_attr_onoff`, `evt_mapobj_flag_onoff`,
    `evt_mapobj_flag4_onoff` and `evt_map_playanim` -- scene setup, where a
    clobber would break the map and make a failure unreadable.

    `aa4_01` is deliberately NOT the target: it drives the attract demo, so
    breaking it would stop the rig reaching gameplay at all.

    ⚠️ No cache flush. This writes evt *bytecode*, which the VM reads as data
    through the same data cache -- unlike patching PowerPC instructions, which
    needs dcbst/sync/icbi.

    The sentinel is written before the hook returns, so the observation does not
    depend on getting the user-func return convention right.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'EVTX'
      +0x04  he1_01 initScript
      +0x08  original word 0        (expected 0x00010072)
      +0x0C  original word 1        (the message pointer)
      +0x10  patch state: 0 never ran, 1 applied, 2 refused
      +0x14  word 0 read back after the write
      +0x18  word 1 read back after the write
      +0x1C  times the hook was entered
      +0x20  sentinel, written by the hook
      +0x24  SEQ_GAME frames

    Run with:  scripts/ingame.py evt-probe --map he1_01 --words 12
    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x45565458U /* 'EVTX' */
#define SENTINEL 0xB1ECB1ECU

#define MAP_INIT_OFFSET 0x18
#define SEQ_COUNT 6
#define SEQ_GAME 2

/* DEBUG_PUT_MSG, one argument. Refuse to patch anything else. */
#define EXPECT_WORD0 0x00010072U
/* USER_FUNC, one argument -- the function pointer itself. */
#define USER_FUNC_1 0x0001005CU

#define PATCH_APPLIED 1
#define PATCH_REFUSED 2

/* What the evt VM expects back so the script advances. Not documented in
   spm-headers; the sentinel is written first so a wrong guess still shows the
   hook ran. */
#define EVT_CONTINUE 2

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *mapDataPtr(const char *name);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define SCRIPT (probe[1])
#define ORIG_W0 (probe[2])
#define ORIG_W1 (probe[3])
#define STATE (probe[4])
#define BACK_W0 (probe[5])
#define BACK_W1 (probe[6])
#define HOOK_HITS (probe[7])
#define HOOK_MARK (probe[8])
#define GAME_FRAMES (probe[9])

static const char target[] = "he1_01";

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

/* Called by the patched script. Signature is evt's UserFunc. */
static s32 patchedHook(void *entry, int firstRun)
{
    (void) entry;
    (void) firstRun;

    HOOK_HITS += 1;
    HOOK_MARK = SENTINEL;
    return EVT_CONTINUE;
}

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
    unsigned char *entry;
    u32 *script = 0;
    u32 i;

    for (i = 0; i < 12; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    entry = (unsigned char *) mapDataPtr(target);
    if (entry != 0)
        script = *(u32 **) (entry + MAP_INIT_OFFSET);
    SCRIPT = (u32) script;

    if (script != 0)
    {
        ORIG_W0 = script[0];
        ORIG_W1 = script[1];

        /* Only patch what was decoded. If the script is not what the dump
           showed, say so rather than writing into something unknown. */
        if (script[0] == EXPECT_WORD0)
        {
            script[0] = USER_FUNC_1;
            script[1] = (u32) &patchedHook;
            STATE = PATCH_APPLIED;
        }
        else
        {
            STATE = PATCH_REFUSED;
        }

        BACK_W0 = script[0];
        BACK_W1 = script[1];
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
