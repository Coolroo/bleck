"""Linux specifics."""

from __future__ import annotations

from .base import (
    DOLPHIN,
    DOLPHIN_TOOL,
    PPC_GCC,
    WIT,
    WSTRT,
    PlatformProfile,
    ToolLocation,
)

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
        WSTRT: ToolLocation(
            # install.sh puts binaries in /usr/local/bin; the tarball also works
            # unpacked in place.
            names=["wstrt"],
            directories=[
                "/usr/local/bin",
                "/usr/bin",
                "~/tools/szs/bin",
                "~/szs/bin",
            ],
            hint=(
                "wstrt ships with Wiimms SZS Toolset — a separate package from "
                "wit, with no distro package:\n"
                "  wget https://szs.wiimm.de/download/szs-v2.42a-r8989-x86_64.tar.gz\n"
                "  tar xf szs-*.tar.gz && cd szs-* && sudo ./install.sh\n"
                "  or unpack it anywhere and set BLECK_WSTRT to the wstrt binary"
            ),
        ),
        PPC_GCC: ToolLocation(
            # devkitPPC's `powerpc-eabi-gcc` first: same ABI as the game.
            # Debian's works too but needs different flags (see toolchain.py).
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
