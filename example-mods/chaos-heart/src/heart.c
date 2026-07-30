/*
    The Chaos Heart attack: the heart drifts like a DVD logo while five beams
    orbit it, evenly spaced and turning together.

    ✅ The heart is an EFFECT (D171), spawned by an unnamed function at
    0x80094E44 whose first argument selects the variant -- **16 is the Chaos
    Heart** and 0..7 are the coloured Pure Hearts (D172).

    ✅ Its position lives at userWork +0x10 / +0x14 / +0x18 (D173), measured by
    spawning at a known point and reading the block back. The same dump showed
    userWork +0x00 holding the variant and +0x04 the value the entry function
    clamps to 8, which is what confirms the block is the right one.

    ⛔ No libm: a REL links -nostdlib, so there is no sinf. The circle comes from
    a 64-entry table built at load by walking the unit circle with a rotation
    recurrence -- the same approach as orb-attack, and no trig call anywhere.
*/

typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;
typedef float f32;

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *marioGetPtr(void);

/* Every effect entry found so far takes this shape: variant, then a position.
   Shared by the heart and the beam, which is what lets one `summon` drive
   both. */
typedef void *(EffEntry)(s32 variant, f32 x, f32 y, f32 z);

#define HEART_ENTRY 0x80094E44
#define CHAOS 16

/* `robo_beam`, from the 174 effects `scripts/dump_effects.py` lists. Its
   position sits at userWork +0x10 like the heart's, and it does NOT expire --
   both measured (D183). */
#define BEAM_ENTRY 0x800A6880
#define BEAM_VARIANT 0

#define MARIO_POSITION 0x5C
#define EFF_USERWORK 0x00C

/* Measured (D173), not guessed. */
#define WORK_VARIANT 0x00
#define WORK_X 0x10
#define WORK_Y 0x14
#define WORK_Z 0x18

#define ORBITERS 5
#define TABLE 64
#define RADIUS (150.0f)
#define SPIN_STEP 1

/* Bounds are relative to where the heart spawns, since the room's real walls
   are unmeasured and an absolute box risked putting it inside geometry. */
#define SPAN_X (420.0f)
#define DROP_Y (40.0f)
#define RISE_Y (200.0f)
#define SPEED_X (3.2f)
#define SPEED_Y (2.1f)

#define OFFSET_X (120.0f)
#define OFFSET_Y (110.0f)

#define SPAWN_AT 300
#define SEQ_COUNT 6
#define SEQ_GAME 2

/*
      [0] magic          [4] orbiters made   [7] heart x bits
      [1] game frames    [5] chaos entry     [8] heart y bits
      [2] spawn attempts [6] driven frames   [9] bounces
      [3] chaos non-null
      [10] userWork ptr  [11] spin index
*/
#define PROBE 0x80005000
#define MAGIC 0xC0A05EA7u
#define REPORT_WORDS 12

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define ATTEMPTS (probe[2])
#define RETURNED (probe[3])
#define MADE (probe[4])
#define ENTRY_PTR (probe[5])
#define DRIVEN (probe[6])
#define BOUNCES (probe[9])
#define USERWORK_PTR (probe[10])
#define SPIN_INDEX (probe[11])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static f32 sinTable[TABLE];
static f32 cosTable[TABLE];

static u8 *chaosWork = 0;
static u8 *orbitWork[ORBITERS];
static u32 orbiters = 0;
static u32 spawned = 0;
static u32 spin = 0;

static f32 homeX = 0.0f;
static f32 homeY = 0.0f;
static f32 heartX = 0.0f;
static f32 heartY = 0.0f;
static f32 heartZ = 0.0f;
static f32 velX = SPEED_X;
static f32 velY = SPEED_Y;

#define STEP_COS 0.99518472f
#define STEP_SIN 0.09801714f

static void buildTables(void)
{
    f32 c = 1.0f;
    f32 s = 0.0f;
    u32 i;

    for (i = 0; i < TABLE; i++)
    {
        f32 nc, ns;

        cosTable[i] = c;
        sinTable[i] = s;
        nc = c * STEP_COS - s * STEP_SIN;
        ns = s * STEP_COS + c * STEP_SIN;
        c = nc;
        s = ns;
    }
}

static void place(u8 *work, f32 x, f32 y, f32 z)
{
    if (work == 0)
        return;
    *(f32 *) (work + WORK_X) = x;
    *(f32 *) (work + WORK_Y) = y;
    *(f32 *) (work + WORK_Z) = z;
}

static u8 *summon(u32 address, s32 variant, f32 x, f32 y, f32 z)
{
    EffEntry *entry = (EffEntry *) address;
    void *made;

    ATTEMPTS += 1;
    made = entry(variant, x, y, z);
    if (made == 0)
        return 0;
    return *(u8 **) ((u8 *) made + EFF_USERWORK);
}

static void summonAll(void)
{
    u8 *mario = (u8 *) marioGetPtr();
    f32 *from;
    u32 i;

    if (mario == 0)
        return;
    from = (f32 *) (mario + MARIO_POSITION);
    homeX = from[0] + OFFSET_X;
    homeY = from[1] + OFFSET_Y;
    heartX = homeX;
    heartY = homeY;
    heartZ = from[2];

    chaosWork = summon(HEART_ENTRY, CHAOS, heartX, heartY, heartZ);
    ENTRY_PTR = (u32) chaosWork;
    USERWORK_PTR = (u32) chaosWork;
    RETURNED = chaosWork != 0;

    for (i = 0; i < ORBITERS; i++)
    {
        orbitWork[i] = summon(BEAM_ENTRY, BEAM_VARIANT, heartX, heartY, heartZ);
        if (orbitWork[i] != 0)
            orbiters += 1;
    }
    MADE = orbiters;
    spawned = 1;
}

static void drive(void)
{
    u32 i;

    if (chaosWork == 0)
        return;

    /* DVD-logo drift: advance, and reverse on contact with a bound. */
    heartX += velX;
    heartY += velY;
    if (heartX < homeX - SPAN_X) { heartX = homeX - SPAN_X; velX = -velX; BOUNCES += 1; }
    if (heartX > homeX + SPAN_X) { heartX = homeX + SPAN_X; velX = -velX; BOUNCES += 1; }
    if (heartY < homeY - DROP_Y) { heartY = homeY - DROP_Y; velY = -velY; BOUNCES += 1; }
    if (heartY > homeY + RISE_Y) { heartY = homeY + RISE_Y; velY = -velY; BOUNCES += 1; }

    place(chaosWork, heartX, heartY, heartZ);
    probe[7] = *(u32 *) &heartX;
    probe[8] = *(u32 *) &heartY;

    /* Five orbiters, evenly spaced, all turning together. */
    spin = (spin + SPIN_STEP) % TABLE;
    SPIN_INDEX = spin;
    for (i = 0; i < ORBITERS; i++)
    {
        u32 at = (spin + i * (TABLE / ORBITERS)) % TABLE;

        place(orbitWork[i],
              heartX + cosTable[at] * RADIUS,
              heartY + sinTable[at] * RADIUS,
              heartZ);
    }
    DRIVEN += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;

    /* The game's own update first, or the effect's own main function undoes the
       placement in the same frame. */
    if (realMain[seq] != 0)
        realMain[seq](work);

    if (seq != SEQ_GAME)
        return;
    if (!spawned && GAME_FRAMES > SPAWN_AT)
        summonAll();
    else if (spawned)
        drive();
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
    for (i = 0; i < ORBITERS; i++)
        orbitWork[i] = 0;
    buildTables();
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
