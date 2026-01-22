# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..generation.troubleshooting import CloudRig_Generator
    from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Object, PoseBone, PropertyGroup

from ..generation.troubleshooting import LoggerMixin
from ..rig_component_features.bone_gizmos import BoneGizmoMixin
from ..rig_component_features.bone_set import BoneSetMixin
from ..rig_component_features.custom_props import CloudCustomPropertiesMixin
from ..rig_component_features.mechanism import CloudMechanismMixin
from ..rig_component_features.object import CloudObjectUtilitiesMixin
from ..rig_component_features.overlay_painter import no_overlay
from ..rig_component_features.params_ui_utils import CloudUIMixin
from ..rig_component_features.parenting import CloudParentingMixin
from ..rig_component_features.widgets.widgets import (
    refresh_widget_list,
    widget_name,
    widgets_enum_items,
)


class Component_Base(
    LoggerMixin,
    CloudParentingMixin,
    CloudMechanismMixin,
    CloudObjectUtilitiesMixin,
    CloudCustomPropertiesMixin,
    CloudUIMixin,
    BoneSetMixin,
    BoneGizmoMixin,
):
    """Base class that all CloudRig components should inherit from."""
    # Name to display for this component type in the UI. Cloud Base doesn't
    # appear in Blender because there's no RIG_COMPONENT_MODULE variable in this file.
    ui_name = "Cloud Base"

    # Constraints on the metarig's bones get transferred to bones named with this prefix.
    # Child classes are expected to override this with the prefix of their highest level controls.
    relink_default_prefix = ""

    # String displayed when Parent Switching is enabled.
    parent_switch_behaviour = "The active parent will own the component's root bone."
    # Whether enabling parent switching should be mutually exclusive with the Root Parent option.
    parent_switch_overwrites_root_parent = True

    # Whether original bones from the metarig should be created during rig generation.
    keep_original_bones = True
    # Whether bone collection assignments of the original bones should be preserved.
    keep_original_bones_collections = False
    # Whether bone colors of the original bones should be preserved.
    keep_original_bones_colors = False

    # Whether the Base Name param should be shown in the UI. Used only by some child classes.
    use_base_name = False

    def __str__(self) -> str:
        return f'{self.base_bone_name}: {type(self).ui_name}'

    def __init__(
        self,
        generator: CloudRig_Generator,
        bone_name: str,
        parent_component=None
    ):
        # Quick access to generator features.
        self.generator = generator
        # Presence of an OverlayPainter instance determines whether code is running for a real rig generation, or just for overlay drawing.
        # The latter should skip as many steps as possible while still providing the BoneInfo data needed to draw the overlays.
        self.painter = generator.painter
        self.naming = self.generator.naming
        self.logger = self.generator.logger
        self.generator_params = self.generator.params
        self.scale = self.generator.scale
        self.target_rig = generator.target_rig
        self.metarig = generator.metarig
        self.base_bone_name = bone_name
        pose_bone = self.metarig.pose.bones.get(bone_name)
        self.params = pose_bone.cloudrig_component.params
        self.defaults = dict(self.generator.defaults)

        # Components should be aware of their parent and children components.
        self.parent_component = parent_component
        if parent_component:
            parent_component.child_components.append(self)
        self.child_components = []

        # Determine Suffix/Prefix.
        self.side_suffix = ""
        self.side_prefix = ""
        is_left = self.naming.side_is_left(self.base_bone_name)
        if is_left:
            self.side_suffix = "L"
            self.side_prefix = "Left"
        elif is_left is False:
            self.side_suffix = "R"
            self.side_prefix = "Right"
        self.suffixes = [self.side_suffix]
        blender_zeroes = self.naming.get_blender_zeroes(self.base_bone_name)
        if blender_zeroes:
            self.suffixes.append(blender_zeroes)

        self.bone_count = len(self.get_component_pbone_chain())

        # Reference to this component's root bone info which should be set in create_bone_infos()
        # Used for the "Custom Root Parent" feature.
        self.root_bone = None

        self.__force_parameters(self.metarig_base_pbone)

        # Prepare Bone Sets
        self.bone_sets = self.init_bone_sets()

        # Quick access to the 3 basic bone sets.
        self.bones_org = self.bone_sets['Original Bones']
        self.bones_def = self.bone_sets['Deform Bones']
        self.bones_mch = self.bone_sets['Mechanism Bones']

    @property
    def base_name(self):
        # NOTE: self.params.base.base_name shouldn't be accessed directly outside of here.
        return self.params.base.base_name or self.naming.get_name_parts(self.base_bone_name)[1]

    def make_name(self, prefixes: list[str], base=""):
        orig_prefixes, base_bone_base, suffixes, blender_zeroes = self.naming.get_name_parts(self.base_bone_name)
        if not base:
            base = base_bone_base
        return orig_prefixes + "-".join(prefixes) + "-" + base + suffixes + blender_zeroes

    def base__load_metarig_bones(self) -> dict[str, BoneInfo]:
        """Read ORG bones into BoneInfo instances in self.bones_org
        which will be turned into real bones by the CloudRig generator.
        """

        bone_infos = {}
        for pbone in self.get_component_pbone_chain():
            if self.naming.has_trailing_numbers(pbone):
                self.add_log(
                    "Trailing zeroes",
                    trouble_bone=pbone.name,
                    description="Trailing zeroes in the metarig can cause bone name clashes and should be avoided.",
                    operator='object.cloudrig_rename_bone',
                    op_kwargs={
                        'old_name': pbone.name,
                        'new_name': self.naming.uniqify(pbone)
                    },
                )

            bone_info = self.bones_org.new(
                name=pbone.name,
                source=pbone,
                allow_pose_transforms=bool(self.painter),
                keep_collections=type(self).keep_original_bones_collections,
                keep_colors=type(self).keep_original_bones_colors,
            )
            if not bone_info:
                self.raise_generation_error(
                    description="Make sure your bone names are unique and do not have trailing zeroes!",
                    description_short=f'Bone name "{bone_info.name}" was used twice!',
                )
            bone_info.preserve = self.keep_original_bones
            bone_infos[bone_info.name] = bone_info

        return bone_infos

    ### Functions called by the CloudRig Generator.
    def create_bone_infos(self, context):
        self.root_bone = self.bones_org[0]

    def create_component_interactions(self, context):
        self.base__relink()
        skip_root_parenting = (
            self.parent_switch_overwrites_root_parent
            and self.params.parenting.parent_switching
        )
        if not skip_root_parenting and self.params.parenting.root_parent != "":
            self.base__apply_custom_root_parent()
        if self.params.parenting.parent_switching:
            self.base__apply_parent_switching()
        # self.gizmos__add_interactions()

    def create_helper_objects(self, context):
        # Called by the generator. Subclasses can use this to create
        # helpers like curves, empties, lattices.
        pass

    ### Relinking - Allow users to easily add constraints to the generated rig to specific bones,
    # in cases where user intent can be made clear.
    @no_overlay
    def base__relink(self):
        """Move constraints from original bones to other bones."""
        for org_idx, org_bi in enumerate(self.bones_org):
            for con_info in org_bi.constraint_infos[:]:
                if not con_info.is_from_real:
                    # If this constraint was added by CloudRig code, don't relink it.
                    # We only want to relink constraints that were added by the user.
                    continue

                self.base__relink_single(org_idx, con_info)

    def base__relink_single(self, org_idx, con_info):
        org_bi = self.bones_org[org_idx]
        to_binfo = self.base__relink_get_target(org_idx, con_info)
        if con_info.type == 'ARMATURE' and 'NOHLP' not in con_info.name:
            to_binfo = self.create_parent_bone(to_binfo, self.bones_mch)

        base_name = con_info.name.split("@")[0]
        if to_binfo != org_bi:
            to_binfo.constraint_infos.append(con_info)
            org_bi.constraint_infos.remove(con_info)
        elif "-" in base_name and (('KEEP-' not in base_name and 'ORG-' not in base_name) or not org_bi.preserve):
            target_name = con_info.name.split("-")[0] + "-" + org_bi.name
            self.raise_generation_error(
                description=f'Relinking Failed for constraint "{con_info.name}".\nThe dash (-) in the constraint name tells CloudRig to move the constraint to a generated bone named "{target_name}", but no such bone exists.',
                icon='CONSTRAINT_BONE',
                description_short=f'Relinking Failed: {con_info.name}',
                trouble_bone=org_bi.name,
            )

    def base__relink_get_target(self, org_i: int, con_info: ConstraintInfo) -> BoneInfo:
        """Return which BoneInfo a given constraint should be moved to.
        Params:
            org_i: Index of the original bone that has the constraint
            con_info: The constraint itself.
        This function should be overridden by child classes.
        By default, we will return the original bone itself, ie. not moving the constraint anywhere.
        """

        org_name = self.bones_org[org_i].name

        name_without_target = con_info.name.replace("NOHLP-", "NOHLP_").split("@")[0]
        if "-" in name_without_target:
            prefix, _base_name = name_without_target.rsplit("-", 1)
        else:
            prefix = type(self).relink_default_prefix

        target_name = "-".join([prefix, org_name])
        for bone_info in self.all_bone_infos:
            if bone_info.name == target_name:
                return bone_info

        return self.bones_org[org_i]

    @property
    def all_bone_infos(self) -> Iterable[BoneInfo]:
        for set_name, bone_set in self.bone_sets.items():
            for bone_info in bone_set:
                yield bone_info

    ##############################
    # Parameters

    def __force_parameters(self, metarig_base_pbone: PoseBone):
        """Allows the class to force certain parameter values for its instances."""
        clas = type(self)
        for param in clas.forced_params.keys():
            forced_value = clas.forced_params[param]
            if forced_value != 'NOFORCE':
                parts = param.split(".")
                component_prop = metarig_base_pbone.cloudrig_component.params
                while len(parts) > 1:
                    part = parts.pop(0)
                    component_prop = getattr(component_prop, part)

                current_value = getattr(component_prop, parts[0])
                if current_value != forced_value:
                    setattr(component_prop, parts[0], forced_value)

    @classmethod
    def draw_control_params(cls, layout, context, component):
        params = component.params
        if cls.is_advanced_mode(context) and cls.use_base_name:
            layout.prop(params.base, 'base_name', text="Base Name")
            layout.separator()

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        layout.operator('pose.cloudrig_refresh_widget_list', icon='FILE_REFRESH')
        layout.separator()

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Deform Bones', is_advanced=True, defaults={'display_type': 'BBONE'})
        cls.define_bone_set('Mechanism Bones', is_advanced=True, defaults={'display_type': 'STICK'})
        cls.define_bone_set('Original Bones', is_advanced=True, wire_width=0.5)


    @classmethod
    def make_rotation_mode_param(
        cls,
        name="Rotation Mode",
        description="Set the rotation mode of the controls",
        can_propagate=True,
        default='XYZ',
    ):
        items = [
            ('XYZ', 'XYZ Euler', ''),
            ('XZY', 'XZY Euler', ''),
            ('YXZ', 'YXZ Euler', ''),
            ('YZX', 'YZX Euler', ''),
            ('ZXY', 'ZXY Euler', ''),
            ('ZYX', 'ZYX Euler', ''),
            ('AXIS_ANGLE', 'Axis Angle', ''),
            ('QUATERNION', 'Quaternion', ''),
        ]
        if can_propagate:
            items.append(
                (
                    'PROPAGATE',
                    'Propagate',
                    'Propagate rotation mode from each meta bone to its corresponding control',
                ),
            )

        return EnumProperty(
            name=name, description=description, items=items, default=default
        )


    @classmethod
    def make_inherit_scale_param(
        cls,
        name="Inherit Scale",
        description="Set the scale inheritance mode for the controls",
        can_propagate=True,
        default='FULL',
    ):
        items = [
            ('FULL', 'Full', 'Inherit all effects of parent scaling'),
            (
                'FIX_SHEAR',
                'Fix Shear',
                'Inherit scaling, but remove shearing of the child in the rest orientation',
            ),
            (
                'ALIGNED',
                'Aligned',
                'Rotate non-uniform parent scaling to align with the child, applying parent X scale to child X axis, and so forth',
            ),
            (
                'AVERAGE',
                'Average',
                'Inherit uniform scaling representing the overall change in the volume of the parent',
            ),
            ('NONE', 'None', 'Completely ignore parent scaling'),
        ]
        if can_propagate:
            items.append(
                (
                    'PROPAGATE',
                    'Propagate',
                    'Propagate scale inheritance mode from each meta bone to its corresponding control',
                )
            )

        return EnumProperty(
            name=name, description=description, items=items, default=default
        )


    @classmethod
    def make_custom_shape_params(
        cls,
        *,
        identifier: str,
        default: str,
        description="",
    ) -> dict[str, type]:
        def update_widgets(self, context):
            refresh_widget_list()

        def update_pointer(self, context):
            update_widgets(self, context)
            if not self.use_pointer:
                # Pointer was de-toggled.
                if self.custom_shape:
                    self.name = widget_name(self.custom_shape.name)
                else:
                    self.name = ""
            else:
                # Pointer was en-toggled.
                obj = bpy.data.objects.get("WGT-"+self.name)
                if obj:
                    self.custom_shape = obj

        @property
        def shape_name(self):
            if self.use_pointer and self.custom_shape:
                return self.custom_shape.name
            return self.name

        @shape_name.setter
        def shape_name(self, value: str):
            if self.use_pointer:
                self.custom_shape = bpy.data.objects.get("WGT-"+value)
            else:
                self.name = value

        @property
        def shape_object(self) -> Object | None:
            """Return local object of a custom shape, if it exists in the scene."""
            if self.use_pointer:
                return self.custom_shape
            return bpy.data.objects.get('WGT-' + self.shape_name)

        def get_enum(self, _current_value, _is_set):
            value = next((w[4] for w in widgets_enum_items() if w[0]==self.name), 0)
            return value

        def set_enum(self, new_value, _current_value, _is_set):
            value = widgets_enum_items()[new_value][0]
            self.name = value
            return new_value

        default_description = 'You can add your own shape library in CloudRig\'s preferences.\n\nLocal objects starting with "WGT-" will also appear.'
        class_props = {
            '__annotations__': {
                'name': StringProperty(
                    name=identifier+" Shape",
                    description=description or default_description,
                    default=default,
                    update=update_widgets,
                ),
                'name_enum': EnumProperty(
                    name=identifier+" Shape",
                    description=description or default_description,
                    items=widgets_enum_items,
                    get_transform=get_enum,
                    set_transform=set_enum,
                ),
                'use_pointer': BoolProperty(
                    name="Select Local Object",
                    description='Select an object in the current file to use as widget. Must be a mesh object whose name starts with "WGT-"',
                    default=False,
                    update=update_pointer,
                ),
                'custom_shape': PointerProperty(
                    name=identifier + " Shape",
                    description='Object to use as custom shape for these bones. Must be a mesh object whose name starts with "WGT-"',
                    type=Object,
                    poll=lambda self, object: object.type=='MESH' and object.name.startswith("WGT-"),
                )
            },
            'shape_name': shape_name,
            'shape_object': shape_object,
        }
        class_name="CloudRig_CustomShape_"+ identifier.replace(" ", "_").lower()
        group_class = type(class_name, (PropertyGroup,), class_props)
        # NOTE: This should become a PointerProperty(type=group_class)
        # But doing that here is too early, because the group_class would have to
        # already be registered, which we don't want to do until inject_update_callback()
        # has a chance to run on it.
        # See get_param_classes_ordered() for when this gets converted to a PointerProperty.
        return group_class


class Params(PropertyGroup):
    # NOTE: This param shouldn't be accessed directly (self.params.base.base_name)!
    # Use self.base_name instead, which falls back when this is empty.
    base_name: StringProperty(
        name="Base Name",
        description='Optional. If provided, use this as the base name for some generated bones and properties, '
            'rather than the bone name. This should not include a side indicator ("Left"/"Right"), as that will'
            'be added automatically',
        default="",
    )
