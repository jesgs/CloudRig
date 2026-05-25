# SPDX-License-Identifier: GPL-3.0-or-later

from math import pi
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.types import Object
from mathutils import Euler, Vector

from ..bs_utils.prefs import get_addon_prefs
from ..generation.actions_component import ActionConstraintSetup
from ..generation.cloudrig import is_cloud_metarig, is_generated_cloudrig
from ..operators.render_thumbnail import selection_state
from ..rig_component_features.object import EnsureVisible
from ..rig_components import ALL_COMPONENT_MODULES
from ..utils.misc import load_script

RIG_TYPE_MAP = {key: module.RIG_COMPONENT_CLASS.ui_name for key, module in ALL_COMPONENT_MODULES.items()}


def setattr_safe(thing, key, value):
    if hasattr(thing, 'bl_rna') and type(thing.bl_rna.properties[key]) is bpy.types.EnumProperty and type(value) is int:
        enum_value = thing.bl_rna.properties[key].enum_items[value].identifier
        setattr(thing, key, enum_value)
    else:
        setattr(thing, key, value)


def preserve_old_default(metarig: Object, param_name: str, old_default: float | int | bool | str):
    for pb in metarig.pose.bones:
        if param_name not in pb.cloudrig_component.params:
            setattr(pb.cloudrig_component.params, param_name, old_default)
            print(f"Preserve old default value: {pb.name} -> {param_name} = {old_default}")


def version_cloud_metarig_editmode(context, metarig):
    visibility = EnsureVisible(context, metarig)

    fix_corrective_actions_51(metarig)

    cloudrig = metarig.cloudrig
    addon_metarig_version = get_addon_prefs().cloud_metarig_version
    metarig_version = cloudrig.metarig_version

    if metarig_version >= addon_metarig_version:
        return

    with selection_state(context, active_obj=metarig, selected_obs=[metarig]):
        bpy.ops.object.mode_set(mode='EDIT')
        version_cloud_metarig(metarig)
        bpy.ops.object.mode_set(mode='OBJECT')
    visibility.restore(context)


