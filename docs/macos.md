# macOS Setup — status, blockers, and what a Mac owner must verify

macOS is a supported target (D30) and has **never been run on a Mac** (D239).
This page is written from our own source, our own CI logs, and upstream
documents. Every claim carries a confidence marker, and **almost nothing here is
✅** — reserve that for what was read out of this repository, a CI run, or an
authoritative upstream file.

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
2. ⚠️ **devkitPPC has no arm64 macOS build**, and Rosetta 2 is scheduled to go
   away (✅ both, below). Every code mod goes through it.
3. ⚠️ **`wstrt` is x86_64-only with no universal build at all** (✅) — same
   Rosetta dependency, no upstream plan visible.
4. ⚠️ **`scripts/ingame.py` needs Dolphin re-signed with debugging
   entitlements** on macOS, and re-signed after every Dolphin update (✅
   upstream README).
5. 🔶 **A downloaded release binary may be quarantined**, depending on how the
   user unpacks it. No signing or notarization exists today.
6. ⚠️ **CI publishes no Intel-Mac artifact** (✅) — `macos-latest` is arm64 only.

### ⚠️ Blockers 1–3 have a partial answer: [`container.md`](./container.md)

An arm64 Linux devcontainer sidesteps Rosetta entirely. Debian's
`gcc-powerpc-linux-gnu` **14.2.0** is a plain apt package on arm64 (✅ measured),
so devkitPPC is not needed, and **`wit` builds from source and runs on arm64**
(✅ measured) — no re-signing, because it is not a macOS binary.

⛔ **It does not close blocker 2.** The container gets as far as a linked
PowerPC ELF and then fails to convert it to a REL, in three named ways. Read
`container.md` before budgeting against it.

⛔ **Dolphin and Dimentio stay native**, so blockers 4 and 5 are untouched.

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
order. ⚠️ **`CLAUDE.md` and `docs-site/install/macos.md` both say `DolphinTool`
and are wrong** — see "Corrections owed elsewhere".

### ✅ `bleck toolchain install` does not exist

All three platform profiles tell the user to run it when the cross-compiler is
missing (`macos.py:86`, `linux.py:63`, `windows.py:73`, and
`toolchain.py:100`), and `bleck --help` lists no `toolchain` command.

⚠️ **This hurts macOS most.** Linux's hint offers
`sudo apt install gcc-powerpc-linux-gnu` as a second option and Windows names a
real installer; the macOS hint offers **only** the command that does not exist,
then `BLECK_PPC_GCC`.

### ✅ Tool availability, from upstream download pages

