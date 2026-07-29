---
title: Two wrong names in the PAL symbol list, and 148 builtins with no address
description: Comparing two upstream sources that had only ever been used separately — spm-headers' lst against spm-decomp's symbol table — found both
---

# Two wrong names in `spm.eu0.lst`, and 148 builtins that cannot be linked

Two SPM reverse-engineering projects publish symbol information for PAL rev 0,
and they had never been compared against each other:

- [`spm-headers`](https://github.com/SeekyCt/spm-headers) ships
  `linker/spm.eu0.lst` — 976 lines, 927 human-named symbols, the file most tools
  link against.
- [`spm-decomp`](https://github.com/SeekyCt/spm-decomp) ships
  `config/EU0/symbols.txt` — 34,302 parsed entries, of which **4,584** are
  human-named and 3,960 are functions.

(Neither is redistributed here; both are the upstream projects' own work and
should be taken from them.)

## ⛔ Two of the lst's addresses carry the wrong name

Of the **744 names both sources know**, exactly **2 disagree** — and in both
cases the lst names the *neighbouring* function:

| name in `spm.eu0.lst` | address | what the decomp calls that address |
|---|---|---|
| `strlen` | `0x80267018` | **`TRK_strlen`** — the debugger's own copy |
| `evt_fairy_flag_onoff` | `0x800E8214` | **`evt_fairy_flag_onoff_all`** |

The decomp holds *both* symbols in each case, which is what makes this
diagnosable rather than a coin toss: the lst has not invented an address, it has
attached the wrong name to a real one.

⚠️ **A mod calling `strlen` through the lst jumps into the TRK debugger.**
Nothing had, which is why it went unnoticed.

🔶 Two disagreements out of 744 is a small sample, and "the decomp is always
right" is *not* the claim being made. What is claimed is that these two
addresses are worth checking before relying on them.

## ⛔ A third of the declared evt builtins have no address at all

`spm-headers` declares 443 evt user functions with `EVT_DECLARE_USER_FUNC`. A
script can name any of them, pass every check a compiler could make, run a whole
toolchain — and then fail at link time with a missing symbol, because a
*declaration* and an *address* come from two different files that nothing
compares:

| where the 443 live | count | linkable |
|---|---|---|
| `spm.eu0.lst` | 295 | ✅ |
| only `spm-decomp`'s DOL symbol table | **94** | ✅ if you have that clone |
| only `config/EU0/relF/symbols.txt` | 21 | ⛔ REL-relative addresses |
| nowhere at all | 33 | ⛔ declared, address unknown |

🔶 The 33 that appear nowhere have names like `evt_an2_08_draw_face` and
`evt_bos_01_*`, which suggests per-map code living in the game's own REL — the
same explanation as the 21 REL-relative ones. No table names them.

⚠️ The 21 REL-relative symbols are a different problem from a missing one:
they live inside the game's own relocatable module, and linking one module
against another module's internals is not a matter of finding the number.

⛔ **`relF/symbols.txt` looks tempting and is not usable** for this: 30,162
lines, but only 216 human names, at REL-relative addresses like `0x000052E4`.

## The pattern worth taking away

**Two upstream sources, each correct about what it describes, contradicting each
other in a way neither could notice.** Both findings on this page came from the
same move: comparing things that had only ever been used separately. The
[wrong argument count in `evt_door.h`](evt-door-argc.md) is a third instance,
found the same way — the macro against the comment directly above it.

*(Sources: bleck decision log D60, D61. The 4,584 figure also corrects an
earlier "~9,566 human-named symbols" claim in this project, which had been
repeated without being measured.)*