def version_cloud_metarig(metarig):
    """Convert older CloudRig metarigs to work with the current version of
    CloudRig as well as possible. They will still need some manual cleanup!!!

    # NOTE on default values:
    # Old values left on their default are NOT STORED in the .blend, so
    # there's no way to guarantee correct versioning when changing the default value of a parameter.
    # So, make really damn sure that default values are correct when first implementing them!
    """
    cloudrig = metarig.cloudrig
    addon_metarig_version = get_addon_prefs().cloud_metarig_version
    metarig_version = cloudrig.metarig_version

    if metarig_version >= addon_metarig_version:
        return
    cloudrig.metarig_version = addon_metarig_version
    print(f"CloudRig Versioning: {metarig.name} bumping version {metarig_version} -> {addon_metarig_version}")

    if metarig_version < 3:
        # Generated rigs used to keep the metarig data, which confuses some poll functions.
        if (
            'generation_date' in metarig.data
            or 'generation_time' in metarig.data
            or ('is_generated_cloudrig' in metarig.data and metarig.data['is_generated_cloudrig'])
        ):
            metarig.property_unset('cloudrig')
            return

    if metarig_version < 4:
        # Action Slots were renamed to Action Setups, and now support Blender's Action Slots.
        generator_properties = cloudrig.generator.bl_system_properties_get()
        new_actions_data = cloudrig.generator.action_setups
        old_actions_data = [a.to_dict() for a in generator_properties.get('action_slots', [])]
        for old_setup in old_actions_data:
            new_setup = cloudrig.generator.action_setups.add()
            for key, value in old_setup.items():
                if hasattr(new_setup, key):
                    setattr_safe(new_setup, key, value)

        def find_first_setup_using_action(action: bpy.types.Action) -> ActionConstraintSetup | None:
            if not action:
                return
            for action_setup in cloudrig.generator.action_setups:
                if action_setup.action == action:
                    return action_setup

        for old_setup, new_setup in zip(old_actions_data, new_actions_data):
            if old_setup.get('is_corrective', False):
                new_setup.trigger_a = find_first_setup_using_action(old_setup.get('trigger_action_a', None))
                new_setup.trigger_b = find_first_setup_using_action(old_setup.get('trigger_action_b', None))

        if 'action_slots' in generator_properties:
            del generator_properties['action_slots']

    if metarig_version < 5:
        # Trigger the new set_transform callback in 5.0, which updates the underlying data
        # of the component_type property to be masked by the transform callbacks,
        # making it resilient to changing the UI names of components in the future.
        for pbone in metarig.pose.bones:
            if pbone.cloudrig_component.component_type:
                pbone.cloudrig_component.component_type = pbone.cloudrig_component.component_type

    if metarig_version < 6:
        # Rename widget params.
        widget_map = {
            "Root Simple": "Root 2",
            "Root Arrows": "Root 3",
            "Arrow Four-way": "Root 4",
            "Nose Master": "Nose",
            "Circle Spiked 1": "Circle 2",
            "Circle Spiked 2": "Circle 3",
            "Semicircle": "Circle 4",
            "Curve Point": "Bezier",
            "Curve Handle": "Handle",
            "Arrow Two-way": "Slider",
            "Arrow 3D": "Arrow 2",
            "Arrow Head": "Arrow 3",
            "IK Pole": "Pole",
            "Squares 2": "Squares",
            "Triangle Rounded": "Tri 2",
            "Capsule": "Pill",
            "Carpal": "Pill 2",
            "Cogwheel": "Cog",
            "Square Rounded": "Square 2",
            "Torso Master": "Torso",
            "Sphere XZ": "Sphere 2",
            "Eyes Target": "Eyes",
            "Roll Flat": "Roll 2",
            "Hyperbola": "Saddle",
            "Finger Curl": "Wave",
            "Sphere Half": "Sphere H",
        }
        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component
            if not comp.component_type:
                continue
            for paramset_name in comp.params.keys():
                if not hasattr(comp.params, paramset_name):
                    continue
                paramset = getattr(comp.params, paramset_name)
                for param_name in paramset.keys():
                    if not hasattr(paramset, param_name):
                        continue
                    param = getattr(paramset, param_name)
                    if hasattr(param, 'shape_name') and param.name in widget_map:
                        new_name = widget_map[param.name].replace("_", " ")
                        param.name = new_name

    if metarig_version < 7:
        # We moved from using BBone Scale as a way to control widget size, to using the metarig bones' custom_shape_scale_xyz instead.
        # The conversion is easy enough to do.
        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component.inherited_component or pbone.cloudrig_component
            if comp.component_type in ('Single Control', 'Bone Copy', 'Bone Tweak', 'Raw Copy'):
                continue
            elif comp.component_class.__name__ == 'Component_RawCopy':
                continue
            old_scale = pbone.bone.bbone_x * 10
            length = pbone.bone.length
            ratio = old_scale / length
            pbone.custom_shape_scale_xyz *= ratio
            if comp and comp.component_type == 'Spine: Cartoon' and pbone == comp.component_pbone_chain[-1]:
                pbone.custom_shape_scale_xyz.y = 1.1

    if metarig_version < 8:
        # We let Lattice components use custom shape scale to define the size of the lattice.
        # Previously, lattice size was defined by the bone's length.
        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component
            if comp.component_type == 'Lattice':
                pbone.custom_shape_scale_xyz = Vector((1, 1, 1))
                pbone.use_custom_shape_bone_size = True

    if metarig_version < 9:
        # We changed some bone shapes.
        rotated_shapes = {
            'WGT-Root 2': Euler((-pi / 2, 0, 0)),
            'WGT-Root 3': Euler((-pi / 2, 0, 0)),
            'WGT-Root 4': Euler((-pi / 2, 0, 0)),
            'WGT-Root 5': Euler((-pi / 2, 0, 0)),
            'WGT-Root 6': Euler((-pi / 2, 0, 0)),
            'WGT-Mouth': Euler((-pi / 2, 0, 0)),
            'WGT-Diamond': Euler((0, 0, -pi / 2)),
            'WGT-Heel': Euler((-pi, 0, 0)),
        }
        for pbone in metarig.pose.bones:
            if pbone.custom_shape and pbone.custom_shape.name in rotated_shapes:
                pbone.custom_shape_rotation_euler.rotate(rotated_shapes[pbone.custom_shape.name])

    if metarig_version < 10:
        # New heel roll logic.
        for pbone in metarig.pose.bones:
            if pbone.cloudrig_component.component_type == 'Limb: Biped Leg':
                heel_bone = pbone.cloudrig_component.params.leg.heel_bone
                if not heel_bone:
                    continue
                ebone = metarig.data.edit_bones[heel_bone]
                if not ebone:
                    continue
                center = ebone.head + (ebone.tail - ebone.head) * 0.5
                length = ebone.length
                side = 1
                if ".L" in ebone.name:
                    side = -1
                ebone.head = center + Vector((length / 2, 0, 0)) * side
                ebone.tail = center - Vector((length / 2, 0, 0)) * side
                ebone.roll = 0

    if metarig_version < 11:
        # IK Stretch is now disabled by default.
        for pbone in metarig.pose.bones:
            if pbone.cloudrig_component.component_type in ('Chain: IK', 'Limb: Generic', 'Limb: Biped Leg'):
                pbone.cloudrig_component.params.ik_chain.default_stretch = 1.0

    if metarig_version < 12:
        # 'World Aligned' params are now strictly aligned to Blender's exact
        # world axes, rather than the nearest axes of the bone's current transforms.
        # The old behaviour was moved to a new "flatten_controls" param,
        # which is deprecated, since the new behaviour is just nicer.
        param_map = {
            'Spine: Cartoon': 'spine_toon',
            'Spine: IK/FK': 'spine',
            'Chain: IK': 'ik_chain',
            'Limb: Biped Leg': 'ik_chain',
            'Limb: Generic': 'ik_chain',
        }

        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component
            param_name = param_map.get(comp.component_type)
            if not param_name:
                continue

            params = getattr(comp.params, param_name)

            if param_name == 'ik_chain':
                # Renamed from "world_aligned" to "world_align".
                params.flatten_controls = params.get('world_aligned', False)
            else:
                params.flatten_controls = params.world_align
            params.world_align = False

    if metarig_version < 13:
        # Foot shape became customizable, but its default is inherited from the IK chain.
        # Uses new "soft-default" mechanism to switch to the Foot shape, but has to be done
        # retro-actively for pre-existing metarigs.
        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component
            if comp.component_type == 'Limb: Biped Leg':
                comp.params.ik_chain.shape_ik_master.shape_name = "Foot"

    if metarig_version < 14 and bpy.app.version < (5, 1, 0):
        # Fix for #309, only needed in Blender 5.0.
        for action_setup in cloudrig.generator.action_setups:
            if not action_setup.is_corrective:
                continue
            action_setup.trigger_select_a = action_setup.setup_id_to_str(action_setup.trigger_select_a, True)
            action_setup.trigger_select_b = action_setup.setup_id_to_str(action_setup.trigger_select_b, True)

    if metarig_version < 15:
        for pbone in metarig.pose.bones:
            comp = pbone.cloudrig_component
            if comp.component_type == 'Shoulder Bone':
                comp.params.fk_chain.shape_fk.name = "Shoulder"


