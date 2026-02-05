# SPDX-License-Identifier: GPL-3.0-or-later

from itertools import pairwise
from math import pi

import bpy
import rigify
from bpy.props import BoolProperty
from bpy.types import Object, Operator, PoseBone

from ..rig_component_features.mechanism import find_or_create_constraint
from ..rig_component_features.properties_ui import add_property_to_ui
from .pie_bone_selection_ops import reveal_and_select_bone


class CLOUDRIG_OT_convert_rigify_metarig(Operator):
    """Convert Rigify's Rig Types to the closest equivalent in CloudRig's Component Types. The Rigify data is preserved, but existing CloudRig data may get overwritten."""

    bl_idname = "armature.convert_rigify_to_cloudrig"
    bl_label = "Rigify Types -> CloudRig Components"
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
        convert_rigify_to_cloudrig(context, metarig_ob)
        return {'FINISHED'}


class CLOUDRIG_OT_replace_rigify_rig(Operator):
    """Replace the generated Rigify rig with the generated CloudRig rig. This will destroy the Rigify rig."""

    bl_idname = "armature.replace_rigify_with_cloudrig_rig"
    bl_label = "Replace Generated Rig & Rename Vertex Groups"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    rename_vertex_groups: BoolProperty(
        name="Rename Vertex Groups",
        description="Rename vertex groups associated with deforming bones, to the names of the closest deforming bone in the CloudRig rig",
        default=True
    )
    remove_rigify_data: BoolProperty(
        name="Remove Rigify Data",
        description="Remove all Rigify data from the metarig",
        default=False,
    )

    def execute(self, context):
        metarig = context.object
        rigify_target_rig = metarig.data.rigify_target_rig
        cloudrig_target_rig = metarig.cloudrig.generator.target_rig

        rigify_dependent_ids = bpy.data.user_map()[rigify_target_rig]
        rigify_dependent_objects = [id for id in rigify_dependent_ids if isinstance(id, Object)]
        rigify_deformed_meshobs = [obj for obj in rigify_dependent_objects if any([hasattr(m, 'object') and m.object == rigify_target_rig for m in obj.modifiers])]
        for mesh_ob in rigify_deformed_meshobs:
            print("Mesh obj: ", mesh_ob)
            # TODO: Rename deform bones based on proximity. But also maybe this should be done on a per component basis, rather than overall across the whole thing.

        rigify_target_rig.user_remap(cloudrig_target_rig)
        bpy.data.objects.remove(rigify_target_rig)

        return {'FINISHED'}

def convert_rigify_to_cloudrig(context, metarig_ob: Object):
    for pb in metarig_ob.pose.bones:
        if not pb.custom_shape:
            pb.custom_shape_scale_xyz = [1, 1, 1]
            pb.custom_shape_translation = [0, 0, 0]
            pb.custom_shape_rotation_euler = [0, 0, 0]
            pb.use_custom_shape_bone_size = True
    convert_actions(metarig_ob)
    convert_components(context, metarig_ob)
    convert_bone_collections_ui(metarig_ob)


