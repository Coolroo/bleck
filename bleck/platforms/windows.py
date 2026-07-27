"""Windows specifics."""

from __future__ import annotations

from .base import DOLPHIN, DOLPHIN_TOOL, PPC_GCC, WIT, PlatformProfile, ToolLocation

# Dolphin ships as a portable folder rather than an installer, so there is no
# canonical install path — these are the conventional ones. A user who unzipped
# it somewhere else sets BLECK_DOLPHIN instead.
DOLPHIN_DIRECTORIES = [
    r"C:\Program Files\Dolphin",
    r"C:\Program Files (x86)\Dolphin",
    r"C:\Program Files\Dolphin-x64",
]

PROFILE = PlatformProfile(
    name="Windows",
    venv_bin="Scripts",
    tools={
        WIT: ToolLocation(
            names=["wit.exe", "wit"],
            directories=[
                r"C:\Program Files\Wiimm\wit\bin",
                r"C:\Program Files (x86)\Wiimm\wit\bin",
                r"C:\wit\bin",
            ],
            hint=(
                "install Wiimms ISO Tools from https://wit.wiimm.de/ and add it "
                "to PATH, or set BLECK_WIT to wit.exe"
            ),
        ),
        DOLPHIN_TOOL: ToolLocation(
            # Windows ships it beside the emulator, with different casing.
            names=["DolphinTool.exe", "dolphin-tool.exe", "DolphinTool"],
            directories=DOLPHIN_DIRECTORIES,
            hint=(
                "DolphinTool.exe ships with Dolphin; add its folder to PATH or "
                "set BLECK_DOLPHIN_TOOL to its full path"
            ),
        ),
        DOLPHIN: ToolLocation(
            names=["Dolphin.exe", "dolphin"],
            directories=DOLPHIN_DIRECTORIES,
            hint=(
                "Dolphin.exe is the emulator, beside DolphinTool.exe; add its "
                "folder to PATH or set BLECK_DOLPHIN to its full path.\n"
                "  Get it from https://dolphin-emu.org/download/ — not winget, "
                "which ships the 2016 release"
            ),
        ),
        PPC_GCC: ToolLocation(
            # devkitPPC is the only realistic source on Windows; there is no
            # distro package to fall back to.
            names=["powerpc-eabi-gcc.exe", "powerpc-eabi-gcc"],
            directories=[
                r"C:\devkitPro\devkitPPC\bin",
                r"D:\devkitPro\devkitPPC\bin",
            ],
            hint=(
                "install devkitPPC, then reopen your shell:\n"
                "  bleck toolchain install\n"
                "  or set BLECK_PPC_GCC to powerpc-eabi-gcc.exe"
            ),
        ),
    },
    # Windows refuses to delete read-only files.
    strip_readonly_on_delete=True,
)
