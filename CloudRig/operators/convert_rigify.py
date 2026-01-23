# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty
from bpy.types import Object, Operator, PoseBone

from ..rig_component_features.properties_ui import add_property_to_ui


class CLOUDRIG_OT_convert_rigify_metarig(Operator):
    """Convert a Rigify metarig to a CloudRig metarig. The Rigify data is preserved, but existing CloudRig data may get overwritten."""

    bl_idname = "armature.convert_rigify_to_cloudrig"
    bl_label = "Convert Rigify to CloudRig"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        rig = context.active_object
        if not rig or rig.type != 'ARMATURE':
            cls.poll_message_set("No active Armature.")
            return False
        if not is_rigify_metarig(rig):
            cls.poll_message_set("No Rigify data found on this armature.")
            return False
        return True

    def invoke(self, context, _event):
        metarig = context.object
        if is_rigify_metarig(metarig) and any_cloudrig_data(metarig):
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text="This will overwrite existing CloudRig data.")

    def execute(self, context):
        metarig_ob = context.active_object
        convert_rigify_to_cloudrig(metarig_ob)
        return {'FINISHED'}


def convert_rigify_to_cloudrig(metarig_ob: Object):
    convert_actions(metarig_ob)
    convert_components(metarig_ob)
    convert_bone_collections_ui(metarig_ob)
    for pb in metarig_ob.pose.bones:
        if not pb.custom_shape:
            pb.custom_shape_scale_xyz = [1, 1, 1]
            pb.custom_shape_translation = [0, 0, 0]
            pb.custom_shape_rotation_euler = [0, 0, 0]


def convert_components(metarig_ob: Object):
    for pbone in metarig_ob.pose.bones:
        comp = pbone.cloudrig_component
        params = comp.params
        rigify_type = get_rigify_type(pbone)
        if not rigify_type:
            continue
        # Do some quick and dirty conversions for proof of concept...
        if rigify_type == 'limbs.leg':
            comp.component_type = 'Limb: Biped Leg'
            params.leg.shape_footroll.shape_name = 'Heel'
            for pb in pbone.children_recursive:
                bone = pb.bone
                if not bone.use_connect and not bone.children and not is_rigify_base_bone(pb):
                    params.leg.heel_bone = bone.name
                    break
        if rigify_type == 'limbs.arm':
            pbone.cloudrig_component.component_type = 'Limb: Generic'
        if rigify_type == 'spines.basic_spine':
            pbone.cloudrig_component.component_type = 'Spine: Cartoon'
        if rigify_type == 'basic.super_copy':
            any_arm_child = any(get_rigify_type(child)=='limbs.arm' for child in pbone.children)
            if any_arm_child:
                pbone.cloudrig_component.component_type = 'Shoulder Bone'
            else:
                pbone.cloudrig_component.component_type = 'Single Control'
        if rigify_type == 'spines.super_head':
            pbone.cloudrig_component.component_type = 'Chain: FK'
        if rigify_type == 'limbs.super_finger':
            pbone.cloudrig_component.component_type = 'Chain: FK'
        if rigify_type == 'limbs.super_palm':
            # I think this rigify type affects its siblings...
            for pbone in pbone.parent.children:
                pbone.cloudrig_component.component_type = 'Chain: FK'


def convert_actions(metarig_ob: Object):
    cloudrig_actions = metarig_ob.cloudrig.generator.action_setups
    cloudrig_actions.clear()
    for rigify_action in metarig_ob.data.rigify_action_slots:
        cr_action = cloudrig_actions.add()
        cr_action.action = rigify_action.action
        cr_action.action_slot = rigify_action.action_slot
        cr_action.subtarget = rigify_action.subtarget
        cr_action.frame_start = rigify_action.frame_start
        cr_action.frame_end = rigify_action.frame_end
        cr_action.target_space = rigify_action.target_space
        cr_action.transform_channel = rigify_action.transform_channel
        cr_action.trans_min = rigify_action.trans_min
        cr_action.trans_max = rigify_action.trans_max

        cr_action.is_corrective = rigify_action.is_corrective
        cr_action.trigger_select_a = rigify_action.trigger_select_a
        cr_action.trigger_select_b = rigify_action.trigger_select_b


def convert_bone_collections_ui(metarig_ob: Object):
    for coll in metarig_ob.data.collections_all:
        add_property_to_ui(
            obj=metarig_ob,
            owner_path=f'data.collections_all["{coll.name}"]',
            prop_name="is_visible",
            panel_name="Bone Collections",
            row_name=f"Rigify Row {coll.rigify_ui_row}",
            slider_name=coll.name,
            icon_true="HIDE_OFF",
            icon_false="HIDE_ON",
        )


def any_cloudrig_data(metarig_ob: Object) -> bool:
    if not metarig_ob or metarig_ob.type != 'ARMATURE':
        return False
    if metarig_ob.cloudrig.generator.action_setups:
        return True
    if any(pb.cloudrig_component.component_type for pb in metarig_ob.pose.bones):
        return True
    return False


def is_rigify_metarig(metarig_ob: Object) -> bool:
    if not metarig_ob or metarig_ob.type != 'ARMATURE':
        return False
    return any(get_rigify_type(pb) for pb in metarig_ob.pose.bones)


def get_rigify_type(pbone: PoseBone) -> str:
    if hasattr(pbone, 'rigify_type'):
        return pbone.rigify_type
    props = pbone.bl_system_properties_get()
    if not props:
        return ""
    return props.get('rigify_type', "")


def is_rigify_base_bone(pbone: PoseBone):
    return bool(get_rigify_type(pbone))

registry = [
    CLOUDRIG_OT_convert_rigify_metarig,
]
