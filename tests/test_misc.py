import bpy
from pathlib import Path

def test_run_in_blender(context):
    file = Path(__file__).parent / Path("run_in_blender.py")
    run_file_in_blender(file)

def run_file_in_blender(filepath: Path):
    text = bpy.data.texts.new(filepath.name)
    text.write(filepath.read_text())
    text.as_module()