def convert_components(context, metarig_ob: Object):
    """
    Convert Rigify's "Rig Type" assignments to as-close-as-possible CloudRig
    component type assignments.

    Rigify's docs can be helpful:
    https://docs.blender.org/manual/en/latest/addons/rigging/rigify/rig_types
    """
    skipped = 0
    converted = 0
    for pbone in metarig_ob.pose.bones[:]:
        comp = pbone.cloudrig_component
        cr_params = comp.params
        rigify_params = pbone.rigify_parameters
        rigify_type = get_rigify_type(pbone)
        if not rigify_type:
            continue

        rigify_pb_chain = [pbone] + [
            metarig_ob.pose.bones.get(name) for name in
            rigify.utils.rig.connected_children_names(metarig_ob, pbone.name)
        ]

        if rigify_type == 'limbs.super_limb':
            # Un-wrap super_limb compatibility layer.
            if rigify_params.limb_type == 'Arm':
                rigify_type = 'limbs.arm'
            elif rigify_params.limb_type == 'Leg':
                rigify_type = 'limbs.leg'
            elif rigify_params.limb_type == 'Paw':
                rigify_type = 'limbs.paw'

        if rigify_type == 'basic.copy_chain':
            # I don't really want to implement this as a component type, because users should just
            # rely on implicit raw copy, but for the sake of conversion, let's convert each bone of
            # the chain to a Single Control component.
            for pb in rigify_pb_chain:
                comp.component_type = 'Single Control'
                cr_params.copy.create_deform = pbone.rigify_parameters.make_deforms
                if not pb.custom_shape:
                    cr_params.copy.shape_control.shape_name = 'Taper Rect'
        elif rigify_type == 'basic.pivot':
            # Weird things:
            # - If Switchable Parent==Register Parent==True, it generates a dependency cycle.
            # - If Master Control==True and Pivot Control==False, then it doesn't generate a
            # pivot rig at all.
            comp.component_type = 'Single Control'
            cr_params.copy.custom_pivot = not (rigify_params.make_extra_control and not rigify_params.make_control)
            cr_params.copy.create_deform = rigify_params.make_extra_deform
        elif rigify_type == 'basic.raw_copy':
            # Assigning this is optional in CloudRig, but doing it will let the user distinguish
            # between bones that used to have Rigify's raw_copy assigned vs those that did not.
            # (both will behave the same)
            comp.component_type = 'Raw Copy'
        elif rigify_type in ('basic.super_copy', 'skin.anchor'):
            # Special case: Shoulder bone
            any_arm_child = any(get_rigify_type(child)=='limbs.arm' for child in pbone.children)
            if any_arm_child:
                comp.component_type = 'Shoulder Bone'
                continue
            # General case weird things:
            # - You can turn everything off, and then this just generates a useless locked ORG bone.
            # - I don't get the point of turning off Relink Constraints, you would always want it.
            widget_map = {
                'bone': 'Circle', # idk what to tell ya.
                'circle': 'Circle',
                'cube': 'Cube',
                'cube_truncated': 'Cube 2',
                'cuboctahedron': 'Cube 2',
                'diamond': 'Diamond', # Scale x2 on X/Z
                'gear': 'Cog 3',
                'jaw': 'Jaw', # Offset Y position by full bone length.
                'limb': 'Circle', # Offset Y position by half bone length.
                'line': 'Line',
                'palm': 'Foot 2',
                'palm_z': 'Foot 2', # Offset Y rotation by 90.
                'pivot': 'Axes 6',
                'pivot_cross': 'Axes 6',
                'shoulder': 'Shoulder', # Offset Y position by half bone length.
                'sphere': 'Sphere',
                'teeth': 'Shoulder 4', # Offset X rotation by 90 and Y position by half bone length.
            }
            comp.component_type = 'Single Control'
            cr_params.copy.create_deform = rigify_params.make_deform

            rigify_wgt = rigify_params.super_copy_widget_type
            if rigify_params.make_widget:
                cr_params.copy.shape_control.shape_name = widget_map.get(rigify_wgt, "Circle")
                print(rigify_wgt)
                if rigify_wgt == 'diamond':
                    pbone.custom_shape_scale_xyz = (2, 1, 2)
                if rigify_wgt == 'jaw':
                    pbone.custom_shape_translation.y = pbone.bone.length
                    print("Offset by full bone length:", pbone.bone.length, pbone.custom_shape_translation, pbone.id_data, pbone.name)
                elif rigify_wgt in ('limb', 'shoulder', 'teeth'):
                    pbone.custom_shape_translation.y = pbone.bone.length/2
                    if rigify_wgt == 'teeth':
                        pbone.custom_shape_rotation_euler.x += pi/2
                elif rigify_wgt == 'palm_z':
                    pbone.custom_shape_rotation_euler.y += pi/2
            else:
                cr_params.copy.shape_control.shape_name = "Taper Rect"

            if rigify_type == 'skin.anchor':
                # - Suppress Control: 1. Why would you 2. Just assign it to the collections you want.
                comp.component_type = 'Chain Intersection'
                cr_params.copy.create_deform = rigify_params.make_extra_deform

        elif rigify_type == 'limbs.simple_tentacle':
            # - Bendy bones segments are copied from metarig bones.
            # - Always uses Automatic handles
            # - Stretch constraints have Volume Variation at 1
            # I think I will implement the curl behaviour here with constraints, because
            # a curl behaviour that can be split per axis seems too niche.
            comp.component_type = 'Chain: FK'
            cr_params.chain.bbone_density = 10 if any([pb.bone.bbone_segments > 1 for pb in rigify_pb_chain]) else 0
            cr_params.fk_chain.counter_rotate_stretch_bones = 0.5
            if any(rigify_params.copy_rotation_axes):
                for first, second in pairwise(rigify_pb_chain):
                    copyrot = find_or_create_constraint(second, 'COPY_ROTATION', f"Copy Rotation@FK-{first.name}")
                    copyrot.use_x, copyrot.use_y, copyrot.use_z = rigify_params.copy_rotation_axes
                    copyrot.mix_mode = 'BEFORE'
                    copyrot.target_space = copyrot.owner_space = 'LOCAL'
        elif rigify_type == 'limbs.super_finger':
            if rigify_params.make_extra_ik_control:
                comp.component_type = 'Chain: Finger'
            else:
                comp.component_type = 'Chain: FK'
            cr_params.chain.sharp = True
            cr_params.chain.bbone_density = rigify_params.bbones if rigify_params.bbones > 1 else 0
            cr_params.fk_chain.root = True
            cr_params.fk_chain.create_curl_control = True
            cr_params.fk_chain.counter_rotate_stretch_bones = 0.5
        elif rigify_type == 'limbs.arm':
            # - IK Wrist Pivot, Custom IK Pivot, IK Local Location: Useless imo.
            #   Will ignore until a user asks for these.
            # - Rotation Axis: Anything other than Automatic seems pointless.
            # - Auto-Align Hand: I don't think this is doing anything at all.
            # - Support Uniform Scaling: There's no reason to turn this off
            #   (which is the default because of course it is),
            #   and a scalable root is already built into CloudRig's IK chain.
            # and CloudRig's FK Root control already provides this functionality.
            # While CloudRig (for now) allows disabling generation of an IK Pole,
            # and Rigify starts out without an IK pole by default, I'd rather discourage that.
            comp.component_type = 'Chain: IK'
            cr_params.chain.segments = rigify_params.segments
            cr_params.chain.bbone_density = rigify_params.bbones if rigify_params.bbones > 1 else 0
        elif rigify_type == 'limbs.leg':
            # - Foot Pivot: This should never be just "Toe".
            #   A toe pivot should be an optional addition on top of the foot bone
            #   which pivots at the ankle.
            # - Separate IK Toe: Pointless; CloudRig's FK toe works fine in IK mode.
            # - Toe Tip Roll: I think CloudRig's behaviour is more lifelike, so ignoring this.
            # For other options, see comments of `limbs.arm`.
            # While CloudRig (for now) allows disabling generation of an IK Pole,
            # and Rigify starts out without an IK pole by default, I'd rather discourage that.
            comp.component_type = 'Limb: Biped Leg'
            cr_params.chain.segments = rigify_params.segments
            cr_params.chain.bbone_density = rigify_params.bbones if rigify_params.bbones > 1 else 0
            cr_params.leg.shape_footroll.shape_name = 'Heel'
            for pb in pbone.children_recursive:
                bone = pb.bone
                if not bone.use_connect and not bone.children and not is_rigify_base_bone(pb):
                    cr_params.leg.heel_bone = bone.name
                    break
        elif rigify_type == 'limbs.paw':
            # TODO: Need to implement as a new component type in CloudRig, probably.
            pass
        elif rigify_type == 'limbs.front_paw':
            # TODO
            pass
        elif rigify_type == 'limbs.rear_paw':
            # TODO
            pass
        elif rigify_type == 'limbs.super_palm':
            # This rigify type affects its siblings.
            # TODO: Decide how to do this. I'd prefer not implementing a component type that affects its siblings,
            # since there's no precedent for that in CloudRig currently, and it would raise questions about execution order...
            # I guess it could affect siblings which don't have their own component type?
            # But still, it would be quite some code restructuring to support this.
            for sibling in sibling.parent.children:
                sibling.cloudrig_component.component_type = 'Chain: FK'
        elif rigify_type == 'limbs.spline_tentacle':
            # - Extra Start/End Controls: I don't think it's working.
            # - sik_stretch_control: No clue what this is doing.
            # - Radius Scaling: This is always on in CloudRig, as it should be.
            # - Maximum Radius: Pointless.
            comp.component_type = 'Curve: Spline IK'
            comp.spline_ik.match_hooks = False
            comp.spline_ik.hooks = rigify_params.sik_mid_controls + 2
            comp.spline_ik.create_fk_chain = rigify_params.sik_fk_controls
            comp.spline_ik.deform_setup = 'CREATE'
        elif rigify_type == 'spines.super_spine':
            # TODO
            pass
        elif rigify_type == 'spines.basic_spine':
            comp.component_type = 'Spine: Cartoon'
            # TODO details
        elif rigify_type == 'spines.basic_tail':
            # TODO
            pass
        elif rigify_type == 'spines.super_head':
            comp.component_type = 'Chain: FK'
            # TODO details
            pass

        elif rigify_type == 'face.basic_tongue':
            # Rigify creates a sort of IK tongue rig.
            # Studio animators aren't a big fan of it, so I won't bother replicating it until
            # someone asks. In meantime, FK chain w/ curl ctrl seems close enough.

            # Since Rigify's tongue rig is for some reason in reverse, I need to switch direction
            # on the metarig bones... And since this should only be done once, we want to avoid re-doing it
            # on subsequent executions...
            if 'cloudrig_converted' in pbone:
                continue
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.armature.reveal()
            bpy.ops.armature.select_all(action='DESELECT')
            for pb in rigify_pb_chain:
                eb = metarig_ob.data.edit_bones.get(pb.name)
                reveal_and_select_bone(context, eb, extend_selection=True)
            bpy.ops.armature.switch_direction()
            bpy.ops.object.mode_set(mode='POSE')
            rigify_pb_chain[0]['cloudrig_converted'] = True

            rigify_pb_chain.reverse()
            comp = rigify_pb_chain[0].cloudrig_component
            cr_params = comp.params

            comp.component_type = 'Chain: FK'
            cr_params.fk_chain.root = True
            cr_params.fk_chain.create_curl_control = True
            cr_params.chain.smooth_spline = True
        elif rigify_type == 'face.skin_eye':
            # - Eyelid Detach: Doesn't seem that important, and users can easily add the
            #   Limit Distance constraints if they want this.
            # - Split Eyelid Follow Slider: Also doesn't seem important, but could be implemented
            #   as part of CloudRig's Eyelid component if people want it.
            comp.component_type = 'Aim'
            cr_params.aim.deform = rigify_params.make_deform
        elif rigify_type == 'skin.basic_chain':
            # - Use Scale XYZ/Ease: CloudRig always behaves as if X/Z are enabled, and scaling
            #   on Y affects easing. I'm very happy with that behaviour, so won't be converting this.
            # - Connect Mirror: CloudRig's Face Grid components always acts as if this is On, I think.
            # - Connect Next: CloudRig determines this based on whether "Tip Control" is on or off in the case of
            #   a toon chain that connects to another toon chain.
            # - Sharpen: This seems confusing and specific... I'm ignoring it.
            # - Orientation: This changes the bone roll of only the controls. But WHY???
            # - Chain Priority: CloudRig's Face Grid doesn't care about this much, and generation order can be tweaked.
            comp.component_type = 'Chain: Face Grid'
            # So yeah, I guess that's about it for this one. Rigify also always makes these chains
            # behave as CloudRig's Smooth Spline does, but I think that's a horrible idea.
        elif rigify_type == 'skin.stretchy_chain':
            # Not sure of real world use case for this. It's used in the eyelid
            # rigs but all that allows is squashing the eyelid horizontally, which is pointless.
            # In future, I'd like to implement a component type that uses a bendy bone as a
            # parent helper, which would be similar to this but imo have better real world uses.
            # For now, I find this very difficult to configure, and I'd be surprised if
            # anybody's actually using it, hence keeping the conversion logic minimal.

            comp.component_type = 'Chain: Face Grid'
            # If the parent of this is `face.skin_eye`, then this should be an Eyelid component.
            if get_rigify_type(pbone.parent) == 'face.skin_eye':
                comp.component_type = 'Chain: Eyelid'
        elif rigify_type == 'skin.glue':
            # Figuring out what generated control this would be attached to is way non-trivial.
            # But implementing a component type for it doesn't make sense either, since
            # all these functionalities can be achieved with the Single Control component type,
            # just with a parent selection or adding a single constraint.
            if rigify_params.skin_glue_head_mode == 'BRIDGE':
                comp.component_type = 'Chain: Face Grid'
            else:
                skipped += 1
        else:
            skipped += 1
            continue
        converted += 1

    print("Converted Rigify Types: ", converted)
    print("Skipped Rigify Types: ", skipped)


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
    CLOUDRIG_OT_replace_rigify_rig,
]
