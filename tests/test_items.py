"""The item catalog: names -> ids, and the tiers that keep them apart.

The names exist so `item:0x41` can be written `item:fire_burst` (D114). They are
a convenience, so an absent catalog has to stay harmless.

The *ids* are not a convenience, which is why they are a generated `IntEnum`
rather than a column of the JSON (D119). Two things follow, and both are tested
here: the constant tiers keep working with no catalog on disk, and the committed
`itemids.py` cannot drift from `itemcatalog.json`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bleck.formats import itemgen, items
from bleck.formats.itemids import ItemId
from tests.synthetic_msg import BLASTER, BLASTER_ID, BLASTER_WRITTEN

#: The generated module itself, so the drift guard can compare its text.
ITEM_IDS = Path(items.__file__).with_name("itemids.py")

#: Four rows shaped like the committed catalog. `MARIO` appears twice on
#: purpose: the real table has four such pairs, and they are what makes an
#: unqualified name ambiguous rather than merely unknown.
ROWS = [
    {
        "id": 0x41,
        "name": "HONOO_SAKURETU",
        "msg": "in_honoo_sakuretsu",
        "enum": "ITEM_ID_USE_HONOO_SAKURETU",
        "english": "Fire Burst",
    },
    {
        "id": 0x45,
        "name": "POW_BLOCK",
        "msg": "in_pow_block",
        "enum": "ITEM_ID_USE_POW_BLOCK",
        "english": "POW Block",
    },
    {
        "id": 0xD8,
        "name": "MARIO",
        "msg": "in_pc_mario",
        "enum": "ITEM_ID_CHAR_MARIO",
        "english": "Mario",
    },
    {
        "id": 0x20A,
        "name": "MARIO",
        "msg": "in_card_mario",
        "enum": "ITEM_ID_CARD_MARIO",
        "english": "Mario",
    },
]


@pytest.fixture(name="names")
def _names() -> items.ItemNames:
    return items.ItemNames(ROWS)


class TestNormalize:
    """Case, dashes and spaces are punctuation to a person, not identity."""

    @pytest.mark.parametrize(
        "written",
        ["fire_burst", "FIRE_BURST", "Fire Burst", "fire-burst", " Fire-Burst "],
    )
    def test_every_spelling_of_one_name_collapses(self, written):
        assert items.normalize(written) == "fire_burst"

    def test_punctuation_never_survives(self):
        assert items.normalize("Gold Bar x3!") == "gold_bar_x3"


class TestResolve:
    def test_the_internal_name(self, names):
        assert names.resolve("HONOO_SAKURETU").item.id == 0x41

    def test_the_full_constant(self, names):
        assert names.resolve("ITEM_ID_USE_HONOO_SAKURETU").item.id == 0x41

    def test_the_constant_without_its_prefix(self, names):
        assert names.resolve("USE_HONOO_SAKURETU").item.id == 0x41

    def test_the_english_name(self, names):
        assert names.resolve("fire burst").item.id == 0x41

    def test_case_and_dashes_do_not_matter(self, names):
        assert names.resolve("Fire-Burst").item.id == 0x41
        assert names.resolve("honoo_sakuretu").item.id == 0x41

    def test_a_name_two_items_share_is_ambiguous(self, names):
        """Silently picking the first would patch the character item when the
        card was meant, and nothing downstream could tell."""
        match = names.resolve("mario")
        assert match.item is None
        assert [found.id for found in match.ambiguous] == [0xD8, 0x20A]

    def test_the_full_constant_disambiguates(self, names):
        assert names.resolve("ITEM_ID_CARD_MARIO").item.id == 0x20A

    def test_an_unknown_name_suggests_near_ones(self, names):
        match = names.resolve("fire_blast")
        assert match.item is None
        assert not match.ambiguous
        assert "fire_burst" in match.near

    def test_an_empty_name_resolves_to_nothing(self, names):
        assert not names.resolve("  ").found

    def test_an_internal_name_outranks_an_english_one(self, names):
        """`POW_BLOCK` is both, on the same item -- but the tiers exist so that
        an English name never decides an answer an internal name could."""
        assert names.resolve("pow_block").item.id == 0x45


class TestItemInfo:
    def test_it_describes_itself_with_both_names(self, names):
        assert names.lookup(0x41).describe() == "Fire Burst (HONOO_SAKURETU)"

    def test_it_says_how_to_write_itself(self, names):
        assert names.lookup(0x41).selector == "item:0x41"

    def test_the_group_comes_from_the_constant(self, names):
        assert names.lookup(0x41).group == "USE"
        assert names.lookup(0x20A).group == "CARD"

    def test_an_unknown_id_is_none(self, names):
        assert names.lookup(0x999) is None


class TestBrowsing:
    """`search`, `group` and `groups` — what `bleck items` lists (D120).

    Separate from `resolve` because they answer a different question: "which
    items are worth looking at", not "which item is this called". A name that
    `resolve` calls ambiguous is a perfectly good browsing result.
    """

    def test_a_substring_matches_where_resolve_would_not(self, names):
        # ⚠️ A superset, not an equality: these four rows are merged with every
        # real `ItemId` (`known`), so the constant tiers answer for all 538 and
        # `mari` legitimately reaches Marilyn as well as both Marios.
        assert names.resolve("mari").item is None
        assert {found.id for found in names.search("mari")} >= {0xD8, 0x20A}

    def test_an_english_substring_matches(self, names):
        """`Fire Burst` is an English name; no constant contains `fire_burst`."""
        assert [found.id for found in names.search("fire_burst")] == [0x41]

    def test_it_matches_the_same_aliases_a_manifest_takes(self, names):
        """The tier tables, not a second alias list — the point of reusing them
        is that `bleck items` cannot find a name a manifest then refuses."""
        for written in ("HONOO_SAKURETU", "ITEM_ID_USE_HONOO_SAKURETU", "sakuretu"):
            assert [found.id for found in names.search(written)] == [0x41]

    def test_case_and_punctuation_do_not_matter(self, names):
        assert [found.id for found in names.search("Fire-Burst")] == [0x41]

    def test_an_empty_search_is_everything(self, names):
        assert len(names.search("")) == len(names.known)

    def test_nothing_matching_is_empty_rather_than_an_error(self, names):
        assert names.search("zzzz") == []

    def test_known_covers_every_id_not_just_the_catalog(self, names):
        """Four rows read, 538 ids known: the ids are a module, not the JSON."""
        assert len(names.items) == 4
        assert len(names.known) == len(ItemId)

    def test_a_group_is_the_constants_first_word(self, names):
        carded = {found.id for found in names.group("CARD")}
        assert 0x20A in carded
        assert 0xD8 not in carded  # the character item, not the card

    def test_a_group_name_is_spelled_loosely_too(self, names):
        assert names.group("card") == names.group("CARD")

    def test_groups_count_every_known_id(self, names):
        assert sum(found.items for found in names.groups()) == len(ItemId)

    def test_groups_are_largest_first(self, names):
        counts = [found.items for found in names.groups()]
        assert counts == sorted(counts, reverse=True)


class TestLoading:
    def test_a_missing_catalog_is_not_an_error(self, tmp_path):
        # Names are a convenience; every id must work without them.
        empty = items.load_items(tmp_path / "absent.json")
        assert not empty
        assert empty.lookup(0x41) is None
        assert not empty.resolve("fire_burst").found

    def test_it_reads_the_committed_shape(self, tmp_path):
        path = tmp_path / "itemcatalog.json"
        path.write_text(json.dumps({"items": ROWS}), encoding="utf-8")
        assert items.load_items(path).resolve("fire_burst").item.id == 0x41


class TestWithoutTheCatalog:
    """⚠️ Deliberate, not accidental (D119). `ItemId` is a module, so the two
    constant tiers survive a missing JSON; `itemName` and the English name
    cannot, because neither is derivable from an id.

    This is the improvement the enum bought, so it is pinned rather than left
    to be rediscovered -- and the *absence* of the English name is pinned in
    the same breath, since a tier that quietly stopped working would look
    identical from the outside.
    """

    @pytest.fixture(name="empty")
    def _empty(self, tmp_path) -> items.ItemNames:
        return items.load_items(tmp_path / "absent.json")

    @pytest.mark.parametrize(
        "written",
        ["ITEM_ID_USE_HONOO_SAKURETU", "USE_HONOO_SAKURETU", "use-honoo-sakuretu"],
    )
    def test_a_constant_still_resolves(self, empty, written):
        assert empty.resolve(written).item.id == 0x41

    def test_what_it_resolves_to_carries_the_constant_and_nothing_else(self, empty):
        found = empty.resolve("ITEM_ID_USE_HONOO_SAKURETU").item
        assert found.enum is ItemId.USE_HONOO_SAKURETU
        assert found.constant == "ITEM_ID_USE_HONOO_SAKURETU"
        assert not found.name
        assert not found.english

    def test_the_english_name_does_not(self, empty):
        """The only tier that truly needs the JSON. `Fire Burst` is a lookup in
        `files/msg/UK`, and no rule turns 65 into it."""
        assert not empty.resolve("fire_burst").found

    def test_the_internal_name_survives_anyway_and_that_is_a_coincidence(self, empty):
        """⚠️ Not evidence that `itemName` is derivable from an id. Every one of
        the 538 internal names happens to equal its constant's bare form
        (measured, D119), so `HONOO_SAKURETU` still resolves here -- as tier 2,
        via `ITEM_ID_USE_HONOO_SAKURETU`, not as tier 1 via `itemName`."""
        assert empty.resolve("HONOO_SAKURETU").item.id == 0x41
        assert not empty.resolve("HONOO_SAKURETU").item.name

    def test_it_still_reports_as_absent(self, empty):
        """`bool` means "the catalog was read", which is what the error message
        in `codespec` turns on. Resolving a constant must not make it look
        present."""
        assert not empty
        assert len(empty) == 0

    def test_an_ambiguous_constant_is_still_refused(self, empty):
        """`MARIO` is the bare form of both `CHAR_MARIO` and `CARD_MARIO`, and
        a missing catalog is no reason to start guessing."""
        match = empty.resolve("mario")
        assert match.item is None
        assert [found.constant for found in match.ambiguous] == [
            "ITEM_ID_CHAR_MARIO",
            "ITEM_ID_CARD_MARIO",
        ]


class TestTheGeneratedEnum:
    """`itemids.py` is generated, and this is the point of generating it.

    Two artifacts come out of one dump (`scripts/dump_items.py`). Nothing but a
    test stops someone editing one of them by hand, so the test regenerates the
    module from the catalog and compares the text.
    """

    def test_a_member_name_is_its_constant_without_the_prefix(self):
        assert ItemId.USE_HONOO_SAKURETU == 0x41
        assert ItemId.NULL == 0
        assert ItemId(0x20A) is ItemId.CARD_MARIO

    def test_a_member_is_an_int_and_that_is_a_trap(self):
        """Pinned because it already bit: `ItemId.NULL` is falsy and formats as
        a number, so `if info.enum` and `f"{info.enum}"` are both wrong (D119).
        """
        assert not ItemId.NULL
        assert ItemId.NULL is not None
        assert f"{ItemId.USE_HONOO_SAKURETU}" == "65"
        assert ItemId.USE_HONOO_SAKURETU.name == "USE_HONOO_SAKURETU"

    @pytest.mark.skipif(not items.ITEM_CATALOG.is_file(), reason="no item catalog")
    def test_the_committed_module_is_what_the_generator_writes(self):
        rows = json.loads(items.ITEM_CATALOG.read_text(encoding="utf-8"))["items"]
        regenerated = itemgen.render(itemgen.from_catalog(rows))
        committed = ITEM_IDS.read_text(encoding="utf-8")
        assert regenerated == committed, (
            "bleck/formats/itemids.py disagrees with itemcatalog.json. Both come "
            "from one dump; regenerate them together with scripts/dump_items.py."
        )

    @pytest.mark.skipif(not items.ITEM_CATALOG.is_file(), reason="no item catalog")
    def test_there_is_one_member_per_catalog_row(self):
        rows = json.loads(items.ITEM_CATALOG.read_text(encoding="utf-8"))["items"]
        assert len(ItemId) == len(rows) == 538
        assert {member.name: int(member) for member in ItemId} == {
            row["enum"].removeprefix("ITEM_ID_"): row["id"] for row in rows
        }


class TestGenerationRefuses:
    """A broken module is never written: a silently aliased member would make
    two different items the same object, and every lookup after it wrong."""

    def test_a_repeated_name_is_refused(self):
        members = [
            itemgen.EnumMember(name="USE_POW_BLOCK", value=1),
            itemgen.EnumMember(name="USE_POW_BLOCK", value=2),
        ]
        with pytest.raises(itemgen.GenerationError, match="alias"):
            itemgen.render(members)

    def test_a_repeated_id_is_refused(self):
        members = [
            itemgen.EnumMember(name="USE_POW_BLOCK", value=1),
            itemgen.EnumMember(name="CARD_MARIO", value=1),
        ]
        with pytest.raises(itemgen.GenerationError, match="alias"):
            itemgen.render(members)

    @pytest.mark.parametrize("name", ["USE POW BLOCK", "2SEI", "class", "", "_HIDDEN"])
    def test_a_name_python_cannot_hold_is_refused(self, name):
        with pytest.raises(itemgen.GenerationError):
            itemgen.render([itemgen.EnumMember(name=name, value=1)])

    def test_a_name_enum_owns_is_refused(self):
        with pytest.raises(itemgen.GenerationError, match="shadows"):
            itemgen.render([itemgen.EnumMember(name="name", value=1)])

    def test_nothing_at_all_is_refused(self):
        with pytest.raises(itemgen.GenerationError, match="empty"):
            itemgen.render([])

    def test_what_it_writes_is_importable(self, tmp_path):
        """The renderer's output has to be a module, not merely a string."""
        body = itemgen.render(
            [
                itemgen.EnumMember(name="NULL", value=0),
                itemgen.EnumMember(name="USE_HONOO_SAKURETU", value=65),
            ]
        )
        path = tmp_path / "generated.py"
        path.write_text(body, encoding="utf-8", newline="\n")

        spec = importlib.util.spec_from_file_location("generated_itemids", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.ItemId.USE_HONOO_SAKURETU == 65
        assert module.ItemId(0).name == "NULL"


@pytest.mark.skipif(not items.ITEM_CATALOG.is_file(), reason="no item catalog")
@pytest.mark.usefixtures("invented_item_names")
class TestTheCommittedItemCatalog:
    """⚠️ ITEM_ID_MAX is 538 and every row is named -- both checked, because a
    catalog that silently lost its tail would still resolve every constant.

    The English tier needs words to resolve against and the catalog no longer
    ships any (D194), so these run against `tests/synthetic_msg.py`: invented
    names in a real `files/msg/UK` table, which is why they pass on a machine
    that has never seen the game."""

    def test_it_covers_every_id(self):
        names = items.load_items()
        assert len(names) == 538
        assert names.lookup(537) is not None
        assert names.lookup(538) is None

    def test_every_item_is_named(self):
        """⚠️ `is not None`, not truthiness: `ItemId.NULL` is 0 and therefore
        falsy, so `and found.enum` would report item 0 as unnamed. It did,
        the first time this ran against the enum (D119)."""
        assert all(
            found.name and found.enum is not None for found in items.load_items().items
        )

    def test_the_enum_and_the_table_agree(self):
        """Two independent sources: `itemName` came out of the DOL's `.data`,
        the constant out of spm-headers. `ITEM_ID_USE_HONOO_SAKURETU` sitting
        at the id whose `itemName` is `HONOO_SAKURETU` is what says the stride
        and the base address are right."""
        found = items.load_items().lookup(BLASTER_ID)
        assert found.name == "HONOO_SAKURETU"
        assert found.enum is ItemId.USE_HONOO_SAKURETU
        assert found.constant == "ITEM_ID_USE_HONOO_SAKURETU"
        assert found.english == BLASTER

    def test_an_english_name_resolves(self):
        """The whole runtime path in one line: the catalog's message key, the
        table under `BLECK_BASE_DIR`, and the tier that joins them."""
        assert items.load_items().resolve(BLASTER_WRITTEN).item.id == BLASTER_ID
