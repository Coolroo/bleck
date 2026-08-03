"""A keyframe is not a morph target, and the budget has to know it.

⚠️ **Poses accumulate** (D252), so a clip holds its shape for a beat whenever a
track carries no keys — 13,115 of the disc's 35,190 tracks, 36% of every
keyframe written. Giving each of those its own target makes the weight block
`keys` squared instead of `keys` times `targets`, which cost 70 clips to the
export budget and 39 MB.

⚠️ **Read out of the emitted document, not from the writer's own lists** (D245).
"""

from __future__ import annotations

from bleck.formats import gltf, gltfmorph, model
from tests.test_gltf import _floats, a_mesh, parsed


def held() -> list:
    """One movement, then two beats where nothing changes, then another."""
    return [
        gltfmorph.Clip(
            name="beat",
            poses=[
                model.Morph(time=0.0, offsets=[(1, 1.0, 0.0, 0.0)]),
                model.Morph(time=1.0, offsets=[(1, 1.0, 0.0, 0.0)]),
                model.Morph(time=2.0, offsets=[(1, 1.0, 0.0, 0.0)]),
                model.Morph(time=3.0, offsets=[(1, 2.0, 0.0, 0.0)]),
            ],
        )
    ]


class TestAHoldKeyframeCostsNoTarget:
    def test_four_keyframes_over_two_targets(self):
        document = parsed(gltf.write(a_mesh(), clips=held()))
        targets = document["meshes"][0]["primitives"][0]["targets"]
        assert len(targets) == 2, "the three identical poses are one target"
        assert document["meshes"][0]["weights"] == [0.0, 0.0]

    def test_the_timeline_keeps_every_beat(self):
        """⚠️ The failure that would look fine: folding the *keyframes* too,
        which plays a four-beat clip in two."""
        blob = gltf.write(a_mesh(), clips=held())
        document = parsed(blob)
        sampler = document["animations"][0]["samplers"][0]
        assert _floats(blob, document, sampler["input"]) == [0.0, 1.0, 2.0, 3.0]
        assert _floats(blob, document, sampler["output"]) == [
            1.0,
            0.0,
            1.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
        ]

    def test_the_budget_prices_the_targets_it_will_actually_write(self):
        """⛔ `costs` mirroring `_morph_targets` is not optional — a cost model
        that charged per keyframe would drop clips that fit."""
        written = len(
            parsed(gltf.write(a_mesh(), clips=held()))["meshes"][0]["primitives"][0][
                "targets"
            ]
        )
        priced = gltfmorph.costs(a_mesh(), held())
        assert priced[0].poses == written
        assert priced[0].keys == 4

    def test_the_weight_block_is_keys_by_targets(self):
        assert (
            gltfmorph.weight_cost(2, 4)
            == 2 * 4 * gltfmorph.WEIGHT_BYTES + 2 * gltfmorph.WEIGHT_JSON
        )
        assert gltfmorph.weight_cost(4) == gltfmorph.weight_cost(4, 4), (
            "keys default to targets"
        )
