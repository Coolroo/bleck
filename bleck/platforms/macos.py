"""macOS specifics: the emulator lives inside `Dolphin.app/Contents/MacOS/`,
Homebrew's prefix depends on the CPU, Finder clutter (`.DS_Store`, `._`
sidecars) must never reach a rebuilt image, and an unsigned arm64 binary is
killed rather than run.

⛔ The bundle contains the emulator and **not** `dolphin-tool` (D274). The
directory is still searched, because a source build does put it there.
"""

from __future__ import annotations

from .base import PlatformProfile, ToolKey, ToolLocation

# Apple Silicon first; /usr/local exists there too but is not Homebrew's.
HOMEBREW_PREFIXES = ["/opt/homebrew", "/usr/local"]

DOLPHIN_BUNDLES = [
    "/Applications/Dolphin.app/Contents/MacOS",
    "~/Applications/Dolphin.app/Contents/MacOS",
]

PROFILE = PlatformProfile(
    name="macOS",
    venv_bin="bin",
    tools={
        ToolKey.WIT: ToolLocation(
            names=["wit"],
            directories=[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
            hint=(
                "Wiimms ISO Tools has no Homebrew formula — download the macOS "
                "build from https://wit.wiimm.de/ and put wit on PATH, or set "
                "BLECK_WIT to its full path"
            ),
        ),
        ToolKey.DOLPHIN_TOOL: ToolLocation(
            # The bundle ships DolphinTool without an extension.
            names=["dolphin-tool", "DolphinTool"],
            directories=[
                *DOLPHIN_BUNDLES,
                *[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
            ],
            hint=(
                "the distributed Dolphin.app does not ship dolphin-tool: it is "
                "built as Binaries/dolphin-tool, a sibling of the app, and is "
                "never copied inside it (D274).\n"
                "  RVZ is the only format that needs it. To convert one, "
                "outside bleck:\n"
                "    cargo install --locked nodtool && nodtool convert "
                "game.rvz game.iso\n"
                "      (native arm64; always writes ISO whatever you name the "
                "output)\n"
                "    or npx dolphin-tool convert -f iso -i game.rvz -o "
                "game.iso\n"
                "    or right-click the game in Dolphin and choose Convert "
                "File...\n"
                "  Then work from the .iso or .wbfs, which wit reads natively.\n"
                "  BLECK_DOLPHIN_TOOL needs a real dolphin-tool: npx installs "
                "one for arm64,\n"
                "  and a source build produces one. If it is killed on launch, "
                "sign it:  codesign -s - <path>"
            ),
        ),
        ToolKey.DOLPHIN: ToolLocation(
            # `Dolphin` in the bundle; `dolphin-emu` when Homebrew-built.
            names=["Dolphin", "dolphin-emu"],
            directories=[
                *DOLPHIN_BUNDLES,
                *[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
            ],
            hint=(
                "the Dolphin emulator lives inside Dolphin.app "
                "(/Applications/Dolphin.app/Contents/MacOS/Dolphin).\n"
                "  Install with `brew install --cask dolphin`, or set "
                "BLECK_DOLPHIN to its full path"
            ),
        ),
        ToolKey.WSTRT: ToolLocation(
            # No Homebrew formula; the prefixes are where hand-installs land.
            names=["wstrt"],
            directories=[
                "/usr/local/bin",
                *[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
                "~/tools/szs/bin",
            ],
            hint=(
                "wstrt ships with Wiimms SZS Toolset — a separate package from "
                "wit, with no Homebrew formula:\n"
                "  curl -LO https://szs.wiimm.de/download/szs-v2.42a-r8989-mac64.tar.gz\n"
                "  tar xf szs-*.tar.gz && cd szs-* && sudo ./install.sh\n"
                "  or unpack it anywhere and set BLECK_WSTRT to the wstrt binary\n"
                "  Note: the macOS build is x86_64, so Apple Silicon runs it "
                "under Rosetta 2"
            ),
        ),
        ToolKey.PPC_GCC: ToolLocation(
            # No Homebrew cask; devkitPPC uses the same prefix as on Linux.
            names=["powerpc-eabi-gcc"],
            directories=[
                "/opt/devkitpro/devkitPPC/bin",
                *[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
            ],
            hint=(
                "install devkitPPC from devkitPro's macOS installer:\n"
                "  open https://github.com/devkitPro/pacman/releases/latest\n"
                "  run devkitpro-pacman-installer.pkg, then:\n"
                "  sudo dkp-pacman -S gamecube-dev\n"
                "  or set BLECK_PPC_GCC to powerpc-eabi-gcc.\n"
                "  The build is x86_64 only, so Apple Silicon needs Rosetta 2:  "
                "softwareupdate --install-rosetta"
            ),
        ),
    },
    ignored_filenames=frozenset({".DS_Store", ".localized"}),
    ignored_prefixes=frozenset({"._"}),
    signing_remedy=(
        "codesign --sign - --force "
        "--preserve-metadata=entitlements,requirements,flags,runtime {path}"
    ),
)
