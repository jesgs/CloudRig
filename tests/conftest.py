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
    ctx = bpy.context
    # Some CloudRig drivers need Python script execution.
    ctx.preferences.filepaths.use_scripts_auto_execute = True
    return ctx

#############################

@pytest.fixture
def context_curves(context):
    load_blend("test_curves.blend")
    return context

@pytest.fixture
def context_workflow(context):
    load_blend("test_workflow_ops.blend")
    select_obj(context, 'META-Sintel')
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    return context

@pytest.fixture
def context_simple(context):
    load_blend("test_simple.blend")
    select_obj(context, 'META-Simple')
    return context

@pytest.fixture
def context_poses(context) -> Scene:
    load_blend("test_poses.blend")
    return context

@pytest.fixture
def context_chains(context) -> Scene:
    load_blend("test_chains.blend")
    return context

#############################

def load_blend(blend_name: str):
    blend_path = Path(__file__).parent / Path(f"blends/{blend_name}")
    bpy.ops.wm.open_mainfile(filepath=blend_path.as_posix())
    bpy.context.workspace.use_filter_by_owner = False

def select_obj(context, obj_name=None):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    if obj_name:
        obj = bpy.data.objects[obj_name]
        # Some naive un-hiding...
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
        context.view_layer.objects.active = obj
