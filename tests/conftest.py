import pytest
import bpy
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
    blend_path = Path(__file__).parent / Path("tests.blend")
    bpy.ops.wm.open_mainfile(filepath=blend_path.as_posix())
    return context

@pytest.fixture
def scene_workflow(context_blend):
    select_scene_and_object(context_blend, 'Workflow Ops', 'META-Sintel')
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    return context_blend


@pytest.fixture
def scene_simple(context_blend):
    select_scene_and_object(context_blend, 'Simple', 'META-Simple')
    return context_blend

@pytest.fixture
def context_poses(context_blend):
    select_scene_and_object(context_blend, 'Poses')
    return context_blend

def select_scene_and_object(context, scene_name: str, obj_name=None):
    context.window_manager.windows[0].scene = bpy.data.scenes[scene_name]
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    if obj_name:
        obj = bpy.data.objects[obj_name]
        context.view_layer.objects.active = obj
        obj.hide_set(False)
        obj.select_set(True)
