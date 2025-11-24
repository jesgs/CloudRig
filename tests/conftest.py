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
def context_sintel(context_blend):
    context_blend.window_manager.windows[0].scene = bpy.data.scenes['Sintel']
    context_blend.view_layer.objects.active = bpy.data.objects['META-Sintel']
    return context_blend

@pytest.fixture
def context_poses(context_blend):
    context_blend.window_manager.windows[0].scene = bpy.data.scenes['Poses']
    return context_blend