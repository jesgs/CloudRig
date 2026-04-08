# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import Constraint, Object, Operator, PoseBone
from bpy.utils import flip_name
from rna_prop_ui import rna_idprop_value_item_type

from ..bs_utils.properties import (
    copy_property_group,
    get_custom_prop_names,
    get_opposite_obj,
    rename_custom_prop,
)
from ..generation.cloudrig import active_rig, object_mode
from ..rig_component_features.mechanism import find_or_create_constraint


class POSE_OT_symmetrize_rigging(Operator):
    """Mirror selected bones, their constraints, their drivers, and the animation of Actions used by Action constraints"""

    bl_idname = "pose.symmetrize_rigging"
    bl_label = "Symmetrize Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = active_rig(context)
        if not rig:
            cls.poll_message_set("No active armature.")
            return False

        sel_bones = context.selected_bones or context.selected_pose_bones
        if not sel_bones:
            cls.poll_message_set("No selected bones.")
            return False

        for bone in sel_bones:
            if bone.name != flip_name(bone.name):
                return True

        cls.poll_message_set("No selected flippable bones.")
        return False

    def get_symmetrize_bone_mapping(self, context) -> dict[PoseBone, PoseBone] | set:
        bone_map = {}
        rig = active_rig(context)
        selected_pose_bones = context.selected_pose_bones[:]
        for pb in selected_pose_bones:
            flipped_name = flip_name(pb.name)
            if flipped_name == pb.name:
                continue
            opp_pb = rig.pose.bones.get(flipped_name)
            if opp_pb in selected_pose_bones:
                self.report(
                    {'ERROR'},
                    rpt_('Bone selected on both sides: "{bone}". Select only one side to clarify symmetrizing direction.')
                    .format(bone=pb.name),
                )
                return {'CANCELLED'}
            if opp_pb == pb:
                self.report(
                    {'WARNING'},
                    rpt_('Bone name cannot be flipped: "{bone}". Symmetrize will have no effect.')
                    .format(bone=pb.name),
                )
                pb.select = False
                continue
            if not opp_pb:
                continue
            bone_map[pb] = opp_pb

        return bone_map

    def execute(self, context):
        rig = active_rig(context)

        with object_mode(rig, mode='POSE'):
            bone_map = self.get_symmetrize_bone_mapping(context)
            if bone_map == {'CANCELLED'}:
                return {'CANCELLED'}

            for to_pb in bone_map.values():
                for to_con in to_pb.constraints:
                    remove_constraint_with_drivers(to_pb, to_con)

        with object_mode(rig, mode='EDIT'):
            for pb in bone_map.keys():
                eb = rig.data.edit_bones[pb.name]
                eb.hide = False
                eb.select = True
            bpy.ops.armature.symmetrize()

        with object_mode(rig, mode='POSE'):
            bpy.ops.pose.select_mirror(extend=False)
            bone_map = self.get_symmetrize_bone_mapping(context)
            bpy.ops.pose.select_mirror(extend=False)

        for from_pb, to_pb in bone_map.items():
            # Copy bone color preset.
            to_pb.bone.color.palette = from_pb.bone.color.palette

            # Copy armature display type.
            to_pb.bone.display_type = from_pb.bone.display_type

            # Mirror drivers on bone properties.
            symmetrize_drivers(rig, from_pb, to_pb)

            # Mirror constraint names and drivers.
            for from_con in from_pb.constraints:
                symmetrize_constraint(rig, from_pb, from_con)

            copy_property_group(from_pb.cloudrig_component, to_pb.cloudrig_component, x_mirror=True)
            if to_pb.cloudrig_component.params.shoulder.is_property_set('up_axis'):
                to_pb.cloudrig_component.params.shoulder.up_axis = str((
                    int(to_pb.cloudrig_component.params.shoulder.up_axis) + 2) % 4
                )

            # Flip custom property names
            for prop_name in get_custom_prop_names(to_pb):
                flipped_name = flip_name(prop_name)
                if flipped_name == prop_name:
                    continue
                if flipped_name in to_pb:
                    continue
                rename_custom_prop(to_pb, prop_name, flipped_name)

            # Mirror bone collections.
            for coll in to_pb.bone.collections[:]:
                coll.unassign(to_pb)
            for from_coll in from_pb.bone.collections:
                to_coll = rig.data.collections_all.get(flip_name(from_coll.name))
                if to_coll:
                    to_coll.assign(to_pb)
                else:
                    # Opposite collection doesn't exist, we're gonna create it.
                    to_coll = rig.data.collections.new(name=flip_name(from_coll.name))
                    rig.cloudrig_prefs.active_collection_index = rig.cloudrig_prefs.active_collection_index
                    to_coll.parent = from_coll.parent
                    to_coll.assign(to_pb)

        return {"FINISHED"}


