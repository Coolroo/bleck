"""Reading a `code` block out of `mod.json`."""

from __future__ import annotations

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.code.hooks import _parse_hooks
from bleck.mods.manifest.code.patches import _parse_patches
from bleck.mods.manifest.code.specs import (
    BannerSpec,
    CodeSpec,
    ComboBinding,
    MapHook,
)
from bleck.mods.manifest.replacements import parse_replacements
from bleck.mods.manifest.selectors import _MAP_NAME_RE
from bleck.script import emit


def _parse_code(raw: object, source: str) -> CodeSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'code' must be an object")

    script = raw.get("script", "")
    if not isinstance(script, str):
        raise ManifestError(f"{source}: 'code.script' must be a path")

    sources = raw.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ManifestError(f"{source}: 'code.sources' must be a list of paths")

    boot = _parse_boot(raw.get("boot"), source)
    combos = _parse_combos(raw.get("combos"), source)
    patches = _parse_patches(raw.get("patches"), source)
    hooks = _parse_hooks(raw.get("hooks"), source)
    replacements = parse_replacements(raw.get("replace"), source)

    if not script and not sources and not boot:
        raise ManifestError(
            f"{source}: 'code' needs a 'script', 'sources', 'boot', or a "
            f"combination -- otherwise there is nothing to compile"
        )

    module_id = raw.get("module_id", 2)
    if not isinstance(module_id, int) or isinstance(module_id, bool):
        raise ManifestError(f"{source}: 'code.module_id' must be a whole number")
    # Module 0 is the DOL and 1 is the game's own REL; either would collide.
    if module_id < 2:
        raise ManifestError(
            f"{source}: 'code.module_id' must be 2 or more "
            f"(0 is the game binary, 1 is its own REL)"
        )

    return CodeSpec(
        script=script,
        sources=list(sources),
        target=str(raw.get("target", "eu0")),
        module_id=module_id,
        maps=_parse_maps(raw.get("maps"), source),
        combos=combos,
        patches=patches,
        hooks=hooks,
        replacements=replacements,
        banner=_parse_banner(raw.get("banner"), source),
        boot_map=boot,
    )


#: A map's name as the disc spells it: `he1_01`, `aa4_01`. Enforced because it
#: is interpolated into generated script source.


def _parse_boot(raw: object, source: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ManifestError(
            f"{source}: 'code.boot' must be a map name like 'he1_01', not "
            f"{type(raw).__name__}"
        )
    name = raw.strip()
    if not name:
        return ""
    if not _MAP_NAME_RE.match(name):
        raise ManifestError(
            f"{source}: {raw!r} is not a map name. They look like 'he1_01' -- "
            f"lowercase letters, digits and underscores.\n"
            f"  `bleck maps` lists all 383 of them."
        )
    return name


def _parse_banner(raw: object, source: str) -> BannerSpec:
    """Read `code.banner`: absent, a boolean, or an object."""
    if raw is None or raw is True:
        return BannerSpec()
    if raw is False:
        return BannerSpec(enabled=False)
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.banner' must be an object or false, not "
            f"{type(raw).__name__}"
        )

    text = raw.get("text", "")
    if not isinstance(text, str):
        raise ManifestError(f"{source}: 'code.banner.text' must be a string")

    sequences = raw.get("sequences", list(emit.DEFAULT_BANNER_SEQUENCES))
    if not isinstance(sequences, list) or not all(isinstance(s, str) for s in sequences):
        raise ManifestError(
            f"{source}: 'code.banner.sequences' must be a list of sequence names"
        )
    for name in sequences:
        if name not in emit.SEQUENCE_NAMES:
            known = ", ".join(emit.SEQUENCE_NAMES)
            raise ManifestError(
                f"{source}: unknown sequence {name!r} in "
                f"'code.banner.sequences'\n  known sequences are: {known}"
            )
    if not sequences:
        raise ManifestError(
            f"{source}: 'code.banner.sequences' is empty, so the banner would "
            f'never draw -- use "banner": false to turn it off'
        )

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ManifestError(f"{source}: 'code.banner.enabled' must be true or false")

    return BannerSpec(enabled=enabled, text=text, sequences=list(sequences))


def _parse_maps(raw: object, source: str) -> list[MapHook]:
    """Read `code.maps`, an object of map name -> script name.

    An object, not a list: a map has one init script, so a duplicate entry
    should be inexpressible rather than validated.
    """
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.maps' must be an object of "
            f'map name -> script name, e.g. {{"aa4_01": "on_arrive"}}'
        )

    hooks: list[MapHook] = []
    for map_name, script in raw.items():
        if not isinstance(script, str) or not script:
            raise ManifestError(
                f"{source}: 'code.maps.{map_name}' must name a script in this mod"
            )
        hooks.append(MapHook(map_name=map_name, script=script))
    return hooks


def _parse_combos(raw: object, source: str) -> list[ComboBinding]:
    """Read `code.combos`, an object of combination name -> script name.

    Combination names are not validated here: `bleck.yml` defines them, so the
    check lives where the config is loaded and can list what is defined.
    """
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.combos' must be an object of "
            f'combo name -> script name, e.g. {{"start_map": "warp_home"}}'
        )

    bindings: list[ComboBinding] = []
    for combo, script in raw.items():
        if not isinstance(script, str) or not script:
            raise ManifestError(
                f"{source}: 'code.combos.{combo}' must name a script in this mod"
            )
        bindings.append(ComboBinding(combo=str(combo), script=script))
    return bindings


#: A C identifier, since `call` is emitted into generated C verbatim.