def update_generated_rig_ui_scripts():
    """Replace local cloudrig.py UI scripts that don't match the current add-on version."""
    generation_dir = Path(__file__).parent.parent / 'generation'
    current_content = None

    for text in bpy.data.texts:
        if text.library or not text.use_module:
            continue
        if not any(arm.get('cloudrig_ui') is text and arm.get('is_generated_cloudrig') for arm in bpy.data.armatures):
            continue
        if current_content is None:
            current_content = (generation_dir / 'cloudrig.py').read_text()
        if text.as_string() == current_content:
            continue
        load_script(file_path=str(generation_dir), file_name='cloudrig.py', datablock=text)


def fix_corrective_actions_51(metarig):
    # Action setups saved in 5.0 may need fixing in 5.1.
    if bpy.app.version < (5, 1, 0):
        return
    cloudrig = metarig.cloudrig
    action_setups = cloudrig.generator.action_setups
    for action_setup in action_setups:
        if not action_setup.is_corrective:
            continue
        if not str.isdecimal(action_setup['trigger_select_a']):
            action_setup.trigger_select_a = action_setup['trigger_select_a']
        if not str.isdecimal(action_setup['trigger_select_b']):
            action_setup.trigger_select_b = action_setup['trigger_select_b']


@persistent
def update_all_metarigs(dummy=None):
    if not hasattr(bpy.data, 'objects'):
        # We want this function to run on Register, because we want to version metarigs in current scene
        # when user enables CloudRig. But this is not allowed by PyAPI, so we defer the call to until after
        # add-on registration completes, using a timer.
        bpy.app.timers.register(update_all_metarigs)
        return
    update_generated_rig_ui_scripts()
    context = bpy.context
    metarig_version = get_addon_prefs().cloud_metarig_version

    cloud_metarigs = [
        o for o in bpy.data.objects if o.type == 'ARMATURE' and is_cloud_metarig(o) and not is_generated_cloudrig(o)
    ]

    for metarig in cloud_metarigs:
        if metarig.library or metarig.override_library:
            # Don't try to version linked metarigs, there's no point.
            # Also, metarigs shouldn't get linked and overridden in the first place.
            continue

        # Trigger component type update callbacks to update_ui_bone_sets().
        # https://projects.blender.org/Mets/CloudRig/issues/164
        for pb in metarig.pose.bones:
            pb.cloudrig_component.update_ui_bone_sets()

        if metarig.cloudrig.metarig_version > metarig_version:
            print(f"\tFound a metarig with a higher metarig version than the current: {metarig.name}")
            print("\tIt must have been created with a newer version of CloudRig, and won't behave as expected.")
            print("\tYou should update CloudRig!")
            continue
        version_cloud_metarig_editmode(context, metarig)


def register():
    bpy.app.handlers.load_post.append(update_all_metarigs)


def unregister():
    try:
        bpy.app.handlers.load_post.remove(update_all_metarigs)
    except ValueError:
        pass
