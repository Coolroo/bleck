/*
    Super Dimentio, harder.

    Three edits, all to static game data, applied once at `mod_prolog`:

      maxHp          200 -> 255   `npcTribes[309].maxHp`
      attack power     2 ->   4   an argument word in his move script
      attack cooldown 1000 -> 350 another argument word in the same script

    ⚠️ WHY ARGUMENT WORDS AND NOT `code.patches`. A patch replaces an
    *instruction* with a USER_FUNC of the same argc, which means writing a
    handler whose prototype must match and whose return value drives the VM.
    Both levers here are plain argument words to calls the game already makes,
    so rewriting them needs none of that -- no prototype to get wrong, no
    blocking-return semantics to guess at, and no jump-table concern because
    nothing moves.

    ⚠️ `maxHp` IS A u8. 255 is the ceiling, not a choice; he starts at 200, so
    there is only +27% available from HP alone. That is why the other two
    levers matter.

    Addresses come from the symbol list via `extern`, so this file contains no
    hard-coded game address.
*/

typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;

/* Both are in spm.eu0.lst, so elf2rel binds them. */
extern u8 npcTribes[];
extern u8 npcEnemyTemplates[];

#define TRIBE_STRIDE 0x68
#define TRIBE_MAXHP 0x18

#define TEMPLATE_STRIDE 0x68
#define TEMPLATE_MOVE_SCRIPT 0x38

/* Measured, not guessed: template 255 is スーパーディメーン and tribe 309 is
   its NPCTribe. Both were read out of the DOL and cross-checked against the
   committed npc catalog. */
#define SUPER_DIMENTIO_TEMPLATE 255
#define SUPER_DIMENTIO_TRIBE 309

/* His move script, by word index. The header words are carried as guards: if
   the script is not the one that was measured, nothing is written. */
#define ATTACK_HEADER_AT 4
#define ATTACK_HEADER 0x0004005Cu /* USER_FUNC argc 4 */
#define ATTACK_POWER_AT 8
#define ATTACK_POWER_WAS 2
#define ATTACK_POWER_NOW 4

#define COOLDOWN_HEADER_AT 25
#define COOLDOWN_HEADER 0x0003005Cu /* USER_FUNC argc 3 */
#define COOLDOWN_AT 28
#define COOLDOWN_WAS 1000
#define COOLDOWN_NOW 350

#define NEW_MAX_HP 255

/*
    A report block, so `scripts/ingame.py` can confirm what happened without a
    human watching a boss fight that takes an hour to reach.

      [0] magic          [4] cooldown before
      [1] status bits    [5] cooldown after
      [2] hp before      [6] attack power before
      [3] hp after       [7] attack power after
*/
/* ⚠️ 0x80005000, matching every other probe and what `ingame.py` reads.
   The loader parks a memcpy at 0x80004000, so anything lower collides. */
#define PROBE 0x80005000
#define MAGIC 0xB055AAD0u
#define REPORT_WORDS 8

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define OK_HP 0x1u
#define OK_ATTACK 0x2u
#define OK_COOLDOWN 0x4u
#define BAD_SCRIPT 0x100u

static u32 *move_script_of(s32 template)
{
    u8 *entry = npcEnemyTemplates + template * TEMPLATE_STRIDE;

    return *(u32 **) (entry + TEMPLATE_MOVE_SCRIPT);
}

static u8 *tribe_of(s32 tribe)
{
    return npcTribes + tribe * TRIBE_STRIDE;
}

void mod_prolog(void)
{
    u8 *tribe = tribe_of(SUPER_DIMENTIO_TRIBE);
    u32 *script = move_script_of(SUPER_DIMENTIO_TEMPLATE);
    u32 status = 0;
    u32 i;

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    probe[2] = tribe[TRIBE_MAXHP];
    tribe[TRIBE_MAXHP] = NEW_MAX_HP;
    probe[3] = tribe[TRIBE_MAXHP];
    status |= OK_HP;

    /* Refuse rather than write: a header that is not what was measured means
       this is not the script this mod was built against. */
    if (script == 0
        || script[ATTACK_HEADER_AT] != ATTACK_HEADER
        || script[COOLDOWN_HEADER_AT] != COOLDOWN_HEADER)
    {
        probe[1] = status | BAD_SCRIPT;
        return;
    }

    probe[6] = script[ATTACK_POWER_AT];
    if (script[ATTACK_POWER_AT] == ATTACK_POWER_WAS)
    {
        script[ATTACK_POWER_AT] = ATTACK_POWER_NOW;
        status |= OK_ATTACK;
    }
    probe[7] = script[ATTACK_POWER_AT];

    probe[4] = script[COOLDOWN_AT];
    if (script[COOLDOWN_AT] == COOLDOWN_WAS)
    {
        script[COOLDOWN_AT] = COOLDOWN_NOW;
        status |= OK_COOLDOWN;
    }
    probe[5] = script[COOLDOWN_AT];

    probe[1] = status;
}