def remove_constraint_with_drivers(
    pbone: PoseBone,
    con: Constraint,
):
    armature = pbone.id_data
    if not con:
        return

    if armature.animation_data:
        for fc in armature.animation_data.drivers[:]:
            if fc.data_path.startswith(
                f'pose.bones["{pbone.name}"].constraints["{con.name}"].'
            ):
                armature.animation_data.drivers.remove(fc)

    pbone.constraints.remove(con)


def symmetrize_constraint(armature: Object, pbone: PoseBone, from_con: Constraint):
    """Apply some additional mirroring logic that the Symmetrize operator doesn't do for us."""

    if '@' in from_con.name:
        flipped_con_name = "@".join([flip_name(part) for part in from_con.name.split("@")])
    else:
        flipped_con_name = flip_name(from_con.name)
    flipped_bone_name = flip_name(pbone.name)
    opp_pb = armature.pose.bones.get(flipped_bone_name)

    if pbone == opp_pb:
        # Bone name cannot be flipped, so we skip.
        return
    if pbone == opp_pb and from_con.name == flipped_con_name:
        # No opposite bone found and the constraint name could not be flipped, so we skip.
        return

    to_con = find_or_create_constraint(opp_pb, from_con.type, from_con.name)
    assert to_con, "Constraint should exist! This is a bug!"
    if from_con.type == 'ARMATURE':
        # The built-in Symmetrize operator only flips Armature Constraint subtargets,
        # if there is also a target ID. Otherwise, the subtarget gets ignored...
        for t_src, t_dst in zip(from_con.targets, to_con.targets):
            t_dst.subtarget = flip_name(t_src.subtarget)
    to_con.name = flipped_con_name

    # Try flipping the target objects.
    if hasattr(to_con, 'targets'):
        targets = (from_con.targets, to_con.targets)
    elif hasattr(to_con, 'target') and to_con.target:
        targets = ([from_con], [to_con])
    else:
        targets = ([], [])

    for from_targ, to_targ in zip(*targets):
        if from_targ.target:
            to_targ.target = get_opposite_obj(from_targ.target)
        # Try flipping the target vertex group.
        if to_targ.target and to_targ.target.type != 'ARMATURE' and from_targ.subtarget:
            flipped_name = flip_name(from_targ.subtarget)
            if to_targ.target.type != 'MESH' or flipped_name in to_targ.target.vertex_groups:
                to_targ.subtarget = flip_name(from_targ.subtarget)

    symmetrize_drivers(armature, pbone, opp_pb, from_con, to_con)


