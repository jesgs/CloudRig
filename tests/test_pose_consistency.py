import bpy
import numpy as np
import pytest
from bpy.types import Object, PoseBone
from mathutils import Matrix, Vector


def test_pose_consistency(context_poses):
    # This test is a bit overloaded but whatever.

    obj_frame_map = {
        # Tests foot roll, scale inheritance, limb stretching, FK hinge, probably more.
        "META-Cloud_Human": 20,
        # Tests Spine: Cartoon in 3-bone configuration
        "META-Cloud_Human_ToonSpine": 20,
        # Tests Spine:Cartoon in many-bone configuration (in this case 5)
        "META-Cloud_Human_ToonSpine_Long": 20,
        # Tests various constraint relinking configurations.
        "META-relinking": 40,
        # Tests Action Set-ups, rubber hose limbs, face grid component, intersection controls, center smooth intersections, probably more.
        "META-Sintel": 20,
    }

    # For Action Set-ups, test automatic creating of shape key drivers.
    sk_ob: Object = context_poses.scene.objects["ShapeKeyTest"]
    sk_ob.data.shape_keys.animation_data_clear()

    metarigs_test(context_poses, obj_frame_map)

    shape_keys = sk_ob.data.shape_keys.key_blocks
    assert (
        shape_keys["RIG-sintel_actions ➔ lips_smile.L"].value
        == shape_keys["lips_smile.L"].value
        == pytest.approx(0.730, abs=1e-3)
    )
    assert (
        shape_keys["RIG-sintel_actions ➔ lips_smile.R"].value
        == shape_keys["lips_smile.R"].value
        == pytest.approx(0.424, abs=1e-3)
    )
    assert (
        shape_keys["RIG-sintel_actions ➔ lips_smile"].value
        == shape_keys["lips_smile"].value
        == shape_keys["RIG-sintel_actions ➔ lips_smile+wide"].value
        == pytest.approx(0.0, abs=1e-3)
    )


def test_curves(context_curves):
    obj_frame_map = {
        "META-curves": 10,
        "META-curves_symmetry": 20,
        "META-spline_ik": 30,
        "META-curve_ik": 40,
    }
    metarigs_test(context_curves, obj_frame_map)


def test_chains(context_chains):
    obj_frame_map = {
        "META-toon_chain_tests_1": 10,
        "META-FK_Chains": 10,
        "META-IK_Chains": 10,
        "META-grid_chain_tests": 20,
        "META-grid_chain_tests_nobbones": 20,
    }
    metarigs_test(context_chains, obj_frame_map)


#########################################


class MatchingPose:
    def __init__(
        self,
        context,
        rig: Object,
        *,
        frame: int,
        matrix_tol=0.001,
        bone_subset: list[str] = [],
    ):
        self.context = context
        self.frame = frame
        self.rig_name = rig.name
        self.matrix_tol = matrix_tol
        self.bone_subset = bone_subset

    @property
    def rig(self):
        return bpy.data.objects.get(self.rig_name)

    def __enter__(self):
        if self.context.scene.frame_current != self.frame:
            self.context.scene.frame_current = self.frame
        self.context.view_layer.update()
        self.old_pose = pose_to_dict(
            self.rig, bone_subset=self.bone_subset, visible_only=True
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.context.view_layer.update()
        self.context.scene.frame_current = self.frame
        new_pose = pose_to_dict(self.rig, bone_subset=self.bone_subset)
        assert_matching_pose(
            self.rig, self.old_pose, new_pose, matrix_tol=self.matrix_tol
        )


def metarigs_test(context, obj_frame_map: dict[str, int]):
    error_msg = []
    for metarig_name, frame in obj_frame_map.items():
        metarig = bpy.data.objects[metarig_name]
        with MatchingPose(context, metarig.cloudrig.generator.target_rig, frame=frame):
            regenerate_rig(context, metarig)
        num_logs = len(metarig.cloudrig.generator.logs)
        if num_logs > 0:
            error_msg.append(f"{metarig.name} generated with {num_logs} warnings.")

    # assert not error_msg, "\n".join(error_msg)


def regenerate_rig(context, rig: Object):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    rig.hide_set(False)
    context.view_layer.objects.active = rig
    bpy.ops.pose.cloudrig_generate()


def update_expected_data(context, metarig: Object, frame: int):
    """This can be run manually in the .blend file if the rig results have changed on purpose."""
    context.scene.frame_current = frame
    metarig["expected_data"] = pose_to_dict(metarig.cloudrig.generator.target_rig)


def pose_to_dict(
    rig: Object, *, bone_subset: list[str] = [], visible_only=True, selectable_only=True
) -> dict[str, dict[str, str]]:
    """Crunch the pose of a rig into a data structure that can be stored in a custom property
    for later comparison.
    NOTE: We use list of list instead of list of tuples because tuples auto-convert
    to lists anyways when storing in a custom property."""
    if visible_only:
        pbones = [pb for pb in rig.pose.bones if is_pbone_visible(pb)]
    else:
        pbones = rig.pose.bones
    if selectable_only:
        pbones = [pb for pb in pbones if not pb.bone.hide_select]

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

    return {
        key: get_copy(pbone, key)
        for key in (
            "matrix",
            "bbone_scalein",
            "bbone_scaleout",
            "bbone_curveinx",
            "bbone_curveinz",
            "bbone_curveoutx",
            "bbone_curveoutz",
            "bbone_rollin",
            "bbone_rollout",
            "bbone_easein",
            "bbone_easeout",
        )
    }


def is_pbone_visible(pbone: PoseBone) -> bool:
    is_any_collection_visible = any(
        [coll.is_visible_effectively for coll in pbone.bone.collections]
    )
    if not is_any_collection_visible:
        return False
    return not pbone.hide


def assert_matching_pose(
    rig: Object, old_pose: dict, new_pose: dict, *, matrix_tol=0.001
):
    errors = []
    for bone_name, old_data in old_pose.items():
        new_data = new_pose.get(bone_name)
        if not new_data:
            errors.append(f"Bone missing: {bone_name}")
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
                is_equal = np.allclose(
                    np.array(old_value), np.array(new_value), atol=absolute_tolerance
                )
                old_value = np.array2string(
                    np.array(old_value), precision=8, floatmode="fixed"
                )
                new_value = np.array2string(
                    np.array(new_value), precision=8, floatmode="fixed"
                )
            elif type(old_value) is float:
                is_equal = np.isclose(new_value, old_value, rtol=1e-5, atol=1e-5)
                old_value = np.array2string(
                    np.array(old_value), precision=8, floatmode="fixed"
                )
                new_value = np.array2string(
                    np.array(new_value), precision=8, floatmode="fixed"
                )
            else:
                is_equal = old_value == new_value

            if not is_equal:
                errors.append(
                    f'Pose mismatch: {rig.name}.pose.bones["{bone_name}"].{key}:\n{new_value}\ninstead of\n{old_value}'
                )

    assert errors == [], "\n\n".join(errors)
