"""Linux specifics."""

from __future__ import annotations

from .base import DOLPHIN_TOOL, WIT, PlatformProfile, ToolLocation

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
    },
)
