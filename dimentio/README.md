# Dimentio

**The window onto Super Paper Mario's art**, without building a 460 MB disc
first.

Named for the jester who steps sideways out of the world to watch it.

```bash
cargo run -- ../work/export        # a folder bleck exported into
```

## ⛔ This program reads no game formats, and never should

`bleck` owns every format on the disc — TPL, U8, LZ77, setup files, evt
bytecode — and is tested against real data. A second implementation here would
drift from that one silently, and the failure mode is a texture that builds
correctly but displays wrongly, or the reverse.

So `bleck` exports PNG and JSON; this renders them. The viewer improves for
free as `bleck` learns more formats, and a format bug has exactly one place to
be fixed. The full reasoning is in [`docs/plan-dimentio.md`](../docs/plan-dimentio.md).

## State: stage 1 of 5

A texture browser: a virtualised grid, search, a format filter, and a detail
panel showing size, format, source disc file and archive member.

⚠️ **Rows are virtualised deliberately.** The disc holds 21,780 textures and
egui uploads every image it draws to the GPU and keeps it, so drawing them all
exhausts texture memory within seconds of scrolling. `show_rows` only calls
back for what is on screen.

🔶 **Not yet confirmed by eye.** It compiles, passes `clippy -D warnings`,
launches, and holds a live window at 126 MB — but the machine this was written
on could not screenshot its own desktop, so nobody has actually *looked* at it.
That is the one check left. **There is deliberately no 3D viewport yet** — the model
container is not decoded (only its string table is readable), so a camera
orbiting an empty scene would prove nothing and could not be validated. Stage 2
starts when there is geometry to show.

## Why Rust, and what that must not cost

`wgpu` reaches Vulkan, Metal and DX12 from one codebase, and the result is a
single static binary per platform with no runtime to install.

⚠️ The conditions that keep it from becoming a liability:

1. **No game-format parsing here** — the rule above.
2. **`bleck`'s own build, test and lint never require a Rust toolchain.** This
   crate has its own CI job for that reason.
3. **Dimentio is a lens on the CLI, never the only way to do something.** A
   headless machine stays fully capable.

## Building

Needs a recent stable Rust. `Cargo.lock` is committed, and `image` is pinned to
0.25.5 because 0.25.10 requires rustc 1.88 while this was written against 1.87 —
raise it once the toolchain floor moves.
