/*
    An orb that drifts around the arena like a DVD logo, with five beams
    spinning around it at 72 degrees apart.

    The entities are placed by `tables/enemies.csv`, not spawned -- calling
    `npcEntryFromTemplate` from a sequence hook hangs (D155). All this does is
    move things that already exist.

    ⚠️ POSITIONS ARE WRITTEN AFTER THE GAME'S OWN UPDATE. `mod_prolog` installs
    a hook on `seq_data[].main`; the original is called FIRST and the writes
    happen after it, so an NPC's own move script cannot overwrite them in the
    same frame. Writing first was the obvious order and would have lost.

    ⛔ No libm: a REL links `-nostdlib`, so there is no `sinf`. The circle comes
    from a 64-entry table built at `mod_prolog` by walking the unit circle with
    a rotation recurrence -- no trig calls anywhere.
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
extern void *npcGetWorkPtr(void);

#define WORK_NUM 0x004
#define WORK_ENTRIES 0x008
#define ENTRY_STRIDE 0x748
#define ENTRY_FLAG8 0x008
#define ENTRY_POSITION 0x2A0
#define ENTRY_TRIBE_ID 0x49C
#define ENTRY_ACTIVE 0x1u

/* ⛔ Stand-ins. The portal (307) and his beam (311) delete themselves after
   ~314 frames; they are projectiles. See tables/enemies.csv. */
#define ORB_TRIBE 295 /* Mr. L */
#define BEAM_TRIBE 0  /* Goomba */
#define BEAMS 5

/* he1_04's own enemies span x -2175..325, y 0..200, z -138..138. The orb is
   kept well inside that, since the room's real walls are unmeasured. */
#define MIN_X (-1800.0f)
#define MAX_X (-200.0f)
#define MIN_Y (60.0f)
#define MAX_Y (260.0f)
#define ORB_SPEED_X (7.0f)
#define ORB_SPEED_Y (4.3f)

#define RADIUS (170.0f)
#define SPIN_STEP 1 /* table entries per frame; 64 entries = one turn */

#define TABLE 64
#define SEQ_COUNT 6
#define SEQ_GAME 2

/*
      [0] magic        [4] beams found      [7] orb y bits
      [1] game frames  [5] bounces          [8] spin index
      [2] npcs seen    [6] orb x bits       [9] frames the orb was moved
      [3] orb found
*/
#define PROBE 0x80005000
#define MAGIC 0x0B0A11ACu
#define REPORT_WORDS 10

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define NPCS_SEEN (probe[2])
#define ORB_FOUND (probe[3])
#define BEAMS_FOUND (probe[4])
#define BOUNCES (probe[5])
#define ORB_X_BITS (probe[6])
#define ORB_Y_BITS (probe[7])
#define SPIN_INDEX (probe[8])
#define MOVED_FRAMES (probe[9])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static f32 sinTable[TABLE];
static f32 cosTable[TABLE];

static f32 orbX = -900.0f;
static f32 orbY = 160.0f;
static f32 velX = ORB_SPEED_X;
static f32 velY = ORB_SPEED_Y;
static u32 spin = 0;

/* One turn of the unit circle by repeated rotation. The step angle is
   2*pi/64, and its sine and cosine are written out as constants because
   computing them would need the library this cannot link. */
#define STEP_COS 0.99518472f
#define STEP_SIN 0.09801714f

static void buildTables(void)
{
    f32 c = 1.0f;
    f32 s = 0.0f;
    u32 i;

    for (i = 0; i < TABLE; i++)
    {
        f32 nc;
        f32 ns;

        cosTable[i] = c;
        sinTable[i] = s;
        nc = c * STEP_COS - s * STEP_SIN;
        ns = s * STEP_COS + c * STEP_SIN;
        c = nc;
        s = ns;
    }
}

static void setPosition(u8 *entry, f32 x, f32 y, f32 z)
{
    f32 *pos = (f32 *) (entry + ENTRY_POSITION);

    pos[0] = x;
    pos[1] = y;
    pos[2] = z;
}

static void driveOrb(void)
{
    u8 *work = (u8 *) npcGetWorkPtr();
    u8 *entries;
    u8 *orb = 0;
    u8 *beams[BEAMS];
    u32 found = 0;
    s32 count;
    s32 i;
    f32 orbZ = 0.0f;

    if (work == 0)
        return;
    count = *(s32 *) (work + WORK_NUM);
    entries = *(u8 **) (work + WORK_ENTRIES);
    if (entries == 0 || count <= 0 || count > 96)
        return;
    NPCS_SEEN = (u32) count;

    for (i = 0; i < count; i++)
    {
        u8 *entry = entries + i * ENTRY_STRIDE;
        u32 tribe;

        if ((*(u32 *) (entry + ENTRY_FLAG8) & ENTRY_ACTIVE) == 0)
            continue;
        tribe = *(u32 *) (entry + ENTRY_TRIBE_ID);
        if (tribe == ORB_TRIBE && orb == 0)
            orb = entry;
        else if (tribe == BEAM_TRIBE && found < BEAMS)
            beams[found++] = entry;
    }
    ORB_FOUND = orb != 0;
    BEAMS_FOUND = found;
    if (orb == 0)
        return;

    /* DVD-logo drift: advance, and reverse on contact with a bound. */
    orbX += velX;
    orbY += velY;
    if (orbX < MIN_X) { orbX = MIN_X; velX = -velX; BOUNCES += 1; }
    if (orbX > MAX_X) { orbX = MAX_X; velX = -velX; BOUNCES += 1; }
    if (orbY < MIN_Y) { orbY = MIN_Y; velY = -velY; BOUNCES += 1; }
    if (orbY > MAX_Y) { orbY = MAX_Y; velY = -velY; BOUNCES += 1; }

    setPosition(orb, orbX, orbY, orbZ);
    ORB_X_BITS = *(u32 *) &orbX;
    ORB_Y_BITS = *(u32 *) &orbY;

    /* Five beams, evenly spaced, all turning together. */
    spin = (spin + SPIN_STEP) % TABLE;
    SPIN_INDEX = spin;
    for (i = 0; i < (s32) found; i++)
    {
        u32 at = (spin + (u32) i * (TABLE / BEAMS)) % TABLE;

        setPosition(beams[i],
                    orbX + cosTable[at] * RADIUS,
                    orbY + sinTable[at] * RADIUS,
                    orbZ);
    }
    MOVED_FRAMES += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;

    /* ⚠️ The game's own update first. See the note at the top of this file. */
    if (realMain[seq] != 0)
        realMain[seq](work);

    if (seq == SEQ_GAME)
        driveOrb();
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
    buildTables();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
