# macOS Setup — status, blockers, and what a Mac owner must verify

macOS is a supported target (D30). It was **run on a Mac for the first time on
2026-08-03** — an Apple Silicon MacBook, briefly, retiring exactly one line of
this page (D274). Everything else here is still written from our own source, our
own CI logs, and upstream documents. Every claim carries a confidence marker,
and **almost nothing here is ✅** — reserve that for what was read out of this
repository, a CI run, an authoritative upstream file, or that one session.

⚠️ **Read the marker before budgeting against a line.** A doc full of
confident-sounding untested claims is worse than no doc.

| | meaning |
|---|---|
| ✅ | verified — quoted from this repo's source, a CI job that ran, or an upstream document |
| 🔶 | hypothesis — plausible, unverified, and the reason it is unverified is stated |
| ⛔ | ruled out |

---

## The short version

**Apple Silicon splits this project cleanly in two.**

| Half | Status |
|---|---|
| **Asset work** — extract, texture/model/sound/effect export, rebuild a disc, Dimentio | 🔶 expected to work natively; the two binaries already build and run on an arm64 runner |
| **Code mods** — compiling C into `mod.rel`, embedding the loader | ⚠️ **x86_64-only tools under Rosetta 2**, with an announced end date |

⛔ **The Wii itself is irrelevant to the architecture question.** Everything here
is about the *host* toolchain, not the PowerPC target.

### Blockers, ranked

1. ⚠️ **`wit`'s arm64 binary is reported to be killed on launch until it is
   re-signed** (🔶, below). `wit` is required by `bleck extract` and
   `bleck build` — that is the whole disc path.
2. ⚠️ **devkitPPC has no arm64 *macOS* build**, and Rosetta 2 is scheduled to go
   away (✅ both, below). Every code mod goes through it — **unless it goes
   through the arm64 Linux container, where devkitPPC is native** (D249).
3. ⚠️ **`wstrt` is x86_64-only with no universal build at all** (✅) — same
   Rosetta dependency, no upstream plan visible.
4. ⚠️ **`scripts/ingame.py` needs Dolphin re-signed with debugging
   entitlements** on macOS, and re-signed after every Dolphin update (✅
   upstream README).
5. 🔶 **A downloaded release binary may be quarantined**, depending on how the
   user unpacks it. No signing or notarization exists today.
6. ⚠️ **CI publishes no Intel-Mac artifact** (✅) — `macos-latest` is arm64 only.

### ✅ Blockers 1–3 are answered by [`container.md`](./container.md)

An arm64 Linux devcontainer sidesteps Rosetta entirely, and **it closes blocker
2 outright** (D249): devkitPro publishes **devkitPPC 16.1.0 for aarch64 Linux**,
so the container compiles with the game's own `powerpc-eabi` ABI — the same
toolchain the Windows host uses, running as a native arm64 binary.

| | |
|---|---|
| all four `container_verify.py` mods build a `mod.rel` | ✅ measured |
| two of the four are **byte-identical** to the Windows devkitPPC build | ✅ measured |
| the other two match the Windows build byte for byte too, and disagree only with a stale stored reference | ✅ measured |
| `wit` and `wstrt` build from source and run on arm64 | ✅ measured — no re-signing, because they are not macOS binaries |

⚠️ **This says nothing about *native* macOS devkitPPC.** `pkg.devkitpro.org`
serves `packages/linux/x86_64`, `packages/linux/aarch64` and
`packages/windows/x86_64`; every `macos`/`darwin` path tried returned 404, and
macOS is distributed by a `.pkg` installer instead. The row in the tool table
below is unchanged. The container's answer is "run Linux arm64 in a VM", not
"devkitPro shipped an Apple Silicon build".

⛔ **Dolphin and Dimentio stay native**, so blockers 4 and 5 are untouched.
⛔ **Nothing built in the container has been booted**, on any host.

---

## What is actually verified

### ✅ Both programs already build and run on an arm64 macOS runner

`macos-latest` maps to **macOS 15, arm64, 3 cores**
([GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)),
and both workflows already use it.

| | evidence |
|---|---|
| `bleck` PyInstaller binary builds **and starts** | run `30660950660`, job `macos-arm64` (`91256777974`), 2026-07-31: `Build` ✅, then `ok starts at all`, `ok builtin catalog is bundled`, `ok map catalog is bundled` |
| Dimentio passes `fmt`, `clippy -D warnings`, `cargo test`, `cargo build --release` | run `30599074613`, job `build (macos-latest)` (`91057678385`), 2026-07-31, green |

