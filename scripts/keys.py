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


class _MouseInput(ctypes.Structure):
    """Unused, but it is the largest arm of the union and so sets its size.

    ⚠️ Do not replace this with a hand-counted padding array. The first version
    did, guessed 24 bytes from `KEYBDINPUT`, and produced a 32-byte `INPUT`
    where Windows wants 40 on x64 — `SendInput` then rejected every call with
    `ERROR_INVALID_PARAMETER` (87). That looked exactly like the OS refusing to
    inject input for security reasons, and very nearly got recorded as one.
    Declaring the real fields lets ctypes size the union on any architecture.
    """

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyboardInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


#: What `SendInput` expects `cbSize` to be: 40 on x64, 28 on x86.
EXPECTED_INPUT_SIZE = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28

if IS_WINDOWS and ctypes.sizeof(_Input) != EXPECTED_INPUT_SIZE:
    # Loud, at import, because the symptom of getting this wrong is
    # `SendInput` failing in a way that reads as a security refusal.
    raise RuntimeError(
        f"INPUT is {ctypes.sizeof(_Input)} bytes, but SendInput wants "
        f"{EXPECTED_INPUT_SIZE}; the struct definitions above are wrong"
    )


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
    """Bring a process's window to the front, and confirm it got there.

    Injected input goes to whatever is focused, so this is not cosmetic: sending
    keys to an unfocused Dolphin types them into whatever *is* focused, which on
    a developer's machine is usually an editor or a terminal.

    ⚠️ `SetForegroundWindow` alone does not work from a background script.
    Windows only grants it to a process that already owns the foreground or
    handled the most recent input, specifically to stop programs stealing focus
    — measured here: it returned false every time and no key was ever sent.

    The sanctioned way round it is `AttachThreadInput`: attach to the thread
    that currently owns the foreground, which makes the two share an input
    queue and puts this process inside the permitted set for as long as the
    attachment lasts. Detached again immediately, because leaving two threads
    sharing an input queue is a good way to deadlock both.

    Returns whether the window is *actually* frontmost afterwards, not whether
    the call claimed success — the two differ, and only the first one is safe
    to send keystrokes on.
    """
    if not IS_WINDOWS:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    for hwnd in windows_for_pid(pid):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE, in case it is minimised

        current = kernel32.GetCurrentThreadId()
        foreground = user32.GetForegroundWindow()
        owner = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

        attached = bool(owner) and owner != current
        if attached:
            attached = bool(user32.AttachThreadInput(current, owner, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(current, owner, False)

        if user32.GetForegroundWindow() == hwnd:
            return True
    return False


def is_foreground(pid: int) -> bool:
    if not IS_WINDOWS:
        return False
    return ctypes.windll.user32.GetForegroundWindow() in windows_for_pid(pid)


def wait_until_foreground(pid: int, seconds: float = 30.0) -> bool:
    """Wait for a window of `pid` to become frontmost, however it gets there.

    ⚠️ Deliberately cooperative. Windows blocks a background process from
    stealing focus, and `AttachThreadInput` did not get around it here —
    measured: the call is accepted and the foreground never changes.

    It *can* be forced, by setting `SPI_SETFOREGROUNDLOCKTIMEOUT` to zero and
    turning off the protection system-wide. That is not done, and should not
    be: quietly disabling an operating system's defence against focus theft is
    a bigger imposition than synthesising a keystroke, and it would persist
    beyond this process. One click is cheaper than that trade.
    """
    if not IS_WINDOWS:
        return False
    deadline = time.time() + seconds
    while time.time() < deadline:
        if is_foreground(pid):
            return True
        time.sleep(0.5)
    return False


def press(button: str, hold: float = 0.35, gap: float = 0.9) -> PressResult:
    """Press and release one button or one combination, then pause.

    `a` presses a single button; `1+2` holds both together and releases both.
    A combination has to be *simultaneous* — the whole point of the feature is
    that a mod tests `(held & mask) == mask` in one frame, so pressing the
    buttons in sequence exercises nothing.

    `hold` is generous on purpose. The game samples once per frame, so a press
    shorter than a frame or two can be missed entirely — and a missed press is
    indistinguishable from the feature not working when results are read back.
    """
    if not IS_WINDOWS:
        return PressResult(button, False, "keystroke injection is Windows-only")

    names = [part.strip().lower() for part in button.split("+") if part.strip()]
    scans = []
    for name in names:
        scan = SCAN_CODES.get(name)
        if scan is None:
            valid = ", ".join(sorted(SCAN_CODES))
            return PressResult(button, False, f"no key mapped for {name!r} ({valid})")
        scans.append(scan)
    if not scans:
        return PressResult(button, False, "nothing to press")

    # Down in order, up in reverse, so the combination is genuinely held at
    # once rather than being a fast sequence of individual presses.
    for scan in scans:
        if not _send(scan, keyup=False):
            for done in reversed(scans):
                _send(done, keyup=True)
            return PressResult(button, False, "SendInput refused the key-down")
    time.sleep(hold)
    for scan in reversed(scans):
        if not _send(scan, keyup=True):
            return PressResult(button, False, "SendInput refused the key-up")
    time.sleep(gap)
    return PressResult(button, True)
