"""Compiling a mod's script into the `mod.rel` its overlay ships.

This runs before the overlay is planned, because the plan is derived from a
walk of `overlay/` and the compiled module has to exist by then. The output goes
to `overlay/files/mod/mod.rel` and is then carried by the ordinary overlay
machinery -- a code mod is still just a mod, and nothing downstream needs to
know it was generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.backends import toolchain
from bleck.common.errors import BleckError
from bleck.mods import registry as mod_registry
from bleck.mods.manifest import REL_DISC_PATH
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain
from bleck.script import ScriptError, compile_source


class CodeError(BleckError):
    """A mod's script could not be turned into a module."""


@dataclass(frozen=True)
class CodeBuild:
    """One mod's compiled code, and what it took to produce."""

    mod: str
    script: Path
    output: Path
    size: int
    toolchain: str
    scripts: list[str]
    called_symbols: list[str]

    def describe(self) -> str:
        names = ", ".join(self.scripts)
        return (
            f"{self.mod}: compiled {self.script.name} "
            f"[{names}] -> {self.size} byte module ({self.toolchain})"
        )


def mods_with_code(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_code]


def build_chain(chain: Chain, workroot: Path | None = None) -> list[CodeBuild]:
    """Compile every code mod in `chain`, newest last.

    Raises before touching anything if the chain contains more than one code
    mod: the Gecko loader opens exactly one `/mod/mod.rel`, so a second would be
    silently dropped rather than merged. Failing loudly here is the interim
    answer to that; chaining several modules together is a separate feature.
    """
    coded = mods_with_code(chain)
    if len(coded) > 1:
        names = ", ".join(mod.name for mod in coded)
        raise CodeError(
            f"this chain contains {len(coded)} code mods ({names}), but the "
            f"loader can only run one {REL_DISC_PATH}.\n"
            "  Combine their scripts into a single mod for now."
        )

    root = workroot or mod_registry.build_root()
    return [build_mod(mod, root) for mod in coded]


def build_mod(mod: Mod, workroot: Path) -> CodeBuild:
    """Compile one mod's script and place the module in its overlay."""
    spec = mod.manifest.code
    if spec is None:
        raise CodeError(f"{mod.name} declares no code to build")

    source_path = mod.root / spec.script
    if not source_path.exists():
        raise CodeError(
            f"{mod.name}: no script at {source_path}\n"
            f"  mod.json points 'code.script' at {spec.script!r}"
        )

    text = source_path.read_text(encoding="utf-8")
    try:
        compiled = compile_source(text, origin=spec.script)
    except ScriptError as exc:
        raise CodeError(f"{mod.name}:\n{exc.render(str(source_path))}") from exc

    result = toolchain.build_rel(
        compiled.generated.text,
        workdir=workroot / mod.name / "code",
        target=spec.target,
        module_id=spec.module_id,
    )

    output = mod.overlay / REL_DISC_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.rel)

    return CodeBuild(
        mod=mod.name,
        script=source_path,
        output=output,
        size=result.size,
        toolchain=result.toolchain,
        scripts=compiled.script_names,
        called_symbols=list(compiled.program.called_symbols),
    )