def symmetrize_drivers(
    armature: Object,
    src_bone: PoseBone,
    dst_bone: PoseBone,
    src_constraint: Constraint = None,
    dst_constraint: Constraint = None,
):
    """Mirrors all drivers from one bone to another.
    If src_constraint is specified, dst_constraint also must be, and then copy and mirror
    drivers between constraints instead of bones.

    Drivers of certain values of certain constraint types will also be attempted to be inverted and
    axes swapped as appropriate, based on the C implementation of the Symmetrize operator.
    NOTE: I never bothered testing this for Transform constraints.
    """

    invert_values, datapath_swap_maps = get_driver_mirror_logic(src_constraint)

    if not armature.animation_data:
        # No drivers to mirror.
        return

    for src_fc in armature.animation_data.drivers[:]:
        if f'pose.bones["{src_bone.name}"]' not in src_fc.data_path:
            # Driver doesn't belong to source bone, skip.
            continue
        if "constraints[" in src_fc.data_path and not src_constraint:
            # Driver is on a constraint, but no source constraint was given, skip.
            continue
        if src_constraint and src_constraint.name not in src_fc.data_path:
            # Driver is not on the given source constraint, skip.
            continue

        ### Copying mirrored driver to target bone.

        # Managing drivers through bpy is a bit tricky:
        # Bones & Constraints have driver_add() and driver_remove() functions
        # that take a data path relative to themselves, but they don't have anything
        # along the lines of driver_find(). For that you have to use the ID's AnimData.

        data_path_from_bone = src_fc.data_path.split("]", 1)[1]
        if data_path_from_bone.startswith("."):
            data_path_from_bone = data_path_from_bone[1:]
        new_fc = None
        if "constraints[" in data_path_from_bone:
            data_path_from_constraint = data_path_from_bone.split("]", 1)[1]
            if data_path_from_constraint.startswith("."):
                data_path_from_constraint = data_path_from_constraint[1:]
            swap_map = datapath_swap_maps.get(src_constraint.type)
            if swap_map:
                for key, value in swap_map.items():
                    if key in data_path_from_constraint:
                        data_path_from_constraint = data_path_from_constraint.replace(
                            key, value
                        )
                    elif value in data_path_from_constraint:
                        data_path_from_constraint = data_path_from_constraint.replace(
                            value, key
                        )
            # Armature constraints need special special treatment...
            if (
                src_constraint.type == 'ARMATURE'
                and "targets[" in data_path_from_constraint
            ):
                target_idx = int(data_path_from_constraint.split("targets[")[1][0])
                target = dst_constraint.targets[target_idx]
                # Weight is the only property that can have a driver on an Armature constraint's Target.
                target.driver_remove("weight")
                new_fc = target.driver_add("weight")
            else:
                dst_constraint.driver_remove(data_path_from_constraint)
                new_fc = dst_constraint.driver_add(data_path_from_constraint)
        else:
            dst_bone.driver_remove(data_path_from_bone, src_fc.array_index)
            try:
                new_fc = dst_bone.driver_add(data_path_from_bone, src_fc.array_index)
            except TypeError:
                new_fc = dst_bone.driver_add(data_path_from_bone)

        expression = src_fc.driver.expression

        # Copy the driver variables.
        for src_var in src_fc.driver.variables:
            dst_var = new_fc.driver.variables.new()
            dst_var.type = src_var.type
            dst_var.name = src_var.name
            # We want to flip variable names, but it doesn't work when eg. "Left" is followed by "_".
            dst_var.name = flip_name(src_var.name.replace("_", " ")).replace(" ", "_")

            for src_tgt, dst_tgt in zip(src_var.targets, dst_var.targets):
                if src_var.type == 'TRANSFORMS' and src_tgt.transform_space != 'LOCAL_SPACE':
                    # NOTE: Non-euler rotation modes might also be off when mirroring drivers.
                    print(
                        "CloudRig Warning: Only local space is supported for mirroring driver variables. Result may be unexpected for ",
                        src_fc.data_path,
                    )

                target_bone = src_tgt.bone_target
                new_target_bone = flip_name(target_bone)
                if dst_var.type == 'SINGLE_PROP':
                    dst_tgt.id_type = src_tgt.id_type
                dst_tgt.id = src_tgt.id
                dst_tgt.rotation_mode = src_tgt.rotation_mode
                dst_tgt.bone_target = new_target_bone
                dst_data_path = src_tgt.data_path
                if "pose.bones" in dst_data_path:
                    # Flip bone name in data
                    bone_name = dst_data_path.split('pose.bones["')[1].split('"')[0]
                    flipped_name = flip_name(bone_name)
                    dst_data_path = dst_data_path.replace(bone_name, flipped_name)

                    # If the data path is referring to a custom property, flip the custom property name, too.
                    prop_name = dst_data_path.split('["')[-1].split('"')[0]
                    dst_data_path = dst_data_path.replace(
                        prop_name, flip_name(prop_name)
                    )

                dst_tgt.data_path = dst_data_path
                dst_tgt.transform_type = src_tgt.transform_type
                dst_tgt.transform_space = src_tgt.transform_space

                if src_var.name != dst_var.name:
                    expression = expression.replace(src_var.name, dst_var.name)

                # If one of the driving values is something that needs to be inverted, invert only that value in the expression.
                if (
                    dst_var.type == 'TRANSFORM'
                    and dst_tgt.transform_type in {'ROT_Y', 'ROT_Z', 'LOC_X'}
                ) or (
                    dst_var.type == 'SINGLE_PROP'
                    and any(
                        [dst_tgt.data_path.endswith(thing) for thing in invert_values]
                    )
                ):
                    expression = expression.replace(dst_var.name, f"-({dst_var.name})")

            # If the driven value is something that needs to be inverted, invert the entire expression.
            driven_value = armature.path_resolve(new_fc.data_path)
            _value_type, is_array = rna_idprop_value_item_type(driven_value)
            data_path_with_index = new_fc.data_path
            if is_array and new_fc.array_index > -1:
                data_path_with_index += f"[{new_fc.array_index}]"

            if any([data_path_with_index.endswith(key) for key in invert_values]):
                expression = f"-({expression})"

            if new_fc.data_path.endswith('pole_angle'):
                # If the IK pole angle is driven, add 180 degrees in a way that loops it around to
                # keep it in -180->180 range.
                # NOTE: This will coincidentally work around the -180->180 range limitation,
                # which technically makes it assymetrical, but I'll ignore that for the sake of
                # keeping the expression simple. Why would anyone drive this value anyways?
                expression = f"-({expression}) % (2 * pi) - pi"

        # Copy the driver expression.
        new_fc.driver.expression = expression


