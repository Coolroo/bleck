/*
    Diagnostic 2: why does the coin script still not pay out?

    Diagnostic 1 established that the module loads and executes (a direct
    instruction patch from _prolog worked), and that evtEntry() called from
    _prolog does nothing. The fix hooked seq_data[SEQ_GAME].init and still
    produced no coins, so something between "the module runs" and "the script
    runs" is still wrong, and the symptom does not say which.

    THREE independent signals, one boot. Each is observable on its own and each
    depends on strictly more than the last.

      A - DOUBLE SPEED, applied from INSIDE the hook (not from _prolog).
          Proves the seq_data hook fired at all. Diagnostic 1 applied this at
          _prolog, so it could not distinguish "module ran" from "hook ran";
          moving it inside the hook is the whole point.

      B - +100 COINS, once, via pouchAddCoin() - a direct game function, no evt
          involved. Proves the hook runs at a point where game state is live
          and writable. If A fires and B does not, the hook is running far too
          early.

      C - +1 COIN PER SECOND via evtEntry(). The evt path.

    Reading the result:

      A+B+C     everything works; promote the .main hook into the emitter
      A+B, no C evt scheduling is still wrong even at a fully live SEQ_GAME
      A, no B/C the hook fires but the game is not live yet
      none      the seq_data write is not taking effect at all

    Also switches the hook from .init to .main, which is what every mod in the
    scene actually uses (evtpatch, spm-practice-codes, SPM-RPG-Battles). Nobody
    hooks .init, and this is the most likely reason why.

    Target: eu0 only.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;
typedef float f32;

/* --- resolved by name from the symbol list ------------------------------- */

extern void evt_pouch_add_coins(void);
extern void *evtEntry(const s32 *script, u32 priority, u8 flags);
extern void pouchAddCoin(s32 increase);

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

#define SEQ_GAME 2

/* Signal C: script main { loop { wait(60) evt_pouch_add_coins(1) } } */
const s32 bleck_script_main[] = {
    65541, 0, 65545, 60,
    131164, (s32) &evt_pouch_add_coins, 1, 6,
    1,
};

/* --- Signal A: a patch that depends on nothing but running --------------- */

#define MARIO_GET_GAME_SPEED_SCALE 0x80121e50
#define BRANCH_REACH 0x2000000

f32 fastGameSpeedScale(void)
{
    return 2.0f;
}

static void flushInstruction(u32 address)
{
    __asm__ volatile(
        "dcbst 0,%0\n"
        "sync\n"
        "icbi 0,%0\n"
        "isync\n"
        :
        : "r"(address)
        : "memory");
}

static void patchGameSpeed(void)
{
    u32 target = MARIO_GET_GAME_SPEED_SCALE;
    u32 to = (u32) &fastGameSpeedScale;
    s32 delta = (s32) (to - target);

    if (delta < -BRANCH_REACH || delta >= BRANCH_REACH)
        return;

    *(volatile u32 *) target = 0x48000000u | ((to - target) & 0x03FFFFFCu);
    flushInstruction(target);
}

/* --- the hook ------------------------------------------------------------ */

/* Non-zero initialiser keeps this in .data; the loader allocates bss but
   nothing documents whether it zeroes it. */
static SeqFunc *realGameMain = (SeqFunc *) 1;

static void gameMainHook(void *work)
{
    /* Unhook first: .main runs every frame, so without this every signal
       would fire sixty times a second. */
    seq_data[SEQ_GAME].main = realGameMain;

    patchGameSpeed();   /* A */
    pouchAddCoin(100);  /* B */
    evtEntry(bleck_script_main, 0, 0); /* C */

    if (realGameMain != 0)
        realGameMain(work);
}

void _prolog(void)
{
    realGameMain = seq_data[SEQ_GAME].main;
    seq_data[SEQ_GAME].main = &gameMainHook;
}

void _epilog(void)
{
}

void _unresolved(void)
{
}
