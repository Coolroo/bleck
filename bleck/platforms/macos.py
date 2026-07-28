"""macOS specifics: Dolphin's tools live inside `Dolphin.app/Contents/MacOS/`,
Homebrew's prefix depends on the CPU, and Finder clutter (`.DS_Store`, `._`
sidecars) must never reach a rebuilt image.
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
                "DolphinTool ships inside Dolphin.app "
                "(/Applications/Dolphin.app/Contents/MacOS/DolphinTool).\n"
                "  Install with `brew install --cask dolphin`, or set "
                "BLECK_DOLPHIN_TOOL to its full path"
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
                "install devkitPPC:\n"
                "  bleck toolchain install\n"
                "  or set BLECK_PPC_GCC to powerpc-eabi-gcc"
            ),
        ),
    },
    ignored_filenames=frozenset({".DS_Store", ".localized"}),
    ignored_prefixes=frozenset({"._"}),
)
