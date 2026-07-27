"""Windows specifics."""

from __future__ import annotations

from .base import DOLPHIN_TOOL, WIT, PlatformProfile, ToolLocation

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
            directories=[
                r"C:\Program Files\Dolphin",
                r"C:\Program Files (x86)\Dolphin",
                r"C:\Program Files\Dolphin-x64",
            ],
            hint=(
                "DolphinTool.exe ships with Dolphin; add its folder to PATH or "
                "set BLECK_DOLPHIN_TOOL to its full path"
            ),
        ),
    },
    # Windows refuses to delete read-only files.
    strip_readonly_on_delete=True,
)
