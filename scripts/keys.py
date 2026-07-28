"""Synthesising keystrokes into Dolphin, on Windows.

⚠️ **Needs an unlocked session with Dolphin in the foreground**, so the
unattended limit in D48 stands. `SendInput` injects below DirectInput's polling
and does reach Dolphin, unlike the `SendKeys`/`PostMessage` D48 ruled out.

Dolphin's default Wii remote mapping puts each button on its own letter, so the
button names used elsewhere in this toolkit map straight through.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

#: Hardware scan codes, not virtual key codes: DirectInput reports *physical*
#: keys, and `KEYEVENTF_SCANCODE` takes the keyboard layout out of it.
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

    ⚠️ Do not replace with hand-counted padding. Getting `INPUT`'s size wrong
    makes `SendInput` reject every call with `ERROR_INVALID_PARAMETER` (87),
    which reads as the OS refusing injection for security reasons. Declaring
    the real fields lets ctypes size the union on any architecture.
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
    # ctypes reads `_fields_` at class creation: a declaration, not shared state.
    _fields_ = [  # noqa: RUF012
        ("mi", _MouseInput),
        ("ki", _KeyboardInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


#: What `SendInput` expects `cbSize` to be: 40 on x64, 28 on x86.
EXPECTED_INPUT_SIZE = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28

if IS_WINDOWS and ctypes.sizeof(_Input) != EXPECTED_INPUT_SIZE:
    # Loud, at import: the symptom otherwise reads as a security refusal.
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

    Not cosmetic: injected input goes to whatever is focused, so keys sent to
    an unfocused Dolphin land in an editor or terminal instead.

    ⚠️ `SetForegroundWindow` alone fails from a background script. The
    sanctioned way round it is `AttachThreadInput` on the thread that owns the
    foreground, detached immediately after -- two threads left sharing an input
    queue can deadlock.

    Returns whether the window is *actually* frontmost, not whether the call
    claimed success; only the first is safe to send keystrokes on.
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

    ⚠️ Deliberately cooperative: waits for a human click. Forcing focus needs
    `SPI_SETFOREGROUNDLOCKTIMEOUT` set to zero, which disables the protection
    system-wide and outlasts this process. One click is cheaper.
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

    `a` presses one button; `1+2` holds both together. A combination must be
    *simultaneous*: a mod tests `(held & mask) == mask` within one frame.

    ⚠️ `hold` is generous on purpose. The game samples once per frame, and a
    missed press is indistinguishable from the feature not working.
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

    # Down in order, up in reverse, so a combination is genuinely held at once
    # rather than being a fast sequence of individual presses.
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