⚠️ **The build job is currently red on all three platforms and it is not a macOS
fault.** `smoke_binary.py` searches for the item `fire_burst`, which the item
catalog no longer holds; Linux, Windows and macOS fail the same assertion with
the same message. Read it as "the arm64 binary works" plus "the smoke script has
gone stale", not as a macOS problem.

⛔ **This proves nothing about the window, the speaker, or any external tool.**
A CI runner has no display, no audio device, no `wit`, no Dolphin and no
devkitPPC.

### ✅ The macOS binary graph is real, and it is OpenGL, not Metal

`dimentio/Cargo.lock` resolves `cpal 0.17.3`, `coreaudio-rs 0.14.2`,
`objc2-core-audio`, `objc2-app-kit`, `objc2-metal`, `metal 0.29.0` and
`arboard 3.6.1` — the whole Apple side of the graph is present, and
`cargo build --release` linked it above.

⚠️ **The task brief's premise that Dimentio runs on wgpu/Metal is wrong.**
eframe 0.29.1's default features are `accesskit, default_fonts, glow, wayland,
web_screen_reader, x11`
([docs.rs](https://docs.rs/crate/eframe/0.29.1/features)) — **`glow` is the
renderer**, i.e. OpenGL through `glutin`. `wgpu` is in the lock file because
`eframe` depends on `egui-wgpu` unconditionally in its manifest; it is not
enabled. So egui's UI painting goes through macOS's **deprecated but functional**
OpenGL, and the model viewport is a software rasteriser regardless (D213).

- ✅ `rodio`'s `playback` feature is the one that pulls `cpal`, and cpal's macOS
  backend is CoreAudio — `coreaudio-rs` in the lock is that backend, and it
  compiled. The MPL-2.0 Symphonia exclusion (D227) costs nothing on macOS.
- ✅ Clipboard is `arboard`, which uses `objc2-app-kit`'s pasteboard natively.
- ✅ **No file-dialog crate** (`rfd` is absent). Dimentio takes its export root
  as an argv path, so there is no native-dialog surface to port.

### ✅ On macOS the Dolphin CLI tool is called `dolphin-tool`, not `DolphinTool`

`Source/Core/DolphinTool/CMakeLists.txt` names the target `dolphin-tool` and
sets `OUTPUT_NAME DolphinTool` **inside `if (WIN32)` only**
([source](https://raw.githubusercontent.com/dolphin-emu/dolphin/master/Source/Core/DolphinTool/CMakeLists.txt)).
Dolphin's own macOS build page gives the path as
`./Binaries/Dolphin.app/Contents/MacOS/dolphin-tool`
([Building on macOS](https://dolphin-emu-dolphin.mintlify.app/platforms/macos)).

✅ `bleck` is fine: `macos.py` lists `["dolphin-tool", "DolphinTool"]` in that
order. ⚠️ **`CLAUDE.md` says `DolphinTool` and is wrong** — see "Corrections
owed elsewhere". `docs-site/install/macos.md` was corrected in D274.

### ⛔ The distributed macOS build does not ship `dolphin-tool`

**Measured on the Mac** (D274): an Apple Silicon MacBook, Dolphin installed with
`brew install --cask dolphin`. `find /Applications/Dolphin.app -type f -perm
+111` returns eight executables — `Dolphin`, two Qt plugin dylibs, four
frameworks, and `Dolphin Updater`. No `dolphin-tool`, no `DolphinTool`.

Three lines agree: the artifact above; `BuildMacOSUniversalBinary.py`, which
bundles only `Dolphin.app`, `Dolphin Updater.app` and `unittests`; and
`Casks/d/dolphin.rb`, which declares one artifact and no `binary` stanza.

✅ **And the mechanism, so this is a cause rather than an observation.** The
bundle is assembled by `build_final_bundle` in `Source/Core/CMakeLists.txt`,
gated on `if (APPLE AND ENABLE_QT)`. It `DEPENDS dolphin-emu` — **not**
`dolphin-tool` — and copies in DolphinQt plus the updater.
`CMAKE_RUNTIME_OUTPUT_DIRECTORY` is `Binaries/` with no `APPLE` override, and
`dolphin-tool` is a plain non-bundle executable, so it lands at
**`Binaries/dolphin-tool`, a sibling of `Dolphin.app`**.

⚠️ **State it precisely.** `Source/Core/DolphinTool/CMakeLists.txt` has
`add_executable(dolphin-tool …)` with **no platform guard**, so the target is
built on macOS — its install rule (`if (NOT WIN32)`) just sends it to
`${CMAKE_INSTALL_BINDIR}`. ⛔ Not "it does not exist on macOS"; **"the
distributed build does not ship it"**.

⛔ **Dolphin's macOS docs page is wrong**, and that is why this took three
passes. It gives `./Binaries/Dolphin.app/Contents/MacOS/dolphin-tool`; the
official Building-for-macOS wiki never mentions `dolphin-tool`, and third-party
macOS CI collects it with `mv Binaries/dolphin-tool ../` — the sibling path.
That one line put the path into `macos.py`, into `docs-site/install/macos.md`,
into a user's `.env`, and finally into a `FileNotFoundError`. ✅
`formulae.brew.sh` 404s for both `dolphin` and `dolphin-tool`, so there is no
formula either — only the cask.

⛔ **So RVZ is unreadable with the tools this project already assumes.** The
`DOLPHIN_TOOL` hint now offers four routes, cheapest first: `nodtool`
(`cargo install --locked nodtool`, dual MIT/Apache-2.0, native arm64, ✅ v1.4.4
verified installing — ⚠️ always writes ISO regardless of the output name);
`npx dolphin-tool` (`@emmercm/dolphin-tool-darwin-arm64` v0.2606.1, ✅ verified
a Mach-O `cputype arm64` — ⚠️ its CI checks `--help` *before* stripping, and a
strip can invalidate the mandatory signature, so `Killed: 9` is plausible and
`codesign -s - <path>` repairs it); Dolphin's own GUI (*Convert File…*); and a
source build last. Then work from the `.iso`/`.wbfs`, which `wit` reads
natively — already the sharing recommendation (D24).

🔶 A source build is possible and Qt is genuinely avoidable
(`ENABLE_CLI_TOOL` is independent of `ENABLE_QT`), but `dolphin-tool` links
`discio` and `uicommon`, both of which `PUBLIC`-link `core`, so the emulator
core builds regardless. ⛔ No time estimate: nobody has measured one.

⚠️ **`DOLPHIN_BUNDLES` is still searched, deliberately.** A source build does
put `dolphin-tool` there. What changed is the *hint*, which used to promise the
distributed bundle had it.

🔶 **Teaching `bleck` to drive `nodtool` is a separate change** — different
invocation, different output rule, its own `ToolKey`. Naming it in a hint is not
the same as supporting it (D274).

### ✅ `bleck toolchain install` does not exist — and is no longer offered

`bleck --help` lists no `toolchain` command, and three profiles told the user to
run it anyway. **Fixed in D274**: `macos.py` now gives devkitPro's `.pkg`
installer plus `sudo dkp-pacman -S gamecube-dev`, `windows.py` gives devkitPro's
Windows installer, and `toolchain.py:100` quotes whichever platform hint applies
rather than repeating a recipe that can rot separately.

⚠️ **The count of four sites in earlier drafts of this page was wrong.**
`linux.py` had already been corrected and its `apt.devkitpro.org` recipe is
right *for Linux*; only three sites named the non-command. A test now pins that
no profile hint contains the string.

### ✅ Tool availability, from upstream download pages

| Tool | arm64 macOS? | Evidence |
|---|---|---|
| `wit` | **yes, from v3.05a** | [wit.wiimm.de/download.html](https://wit.wiimm.de/download.html): `wit-v3.05a-r8638-mac.tar.gz` — "Mac OS universal binaries (x86_64 and arm64)", 2022-08-27. v3.04a and earlier are x86_64 |
| `wstrt` (SZS toolset) | ⛔ **no** | [szs.wiimm.de/download.html](https://szs.wiimm.de/download.html): every macOS asset is `…-mac64.tar.gz`, "Mac OS x86_64 binaries". Latest v2.42a, 2024-03-26 |
| `devkitPPC`, natively on macOS | ⛔ **no** | "devkitPro provides precompiled versions … for the following Unix-like platforms: Linux (x86_64), macOS (x86_64)" ([switchbrew](https://switchbrew.org/wiki/Setting_up_Development_Environment)). `devkitPro/pacman`'s latest release is **v6.0.2, 2023-04-05**, one asset: `devkitpro-pacman-installer.pkg` |
| `devkitPPC`, in the arm64 Linux container | ✅ **yes** | `pkg.devkitpro.org/packages/linux/aarch64/dkp-linux.db.tar.gz` lists `devkitppc-gcc 16.1.0-1`, filename `…-aarch64.pkg.tar.zst` (D249). ⚠️ That URL 403s to a non-browser User-Agent and its directory has listings disabled, which is how D26 concluded the opposite |
| Dolphin | **yes, universal** | the `dolphin` cask installs `Dolphin.app` to `/Applications`, `depends_on macos >= 11`; Dolphin's build docs describe a universal x64+ARM bundle |
| a non-devkitPPC PowerPC cross-gcc | ⛔ **nothing packaged** | `formulae.brew.sh/api/formula/powerpc-elf-gcc.json` → 404, and no formula in homebrew-core has `powerpc` in its name. `messense/homebrew-macos-cross-toolchains` ships only `x86_64-`/`aarch64-unknown-linux-gnu` |

⚠️ **The repo's working notes still say "wit 3.01a".** That is the *Linux dev
host's* build. A Mac owner must take **3.05a** — it is the only one with an arm64
slice at all.

⛔ **D26's escape hatch does not exist on macOS**, and it no longer works
anywhere. Homebrew packages no PowerPC cross-gcc at all, and Debian's — which
`bleck` can still be pointed at — cannot currently produce a REL (D250). On a
Mac the two real options are **devkitPPC under Rosetta**, natively, or
**devkitPPC in the arm64 Linux container**, which is native arm64 and has no
expiry date.

### ✅ Apple Silicon will not run unsigned arm64 code, and Rosetta 2 has a date

- **Every native arm64 binary needs at least an ad-hoc signature.** A Mac with
  Apple silicon does not permit native arm64 code to execute unless a valid
  signature is attached; the failure is an immediate `SIGKILL`, not a dialog
  ([The Eclectic Light Company](https://eclecticlight.co/2020/08/22/apple-silicon-macs-will-require-signed-code/)).
  x86_64 binaries under Rosetta are exempt.
- **Rosetta 2 is being withdrawn.** Apple, at WWDC 2025: "we plan to make it
  available for the next two major macOS releases — through macOS 27 — as a
  general-purpose tool for Intel apps". After that only a narrow subset survives,
  for old games
  ([MacRumors](https://www.macrumors.com/2026/06/10/macos-golden-gate-last-to-support-intel-apps/)).

⚠️ **Read those two together.** `wstrt` and macOS devkitPPC are x86_64-only, so
the *native* code-mod path on a Mac has an announced expiry. Asset work does
not, and neither does the container — both of those tools have an arm64 Linux
build (D249, and `wstrt` compiled from source).

### ✅ The in-game rig needs Dolphin itself re-signed

`dolphin-memory-engine` 1.3.1 does publish a `macosx_11_0_arm64` wheel, so
`uv sync --extra dev` installs. But its README states macOS "requires a custom
code signature", and upstream's
[MacOS code signing](https://github.com/aldelaro5/dolphin-memory-engine#macos-code-signing)
section says the **Dolphin executable** must be signed with a self-signed
certificate and debugging entitlements before it can be attached to — and
re-signed after every Dolphin update.

⚠️ `scripts/ingame.py` is how nearly every in-game question in this project has
been settled. On macOS it needs a one-time Keychain certificate plus a re-sign
after each Dolphin upgrade, and the failure mode is "cannot attach", which reads
like a bug in the rig.

---

## 🔶 What is likely to break, and why it is unverified

### 🔶 `wit` v3.05a is reported to be killed on Apple Silicon until re-signed

[Wiimm/wiimms-iso-tools issue #18](https://github.com/Wiimm/wiimms-iso-tools/issues/18)
is **still open** (opened 2022-08-22, 27 comments). Users on 2024-12-01 and
2025-02-09 report `wit` from `wit-v3.05a-r8638-mac.tar.gz` dying with
`Killed: 9`, fixed by an ad-hoc re-sign:

```bash
sudo codesign --sign - --force \
  --preserve-metadata=entitlements,requirements,flags,runtime /usr/local/bin/wit
