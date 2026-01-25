from pathlib import Path

import bpy
from bpy.types import Text


def test_run_in_blender(context):
    file = Path(__file__).parent / Path("run_in_blender.py")
    run_file_in_blender(file)

def test_post_gen_utils(context, scene_simple):
    post_gen = Path(__file__).parent / Path("post_gen.py")
    text = load_in_blender(post_gen)
    metarig = context.active_object
    metarig.cloudrig.generator.custom_script = text
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    # run_file_in_blender(post_gen)
    assert len(context.active_object.cloudrig.generator.logs) == 0

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

def run_file_in_blender(filepath: Path):
    text = load_in_blender(filepath)
    text.as_module()

def load_in_blender(filepath: Path) -> Text:
    text = bpy.data.texts.new(filepath.name)
    text.write(filepath.read_text())
    return text
