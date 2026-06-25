"""Order pose binds for hierarchical armatures (parents before children)."""

from __future__ import annotations

from typing import Iterable, List


def _bone_depth(armature, bone_name: str) -> int:
    if not armature or not bone_name:
        return 0
    bone = armature.pose.bones.get(bone_name)
    depth = 0
    while bone is not None and bone.parent is not None:
        depth += 1
        bone = bone.parent
    return depth


def sort_pose_binds(pose_binds: Iterable) -> List:
    """Return pose binds sorted shallow-to-deep on each armature."""
    items = list(pose_binds)
    return sorted(
        items,
        key=lambda pb: (
            int(pb.armature.as_pointer()) if getattr(pb, "armature", None) else 0,
            _bone_depth(pb.armature, pb.pose_bone),
            pb.pose_bone,
        ),
    )


def iter_pose_binds_sorted(pose_binds: Iterable):
    """Yield (original_index, pose_bind) in hierarchy apply order."""
    indexed = list(enumerate(pose_binds))
    indexed.sort(
        key=lambda item: (
            int(item[1].armature.as_pointer()) if getattr(item[1], "armature", None) else 0,
            _bone_depth(item[1].armature, item[1].pose_bone),
            item[1].pose_bone,
        ),
    )
    yield from indexed
