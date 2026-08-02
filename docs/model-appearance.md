# What the models are supposed to look like

⚠️ **This is secondary-source research, not measurement.** Everything in the
"canonical appearance" column comes from Nintendo artwork and screenshots
republished on the Super Mario Wiki, read by eye. It exists so that a render can
be judged against *something* rather than against an assumption — D251 spent its
first half chasing a palette-indexed-texture hypothesis for a robot nobody had
established the colour of.

⚠️ **A disagreement with the game's own data means the wiki may be the wrong
one.** Where the disc itself was consulted, the row says so and is marked ✅
*measured*; treat those as outranking the prose.

⚠️ **Super Paper Mario is Wii, 2007.** Paper Mario 64, The Thousand-Year Door,
Color Splash and The Origami King draw the same characters differently. Every
source below is an SPM page or an SPM-captioned image; nothing is carried across
from another game.

## Reference table

| model id | what it is | canonical appearance | conf | source |
|---|---|---|---|---|
| `e_lui_robo` | **Brobot**, Mr. L's robot (Whoa Zone, ch. 4) | Luigi-head-shaped. **Green cap**, pale blue-grey riveted body, **yellow octagonal eyes**, **brown moustache**, **red** arm joints/fists/thruster, cyan cockpit with Mr. L inside | ✅ | [Brobot](https://www.mariowiki.com/Brobot), [artwork](https://mario.wiki.gallery/images/1/19/Brobot.png), [in-game](https://mario.wiki.gallery/images/0/01/Brobot_Battle.png) |
| `e_lui_robo_hige` | Brobot's **moustache** (髭 *hige*) — a separate model | brown, boomerang-shaped | ✅ measured | disc + [Brobot L-type](https://www.mariowiki.com/Brobot_L-type) |
| `OFF_doorL` | left half of an `OFF_`-family two-sided door | two quads, one texture 表 (*omote*, front), one 裏 (*ura*, back) | ✅ measured | disc |
| `e_bari_beam` | the energy ring **Barribad** fires | a ring; **yellow-green**, not white | ✅ measured | disc + [Barribad](https://www.mariowiki.com/Barribad) |
| `p_bibi` | a **Catch Card** model — its one texture is Mario's card art | Mario on a purple/green star-patterned card | ✅ measured | disc |
| `e_2D_manera6` | **Mimi** (JP マネーラ *Manēra*) | green square head + green blocky pigtails, pink blushes, red bow, **yellow dress with white polka dots**, thin black stick limbs | ✅ | [Mimi](https://www.mariowiki.com/Mimi), [artwork](https://mario.wiki.gallery/images/9/9d/MimiSuperPaperMario.png) |

## Brobot — the answer to "is it white or coloured?"

**It is coloured, emphatically.** The [official
artwork](https://mario.wiki.gallery/images/1/19/Brobot.png) and the [in-game
screenshot](https://mario.wiki.gallery/images/0/01/Brobot_Battle.png) on
[mariowiki.com/Brobot](https://www.mariowiki.com/Brobot) agree region by region:

| region | colour |
|---|---|
| cap | Luigi green — bright lime top panels, darker olive sides |
| cockpit | cyan screen, dials and a green radar, **Mr. L visible inside** |
| face, nose, jaw | pale blue-grey riveted plate, black panel lines |
| eyes | **large yellow/gold octagonal domes with black pupils** |
| moustache | **dark brown**, sweeping across the lower face |
| arms | olive rods in green cage segments, **red** cylindrical joints, **red** ball fists |
| thruster | **red** faceted dome over an orange flame |

So yes to a **moustache**, yes to **eyes**, and the **red** sits on the arm
joints, the fists, the thruster and small hex bolts. A rip carrying `red.dds`,
`red2.dds`, `stache.png`, `eye.png` and `orange nut.dds` is describing this
robot accurately.

### Brobot vs Brobot L-type — not the wrong reference

[Brobot L-type](https://www.mariowiki.com/Brobot_L-type) (ch. 6-2) is
"upgraded with hands and feet"; the original has rod arms with ball fists and a
rocket where the legs would be. Its
[artwork](https://mario.wiki.gallery/images/6/60/BrobotArt.png) is otherwise the
**same palette** — same green cap, same grey body, same yellow eyes, same brown
moustache, same red. ✅ **The colour question does not depend on which form is
being compared**, so a white-grey render cannot be excused as "that's the other
one".

🔶 **Which form `e_lui_robo` is, is not established.** The disc splits the robot
across `e_lui_robo`, `_antena`, `_foot`, `_hand`, `_hige` and `_missile`; feet
and hands are L-type features, but whether both forms share one model set was
not checked.

### ✅ Measured: the colour is not in the textures, and that is correct

All 24 images in `e_lui_robo-`, and all of `_antena-`/`_foot-`/`_hand-`/
`_hige-`/`_missile-`, are **white line-art with black outlines** — panel edges,
rivets, vents — plus one yellow X plate, one cyan cockpit dashboard, purple
arrow panels and two 8×8 red dots. There is no green cap texture, no brown
moustache texture and no yellow eye texture anywhere in the bank.

**This is not a bug.** The hue is carried per-vertex, which D251 traced to
attribute slot 5. Decoding `COLOR_0` out of the current
`work/export/models/files/a/e_lui_robo.glb` gives 64 distinct values, and they
are the canonical palette above:

| `COLOR_0` rgb | region it matches |
|---|---|
| `0.71, 0.86, 0.87` | pale blue-grey body |
| `0.38, 0.56, 0.17` · `0.48, 0.70, 0.22` · `0.31, 0.45, 0.14` | cap greens |
| `0.78, 0.15, 0.15` · `0.55, 0.11, 0.11` · `0.45, 0.09, 0.09` | reds |
| `0.93, 0.73, 0.00` · `0.80, 0.62, 0.00` | eye gold |
| `0.88, 0.29, 0.15` · `0.75, 0.25, 0.13` | orange |
| `0.00, 0.00, 0.00` | outlines (3,224 vertices — the most common value) |

⚠️ **So a white-grey Brobot is a viewer that is ignoring `COLOR_0`, or a stale
`.glb`** — not a texture fault, and not a wrong reference. Only one copy of the
file exists (`work/export`); there is no `export-good` or `work/models` copy to
be looking at by mistake.

⚠️ The six Mario sprite frames sitting in `e_lui_robo-` are **D236's stray
quad**, not a mystery — the model's bounds run x −176.6 → +33.7 because a Mario
plane sits ~130 units to one side.

## `OFF_doorL` — the kanji is the game's own texture

✅ **Measured.** `OFF_doorL` is 8 positions / 4 triangles — two quads — with
exactly two 32×32 CMPR textures: one is **裏** (*ura*, back), the other **表**
(*omote*, front). Its shape is named `uraShape`. So a render showing 表 across
the door is showing what the disc contains; it is neither the wrong image nor a
decode failure.

`OFF_` is a 152-file family on this disc. It includes `OFF_card`,
`OFF_d_16pazu` (16-tile sliding puzzle), `OFF_d_four_meku` (めくる, *to flip
over*), `OFF_d_dokan_{up,down,left,right}` (pipes), `OFF_d_bom`, `OFF_d_kaiten`
(rotate), and `OFF_door{L,R}` with `_v` variants.

🔶 **What `OFF_` is, and whether these are ever drawn for the player, is not
established.** A card-flipping or tile puzzle is the obvious reading of
`OFF_card` + `meku` + 表/裏, and front/back labels are equally what a developer
places to check facing. ⛔ Do not record either as fact without finding the code
that loads them.

## `e_bari_beam` — a ring, and it should be yellow-green

`bari` is **Barribad** (JP バリバー *Baribā*, from "barrier"), a Whoa Zone enemy
that "wraps itself in a force field" and "shoots rings of energy"
([Barribad](https://www.mariowiki.com/Barribad)). A stronger white variant,
[Sobarribad](https://www.mariowiki.com/Sobarribad), appears in Castle Bleck.

✅ **Measured.** `e_bari_beam` is a single 18×18 quad. Its 144×144 texture is a
pure-white **annulus** in the alpha channel — geometry and shape are right. Its
two `COLOR_0` values are `0.99, 1.00, 0.45` and `0.71, 1.00, 0.23`, so the ring
should render as a **yellow-green gradient**. A plain white ring is the same
missing-`COLOR_0` symptom as Brobot, on a model small enough that it reads as
"probably fine".

✅ Separately, `e_bari-`'s first texture is a **mint/cyan sphere** — the barrier
bubble itself, which the wiki does not give a colour for.

## `p_bibi` — a Catch Card, not a character

✅ **Measured.** One 176×256 texture: **Mario's Catch Card** — Mario standing, on
a purple-and-green star-patterned background inside a pink border. No
`COLOR_0`; D251 notes its vertex colours are 192-of-192 opaque white, which is
why it looked right while Brobot did not.

🔶 **What "bibi" names is not established.** There is also an `e_card_bibi`,
whose texture is a **purple imp with a red-and-white striped floppy cap, pink
face and white gloves** — a different character from `p_bibi`'s Mario card, so
the `-bibi` suffix is not a shared character name. That enemy was not identified
against the wiki bestiary. ⛔ Do not assume it is a Pixl: the wiki gives Pixls a
single collective Japanese name (フェアリン) and lists no individual "ビビ"
([Pixl](https://www.mariowiki.com/Pixl)).

## `e_2D_manera6` — Mimi, confirmed

✅ **Confirmed.** Mimi's Japanese name is **マネーラ** (*Manēra*), from 真似
(*mane*, "copy") — [Mimi](https://www.mariowiki.com/Mimi). The model's animation
clips are all prefixed `2D_manera_`, and its first texture is unmistakably her.

Colours, from the [SPM
artwork](https://mario.wiki.gallery/images/9/9d/MimiSuperPaperMario.png) and
matching the disc texture:

- **head** — flat green square, lighter at the top; two green **blocky
  pigtails** made of offset squares
- **face** — green eyes with black lashes, black smile, **salmon-pink oval
  blushes** (the wiki notes her sprite uses a Rubee-shaped blush instead)
- **neck** — small **red bow tie**
- **body** — **yellow half-circle dress with white polka dots**, black outline
- **limbs** — thin black sticks, no hands or feet

Her **true form** is "an evil-looking robotic spider": the same green head, now
crumpled, on long thin black legs, with the yellow dress reduced to a curl
underneath —
[artwork](https://mario.wiki.gallery/images/5/56/SPM_Mimis_True_Form_Artwork.png).
🔶 Whether `e_2D_manera6`'s `6` selects a disguise, a form or an animation set
was not established.
