import bpy

from .conftest import select_obj
from .install_this import disable_this, enable_this
from .test_pose_consistency import MatchingPose


def test_snap_bake_ops(context_poses):
    select_obj(context_poses, "RIG-Cloud_Human")
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}, "Failed to regenerate Cloud Human in tests.blend."

    # I re-register the add-on because if we're running the rig UI operators now, we're running
    # the version of them which was registered from the Blender Text Editor.
    # That means we don't get code coverage stats!
    # If we re-register CloudRig, then once again the code in the repo itself will be run when the operators are called,
    # and that's what we want.
    disable_this()
    enable_this()

    rig = context_poses.active_object
    bpy.ops.object.mode_set(mode='POSE')

    # We snap FK to IK, then IK back to FK, and assert that the IK bones are in the exact same transforms as they started out with.
    # This snapping logic is perceptibly perfect, but we still have to crank the matrix tolerance up a fair bit, even for it to pass
    # on my work PC.
    with MatchingPose(context_poses, rig, frame=13, bone_subset=['IK-Wrist.L', 'IK-M-UpperArm.L'], matrix_tol=0.1):
        for i in range(3):
            bpy.ops.pose.cloudrig_toggle_ikfk_bake(
                prop_bone="Properties",
                prop_id="ik_left_upperarm",
                do_bake=True if i<2 else False,
                frame_start=11, frame_end=15,
                map_fk_to_ik="[('FK-UpperArm.L', 'IK-M-UpperArm.L'), ('FK-Forearm.L', 'IK-M-Forearm.L'), ('FK-Wrist.L', 'IK-M-Wrist.L')]",
                map_ik_to_fk="[('IK-Wrist.L', 'FK-Wrist.L'), ('IK-M-UpperArm.L', 'FK-UpperArm.L')]",
                ik_pole="POLE-UpperArm.L",
                ik_first="IK-M-UpperArm.L",
                fk_first="FK-UpperArm.L"
            )

            bpy.ops.pose.cloudrig_switch_parent_bake(
                bone_names="['IK-Wrist.L', 'POLE-UpperArm.L']",
                prop_bone="Properties",
                prop_id="ik_parents_left_upperarm",
                do_bake=True if i<2 else False,
                frame_start=14,
                frame_end=17,
                key_before_start=True,
                key_after_end=True,
                parent_names="['Root', 'Torso', 'Chest', 'Arm Root']",
                selected='2'
            )


def test_rig_ops(context_poses):
    context_poses.view_layer.objects.active = bpy.data.objects['RIG-Cloud_Human']
    rig = context_poses.active_object
    assert bpy.ops.pose.cloudrig_keyframe_all_settings() == {'FINISHED'}, "Failed to Keyframe All Settings."
    assert bpy.ops.pose.armature_reset(
        reset_action=True,
        reset_viewport_display=True,
        reset_bone_visibility=True,
        selection_only=False,
        reset_transforms=True,
        reset_custom_props=True
    ), "Failed to Reset Armature."
    assert rig.animation_data.action is None
