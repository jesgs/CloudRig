# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.maths import bounding_box, bounding_box_center
from .cloud_base import Component_Base


class Component_Aim(Component_Base):
    """Create Aim Target Control for a single bone."""

    ui_name = "Aim"

    relink_default_prefix = "CTR"

    parent_switch_behaviour = "The active parent will own the Aim Target or the Group Master Target if there are multiple eye components with a matching string as their Eye Group paramter."
    parent_switch_overwrites_root_parent = False

    ##############################
    # Inherited functions.

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        aim_org = self.bones_org[0]
        aim_bone = self.bone_sets['Mechanism Bones'].new(
            name=self.naming.add_prefix(self.bones_org[0].name, 'AIM'),
            source=aim_org,
            parent=aim_org,
        )

        if self.params.aim.root:
            self.root_bone = self.__make_root_bone(aim_org)

        self.ctr_bone = self.__make_aim_control(aim_org, aim_bone)
        self.target_bone = self.__make_target_control(aim_bone)

        self.group_master = None
        if self.params.aim.group != "":
            self.group_master = self.__ensure_group_master()

        aim_bone.add_constraint('DAMPED_TRACK', subtarget=self.target_bone.name)

        if self.params.aim.deform:
            def_bone = self.make_def_bone(self.ctr_bone, self.bones_def)
            def_bone.parent = aim_org
            def_bone.add_constraint('COPY_TRANSFORMS', subtarget=self.ctr_bone.name)

        if self.params.aim.create_sub_control:
            self.__create_eye_highlight(self.ctr_bone)

    @no_overlay
    def base__apply_parent_switching(
        self,
        *,
        child_bone=None,
        prop_bone=None,
        prop_name="",
        panel_name="Face",
        row_name="",
        label_name="",
        entry_name=""
    ):
        """Apply the parent switching to the aim target or group master if it exists."""
        target_bone = self.group_master
        if not target_bone:
            target_bone = self.target_bone
        else:
            # Ensure parent switching for the group master
            if (
                self.group_master.parent
                and self.group_master.parent.name == self.naming.add_prefix(self.group_master.name, "P")
            ):
                # If the parent switching set-up already exists, don't create it again.
                return

        super().base__apply_parent_switching(
            child_bone=child_bone or target_bone,
            prop_bone=prop_bone or self.properties_bone,
            prop_name=prop_name,
            panel_name=panel_name,
            label_name=label_name or "Aim Target Parent",
            row_name=row_name,
            entry_name=entry_name or self.params.aim.group + " Parent",
        )

    ##############################
    # Aim Rig functions.

    def __find_target_pos(self, bone: BoneInfo) -> Vector:
        """Find location of where the target bone should be for an aim bone."""
        direction = bone.vector.normalized()

        not_flattened = (
            bone.tail
            + direction
            * self.params.aim.target_distance * self.scale
        )

        # Discard X axis.
        direction[0] = 0.0
        flattened = (
            bone.head
            + direction
            * self.params.aim.target_distance * self.scale
        )

        lerped = not_flattened.lerp(flattened, self.params.aim.flatten)

        return lerped

    def __make_target_control(self, aim_bone: BoneInfo) -> BoneInfo:
        """Set up target control for a bone."""
        head = self.__find_target_pos(aim_bone)
        tail = head + (head-aim_bone.head).normalized() * aim_bone.length

        target_bone = self.bone_sets['Aim Target Control'].new(
            name=aim_bone.name.replace("AIM", "TGT"),
            source=aim_bone,
            head=head,
            tail=tail,
            custom_shape_name=self.params.aim.shape_target.shape_name,
            custom_shape_scale_xyz=Vector([max(1, self.params.aim.target_distance) * self.scale*self.params.aim.target_size*0.1]*3),
            use_custom_shape_bone_size=False,
            parent=aim_bone.parent,
        )
        target_bone.roll_align_other(self.bones_org[0])
        dsp_bone = self.create_dsp_bone(target_bone)
        dsp_bone.add_constraint(
            'DAMPED_TRACK', subtarget=aim_bone.name, track_axis='TRACK_NEGATIVE_Y'
        )

        return target_bone

    def __make_aim_control(self, org_bone, aim_bone) -> BoneInfo:
        """Create direct control, with a display bone at the tip of it."""
        ctr_bone = self.bone_sets['Aim Target Control'].new(
            name=self.naming.make_name(
                ["CTR"], *self.naming.slice_name(org_bone.name)[1:]
            ),
            source=org_bone,
            parent=org_bone.parent if self.params.aim.root else org_bone,
            custom_shape_name=self.params.aim.shape_eye.shape_name,
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

    def __make_root_bone(self, org_bone) -> BoneInfo:
        root_bone = self.bone_sets['Aim Root Control'].new(
            name=self.naming.add_prefix(org_bone.name, 'ROOT'),
            source=org_bone,
            parent=org_bone.parent,
            custom_shape_name=self.params.aim.shape_root.shape_name,
            custom_shape_scale=2,
            custom_shape_along_length=1,
        )

        org_bone.parent = root_bone

        return root_bone

    def __create_eye_highlight(self, ctr_bone):
        name_slices = self.naming.slice_name(ctr_bone)
        name_slices[1] += "_Highlight"
        highlight_ctr = self.bone_sets['Aim Target Control'].new(
            name=self.naming.make_name(*name_slices),
            source=ctr_bone,
            parent=ctr_bone,
            custom_shape_name=self.params.aim.shape_highlight.shape_name,
            custom_shape_scale=ctr_bone.custom_shape_scale / 3,
            custom_shape_along_length=1.05,
        )

        if ctr_bone.parent:
            prop_name = "follow_eye"
            self.rig_ui__add_bone_property(
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

            self.create_driven_armature_constraint(highlight_ctr, target_bones=[ctr_bone.parent, ctr_bone], prop_bone=highlight_ctr, prop_name=prop_name)

        self.lock_transforms(highlight_ctr, loc=False, rot=False, scale=[False, True, False])

        if self.params.aim.deform:
            self.make_def_bone(highlight_ctr, self.bones_def)

    def __group_get_components(self) -> list[Component_Aim]:
        return [comp for comp in self.generator.all_components
                if isinstance(comp, Component_Aim) and comp.params.aim.group == self.params.aim.group]

    def __is_last_of_group(self) -> bool:
        return self is self.__group_get_components()[-1]

    def __group_get_tgt_ctrls(self) -> list[BoneInfo]:
        return [comp.target_bone for comp in self.__group_get_components()]

    def __group_get_org_bones(self) -> list[BoneInfo]:
        return [comp.bones_org[0] for comp in self.__group_get_components()]

    def __ensure_group_master(self) -> BoneInfo | None:
        """This function will be called by each aim rig, but we want to make sure
        it only runs once per aim group.
        """

        # Check if a bone with the right name already exists and if it does, just return it.
        if not self.__is_last_of_group():
            return

        group_name = self.params.aim.group
        group_master_name = self.naming.add_prefix(group_name, "TGT")
        tgt_bones = self.__group_get_tgt_ctrls()
        org_bones = self.__group_get_org_bones()

        # Find a parent to fall back to, although ideally the rigger specifies
        # parents using params.parenting.parent_switching.
        first_parent = ""
        for tgt_bone in tgt_bones:
            if tgt_bone.parent and first_parent == "":
                first_parent = tgt_bone.parent.name
                break

        if len(tgt_bones) < 2:
            return None

        # Find center of all org bones
        orgs_center = bounding_box_center([b.head for b in org_bones])

        # Find center of all targets
        target_positions = [b.head for b in tgt_bones]
        target_center = bounding_box_center(target_positions)
        z_axis = Vector((0, 0, 0))
        lgt = 0
        for b in tgt_bones:
            z_axis += b.z_axis
            lgt += b.length
        lgt /= len(tgt_bones)

        bbox_low, bbox_high = bounding_box(target_positions)
        shape_size = max(sorted(tgt_bones, key=lambda b: b.custom_shape_scale_xyz.x)[0].custom_shape_scale_xyz)
        targets_size = (bbox_high - bbox_low).length + shape_size * 1.2

        # Create a helper bone in the center.
        group_vec = target_center - orgs_center
        center_bone = self.bone_sets['Mechanism Bones'].new(
            name="CEN-" + group_name,
            source=self.bones_org[0],
            head=orgs_center,
            tail=orgs_center + group_vec.normalized() * lgt,
            parent=self.generator.find_bone_info(first_parent),
        )
        center_bone.roll_align_vector(center_bone.head + z_axis)
        center_bone.add_constraint('ARMATURE', targets=[{'subtarget': bone.name} for bone in tgt_bones])

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
            tail=target_center + group_vec.normalized() * lgt,
            custom_shape_name=self.params.aim.shape_master.shape_name,
            use_custom_shape_bone_size=False,
            custom_shape_scale_xyz=Vector((targets_size, 1, shape_size*2.2)),
        )
        group_master.roll_align_other(center_bone)
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
            "Aim Target Control", collections=['Face Main'], color_palette='THEME12', wire_width=1.5
        )
        cls.define_bone_set(
            "Aim Root Control", collections=['Face Secondary'], color_palette='THEME12'
        )
        cls.define_bone_set(
            "Aim Deform", collections=['Deform Bones'], is_advanced=True
        )

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        cls.draw_prop_custom_shape(context, layout, params.aim, 'shape_eye')
        cls.draw_prop_custom_shape(context, layout, params.aim, 'shape_target')
        if params.aim.root:
            cls.draw_prop_custom_shape(context, layout, params.aim, 'shape_root')
        if params.aim.create_sub_control:
            cls.draw_prop_custom_shape(context, layout, params.aim, 'shape_highlight')
        cls.draw_prop(context, layout, params.aim, 'target_size')

    @classmethod
    def draw_control_params(cls, layout, context, component):
        params = component.params
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
        min=0.1,
    )
    target_size: FloatProperty(
        name="Target Size",
        default=1.0,
        description="Size multiplier for the target control. This is for display purposes only, as sometimes the target can be too small, and there's no good automatic way to determine the desired size",
        min=0.1,
        soft_max=10.0,
    )
    flatten: FloatProperty(
        name="Flatten X",
        description="Discard the X component of the eye vector when placing the target control. Useful for eyes that have significant default rotation. This can result in the eye becoming cross-eyed in the default pose, but it prevents the eye targets from crossing each other or being too far from each other",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
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
        name="Create Highlight",
        description="Create a secondary control and deform bone attached to the aim control. Useful for eye highlights. The extent to which it follows the eye's rotation can be controlled in the Rig UI under the Face panel",
        default=False,
    )

    shape_target: Component_Base.make_custom_shape_params(
        identifier="Target",
        default="Circle"
    )
    shape_eye: Component_Base.make_custom_shape_params(
        identifier="Eye",
        default="Circle"
    )
    shape_root: Component_Base.make_custom_shape_params(
        identifier="Root",
        default="Square"
    )
    shape_highlight: Component_Base.make_custom_shape_params(
        identifier="Highlight",
        default="Circle"
    )
    shape_master: Component_Base.make_custom_shape_params(
        identifier="Master",
        default="Circle"
    )

RIG_COMPONENT_CLASS = Component_Aim
