import bpy
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, IntProperty
from bpy.types import PropertyGroup
from . import rigs
import inspect

def get_param_classes():
    ret = {}
    for name, module in inspect.getmembers(rigs, inspect.ismodule):
        if hasattr(module, 'Params'):
            ret[name.replace("cloud_", "")] = module.Params
    return ret

class RigParams(PropertyGroup):
    # TODO: Some params would have to be grabbed from the rig_features package.

    __annotations__ = {
        name : PointerProperty(type=param_class)
        for name, param_class in get_param_classes().items()
    }

class RigElement(PropertyGroup):
	owner_bone: StringProperty()
	params: PointerProperty(type=RigParams)

class GeneratorParameters(PropertyGroup):
    advanced_mode: BoolProperty()

class CloudRigProperties(PropertyGroup):
    rig_elements: CollectionProperty(type=RigElement)
    generator: PointerProperty(type=GeneratorParameters)
    metarig_version: IntProperty()

registry = list(get_param_classes().values()) + [
    RigParams,
    RigElement,
    GeneratorParameters,
    CloudRigProperties
]

def register():
    bpy.types.Armature.cloudrig = PointerProperty(type=CloudRigProperties)

def unregister():
    del bpy.types.Armature.cloudrig
