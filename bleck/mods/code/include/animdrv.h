/*
    The animation driver, as this project has measured it.

    Addresses and struct offsets are facts, and this file records the ones read
    out of the game's own code rather than out of a header. Nothing here is
    derived from spm-headers -- `animdrv.h` does not exist upstream, and the
    names below are this project's.

    ⚠️ **eu0 only.** Every address is PAL rev 0. `code.target` carries the
    version and nothing here is portable to us0 without re-measuring.

    Where each fact came from:

        D288  the pose table, its stride, and the 60 Hz clock
        D289  slot 20 is a u8 per node, 0 meaning the node is not drawn
        D290  animPoseMain copies four section arrays into the pose
        D291  the runtime node block changes during play
        D292  the walker, and the draw gate that reads slot 20
        D295  the local matrix: two rotation sets, z then y then x

    Full reasoning in docs/function-behaviour.md and docs/model-format.md.
*/

#ifndef BLECK_ANIMDRV_H
#define BLECK_ANIMDRV_H

/*
    animGetPtr() is `lwz r3,-32680(r13); blr`, and r13 is 0x805B5F00, so the
    driver's work pointer is here (D288).
*/
#define ANIMDRV_WP 0x805ADF58

/*
    The work struct, as animPoseGetAnimPosePtr (0x8004c660) and
    animPoseGetAnimBaseDataPtr (0x8004c828) index it. Both bounds-check an
    index against `poseCount` and assert when it is out of range.
*/
#define ANIMDRV_BASE_TABLE 0x00  /* 16 bytes an entry                        */
#define ANIMDRV_POSES      0x10  /* the AnimPose array                       */
#define ANIMDRV_POSE_COUNT 0x14  /* 384 on eu0                               */

/* +0x04..+0x0C is unread, so this is offsets rather than fields for the same
   reason AnimPose is: naming padding would assert something unmeasured. */

/*
    One AnimPose. The stride is `mulli r31,r30,392` in both accessors, and
    `clrlwi. r0,r0,31` on the first word is the in-use test -- the assert
    fires when bit 0 is clear (D288).

    ⚠️ The four pointers at +0x50..+0x70 are *copies* animPoseMain makes of the
    model's own section arrays, not pointers into the model (D290). The game
    owns them afterwards and may change them, which is why the visibility array
    has to be read here rather than from the file to know what is drawn.
*/
#define ANIM_POSE_STRIDE 392

/*
    ⚠️ **Offsets, not a struct, and deliberately.** Writing this as C fields
    would commit to padding between them, and the padding is not established:
    animPoseMain's five copies land 8 bytes apart (+0x50, +0x58, +0x60, +0x68,
    +0x70) while a live dump reads a plausible pointer at *every* 4-byte word
    across 0x50..0x74, several of them in equal pairs. A (start, end) pair per
    block fits and is not proven, so nothing here asserts it.

    Read them with ANIM_POSE_FIELD until somebody measures the pairing.
*/
#define ANIM_POSE_FLAGS       0x00  /* bit 0 = in use                        */
#define ANIM_POSE_BASE_INDEX  0x10  /* into AnimDrvWork.baseTable            */
#define ANIM_POSE_FRAMES      0x20  /* f32 elapsed frames; 60.06 Hz measured */
#define ANIM_POSE_CLIP_TIME   0x24  /* f32, wrapped at the clip's own length */
#define ANIM_POSE_KEY_NOW     0x30  /* current keyframe index                */
#define ANIM_POSE_KEY_NEXT    0x34
#define ANIM_POSE_BLEND       0x38  /* f32 0..1 between those two keys       */
#define ANIM_POSE_KEY_OTHER   0x44  /* a second channel's key index          */
#define ANIM_POSE_BLEND_OTHER 0x48

/* The copies animPoseMain makes, in the order it makes them (D290). */
#define ANIM_POSE_POSITIONS  0x50  /* slot 2,  12 bytes an element           */
#define ANIM_POSE_NORMALS    0x58  /* slot 3,  12 bytes an element           */
#define ANIM_POSE_VISIBLE    0x60  /* slot 20, ONE BYTE a node               */
#define ANIM_POSE_TRANSFORMS 0x68  /* slot 21, 96 bytes a node               */
#define ANIM_POSE_LAYERS     0x70  /* slot 16, 24 bytes an element           */