```

⚠️ Two details from the thread: it must be applied **after** `install.sh` and
`load-titles.sh` (both overwrite the signed binaries), and it must be applied to
**every** binary in the toolset's `bin/`, not just `wit`.

**Why this is 🔶 and not ✅:** these are third-party reports on an open issue,
and nobody here has run the binary. It fits the signing rule above exactly, which
is why it is the top-ranked blocker rather than a footnote.

✅ **`bleck` used to report this badly, and no longer does** (D274). `disc._run`
built its message from `stderr or stdout`; a `SIGKILL` produces neither, so the
user saw **`wit failed:`** and nothing else. A silent failure now stands in for
itself — "was killed before it could report anything (signal 9)" — and carries
`PlatformProfile.signing_remedy`, the `codesign --sign -` line. `bleck doctor`
reaches the same conclusion without a disc, by probing every tool.

🔶 Still unverified in the direction that matters: nobody has watched macOS kill
`wit`, or watched the re-sign fix it.

### 🔶 Whether the window opens and takes focus from a bare `cargo run`

A Cocoa application invoked as a bare executable from a terminal — rather than
through an `.app` bundle — runs as a background process and does not activate.
winit carries a pile of open issues in this area (e.g.
[#4260](https://github.com/rust-windowing/winit/issues/4260),
[#261](https://github.com/rust-windowing/winit/issues/261)). eframe does set an
activation policy, so this may simply work.

⛔ **CI cannot see this.** `cargo test` asserts on a `Vec<u8>` from the software
rasteriser and needs no display, which is exactly why it passes on a headless
runner (D213).

### 🔶 Whether a released binary is quarantined on download

- ✅ PyInstaller ad-hoc signs the executable and every collected binary by
  default ([feature notes](https://pyinstaller.org/en/stable/feature-notes.html)),
  so the arm64 signing rule is satisfied and the binary can execute at all.
- 🔶 **Gatekeeper is a second, separate gate.** A file downloaded by a *browser*
  carries `com.apple.quarantine`; Archive Utility propagates it to everything it
  extracts, while command-line `tar` does not, and `curl` never sets it in the
  first place.

So a user who runs `curl -L … | tar xz` should be unaffected, and a user who
clicks the release link in Safari and double-clicks the tarball probably meets
"cannot be opened because the developer cannot be verified".

⚠️ **Unverified in both directions**, and the second path is the common one.

### 🔶 Whether a `universal2` build is even possible here

PyInstaller accepts `target_arch` of `x86_64`, `arm64` or `universal2`, but
"even with a `universal2` python environment, some packages may end up providing
only single-arch binaries, making it impossible to create a functional
`universal2` frozen application" — it aborts with `IncompatibleBinaryArchError`.

The macOS runner logs `Python 3.13.14 (v3.13.14:fd17997c386, …)`, which is a
**python.org tagged build** and those are universal2 — so CI might manage it. A
developer using uv's managed Python would not: uv fetches
`…-aarch64-apple-darwin-install_only.tar.gz`, a thin arm64 build.

⛔ **Two builds are the safer answer than one fat one**, and today we do not even
have two: the matrix has one macOS entry and it is arm64. An Intel Mac owner gets
no artifact at all.

---

## The first hour on a Mac

Ordered by how many 🔶s each command retires per minute spent. **Capture output
to a file and read the file** — do not re-run to widen a query.

```bash
mkdir -p /tmp/mac-check
```

### 0. Establish the ground (2 min)

```bash
uname -m                       # expect arm64
sw_vers                        # macOS version; Rosetta's clock is macOS 27
xcode-select --install         # needed by anything that compiles
```

### 1. The thing CI cannot see (10 min)

⛔ The bundle question is **settled** (D274) — `dolphin-tool` is not in it, so
there is no RVZ path on macOS. Skip that check; run `uv run bleck doctor`
instead once step 2 has synced, which reports every tool at once and, unlike an
`ls`, also proves each one actually executes.

```bash
brew install --cask dolphin

