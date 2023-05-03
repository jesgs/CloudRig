from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty
from bpy.types import PropertyGroup
from . import rigs
import inspect

param_classes = {
    name : module.Params
    for name, module in inspect.getmembers(rigs, inspect.ismodule)
    if hasattr(module, 'Params')
}

class RigParams(PropertyGroup):
    # TODO: Some params would have to be grabbed from the rig_features package.

    __annotations__ = {
        name : PointerProperty(type=param_class)
        for name, param_class in param_classes.items()
    }

class RigElement(PropertyGroup):
	owner_bone: StringProperty()
	params: PointerProperty(type=RigParams)

class GeneratorParameters(PropertyGroup):
    advanced_mode: BoolProperty()

class CloudRigProperties(PropertyGroup):
    rig_elements: CollectionProperty(type=RigElement)
    generator: PointerProperty(type=GeneratorParameters)

registry = list(param_classes.values()) + [
    RigParams,
    RigElement,
    GeneratorParameters,
    CloudRigProperties
]

def register():
    bpy.types.Armature.cloudrig = PointerProperty(type=CloudRigProperties)

def unregister():
    del bpy.types.Armature.cloudrig
