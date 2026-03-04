from pathlib import Path

import bpy
from bpy.types import Text
from mathutils import Vector

from .test_generate_metarigs import generate_without_errors


def test_run_in_blender(context):
    file = Path(__file__).parent / Path("run_in_blender.py")
    run_file_in_blender(file)

def test_post_gen_utils(context_simple):
    post_gen = Path(__file__).parent / Path("post_gen.py")
    text = load_in_blender(post_gen)
    metarig = context_simple.active_object
    metarig.cloudrig.generator.custom_script = text
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    # run_file_in_blender(post_gen)
    assert len(context_simple.active_object.cloudrig.generator.logs) == 0

def test_bone_colors(context):
    assert bpy.ops.preferences.set_bone_color_presets(preset='BLENDER') == {'FINISHED'}
    assert bpy.ops.preferences.set_bone_color_presets(preset='CLOUDRIG') == {'FINISHED'}

def test_naming_functions():
    from CloudRig.generation.naming import get_name_parts
    assert get_name_parts("Left Left Bone Left Left.001") == ("Left ", "Left Bone Left Left", "", ".001")
    assert get_name_parts("Left Bone.L.001") == ("", "Left Bone", ".L", ".001")
    assert get_name_parts("L_Bone.Left.001") == ("L_", "Bone.Left", "", ".001")
    assert get_name_parts("Bone.Left.001") == ("", "Bone", ".Left", ".001")
    assert get_name_parts("LeftBone.Left.001") == ("Left", "Bone.Left", "", ".001")

def test_bone_tweak(context_simple):
    generate_without_errors(context_simple, bpy.context.active_object)
    generated_rig = bpy.context.active_object
    tweaked_pb = generated_rig.pose.bones['Properties']
    # TODO: Test additive constraints and Ensure Free Transforms?
    assert tweaked_pb.constraints[0].target == generated_rig, "Failed to relink constraint"
    assert tweaked_pb.parent.name == "P-"+tweaked_pb.name, "Failed to create parent helper"
    assert tweaked_pb.parent.constraints[0].targets[0].subtarget == 'root', "Failed to ensure free transforms or relink constraint"
    assert tweaked_pb.bone.y_axis.z < 0.001, "Failed to tweak bone transforms"
    assert tweaked_pb.lock_rotation[:] == (True, True, True), "Failed to tweak transform locks"
    assert tweaked_pb.rotation_mode == 'ZYX', "Failed to tweak rotation mode"
    assert tweaked_pb.bone.display_type == 'BBONE', "Failed to tweak bone display"
    assert tweaked_pb.custom_shape.name == 'WGT-Cog 2', "Failed to tweak bone display"
    assert tweaked_pb.custom_shape_scale_xyz == Vector((0.9, 0.9, 0.9)), "Failed to tweak bone display"
    assert tweaked_pb.bone.collections[:] != [], "Failed to tweak bone collections"
    assert tweaked_pb.bone.color.palette == 'CUSTOM', "Failed to tweak bone color"
    assert tweaked_pb.lock_ik_x, "Failed to tweak IK settings"
    assert abs(tweaked_pb.bone.bbone_x-0.123) <= 0.001, "Failed to tweak BBone settings"




def run_file_in_blender(filepath: Path):
    text = load_in_blender(filepath)
    text.as_module()

def load_in_blender(filepath: Path) -> Text:
    text = bpy.data.texts.new(filepath.name)
    text.write(filepath.read_text())
    return text
