"""Vertex colour, walked in the bytes the writer produced.

⛔ **Leaving it out is what made Brobot render white** (D251). The disc stores
one greyscale panel with rivets and vents on it and tints that panel red, blue
or green *per shape*, in slot 5 of the section table — so an export carrying
the panel and not the tint is structurally perfect, passes every material check
in `test_gltf_materials.py`, and is visibly wrong the moment a person opens it.

The walk here is the one a reader performs:

    primitive.attributes.COLOR_0 -> accessors[n] -> bufferViews[v] -> bytes

⚠️ **Read through the accessor, never from the writer.** A test that trusted
the writer's own list is exactly what let an export with no materials at all
pass 1,508 tests (D245).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bleck.formats import gltf, gltfcore, model
from tests.test_gltf_materials import Loaded, a_painted_mesh, a_png, load

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"

#: One tint per corner of `a_painted_mesh`: the first shape red, the second
#: blue. ⚠️ Alpha is 255 on both, so a reader that dropped the channel would
#: still pass — the colours differ in RGB, which is what the disc's do.
TINTS = [
    (198, 39, 39, 255),
    (198, 39, 39, 255),
    (198, 39, 39, 255),
    (0, 126, 188, 255),
    (0, 126, 188, 255),
    (0, 126, 188, 255),
]

WHITE = (255, 255, 255, 255)


def colour_attributes(loaded: Loaded) -> list:  # pylint: disable=container-return
    """Every primitive's `COLOR_0`, decoded out of the emitted bytes."""
    document, binary = loaded.document, loaded.binary
    found = []
    for mesh in document.get("meshes", []):
        for primitive in mesh["primitives"]:
            at = primitive["attributes"].get("COLOR_0")
            if at is None:
                found.append([])
                continue
            accessor = document["accessors"][at]
            assert accessor["type"] == "VEC4"
            assert accessor["componentType"] == gltfcore.UNSIGNED_BYTE
            assert accessor.get("normalized") is True, (
                "an unsigned-byte COLOR_0 that is not normalized is read as "
                "0..255, and a reader would blow the colour out"
            )
            view = document["bufferViews"][accessor["bufferView"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            found.append(
                [
                    tuple(binary[start + i * 4 : start + i * 4 + 4])
                    for i in range(accessor["count"])
                ]
            )
    return found


def a_coloured_mesh(tints: list | None = None) -> model.Mesh:
    """`a_painted_mesh` with a vertex colour on every corner."""
    return replace(
        a_painted_mesh(),
        colours=list(TINTS if tints is None else tints),
        corner_colours=[0, 1, 2, 3, 4, 5],
    )


class TestTheColoursReachTheFile:
    def test_the_colours_the_mesh_holds_are_the_bytes_in_the_file(self):
        blob = gltf.write(a_coloured_mesh(), paints=[gltfcore.Paint(7, a_png())])
        found = colour_attributes(load(blob))
        assert [run for run in found if run], "no primitive carried COLOR_0"
        assert sorted({tint for run in found for tint in run}) == sorted(set(TINTS))

    def test_each_shape_keeps_its_own_tint(self):
        """⚠️ The failure that would look like success: one tint over the whole
        mesh renders coloured, and is the D246 bug in a new place."""
        found = [
            run
            for run in colour_attributes(
                load(gltf.write(a_coloured_mesh(), paints=[gltfcore.Paint(7, a_png())]))
            )
            if run
        ]
        assert len(found) == 2
        assert set(found[0]) != set(found[1])

    def test_an_all_white_mesh_writes_no_attribute(self):
        """A multiply by 1 is the specification's default, so four bytes a
        vertex saying so is weight for nothing. 524 of 864 models are here."""
        blob = gltf.write(
            a_coloured_mesh([WHITE] * 6), paints=[gltfcore.Paint(7, a_png())]
        )
        assert not any(colour_attributes(load(blob)))
        assert gltf.painting(blob).coloured == 0

    def test_a_mesh_with_no_colours_writes_no_attribute(self):
        blob = gltf.write(a_painted_mesh(), paints=[gltfcore.Paint(7, a_png())])
        assert not any(colour_attributes(load(blob)))

    def test_an_index_past_the_array_is_dropped_rather_than_guessed(self):
        """⛔ Clamping would tint a shape with whatever colour sat last."""
        broken = replace(a_coloured_mesh(), corner_colours=[0, 1, 2, 3, 4, 99])
        blob = gltf.write(broken, paints=[gltfcore.Paint(7, a_png())])
        assert len([run for run in colour_attributes(load(blob)) if run]) == 1

    def test_two_corners_at_one_point_with_different_tints_stay_apart(self):
        """⚠️ Welding on position alone would average a hard colour edge away.

        The control is the same geometry with one colour index on every corner,
        which welds to three — so the count is a measurement, not a constant.
        """
        seam = model.Mesh(
            name="seamShape",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3), model.Face(first=3, corners=3)],
            corner_positions=[0, 1, 2, 0, 1, 2],
            colours=list(TINTS),
            corner_colours=[0, 1, 2, 3, 4, 5],
            groups=[model.Shape(first=0, count=2)],
        )
        split = colour_attributes(load(gltf.write(seam)))
        merged = colour_attributes(
            load(gltf.write(replace(seam, corner_colours=[0, 1, 2, 0, 1, 2])))
        )
        assert sum(len(run) for run in split) == 6
        assert sum(len(run) for run in merged) == 3


