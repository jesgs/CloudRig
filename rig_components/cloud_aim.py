# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup, PoseBone
from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo

from bpy.props import BoolProperty, FloatProperty, StringProperty
from mathutils import Vector

from ..utils.maths import bounding_box_center, bounding_box
from .cloud_base import Component_Base


class Component_Aim(Component_Base):
    """Create Aim Target Control for a single bone."""

    ui_name = "Aim"

    relink_default_prefix = "CTR"

    parent_switch_behaviour = "The active parent will own the Aim Target or the Group Master Target if there are multiple eye components with a matching string as their Eye Group paramter."
    parent_switch_overwrites_root_parent = False

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        aim_org = self.bones_org[0]
        aim_bone = self.bone_sets['Mechanism Bones'].new(
            name=self.naming.add_prefix(self.bones_org[0].name, 'AIM'),
            source=aim_org,
            parent=aim_org,
        )

        if self.params.aim.root:
            self.root_bone = self.make_root_bone(aim_org)

        self.group_master = None
        if self.params.aim.group != "":
            self.group_master = self.ensure_group_master()

        self.ctr_bone = self.make_aim_control(aim_org, aim_bone)
        self.target_bone = self.make_target_control(aim_bone, self.group_master)

        aim_bone.add_constraint('DAMPED_TRACK', subtarget=self.target_bone.name)

        if self.params.aim.deform:
            def_bone = self.make_def_bone(self.ctr_bone, self.bones_def)
            def_bone.parent = aim_org
            def_bone.add_constraint('COPY_TRANSFORMS', subtarget=self.ctr_bone.name)

        if self.params.aim.create_sub_control:
            self.create_eye_highlight(self.ctr_bone)

    def find_target_pos(self, bone: BoneInfo) -> Vector:
        """Find location of where the target bone should be for an aim bone."""
        if self.params.aim.flatten:
            direction = bone.vector.normalized()
            # Ignore X axis
            direction[0] = 0.0
            return bone.head + direction * self.params.aim.target_distance * self.scale
        else:
            return (
                bone.tail
                + bone.vector.normalized()
                * self.params.aim.target_distance
                * self.scale
            )

    def make_target_control(self, bone: BoneInfo, parent: BoneInfo = None) -> BoneInfo:
        """Set up target control for a bone."""
        if not parent:
            parent = bone.parent

        head = self.find_target_pos(bone)
        tail = head + bone.vector

        target_bone = self.bone_sets['Aim Target Control'].new(
            name=self.naming.add_prefix(self.bones_org[0].name, 'TGT'),
            source=self.bones_org[0],
            head=head,
            tail=tail,
            custom_shape_name="Circle",
            parent=parent,
        )
        target_bone.custom_shape_scale *= self.params.aim.target_size
        dsp_bone = self.create_dsp_bone(target_bone)
        dsp_bone.add_constraint(
            'DAMPED_TRACK', subtarget=bone.name, track_axis='TRACK_NEGATIVE_Y'
        )

        return target_bone

    def make_aim_control(self, org_bone, aim_bone) -> BoneInfo:
        """Create direct control, with a display bone at the tip of it."""
        ctr_bone = self.bone_sets['Aim Target Control'].new(
            name=self.naming.make_name(
                ["CTR"], *self.naming.slice_name(org_bone.name)[1:]
            ),
            source=org_bone,
            parent=org_bone.parent if self.params.aim.root else org_bone,
            custom_shape_name="Circle",
        )

        ctr_bone.add_constraint('COPY_ROTATION', subtarget=aim_bone.name, mix_mode='AFTER')

        # Lock all location and Y scale
        self.lock_transforms(ctr_bone, loc=True, rot=False, scale=[False, True, False])

        # Scale hack! Don't actually allow scaling the control bone,
        # but send the scaling input into the display bone's scale, so it appears like it is scaling.
        # This is done because actually scaling the bone would result in scaling the eyeball which is not useful
        # but this way we can hook up the scale to iris scaling shape keys.
        ctr_bone.add_constraint(
            'LIMIT_SCALE',
            use_min_x=True,
            use_min_y=True,
            use_min_z=True,
            use_max_x=True,
            use_max_y=True,
            use_max_z=True,
            min_x=1,
            min_y=1,
            min_z=1,
            max_x=1,
            max_y=1,
            max_z=1,
            use_transform_limit=False,
            space='LOCAL',
        )
        dsp_bone = self.create_dsp_bone(ctr_bone)
        dsp_bone.put(ctr_bone.tail)
        dsp_bone.drivers.append(
            {'prop': 'scale', 'index': 0, 'variables': [(ctr_bone.name, '.scale[0]')]}
        )
        dsp_bone.drivers.append(
            {'prop': '.scale', 'index': 2, 'variables': [(ctr_bone.name, '.scale[2]')]}
        )
        return ctr_bone

    def make_root_bone(self, org_bone) -> BoneInfo:
        root_bone = self.bone_sets['Aim Root Control'].new(
            name=self.naming.add_prefix(org_bone.name, 'ROOT'),
            source=org_bone,
            parent=org_bone.parent,
            custom_shape_name='Square',
            custom_shape_scale=2,
            custom_shape_along_length=1,
        )

        org_bone.parent = root_bone

        return root_bone

    def create_eye_highlight(self, ctr_bone):
        name_slices = self.naming.slice_name(ctr_bone)
        name_slices[1] += "_Highlight"
        highlight_ctr = self.bone_sets['Aim Target Control'].new(
            name=self.naming.make_name(*name_slices),
            source=ctr_bone,
            parent=ctr_bone,
            custom_shape_name="Circle",
            custom_shape_scale=ctr_bone.custom_shape_scale / 3,
            custom_shape_along_length=1.05,
        )

        if ctr_bone.parent:
            prop_name = "follow_eye"
            self.add_bone_property_with_ui(
                prop_bone=highlight_ctr,
                prop_id=prop_name,

                panel_name="Face",
                label_name="Eye Highlights Follow",
                row_name="Eye Highlights",
                slider_name=self.side_prefix + " Eye",

                custom_prop_settings={
                    'default': 1.0,
                    'description': f'Makes "{highlight_ctr.name}" follow "{ctr_bone.name}"',
                },
                operator="pose.cloudrig_snap_bake",
                op_icon="FILE_REFRESH",
                op_kwargs={
                    "bone_names": [highlight_ctr.name],
                },
            )

            self.create_driven_armature_constraint(highlight_ctr, target_bones=[ctr_bone, ctr_bone.parent], prop_bone=highlight_ctr, prop_name=prop_name)

        self.lock_transforms(highlight_ctr, loc=False, rot=False, scale=[False, True, False])

        if self.params.aim.deform:
            self.make_def_bone(highlight_ctr, self.bones_def)

    def apply_parent_switching(
        self,
        parent_slots,
        *,
        child_bone=None,
        prop_bone=None,
        prop_name="",
        panel_name="Face",
        row_name="",
        label_name="",
        entry_name=""
    ):
        """Overrides cloud_base to apply the parent switching to the aim target
        or group master if it exists."""
        target_bone = self.group_master
        if not target_bone:
            target_bone = self.target_bone
        else:
            # Ensure parent switching for the group master
            if (
                self.group_master.parent
                and self.group_master.parent.name == "P-" + self.group_master.name
            ):
                # If the parent switching set-up already exists, don't create it again.
                return

        super().apply_parent_switching(
            parent_slots,
            child_bone=child_bone or target_bone,
            prop_bone=prop_bone or self.properties_bone,
            prop_name=prop_name,
            panel_name=panel_name,
            label_name=label_name or "Aim Target Parent",
            row_name=row_name,
            entry_name=entry_name or self.params.aim.group + " Parent",
        )

    def find_aim_bones_in_group(self, group_name) -> list[PoseBone]:
        """Return a list of all cloud_aim components with a matching Aim Group."""
        aim_bones = []
        for component in self.generator.all_components:
            if (
                isinstance(component, Component_Aim)
                and component.params.aim.group == group_name
            ):
                aim_bone = self.metarig.pose.bones[component.base_bone_name]
                aim_bones.append(aim_bone)
        return aim_bones

    def ensure_group_master(self) -> BoneInfo | None:
        """This function will be called by each aim rig, but we want to make sure
        it only runs once per aim group.
        """

        # Check if a bone with the right name already exists and if it does, just return it.
        group_name = self.params.aim.group
        group_master_name = self.naming.add_prefix(group_name, "TGT")
        existing = self.generator.find_bone_info(group_master_name)
        if existing:
            return existing

        aim_bones = self.find_aim_bones_in_group(group_name)

        # Find a parent to fall back to, although ideally the rigger specifies
        # parents using params.parenting.parent_switching.
        first_parent = ""
        for aim_bone in aim_bones:
            if aim_bone.parent and first_parent == "":
                first_parent = aim_bone.parent.name
                break

        if len(aim_bones) < 2:
            return None

        # Find center of all aim bones
        aims_center = bounding_box_center([b.head for b in aim_bones])

        # Find center of all targets
        target_positions = [self.find_target_pos(b) for b in aim_bones]
        target_center = bounding_box_center(target_positions)
        z_axis = Vector((0, 0, 0))
        for b in aim_bones:
            z_axis += b.z_axis
        z_axis /= len(aim_bones)

        lowest, highest = bounding_box(target_positions)
        targets_size = (highest - lowest).length

        # Create a helper bone in the center.
        group_vec = target_center - aims_center
        center_bone = self.bone_sets['Mechanism Bones'].new(
            name="CEN-" + group_name,
            source=self.bones_org[0],
            head=aims_center,
            tail=aims_center + group_vec.normalized() * self.scale,
            bbone_width=0.1,
            roll_type='VECTOR',
            roll_vector=z_axis,
            roll=0,
            parent=self.generator.find_bone_info(first_parent),
        )
        center_bone.add_constraint('ARMATURE', targets=[{'subtarget': bone.name} for bone in aim_bones])

        max_dist = 0
        for i, target_pos in enumerate(target_positions[1:]):
            prev = target_positions[i]
            dist = (target_pos - prev).length
            if dist > max_dist:
                max_dist = dist

        # Create the master bone.
        group_master = self.bone_sets['Aim Group Target Control'].new(
            name=group_master_name,
            source=self.bones_org[0],
            head=target_center,
            tail=target_center + group_vec.normalized() * targets_size * 1.5,
            roll_type='VECTOR',
            roll_vector=z_axis,
            roll=0,
            custom_shape_name='Circle',
            use_custom_shape_bone_size=True,
            custom_shape_scale=1,
        )
        group_master.add_constraint(
            'DAMPED_TRACK', subtarget=center_bone.name, track_axis='TRACK_NEGATIVE_Y'
        )

        return group_master

    ##############################
    # Parameters

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'deform_bones':
            return params.aim.deform
        if set_name == 'aim_root_control':
            return params.aim.root

        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def define_bone_sets(cls):
        super().define_bone_sets()
        cls.define_bone_set(
            "Aim Group Target Control",
            collections=['Face Main'],
            color_palette='THEME02',
            wire_width=3,
        )
        cls.define_bone_set(
            "Aim Target Control", collections=['Face Main'], color_palette='THEME12', wire_width=2
        )
        cls.define_bone_set(
            "Aim Root Control", collections=['Face Secondary'], color_palette='THEME12'
        )
        cls.define_bone_set(
            "Aim Deform", collections=['Deform Bones'], is_advanced=True
        )

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        super().draw_appearance_params(layout, context, params)
        cls.draw_prop(context, layout, params.aim, 'target_size')

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        cls.draw_prop(context, layout, params.aim, 'group')
        cls.draw_prop(context, layout, params.aim, 'target_distance')
        cls.draw_prop(context, layout, params.aim, 'flatten')
        cls.draw_prop(context, layout, params.aim, 'deform')
        cls.draw_prop(context, layout, params.aim, 'root')
        cls.draw_prop(context, layout, params.aim, 'create_sub_control')