def get_driver_mirror_logic(src_constraint):
    transforms_to_invert = ['location[0]', 'rotation_euler[1]', 'rotation_euler[2]']
    invert_values = {
        'LIMIT_LOCATION': ['min_x', 'max_x'],
        'LIMIT_ROTATION': ['min_y', 'max_y', 'min_z', 'max_z'],
        'TRANSFORM': [
            'from_min_x',
            'from_max_x',
            'from_min_y_rot',
            'from_max_y_rot',
            'from_min_z_rot',
            'from_max_z_rot',
            'to_min_x',
            'to_max_x',
            'to_min_z_rot',
            'to_max_z_rot',
        ],
    }

    datapath_swap_maps = {
        'LIMIT_LOCATION': {
            'min_x': 'max_x',
        },
        'LIMIT_ROTATION': {
            'min_y': 'max_y',
            'min_z': 'max_z',
        },
        'TRANSFORM': {
            'from_min_x': 'from_max_x',
            'from_min_y_rot': 'from_max_y_rot',
            'from_min_z_rot': 'from_max_z_rot',
        },
    }
    for axis in "xyz":
        if src_constraint and src_constraint.type == 'TRANSFORM':
            from_axis = getattr(src_constraint, f'map_to_{axis}_from')
            if (src_constraint.map_from == 'LOCATION' and from_axis == 'X') or (
                src_constraint.map_from == 'ROTATION' and from_axis != 'X'
            ):
                # X Loc to X/Y/Z Scale: Min/Max Flipped
                # Y Rot to X/Y/Z Scale: Min/Max Flipped
                # Z Rot to X/Y/Z Scale: Min/Max Flipped

                # X Loc to X/Y/Z Loc: Min/Max Flipped
                # Y Rot to X/Y/Z Loc: Min/Max Flipped
                # Z Rot to X/Y/Z Loc: Min/Max Flipped
                datapath_swap_maps['TRANSFORM'].update(
                    {
                        f"to_min_{axis}_scale": f"to_max_{axis}_scale",
                        f"to_min_{axis}": f"to_max_{axis}",
                    }
                )
            if (
                (
                    src_constraint.map_from == 'LOCATION'
                    and from_axis == 'X'
                    and axis != 'Y'
                )
                or (
                    src_constraint.map_from == 'ROTATION'
                    and from_axis == 'Y'
                    and axis != 'Y'
                )
                or (src_constraint.map_from == 'ROTATION' and from_axis == 'Z')
            ):
                # X Loc to X/Z Rot: Flipped
                # Y Rot to X/Z Rot: Flipped
                # Z Rot to X/Y/Z rot: Flipped

                datapath_swap_maps['TRANSFORM'].update(
                    {f"to_min_{axis}_rot": f"to_max_{axis}_rot"}
                )
            if src_constraint.map_from == 'ROTATION' and from_axis == 'Y':
                # If source is Y rot, flip and invert Y rot
                datapath_swap_maps['TRANSFORM'].update({'to_min_y_rot': 'to_max_y_rot'})
                invert_values['TRANSFORM'] += ['to_min_rot_y', 'to_max_rot_y']

    if src_constraint and src_constraint.type == 'TRANSFORM':
        from_axis = getattr(src_constraint, f'map_to_{axis}_from')
        if (
            (src_constraint.map_from == 'LOCATION' and from_axis != 'X')
            or (src_constraint.map_from == 'ROTATION' and from_axis != 'Y')
            or src_constraint.map_from == 'SCALE'
        ):
            invert_values['TRANSFORM'] += ['to_min_rot_y', 'to_max_rot_y']

    if (
        src_constraint
        and src_constraint.type == 'ACTION'
        and src_constraint.transform_channel
        in {'LOCATION_X', 'ROTATION_Y', 'ROTATION_Z'}
    ):
        invert_values['ACTION'] = ['min', 'max']

    swap_map = {}
    if src_constraint:
        transforms_to_invert += invert_values.get(src_constraint.type, [])
        swap_map = datapath_swap_maps.get(src_constraint.type, {})

    return transforms_to_invert, swap_map


def draw_menu_entry(self, context):
    self.layout.separator()
    self.layout.operator(POSE_OT_symmetrize_rigging.bl_idname, icon='MOD_MIRROR')


registry = [POSE_OT_symmetrize_rigging]


def register():
    bpy.types.VIEW3D_MT_pose.append(draw_menu_entry)


def unregister():
    bpy.types.VIEW3D_MT_pose.remove(draw_menu_entry)