| Tool | arm64 macOS? | Evidence |
|---|---|---|
| `wit` | **yes, from v3.05a** | [wit.wiimm.de/download.html](https://wit.wiimm.de/download.html): `wit-v3.05a-r8638-mac.tar.gz` — "Mac OS universal binaries (x86_64 and arm64)", 2022-08-27. v3.04a and earlier are x86_64 |
| `wstrt` (SZS toolset) | ⛔ **no** | [szs.wiimm.de/download.html](https://szs.wiimm.de/download.html): every macOS asset is `…-mac64.tar.gz`, "Mac OS x86_64 binaries". Latest v2.42a, 2024-03-26 |
| `devkitPPC` | ⛔ **no** | "devkitPro provides precompiled versions … for the following Unix-like platforms: Linux (x86_64), macOS (x86_64)" ([switchbrew](https://switchbrew.org/wiki/Setting_up_Development_Environment)). `devkitPro/pacman`'s latest release is **v6.0.2, 2023-04-05**, one asset: `devkitpro-pacman-installer.pkg` |
| Dolphin | **yes, universal** | the `dolphin` cask installs `Dolphin.app` to `/Applications`, `depends_on macos >= 11`; Dolphin's build docs describe a universal x64+ARM bundle |
| a non-devkitPPC PowerPC cross-gcc | ⛔ **nothing packaged** | `formulae.brew.sh/api/formula/powerpc-elf-gcc.json` → 404, and no formula in homebrew-core has `powerpc` in its name. `messense/homebrew-macos-cross-toolchains` ships only `x86_64-`/`aarch64-unknown-linux-gnu` |

⚠️ **The repo's working notes still say "wit 3.01a".** That is the *Linux dev
host's* build. A Mac owner must take **3.05a** — it is the only one with an arm64
slice at all.

⛔ **D26's escape hatch does not exist on macOS.** On Debian, `bleck` can fall
back to `gcc-powerpc-linux-gnu` with `-fno-pic -fno-PIE`. Homebrew has no
equivalent, so **devkitPPC is the only packaged path**, and it is x86_64.

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

⚠️ **Read those two together.** `wstrt` and `devkitPPC` are x86_64-only, so the
entire code-mod path on a Mac has an announced expiry unless devkitPro ships
arm64 packages. Asset work does not.

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

⚠️ **`bleck` will report this badly.** `disc._run` raises
`DiscError(f"{name} failed:\n{detail}")` from `stderr or stdout`. A `SIGKILL`
produces neither, so the user sees **`wit failed:`** and nothing else.

### 🔶 Whether `dolphin-tool` is inside the shipped `Dolphin.app` at all

`bleck` looks for it in `/Applications/Dolphin.app/Contents/MacOS`. Dolphin's own
docs give that path — but from the **build tree** (`./Binaries/Dolphin.app/…`),
and `Source/Core/DolphinQt/CMakeLists.txt` has no rule copying `dolphin-tool`
into the bundle. The release `.dmg` may ship `Dolphin.app` alone.

⛔ If it is absent, **RVZ is unreadable on macOS** — `wit` cannot read RVZ and
`dolphin-tool` is the only thing that can. The workaround is to convert on
another machine and ship `.wbfs`, which is already the recommendation (D24).

**One `ls` settles it.** It is first on the checklist below for that reason.

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

### 1. The two things CI cannot see (10 min)

```bash
# Does the shipped Dolphin bundle contain the CLI tool?  Settles RVZ support.
brew install --cask dolphin
ls -l /Applications/Dolphin.app/Contents/MacOS/ > /tmp/mac-check/dolphin.txt 2>&1
file /Applications/Dolphin.app/Contents/MacOS/Dolphin >> /tmp/mac-check/dolphin.txt

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
cargo run --manifest-path dimentio/Cargo.toml -- work/export
```

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
runs. Nothing in the toolchain is architecture-sensitive in principle; nobody has
shown it.

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
| Dolphin | `/Applications/Dolphin.app/Contents/MacOS/` — `Dolphin` and (🔶) `dolphin-tool` |
| devkitPPC | `/opt/devkitpro/devkitPPC/bin` |
| `wit` / `wstrt` after `install.sh` | `/usr/local/bin` |
| **Dolphin's user directory** | `~/Library/Application Support/Dolphin/` — **not** `%APPDATA%`. The Gecko cheat lives at `…/GameSettings/R8PP01.ini` (D86 describes the Windows path) |

`.env` works exactly as on the other platforms; see `.env.example`.

```ini
BLECK_WIT=/usr/local/bin/wit
BLECK_DOLPHIN=/Applications/Dolphin.app/Contents/MacOS/Dolphin
BLECK_DOLPHIN_TOOL=/Applications/Dolphin.app/Contents/MacOS/dolphin-tool
BLECK_PPC_GCC=/opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc
```

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
| `DOLPHIN_BUNDLES` | 🔶 | `ls /Applications/Dolphin.app/Contents/MacOS/`. If `dolphin-tool` is absent from the release bundle, the `DOLPHIN_TOOL` hint must stop implying it is there and say "build Dolphin, or convert RVZ elsewhere" |
| `DOLPHIN_TOOL.names` | ✅ correct order | `dolphin-tool` first is right; `DolphinTool` is Windows-only naming and harmless as a fallback |
| `WIT.hint` | ⚠️ **stale and incomplete** | It says "download the macOS build". It should name **v3.05a** (the only one with arm64) and, if the checklist reproduces `Killed: 9`, carry the `codesign --sign -` line. A hint that does not mention the failure leaves the user with `wit failed:` and no text |
| `WSTRT.hint` | ✅ accurate | Correctly says x86_64/Rosetta. ⚠️ Should gain the macOS-27 Rosetta deadline |
| `PPC_GCC.hint` | ⛔ **names a command that does not exist** | `bleck toolchain install` is not a `bleck` subcommand. Replace with the `.pkg` URL and `dkp-pacman -S gamecube-dev`. Same fix needed in `linux.py`, `windows.py` and `toolchain.py:100` |
| `PPC_GCC.directories` | ✅ correct | `/opt/devkitpro/devkitPPC/bin` is where the pkg installs |
| `ignored_filenames` / `ignored_prefixes` | ✅ as designed | ⛔ Never exercised by a real Finder |
| `strip_readonly_on_delete` | ✅ correctly `False` | POSIX unlink needs no bit cleared |

🔶 **One field the profile does not have and may need:** nothing describes a tool
that must be run under Rosetta, or one whose signature must be repaired. If the
`wit` re-sign turns out to be required, that is data — a `needs_adhoc_signature`
flag or a richer hint — not an `if platform.system()` anywhere.

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
| `CLAUDE.md`, cross-platform rules | "`DolphinTool` inside `Dolphin.app` on macOS" — the macOS binary is `dolphin-tool` |
| `docs-site/install/macos.md` | Same `DolphinTool` path; and it gives `apt.devkitpro.org/install-devkitpro-pacman`, the **Debian** installer, as the macOS devkitPPC step |
| `docs-site/install/macos.md` | "There is no Homebrew formula" for wit is still true, but it does not name v3.05a as the only arm64 build |
| `macos.py`, `linux.py`, `windows.py`, `toolchain.py` | All four point at `bleck toolchain install`, which is not a command |
| Working notes | "wit 3.01a" is the Linux host's version; a Mac needs 3.05a |

---

## What could not be determined without a Mac

Listed so the next person does not re-derive them from the same sources.

1. Whether `wit` v3.05a actually runs on Apple Silicon unmodified.
2. Whether `dolphin-tool` is in the released `Dolphin.app`.
3. Whether devkitPPC under Rosetta 2 produces a REL that loads and runs.
4. Whether Dimentio's window opens, focuses, renders textures, and plays audio.
5. Whether the release tarball trips Gatekeeper in practice.
6. Whether a `universal2` PyInstaller build is achievable with our dependency
   set.
7. Whether the Finder-clutter filter works against a real Finder.
8. Whether `scripts/ingame.py` can attach after Dolphin is re-signed.
9. Whether Dolphin's macOS Gecko/cheat configuration behaves as the Windows path
   in D86 does.

⚠️ **Items 1 and 2 are two commands and gate everything else.** They are steps 0
and 1 of the checklist for that reason.