def a_written_model(name: str) -> bytes:
    """One disc model exported the way `bleck model export` exports it."""
    path = MODELS / name
    if not path.is_file():
        pytest.skip(f"no {path}")
    data = path.read_bytes()
    mesh = model.mesh(data)
    # pylint: disable=import-outside-toplevel
    from bleck.cli.commands import model as command

    paints = command.textures_for(MODELS.parent.parent, f"files/a/{name}", mesh)
    return gltf.write(mesh, name=name, paints=paints)


def _readable_models():
    """Every model on the disc whose geometry this reading covers."""
    for path in sorted(MODELS.iterdir()):
        if path.name.endswith("-") or path.suffix == ".bin":
            continue
        data = path.read_bytes()
        if not model.is_model(data):
            continue
        try:
            yield path.name, model.mesh(data)
        except model.ModelError:
            continue


class TestAgainstTheDisc:
    def test_brobot_carries_the_tints_that_make_it_not_white(self):
        """✅ The model a person reported as 'almost entirely white' (D251).

        ⚠️ **The assertion is on the spread, not on one colour.** A writer that
        put a single tint over every primitive would satisfy "carries colour"
        and still be wrong; `e_lui_robo` states 20 distinct modal tints across
        84 of its 92 primitives.
        """
        runs = [
            run for run in colour_attributes(load(a_written_model("e_lui_robo"))) if run
        ]
        assert len(runs) > 70, f"only {len(runs)} of 92 primitives carry a tint"
        tints = {tint for run in runs for tint in run}
        assert len(tints) > 10, f"only {len(tints)} distinct colours"
        saturated = [t for t in tints if max(t[:3]) - min(t[:3]) > 60]
        assert len(saturated) > 10, (
            f"only {len(saturated)} tints have a hue at all; the disc's panels "
            "are greyscale and it is the vertex colour that reddens them"
        )

    def test_every_colour_index_on_the_disc_lands_in_its_own_array(self):
        """The invariant that makes slot 6 a reading rather than a fit.

        ⚠️ **A bounds check alone would pass on an array long enough for
        anything**, so the streams are also required to *reach* the last entry.
        """
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        looked = stray = tight = 0
        for _, mesh in _readable_models():
            if not mesh.colours or not mesh.corner_colours:
                continue
            looked += 1
            reach = max(mesh.corner_colours)
            stray += reach >= len(mesh.colours)
            tight += reach == len(mesh.colours) - 1
        assert looked > 800, "too few models read to mean anything"
        assert stray == 0, f"{stray} models index past their own colour array"
        assert tight > looked * 0.9, (
            f"only {tight} of {looked} streams reach the last colour; a stream "
            "that stops short is not indexing this array"
        )

    @pytest.mark.gamedata
    def test_the_corpus_carries_colour_on_the_models_that_state_one(self):
        """How many models the tint changes, counted in their emitted bytes."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        # pylint: disable=import-outside-toplevel
        from bleck.cli.commands import model as command

        base = MODELS.parent.parent
        looked = coloured = 0
        for name, mesh in _readable_models():
            paints = command.textures_for(base, f"files/a/{name}", mesh)
            try:
                blob = gltf.write(mesh, name=name, paints=paints)
            except ValueError:
                continue
            looked += 1
            coloured += bool(gltf.painting(blob).coloured)
        assert looked > 800
        assert coloured > 300, (
            f"only {coloured} of {looked} models carry a tint; 331 hold more "
            "than one distinct colour, so this has stopped being read"
        )
        assert coloured < looked, (
            "every model carrying one would mean the all-white shortcut has "
            "stopped working, and 524 of them are all white"
        )
