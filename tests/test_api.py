"""The JSON contract other applications integrate against.

The load-bearing property is **round-tripping**: a document read out and sent
back unchanged must produce the same manifest (`docs/vision.md`).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bleck import api
from bleck.formats import setup
from bleck.mods import manifest as mod_manifest
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
        # Otherwise `{"slot": 1}` writes a no-op that looks like it did something.
        with pytest.raises(ValidationError, match="must change something"):
            api.PlacementEdit(slot=1)

    def test_a_negative_slot_is_refused(self):
        with pytest.raises(ValidationError):
            api.PlacementEdit(slot=-1, template=5)

    def test_an_unknown_field_is_refused(self):
        """`extra="forbid"`, so a typo is an error rather than silently dropped."""
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
    """With pydantic the schema and the parser are one declaration, so they
    cannot drift."""

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


class TestVersioning:
    """Documents carry `api_version` *and* the module path versions the code —
    both, since a document read off disk has no schema to hand."""

    def test_a_document_stamps_its_version(self):
        assert api.SetupEdits().api_version == api.API_VERSION

    def test_an_unknown_version_is_refused_with_a_way_forward(self):
        with pytest.raises(ValidationError) as caught:
            api.SetupEdits.model_validate_json('{"api_version": 99, "setup": {}}')
        message = str(caught.value)
        assert "not supported" in message
        assert "Upgrade bleck" in message

    def test_omitting_it_means_the_current_version(self):
        """A hand-written document should not need boilerplate to be valid."""
        assert api.SetupEdits.model_validate_json('{"setup": {}}').api_version == 1

    def test_nested_models_carry_no_version(self):
        # Stamping every object would make a document mostly version fields.
        assert "api_version" not in api.PlacementEdit.model_json_schema()["properties"]

    def test_the_current_alias_points_at_a_real_version(self):
        assert api.CURRENT is api.v1


class TestModDocument:
    def _manifest(self):
        return mod_manifest.Manifest(
            name="demo",
            version=mod_manifest.Version(1, 2, 3),
            description="a mod",
            base="eu0",
            dependencies=[mod_manifest.Requirement.parse("other", ">=1.0.0")],
            code=mod_manifest.CodeSpec(
                script="s.evt",
                maps=[mod_manifest.MapHook("aa4_01", "on_arrive")],
                combos=[mod_manifest.ComboBinding("start_map", "warp")],
                boot_map="he1_01",
            ),
        )

    def test_a_manifest_survives_a_trip_through_json(self):
        original = self._manifest()
        wire = api.ModDocument.of(original).model_dump_json()
        assert api.ModDocument.model_validate_json(wire).to_manifest() == original

    def test_a_versioned_dependency_keeps_its_constraint(self):
        """`>=1.0.0` collapsing to `1.0.0` would silently tighten a chain."""
        document = api.ModDocument.of(self._manifest())
        assert document.dependencies[0].version == ">=1.0.0"

    def test_an_asset_only_mod_has_no_code_block(self):
        document = api.ModDocument.of(mod_manifest.Manifest(name="m"))
        assert document.code is None

    def test_a_document_needs_a_name(self):
        with pytest.raises(ValidationError, match="needs a name"):
            api.ModDocument(name="   ")

    def test_unknown_fields_are_refused(self):
        with pytest.raises(ValidationError):
            api.ModDocument(name="m", desription="typo")

    def test_a_reserved_module_id_is_refused(self):
        # 0 is the game binary and 1 its own REL.
        with pytest.raises(ValidationError):
            api.Code(module_id=1)
