/*
    A hook declared where the function it names actually lives.

    `mod.json` could only name `watchMapData` as a string, so renaming this
    function used to break the link rather than anything a reader could see.
*/

#include <bleck.h>

typedef unsigned int u32;

#define PROBE 0x80005000

static volatile u32 *const probe = (volatile u32 *) PROBE;

BLECK_HOOK(mapDataPtr, before)
void watchMapData(void)
{
    probe[1] += 1;
}

void mod_prolog(void)
{
    probe[0] = 0x7A6D0DE0u;
}
