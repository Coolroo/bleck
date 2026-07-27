/*
    The mod side of unattended in-game testing.

    A mod writes progress into a fixed block of RAM; `scripts/ingame.py`
    attaches to the running Dolphin process and reads it back. That turns
    "nothing happened" into "reached stage 3 of 5, hook fired 130 times", and
    removes the human from the loop entirely.

    Copy this into a mod's sources, or include it -- it depends on nothing.

        #include "probe.h"

        void mod_prolog(void)
        {
            probeReset();
            probeMark(PROBE_STAGE_LOADED);
            PROBE(4) = someInterestingPointerValue;
        }

    Then:

        uv run python scripts/ingame.py my-mod --words 8

    ⚠️ Only one mod can use this at a time, which is fine because the Gecko
    loader only runs one module anyway.

    Why this address: 0x80005000 sits in the unused TRK interrupt vector table,
    which is free and at the same address in every region and revision --
    `spm-loaders` reserves the same range for the same reason. The Gecko loader
    parks a memcpy at 0x80004000, well below it.
*/

#ifndef BLECK_PROBE_H
#define BLECK_PROBE_H

typedef unsigned int ProbeWord;

#define PROBE_BASE 0x80005000

/* Word `n` of the report block. Read back by `ingame.py --words`. */
#define PROBE(n) (((volatile ProbeWord *) PROBE_BASE)[(n)])

/*
    Word 0 is a magic value, so a reader can tell "the mod has not run yet"
    apart from "the mod ran and reported zero". Without it, a failure to load
    looks exactly like a successful run that did nothing -- which is the
    ambiguity this whole mechanism exists to remove.
*/
#define PROBE_MAGIC 0x424C434BU /* 'BLCK' */

/* Word 1 is a bitmask of stages reached. Words 2 upward are yours. */
#define PROBE_STAGE_LOADED 0x01
#define PROBE_STAGE_HOOKED 0x02
#define PROBE_STAGE_RAN 0x04

#define PROBE_FIRST_FREE 2

static inline void probeReset(void)
{
    ProbeWord i;

    /* Whatever was there is not ours -- a previous boot, or noise. */
    for (i = 0; i < 32; i++)
        PROBE(i) = 0;
    PROBE(0) = PROBE_MAGIC;
}

static inline void probeMark(ProbeWord stage)
{
    PROBE(1) |= stage;
}

static inline void probeCount(ProbeWord word)
{
    PROBE(word) += 1;
}

#endif /* BLECK_PROBE_H */
