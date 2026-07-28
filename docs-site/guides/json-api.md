---
title: JSON API
description: Reading and editing mods from another program
---

`bleck`'s commands print for people. When you want a **program** to read or edit
a mod — an editor, a script, a web tool — use the JSON interface instead.

Every document is validated against a published JSON Schema, so a typo is an
error immediately rather than a mystery at build time.

## Reading

```bash
bleck mod export hard-lineland        # everything the mod declares
bleck setup show he1_01 --json        # what a map places, enemy names resolved
bleck setup edits hard-lineland --json  # just this mod's placement changes
```

```json
{
  "api_version": 1,
  "name": "hard-lineland",
  "version": "0.2.0",
  "base": "eu0",
  "setup": {
    "he1_01": [
      { "slot": 0, "template": 148, "clear": false },
      { "slot": 2, "template": 144,
        "position": { "x": -75.0, "y": 0.0, "z": -75.0 }, "clear": false }
    ]
  }
}
```

## Writing

```bash
bleck mod import hard-lineland --json edited.json
bleck setup apply hard-lineland --json edited.json
```

Both accept `-` for stdin, so a whole edit runs in one pipe:

```bash
bleck mod export hard-lineland | your-tool | bleck mod import hard-lineland --json -
```

!!! warning "Writing replaces, it does not merge"

    The document you send becomes the mod's declarations entirely. Merging would
    need a rule for *"the document omits a field — clear it or keep it?"*, and
    either answer surprises half of callers. Read the whole document, change it,
    send it back.

## Schemas

```bash
bleck mod schema                  # a whole mod
bleck setup schema --of edits     # placement changes
bleck setup schema --of map       # a map's current contents
```

Generate client types from these rather than hand-writing them — the schema and
the parser are the same declaration inside `bleck`, so they cannot drift apart.

## Versioning

Every top-level document carries `api_version`. Omit it when writing and the
current version is assumed; a document from a newer `bleck` is refused with a
message saying so, rather than being half-understood.

```json
{ "api_version": 1, "setup": {} }
```

If you are calling `bleck` as a Python library, `bleck.api` re-exports the
current version and `bleck.api.v1` pins to that one — import the pinned path if
you would rather fail at import than adapt silently when a v2 lands.

```python
from bleck.api.v1 import ModDocument

document = ModDocument.model_validate_json(text)
document.description = "edited in place"
print(document.model_dump_json(indent=2))
```

## What is not in these documents

**Overlay files.** A mod's overlay holds extracted game assets — textures,
archives, a compiled module. They are binary, often large, and already on disk;
carrying them through a document that is mostly a name would make every read
expensive. List them from the filesystem, or with `bleck mod status`.

## Two shapes, not one

`setup show` returns **every** slot in a map, with names resolved. `setup edits`
returns **only the slots a mod changes**.

That asymmetry is deliberate. Sending a whole map back as edits would rewrite a
hundred slots to change one, and would lose the difference between "left alone"
and "deliberately set to what it already was".

!!! note "One rule the API cannot enforce for you"

    The game stops reading a map's enemy entries at the first empty one, so
    clearing a slot with used slots after it silently discards them. `bleck`
    refuses that at build time and names the slots it would orphan — but an
    editor showing a delete button should know that removing a middle enemy is
    not a safe operation.
