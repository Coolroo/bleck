"""The JSON contract other applications integrate against.

The load-bearing property is **round-tripping**: a document read out, sent back
unchanged, must produce the same manifest. An editor that cannot re-open what it
wrote is a converter, so this is checked rather than assumed
(`docs/vision.md`).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bleck import api
from bleck.formats import setup
from bleck.mods.manifest import placements as manifest_placements


class TestRoundTrip:
    def _declared(self):
        return [
            manifest_placements.MapPlacements(
                map_name="he1_01",
                edits=[
                    manifest_placements.PlacementEdit(slot=0, template=148),
                    manifest_placements.PlacementEdit(
                        slot=2, template=144, position=setup.Position(-75, 0, -75)
                    ),
                    manifest_placements.PlacementEdit(slot=3, clear=True),
                ],
            )
        ]

    def test_manifest_survives_a_trip_through_json(self):
        declared = self._declared()
        wire = api.SetupEdits.of(declared)
        again = api.SetupEdits.model_validate_json(wire.model_dump_json()).to_manifest()
        assert again == declared

    def test_positions_keep_their_values(self):
        """Floats through JSON is where a round trip usually rots."""
        wire = api.SetupEdits.of(self._declared())
        back = wire.to_manifest()[0].edits[1]
        assert back.position.as_tuple() == (-75.0, 0.0, -75.0)

    def test_a_clear_stays_a_clear(self):
        back = api.SetupEdits.of(self._declared()).to_manifest()[0].edits[2]
        assert back.clear
        assert back.template is None


class TestEditValidation:
    """An edit that means nothing, or two things, is refused at the boundary."""

    def test_clearing_and_setting_at_once_is_refused(self):
        with pytest.raises(ValidationError, match="cannot also set"):
            api.PlacementEdit(slot=1, clear=True, template=5)

    def test_an_edit_that_changes_nothing_is_refused(self):
        # Otherwise `{"slot": 1}` writes a no-op into a manifest and looks
        # like it did something.
        with pytest.raises(ValidationError, match="must change something"):
            api.PlacementEdit(slot=1)

    def test_a_negative_slot_is_refused(self):
        with pytest.raises(ValidationError):
            api.PlacementEdit(slot=-1, template=5)

    def test_an_unknown_field_is_refused(self):
        """`extra="forbid"` so a typo is an error rather than silently dropped
        -- an editor sending `{"tempalte": 5}` should hear about it."""
        with pytest.raises(ValidationError):
            api.PlacementEdit(slot=1, tempalte=5)

    def test_position_needs_all_three_axes(self):
        # SPM is 2D with a 3D flip axis; z is not optional decoration.
        with pytest.raises(ValidationError):
            api.Position(x=1, y=2)


class TestMapPlacements:
    def _enemy(self, slot: int, template: int) -> setup.Enemy:
        raw = bytearray(112)
        raw[0x0C:0x10] = template.to_bytes(4, "big")
        return setup.Enemy(slot=slot, raw=bytes(raw), version=6)

    def test_an_occupied_slot_carries_its_template(self):
        placement = api.EnemyPlacement.of(0, self._enemy(0, 148), "Squig")
        assert not placement.empty
        assert placement.template == 148
        assert placement.name == "Squig"

    def test_an_empty_slot_says_so_rather_than_guessing(self):
        placement = api.EnemyPlacement.of(4, self._enemy(4, 0))
        assert placement.empty
        assert placement.template is None
        assert placement.position is None

    def test_used_skips_the_empty_ones(self):
        document = api.MapPlacements(
            map="he1_01",
            version=6,
            documented=True,
            enemies=[
                api.EnemyPlacement.of(0, self._enemy(0, 148)),
                api.EnemyPlacement.of(1, self._enemy(1, 0)),
            ],
        )
        assert [e.slot for e in document.used] == [0]


class TestSchema:
    """The reason for pydantic rather than hand-rolled JSON: the schema and the
    parser are the same declaration, so they cannot drift."""

    @pytest.mark.parametrize("model", [api.SetupEdits, api.MapPlacements])
    def test_a_schema_is_published(self, model):
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert json.dumps(schema)  # serialisable, which is the whole point

    def test_the_schema_records_the_slot_bound(self):
        schema = api.PlacementEdit.model_json_schema()
        assert schema["properties"]["slot"]["minimum"] == 0

    def test_the_schema_forbids_unknown_fields(self):
        assert api.PlacementEdit.model_json_schema()["additionalProperties"] is False
