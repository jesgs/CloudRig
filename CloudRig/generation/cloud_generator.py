# SPDX-License-Identifier: GPL-3.0-or-later

import bpy, os, traceback, sys
from bpy.types import Object, PropertyGroup, Collection, Text, Action, Operator
from bpy.props import (
    BoolProperty,
    PointerProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from collections import OrderedDict
from datetime import datetime
from mathutils import Matrix

from ..rig_component_features.widgets.widgets import (
    ensure_widget, 
    get_custom_shape_rig_data, 
    apply_custom_shape_rig_data
)
from .actions_component import ActionConstraintComponent
from ..rig_component_features.object import EnsureVisible
from ..rig_component_features.bone_gizmos import auto_initialize_gizmos
from ..rig_component_features.mechanism import relink_real_driver
from ..rig_component_features.bone_info import BoneInfo
from ..rig_components.cloud_base import Component_Base

from .troubleshooting import CloudRigLogEntry, CloudLogManager
from . import naming

from ..ui.actions_ui import ActionConstraintSetup
from ..utils.external.mechanism import refresh_all_drivers
from ..utils.external.collections import ensure_collection
from ..utils.rig import get_pbone_of_active, get_armature_dimensions
from ..utils.misc import (
    check_addon,
    load_script,
    assign_to_collection,
)
from ..bs_utils.properties import (
    copy_all_custom_properties,
    copy_all_runtime_properties,
    copy_property_group,
)
from ..bs_utils.prefs import get_addon_prefs
from ..bs_utils.hotkeys import register_hotkey

from .cloudrig import (
    is_active_cloud_metarig,
    is_active_cloudrig,
    is_cloud_metarig,
)
from .generate_test_animation import TestAnimationGeneratorMixin

class GeneratorProperties(PropertyGroup):
    # RNA data used by the CloudRig Generator.
    preserve_shapes_properties: BoolProperty(
        name="Preserve Shape Properties",
        description="Preserve custom shape properties on the generated rig, if available",
        default=False,
    )
    preserve_custom_shapes: BoolProperty(
        name="Preserve Custom Shapes",
        description="Preserve custom shapes on the generated rig, if available. If this is disabled, only other properties will be preserved, but not the shape object",
        default=True,
    )
    metarig_version: IntProperty(
        name="Metarig Version",
        description="Used for automatic versioning of metarigs",
        default=0,
    )
    target_rig: PointerProperty(
        name="Target Rig",
        description="Rig to re-genreate based on this metarig when the Generate button is used",
        type=Object,
    )
    ensure_root: StringProperty(
        name="Root Bone",
        description="Bones that would otherwise be orphaned will be parented to this bone. If the bone doesn't exist, it will be created",
        default='root',
    )
    properties_bone: StringProperty(
        name="Properties Bone",
        description="Bone to use as the default custom property storage. Can be the same as the root bone. If it doesn't exist and is required, a bone named 'Properties' will be created on the metarig",
        default='Properties',
    )

    custom_script: PointerProperty(
        name="Post-Generation Script",
        type=Text,
        description="Execute a python script after the rig is generated",
    )
    widget_collection: PointerProperty(
        name="Custom Shape Collection",
        type=Collection,
        description="Collection dedicated to storing nothing but the custom shapes used by this rig. Additional objects will result in warnings, and missing custom shapes will be re-linked during generation",
    )
    reload_widgets: BoolProperty(
        name="Overwrite Custom Shapes",
        description="Reload custom shapes, discarding any local modifications to them",
        default=True,
    )

    generate_test_action: BoolProperty(
        name="Generate Test Action",
        description="Whether to create/update the deform test action or not. Enabling this enables the Animation parameter category on FK chain components",
        default=False,
    )
    test_action: PointerProperty(
        name="Test Action",
        type=Action,
        description="Action which will be generated with the keyframes neccessary to test the rig's deformations",
    )

    auto_setup_gizmos: BoolProperty(
        name="Auto Setup Gizmos (EXPERIMENTAL)",
        description="Experiment with the initial BoneGizmo addon integration",
        default=False,
    )

    logs: CollectionProperty(type=CloudRigLogEntry)
    active_log_index: IntProperty(min=0)

    def remove_active_log(self):
        logs = self.logs

        active_index = self.active_log_index
        # This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
        to_index = active_index
        if to_index > len(logs) - 2:
            to_index = len(logs) - 2

        self.logs.remove(active_index)
        self.active_log_index = to_index

    @property
    def active_log(self):
        return self.logs[self.active_log_index] if len(self.logs) > 0 else None

    action_setups: CollectionProperty(type=ActionConstraintSetup)
    active_action_index: IntProperty(min=0)

    @property
    def active_action_setup(self) -> ActionConstraintSetup | None:
        if len(self.action_setups) > 0:
            return self.action_setups[self.active_action_index]

class CloudGeneratorError(Exception):
    """Exception raised for errors."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.traceback = traceback.format_exc()

    def __str__(self):
        return repr(self.message)

class CloudRig_Generator(TestAnimationGeneratorMixin):
    """
    This class is instantiated by the Generate operator.
    It instantiates the rig components and calls their rig generation functions.
    """

    def __init__(self, context, metarig):
        self.metarig = metarig
        self.target_rig = None
        self.params = metarig.cloudrig.generator

        self.custom_script_failure = False

        # Reset the metarig; This will be un-done when generation ends (even if it fails).
        self.loc_bkp = metarig.matrix_world.to_translation()
        self.rot_bkp = metarig.matrix_world.to_euler()
        self.scale_bkp = metarig.matrix_world.to_scale()

        metarig.data.pose_position = 'REST'
        metarig.matrix_world = Matrix.Identity(4)

        # Needed to make sure we get the correct scale
        context.view_layer.update()

        # Used to calculate sizes and distances in a rig-size-agnostic way.
        self.scale = max(get_armature_dimensions(metarig)) / 10
        self.naming = naming

        # Default kwargs that are passed in to every created BoneInfo.
        self.defaults = {
            'rotation_mode': 'XYZ',
        }

        # Wipe the generation log.
        self.logger = CloudLogManager(metarig)
        self.logger.clear()

        # Set flag to handle Bone Gizmos.
        self.use_gizmos = (
            check_addon(context, 'bone_gizmos') and self.params.auto_setup_gizmos
        )

    ### Helper functions/properties.
    def raise_generation_error(
        self, description_short="Generation Error", description="", **kwargs
    ):
        """For raising non-bug errors that should be fixable by the user."""

        self.logger.log_fatal_error(
            description_short, description=description, display_stack_trace='ADVANCED', **kwargs
        )
        errmsg = (description or description_short)
        base_bone_name = kwargs.get('base_bone_name', "")
        if base_bone_name:
            errmsg = base_bone_name + ": " + errmsg
        raise CloudGeneratorError(message=errmsg)

    def find_bone_info(self, name):
        for bone_set in self.bone_sets:
            if len(bone_set) == 0:
                continue
            exists = bone_set.get(name)
            if exists:
                return exists

    def ensure_widget(self, context, widget_name, overwrite=False):
        self.ensure_widget_collection(context)
        try:
            wgt = ensure_widget(
                widget_name,
                overwrite=overwrite,
            )
        except ValueError:
            self.raise_generation_error(
                "Failed to load custom shape",
                description=f"Failed to find custom shape named '{widget_name}'.",
            )
        coll = self.params.widget_collection or context.scene.collection
        assign_to_collection(wgt, coll)
        return wgt

    @property
    def all_components(self):
        for bone_name, component in self.component_map.items():
            yield component

    @property
    def bone_sets(self):
        for rig_component in self.component_map.values():
            for bone_set in rig_component.bone_sets.values():
                yield bone_set

    @property
    def bone_infos(self):
        for bone_set in self.bone_sets:
            for bone_info in bone_set:
                yield bone_info

    @property
    def bone_infos_sorted_by_roll_dependency(self) -> list[BoneInfo]:
        # Since we want to allow BoneInfos to define another bone's final roll
        # as their roll alignment, we need to make sure those bones are actually
        # created first... This is admittedly a bit awkward.
        bone_infos = list(self.bone_infos)

        sorted_list = [bi for bi in bone_infos if not bi.roll_bone]

        def add_bi(bi):
            if bi in sorted_list:
                return
            if bi.roll_bone not in sorted_list:
                add_bi(bi.roll_bone)
            parent_idx = sorted_list.index(bi.roll_bone)
            sorted_list.insert(parent_idx + 1, bi)

        for bi in bone_infos:
            add_bi(bi)

        # Return the sorted flat list of bones
        return sorted_list

    @property
    def root_bone_info(self):
        return self.find_bone_info(self.params.ensure_root)

    @property
    def root_components(self):
        for bone_name, component in self.component_map.items():
            if not component.parent_component:
                yield component

    ### Main generation function.
    def generate(self, context):
        """This is called by the Generate CloudRig opreator."""
        bpy.ops.object.mode_set(mode='OBJECT')

        metarig = self.metarig

        metarig.data.name = self.metarig.name
        self.params.metarig_version = get_addon_prefs(context).cloud_metarig_version
        self.driver_map = map_pbones_to_drivers(self.metarig)

        # If the previous generation failed, delete the failed rig.
        if 'failed_rig' in metarig:
            if metarig['failed_rig']:
                bpy.data.objects.remove(metarig['failed_rig'])
            del metarig['failed_rig']

        self.target_rig = create_target_rig_obj(context, metarig)
        if 'ui_data' in self.metarig.data:
            self.target_rig.data['ui_data'] = self.metarig.data['ui_data']
        self.logger.rig = self.target_rig
        self.logger.metarig = metarig
        self.defaults['rig'] = self.target_rig

        bpy.ops.object.mode_set(mode='EDIT')

        if self.params.ensure_root:
            self.ensure_root_bone_component(context, self.metarig, self.params.ensure_root)

        self.component_map = self.instantiate_rig_components()
        self.components_load_bone_infos(self.component_map, self.metarig)
        focus_select_obj(context, self.target_rig)

        bpy.ops.object.mode_set(mode='EDIT')

        self.components_create_bone_infos(context)
        self.components_create_interactions(context)
        if self.root_bone_info:
            self.parent_orphan_bone_infos_to_root()
        self.components_create_real_bones()
        self.components_write_ebone_data()

        bpy.ops.object.mode_set(mode='OBJECT')

        self.components_create_helper_objs(context)
        self.metarig.cloudrig_prefs.sync_collection_names()
        self.copy_bone_collections(src_armature_obj=metarig, target_armature_obj=self.target_rig)
        self.components_write_pbone_data(context, self.target_rig)

        if self.params.generate_test_action:
            self.components_create_test_animation()

        if self.params.action_setups:
            action_con_component = ActionConstraintComponent(self)
            for action_setup, action_side_map in action_con_component.action_setup_side_map.items():
                for side, action_setup_side in action_side_map.items():
                    action_setup_side.create_custom_property()
                    action_setup_side.rig_bones_and_shape_keys()

        ensure_cloudrig_ui(self.target_rig)

        if self.params.reload_widgets and self.params.widget_collection:
            for obj in self.params.widget_collection.objects:
                if not obj.name.startswith("WGT-"):
                    # This is a custom widget and it's not even following naming convention, so we're
                    # not gonna be able to reload it anyways.
                    continue
                self.ensure_widget(
                    context, obj.name.replace("WGT-", ""), overwrite=True
                )

        if self.params.auto_setup_gizmos and self.use_gizmos:
            auto_initialize_gizmos(self.target_rig, self.bone_infos)

        old_rig = self.params.target_rig
        self.execute_custom_script(old_rig, self.target_rig)

        if old_rig:
            self.replace_old_with_new_rig(
                context,
                old_rig=old_rig,
                new_rig=self.target_rig,
            )
        else:
            self.target_rig.name = self.target_rig.name.replace("NEW-", "")

        # This comes after custom script because the script might mess with widgets.
        # And it comes after rig replacement so the object name doesn't get stored with the "NEW-" prefix.
        self.log_minor_issues()

        # NOTE: Any errors arising after replacing the rigs is really bad,
        # because then the user gets an error even though their old rig has been
        # overwritten. They can't be sure if their rig is in a clean state or not.
        # So, keep these final pieces of generation code simple!

        # Set the param as the target rig.
        # Important for first generation.
        self.params.target_rig = self.target_rig

        self.target_rig.data.name = self.target_rig.name

        self.restore_rig_states(context)
    
    ### Early generation steps.
    def ensure_widget_collection(self, context) -> Collection:
        """Create the collection where bone shapes will be linked to."""
        if not self.params.widget_collection:
            wgts_group_name = self.target_rig.name.replace("NEW-RIG-", "") + "-custom_shapes"
            self.params.widget_collection = ensure_collection(
                context, wgts_group_name, hidden=True
            )

        return self.params.widget_collection

    def instantiate_rig_components(self) -> dict[str, Component_Base]:
        """Refresh the generation order stored in each rig component, then create rig instances based on that order."""
        self.metarig.cloudrig.refresh_generation_order()

        component_bones_ordered = [
            pb
            for pb in sorted(
                self.metarig.pose.bones, key=lambda pb: pb.cloudrig_component.order
            )
            if pb.cloudrig_component.component_type
            and pb.cloudrig_component.is_enabled_component
        ]

        comp_map = OrderedDict()
        for pb in component_bones_ordered:
            parent_component_rna = pb.cloudrig_component.parent
            parent_component = None
            if parent_component_rna:
                parent_component = comp_map.get(parent_component_rna.base_bone_name)
                assert (
                    parent_component
                ), "Error: Parent should've been instantiated already! Are we not looping hierarchically?"

            comp_instance = pb.cloudrig_component.instantiate(
                generator=self, parent_component=parent_component
            )
            if not comp_instance:
                self.logger.log(
                    "Invalid Component Type",
                    note=pb.cloudrig_component.component_type,
                    base_bone_name=pb.name,
                    description="This component type no longer exists in CloudRig. Perhaps it's been renamed or removed. Please re-assign a valid component type.",
                    operator='pose.cloudrig_assign_component_type',
                    op_kwargs={'bone_name': pb.name, 'remove_active_log': True},
                    op_text="Assign Component",
                )
                continue
            comp_map[pb.name] = comp_instance

        return comp_map

    def ensure_root_bone_component(self, context, metarig, root_name='root'):
        if root_name in metarig.data.edit_bones:
            edit_bone = metarig.data.edit_bones[root_name]
            if edit_bone.parent:
                self.logger.log("Root Bone has a parent!", base_bone_name=edit_bone.parent.name, description="If you've added an additional root parent, make sure to set that as the Root Bone under the Generation panel")
            return metarig.pose.bones[root_name]
        edit_bone = create_bone(metarig, root_name)
        name = edit_bone.name
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')

        pose_bone = metarig.pose.bones[name]
        pose_bone.rotation_mode = 'XYZ'
        pose_bone.cloudrig_component.component_type = 'Bone Copy'
        pose_bone.custom_shape = self.ensure_widget(context, "Root")
        return pose_bone

    ### Main generation steps.
    def components_load_bone_infos(self, component_map, metarig):
        """While in edit mode (so we can access as much data as possible)
        let all rig components populate their initial BoneInfo instances.
        """

        bone_infos = {}

        for bone_name, component in component_map.items():
            if hasattr(component, 'base__load_metarig_bones'):
                bone_infos.update(component.base__load_metarig_bones())

        # Parent has to be stored in a separate loop, after all BoneInfos are loaded.
        for bone_name, bone_info in bone_infos.items():
            ebone = metarig.data.edit_bones.get(bone_name)
            if ebone.parent:
                parent_bone_info = bone_infos.get(ebone.parent.name)
                if parent_bone_info:
                    bone_info.parent = parent_bone_info
                else:
                    # This could be supported, but for now, this feels better for code maintainability,
                    # so that BoneInfo._parent doesn't have to support strings as parents.
                    # Alternatively, we could create BoneInfo instances of the component-less parent bone,
                    # implicitly giving it a Bone Copy behaviour.
                    self.raise_generation_error(f'Parent of "{bone_info.name}" is "{ebone.parent.name}", which is not part of any rig component. Assign it at least a "Bone Copy" component type.')

    def components_create_bone_infos(self, context):
        """Create BoneInfos that will get turned into real bones later."""

        for component in self.all_components:
            component.create_bone_infos(context)

    def components_create_interactions(self, context):
        """Once all rig components have created their BoneInfos, we can safely
        create relationships between components, since all bones exist.
        Having this be a separate step is really important for a lenient and flexible
        parent switching system, allowing users to select any bone as a parent.
        """

        for component in self.all_components:
            component.create_component_interactions(context)

    def components_create_real_bones(self):
        """Create real bones from all BoneInfos.
        No bone data is written yet beside the name.
        This function should be called before components_write_ebone_data()
        so that setting the parents can be done without worrying about creation order.
        """

        bones_created = []

        for bone_info in self.bone_infos:
            if not bone_info.create:
                continue
            if bone_info.name in self.target_rig.data.edit_bones:
                # This happens for ORG bones that we load into BoneInfo objects,
                # since they already get created by __duplicate_rig()
                if bone_info.name in bones_created:
                    # If a BoneInfo with this name was already created in this loop, we have a name collision.
                    self.raise_generation_error(
                        description=f"Bone `{bone_info.name}` was already created. It can't be created again by `{bone_info.bone_set.rig_component.base_bone_name}`. This could be a bug, but it could also be caused by bones not being named uniquely enough."
                    )
                bones_created.append(bone_info.name)
                continue

            edit_bone = create_bone(self.target_rig, bone_info.name)
            bone_info.name = edit_bone.name
            assert (
                bone_info.name == edit_bone.name
            ), "Bone names clash. Should have been caught already."
            bones_created.append(bone_info.name)

    def parent_orphan_bone_infos_to_root(self):
        for bone_info in self.bone_infos:
            if bone_info == self.root_bone_info:
                continue
            if bone_info.is_orphan:
                bone_info.parent = self.root_bone_info

    def components_write_ebone_data(self):
        """Write edit bone data for BoneInfos.
        This function does not create EditBones. 
        That should be done earlier by calling components_create_real_bones(),
        so that parenting can be done without worrying about order.
        """

        for bone_info in self.bone_infos_sorted_by_roll_dependency:
            edit_bone = self.target_rig.data.edit_bones.get(bone_info.name)
            bone_info.write_edit_data(self, edit_bone)

    def components_create_helper_objs(self, context):
        """Called in Object mode once bones have been created and placed."""
        for component in self.all_components:
            component.create_helper_objects(context)

    @staticmethod
    def copy_bone_collections(src_armature_obj, target_armature_obj):
        for src_coll in src_armature_obj.data.collections_all:
            tgt_coll = target_armature_obj.data.collections_all.get(src_coll.name)
            if not tgt_coll:
                tgt_coll = target_armature_obj.data.collections.new(src_coll.name)
                copy_all_runtime_properties(src_coll, tgt_coll)
            tgt_coll.is_visible = src_coll.is_visible

            # Copy drivers of BoneCollection properties.
            if src_armature_obj.data.animation_data:
                for src_driver in src_armature_obj.data.animation_data.drivers:
                    if not src_driver.data_path.startswith(f'collections_all["{src_coll.name}"]'):
                        continue
                    if not target_armature_obj.data.animation_data:
                        target_armature_obj.data.animation_data_create()
                    drv = target_armature_obj.data.animation_data.drivers.from_existing(src_driver=src_driver).driver
                    relink_real_driver(drv, src_armature_obj, target_armature_obj)

        target_armature_obj.data.collections.active_index = src_armature_obj.data.collections.active_index

        # Parenting has to be done as a separate loop because `collections_all` 
        # appears to be in creation order, not hierarchy order.
        for src_coll in src_armature_obj.data.collections_all:
            tgt_coll = target_armature_obj.data.collections_all.get(src_coll.name)
            if not tgt_coll:
                continue

            if src_coll.parent:
                parent = target_armature_obj.data.collections_all.get(src_coll.parent.name)
                tgt_coll.parent = parent

    def components_write_pbone_data(self, context, target_rig):
        for bone_info in self.bone_infos:
            if not bone_info.create:
                continue
            # Ensure bone collections in both the metarig and the target rig.
            # TODO: Is this still needed?
            for collection_name in bone_info.collections:
                meta_coll = self.metarig.data.collections_all.get(collection_name)
                if not meta_coll:
                    meta_coll = self.metarig.data.collections.new(collection_name)
                    meta_coll.cloudrig_info.name = meta_coll.name
                    meta_coll.is_visible = True

                target_coll = target_rig.data.collections_all.get(collection_name)
                if not target_coll:
                    target_coll = target_rig.data.collections.new(collection_name)
                    target_coll.cloudrig_info.name = target_coll.name
                    target_coll.is_visible = meta_coll.is_visible

            pose_bone = target_rig.pose.bones.get(bone_info.name)
            if not pose_bone:
                # TODO: This should never happen. Should probably be treated as a bug.
                self.logger.log(
                    "Bone creation failed",
                    base_bone_name=bone_info.owner_component.base_bone_name,
                    trouble_bone=bone_info.name,
                    description=f'BoneInfo "{bone_info.name}" was not created for some reason.',
                )
                continue

            # Scale bone shape based on B-Bone scale
            bone_info.write_pose_data(context, self.metarig, pose_bone)

    ### Final generation steps.
    def execute_custom_script(self, old_rig: Object|None, new_rig: Object):
        """Execute a text datablock to be executed after rig generation."""
        # This is a bit hacky, but we need the rig name to be the "original" so that 
        # post-gen script authors can get a reference to the rig easily.
        # (Since we don't want to move execution of the post-gen script after replace_old_with_new_rig)
        script = self.params.custom_script
        if not script:
            return
        if old_rig:
            old_rig.name = "OLD-" + old_rig.name
        new_rig.name = new_rig.name.replace("NEW-", "")
        try:
            exec(script.as_string(), {})
        except Exception as exc:
            self.logger.log_fatal_error(
                "Post-Generation Script failed.",
                description=f'Execution of post-generation script in text datablock "{script.name}" failed, see stack trace below.',
                note=str(exc),
                display_stack_trace='ALWAYS',
            )
            self.custom_script_failure = True
            raise exc
        finally:
            new_rig.name = "NEW-"+new_rig.name
            if old_rig:
                old_rig.name = old_rig.name.replace("OLD-", "")

    def replace_old_with_new_rig(
        self, context, old_rig, new_rig, preserve_custom_props=True
    ):
        """Preserve useful user-inputted information from the previous rig,
        then delete it and remap users to the new rig.
        """
        # TODO: Document what properties are and aren't preserved.

        # If cloudrig.py is linked, save that reference. This will be checked for
        # later, in ensure_cloudrig_ui.
        if (
            'cloudrig_ui' in old_rig.data
            and old_rig.data['cloudrig_ui']
            and old_rig.data['cloudrig_ui'].library
        ):
            new_rig.data['cloudrig_ui'] = old_rig.data['cloudrig_ui']

        if preserve_custom_props:
            # Preserve all custom properties and add-on properties.
            # Selection Sets, Bone Gizmos, Asset Pipeline, etc...
            copy_all_runtime_properties(old_rig, new_rig)

        old_data_name = old_rig.data.name
        old_rig.data.name += "_old"

        # Preserve parenting information of previous rig.
        new_rig.parent = old_rig.parent
        new_rig.parent_type = old_rig.parent_type
        new_rig.parent_bone = old_rig.parent_bone
        new_rig.parent_vertices = old_rig.parent_vertices
        new_rig.matrix_parent_inverse = old_rig.matrix_parent_inverse.copy()

        # Preserve transform matrix of previous rig.
        new_rig.matrix_world = old_rig.matrix_world.copy()

        # Preserve assigned action of previous rig.
        if old_rig.animation_data and old_rig.animation_data.action:
            if not new_rig.animation_data:
                new_rig.animation_data_create()
            new_rig.animation_data.action = old_rig.animation_data.action
            if hasattr(new_rig.animation_data, 'action_slot'):
                new_rig.animation_data.action_slot = old_rig.animation_data.action_slot

        # Preserve Armature display settings.
        new_rig.display_type = old_rig.display_type
        new_rig.show_in_front = old_rig.show_in_front
        new_rig.data.display_type = old_rig.data.display_type
        new_rig.data.show_axes = old_rig.data.show_axes

        # Preserve bone collections which are marked with preserve_on_regenerate.
        for old_idx, old_coll in enumerate(old_rig.data.collections_all):
            if not old_coll.cloudrig_info.preserve_on_regenerate:
                continue
            new_coll = new_rig.data.collections.get(old_coll.name)
            if not new_coll:
                parent = None
                if old_coll.parent:
                    parent = new_rig.data.collections_all.get(old_coll.parent.name)
                new_coll = new_rig.data.collections.new(old_coll.name, parent=parent)
                new_coll.name = old_coll.name
            copy_property_group(old_coll.cloudrig_info, new_coll.cloudrig_info)
            new_coll.is_visible = old_coll.is_visible
            for old_bone in old_coll.bones:
                new_bone = new_rig.data.bones.get(old_bone.name)
                if new_bone:
                    new_coll.assign(new_bone)
            for old_child in old_coll.children:
                new_child = new_rig.data.collections_all.get(old_child.name)
                if new_child:
                    new_child.parent = new_coll
            new_coll_idx = new_rig.data.collections_all.find(new_coll.name)
            max_idx = len(new_rig.data.collections)
            try:
                new_rig.data.collections.move(new_coll_idx, min(old_idx, max_idx))
            except RuntimeError:
                # Shouldn't really happen anymore...
                pass
        new_rig.data.collections.active_index = 0

        # Select and make active the new rig.
        new_rig.select_set(True)
        context.view_layer.objects.active = new_rig

        # Remove old rig from all of its collections, and link the new rig to them.
        for coll in new_rig.users_collection:
            coll.objects.unlink(new_rig)
        for coll in old_rig.users_collection:
            coll.objects.unlink(old_rig)
            coll.objects.link(new_rig)

        # Swap all references pointing at the old rig to the new rig.
        old_rig.id_data.user_remap(new_rig)
        old_name = old_rig.name

        # Preserve custom shapes.
        if self.params.preserve_shapes_properties:
            custom_shape_data = get_custom_shape_rig_data(old_rig)
            if not self.params.preserve_custom_shapes:
                for key, value in custom_shape_data.items():
                    del value['custom_shape']
            apply_custom_shape_rig_data(new_rig, custom_shape_data)

        # Delete the old rig.
        bpy.data.objects.remove(old_rig)

        # Preserve object/data name of previous rig.
        new_rig.name = old_name
        new_rig.data.name = old_data_name

    def restore_rig_states(self, context):
        """Restore transforms after generation has either failed or succeeded."""
        self.metarig.data.pose_position = 'POSE'
        if self.target_rig:
            self.target_rig.data.pose_position = 'POSE'
        self.metarig.location = self.loc_bkp.copy()
        self.metarig.rotation_euler = self.rot_bkp.copy()
        self.metarig.scale = self.scale_bkp.copy()

        refresh_all_drivers()
        refresh_constraints(self.target_rig)
        context.view_layer.update()

    def log_minor_issues(self):
        if self.params.widget_collection:
            self.logger.report_widgets(self.params.widget_collection)
        self.logger.report_unused_bone_collections(self.metarig, self.target_rig)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.metarig)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.target_rig)
        self.logger.report_drivers_targetting_armature_constraint(self.target_rig)
        self.logger.report_sus_constraints(self.target_rig)
        self.logger.report_actions()


def ensure_cloudrig_ui(rig):
    """Load and execute cloudrig.py rig UI script."""
    if 'cloudrig_ui' in rig.data:
        # If the rig UI script is linked, it's been preserved in
        # replace_old_with_new_rig().
        # This also allows the post-generation script to assign a custom script.
        return
    rig.data['cloudrig_ui'] = load_script(
        file_path=os.path.dirname(os.path.realpath(__file__)), file_name="cloudrig.py"
    )


def create_bone(rig_ob, bone_name: str):
    """Adds a new bone to the active Armature object.
    Must be in edit mode.
    Returns the resulting Edit Bone.
    """
    edit_bone = rig_ob.data.edit_bones.new(bone_name)
    edit_bone.head = (0, 0, 0)
    edit_bone.tail = (0, 1, 0)
    edit_bone.roll = 0
    return edit_bone


def create_target_rig_obj(context, metarig) -> Object:
    """Create a new empty Armature object that will get populated throughout
    the generation process.
    We start with a duplicate of the Metarig object, but a blank Armature datablock.
    This means that object-level data on the Metarig such as custom properties and constraints, will be preserved.
    """
    metaname = metarig.name
    final_name = metaname.replace("META", "RIG")
    if 'META' not in metaname:
        final_name = "RIG-" + metaname

    rig_name = "NEW-" + final_name

    armature = bpy.data.armatures.new(name=rig_name)
    target_rig = metarig.copy()

    # Nuke drivers targetting the Pose. (ie. PoseBone drivers).
    if target_rig.animation_data:
        for fc in target_rig.animation_data.drivers[:]:
            if fc.data_path.startswith('pose'):
                target_rig.animation_data.drivers.remove(fc)

    # Remove duplicated CloudRig data to clear ID references used by the metarig.
    target_rig.property_unset('cloudrig')

    target_rig.name = rig_name
    target_rig.data = armature

    context.scene.collection.objects.link(target_rig)
    # Mark rig for cloudrig.py compatibility checks.
    target_rig.data['is_generated_cloudrig'] = True

    # Wipe selection sets.
    target_rig.selection_sets.clear()

    # Save generation timestamp to a custom property.
    today = datetime.today()
    date = f"{today.year}-{today.month}-{today.day}"
    now = datetime.now()
    timestamp = (f"{str(now.hour).zfill(2)}:{str(now.minute).zfill(2)}:{str(now.second).zfill(2)}")
    target_rig.data['generation_date'] = date
    target_rig.data['generation_time'] = timestamp

    # By default, use B-Bone display type.
    target_rig.data.display_type = 'BBONE'

    # Copy debug viewport display settings from the metarig, usually used for debugging.
    target_rig.data.show_names = metarig.data.show_names
    target_rig.show_in_front = metarig.show_in_front
    target_rig.data.show_axes = metarig.data.show_axes

    target_rig.data.pose_position = 'REST'

    # Copy custom properties (and their drivers) of the Armature datablock.
    copy_all_custom_properties(metarig.data, target_rig.data)
    if not target_rig.data.animation_data:
        target_rig.data.animation_data_create()
    if metarig.data.animation_data:
        for src_driver in metarig.data.animation_data.drivers:
            drv = target_rig.data.animation_data.drivers.from_existing(src_driver=src_driver).driver
            relink_real_driver(drv, metarig, target_rig)

    return target_rig


def map_pbones_to_drivers(armature_ob) -> dict[str, tuple[str, int]]:
    """Create a dictionary matching bone names to full data paths of drivers
    that belong to those bones. This is to speed up loading drivers into BoneInfos."""
    driver_map = {}
    if not armature_ob.animation_data:
        return
    for fc in armature_ob.animation_data.drivers:
        data_path = fc.data_path
        if "pose.bones" not in data_path:
            continue
        bone_name = data_path.split('pose.bones["')[1].split('"]')[0]
        if bone_name not in driver_map:
            driver_map[bone_name] = []
        driver_map[bone_name].append((data_path, fc.array_index))
    return driver_map


def refresh_constraints(rig: Object):
    if not rig:
        return
    for pb in rig.pose.bones:
        for c in pb.constraints:
            if hasattr(c, 'target'):
                c.target = c.target
            if c.type == 'ARMATURE':
                for t in c.targets:
                    t.target = t.target


def focus_select_obj(context, obj):
    if not obj:
        return
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj


class CLOUDRIG_OT_generate(Operator):
    bl_idname = "pose.cloudrig_generate"
    bl_label = "Generate CloudRig"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Generates a rig from the active metarig armature"

    focus_generated: BoolProperty(
        name="Focus Generated",
        default=True,
        description="After a successful generation, hide the metarig, unhide the generated rig and make it active, and enter the same mode as the current mode",
    )
    preserve_state: BoolProperty(
        name="Preserve State",
        default=True,
        description="When re-generating a rig and Focus Generated is enabled, preserve the state of its bone and collection visibility, and bone selection",
    )

    @staticmethod
    def get_metarig_to_generate(context) -> Object | None:
        """Finds the metarig the user wants to generate.
        If there are more than one metarigs in the scene, use the active one,
        or the one referencing the active one.
        If there is only one metarig in the scene, just use that one.
        If there are multiple metarigs and neither they or their target rig is active,
        this returns None.
        """
        if is_active_cloud_metarig(context):
            return context.active_object
        elif is_active_cloudrig(context):
            # Find the metarig referencing this rig
            for obj in context.scene.objects:
                if (
                    obj.type == 'ARMATURE'
                    and obj.cloudrig.generator.target_rig == context.active_object
                ):
                    return obj

        metarigs = [obj for obj in context.scene.objects if is_cloud_metarig(obj)]
        if len(metarigs) == 1:
            return metarigs[0]

    @classmethod
    def poll(cls, context):
        """This operator is available when we can deduce from the context which
        metarig the user wants to generate."""
        metarig = cls.get_metarig_to_generate(context)
        if not metarig:
            cls.poll_message_set("Could not find a metarig in the current context.")
            return False
        return True

    def draw(self, context):
        # XXX: Re-doing the generation process crashes Blender,
        # so, just don't draw the operator properties, and therefore don't support re-do for now.
        return

    def execute(self, context):
        metarig = self.get_metarig_to_generate(context)
        prev_generated_rig = metarig.cloudrig.generator.target_rig

        if len(metarig.data.bones) == 0:
            self.report({'ERROR'}, "The metarig has no bones.")
            return {'CANCELLED'}
        if len([pb for pb in metarig.pose.bones if pb.cloudrig_component.component_module]) == 0:
            self.report({'ERROR'}, "The metarig has no bones with valid components assigned.")
            return {'CANCELLED'}

        # If the old rig isn't part of the scene, it needs to be.
        # The generation process works fine without this,
        # but it could confuse users if the generated rig isn't focused.
        if prev_generated_rig and prev_generated_rig not in set(context.view_layer.objects):
            self.report(
                {'ERROR'},
                f"Target rig '{prev_generated_rig.name}' cannot be re-generated because it is not in the current view layer.",
            )
            return {'CANCELLED'}

        # Save state so it can be restored for convenience.
        state_mode = 'OBJECT'
        if metarig is context.active_object:
            state_mode = metarig.mode
        elif prev_generated_rig and prev_generated_rig is context.active_object:
            state_mode = prev_generated_rig.mode
        active_pb = get_pbone_of_active(context)
        state_active_bone = active_pb.name if active_pb else ""
        if prev_generated_rig:
            if prev_generated_rig.mode == 'EDIT':
                ebones = prev_generated_rig.data.edit_bones
                state_selection = {
                    ebone.name: (ebone.select, ebone.select_head, ebone.select_tail)
                    for ebone in ebones
                }
                state_hide = {ebone.name: ebone.hide for ebone in ebones}
            else:
                pbones = prev_generated_rig.pose.bones
                state_selection = {
                    pbone.name: (pbone.select, pbone.select, pbone.select)
                    for pbone in pbones
                }
                state_hide = {ebone.name: ebone.hide for ebone in pbones}

            state_collections = {
                coll.name: coll.is_visible for coll in prev_generated_rig.data.collections_all
            }
        else:
            self.preserve_state = False

        # Ensure required visibility and active states.
        meta_visible = EnsureVisible(context, metarig)
        rig_visible = None
        if prev_generated_rig:
            rig_visible = EnsureVisible(context, prev_generated_rig)
        context.view_layer.objects.active = metarig

        # Try to generate a rig based on the metarig.
        new_rig = self.generate_rig(context, metarig)

        # Restore states.
        meta_visible.restore(context)
        if rig_visible:
            rig_visible.restore(context)

        if not new_rig:
            # if 'failed_rig' in metarig and metarig['failed_rig']:
            #     metarig['failed_rig'].select_set(False)
            #     metarig.select_set(True)

            # This means an error has occurred. It was already handled in generate_rig().
            self.report(
                {'ERROR'},
                f"Generation of {metarig.name} has failed. See the Generation Log for more info.",
            )
            return {'FINISHED'}
        elif self.focus_generated:
            self.focus_generated_rig(context, metarig, state_mode)

        if self.preserve_state and new_rig:
            self.restore_state(
                new_rig,
                mode=state_mode,
                active_bone_name=state_active_bone,
                state_selection=state_selection,
                state_hide=state_hide,
                state_collections=state_collections,
            )

        if len(metarig.cloudrig.generator.logs) > 0:
            self.report(
                {'WARNING'},
                f"Generation of {new_rig.name} successful with {len(metarig.cloudrig.generator.logs)} warnings.",
            )
        else:
            self.report({'INFO'}, f"Generation of {new_rig.name} successful.")

        return {'FINISHED'}

    def generate_rig(self, context, metarig: Object) -> Object | None:
        """Generates a rig from a metarig.

        Encountering a rig generation error will not halt the execution of the operator.
        This is important because the user can make mistakes in the MetaRig set-up,
        which cannot be detected until the rig is attempted to be fully generated.
        Such errors must be accounted for and handled gracefully.
        """

        generator_properties = metarig.cloudrig.generator
        generator = CloudRig_Generator(context, metarig)
        try:
            generator.generate(context)
        except Exception as exception:
            generator.restore_rig_states(context)

            focus_select_obj(context, generator.target_rig)

            if generator.target_rig:
                generator.target_rig.name = "FAILED-" + generator.target_rig.name
                generator.target_rig.name = generator.target_rig.name.replace("NEW-", "")
                metarig['failed_rig'] = generator.target_rig
                # Leave a reference to the Metarig, so the Toggle Metarig operator 
                # can find its way back to it.
                generator.target_rig['metarig'] = metarig

            if type(exception) == CloudGeneratorError:
                # A MetaRig error means the user created an invalid metarig set-up.
                # Importantly, this is not a bug.
                self.report({'ERROR'}, exception.message)
            else:
                if generator.custom_script_failure:
                    # The error occurred in the user's post-generation script.
                    # execute_custom_script() has already created the log entry for us,
                    # so we just want to keep raising the exception.
                    raise exception

                exception_module = get_exception_module(exception)
                operator = 'wm.cloudrig_report_bug'
                op_kwargs = {}
                if exception_module:
                    exc_mod_name = exception_module.__name__
                    is_cloudrig_bug = 'rig_components' not in exc_mod_name or "." not in exc_mod_name.split("rig_components.")[-1]
                    if is_cloudrig_bug:
                        operator = 'wm.cloudrig_report_bug'
                    elif (
                        hasattr(exception_module, 'RIG_COMPONENT_CLASS') and 
                        hasattr(exception_module.RIG_COMPONENT_CLASS, 'bug_report_url') and
                        exception_module.RIG_COMPONENT_CLASS.bug_report_url
                    ):
                        operator = 'wm.url_open'
                        op_kwargs = {'url':exception_module.RIG_COMPONENT_CLASS.bug_report_url}

                # Any other exception type is a bug.
                # We give the user a button to report the error.
                generator.logger.log_fatal_error(
                    "Execution Failed!",
                    description="Execution failed unexpectedly.",
                    note=str(exception),
                    operator=operator,
                    op_kwargs=op_kwargs,
                    op_text="Report Bug",
                    op_icon='URL',
                    display_stack_trace='ALWAYS',
                )

                self.report(
                    {'ERROR'},
                    f"A bug has occurred. You can report it through the Generation Log interface.\n{traceback.format_exc()}",
                )

            return

        return generator_properties.target_rig

    def focus_generated_rig(self, context, metarig: Object, mode='OBJECT'):
        """Focus the generated rig for convenient generation and re-generation workflow:
        - Hide the metarig.
        - Reveal the target rig and set it as selected and active.
        - Enter the same mode as before.
        """

        # Hide metarig.
        metarig.hide_set(True)
        target_rig = metarig.cloudrig.generator.target_rig
        target_rig.hide_set(False)

        # Make target rig visible, selected, active.
        if target_rig in context.view_layer.objects[:]:
            context.view_layer.objects.active = target_rig
            target_rig.select_set(True)

        # Restore object's mode.
        if target_rig.mode != mode:
            bpy.ops.object.mode_set(mode=mode)

    def restore_state(
        self,
        target_rig: Object,
        mode='OBJECT',
        active_bone_name="",
        state_selection={},
        state_hide={},
        state_collections={},
    ):
        """Restore rig state for convenient re-generation workflow:
        - Preserve bone active, selected, and hidden states where possible.
        - Preserve collection visibility states where possible.
        """

        # Bones initialize with their tail selected, so deselect them.
        if mode == 'EDIT':
            for ebone in target_rig.data.edit_bones:
                ebone.select_tail = False

        # Restore active bone.
        if active_bone_name in target_rig.pose.bones:
            target_rig.data.bones.active = target_rig.data.bones[active_bone_name]

        # Restore bone selection states (including head/tail).
        for bone_name, select_state in state_selection.items():
            if bone_name in target_rig.data.bones:
                if mode == 'EDIT':
                    ebone = target_rig.data.edit_bones[bone_name]
                    ebone.select, ebone.select_head, ebone.select_tail = (
                        select_state[0],
                        select_state[1],
                        select_state[2],
                    )
                else:
                    pbone = target_rig.pose.bones[bone_name]
                    pbone.select = select_state[0]

        # Restore bone visibility states.
        for bone_name, hide in state_hide.items():
            bone = target_rig.data.bones.get(bone_name)
            if not bone:
                continue
            bone.hide = hide

        # Restore collection visibility states.
        for coll_name, is_visible in state_collections.items():
            coll = target_rig.data.collections_all.get(coll_name)
            if not coll:
                continue
            coll.is_visible = is_visible

def get_exception_module(exc: Exception):
    tb = exc.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    frame = tb.tb_frame
    module_name = frame.f_globals.get("__name__")
    return sys.modules.get(module_name)

registry = [
    GeneratorProperties,
    CLOUDRIG_OT_generate,
]


def register():
    register_hotkey(
        CLOUDRIG_OT_generate.bl_idname,
        hotkey_kwargs={'type': "R", 'value': "PRESS", 'ctrl': True, 'alt': True},
        keymap_name="3D View",
    )
