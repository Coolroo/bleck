"""Linux specifics."""

from __future__ import annotations

from .base import DOLPHIN, DOLPHIN_TOOL, PPC_GCC, WIT, PlatformProfile, ToolLocation

PROFILE = PlatformProfile(
    name="Linux",
    venv_bin="bin",
    tools={
        WIT: ToolLocation(
            names=["wit"],
            directories=["/usr/bin", "/usr/local/bin"],
            hint=(
                "install Wiimms ISO Tools:  sudo apt install wit\n"
                "  or set BLECK_WIT to its full path"
            ),
        ),
        DOLPHIN_TOOL: ToolLocation(
            names=["dolphin-tool"],
            # Debian installs here, which is not always on PATH.
            directories=["/usr/games", "/usr/local/games", "/usr/bin"],
            hint=(
                "install Dolphin for dolphin-tool:  sudo apt install dolphin-emu\n"
                "  or set BLECK_DOLPHIN_TOOL to its full path"
            ),
        ),
        DOLPHIN: ToolLocation(
            # `dolphin` alone is KDE's file manager, not the emulator — never
            # search for it by that name here.
            names=["dolphin-emu", "dolphin-emu-qt2", "dolphin-emu-wx"],
            directories=["/usr/games", "/usr/local/games", "/usr/bin"],
            hint=(
                "install the Dolphin emulator:  sudo apt install dolphin-emu\n"
                "  or set BLECK_DOLPHIN to its full path"
            ),
        ),
        PPC_GCC: ToolLocation(
            # devkitPPC's `powerpc-eabi-gcc` first: it targets the same ABI the
            # game was built with. Debian's `powerpc-linux-gnu-gcc` also works
            # but needs different flags — see `bleck.backends.toolchain`.
            names=["powerpc-eabi-gcc", "powerpc-linux-gnu-gcc"],
            directories=["/opt/devkitpro/devkitPPC/bin", "/usr/bin"],
            hint=(
                "install a PowerPC cross-compiler:\n"
                "  bleck toolchain install            (devkitPPC, recommended)\n"
                "  sudo apt install gcc-powerpc-linux-gnu   (also works)\n"
                "  or set BLECK_PPC_GCC to its full path"
            ),
        ),
    },
)
