import bpy, sys, os, traceback, time

from bpy.props import BoolProperty, PointerProperty, CollectionProperty, IntProperty
from bpy.types import Object, PropertyGroup
from typing import List, Dict, Tuple

from bone_selection_sets import from_json, to_json
from mathutils import Matrix, Vector
from datetime import datetime

from rigify.utils.naming import change_name_side, Side

from rigify.utils.action_layers import ActionLayerBuilder
from rigify.utils.mechanism import refresh_all_drivers
from rigify.utils.collections import ensure_collection
from rigify.utils.bones import new_bone
from rigify.base_rig import BaseRig

from ..rig_component_features.widgets import widgets as cloud_widgets
from ..rig_component_features.mechanism import get_object_scalar
from ..rig_component_features.ui import redraw_viewport
from ..rig_component_features.bone_set import BoneSet
from ..rig_component_features import mechanism

from .troubleshooting import CloudRigLogEntry, CloudLogManager
from .naming import CloudNameManager

# from ..operators.assign_bone_layers import init_cloudrig_layers
from ..utils.misc import check_addon, load_script
from ..versioning import cloud_metarig_version
from .cloudrig import ensure_custom_panels

class GeneratorProperties(PropertyGroup):
    # TODO: I see no reason why this class couldn't be merged with the one that 
    # holds the generate() function, making a unified `Generator` class that 
    # lives in RNA, giving us the ability to just to `my_metarig.cloudrig.generator.generate()`,
    # which would be pretty neat I think.
    target_rig: PointerProperty(
        name="Target Rig", 
        description="Rig to re-genreate based on this metarig when the Generate button is used", 
        type=bpy.types.Object
    )
    create_root: BoolProperty(
        name         = "Create Root"
        ,description = "Create a default root control"
        ,default     = True
    )
    double_root: BoolProperty(
        name         = "Double Root"
        ,description = "Create two default root controls"
        ,default     = False
    )

    custom_script: PointerProperty(
        name         = "Post-Generation Script"
        ,type         = bpy.types.Text
        ,description = "Execute a python script after the rig is generated"
    )
    widget_collection: PointerProperty(
        name         = "Widget Collection"
        ,type         = bpy.types.Collection
        ,description = "Collection dedicated to storing nothing but the widgets used by this rig. Additional objects will result in warnings, and missing widgets will be re-linked during generation"
    )

    generate_test_action: BoolProperty(
        name         = "Generate Test Action"
        ,description = "Whether to create/update the deform test action or not. Enabling this enables the Animation parameter category on FK chain components"
        ,default     = False
    )
    test_action: PointerProperty(
        name         = "Test Action"
        ,type         = bpy.types.Action
        ,description = "Action which will be generated with the keyframes neccessary to test the rig's deformations"
    )

    show_layers_preview_hidden: BoolProperty(
        name         = "Show Hidden Layers"
        ,description = "Show layers whose names start with $ and will be hidden on the rig UI"
        ,default     = True
        ,override     = {'LIBRARY_OVERRIDABLE'}
    )

    auto_setup_gizmos: BoolProperty(
        name         = "Auto Setup Gizmos (EXPERIMENTAL)"
        ,description = "Experiment with the initial BoneGizmo addon integration"
        ,default     = False
    )

    logs: CollectionProperty(type=CloudRigLogEntry)
    active_log_index: IntProperty(min=0)

    @property
    def active_log(self):
        return self.logs[self.active_log_index] if len(self.logs) > 0 else None


class CloudRig_Generator_Base:
    def instantiate_rig_components(self):
        """Create rig instances and connect them into a tree."""

        # assert(context.active_object == self.obj)
        # assert(self.obj.mode == 'OBJECT')

        # Find bones that have no parents.
        parentless = [pb for pb in self.metarig.pose.bones if not pb.bone.parent]
        for pb in parentless:
            self.instantiate_rig_components_recursive(pb)

    def instantiate_rig_components_recursive(
                self, 
                pb: bpy.types.PoseBone, 
                parent_component: "RigComponent" = None
            ):
        if pb.cloudrig_component.component_type:
            # Maintain rig component's awareness of what bone it is on.
            pb.cloudrig_component.owner_bone = pb.name
            # Instantiate rig component class.
            comp_instance = pb.cloudrig_component.instantiate(generator=self)
            print("Instantiated ", pb.name)

            # Store parent/child relations
            if parent_component:
                comp_instance.parent_component = parent_component
                parent_component.child_components.append(comp_instance)

            # Set parent for the next recursion.
            parent_component = comp_instance

        for child_pb in pb.children:
            self.instantiate_rig_components_recursive(child_pb, parent_component)