class Params(PropertyGroup):
    group: StringProperty(
        name="Aim Group",
        default="Eyes",
        description="Aim components belonging to the same Aim Group will have a shared master control generated for them",
    )

    target_distance: FloatProperty(
        name="Target Distance",
        default=5.0,
        description="Distance of the target from the aim bone. This value is not in blender units, but is a value relative to the scale of the rig",
        min=0,
    )
    target_size: FloatProperty(
        name="Target Size",
        default=1.0,
        description="Size multiplier for the target control. This is for display purposes only, as sometimes the target can be too small, and there's no good automatic way to determine the desired size",
        min=0.1,
        soft_max=10.0,
    )
    flatten: BoolProperty(
        name="Flatten X",
        description="Discard the X component of the eye vector when placing the target control. Useful for eyes that have significant default rotation. This can result in the eye becoming cross-eyed in the default pose, but it prevents the eye targets from crossing each other or being too far from each other",
        default=False,
    )
    deform: BoolProperty(
        name="Create Deform",
        default=False,
        description="Create a deform bone for this rig",
    )
    root: BoolProperty(
        name="Create Root", default=False, description="Create a root bone for this rig"
    )
    create_sub_control: BoolProperty(
        name="Create Sub-Control",
        description="Create a secondary control and deform bone attached to the aim control. Useful for eye highlights",
        default=False,
    )


RIG_COMPONENT_CLASS = Component_Aim
