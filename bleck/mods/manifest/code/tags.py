"""Tags: declaring in the source what `mod.json` would otherwise have to repeat.

A hook names two things -- a game function and one of the mod's own functions --
and `mod.json` could only ever name the second one as a string. So the manifest
had to be kept in step with the code by hand, and a renamed C function became a
link error rather than anything a reader could see coming.

A tag puts the declaration where the thing it describes lives::

    BLECK_HOOK(mapDataPtr, before)
    void watchMapData(void *work) { ... }

    #[map("he1_04")]
    script onLineland { ... }

⚠️ **`BLECK_HOOK` is a real macro**, from the `bleck.h` written beside the
generated sources, and it expands to nothing. That is the point: a typo is a C
compile error rather than a tag that silently does not apply. The scanner here
reads the same text the compiler does.

⛔ **Tags never override `mod.json` and `mod.json` never overrides tags.** A
conflict is refused, naming both sites. Silent precedence is exactly the failure
this repo keeps rediscovering -- a declaration that parses, is ignored, and
reports success (D126, four times).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.code.hooks import build_hook
from bleck.mods.manifest.code.specs import CodeSpec, ComboBinding, FunctionHook, MapHook

#: `BLECK_HOOK(function, mode)`, as the C preprocessor would see it.
HOOK_MACRO = re.compile(r"\bBLECK_HOOK\s*\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)")

#: The definition a tag attaches to: the last identifier before the argument
#: list. Matches `void f(`, `static u32 *f(`, `int f (` -- but not a call,
#: because a call is not at the start of a line at file scope.
DEFINITION = re.compile(r"^[A-Za-z_][\w\s\*]*?([A-Za-z_]\w*)\s*\(")

#: `#[name("value")]` on its own line, above a `script` declaration.
ATTRIBUTE = re.compile(r'^\s*#\[\s*([a-z_]+)\s*\(\s*"([^"]*)"\s*\)\s*\]\s*$')

SCRIPT_DECL = re.compile(r"^\s*script\s+([A-Za-z_]\w*)")

#: Attributes an `.evt` script may carry, and the manifest list each feeds.
SCRIPT_ATTRIBUTES = ("map", "combo")

#: How far past a tag to look for the thing it describes. A tag separated from
#: its definition by more than this is a mistake worth reporting.
LOOKAHEAD = 12


@dataclass(frozen=True)
class Origin:
    """Where a tag was written, for naming it in a conflict."""

    file: str
    line: int

    def describe(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Tags:
    """Everything the sources declared, each paired with where it was written."""

    hooks: list[FunctionHook] = field(default_factory=list)
    maps: list[MapHook] = field(default_factory=list)
    combos: list[ComboBinding] = field(default_factory=list)
    origins: dict[str, Origin] = field(default_factory=dict)

    @property
    def any(self) -> bool:
        return bool(self.hooks or self.maps or self.combos)

    def where(self, key: str) -> str:
        origin = self.origins.get(key)
        return origin.describe() if origin else "a tag"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _definition_after(lines: list[str], start: int, where: str, what: str) -> str:
    """The name of the function a tag sits above."""
    for offset in range(start, min(start + LOOKAHEAD, len(lines))):
        text = lines[offset]
        if not text.strip() or text.lstrip().startswith(("//", "/*", "*", "#")):
            continue
        if HOOK_MACRO.search(text):
            break
        found = DEFINITION.match(text)
        if found:
            return found.group(1)
    raise ManifestError(
        f"{where}: {what} is not above a function definition. A tag describes "
        f"the definition that follows it, and nothing was found within "
        f"{LOOKAHEAD} lines."
    )


def scan_source(path: Path, root: Path, tags: Tags) -> None:
    """Collect `BLECK_HOOK` tags from one C or C++ file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    name = _relative(path, root)
    for index, text in enumerate(lines):
        found = HOOK_MACRO.search(text)
        if not found:
            continue
        target, mode = found.group(1), found.group(2)
        origin = Origin(name, index + 1)
        call = _definition_after(
            lines, index + 1, origin.describe(), f"BLECK_HOOK({target}, {mode})"
        )
        tags.hooks.append(build_hook(target, call, mode, origin.describe()))
        tags.origins[f"hook:{target}"] = origin


