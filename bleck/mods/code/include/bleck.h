/*
    Tags: declare in the source what mod.json would otherwise have to repeat.

    A hook names a game function and one of this mod's own functions. mod.json
    could only ever name the second as a string, so the manifest had to be kept
    in step with the code by hand -- and renaming a function turned into a link
    error rather than something a reader could see coming.

        BLECK_HOOK(mapDataPtr, before)
        void watchMapData(void *work) { ... }

    The mode is `before`, `after` or `replace`. `before` and `after` keep the
    original function working; `replace` takes it over (D96, D97).

    ⚠️ These expand to NOTHING. They exist so the C compiler validates the
    syntax -- bleck reads the same text separately, and a typo that would
    otherwise be a silently-ignored tag is a compile error instead.

    ⚠️ A tag must sit directly above the definition it describes. bleck looks a
    few lines ahead and refuses a tag it cannot attach to.
*/

#ifndef BLECK_H
#define BLECK_H

#define BLECK_HOOK(function, mode)

#endif
