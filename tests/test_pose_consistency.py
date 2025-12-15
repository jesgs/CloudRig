import bpy
import numpy as np
from bpy.types import Object, PoseBone
from mathutils import Matrix, Vector


def test_pose_consistency(context, scene_poses):
    metarigs_test(context)

#########################################

class MatchingPose:
    def __init__(self, context, rig: Object, *, frame: int, matrix_tol=0.001, bone_subset: list[str]=[]):
        self.context = context
        self.frame = frame
        self.rig_name = rig.name
        self.matrix_tol = matrix_tol
        self.bone_subset = bone_subset

    @property
    def rig(self):
        return bpy.data.objects.get(self.rig_name)

    def __enter__(self):
        self.context.scene.frame_current = self.frame
        self.context.view_layer.update()
        self.old_pose = pose_to_dict(self.rig, bone_subset=self.bone_subset, visible_only=True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.context.view_layer.update()
        self.context.scene.frame_current = self.frame
        new_pose = pose_to_dict(self.rig, bone_subset=self.bone_subset)
        assert_matching_pose(self.rig, self.old_pose, new_pose, matrix_tol=self.matrix_tol)

def metarigs_test(context):
    error_msg = []
    for metarig_name, frame in (
        ('META-toon_chain_tests_1', 10),
        ('META-Cloud_Human', 20),
        ('META-grid_chain_tests', 30),
        ('META-relinking', 40),
    ):
        metarig = bpy.data.objects[metarig_name]
        with MatchingPose(context, metarig.cloudrig.generator.target_rig, frame=frame):
            regenerate_rig(context, metarig)
        num_logs = len(metarig.cloudrig.generator.logs)
        if num_logs > 0:
            error_msg.append(f"{metarig.name} generated with {num_logs} warnings.")

    assert not error_msg, "\n".join(error_msg)

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

def pose_to_dict(rig: Object, *, bone_subset: list[str] = [], visible_only=True) -> dict[str, dict[str, str]]:
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
        if bone_subset and pb.name not in bone_subset:
            continue
        transforms[pb.name] = pbone_to_dict(pb)

    return transforms

def pbone_to_dict(pbone: PoseBone) -> dict:
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

def assert_matching_pose(rig: Object, old_pose: dict, new_pose: dict, *, matrix_tol=0.001):
    errors = []
    for bone_name, old_data in old_pose.items():
        new_data = new_pose.get(bone_name)
        if not new_data:
            errors.append(f'Bone missing: {bone_name}')
            continue

        for key, old_value in old_data.items():
            if isinstance(old_value, Matrix):
                # Bone matrix evaluation seems to be a bit non-deterministic across different machines!
                # The VM that runs tests needs this tolerance to be quite high, whereas my local machine passes the test even if this is 0.
                absolute_tolerance = matrix_tol
            else:
                absolute_tolerance = 1e-6
            new_value = new_data[key]
            if isinstance(old_value, Vector) or isinstance(old_value, Matrix):
                is_equal = np.allclose(np.array(old_value), np.array(new_value), atol=absolute_tolerance)
                old_value = np.array2string(np.array(old_value), precision=8, floatmode='fixed')
                new_value = np.array2string(np.array(new_value), precision=8, floatmode='fixed')
            elif type(old_value) is float:
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
