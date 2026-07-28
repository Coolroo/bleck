"""The project's config file: `bleck.yml`.

Distinct from `env.py`, and the split is deliberate. `.env` holds **machine**
settings — where `wit` lives on this laptop — and is gitignored. `bleck.yml`
holds **project** settings: things every build of this repo should agree on, and
which belong in version control so the next person gets them too.

The first thing it carries is named button combinations, so a mod says
`start_map` rather than a magic number, and the number is written once. Nothing
about the file is combo-specific though: `constants` is already there as the
general case, and the schema is versioned so it can grow.

Found by walking up from the working directory, exactly as `.env` is, so it
works from anywhere inside a checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bleck.common.errors import BleckError

#: Committed, unlike `.env` — these are decisions about the project, not about
#: the machine it happens to be built on.
CONFIG_NAME = "bleck.yml"

#: Bumped when a change would make an older `bleck` misread a newer file.
SCHEMA_VERSION = 1


class ConfigError(BleckError):
    """`bleck.yml` is malformed, or names something that does not exist."""


# --- buttons ---------------------------------------------------------------

#: Wii remote button masks.
#:
#: ✅ **The four face bits are confirmed** (D67). Holding A+B+1+2 in the running
#: game reports `0x0F00`, exactly the OR of the four values below, so those four
#: bits are the four buttons.
#:
#: 🔶 **Which bit is which within that group is not confirmed.** Holding all
#: four at once gives the same total whatever the assignment, so a combo of two
#: of them is right either way -- but a combo mixing one of them with `plus`
#: would not be. Settled by pressing them one at a time.
#:
#: 🔶 **`plus`, `minus`, `home` and the d-pad are entirely unverified.** They are
#: the published Revolution SDK values and nothing in `spm-headers` defines
#: them -- `wii/kpad.h` documents `buttonsHeld` and stops there.
#:
#: ⚠️ Bit 31 of `buttonsHeld` is **not** a button. It flips between frames while
#: the controller is untouched, so a combo must test `(held & mask) == mask` and
#: never compare the whole word for equality. See D67.
BUTTON_MASKS = {
    "left": 0x0001,
    "right": 0x0002,
    "down": 0x0004,
    "up": 0x0008,
    "plus": 0x0010,
    "2": 0x0100,
    "1": 0x0200,
    "b": 0x0400,
    "a": 0x0800,
    "minus": 0x1000,
    "home": 0x8000,
}

#: Nunchuk buttons are not in `KPADStatus.buttonsHeld` at all — they live in the
#: `extension` union, which is a different field with a different layout. Named
#: here only so asking for one gets an explanation instead of "unknown button".
EXTENSION_BUTTONS = frozenset({"c", "z"})

#: A single button fires during ordinary play. Two is the smallest combination
#: that a player will not hit by accident while walking around.
MIN_COMBO_BUTTONS = 2


@dataclass(frozen=True)
class Combo:
    """A named button combination, resolved to the mask a mod tests against."""

    name: str
    buttons: tuple[str, ...]
    mask: int

    @property
    def describe(self) -> str:
        return f"{self.name} = {' + '.join(self.buttons)} (0x{self.mask:04X})"


@dataclass(frozen=True)
class Constant:
    """A named value injected at compile time.

    Deliberately stringly-typed for now. Every use so far is a map name or a
    similar identifier, and inventing a type system for a file with three
    entries in it would be inventing work.
    """

    name: str
    value: str


@dataclass(frozen=True)
class Config:
    """Everything `bleck.yml` declares.

    Returned as a value with lookup methods rather than as dictionaries: the
    project forbids returning `dict` (pylint C9001) precisely so that a
    signature says what comes back.
    """

    combos: list[Combo] = field(default_factory=list)
    constants: list[Constant] = field(default_factory=list)
    source: Path | None = None
    """Which file this came from. None when no file was found."""

    @property
    def is_empty(self) -> bool:
        return not self.combos and not self.constants

    @property
    def where(self) -> str:
        """What to name in an error message."""
        return str(self.source) if self.source else CONFIG_NAME

    def combo(self, name: str) -> Combo | None:
        return next((c for c in self.combos if c.name == name), None)

    def constant(self, name: str) -> Constant | None:
        return next((c for c in self.constants if c.name == name), None)

    @property
    def combo_names(self) -> list[str]:
        return [c.name for c in self.combos]

    @property
    def constant_names(self) -> list[str]:
        return [c.name for c in self.constants]


# --- reading ---------------------------------------------------------------


def find(start: Path | None = None) -> Path | None:
    """The nearest `bleck.yml`, walking up from `start`.

    Same search as `.env`, for the same reason: a command run from three
    directories deep inside a checkout should behave the same as one run at the
    top.
    """
    origin = start or Path.cwd()
    for directory in (origin, *origin.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def _button_mask(name: str, combo_name: str, where: str) -> int:
    key = str(name).strip().lower()
    if key in BUTTON_MASKS:
        return BUTTON_MASKS[key]
    if key in EXTENSION_BUTTONS:
        raise ConfigError(
            f"{where}: combo {combo_name!r} uses the nunchuk button {name!r}, "
            f"which is not supported.\n"
            f"  Nunchuk buttons are not in `buttonsHeld` -- they live in the "
            f"controller's extension data, which bleck does not read yet."
        )
    valid = ", ".join(sorted(BUTTON_MASKS))
    raise ConfigError(
        f"{where}: combo {combo_name!r} names an unknown button {name!r}.\n"
        f"  Valid buttons: {valid}"
    )


def _parse_combo(name: str, raw: object, where: str) -> Combo:
    """One `combos:` entry: a list of buttons, or an object that may relax the
    two-button minimum."""
    allow_single = False
    if isinstance(raw, dict):
        allow_single = bool(raw.get("allow_single"))
        raw = raw.get("buttons")

    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            f"{where}: combo {name!r} must be a list of button names, "
            f"e.g. [1, 2].\n"
            f"  To allow a single button, write "
            f"{{buttons: [home], allow_single: true}}"
        )

    # YAML reads bare `1` and `2` as integers; they are button names here.
    buttons = tuple(str(entry).strip().lower() for entry in raw)

    if len(set(buttons)) != len(buttons):
        raise ConfigError(f"{where}: combo {name!r} lists the same button twice")

    if len(buttons) < MIN_COMBO_BUTTONS and not allow_single:
        raise ConfigError(
            f"{where}: combo {name!r} has one button, which would fire during "
            f"ordinary play.\n"
            f"  Use at least {MIN_COMBO_BUTTONS}, or write "
            f"{{buttons: {list(buttons)}, allow_single: true}} if you mean it."
        )

    mask = 0
    for button in buttons:
        mask |= _button_mask(button, name, where)
    return Combo(name=name, buttons=buttons, mask=mask)


def _require_mapping(raw: object, key: str, where: str) -> dict:  # pylint: disable=container-return
    """A top-level section, which must be `name: value` pairs if present.

    Returns a plain dict because it is an intermediate step in parsing, not a
    return value anyone outside this module sees -- the parsed result is
    `Config`, which names everything.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{where}: '{key}' must be a mapping of name to value, not "
            f"{type(raw).__name__}"
        )
    return raw


def parse(text: str, where: str = CONFIG_NAME, source: Path | None = None) -> Config:
    """Read config text. Separate from `load` so it is testable without a file."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{where} is not valid YAML:\n  {exc}") from exc

    if raw is None:
        return Config(source=source)
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{where}: expected a mapping at the top level, not {type(raw).__name__}"
        )

    version = raw.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ConfigError(
            f"{where}: schema version {version!r} is not supported.\n"
            f"  This bleck understands version {SCHEMA_VERSION}."
        )

    combos = [
        _parse_combo(str(name), body, where)
        for name, body in _require_mapping(raw.get("combos"), "combos", where).items()
    ]
    constants = [
        Constant(name=str(name), value=str(value))
        for name, value in _require_mapping(
            raw.get("constants"), "constants", where
        ).items()
    ]
    return Config(combos=combos, constants=constants, source=source)


def load(start: Path | None = None) -> Config:
    """The nearest `bleck.yml`, parsed. An absent file is not an error.

    A project with no config is the normal case — combos are opt-in, and every
    other feature works without them. Referring to a combo that is not declared
    is what fails, and it fails where the reference is.
    """
    path = find(start)
    if path is None:
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    return parse(text, where=str(path), source=path)