# Does wit run, or is it killed?  Settles the whole disc path.
curl -LO https://wit.wiimm.de/download/wit-v3.05a-r8638-mac.tar.gz
tar xf wit-v3.05a-*.tar.gz && cd wit-v3.05a-*
file ./bin/wit                 # expect two slices, one arm64
./bin/wit version              # ⚠️ "Killed: 9" is the failure to look for
```

If it is killed, apply the ad-hoc signature and try again:

```bash
sudo codesign --sign - --force \
  --preserve-metadata=entitlements,requirements,flags,runtime ./bin/wit
./bin/wit version
```

⚠️ **Report which of those two happened.** Either way it turns the top-ranked
blocker into a fact, and the answer decides whether `macos.py`'s hint needs to
carry the `codesign` line.

### 2. The Python half (10 min)

```bash
brew install uv
git clone https://github.com/Coolroo/bleck && cd bleck
uv sync --extra dev
uv run pytest -q               > /tmp/mac-check/tests.txt 2>&1
uv run python scripts/lint.py --full >> /tmp/mac-check/tests.txt 2>&1
uv run bleck --help
```

Then the part no other platform can check — that the Finder-clutter filter is
real rather than only simulated (D30):

```bash
open work/extracted/eu0        # let Finder write a .DS_Store
uv run bleck build work/extracted/eu0 /tmp/mac-check/out.wbfs
# ⛔ a .DS_Store inside the built image is the bug this filter exists to stop
```

### 3. Dimentio, with a screen (10 min)

```bash
cargo run --release --manifest-path dimentio/Cargo.toml -- work/export
```

⚠️ **`--release` matters here.** The viewports rasterise on the CPU and a `dev`
build is 16-33x slower — the effect timeline plays at about 3 fps (D286).

Four questions, all invisible to CI, all answerable by looking:

1. Does a window **appear and take focus**, or does it open behind the terminal?
2. Do textures render, or is every one egui's red error triangle? (that is the
   `egui_extras` `file` feature failing — see `Cargo.toml`)
3. Does the Sounds tab **make a sound**? ⛔ Nobody on any platform has heard it.
4. Do the four tabs scroll comfortably at Retina scaling?

### 4. The code-mod path — budget the rest of the hour (25 min)

```bash
softwareupdate --install-rosetta --agree-to-license
# devkitPro: the .pkg installer, NOT the Debian script the docs currently give
open https://github.com/devkitPro/pacman/releases/latest
sudo dkp-pacman -S gamecube-dev
file /opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc   # expect x86_64 only
uv run bleck mod build coin-tick --mods-dir example-mods /tmp/mac-check/coin.wbfs
```

🔶 The open question is not whether it installs but whether an
**x86_64-under-Rosetta gcc produces a REL `pyelf2rel` accepts** and the game
runs. Nothing in the toolchain is architecture-sensitive in principle, and
D249 showed devkitPPC on aarch64 Linux produces bytes identical to devkitPPC on
x86_64 Windows — but nobody has run it under Rosetta.

⚠️ **Skip this step if the container is acceptable.** `container.md` gets to the
same `mod.rel` with no Rosetta and a shorter list of unknowns.

### 5. If time remains

```bash
# wstrt: x86_64 only, so this is a Rosetta test as much as a wstrt test
curl -LO https://szs.wiimm.de/download/szs-v2.42a-r8989-mac64.tar.gz

