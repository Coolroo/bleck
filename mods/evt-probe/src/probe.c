/*
    D87 steps 1 and 2, before anything writes to a script.

    Step 1: is `MapData.initScript` linked when `mod_prolog` runs? `map_data.h`
    annotates it "In rel, linked by prolog function", so the map's own REL may
    supply it later. D51 checked `mapDataPtr()` was valid that early and
    recorded ✅ -- but it checked the *MapData*, not this field.

    Step 2: does the live pointer decode as plausible evt bytecode? Writing to
    a pointer that is not a script is how the D51 freeze would look.

    `aa4_01` is the attract demo's first map, so it is guaranteed live in an
    unattended run. `he1_01` is never loaded, which is the control: if both
    read the same at prolog and only `aa4_01` changes once live, the field is
    linked per-map and boot-time patching is ruled out.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'EVTP'
      +0x04  mapDataPtr("aa4_01")
      +0x08  aa4_01 initScript, at mod_prolog
      +0x0C  mapDataPtr("he1_01")
      +0x10  he1_01 initScript, at mod_prolog        (control, never loaded)
      +0x14  aa4_01 initScript, re-read during SEQ_GAME
      +0x18  he1_01 initScript, re-read during SEQ_GAME
      +0x1C  live script word 0
      +0x20  live script word 1
      +0x24  live script word 2
      +0x28  live script word 3
      +0x2C  SEQ_GAME frames seen
      +0x30  name of the map that was live, 16 bytes

    Target: eu0. Nothing here writes to game memory.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x45565450U /* 'EVTP' */

#define MAP_INIT_OFFSET 0x18
#define SEQ_COUNT 6
#define SEQ_GAME 2

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

typedef struct
{
    s32 seq;
    s32 stage;
    const char *p0;
    const char *p1;
} SeqWork;

extern SeqDef seq_data[];
extern SeqWork seqWork;
extern void *mapDataPtr(const char *name);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define AA4_PTR (probe[1])
#define AA4_INIT_PROLOG (probe[2])
#define HE1_PTR (probe[3])
#define HE1_INIT_PROLOG (probe[4])
#define AA4_INIT_LIVE (probe[5])
#define HE1_INIT_LIVE (probe[6])
#define WORD(i) (probe[7 + (i)])
#define GAME_FRAMES (probe[11])
#define MAPNAME (probe[12])

static const char watched[] = "aa4_01";
static const char control[] = "he1_01";

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

/* The module links -nostdlib, so there is no strncpy to call. */
static void recordMapName(const char *name)
{
    volatile u32 *out = &MAPNAME;
    u32 i;

    for (i = 0; i < 4; i++)
        out[i] = 0;
    if (name == 0)
        return;
    for (i = 0; i < 15 && name[i] != 0; i++)
        ((volatile unsigned char *) out)[i] = (unsigned char) name[i];
}

static u32 initScriptOf(const char *name)
{
    unsigned char *entry = (unsigned char *) mapDataPtr(name);

    if (entry == 0)
        return 0;
    return (u32) *(s32 **) (entry + MAP_INIT_OFFSET);
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;

        /* Sample once, on the first frame of gameplay. Re-reading every frame
           would overwrite the interesting first observation with whatever the
           last map left behind. */
        if (GAME_FRAMES == 1)
        {
            u32 live = initScriptOf(watched);
            u32 i;

            AA4_INIT_LIVE = live;
            HE1_INIT_LIVE = initScriptOf(control);
            recordMapName(seqWork.p0);

            if (live != 0)
                for (i = 0; i < 4; i++)
                    WORD(i) = (u32) ((s32 *) live)[i];
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

    for (i = 0; i < 16; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    AA4_PTR = (u32) mapDataPtr(watched);
    AA4_INIT_PROLOG = initScriptOf(watched);
    HE1_PTR = (u32) mapDataPtr(control);
    HE1_INIT_PROLOG = initScriptOf(control);

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