class CloudRig_Generator(CloudRig_Generator_Base):
    """
    This class is instantiated by the Generate operator. 
    It instantiates the rig components and calls their rig generation functions.
    """
    def __init__(self, context, metarig):
        self.metarig = metarig
        self.target_rig = None
        self.params = metarig.data.cloudrig.generator

        self.custom_script_failure = False

        metarig.data.pose_position = 'REST'
        metarig['loc_bkp'] = metarig.matrix_world.to_translation()
        metarig['rot_bkp'] = metarig.matrix_world.to_euler()
        metarig['scale_bkp'] = metarig.matrix_world.to_scale()
        metarig.matrix_world = Matrix.Identity(4)

        return
        context.view_layer.update() # Needed to make sure we get the correct scale # TODO: Is this really necessary?
        self.scale = get_object_scalar(metarig)

        self.naming = CloudNameManager()

        # List that stores a reference to all BoneInfo instances of all components.
        # IMPORTANT: This should not be a BoneSet, just a regular list. Otherwise the LinkedList behaviour gets all messed up!
        # Each BoneInfo should only exist in a single BoneSet!
        # TODO: Would make more sense to make this a @property that loops through the BoneSets, but that may be less performant.
        self.bone_infos = []
        # List that stores a reference to all BoneSets of all components.
        self.bone_sets: List[BoneSet] = []
        # Default kwargs that are passed in to every created BoneInfo.
        self.defaults = {
            'rotation_mode' : 'XYZ'
        }

        # Wipe the generation log.
        self.logger = CloudLogManager(metarig)
        self.logger.clear()

        # Set flag to handle Bone Gizmos.
        self.use_gizmos = check_addon(context, 'bone_gizmos') and self.params.auto_setup_gizmos
        # Set flag to handle Selection Sets.
        self.do_sel_sets = check_addon(context, 'bone_selection_sets')

    def generate(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')

        metarig = self.metarig
        self.target_rig = self.create_rig_object(context, metarig)
        print("Begin Generating CloudRig from metarig: " + metarig.name)

        # self.collection is only used for Rigify compatibility.
        self.collection = context.scene.collection
        if len(self.metarig.users_collection) > 0:
            self.collection = self.metarig.users_collection[0]

        print("Instantiate rig components...!")
        self.instantiate_rig_components()

        return

        # If the previous generation failed, delete the failed rig.
        if 'failed_rig' in metarig and metarig['failed_rig']:
            bpy.data.objects.remove(metarig['failed_rig'])
            del metarig['failed_rig']

        #------------------------------------------

        # Rename metarig data
        metarig.data.name = "Data_" + self.metarig.name
        # Update metarig version
        self.params.version = cloud_metarig_version

        # Symmetry option seems to mess with generation...
        self.bkp_x_mirror = metarig.data.use_mirror_x
        metarig.data.use_mirror_x = False

        # Symmetry option seems to mess with generation...
        self.bkp_x_mirror = metarig.data.use_mirror_x
        metarig.data.use_mirror_x = False

        # Ensure rigify layers are initialized.
        # if len(metarig.data.rigify_layers) < 32:
        #     init_cloudrig_layers(metarig.data)

        #------------------------------------------

        # Create/find the rig object and set it up
        old_rig = self.params.target_rig
        self.obj = obj = self.create_rig_object(context, metarig)

        self.logger.rig = obj
        self.logger.metarig = metarig

        self.defaults['rig'] = obj

        # Create Widget Collection
        self.ensure_widget_collection()

        redraw_viewport()

        self.driver_map = self.map_drivers()

        self.script = None

        self.action_layers = ActionLayerBuilder(self)

        #------------------------------------------
        self.instantiate_rig_tree()
        self.cloudrig_reorder_rig_components(self.rig_list)

        #------------------------------------------
        self.invoke_initialize()
        t.tick("Initialize components: ")

        #------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')
        self.root_bone = None
        self.create_root_bones()

        #------------------------------------------
        self.invoke_load_bone_infos()
        t.tick("Load BoneInfos: ")

        #------------------------------------------
        self.invoke_prepare_bones()
        t.tick("Prepare bones: ")

        #------------------------------------------
        self.invoke_generate_bones()
        t.tick("Generate bones: ")

        #------------------------------------------
        self.invoke_parent_bones()
        t.tick("Write Edit Data: ")
        redraw_viewport()

        #------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        self.ensure_bone_groups()
        self.invoke_configure_bones()
        t.tick("Write Pose Data: ")
        redraw_viewport()

        #------------------------------------------
        self.invoke_preapply_bones()
        t.tick("Preapply bones: ")

        #------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')

        self.invoke_apply_bones()
        t.tick("Apply bones: ")
        redraw_viewport()

        #------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        self.invoke_rig_bones()
        redraw_viewport()

        self.invoke_apply_bones()
        t.tick("Apply bones: ")
        redraw_viewport()

        #------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        self.invoke_rig_bones()
        redraw_viewport()

        #------------------------------------------
        self._Generator__restore_driver_vars()

        #------------------------------------------
        self.ensure_cloudrig_ui(obj)

        self.invoke_finalize()

        t.tick("Finalize: ")
        redraw_viewport()

        #------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        self._Generator__assign_widgets()

        self.create_test_animation()

        # Only leave Force Widget Update enabled until the next generation.
        self.params.rigify_force_widget_update = False

        self.execute_custom_script()

        if old_rig:
            self.replace_old_with_new_rig(old_rig, obj)
        else:
            obj.name = obj.name.replace("NEW-", "")

        if self.params.auto_setup_gizmos and self.use_gizmos:
            self.auto_initialize_gizmos()

        self.params.target_rig = obj

        ensure_custom_panels(None, None)

        t.tick("The rest: ")
        self.restore_rig_states()
        self.log_minor_issues()
        t.tick("Cleanup & Troubleshoot: ")
        t.total()

    def cloudrig_reorder_rig_components(self, rig_list):
        """Some rig types need special treatment in regards to where they are in
        the rig generation order."""
        from ..rig_components.cloud_tweak import Component_TweakBone
        from ..rig_components.cloud_chain_anchor import CloudChainAnchorRig
        from ..rig_components.cloud_face_chain import CloudFaceChainRig
        from ..rig_components.cloud_jaw import CloudJawRig

        first_face_idx = -1
        for i, rig in enumerate(rig_list[:]):
            if isinstance(rig, Component_TweakBone) or isinstance(rig, CloudChainAnchorRig):
                # cloud_tweak components should be generated last.
                rig_list.remove(rig)
                rig_list.append(rig)
            if isinstance(rig, CloudFaceChainRig) and first_face_idx == -1:
                first_face_idx = i

        for i, rig in enumerate(rig_list[:]):
            if isinstance(rig, CloudJawRig):
                for param_name in {'CR_jaw_lower_face_bone', 'CR_jaw_squash_bone', 'CR_jaw_chin_bone', 'CR_jaw_mouth_bone', 'CR_jaw_teeth_follow', 'CR_jaw_teeth_upper_bone', 'CR_jaw_teeth_lower_bone'}:
                    bone_name = getattr(rig.params, param_name)
                    dependency_rig = self.get_rig_by_name(bone_name)
                    if dependency_rig:
                        rig_list.remove(dependency_rig)
                        rig_list.insert(i-1, dependency_rig)

        for rig in rig_list[:]:
            if isinstance(rig, CloudChainAnchorRig):
                # cloud_chain_anchor pushed before the first cloud_face_chain.
                rig_list.remove(rig)
                rig_list.insert(first_face_idx, rig)

    def find_bone_info(self, name):
        for rig in self.rig_list:
            if hasattr(rig, "bone_sets"):
                for bs in list(rig.bone_sets.values()):
                    exists = bs.find(name)
                    if exists:
                        return exists

        # If the name wasn't found in any rig component's bone sets,
        # maybe it's in the root set that's owned by the Generator.
        return self.root_set.find(name)


    def create_rig_object(self, context, metarig) -> Object:
        """Create a new empty Armature object that will get populated throughout
        the generation process and then replace the previously generated rig."""
        metaname = metarig.name
        final_name = metaname.replace("META", "RIG")
        if 'META' not in metaname:
            final_name = "RIG-" + metaname

        rig_name = "NEW-" + final_name

        armature = bpy.data.armatures.new(name=rig_name)
        target_rig = bpy.data.objects.new(rig_name, armature)
        context.scene.collection.objects.link(target_rig)
        # Mark rig for cloudrig.py compatibility checks
        target_rig.data['allow_cloudrig_ui'] = True

        # Save generation timestamp to a custom property
        today = datetime.today()
        now = datetime.now()
        target_rig.data['generation_date'] = f"{today.year}-{today.month}-{today.day}"
        target_rig.data['generation_time'] = f"{str(now.hour).zfill(2)}:{str(now.minute).zfill(2)}:{str(now.second).zfill(2)}"

        # Make sure Hidden Layers checkbox is saved in the generated rig, so it
        # remains even if the Rigify addon is disabled.
        target_rig.data.cloudrig.generator.show_layers_preview_hidden = False

        # By default, use B-Bone display type since it's the most useful
        target_rig.data.display_type = 'BBONE'

        # Copy viewport display settings from the metarig.
        target_rig.data.show_names = metarig.data.show_names
        target_rig.show_in_front = metarig.show_in_front
        target_rig.data.show_axes = metarig.data.show_axes

        target_rig.data.pose_position = 'REST'

        return target_rig

    def create_root_bones(self):
        # Bone Set used for the Root, default Properties, and Action Properties bones.
        self.root_set = BoneSet(self
            ,ui_name = 'Root'
            ,bone_group = "Generator"
            ,layers = [i==0 for i in range(32)]
            ,preset = 2
            ,defaults = self.defaults
        )
        self.bone_sets.append(self.root_set)

        self.root_bone = None
        if self.params.create_root:
            self.root_bone = self.root_set.new(
                name                = "root"
                ,head                = Vector((0, 0, 0))
                ,tail                = Vector((0, self.scale*5, 0))
                ,bbone_width        = 1/10
                ,custom_shape        = self.ensure_widget("Root")
                ,custom_shape_scale = 1.5
                ,use_custom_shape_bone_size = True
            )

        if self.params.double_root:
            self.root_parent_set = BoneSet(self
                ,ui_name = 'Root'
                ,bone_group = "Root Parent"
                ,layers = [i==0 for i in range(32)]
                ,preset = 8
                ,defaults = self.defaults
            )
            self.bone_sets.append(self.root_parent_set)
            self.root_parent = mechanism.create_parent_bone(self.root_bone, self.root_parent_set)

    def ensure_bone_groups(self):
        # Wipe any existing bone groups from the target rig.
        if self.obj.pose:
            for bone_group in self.obj.pose.bone_groups:
                self.obj.pose.bone_groups.remove(bone_group)

        for bone_set in self.bone_sets:
            meta_bg = bone_set.ensure_bone_group(self.metarig, overwrite=False)
            if meta_bg:
                bone_set.normal = meta_bg.colors.normal[:]
                bone_set.select = meta_bg.colors.select[:]
                bone_set.active = meta_bg.colors.active[:]
            if self.params.rigify_colors_lock:
                bone_set.select = self.params.rigify_selection_colors.select
                bone_set.active = self.params.rigify_selection_colors.active

            bone_set.ensure_bone_group(self.obj, overwrite=True)

    def ensure_widget(self, widget_name):
        wgt = cloud_widgets.ensure_widget(
            widget_name
            ,overwrite = self.params.rigify_force_widget_update
            ,collection = self.widget_collection
        )
        if not wgt:
            self.logger.log_bug("Failed to create widget"
                ,description = f"Failed to load widget named '{widget_name}'."
            )
        return wgt

    def add_to_widget_collection(self, widget_ob):
        context = self.context
        if not self.widget_collection:
            return
        if widget_ob.name not in self.widget_collection.objects:
            self.widget_collection.objects.link(widget_ob)
        if widget_ob.name in context.scene.collection.objects:
            context.scene.collection.objects.unlink(widget_ob)

    ### Deform test animation generation
    def ensure_test_action(self):
        # Ensure test action exists
        test_action = self.params.test_action
        if not test_action:
            test_action = bpy.data.actions.new("RIG.DeformTest."+self.obj.name)
            self.metarig.data.cloudrig.generator.test_action = test_action

        # Nuke all curves
        for fc in test_action.fcurves[:]:
            test_action.fcurves.remove(fc)

        if not self.obj.animation_data:
            self.obj.animation_data_create()

        if not self.obj.animation_data.action:
            self.obj.animation_data.action = test_action

        return test_action

    def get_symmetry_rig(self, rig: BaseRig) -> BaseRig:
        """Find another rig in the generator with the opposite name for rig.base_bone."""
        flipped_name = self.naming.flipped_name(rig.base_bone)
        if flipped_name == rig.base_bone: return

        for other_rig in self.rig_list:
            if other_rig.base_bone == flipped_name:
                return other_rig

    def get_rig_children(self, rig: BaseRig):
        children = []
        for r in self.rig_list:
            if r.rigify_parent == rig:
                children.append(r)
        return children

    def get_rig_by_name(self, rig_name: str) -> BaseRig:
        for r in self.rig_list:
            if r.base_bone.replace("ORG-", "") == rig_name:
                return r

    def create_test_animation(self):
        """Generate deformation test animation.

        In order to generate the test animation, we need to call add_test_animation() on components
        in a different order than regular rig execution, and we also want to account for symmetry.

        Usual rig execution is in order of hierarchical levels: highest level gets executed first,
        then all second level components, then all third level components.
        For the animation, we need a hierarchy to be executed all the way down before moving on to
        the next one.

        Symmetrical components should animate at the same time, and with the Y and Z axis rotations flipped.
        """

        if not self.params.generate_test_action:
            return
        for rig in self.rig_list:
            if hasattr(rig.params, 'CR_fk_chain_test_animation_generate') and rig.params.CR_fk_chain_test_animation_generate:
                found = True
                break
        if not found:
            return

        action = self.ensure_test_action()

        rigs_anim_order = []

        def add_rig_hierarchy_to_animation_order(rig):
            if hasattr(type(rig), 'has_test_animation') and type(rig).has_test_animation:
                rigs_anim_order.append(rig)
            for child_rig in self.get_rig_children(rig):
                add_rig_hierarchy_to_animation_order(child_rig)

        for root_rig in self.root_rigs:
            add_rig_hierarchy_to_animation_order(root_rig)

        start_frame = 1
        for rig in rigs_anim_order:
            symm_rig = self.get_symmetry_rig(rig)
            symm_new_start_frame = 1
            new_start_frame = rig.add_test_animation(action, start_frame)
            if symm_rig:
                symm_new_start_frame = symm_rig.add_test_animation(action, start_frame, flip_xyz=[False, True, True])
                rigs_anim_order.remove(symm_rig)
            start_frame = max(new_start_frame, symm_new_start_frame)

    def invoke_generate_bones(self):
        """Create real bones from all BoneInfos.
        No bone data is written yet beside the name."""
        for bi in self.bone_infos:
            if bi.name in self.obj.data.edit_bones:
                # This happens for ORG bones that we load into BoneInfo objects,
                # since they already get created by __duplicate_rig()
                continue
            new_name = new_bone(self.obj, bi.name)
            if new_name != bi.name:
                self.logger.log(
                    "Bone Name Clash"
                    ,trouble_bone = bi.name
                    ,description = f'Bone name "{bi.name}" was already taken, fell back to "{new_name}" instead. This is a bug unless your bone names are around 60 characters long.'
                )
                bi.name = new_name
            self.bone_owners[new_name] = None

        super().invoke_generate_bones()

    def invoke_parent_bones(self):
        super().invoke_parent_bones()

        # Write edit bone data for BoneInfos.
        for bi in self.bone_infos:
            edit_bone = self.obj.data.edit_bones.get(bi.name)
            bi.write_edit_data(self, edit_bone, self.context)

        # Parent parent-less bones to the root bone, if there is one.
        if self.root_bone:
            self.parent_bones_to_root()

    def parent_bones_to_root(self):
        pass
        # TODO 4.0: Implement this (Can copy from Rigify, but operating on BoneInfo might be better, dunno.)

    def invoke_configure_bones(self):
        for bi in self.bone_infos:
            pose_bone = self.obj.pose.bones.get(bi.name)
            if not pose_bone:
                self.logger.log("Bone creation failed"
                    ,owner_bone   = bi.owner_rig.base_bone
                    ,trouble_bone = bi.name
                    ,description  = f'BoneInfo "{bi.name}" was not created for some reason.'
                )
                continue

            # Scale bone shape based on B-Bone scale
            bi.write_pose_data(pose_bone)
            if not pose_bone.use_custom_shape_bone_size and bi.use_custom_shape_bbone_scaling:
                pose_bone.custom_shape_scale_xyz *= bi.bbone_width * 10 * self.scale

        super().invoke_configure_bones()

    def invoke_apply_bones(self):
        super().invoke_apply_bones()

        # Rigify automatically parents bones that have no parent to the root bone.
        # We want to undo this when the bone has an Armature constraint.
        for eb in self.obj.data.edit_bones:
            pb = self.obj.pose.bones.get(eb.name)
            for c in pb.constraints:
                if c.type=='ARMATURE' and c.enabled:
                    eb.parent = None
                    break

    @staticmethod
    def map_vgroups_to_most_significant_object(
            group_names: List[str]
            ,objects: List[Object]
            ) -> Dict[str, Object]:
        """Create a dictionary, mapping each vertex group name to the object
        which has the vertex group with the most vertices in it.
        This is expected to be pretty damn slow.
        """
        objects = [o for o in objects if o.type == 'MESH' and o.visible_get()]

        vgroup_map = {}
        # For each object, go through each of its vertex groups.
        for ob in objects:
            group_lookup = {g.index: g.name for g in ob.vertex_groups}
            vgroup_datas = {name: [] for name in group_lookup.values() if name in group_names}
            for v in ob.data.vertices:
                for g in v.groups:
                    group_name = group_lookup[g.group]
                    if g.weight > 0.1 and group_name in group_names:
                        vgroup_datas[group_name].append(v.index)

            for vg_name, vg_verts in vgroup_datas.items():
                if (vg_name not in vgroup_map) or ( vgroup_map[vg_name][1] < len(vg_verts) ):
                    vgroup_map[vg_name] = (ob, len(vg_verts))

        return {vg_name : tup[0] for vg_name, tup in vgroup_map.items()}

    def auto_initialize_gizmos(self):
        """Enable and set up custom gizmos for those bones whose BoneInfo
        contains the neccessary data.
        This is not done on a per-bone basis due to performance.
        """
        # This function just gives terrible results.
        return
        rig = self.params.target_rig
        object_candidates = rig.children[:]

        vgroup_names = set([bi.gizmo_vgroup for bi in self.bone_infos if bi.gizmo_vgroup != ""])

        vgroup_map = self.map_vgroups_to_most_significant_object(vgroup_names, object_candidates)

        pbones = self.obj.pose.bones
        bone_infos = self.bone_infos
        for bi in bone_infos:
            vg_name = bi.gizmo_vgroup
            if vg_name not in vgroup_map:
                continue
            pb = pbones.get(bi.name)
            if pb.enable_bone_gizmo:
                continue
            assert pb

            gizmo_props = pb.bone_gizmo
            pb.enable_bone_gizmo = True
            gizmo_props.shape_object = vgroup_map[vg_name]
            gizmo_props.vertex_group_name = vg_name
            gizmo_props.operator = bi.gizmo_operator
            if pb.bone_group:
                gizmo_props.color = pb.bone_group.colors.normal[:]
                gizmo_props.color_highlight = pb.bone_group.colors.active[:]

    def map_drivers(self) -> Dict[str, Tuple[str, int]]:
        """Create a dictionary matching bone names to full data paths of drivers
        that belong to those bones. This is to speed up loading drivers into BoneInfos."""
        driver_map = {}
        if not self.obj.animation_data:
            return
        for fc in self.obj.animation_data.drivers:
            data_path = fc.data_path
            if "pose.bones" in data_path:
                bone_name = data_path.split('pose.bones["')[1].split('"]')[0]
                if bone_name not in driver_map:
                    driver_map[bone_name] = []
                driver_map[bone_name].append((data_path, fc.array_index))
        return driver_map

    def replace_old_with_new_rig(self, old_rig, new_rig):
        """Preserve useful user-inputted information from the previous rig,
        then delete it and remap users to the new rig."""

        # Save selection sets
        if self.do_sel_sets:
            self.context.view_layer.objects.active = old_rig
            for selset in old_rig.selection_sets:
                selset.is_selected = True
            selsets = to_json(self.context)

        # Save Custom Gizmo settings
        if self.use_gizmos:
            gizmo_properties_class = bpy.types.PropertyGroup.bl_rna_get_subclass_py('BoneGizmoProperties')
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

        # Swap all references pointing at the old rig to the new rig
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

        # Preserve Armature display settings
        new_rig.display_type = old_rig.display_type
        new_rig.show_in_front = old_rig.show_in_front
        new_rig.data.display_type = old_rig.data.display_type
        new_rig.data.show_axes = old_rig.data.show_axes

        # Delete the old rig
        bpy.data.objects.remove(old_rig)

        # Preserve object name of previous rig.
        new_rig.name = old_name
        new_rig.data.name = old_data_name

        # Select and make active the new rig
        new_rig.select_set(True)
        self.context.view_layer.objects.active = new_rig

        # Preserve selection sets of previous rig.
        if self.do_sel_sets:
            from_json(self.context, selsets)

    def execute_custom_script(self):
        """Execute a text datablock to be executed after rig generation."""
        script = self.params.custom_script
        if not script:
            return
        try:
            exec(script.as_string(), {})
        except Exception as e:
            traceback_str = "\n".join(str(traceback.format_exc()).split("\n")[3:])
            self.logger.log_error(
                "Post-Generation Script failed."
                ,description = f'Execution of post-generation script in text datablock "{script.name}" failed, see stack trace below.'
                ,note         = str(e)
                ,popup_text     = traceback_str
                ,pretty_stack = traceback_str
            )
            self.custom_script_failure = True

    def ensure_cloudrig_ui(self, rig):
        """Load and execute cloudrig.py rig UI script."""
        rig.data['cloudrig_ui'] = load_script(
            file_path = os.path.dirname(os.path.realpath(__file__))
            ,file_name = "cloudrig.py"
        )

    def ensure_widget_collection(self):
        """Overrides Rigify's generator's function to avoid annoying object renaming."""
        # Create/find widget collection
        self.widget_collection = self.metarig.data.rigify_widgets_collection
        if not self.widget_collection:
            self.widget_collection = self._Generator__find_legacy_collection()
        if not self.widget_collection:
            wgts_group_name = "WGTS_" + self.obj.name.replace("RIG-", "")
            self.widget_collection = ensure_collection(self.context, wgts_group_name, hidden=True)

        self.metarig.data.rigify_widgets_collection = self.widget_collection

        self.use_mirror_widgets = self.metarig.data.rigify_mirror_widgets

        # Build tables for existing widgets
        self.old_widget_table = {}
        self.new_widget_table = {}
        self.widget_mirror_mesh = {}

        # Find meshes for mirroring
        if self.use_mirror_widgets:
            for bone_name, widget in self.old_widget_table.items():
                mid_name = change_name_side(bone_name, Side.MIDDLE)
                if bone_name != mid_name:
                    self.widget_mirror_mesh[mid_name] = widget.data

    def invoke_load_bone_infos(self):
        """Bit of a hacked-in additional stage to load BoneInfos before
        prepare_bones. 
        
        This is needed only so that BoneInfo.children is correctly populated
        with sub-rig-components during prepare_bones().

        This makes sense to have from CloudRig's perspective, I just 
        didn't find a nice way to add an extra stage to the Generator class.
        """
        for rig in self.rig_list:
            if hasattr(rig, 'load_bone_infos'):
                rig.load_bone_infos()

    def restore_rig_states(self):
        """Restore transforms after generation has either failed or succeeded."""
        return
        bpy.ops.object.mode_set(mode='OBJECT')
        self.metarig.data.pose_position = 'POSE'
        if 'loc_bkp' in self.metarig:
            self.metarig.location = self.metarig['loc_bkp'].to_list()
            self.metarig.rotation_euler = self.metarig['rot_bkp'].to_list()
            self.metarig.scale = self.metarig['scale_bkp'].to_list()
            del self.metarig['loc_bkp']
            del self.metarig['rot_bkp']
            del self.metarig['scale_bkp']
        self.obj.data.pose_position = 'POSE'
        self.metarig.data.use_mirror_x = self.bkp_x_mirror

        # Refresh drivers
        refresh_all_drivers()
        refresh_constraints(self.obj)
        self.context.view_layer.update()

    def log_minor_issues(self):
        self.logger.report_widgets(self.widget_collection)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.metarig)
        self.logger.report_invalid_drivers_on_object_hierarchy(self.obj)
        # self.logger.report_actions()

registry = [
    GeneratorProperties,
]