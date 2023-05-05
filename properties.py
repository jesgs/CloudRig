import bpy
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, IntProperty
from bpy.types import PropertyGroup, Object
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

def refresh_element_bones_list(rig_ob: Object):
    rig_ob.data.cloudrig.rig_element_bones.clear()
    for pb in rig_ob.pose.bones:
        if pb.cloudrig_element.element_type:
            rig_element_bone = rig_ob.data.cloudrig.rig_element_bones.add()
            rig_element_bone.name = pb.name
            pb.cloudrig_element.owner_bone = pb.name

class RigElement(PropertyGroup):
    def update_element_type(self, context):
        rig_ob = self.id_data
        refresh_element_bones_list(rig_ob)

    owner_bone: StringProperty()
    element_type: StringProperty(name="Element Type", update=update_element_type)
    params: PointerProperty(type=RigParams)

class GeneratorParameters(PropertyGroup):
    advanced_mode: BoolProperty()

class RigElementBone(PropertyGroup):
    def change_assigned_bone(self, context):
        pass
        # TODO: Implement this, similar to Copy Rigify Type & Parameters, 
        # but ideally it would also clear the data from the source.

    name: StringProperty(update=change_assigned_bone)

class CloudRigProperties(PropertyGroup):
    rig_element_bones: CollectionProperty(type=RigElementBone)
    def update_elem_index(self, context):
        refresh_element_bones_list(context.object)
        rig = context.object
        active_elem_pb = rig.pose.bones.get(self.active_element_bone_name)
        if not active_elem_pb:
            return

        for pb in context.selected_pose_bones:
            pb.bone.select = False
        active_elem_pb.bone.select = True
        rig.data.bones.active = active_elem_pb.bone

    active_rig_element_index: IntProperty(update=update_elem_index)
    @property
    def active_element_bone_name(self):
        return self.rig_element_bones[self.active_rig_element_index].name

    generator: PointerProperty(type=GeneratorParameters)
    metarig_version: IntProperty()

    target_rig: PointerProperty(type=Object)

registry = list(get_param_classes().values()) + [
    RigParams,
    RigElement,
    RigElementBone,
    GeneratorParameters,
    CloudRigProperties
]

def register():
    bpy.types.Armature.cloudrig = PointerProperty(type=CloudRigProperties)
    bpy.types.PoseBone.cloudrig_element = PointerProperty(type=RigElement)

def unregister():
    del bpy.types.Armature.cloudrig
