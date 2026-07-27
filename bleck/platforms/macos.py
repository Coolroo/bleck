"""macOS specifics.

Three things differ from Linux in ways that matter:

1. **Dolphin is an application bundle**, so its tools live inside
   `Dolphin.app/Contents/MacOS/` rather than on PATH.
2. **Homebrew's prefix depends on the CPU** — `/opt/homebrew` on Apple Silicon,
   `/usr/local` on Intel. Both are listed; only one will exist.
3. **Finder creates `.DS_Store` files** in any directory a user browses, and
   non-native volumes collect `._` AppleDouble sidecars. Browsing an extracted
   disc would otherwise put that clutter onto a rebuilt image.
"""

from __future__ import annotations

from .base import DOLPHIN, DOLPHIN_TOOL, PPC_GCC, WIT, PlatformProfile, ToolLocation

# Apple Silicon first: /usr/local also exists on those machines but is not
# where Homebrew installs.
HOMEBREW_PREFIXES = ["/opt/homebrew", "/usr/local"]

DOLPHIN_BUNDLES = [
    "/Applications/Dolphin.app/Contents/MacOS",
    "~/Applications/Dolphin.app/Contents/MacOS",
]

PROFILE = PlatformProfile(
    name="macOS",
    venv_bin="bin",
    tools={
        WIT: ToolLocation(
            names=["wit"],
            directories=[f"{prefix}/bin" for prefix in HOMEBREW_PREFIXES],
            hint=(
                "Wiimms ISO Tools has no Homebrew formula — download the macOS "
                "build from https://wit.wiimm.de/ and put wit on PATH, or set "
                "BLECK_WIT to its full path"
            ),
        ),
        DOLPHIN_TOOL: ToolLocation(
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
        DOLPHIN: ToolLocation(
            # The bundle's executable is `Dolphin`; `dolphin-emu` is what a
            # Homebrew-built binary is called.
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
        PPC_GCC: ToolLocation(
            # Homebrew has no PowerPC cross-compiler cask; devkitPPC installs to
            # the same /opt/devkitpro prefix it uses on Linux.
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
