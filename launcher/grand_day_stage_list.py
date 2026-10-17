"""Open Grand Day at its retained Orario map-stage list on every fresh entry.

The original factory creates ArgoMapStageUIState with no selected stage, which
opens the missing legacy event_map layout. Returning from battle supplies a
stage ID and uses its intact location list instead. Seed the original first battle
stage before init, only for Grand Day. Other episodes keep the exact init call.
The wrapper occupies the already-disabled Firebase Initialize body.
"""

# Reading guide: Grand Day entry repair: branch() encodes ARM64 jumps; patches() emits
# guarded native replacements.
# Editing notes: Episode, stage, page and offsets belong to the retained game build.
# Preserve the guard so other events keep their original behavior.
# Checks: tools/maintain.py test native.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import struct

ENTRY = 0x1A5D288
WRAPPER = 0x2ADED00
EPISODE = 7160000101
FIRST_STAGE = 1160000101102
INITIALIZE = 0x19BAF10


def branch(source, target, link=False):
    """Encode an aligned ARM64 branch between verified instruction addresses."""
    offset = target - source
    if offset % 4 or not -(1 << 27) <= offset < (1 << 27):
        raise ValueError("Branch out of range")
    return (0x94000000 if link else 0x14000000) | ((offset // 4) & 0x3FFFFFF)


def patches():
    """Return the exact guarded native byte replacements for the retained build."""
    code = [
        0xD2800000 | ((EPISODE & 0xFFFF) << 5) | 8,
        0xF2A00000 | (((EPISODE >> 16) & 0xFFFF) << 5) | 8,
        0xF2C00000 | (((EPISODE >> 32) & 0xFFFF) << 5) | 8,
        0xEB08003F,  # cmp x1,x8 (episode passed to native initializer)
        0x540000E1,  # b.ne tail call, preserving all other episodes
        0xD2800000 | ((FIRST_STAGE & 0xFFFF) << 5) | 8,
        0xF2A00000 | (((FIRST_STAGE >> 16) & 0xFFFF) << 5) | 8,
        0xF2C00000 | (((FIRST_STAGE >> 32) & 0xFFFF) << 5) | 8,
        0xF9000000 | ((0x4B0 // 8) << 10) | 8,  # state selected stage
        0x52800028,  # mov w8,#1: original Orario map page
        0xB9000000 | ((0x4BC // 4) << 10) | 8,
        branch(WRAPPER + 44, INITIALIZE),
    ]
    # Grand Day's Back leaves the event instead of opening the absent map top.
    back = WRAPPER + 64
    back_code = [
        0xF9400000 | ((0x4A8 // 8) << 10) | 8,
        0xD2800000 | ((EPISODE & 0xFFFF) << 5) | 9,
        0xF2A00000 | (((EPISODE >> 16) & 0xFFFF) << 5) | 9,
        0xF2C00000 | (((EPISODE >> 32) & 0xFFFF) << 5) | 9,
        0xEB09011F,
        0x54000041,
        branch(back + 24, 0x19BE884),
        0xB9446408,  # displaced ldr w8,[x0,#0x464]
        0x35000048,  # cbnz w8, final branch
        branch(back + 36, 0x19BE884),
        branch(back + 40, 0x19BE868),
    ]
    return {
        0x19BE860: struct.pack("<I", branch(0x19BE860, back)),
        back: struct.pack("<11I", *back_code),
        ENTRY: struct.pack("<I", branch(ENTRY, WRAPPER, True)),
        WRAPPER: struct.pack("<12I", *code),
    }