# the rig: needs Dolphin re-signed first (see above)
uv run python scripts/ingame.py nop --words 4 --mods-dir example-mods
```

---

## Install, once the checklist has been run

### Native on Apple Silicon

```bash
brew install uv
brew install --cask dolphin                 # universal bundle
curl -LO https://wit.wiimm.de/download/wit-v3.05a-r8638-mac.tar.gz
tar xf wit-v3.05a-*.tar.gz && cd wit-v3.05a-* && sudo ./install.sh
git clone https://github.com/Coolroo/bleck && cd bleck
uv sync --extra dev
```

⚠️ **Take wit 3.05a specifically.** Earlier macOS builds have no arm64 slice.
⚠️ **Re-sign after `install.sh`** if `wit version` is killed — see above.

### Under Rosetta 2, for code mods only

```bash
softwareupdate --install-rosetta --agree-to-license
```

Then devkitPPC via the **`.pkg` installer** from
<https://github.com/devkitPro/pacman/releases/latest>, then
`sudo dkp-pacman -S gamecube-dev`; and `wstrt` from the SZS toolset's
`…-mac64.tar.gz`.

⛔ **Do not use `apt.devkitpro.org/install-devkitpro-pacman` on macOS.** That is
the Debian/Ubuntu installer. Both this page and `docs-site/install/macos.md` gave
it for years.

### Where things land

| | |
|---|---|
| Homebrew prefix | `/opt/homebrew` on Apple Silicon, `/usr/local` on Intel. Both are searched |
| Dolphin | `/Applications/Dolphin.app/Contents/MacOS/` — `Dolphin` only. ⛔ `dolphin-tool` is **not** in the distributed bundle (D274); a source build puts it here |
| devkitPPC | `/opt/devkitpro/devkitPPC/bin` |
| `wit` / `wstrt` after `install.sh` | `/usr/local/bin` |
| **Dolphin's user directory** | `~/Library/Application Support/Dolphin/` — **not** `%APPDATA%`. The Gecko cheat lives at `…/GameSettings/R8PP01.ini` (D86 describes the Windows path) |

`.env` works exactly as on the other platforms; see `.env.example`.

```ini
BLECK_WIT=/usr/local/bin/wit
BLECK_DOLPHIN=/Applications/Dolphin.app/Contents/MacOS/Dolphin
BLECK_PPC_GCC=/opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc
```

⛔ **Do not set `BLECK_DOLPHIN_TOOL` to a path inside `Dolphin.app`.** Nothing
is there, and this page and `docs-site/install/macos.md` both told people to do
it — which is the setting that produced D274's `FileNotFoundError`. Set it only
if you built Dolphin yourself. `bleck doctor` now reports an override pointing
at a missing path as a misconfiguration, and names the variable.

### Finder clutter is filtered automatically

Browsing an extracted disc in Finder creates `.DS_Store`; non-native volumes
collect `._` AppleDouble sidecars. Without handling, that clutter would be staged
into a rebuilt image — files the real game never shipped.

`bleck` excludes `.DS_Store`, `.localized` and `._*` from staging and from mod
overlays, **on macOS only**: filtering them elsewhere would hide real mistakes.

⚠️ ✅ tested, 🔶 never exercised by an actual Finder. `tests/test_platform.py`
asserts the profile filters those names, and D30's end-to-end check used a
*simulated* macOS staging run from Linux. Step 2 of the checklist is what turns
that into ✅.

---

## The gaps in `bleck/platforms/macos.py`

⛔ **Not changed by this document, deliberately** — editing it untested would put
unverifiable guesses into shipping code. Each row says what to change and what
must be true first.

| Field | Status | What a Mac would settle |
|---|---|---|
| `HOMEBREW_PREFIXES` | ✅ correct | Documented Apple behaviour; `find_tool` calls `.expanduser()`, so `~`-relative entries are live |
| `DOLPHIN_BUNDLES` | ✅ **settled, and the hint is fixed** | `dolphin-tool` is not in the distributed bundle (D274). The directory is still searched, because a source build puts it there; the hint now says the distribution does not ship it and gives Dolphin's GUI conversion and `.iso`/`.wbfs` instead |
| `DOLPHIN_TOOL.names` | ✅ correct order | `dolphin-tool` first is right; `DolphinTool` is Windows-only naming and harmless as a fallback |
| `WIT.hint` | ⚠️ **stale** | It says "download the macOS build"; it should name **v3.05a**, the only one with an arm64 slice. ✅ The `codesign` half is handled elsewhere now — `signing_remedy` supplies it whenever a tool dies on a signal, so a hint that omits it no longer leaves the user with `wit failed:` and no text (D274) |
| `WSTRT.hint` | ✅ accurate | Correctly says x86_64/Rosetta. ⚠️ Should gain the macOS-27 Rosetta deadline |
| `PPC_GCC.hint` | ✅ **fixed** | It named `bleck toolchain install`, which is not a subcommand. It now gives the `.pkg` URL and `dkp-pacman -S gamecube-dev` (D274). `windows.py` and `toolchain.py:100` were fixed with it; `linux.py` was already correct |
| `PPC_GCC.directories` | ✅ correct | `/opt/devkitpro/devkitPPC/bin` is where the pkg installs |
| `ignored_filenames` / `ignored_prefixes` | ✅ as designed | ⛔ Never exercised by a real Finder |
| `strip_readonly_on_delete` | ✅ correctly `False` | POSIX unlink needs no bit cleared |

✅ **Half of the missing field now exists.** `PlatformProfile.signing_remedy`
carries the `codesign --sign -` command, empty on Linux and Windows, and
`bleck doctor` prints it whenever a tool dies on a signal (D274) — data, as this
paragraph asked for, not an `if platform.system()`.

🔶 **The other half is still absent:** nothing describes a tool that must be run
under Rosetta. Add it when something actually depends on knowing.

---

## Packaging, signing and CI

### What exists

✅ `build.yml`'s matrix already carries `macos-latest` → `bleck-macos-arm64.tar.gz`,
built by `bleck.spec`, smoke-tested, tarred **inside the platform job** so the
exec bit survives `upload-artifact`.

✅ `bleck.spec` sets `target_arch=None` and `codesign_identity=None`, so the
build is single-arch-for-the-host and ad-hoc signed. On an arm64 runner that is
an arm64 binary, which is the right default.

✅ Public repositories get standard GitHub-hosted runners free and unlimited, so
**the macOS job costs nothing today**. ⚠️ If this repo ever goes private, macOS
minutes bill at roughly **10×** Linux — a 1-minute job draws 10 minutes of
allowance. Budget from the multiplier, not the wall clock.

### What is missing

| Gap | Cost |
|---|---|
| ⛔ No Intel-Mac artifact | `macos-latest` is arm64. An Intel Mac owner has no download |
| 🔶 No `universal2` build | Would need a universal2 interpreter *and* every dependency universal2. `pyyaml` and `pydantic` both ship compiled wheels, so this is a real risk of `IncompatibleBinaryArchError`, not a formality |
| 🔶 No Gatekeeper story | Ad-hoc signing lets the binary *execute*; it does not clear quarantine |
| ⛔ No notarization | Needs an Apple Developer Program membership at **$99/year**, which is what gates Developer ID certificates and notarization, plus `codesign` and `notarytool` in a CI job with the certificate in a secret |
| ⛔ Dimentio ships no artifact at all | `dimentio.yml` builds and tests; it uploads nothing, on any platform |

**Cheapest honest fix, and the one to prefer:** document `curl` + `tar` as the
macOS install path in `docs-site/`, since neither sets nor propagates
`com.apple.quarantine`. That costs nothing and removes the common failure. Adding
a second matrix entry for Intel is the next cheapest. Notarization is a
$99/year commitment with a certificate to rotate, and is not worth it until
somebody actually hits the Gatekeeper wall.

⚠️ **Do not add `target_arch="universal2"` to `bleck.spec` speculatively.** It
would change every platform's build path to satisfy a Mac case nobody has
reproduced.

---

## Corrections owed elsewhere

Found while writing this; **not changed here**, because they are outside this
document's scope.

| Where | What is wrong |
|---|---|
| `CLAUDE.md`, cross-platform rules | "`DolphinTool` inside `Dolphin.app` on macOS" — the macOS binary is `dolphin-tool`, and ⛔ it is not in the bundle at all (D274) |
| ~~`docs-site/install/macos.md`, the `DolphinTool` path and the Debian installer~~ | ✅ **fixed in D274** |
| ~~`macos.py`, `windows.py`, `toolchain.py` pointing at `bleck toolchain install`~~ | ✅ **fixed in D274.** ⚠️ The count was wrong: `linux.py` was already correct, so it was three sites, not four |
| `docs-site/install/macos.md` | "There is no Homebrew formula" for wit is still true, but it does not name v3.05a as the only arm64 build |
| Working notes | "wit 3.01a" is the Linux host's version; a Mac needs 3.05a |

---

## What could not be determined without a Mac

Listed so the next person does not re-derive them from the same sources.

1. Whether `wit` v3.05a actually runs on Apple Silicon unmodified.
2. ~~Whether `dolphin-tool` is in the released `Dolphin.app`.~~ ✅ **Settled
   2026-08-03: it is not** (D274). The distributed bundle's eight executables do
   not include it, so RVZ is unreadable on macOS. `nodtool` is the candidate
   replacement and is not built yet.
3. Whether devkitPPC under Rosetta 2 produces a REL that loads and runs. ⚠️
   Partly retired: D249 shows aarch64-Linux devkitPPC produces bytes identical
   to x86_64-Windows devkitPPC, so "the host architecture changes the output" is
   no longer the worry. "Loads and runs" is still open on every host.
4. Whether Dimentio's window opens, focuses, renders textures, and plays audio.
5. Whether the release tarball trips Gatekeeper in practice.
6. Whether a `universal2` PyInstaller build is achievable with our dependency
   set.
7. Whether the Finder-clutter filter works against a real Finder.
8. Whether `scripts/ingame.py` can attach after Dolphin is re-signed.
9. Whether Dolphin's macOS Gecko/cheat configuration behaves as the Windows path
   in D86 does.

⚠️ **Item 1 gates everything else, and is one command.** It is step 1 of the
checklist for that reason. Item 2 was the other such question and is now
answered.
