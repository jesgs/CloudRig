import bpy, sys, os, traceback, time
from collections import OrderedDict

from bpy.props import (
    BoolProperty,
    PointerProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Object, PropertyGroup
from typing import List, Dict, Tuple, Optional

from bone_selection_sets import from_json, to_json
from mathutils import Matrix
from datetime import datetime

from ..ui.actions_ui import ActionSlot
from rigify.utils.mechanism import refresh_all_drivers
from rigify.utils.collections import ensure_collection

# TODO: All of these imports are suspiciously NOT rig component features if they are being used by the generator.
from ..rig_component_features.widgets import widgets as cloud_widgets
from ..rig_component_features.ui import redraw_viewport, get_addon_prefs
from ..rig_component_features import mechanism
from ..rig_component_features.object import EnsureVisible
from ..rig_component_features.bone_gizmos import auto_initialize_gizmos

from .troubleshooting import CloudRigLogEntry, CloudLogManager
from .naming import CloudNameManager

# from ..operators.assign_bone_layers import init_cloudrig_layers
from ..utils.misc import check_addon, load_script, get_pbone_of_active
from .cloudrig import (
    ensure_custom_panels,
    register_hotkey,
    is_active_cloud_metarig,
    is_active_cloudrig,
    is_cloud_metarig,
)
from .test_animation import TestAnimationGeneratorMixin

from ..rig_components.cloud_base import Component_Base
from .actions_component import ActionLayerComponent

import bpy, sys, os, traceback
from bpy.types import Object, Operator
from bpy.props import BoolProperty


class GeneratorProperties(PropertyGroup):
    # TODO: I see no reason why this class couldn't be merged with the one that
    # holds the generate() function, making a unified `Generator` class that
    # lives in RNA, giving us the ability to just to `my_metarig.cloudrig.generator.generate()`,
    # which would be pretty neat I think.
    metarig_version: IntProperty(
        name="Metarig Version",
        description="Used for automatic versioning of metarigs",
        default=0,
    )
    target_rig: PointerProperty(
        name="Target Rig",
        description="Rig to re-genreate based on this metarig when the Generate button is used",
        type=bpy.types.Object,
    )
    ensure_root: StringProperty(
        name="Ensure Root",
        description="Create a default root bone with the given name on the metarig before generating. Bones that would otherwise be orphaned will be parented to this bone",
        default='root',
    )
    properties_bone: StringProperty(
        name="Properties Bone",
        description="Bone to use as the default custom property storage. Can be the same as the root bone. If it doesn't exist and is required, a bone named 'Properties' will be created on the metarig",
        default='Properties',
    )

    custom_script: PointerProperty(
        name="Post-Generation Script",
        type=bpy.types.Text,
        description="Execute a python script after the rig is generated",
    )
    widget_collection: PointerProperty(
        name="Widget Collection",
        type=bpy.types.Collection,
        description="Collection dedicated to storing nothing but the widgets used by this rig. Additional objects will result in warnings, and missing widgets will be re-linked during generation",
    )

    generate_test_action: BoolProperty(
        name="Generate Test Action",
        description="Whether to create/update the deform test action or not. Enabling this enables the Animation parameter category on FK chain components",
        default=False,
    )
    test_action: PointerProperty(
        name="Test Action",
        type=bpy.types.Action,
        description="Action which will be generated with the keyframes neccessary to test the rig's deformations",
    )

    show_secret_collections: BoolProperty(  # TODO 4.0 implement this.
        name="Show Secret Collections",
        description="Show collections whose names contain $ and will be hidden on the rig UI",
        default=True,
        override={'LIBRARY_OVERRIDABLE'},
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

    action_slots: CollectionProperty(type=ActionSlot)
    active_action_index: IntProperty(min=0)

    @property
    def active_action_slot(self) -> Optional[ActionSlot]:
        if len(self.action_slots) > 0:
            return self.action_slots[self.active_action_index]

    def find_slot_by_action(self, action) -> Tuple[Optional[ActionSlot], int]:
        """Find the ActionSlot in the rig which targets this action."""
        if not action:
            return None, -1

        for i, slot in enumerate(self.action_slots):
            if slot.action == action:
                return slot, i
        else:
            return None, -1

    def find_duplicate_action_slot(self, slot: ActionSlot) -> Optional[ActionSlot]:
        """Find a different ActionSlot in the rig which has the same action."""

        for other_slot in self.action_slots:
            if other_slot.action == slot.action and other_slot != slot:
                return other_slot

        return None


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

        # TODO 4.0: __init__ should only be assigning stuff to self. This should be moved to generate().
        # Reset the metarig; This will be un-done when generation ends (even if it fails).
        self.loc_bkp = metarig.matrix_world.to_translation()
        self.rot_bkp = metarig.matrix_world.to_euler()
        self.scale_bkp = metarig.matrix_world.to_scale()

        metarig.data.pose_position = 'REST'
        metarig.matrix_world = Matrix.Identity(4)

        # Needed to make sure we get the correct scale # TODO: Is this really necessary?
        context.view_layer.update()

        # Used to calculate sizes and distances in a rig-size-agnostic way.
        self.scale = max(metarig.dimensions) / 10
        self.naming = CloudNameManager()

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
        # Set flag to handle Selection Sets.
        self.do_sel_sets = check_addon(context, 'bone_selection_sets')

    def raise_generation_error(
        self, description_short="Generation Error", description="", **kwargs
    ):
        """For raising non-bug errors that should be fixable by the user."""

        self.logger.log_fatal_error(
            description_short, description=description, **kwargs
        )

        raise CloudGeneratorError(message=description or description_short)

    ### Useful helper properties
    def find_bone_info(self, name):
        for bone_set in self.bone_sets:
            if len(bone_set) == 0:
                continue
            exists = bone_set.get(name)
            if exists:
                return exists

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
        print("Begin Generating CloudRig from metarig: " + metarig.name)

        metarig.data.name = "Data_" + self.metarig.name
        self.params.metarig_version = get_addon_prefs(context).cloud_metarig_version
        self.driver_map = map_pbones_to_drivers(self.metarig)

        # If the previous generation failed, delete the failed rig.
        if 'failed_rig' in metarig and metarig['failed_rig']:
            bpy.data.objects.remove(metarig['failed_rig'])
            del metarig['failed_rig']

        # Prepare the target rig.
        self.target_rig = create_target_rig_obj(context, metarig)
        self.logger.rig = self.target_rig
        self.logger.metarig = metarig
        self.defaults['rig'] = self.target_rig

        # Create Widget Collection
        # TODO: It could be argued that this should only happen when the first widget is created.
        self.ensure_widget_collection(context)

        # ------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')
        if self.params.ensure_root:
            self.ensure_root_bone_component(self.metarig, self.params.ensure_root)

        self.component_map = self.instantiate_rig_components()

        self.components_load_bone_infos(self.component_map, self.metarig)

        # ------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        self.target_rig.select_set(True)
        context.view_layer.objects.active = self.target_rig
        bpy.ops.object.mode_set(mode='EDIT')

        self.components_create_bone_infos(context)
        self.components_create_interactions()
        if self.root_bone_info:
            self.parent_orphan_bone_infos_to_root()
        self.components_create_real_bones()
        # ------------------------------------------
        self.components_write_ebone_data()

        # ------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        self.components_create_helper_objs(context)
        self.metarig.cloudrig_prefs.ensure_bone_collections_info()
        self.copy_bone_collections(src=metarig, target=self.target_rig)
        self.components_write_pbone_data(self.target_rig)

        # ------------------------------------------
        ensure_cloudrig_ui(self.target_rig)

        if self.params.generate_test_action:
            self.create_test_animation()  # TODO 4.0: Verify this works.

        actions = ActionLayerComponent(self)
        actions.initialize()
        for action_name, action_map in actions.action_map.items():
            for side, action_layer in action_map.items():
                action_layer.create_custom_property()
                action_layer.rig_bones_and_shape_keys()

        self.execute_custom_script()

        old_rig = self.params.target_rig
        if old_rig:
            replace_old_with_new_rig(
                context,
                old_rig,
                self.target_rig,
                preserve_sel_sets=self.do_sel_sets,
                preserve_gizmos=self.use_gizmos,
            )
        else:
            self.target_rig.name = self.target_rig.name.replace("NEW-", "")
        self.params.target_rig = self.target_rig

        if self.params.auto_setup_gizmos and self.use_gizmos:
            auto_initialize_gizmos()

        ensure_custom_panels(None, None)

        self.restore_rig_states(context)
        self.log_minor_issues()

    ### Early generation steps.
    def ensure_widget_collection(self, context):
        """Create the collection where bone shapes will be linked to."""
        if not self.params.widget_collection:
            wgts_group_name = "Widgets_" + self.target_rig.name.replace("RIG-", "")
            self.params.widget_collection = ensure_collection(
                context, wgts_group_name, hidden=True
            )

    def instantiate_rig_components(self) -> Dict[str, Component_Base]:
        """Refresh the generation order stored in each rig component, then create rig instances based on that order."""

        self.metarig.cloudrig.refresh_generation_order()

        component_bones_ordered = [
            pb
            for pb in sorted(
                self.metarig.pose.bones, key=lambda pb: pb.cloudrig_component.order
            )
            if pb.cloudrig_component.is_enabled_component
        ]

        comp_map = OrderedDict()
        for pb in component_bones_ordered:
            parent_component_rna = pb.cloudrig_component.parent
            parent_instance = None
            if parent_component_rna:
                parent_instance = comp_map.get(parent_component_rna.base_bone_name)
                assert (
                    parent_instance
                ), "Error: Parent should've been instantiated already! Are we not looping hierarchically?"

            comp_instance = pb.cloudrig_component.instantiate(
                generator=self, parent_instance=parent_instance
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

    def ensure_root_bone_component(self, metarig, root_name='root'):
        if root_name in metarig.data.edit_bones:
            return metarig.pose.bones[root_name]
        edit_bone = create_bone(metarig, root_name)
        name = edit_bone.name
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')

        pose_bone = metarig.pose.bones[name]
        pose_bone.rotation_mode = 'XYZ'
        pose_bone.cloudrig_component.component_type = 'Bone Copy'
        pose_bone.custom_shape = self.ensure_widget("Root")
        return pose_bone

    def ensure_widget(self, widget_name):
        wgt = cloud_widgets.ensure_widget(
            widget_name, overwrite=False, collection=self.params.widget_collection
        )
        if not wgt:
            self.logger.log_bug(
                "Failed to create widget",
                description=f"Failed to load widget named '{widget_name}'.",
            )
        return wgt


    ### Main generation steps
    @staticmethod
    def components_load_bone_infos(component_map, metarig):
        """While in edit mode (so we can access as much data as possible)
        let all rig components populate their initial BoneInfo instances.
        """

        bone_infos = {}

        for bone_name, component in component_map.items():
            if hasattr(component, 'load_metarig_bone_infos'):
                bone_infos.update(component.load_metarig_bone_infos(metarig))

        # Parent has to be stored in a separate loop, after all BoneInfos are loaded.
        for bone_name, bone_info in bone_infos.items():
            ebone = metarig.data.edit_bones.get(bone_name)
            if ebone.parent:
                parent_bone_info = bone_infos.get(ebone.parent.name)
                if parent_bone_info:
                    bone_info.parent = parent_bone_info
                else:
                    bone_info.parent = ebone.parent.name

    def components_create_bone_infos(self, context):
        """Create BoneInfos that will get turned into real bones later."""

        for component in self.all_components:
            component.create_bone_infos(context)

    def components_create_interactions(self):
        """Once all rig components have created their BoneInfos, we can safely
        create relationships between components, since all bones exist.
        """

        for component in self.all_components:
            component.create_component_interactions()

    def components_create_real_bones(self):
        """Create real bones from all BoneInfos.
        No bone data is written yet beside the name."""

        for bone_info in self.bone_infos:
            if not bone_info.create:
                continue
            if bone_info.name in self.target_rig.data.edit_bones:
                # This happens for ORG bones that we load into BoneInfo objects,
                # since they already get created by __duplicate_rig()
                continue
            edit_bone = create_bone(self.target_rig, bone_info.name)
            if edit_bone.name != bone_info.name:
                self.logger.log(
                    "Bone Name Clash",
                    trouble_bone=bone_info.name,
                    description=f'Bone name "{bone_info.name}" was already taken, got back to "{edit_bone.name}" instead.',
                )
                bone_info.name = edit_bone.name

    def parent_orphan_bone_infos_to_root(self):
        for bone_info in self.bone_infos:
            if bone_info == self.root_bone_info:
                continue
            if bone_info.is_orphan:
                bone_info.parent = self.root_bone_info

    def components_write_ebone_data(self):
        # Write edit bone data for BoneInfos.
        for bone_info in self.bone_infos:
            edit_bone = self.target_rig.data.edit_bones.get(bone_info.name)
            bone_info.write_edit_data(self, edit_bone)

    def components_create_helper_objs(self, context):
        """Called in Object mode once bones have been created and placed."""
        for component in self.all_components:
            component.create_helper_objects(context)

    @staticmethod
    def copy_bone_collections(src, target):
        for src_coll in src.data.collections:
            tgt_coll = target.data.collections.get(src_coll.name)
            if not tgt_coll:
                tgt_coll = target.data.collections.new(src_coll.name)
                tgt_coll['cloudrig_info'] = src_coll['cloudrig_info'].to_dict()
            tgt_coll.is_visible = src_coll.is_visible
        target.data.collections.active_index = src.data.collections.active_index

    def components_write_pbone_data(self, target_rig):
        for bone_info in self.bone_infos:
            if not bone_info.create:
                continue
            # Ensure bone collections in both the metarig and the target rig.
            for collection_name in bone_info.collections:
                meta_coll = self.metarig.data.collections.get(collection_name)
                if not meta_coll:
                    meta_coll = self.metarig.data.collections.new(collection_name)
                    meta_coll.cloudrig_info.name = meta_coll.name
                    meta_coll.is_visible = False

                target_coll = target_rig.data.collections.get(collection_name)
                if not target_coll:
                    target_coll = target_rig.data.collections.new(collection_name)
                    target_coll.cloudrig_info.name = target_coll.name
                    target_coll.is_visible = meta_coll.is_visible

            pose_bone = target_rig.pose.bones.get(bone_info.name)
            if not pose_bone:
                # TODO: This should never happen. Should be treated as a bug, probably.
                self.logger.log(
                    "Bone creation failed",
                    base_bone_name=bone_info.owner_component.base_bone_name,
                    trouble_bone=bone_info.name,
                    description=f'BoneInfo "{bone_info.name}" was not created for some reason.',
                )
                continue

            # Scale bone shape based on B-Bone scale
            bone_info.write_pose_data(pose_bone)
            if (
                not pose_bone.use_custom_shape_bone_size
                and bone_info.use_custom_shape_bbone_scaling
            ):
                pose_bone.custom_shape_scale_xyz *= (
                    bone_info.bbone_width * 10 * self.scale
                )

    ### Generation final steps
    def execute_custom_script(self):
        """Execute a text datablock to be executed after rig generation."""
        script = self.params.custom_script
        if not script:
            return
        try:
            exec(script.as_string(), {})
        except Exception as e:
            self.logger.log_fatal_error(
                "Post-Generation Script failed.",
                description=f'Execution of post-generation script in text datablock "{script.name}" failed, see stack trace below.',
                note=str(e),
            )
            self.custom_script_failure = True
            raise e

    def restore_rig_states(self, context):
        """Restore transforms after generation has either failed or succeeded."""
        self.metarig.data.pose_position = 'POSE'
        self.target_rig.data.pose_position = 'POSE'
        self.metarig.location = self.loc_bkp.copy()
        self.metarig.rotation_euler = self.rot_bkp.copy()
        self.metarig.scale = self.scale_bkp.copy()

        # Refresh drivers
        refresh_all_drivers()
        refresh_constraints(self.target_rig)
        context.view_layer.update()

    def log_minor_issues(self):
        self.logger.report_widgets(self.params.widget_collection)
        self.logger.report_unused_bone_collections(self.metarig, self.target_rig)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.metarig)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.target_rig)
        # self.logger.report_actions()


def ensure_cloudrig_ui(rig):
    """Load and execute cloudrig.py rig UI script."""
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
    the generation process."""
    metaname = metarig.name
    final_name = metaname.replace("META", "RIG")
    if 'META' not in metaname:
        final_name = "RIG-" + metaname

    rig_name = "NEW-" + final_name

    armature = bpy.data.armatures.new(name=rig_name)
    target_rig = bpy.data.objects.new(rig_name, armature)
    context.scene.collection.objects.link(target_rig)
    # Mark rig for cloudrig.py compatibility checks
    target_rig.data['is_generated_cloudrig'] = True

    # Save generation timestamp to a custom property
    today = datetime.today()
    now = datetime.now()
    target_rig.data['generation_date'] = f"{today.year}-{today.month}-{today.day}"
    target_rig.data[
        'generation_time'
    ] = f"{str(now.hour).zfill(2)}:{str(now.minute).zfill(2)}:{str(now.second).zfill(2)}"

    # Make sure this flag is saved in the generated rig, so it
    # remains even if the Rigify addon is disabled.
    target_rig.cloudrig.generator.show_secret_collections = False

    # By default, use B-Bone display type since it's the most useful
    target_rig.data.display_type = 'BBONE'

    # Copy debug viewport display settings from the metarig, usually used for debugging.
    target_rig.data.show_names = metarig.data.show_names
    target_rig.show_in_front = metarig.show_in_front
    target_rig.data.show_axes = metarig.data.show_axes

    target_rig.data.pose_position = 'REST'

    return target_rig


def map_pbones_to_drivers(armature_ob) -> Dict[str, Tuple[str, int]]:
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


def replace_old_with_new_rig(
    context, old_rig, new_rig, preserve_sel_sets=True, preserve_gizmos=True
):
    """Preserve useful user-inputted information from the previous rig,
    then delete it and remap users to the new rig.

    TODO: Instead of starting a fresh object from scratch, we could duplicate the old target rig,
    and just delete the bones. That way everything we don't explicitly delete gets implicitly preserved.
    For example, right now we are not preserving arbitrary custom properties, even though that might be nice.
    This approach could also eventually enable us to regenerate only parts of a rig.
    """

    # Save Selection Sets.
    if preserve_sel_sets:
        context.view_layer.objects.active = old_rig
        for selset in old_rig.selection_sets:
            selset.is_selected = True
        selsets = to_json(context)

    # Save Custom Gizmo settings.
    if preserve_gizmos:
        gizmo_properties_class = bpy.types.PropertyGroup.bl_rna_get_subclass_py(
            'BoneGizmoProperties'
        )
        for old_pb in old_rig.pose.bones:
            new_pb = new_rig.pose.bones.get(old_pb.name)
            new_pb.enable_bone_gizmo = old_pb.enable_bone_gizmo
            for key in gizmo_properties_class.__annotations__.keys():
                value = getattr(old_pb.bone_gizmo, key)
                setattr(new_pb.bone_gizmo, key, value)

    # Remove old rig from all of its collections, and link the new rig to them.
    for coll in new_rig.users_collection:
        coll.objects.unlink(new_rig)
    for coll in old_rig.users_collection:
        coll.objects.unlink(old_rig)
        coll.objects.link(new_rig)

    old_data_name = old_rig.data.name
    old_rig.data.name += "_old"

    # Swap all references pointing at the old rig to the new rig.
    old_rig.id_data.user_remap(new_rig)
    old_name = old_rig.name

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

    # Preserve Armature display settings.
    new_rig.display_type = old_rig.display_type
    new_rig.show_in_front = old_rig.show_in_front
    new_rig.data.display_type = old_rig.data.display_type
    new_rig.data.show_axes = old_rig.data.show_axes

    # Preserve collections which are marked with preserve_on_regenerate.
    for old_idx, old_coll in enumerate(old_rig.data.collections):
        if not old_coll.cloudrig_info.preserve_on_regenerate:
            continue
        new_coll = new_rig.data.collections.get(old_coll.name)
        if not new_coll:
            new_coll = new_rig.data.collections.new(old_coll.name)
        new_coll['cloudrig_info'] = old_coll['cloudrig_info'].to_dict()
        for old_bone in old_coll.bones:
            new_bone = new_rig.data.bones.get(old_bone.name)
            if new_bone:
                new_coll.assign(new_bone)
        new_coll_idx = new_rig.data.collections.find(new_coll.name)
        max_idx = len(new_rig.data.collections)
        new_rig.data.collections.move(new_coll_idx, min(old_idx, max_idx))
    new_rig.data.collections.active_index = 0

    # Delete the old rig.
    bpy.data.objects.remove(old_rig)

    # Preserve object/data name of previous rig.
    new_rig.name = old_name
    new_rig.data.name = old_data_name

    # Select and make active the new rig.
    new_rig.select_set(True)
    context.view_layer.objects.active = new_rig

    # Preserve selection sets of old rig.
    if preserve_sel_sets:
        from_json(context, selsets)


def refresh_constraints(rig: Object):
    for pb in rig.pose.bones:
        for c in pb.constraints:
            if hasattr(c, 'target'):
                c.target = c.target
            if c.type == 'ARMATURE':
                for t in c.targets:
                    t.target = t.target


def ___reorder_rig_components(self, rig_list):
    """Some rig types need special treatment in regards to where they are in
    the rig generation order."""
    # TODO 4.0: This should be handled by the Rig Component List UI, parenting, and move up/down operators...
    from ..rig_components.cloud_tweak import Component_TweakBone
    from ..rig_components.cloud_chain_anchor import Component_FaceChainAnchor
    from ..rig_components.cloud_face_chain import Component_FaceChain
    from ..rig_components.cloud_jaw import Component_Jaw

    first_face_idx = -1
    for i, rig in enumerate(rig_list[:]):
        if isinstance(rig, Component_TweakBone) or isinstance(
            rig, Component_FaceChainAnchor
        ):
            # cloud_tweak components should be generated last.
            rig_list.remove(rig)
            rig_list.append(rig)
        if isinstance(rig, Component_FaceChain) and first_face_idx == -1:
            first_face_idx = i

    for i, rig in enumerate(rig_list[:]):
        if isinstance(rig, Component_Jaw):
            for param_name in {
                'CR_jaw_lower_face_bone',
                'CR_jaw_squash_bone',
                'CR_jaw_chin_bone',
                'CR_jaw_mouth_bone',
                'CR_jaw_teeth_follow',
                'CR_jaw_teeth_upper_bone',
                'CR_jaw_teeth_lower_bone',
            }:
                bone_name = getattr(rig.params, param_name)
                dependency_component = self.component_map.get(bone_name)
                if dependency_component:
                    rig_list.remove(dependency_component)
                    rig_list.insert(i - 1, dependency_component)

    for rig in rig_list[:]:
        if isinstance(rig, Component_FaceChainAnchor):
            # cloud_chain_anchor pushed before the first cloud_face_chain.
            rig_list.remove(rig)
            rig_list.insert(first_face_idx, rig)


class CLOUDRIG_OT_generate(Operator):
    """Generates a rig from the active metarig armature using the CloudRig generator"""

    bl_idname = "pose.cloudrig_generate"
    bl_label = "Generate CloudRig"
    bl_options = {'UNDO'}
    bl_description = (
        'Generates a rig from the active metarig armature using the CloudRig generator'
    )

    focus_generated: BoolProperty(
        name="Focus Generated",
        default=True,
        description="After successfully generating a single rig, hide the metarig, unhide the generated rig, enter the same mode as the current mode, and match bone selection states where possible",
    )

    @staticmethod
    def get_metarig_to_generate(context):
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
        return cls.get_metarig_to_generate(context)

    def execute(self, context):
        metarig = self.get_metarig_to_generate(context)

        # Save state so it can be restored for convenience.
        state_mode = 'OBJECT'
        active_pb = get_pbone_of_active(context)
        state_active_bone = active_pb.name if active_pb else ""
        state_selected_bones = (
            [bone.name for bone in context.selected_pose_bones]
            if context.selected_pose_bones
            else []
        )
        state_hide_bones = {bone.name: bone.hide for bone in metarig.data.bones}
        # TODO 4.0: Should Bone Collection Visibilities be preserved? I think so, but probably based on what's on the previously generated rig, not the metarig.

        # Ensure required visibility and active states.
        # TODO: Replace EnsureVisible with context overriding.
        meta_visible = EnsureVisible(metarig)
        target_rig = metarig.cloudrig.generator.target_rig
        rig_visible = None
        if target_rig:
            rig_visible = EnsureVisible(target_rig)
        context.view_layer.objects.active = metarig

        # Try to generate a rig based on the metarig.
        rig = self.generate_rig(context, metarig)

        # Restore states.
        meta_visible.restore()
        if rig_visible:
            rig_visible.restore()

        if not rig:
            # This means an error has occurred. It was already handled in generate_rig().
            return {'FINISHED'}

        if self.focus_generated:
            self.restore_state(
                context,
                metarig,
                state_mode,
                state_active_bone,
                state_selected_bones,
                state_hide_bones,
            )

        return {'FINISHED'}

    def generate_rig(self, context, metarig):
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
            generator.target_rig.name = "FAILED-" + generator.target_rig.name
            generator.target_rig.name = generator.target_rig.name.replace("NEW-", "")
            metarig['failed_rig'] = generator.target_rig

            if type(exception) == CloudGeneratorError:
                # A MetaRig error means the user didn't follow instructions correctly.
                # This is the only kind of Exception that is not a bug in CloudRig.
                self.report({'ERROR'}, exception.message)
            else:
                if generator.custom_script_failure:
                    # The error occurred in the user's script.
                    # execute_custom_script() has already created the log entry for us,
                    # so we just want to keep raising the exception.
                    raise exception

                # Any other exception type is a bug.
                # Let's invite the user to report the error they've encountered.
                generator.logger.log_fatal_error(
                    "Execution Failed!",
                    description="Execution failed unexpectedly. This should never happen!",
                    icon='URL',
                    note=str(exception),
                    operator='wm.cloudrig_report_bug',
                )

                self.report(
                    {'ERROR'},
                    f"A bug has occurred. You can report it through the Generation Log interface.\n{traceback.format_exc()}",
                )

        return generator_properties.target_rig

    def restore_state(
        self,
        context,
        metarig,
        mode,
        active_bone_name="",
        selected_bone_names="",
        hide_bones={},
    ):
        """Restore state for convenience."""
        metarig.hide_set(True)
        rig = metarig.cloudrig.generator.target_rig
        rig.hide_set(False)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='OBJECT')
        rig.select_set(True)

        if mode in ['OBJECT', 'EDIT', 'POSE']:
            bpy.ops.object.mode_set(mode=mode)

        rig = context.active_object
        if active_bone_name in rig.pose.bones:
            rig.data.bones.active = rig.data.bones[active_bone_name]

        for bone_name in selected_bone_names:
            if bone_name in rig.data.bones:
                rig.data.bones[bone_name].select = True

        for bone_name in hide_bones.keys():
            bone = rig.data.bones.get(bone_name)
            if not bone:
                continue
            bone.hide = hide_bones[bone_name]


registry = [
    GeneratorProperties,
    CLOUDRIG_OT_generate,
]


def register():
    # TODO: These would be better organized into a single hotkeys.py file.
    register_hotkey(
        CLOUDRIG_OT_generate.bl_idname,
        hotkey_kwargs={'type': "R", 'value': "PRESS", 'ctrl': True, 'alt': True},
        key_cat="3D View",
        space_type='VIEW_3D',
    )
