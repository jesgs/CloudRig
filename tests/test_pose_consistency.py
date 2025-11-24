import bpy
from bpy.types import Object, PoseBone
from mathutils import Vector, Matrix
import numpy as np

def test_pose_consistency(context_poses):
    metarigs_test(context_poses)

#########################################

def metarigs_test(context):
    for metarig_name, frame in (
        ('META-toon_chain_tests_1', 10),
        ('META-Cloud_Human', 20),
    ):
        context.scene.frame_current = frame
        context.view_layer.update()
        metarig = bpy.data.objects[metarig_name]
        old_pose = pose_to_dict(metarig.cloudrig.generator.target_rig, visible_only=True)
        regenerate_rig(context, metarig)
        context.view_layer.update()
        new_pose = pose_to_dict(metarig.cloudrig.generator.target_rig)
        assert_matching_pose(metarig.cloudrig.generator.target_rig, old_pose, new_pose)
        print(f"{metarig.name} generated with expected transforms.")

def regenerate_rig(context, rig: Object):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    rig.hide_set(False)
    context.view_layer.objects.active = rig
    bpy.ops.pose.cloudrig_generate()

def update_expected_data(context, metarig: Object, frame: int):
    """This can be run manually in the .blend file if the rig results have changed on purpose."""
    context.scene.frame_current = frame
    metarig['expected_data'] = pose_to_dict(metarig.cloudrig.generator.target_rig)

def pose_to_dict(rig: Object, visible_only=True) -> dict[str, dict[str, str]]:
    """Crunch the pose of a rig into a data structure that can be stored in a custom property
    for later comparison.
    NOTE: We use list of list instead of list of tuples because tuples auto-convert
    to lists anyways when storing in a custom property."""
    if visible_only:
        pbones = [pb for pb in rig.pose.bones if is_pbone_visible(pb)]
    else:
        pbones = rig.pose.bones

    transforms = {}
    for pb in sorted(pbones, key=lambda pb: pb.name):
        transforms[pb.name] = pbone_to_dict(pb)

    return transforms

def pbone_to_dict(pbone: PoseBone) -> dict[str]:
    def get_copy(owner, key):
        value = getattr(owner, key)
        if isinstance(value, Vector) or isinstance(value, Matrix):
            return value.copy()
        return value

    return {key:get_copy(pbone, key) for key in (
        'matrix',
        'bbone_scalein',
        'bbone_scaleout',
        'bbone_curveinx',
        'bbone_curveinz',
        'bbone_curveoutx',
        'bbone_curveoutz',
        'bbone_rollin',
        'bbone_rollout',
        'bbone_easein',
        'bbone_easeout',
    )}

def is_pbone_visible(pbone: PoseBone) -> bool:
    is_any_collection_visible = any([coll.is_visible_effectively for coll in pbone.bone.collections])
    if not is_any_collection_visible:
        return False
    return not pbone.hide

def assert_matching_pose(rig: Object, old_pose: dict, new_pose: dict):
    errors = []
    for bone_name, old_data in old_pose.items():
        new_data = new_pose[bone_name]

        for key, old_value in old_data.items():
            if isinstance(old_value, Matrix):
                absolute_tolerance = 0.001 # For some reason this has to be very high to pass on the runner when it should.
            else:
                absolute_tolerance = 1e-6
            new_value = new_data[key]
            if isinstance(old_value, Vector) or isinstance(old_value, Matrix):
                is_equal = np.allclose(np.array(old_value), np.array(new_value), atol=absolute_tolerance)
                old_value = np.array2string(np.array(old_value), precision=8, floatmode='fixed')
                new_value = np.array2string(np.array(new_value), precision=8, floatmode='fixed')
            elif type(old_value) == float:
                is_equal = np.isclose(new_value, old_value, atol=absolute_tolerance)
                old_value = np.array2string(np.array(old_value), precision=8, floatmode='fixed')
                new_value = np.array2string(np.array(new_value), precision=8, floatmode='fixed')
            else:
                is_equal = old_value == new_value

            if not is_equal:
                 errors.append(f'Pose mismatch: {rig.name}.pose.bones["{bone_name}"].{key}:\n{new_value}\ninstead of\n{old_value}')

    assert errors == [], "\n\n".join(errors)

# Paste this file into tests.blend, uncomment the below line, and run the script, to test that results are as expected.
# metarigs_test(bpy.context)