import pytest
import bpy
from .install_this import install_this, disable_this


@pytest.fixture(scope='session')
def install_addon():
    install_this(bpy.context)
    yield
    disable_this()


@pytest.fixture
def context(install_addon):
    return bpy.context