def scan_script(path: Path, root: Path, tags: Tags) -> None:
    """Collect `#[map(...)]` and `#[combo(...)]` from one `.evt` file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    name = _relative(path, root)
    pending: list[tuple[str, str, int]] = []  # pylint: disable=container-return
    for index, text in enumerate(lines):
        attribute = ATTRIBUTE.match(text)
        if attribute:
            kind, value = attribute.group(1), attribute.group(2)
            if kind not in SCRIPT_ATTRIBUTES:
                raise ManifestError(
                    f"{name}:{index + 1}: unknown attribute '#[{kind}(...)]'. "
                    f"A script takes {' or '.join(SCRIPT_ATTRIBUTES)}."
                )
            pending.append((kind, value, index + 1))
            continue
        if text.strip().startswith("--") or not text.strip():
            continue
        declaration = SCRIPT_DECL.match(text)
        if not pending:
            continue
        if not declaration:
            kind, _, line = pending[0]
            raise ManifestError(
                f"{name}:{line}: '#[{kind}(...)]' is not above a script declaration."
            )
        script = declaration.group(1)
        for kind, value, line in pending:
            origin = Origin(name, line)
            if kind == "map":
                tags.maps.append(MapHook(map_name=value, script=script))
                tags.origins[f"map:{value}"] = origin
            else:
                tags.combos.append(ComboBinding(combo=value, script=script))
                tags.origins[f"combo:{value}"] = origin
        pending = []
    if pending:
        kind, _, line = pending[0]
        raise ManifestError(
            f"{name}:{line}: '#[{kind}(...)]' is at the end of the file with no "
            f"script after it."
        )


def _refuse(mod: str, what: str, key: str, tags: Tags, manifest_at: str) -> None:
    raise ManifestError(
        f"{mod}: {what} conflict on '{key}'\n"
        f"  {tags.where(key):<24} declares it as a tag\n"
        f"  {manifest_at:<24} declares it in mod.json\n"
        f"Declare it once. Tags and mod.json do not override one another."
    )


def merge(spec: CodeSpec, tags: Tags, mod: str) -> CodeSpec:
    """Fold tags into a manifest's `code` block, refusing any overlap.

    ⚠️ Conflicts are keyed by the thing that can only be claimed once -- the
    *game* function for a hook, the map for a map hook, the combination for a
    combo. Two mod functions hooking one game function is the collision that
    matters; the same mod function hooking two game functions is fine.
    """
    if not tags.any:
        return spec

    for index, hook in enumerate(spec.hooks):
        if any(tag.function == hook.function for tag in tags.hooks):
            _refuse(mod, "hook", f"hook:{hook.function}", tags, f"code.hooks[{index}]")
    for index, hooked in enumerate(spec.maps):
        if any(tag.map_name == hooked.map_name for tag in tags.maps):
            _refuse(
                mod, "map hook", f"map:{hooked.map_name}", tags, f"code.maps[{index}]"
            )
    for index, combo in enumerate(spec.combos):
        if any(tag.combo == combo.combo for tag in tags.combos):
            _refuse(mod, "combo", f"combo:{combo.combo}", tags, f"code.combos[{index}]")

    _reject_repeats(mod, tags)

    return CodeSpec(
        script=spec.script,
        sources=list(spec.sources),
        target=spec.target,
        module_id=spec.module_id,
        maps=list(spec.maps) + tags.maps,
        combos=list(spec.combos) + tags.combos,
        patches=list(spec.patches),
        hooks=list(spec.hooks) + tags.hooks,
        replacements=list(spec.replacements),
        banner=spec.banner,
        boot_map=spec.boot_map,
    )


def _reject_repeats(mod: str, tags: Tags) -> None:
    """Two tags claiming the same target, which mod.json could never express."""
    for what, claimed in (
        ("hook", [hook.function for hook in tags.hooks]),
        ("map hook", [hooked.map_name for hooked in tags.maps]),
        ("combo", [combo.combo for combo in tags.combos]),
    ):
        seen = set()
        for key in claimed:
            if key in seen:
                raise ManifestError(
                    f"{mod}: two tags declare a {what} on '{key}'. "
                    f"It can only be claimed once."
                )
            seen.add(key)


#: Suffixes scanned for `BLECK_HOOK`. Kept here rather than imported from
#: `formats.languages` because that import would be a cycle through the builder.
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx")


def scan(root: Path, spec: CodeSpec) -> Tags:
    """Every tag in one mod's declared sources and script.

    Only what the manifest already points at is read. A stray `.c` file the mod
    does not build is not scanned, so a tag in it cannot take effect invisibly.
    """
    tags = Tags()
    for entry in spec.sources:
        path = root / entry
        if path.is_dir():
            found = {
                match for suffix in SOURCE_SUFFIXES for match in path.rglob(f"*{suffix}")
            }
            for source in sorted(found):
                scan_source(source, root, tags)
        elif path.exists() and path.suffix.lower() in SOURCE_SUFFIXES:
            scan_source(path, root, tags)
    if spec.script:
        script = root / spec.script
        if script.exists():
            scan_script(script, root, tags)
    return tags


def code_of(mod) -> CodeSpec | None:
    """A mod's `code` block with its tags folded in, or None if it has none."""
    spec = mod.manifest.code
    if spec is None:
        return None
    return merge(spec, scan(mod.root, spec), mod.name)
