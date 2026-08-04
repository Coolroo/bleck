# Assets

## `icon.png` — the window icon

**Original artwork, made for this project.** ⛔ **Not a game asset**, and not
traced or derived from one. It is a jester motif — a diamond-tipped hat over a
half-light, half-dark mask — which is what the program is named after, drawn
rather than extracted.

That distinction matters here. `CLAUDE.md`'s standing rule is **no game
assets**: `work/` is git-ignored and stays that way, and nothing ripped from the
disc is committed. This file is not an exception to that rule, because it was
not taken from the disc. It needs no row in `THIRD-PARTY-NOTICES.md` and no
attribution.

⚠️ **If you replace it, keep it original.** Dropping in official artwork would
put content this repo has no licence for into an MIT project's permanent
history, where removing it later means rewriting history rather than deleting a
file.

### Shape

256×256 RGBA, compiled into the binary by `include_bytes!` in `main.rs` and
decoded at startup with the `image` crate that is already a dependency.

⚠️ **The rounded corners are transparent, and must stay that way.** The source
artwork was 1254×1254 with no alpha channel, so its corners were opaque black;
they were cleared by a flood fill from the four corners rather than by keying
out dark pixels. A plain darkness key would have eaten the jester's own black
outlines, which are the same colour — the flood fill cannot reach them, because
the rounded border encloses everything inside it.

`main.rs`'s `icon_decodes` test asserts the file still decodes, is square, and
still has at least one transparent pixel. That last assertion is the one that
catches a replacement saved without alpha.
