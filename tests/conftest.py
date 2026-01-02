import pytest
import bpy
from bpy.types import Scene
from .install_this import install_this, disable_this
from pathlib import Path

@pytest.fixture(scope='session')
def install_addon():
    install_this(bpy.context)
    yield
    disable_this()

@pytest.fixture
def context(install_addon):
    return bpy.context

@pytest.fixture
def context_blend(context):
    """We're using a single tests.blend file with different Scenes.
    A Scene can be used by multiple tests. If a test would benefit from a new
    Scene set-up, just add it in the .blend (and a new fixture).
    This file gets loaded many times while running tests, so keep it light.
    """
    blend_path = Path(__file__).parent / Path("tests.blend")
    bpy.ops.wm.open_mainfile(filepath=blend_path.as_posix())
    return context

@pytest.fixture
def scene_workflow(context_blend) -> Scene:
    scene = select_scene_and_object(context_blend, 'Workflow Ops', 'META-Sintel')
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    return scene

@pytest.fixture
def scene_simple(context_blend) -> Scene:
    scene = select_scene_and_object(context_blend, 'Simple', 'META-Simple')
    return scene

@pytest.fixture
def scene_poses(context_blend) -> Scene:
    scene = select_scene_and_object(context_blend, 'Poses')
    return scene

def select_scene_and_object(context, scene_name: str, obj_name=None) -> Scene:
    context.window_manager.windows[0].scene = bpy.data.scenes[scene_name]
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    if obj_name:
        obj = bpy.data.objects[obj_name]
        context.view_layer.objects.active = obj
        obj.hide_set(False)
        obj.select_set(True)
    return context.scene
