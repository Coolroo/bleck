"""The `evt` bytecode format: opcodes and operand encoding.

Scripts are plain `s32` arrays. Each instruction is one header word followed by
its argument words::

    header = (argument_count << 16) | opcode

Arguments are `s32`, and **the numeric range of an argument encodes its storage
class**: near -30000000 is local work slot 0, near -240000000 is a fixed-point
float, and anything outside every declared range is a literal. Hence the
`encode_*` helpers — a raw integer in a variable's window is read as that
variable. See `docs/scripting.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

#: Fixed-point scale for float operands: ~3 decimal places of precision.
FLOAT_SCALE = 1024.0


class Opcode(IntEnum):
    """Every `evt` instruction, from `spm/evtmgr_cmd.h`."""

    NEXT = 0x00
    END_SCRIPT = 0x01
    END_EVT = 0x02
    LBL = 0x03
    GOTO = 0x04
    DO = 0x05
    WHILE = 0x06
    DO_BREAK = 0x07
    DO_CONTINUE = 0x08
    WAIT_FRM = 0x09
    WAIT_MSEC = 0x0A
    HALT = 0x0B
    IF_STR_EQUAL = 0x0C
    IF_STR_NOT_EQUAL = 0x0D
    IF_STR_SMALL = 0x0E
    IF_STR_LARGE = 0x0F
    IF_STR_SMALL_EQUAL = 0x10
    IF_STR_LARGE_EQUAL = 0x11
    IFF_EQUAL = 0x12
    IFF_NOT_EQUAL = 0x13
    IFF_SMALL = 0x14
    IFF_LARGE = 0x15
    IFF_SMALL_EQUAL = 0x16
    IFF_LARGE_EQUAL = 0x17
    IF_EQUAL = 0x18
    IF_NOT_EQUAL = 0x19
    IF_SMALL = 0x1A
    IF_LARGE = 0x1B
    IF_SMALL_EQUAL = 0x1C
    IF_LARGE_EQUAL = 0x1D
    IF_FLAG = 0x1E
    IF_NOT_FLAG = 0x1F
    ELSE = 0x20
    END_IF = 0x21
    SWITCH = 0x22
    SWITCHI = 0x23
    CASE_EQUAL = 0x24
    CASE_NOT_EQUAL = 0x25
    CASE_SMALL = 0x26
    CASE_LARGE = 0x27
    CASE_SMALL_EQUAL = 0x28
    CASE_LARGE_EQUAL = 0x29
    CASE_ETC = 0x2A
    CASE_OR = 0x2B
    CASE_AND = 0x2C
    CASE_FLAG = 0x2D
    CASE_END = 0x2E
    CASE_BETWEEN = 0x2F
    SWITCH_BREAK = 0x30
    END_SWITCH = 0x31
    SET = 0x32
    SETI = 0x33
    SETF = 0x34
    ADD = 0x35
    SUB = 0x36
    MUL = 0x37
    DIV = 0x38
    MOD = 0x39
    ADDF = 0x3A
    SUBF = 0x3B
    MULF = 0x3C
    DIVF = 0x3D
    SET_READ = 0x3E
    READ = 0x3F
    READ2 = 0x40
    READ3 = 0x41
    READ4 = 0x42
    READ_N = 0x43
    SET_READF = 0x44
    READF = 0x45
    READF2 = 0x46
    READF3 = 0x47
    READF4 = 0x48
    READF_N = 0x49
    CLAMP_INT = 0x4A
    SET_USER_WRK = 0x4B
    SET_USER_FLG = 0x4C
    ALLOC_USER_WRK = 0x4D
    AND = 0x4E
    ANDI = 0x4F
    OR = 0x50
    ORI = 0x51
    SET_FRAME_FROM_MSEC = 0x52
    SET_MSEC_FROM_FRAME = 0x53
    SET_RAM = 0x54
    SET_RAMF = 0x55
    GET_RAM = 0x56
    GET_RAMF = 0x57
    SETR = 0x58
    SETRF = 0x59
    GETR = 0x5A
    GETRF = 0x5B
    USER_FUNC = 0x5C
    RUN_EVT = 0x5D
    RUN_EVT_ID = 0x5E
    RUN_CHILD_EVT = 0x5F
    DELETE_EVT = 0x60
    RESTART_EVT = 0x61
    SET_PRI = 0x62
    SET_SPD = 0x63
    SET_TYPE = 0x64
    STOP_ALL = 0x65
    START_ALL = 0x66
    STOP_OTHER = 0x67
    START_OTHER = 0x68
    STOP_ID = 0x69
    START_ID = 0x6A
    CHK_EVT = 0x6B
    INLINE_EVT = 0x6C
    INLINE_EVT_ID = 0x6D
    END_INLINE = 0x6E
    BROTHER_EVT = 0x6F
    BROTHER_EVT_ID = 0x70
    END_BROTHER = 0x71
    DEBUG_PUT_MSG = 0x72
    DEBUG_MSG_CLEAR = 0x73
    DEBUG_PUT_REG = 0x74
    DEBUG_NAME = 0x75
    DEBUG_REM = 0x76
    DEBUG_BP = 0x77


#: How many argument words each opcode takes, from the `EVT_HELPER_CMD(n, op)`
#: macros in `spm-headers/mod/evt_cmd.h`. The game's own scripts were assembled
#: with those macros, so this is the arity a vanilla instruction has.
#: `USER_FUNC` is absent because it is variadic: one word for the function
#: pointer plus one per argument.
ARGUMENT_COUNTS = {
    Opcode.NEXT: 0,
    Opcode.END_SCRIPT: 0,
    Opcode.END_EVT: 0,
    Opcode.LBL: 1,
    Opcode.GOTO: 1,
    Opcode.DO: 1,
    Opcode.WHILE: 0,
    Opcode.DO_BREAK: 0,
    Opcode.DO_CONTINUE: 0,
    Opcode.WAIT_FRM: 1,
    Opcode.WAIT_MSEC: 1,
    Opcode.HALT: 1,
    Opcode.IF_STR_EQUAL: 2,
    Opcode.IF_STR_NOT_EQUAL: 2,
    Opcode.IF_STR_SMALL: 2,
    Opcode.IF_STR_LARGE: 2,
    Opcode.IF_STR_SMALL_EQUAL: 2,
    Opcode.IF_STR_LARGE_EQUAL: 2,
    Opcode.IFF_EQUAL: 2,
    Opcode.IFF_NOT_EQUAL: 2,
    Opcode.IFF_SMALL: 2,
    Opcode.IFF_LARGE: 2,
    Opcode.IFF_SMALL_EQUAL: 2,
    Opcode.IFF_LARGE_EQUAL: 2,
    Opcode.IF_EQUAL: 2,
    Opcode.IF_NOT_EQUAL: 2,
    Opcode.IF_SMALL: 2,
    Opcode.IF_LARGE: 2,
    Opcode.IF_SMALL_EQUAL: 2,
    Opcode.IF_LARGE_EQUAL: 2,
    Opcode.IF_FLAG: 2,
    Opcode.IF_NOT_FLAG: 2,
    Opcode.ELSE: 0,
    Opcode.END_IF: 0,
    Opcode.SWITCH: 1,
    Opcode.SWITCHI: 1,
    Opcode.CASE_EQUAL: 1,
    Opcode.CASE_NOT_EQUAL: 1,
    Opcode.CASE_SMALL: 1,
    Opcode.CASE_LARGE: 1,
    Opcode.CASE_SMALL_EQUAL: 1,
    Opcode.CASE_LARGE_EQUAL: 1,
    Opcode.CASE_ETC: 0,
    Opcode.CASE_OR: 1,
    Opcode.CASE_AND: 1,
    Opcode.CASE_FLAG: 1,
    Opcode.CASE_END: 0,
    Opcode.CASE_BETWEEN: 2,
    Opcode.SWITCH_BREAK: 0,
    Opcode.END_SWITCH: 0,
    Opcode.SET: 2,
    Opcode.SETI: 2,
    Opcode.SETF: 2,
    Opcode.ADD: 2,
    Opcode.SUB: 2,
    Opcode.MUL: 2,
    Opcode.DIV: 2,
    Opcode.MOD: 2,
    Opcode.ADDF: 2,
    Opcode.SUBF: 2,
    Opcode.MULF: 2,
    Opcode.DIVF: 2,
    Opcode.SET_READ: 1,
    Opcode.READ: 1,
    Opcode.READ2: 2,
    Opcode.READ3: 3,
    Opcode.READ4: 4,
    Opcode.READ_N: 2,
    Opcode.SET_READF: 1,
    Opcode.READF: 1,
    Opcode.READF2: 2,
    Opcode.READF3: 3,
    Opcode.READF4: 4,
    Opcode.READF_N: 2,
    Opcode.CLAMP_INT: 3,
    Opcode.SET_USER_WRK: 1,
    Opcode.SET_USER_FLG: 1,
    Opcode.ALLOC_USER_WRK: 1,
    Opcode.AND: 3,
    Opcode.ANDI: 3,
    Opcode.OR: 3,
    Opcode.ORI: 3,
    Opcode.SET_FRAME_FROM_MSEC: 2,
    Opcode.SET_MSEC_FROM_FRAME: 2,
    Opcode.SET_RAM: 2,
    Opcode.SET_RAMF: 2,
    Opcode.GET_RAM: 2,
    Opcode.GET_RAMF: 2,
    Opcode.SETR: 2,
    Opcode.SETRF: 2,
    Opcode.GETR: 2,
    Opcode.GETRF: 2,
    Opcode.RUN_EVT: 1,
    Opcode.RUN_EVT_ID: 2,
    Opcode.RUN_CHILD_EVT: 1,
    Opcode.DELETE_EVT: 1,
    Opcode.RESTART_EVT: 1,
    Opcode.SET_PRI: 1,
    Opcode.SET_SPD: 1,
    Opcode.SET_TYPE: 1,
    Opcode.STOP_ALL: 1,
    Opcode.START_ALL: 1,
    Opcode.STOP_OTHER: 1,
    Opcode.START_OTHER: 1,
    Opcode.STOP_ID: 1,
    Opcode.START_ID: 1,
    Opcode.CHK_EVT: 2,
    Opcode.INLINE_EVT: 0,
    Opcode.INLINE_EVT_ID: 1,
    Opcode.END_INLINE: 0,
    Opcode.BROTHER_EVT: 0,
    Opcode.BROTHER_EVT_ID: 1,
    Opcode.END_BROTHER: 0,
    Opcode.DEBUG_PUT_MSG: 1,
    Opcode.DEBUG_MSG_CLEAR: 0,
    Opcode.DEBUG_PUT_REG: 1,
    Opcode.DEBUG_NAME: 1,
    Opcode.DEBUG_REM: 1,
    Opcode.DEBUG_BP: 0,
}


def opcode_named(name: str) -> Opcode | None:
    """Look an opcode up by name, case-insensitively. None if there is none."""
    try:
        return Opcode[name.strip().upper()]
    except KeyError:
        return None


def argument_count(opcode: Opcode) -> int | None:
    """How many argument words `opcode` takes, or None when it is variadic."""
    return ARGUMENT_COUNTS.get(opcode)


@dataclass(frozen=True)
class StorageClass:
    """One of `evt`'s variable families, and the numeric window that encodes it.

    The VM has no operand-type field; it tests which window an argument falls
    into, so `base` is the encoding rather than a convention.
    """

    name: str
    base: int
    """Subtracted from the index to produce the encoded value."""

    limit: int
    """How many slots the VM actually provides, or 0 when unbounded."""

    description: str = ""

    def encode(self, index: int) -> int:
        if self.limit and not 0 <= index < self.limit:
            raise ValueError(
                f"{self.name}({index}) is out of range; "
                f"the game provides {self.name}(0)..{self.name}({self.limit - 1})"
            )
        return index - self.base


#: Per-script scratch. 16 slots, cleared when the script ends.
LW = StorageClass("LW", 30000000, 16, "local work: per-script scratch integers")

#: Shared across every running script, and not saved.
GW = StorageClass("GW", 50000000, 32, "global work: shared between scripts")

#: Per-script boolean flags.
LF = StorageClass("LF", 70000000, 96, "local flags: per-script booleans")

#: Shared boolean flags, not saved.
GF = StorageClass("GF", 90000000, 96, "global flags: shared booleans")

#: Persisted in the save file, and shared with the game's own progression —
#: writing one can corrupt a playthrough. See `docs/scripting.md`.
LSW = StorageClass("LSW", 150000000, 0, "saved local work (persists in saves)")
GSW = StorageClass("GSW", 170000000, 0, "saved global work (persists in saves)")
LSWF = StorageClass("LSWF", 110000000, 0, "saved local flags (persists in saves)")
GSWF = StorageClass("GSWF", 130000000, 0, "saved global flags (persists in saves)")

FLOAT_BASE = 240000000
ADDR_BASE = 270000000

STORAGE_CLASSES = [LW, GW, LF, GF, LSW, GSW, LSWF, GSWF]


def encode_float(value: float) -> int:
    """Encode a float operand as `value * 1024` biased into the float window."""
    scaled = int(value * FLOAT_SCALE)
    encoded = scaled - FLOAT_BASE
    # Outside this window the operand decodes as a pointer (below) or a plain
    # literal (above), so the magnitude is bounded here.
    if not -290000000 < encoded <= -220000000:
        raise ValueError(
            f"float {value} cannot be represented as an evt operand "
            f"(magnitude must stay under about 48000)"
        )
    return encoded


def instruction_header(opcode: Opcode, argument_count: int) -> int:
    """Build the header word that introduces every instruction."""
    return (argument_count << 16) | int(opcode)


def is_literal(encoded: int) -> bool:
    """Whether an encoded operand would be read as a plain number.

    A literal that lands inside a storage window is silently read as a variable
    reference instead, which is near-undebuggable from in-game behaviour.
    """
    return encoded > -20000000 or encoded <= -290000000
