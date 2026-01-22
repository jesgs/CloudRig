from pathlib import Path

import bpy
import pytest
from bpy.types import Scene

from .install_this import disable_this, install_this


@pytest.fixture(scope='session')
def install_addon():
    install_this(bpy.context)
    yield
    disable_this()

@pytest.fixture
def context(install_addon):
    return bpy.context


#############################

def load_blend(blend_name: str):
    blend_path = Path(__file__).parent / Path(f"blends/{blend_name}")
    bpy.ops.wm.open_mainfile(filepath=blend_path.as_posix())

@pytest.fixture
def context_misc(context):
    """Load shared tests blend file, which contains some scenes useful for running tests.
    TODO: This blend file should be split up into multiple smaller files.
    """
    load_blend("misc.blend")
    return context

@pytest.fixture
def context_curves(context):
    load_blend("curves.blend")
    return context

#############################

@pytest.fixture
def scene_workflow(context_misc) -> Scene:
    scene = select_scene_and_object(context_misc, 'Workflow Ops', 'META-Sintel')
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    return scene

@pytest.fixture
def scene_simple(context_misc) -> Scene:
    return select_scene_and_object(context_misc, 'Simple', 'META-Simple')

@pytest.fixture
def scene_poses(context_misc) -> Scene:
    return select_scene_and_object(context_misc, 'Poses')

def scene_curves(context_curves):
    return select_scene_and_object(context_curves, obj_name='META-curves')

def select_scene_and_object(context, scene_name="Scene", obj_name=None) -> Scene:
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
