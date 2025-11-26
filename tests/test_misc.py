import bpy
from bpy.types import Text
from pathlib import Path

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
    bpy.ops.preferences.set_bone_color_presets('INVOKE_DEFAULT', preset='CLOUDRIG')

def run_file_in_blender(filepath: Path):
    text = load_in_blender(filepath)
    text.as_module()

def load_in_blender(filepath: Path) -> Text:
    text = bpy.data.texts.new(filepath.name)
    text.write(filepath.read_text())
    return text