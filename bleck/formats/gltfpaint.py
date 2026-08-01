"""Turning a shape's texture layers into glTF materials, samplers and images.

Split out of `gltf` because that module writes the *geometry* and was already
near the size at which nobody reads the whole file. Everything here is about
one question: given the layers a shape draws with, what does a reader have to
be handed to draw the same thing?

## A layer is an image plus how to sample it

✅ **Wrap mode is read from the file** (D247). It maps onto glTF `samplers`
exactly -- CLAMP_TO_EDGE, REPEAT and MIRRORED_REPEAT are the three GX offers --
so a sampler per distinct pair is written and shared.

⛔ **The single `{"wrapS": REPEAT, "wrapT": REPEAT}` sampler every export
carried until now was an assumption**, and it was wrong for 6,760 of the disc's
7,300 layers.

✅ **The UV transform is read too** (D247), and `KHR_texture_transform` is the
extension that carries it. It is named in `extensionsUsed` and never in
`extensionsRequired`: a reader that ignores it draws the untransformed texture,
which is what every reader did before this and is strictly better than refusing
the file.

## The second layer is a mask, and glTF has no slot for it

✅ **A two-layer shape multiplies the base by the second layer's alpha**
(D247) -- colour *and* alpha, with the second layer's RGB never sampled. The
TEV program the game selects for those 40 shapes is

    stage 0   prev      = tex0
    stage 1   prev      = tex1.a * prev          <- the mask
    stage 2   prev      = ras * prev

⛔ **There is no core glTF slot that means this.** `occlusionTexture` only
dims indirect light and cannot touch alpha; `emissiveTexture` adds rather than
multiplies. Claiming either would put a number in a field that means something
else, and a reader honouring it would draw the wrong thing while looking right.

So the mask goes in `material.extras`, which the specification reserves for
exactly this. Blender and every other reader ignore it and draw the base layer;
`dimentio` reads it and multiplies. ⚠️ The image is still a real `textures`
entry with its own sampler, so it is reachable rather than dangling -- which is
the check D245 added after ten files shipped art nothing referenced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: glTF sampler wrap modes, against `GXTexWrapMode`.
CLAMP_TO_EDGE = 33071
REPEAT = 10497
MIRRORED_REPEAT = 33648
WRAPPING = (CLAMP_TO_EDGE, REPEAT, MIRRORED_REPEAT)

#: What a reader that has never seen this repo needs in order to find the mask.
#: ⚠️ **Namespaced on purpose.** `extras` is a free-for-all shared with every
#: other tool that has ever touched the file.
MASK_KEY = "spmMaskTexture"

TRANSFORM_EXTENSION = "KHR_texture_transform"


@dataclass(frozen=True)
class Surface:
    """One texture reference: an image, how to sample it, and where.

    `image` is the model's own image index -- what `Part.textures` names -- not
    a position in any list the writer has built yet.
    """

    image: int
    wrap_s: int = REPEAT
    wrap_t: int = REPEAT
    offset_u: float = 0.0
    offset_v: float = 0.0
    rotation: float = 0.0
    scale_u: float = 1.0
    scale_v: float = 1.0

    @property
    def moves(self) -> bool:
        """Whether this reference needs `KHR_texture_transform` at all."""
        return (self.offset_u, self.offset_v, self.rotation) != (0.0, 0.0, 0.0) or (
            self.scale_u,
            self.scale_v,
        ) != (1.0, 1.0)


def surface_of(layer, fallback: int = REPEAT) -> Surface:
    """A `modelmat.Layer` as the reference a glTF material makes to it.

    ⚠️ **Accepts a bare integer too.** A hand-built `Mesh` names its images by
    index and has no layer table behind it; refusing those would mean every
    fixture in the tests had to grow one.

    A layer whose wrap word was negative asks for the image's own default,
    which glTF has no way to express -- `fallback` is what those get.
    """
    if isinstance(layer, int):
        return Surface(image=layer, wrap_s=fallback, wrap_t=fallback)
    shift = layer.transform
    return Surface(
        image=layer.material,
        wrap_s=_wrap(layer.wrap.s, fallback),
        wrap_t=_wrap(layer.wrap.t, fallback),
        offset_u=shift.offset.u,
        offset_v=shift.offset.v,
        rotation=shift.radians,
        scale_u=shift.scale.u,
        scale_v=shift.scale.v,
    )


def _wrap(mode: int, fallback: int) -> int:
    return WRAPPING[mode] if 0 <= mode < len(WRAPPING) else fallback


@dataclass(frozen=True)
class Choice:
    """What one primitive ended up drawing: a base surface, and maybe a mask."""

    base: Surface
    mask: Surface | None = None


@dataclass
class _Sheet:
    """The samplers, images, textures and materials written so far.

    Everything is deduplicated on the whole description rather than on the
    image: two shapes can name one picture and clamp it differently, and one
    material for both would silently pick whichever was seen first.
    """

    samplers: list = field(default_factory=list)  # pylint: disable=container-return
    images: list = field(default_factory=list)  # pylint: disable=container-return
    textures: list = field(default_factory=list)  # pylint: disable=container-return
    materials: list = field(default_factory=list)  # pylint: disable=container-return
    _sampler_at: dict = field(default_factory=dict)
    _image_at: dict = field(default_factory=dict)
    _texture_at: dict = field(default_factory=dict)
    _material_at: dict = field(default_factory=dict)

    def sampler(self, wrap_s: int, wrap_t: int) -> int:
        key = (wrap_s, wrap_t)
        if key not in self._sampler_at:
            self._sampler_at[key] = len(self.samplers)
            self.samplers.append({"wrapS": wrap_s, "wrapT": wrap_t})
        return self._sampler_at[key]

    def image(self, index: int, view: int) -> int:
        if index not in self._image_at:
            self._image_at[index] = len(self.images)
            self.images.append({"bufferView": view, "mimeType": "image/png"})
        return self._image_at[index]

    def texture(self, surface: Surface, view: int) -> int:
        key = (surface.image, surface.wrap_s, surface.wrap_t)
        if key not in self._texture_at:
            self._texture_at[key] = len(self.textures)
            self.textures.append(
                {
                    "sampler": self.sampler(surface.wrap_s, surface.wrap_t),
                    "source": self.image(surface.image, view),
                }
            )
        return self._texture_at[key]

    def material(self, choice: Choice, base: int, mask: int | None) -> int:
        key = (choice.base, choice.mask)
        if key not in self._material_at:
            self._material_at[key] = len(self.materials)
            self.materials.append(_material(choice, base, mask))
        return self._material_at[key]


def _reference(surface: Surface, texture: int) -> dict:
    # pylint: disable=container-return
    """One `textureInfo`, carrying its UV transform when it has one."""
    made: dict = {"index": texture}
    if surface.moves:
        made["extensions"] = {
            TRANSFORM_EXTENSION: {
                "offset": [surface.offset_u, surface.offset_v],
                "rotation": surface.rotation,
                "scale": [surface.scale_u, surface.scale_v],
            }
        }
    return made


def material_over(surface: Surface, texture: int) -> dict:
    # pylint: disable=container-return
    """One glTF material over one base layer."""
    return {
        "pbrMetallicRoughness": {
            "baseColorTexture": _reference(surface, texture),
            "metallicFactor": 0.0,
            "roughnessFactor": 1.0,
        },
        # ⚠️ Game art is cut out with alpha, and the default OPAQUE mode
        # ignores it -- every transparent pixel renders black.
        "alphaMode": "MASK",
        "doubleSided": True,
    }


def _material(choice: Choice, base: int, mask: int | None) -> dict:
    # pylint: disable=container-return
    """One glTF material over a base layer, and its mask if it has one."""
    made = material_over(choice.base, base)
    if mask is not None and choice.mask is not None:
        made["extras"] = {MASK_KEY: _reference(choice.mask, mask)}
    return made


def _choose(part, ready: dict) -> Choice | None:
    """The base layer a primitive draws, and the mask over it.

    ⚠️ **The first layer whose image decoded, not the first layer.** A bank
    that is short of an image should cost the shape its texture, not shift the
    mask into the colour slot.
    """
    usable = [surface_of(layer) for layer in part.textures]
    usable = [surface for surface in usable if surface.image in ready]
    if not usable:
        return None
    return Choice(base=usable[0], mask=usable[1] if len(usable) > 1 else None)


def paint(document: dict, blob, primitives: list, parts: list, paints: list) -> None:
    """Give each primitive the layers its shape draws with.

    ✅ **Per shape, not per file** (D243). A model's shapes each name their own
    image through the layer table, so a file carries as many glTF materials as
    its shapes reach -- `e_lui_robo` writes 15 over 92 primitives.

    ⚠️ A primitive with no texture coordinates gets no material at all rather
    than an untextured one, because a reader that finds `TEXCOORD_0` missing
    and a `baseColorTexture` present samples nothing and draws black.

    ⛔ **An image no primitive reaches is not embedded** (D245). Writing every
    image the caller decoded left ten files carrying art nothing referenced --
    bytes a reader downloads, decodes and never draws -- and made the manifest
    call them textured when they open bare.
    """
    ready = {paint_.index: paint_.png for paint_ in paints if paint_.png}
    picks = []
    for primitive, part in zip(primitives, parts, strict=True):
        if "TEXCOORD_0" not in primitive["attributes"]:
            continue
        chosen = _choose(part, ready)
        if chosen is not None:
            picks.append((primitive, chosen))
    if not picks:
        return

    sheet = _Sheet()
    views: dict[int, int] = {}

    def view_for(index: int) -> int:
        if index not in views:
            views[index] = blob.add(ready[index])
        return views[index]

    for primitive, chosen in picks:
        base = sheet.texture(chosen.base, view_for(chosen.base.image))
        mask = None
        if chosen.mask is not None:
            mask = sheet.texture(chosen.mask, view_for(chosen.mask.image))
        primitive["material"] = sheet.material(chosen, base, mask)

    document["images"] = sheet.images
    document["samplers"] = sheet.samplers
    document["textures"] = sheet.textures
    document["materials"] = sheet.materials
    if any(surface.moves for surface in _referenced(picks)):
        document["extensionsUsed"] = [TRANSFORM_EXTENSION]


def _referenced(picks: list):
    """Every surface any primitive ended up naming."""
    for _, chosen in picks:
        yield chosen.base
        if chosen.mask is not None:
            yield chosen.mask
