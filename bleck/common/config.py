"""The project's config file: `bleck.yml`.

Distinct from `env.py`: `.env` holds machine settings and is gitignored, while
`bleck.yml` holds committed project settings — named button combos, constants.
Found by walking up from the working directory, exactly as `.env` is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bleck.common.errors import BleckError

#: Committed, unlike `.env`.
CONFIG_NAME = "bleck.yml"

#: Bumped when a change would make an older `bleck` misread a newer file.
SCHEMA_VERSION = 1


class ConfigError(BleckError):
    """`bleck.yml` is malformed, or names something that does not exist."""


# --- buttons ---------------------------------------------------------------

#: Wii remote button masks. ✅ `a`, `b`, `1`, `2` verified in-game (D68);
#: 🔶 the rest are published SDK values, unverified.
#:
#: ⚠️ Bit 31 of `buttonsHeld` is not a button — it flips between frames, so a
#: combo must test `(held & mask) == mask`, never whole-word equality (D67).
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

#: Nunchuk buttons live in the `extension` union, not `buttonsHeld`. Named here
#: so asking for one gets an explanation instead of "unknown button".
EXTENSION_BUTTONS = frozenset({"c", "z"})

#: A single button fires during ordinary play.
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
    """A named value injected at compile time. Stringly-typed for now."""

    name: str
    value: str


@dataclass(frozen=True)
class Config:
    """Everything `bleck.yml` declares."""

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
    """The nearest `bleck.yml`, walking up from `start`. Same search as `.env`."""
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

    A plain dict because it is an intermediate parsing step; the parsed result
    is `Config`.
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
    """The nearest `bleck.yml`, parsed. An absent file is not an error — an
    undeclared combo fails where it is referenced instead.
    """
    path = find(start)
    if path is None:
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    return parse(text, where=str(path), source=path)
