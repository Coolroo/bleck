"""Synthesising keystrokes into Dolphin, on Windows.

⚠️ **This is not what D48 ruled out, and the distinction is the whole point.**
D48 measured `SendKeys` and `PostMessage`, which post to a window's *message
queue*. Dolphin reads DirectInput, which polls device state and never looks at
the queue, so those were invisible to it — correctly measured, correctly
recorded.

`SendInput` is a different mechanism: it injects at the driver level, beneath
DirectInput's polling, so a focused window does see it. D48 already said as
much ("driver-level injection still needs the session to be unlocked and
Dolphin focused") — the blocker was a locked machine, not the technique.

So: **this needs an unlocked session with Dolphin in the foreground.** The
unattended limit in D48 stands. What it buys is that a button-triggered feature
can be tested by a script instead of by a person pressing keys on cue, which is
the difference between a repeatable check and a favour.

Dolphin's default Wii remote mapping puts each button on its own letter — `A`
on A, `B` on B, `1` on 1, `2` on 2 — so the button names used elsewhere in this
toolkit map straight through.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

#: Hardware scan codes, not virtual key codes.
#:
#: DirectInput reports *physical* keys, so it keys off the scan code. Sending a
#: virtual key and letting Windows derive the scan code works for ordinary
#: applications and is unreliable here; `KEYEVENTF_SCANCODE` says "this is the
#: physical key" and removes the layout from the equation entirely.
SCAN_CODES = {
    "a": 0x1E,
    "b": 0x30,
    "1": 0x02,
    "2": 0x03,
    "plus": 0x0D,  # '=' / '+' on a US layout
    "minus": 0x0C,
    "up": 0x48,
    "down": 0x50,
    "left": 0x4B,
    "right": 0x4D,
}

_INPUT_KEYBOARD = 1
_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeyboardInput), ("padding", ctypes.c_ubyte * 24)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


@dataclass(frozen=True)
class PressResult:
    """What happened when a key was sent."""

    button: str
    sent: bool
    problem: str = ""


def _send(scan: int, keyup: bool) -> bool:
    user32 = ctypes.windll.user32
    flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if keyup else 0)
    event = _Input(
        type=_INPUT_KEYBOARD,
        union=_InputUnion(
            ki=_KeyboardInput(
                wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None
            )
        ),
    )
    written = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input))
    return written == 1


def windows_for_pid(pid: int) -> list[int]:
    """Visible top-level window handles belonging to a process."""
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    found: list[int] = []

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


def focus(pid: int) -> bool:
    """Bring a process's window to the front.

    Injected input goes to whatever is focused, so this is not cosmetic: sending
    keys to an unfocused Dolphin types them into whatever *is* focused, which on
    a developer's machine is usually an editor.
    """
    if not IS_WINDOWS:
        return False
    user32 = ctypes.windll.user32
    for hwnd in windows_for_pid(pid):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE, in case it is minimised
        if user32.SetForegroundWindow(hwnd):
            return True
    return False


def press(
    button: str, hold: float = 0.35, gap: float = 0.9
) -> PressResult:
    """Press and release one button, then pause.

    `hold` is generous on purpose. The game samples once per frame and the probe
    records a value only when it changes, so a press shorter than a frame or two
    can be missed entirely — and a missing press is indistinguishable from a
    wrong mapping when the results are read back.
    """
    if not IS_WINDOWS:
        return PressResult(button, False, "keystroke injection is Windows-only")
    scan = SCAN_CODES.get(button.lower())
    if scan is None:
        valid = ", ".join(sorted(SCAN_CODES))
        return PressResult(button, False, f"no key mapped for {button!r} ({valid})")

    if not _send(scan, keyup=False):
        return PressResult(button, False, "SendInput refused the key-down")
    time.sleep(hold)
    if not _send(scan, keyup=True):
        return PressResult(button, False, "SendInput refused the key-up")
    time.sleep(gap)
    return PressResult(button, True)