#define ANIM_POSE_FIELD(pose, at, type) (*(type *) ((char *) (pose) + (at)))

/*
    A slot 22 node record: what the walker at 0x80048c48 reads.

    ⚠️ `index` is the node's own number, and it is what subscripts
    AnimPose.visible -- `lwz r0,76(r31); lbzx r0,r4,r0` (D292). It looked like
    a redundant copy of the array position until the draw code named its use.

    ⚠️ `transformWords` is `index * 24`, and the walker shifts it left by two
    to reach `index * 96` in AnimPose.transforms. Stored pre-multiplied.
*/
#define ANIM_NODE_STRIDE 88

typedef struct AnimNode
{
    char name[0x20];         /* +0x00, the Maya name                         */
    char _pad20[0x20];
    int previousSibling;     /* +0x40, -1 at the end of a run                */
    int lastChild;           /* +0x44, -1 for a leaf                         */
    int shape;               /* +0x48, -1 for a node that only groups        */
    int index;               /* +0x4C, subscripts AnimPose.visible           */
    int transformWords;      /* +0x50, index * 24                            */
    int flag54;              /* +0x54, 1 on the arm joints; unread           */
} AnimNode;

/*
    The section-table slots this file is about. The table is at 0x150 in a
    model file, so slot N is at 0x150 + N * 4 (see docs/model-format.md).
*/
#define MODEL_SECTIONS_AT     0x150
#define MODEL_SLOT_VISIBLE    20
#define MODEL_SLOT_TRANSFORMS 21
#define MODEL_SLOT_NODES      22

/*
    Measured entry points. ⚠️ Only animPoseMain is named upstream; the walker
    is unnamed in spm.eu0.lst and `animPoseWalkNode` is this project's name for
    it, chosen to describe what it does rather than to guess at Nintendo's.
*/
#define ANIM_POSE_MAIN      0x80045288
#define ANIM_POSE_WALK_NODE 0x80048c48  /* recursive: child, then sibling    */
#define ANIM_GET_PTR        0x8004158c

/*
    A slot 21 record: 24 floats, the local transform of one node (D287, D295).

        [0..2]    translate
        [3..5]    scale
        [6..8]    rotation in degrees -- DOUBLED before use, see below
        [9..11]   a second rotation set, in degrees, applied first
        [12..14]  a pivot; not yet known to be used
        [15..23]  unread

    The walker builds the local matrix as, skipping any block that would be
    the identity:

        R = Rz(f11) . Ry(f10) . Rx(f9) . Rz(2*f8) . Ry(2*f7) . Rx(2*f6)

    Every angle is multiplied by pi/180 (0.01745329238474369, measured at
    r2-30736). ⚠️ The 2.0 on floats 6..8 is measured at r2-30792 and there is
    no branch around it -- it is what the code does, whether or not it reads
    as a tidy convention. Do not vary it to make a render look right.

    ⚠️ The parent's SCALE is threaded down, not its whole matrix, and a node
    with no parent uses (1, 1, 1).
*/
#define ANIM_XFORM_TRANSLATE 0   /* float index, not a byte offset           */
#define ANIM_XFORM_SCALE     3
#define ANIM_XFORM_ROTATE    6   /* degrees, doubled before pi/180           */
#define ANIM_XFORM_ROTATE2   9   /* degrees, applied before the above        */
#define ANIM_XFORM_PIVOT     12
#define ANIM_XFORM_FLOATS    24

/* The SDK calls the composer uses. The last two are unnamed upstream; the
   axis argument to the rotate is an ASCII 'x', 'y' or 'z'. */
#define PSMTX_IDENTITY 0x8027a270
#define PSMTX_TRANS    0x8027a7b4
#define PSMTX_SCALE    0x8027a834
#define PSMTX_ROT_RAD  0x8027a55c  /* (Mtx, char axis, f32 radians)          */
#define PSMTX_CONCAT   0x8027a2d0  /* (a, b, ab) -> ab = a . b               */

/*
    ⛔ What the walker composes is now largely decoded (D295), but the
    exporter still does NOT apply it. It indexes the transform block
    per node; the rotation order, whether the pivot is applied, and what the
    unaccounted floats hold are all unread (D292). `bleck` therefore exports
    every model unposed, and applying slot 21 on the strength of the offsets
    above would move 489 models on an inference.
*/

#endif
