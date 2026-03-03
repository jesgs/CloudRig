# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..rig_components.cloud_base import Component_Base
    from .bone_set import BoneSet

from math import pi

from bpy.app.translations import pgettext_rpt as rpt_
from bpy.types import (
    Bone,
    Constraint,
    EditBone,
    Object,
    PoseBone,
    bpy_prop_array,
)
from mathutils import Matrix, Vector
from rna_prop_ui import rna_idprop_has_properties

from ..generation import naming
from ..rig_component_features.mechanism import copy_relink_real_driver
from ..utils.external.mechanism import make_driver
from ..utils.maths import flat
from ..utils.rig import (
    calc_roll_to_align_axis,
    wrap_angle_pi,
)
from .properties_ui import ensure_custom_property, make_property

# Sadly we can't rely on Blender's RNA property defaults because they are extremely inconsistent.
# Instead, we define here what properties we are interested in writing, and with what default values.
# The downside is that any time a new property is implemented, it has to be added here.
edit_bone_properties = {
    'head': Vector((0, 0, 0)),
    'tail': Vector((0, 1, 0)),
    'roll': 0,
    'use_connect': False,
}

bone_properties = {
    'display_type': 'ARMATURE_DEFINED',
    'collections': [],
    'hide_select': False,
    'hide': False,
    'use_deform': False,
    'show_wire': False,
    'bbone_segments': 1,
    'bbone_x': 0.1,  # NOTE: These two are wrapped by bbone_width @property.
    'bbone_z': 0.1,
    'bbone_mapping_mode': 'CURVED',
    'bbone_curveinx': 0,
    'bbone_curveinz': 0,
    'bbone_curveoutx': 0,
    'bbone_curveoutz': 0,
    'bbone_rollin': 0,
    'bbone_rollout': 0,
    'use_endroll_as_inroll': False,
    'bbone_easein': 1,
    'bbone_easeout': 1,
    'bbone_scalein': Vector((1, 1, 1)),
    'bbone_scaleout': Vector((1, 1, 1)),
    'use_scale_easing': False,
    'bbone_handle_type_start': 'AUTO',
    'bbone_custom_handle_start': None,  # BoneInfo
    'bbone_handle_use_scale_start': [False, False, False],
    'bbone_handle_use_ease_start': False,
    'bbone_handle_type_end': 'AUTO',
    'bbone_custom_handle_end': None,  # BoneInfo
    'bbone_handle_use_scale_end': [False, False, False],
    'bbone_handle_use_ease_end': False,
    'envelope_distance': 0.25,
    'envelope_weight': 1.0,
    'use_envelope_multiply': False,
    'head_radius': 0.1,
    'tail_radius': 0.1,
    'use_inherit_rotation': True,
    'inherit_scale': 'FULL',
    'use_local_location': True,
    'use_relative_parent': False,
}

pose_bone_properties = {
    'custom_shape': None,  # bpy.types.Object
    'custom_shape_transform': None,  # BoneInfo
    'use_transform_at_custom_shape': False,
    'use_transform_around_custom_shape': False,
    'custom_shape_scale_xyz': Vector((1.0, 1.0, 1.0)),
    'custom_shape_translation': Vector((0.0, 0.0, 0.0)),
    'custom_shape_rotation_euler': Vector((0.0, 0.0, 0.0)),
    'custom_shape_wire_width': 1.0,
    'use_custom_shape_bone_size': True,
    'rotation_mode': 'QUATERNION',
    'lock_location': [False, False, False],
    'lock_rotation': [False, False, False],
    'lock_rotation_w': False,
    'lock_scale': [False, False, False],
    'ik_stretch': 0,
    'lock_ik_x': False,
    'lock_ik_y': False,
    'lock_ik_z': False,
    'ik_stiffness_x': 0,
    'ik_stiffness_y': 0,
    'ik_stiffness_z': 0,
    'use_ik_limit_x': False,
    'use_ik_limit_y': False,
    'use_ik_limit_z': False,
    'ik_min_x': 0,
    'ik_max_x': 0,
    'ik_min_y': 0,
    'ik_max_y': 0,
    'ik_min_z': 0,
    'ik_max_z': 0,
    'x_axis': Vector((1, 0, 0)),
    'y_axis': Vector((0, 1, 0)),
    'z_axis': Vector((0, 0, 1)),
}


class BoneInfo:
    """
    Abstraction layer for bpy.types.Bone/PoseBone/EditBone.

    This class does not handle posing/animation of the bone, only creating and
    rigging it. Eg, it does not store local space loc/rot/scale transforms or keyframes,
    but it does store head/tail vectors and (abstractions of) constraints and drivers.
    """

    def __init__(
        self,
        bone_set: BoneSet,
        name: str,
        source: (PoseBone | BoneInfo | None),
        allow_pose_transforms = False,
        owner_component: Component_Base = None,
        keep_collections=False,
        keep_colors=False,
        **kwargs,
    ):
        """
        source: Bone to take transforms from (head, tail, roll, bbone_x, bbone_z) as well as parent bone.
        kwargs: Allow setting arbitrary bone properties at initialization.
        """

        self.bone_set = bone_set
        self.owner_component = owner_component
        self.preserve = True
        self.next = self.prev = None  # For LinkedList behaviour.
        self.gizmo_vgroup = ""  # For CloudRig Gizmos
        self.gizmo_operator = 'transform.translate'

        # {"name": {kwargs}} where kwargs will be passed to make_property().
        self.custom_props = {}
        self.custom_props_edit = {}

        # List of dictionaries that will be passed to make_driver().
        # This is where we define drivers during rig generation.
        self.drivers = []
        # Same but for data bone properties.
        self.drivers_data = []

        # Data path & array index of drivers that should be copied from the metarig.
        # This supports keyframes and curve modifiers.
        self.drivers_to_copy: list[tuple[str, int]] = []

        self.constraint_infos: list[ConstraintInfo] = []

        self.name = name
        self._parent: BoneInfo = None
        self.parent_helper: BoneInfo = None
        self.children: list[BoneInfo] = []

        self.init_variables(edit_bone_properties)
        self.init_variables(bone_properties)
        self.init_variables(pose_bone_properties)

        self.color_palette_base = kwargs.get('color_palette_base', 'DEFAULT')
        self.color_palette_pose = kwargs.get('color_palette_pose', 'DEFAULT')

        self._custom_shape_name = ""
        self._source = self

        # If True, this bone won't be auto-parented to the root if it doesn't have a parent.
        self.ignore_orphan = False

        if source:
            if type(source) is type(self):
                self._source = source
                self.head = source.head.copy()
                self.tail = source.tail.copy()
                self.roll = source.roll
                self.bbone_width = source.bbone_width
                self.parent = source.parent
                self.custom_shape_translation = source.custom_shape_translation.copy()
                self.custom_shape_rotation_euler = source.custom_shape_rotation_euler.copy()
                self.custom_shape_scale_xyz = source.custom_shape_scale_xyz.copy()

                if keep_colors:
                    self.color_palette_base = source.color_palette_base
                    self.color_palette_pose = source.color_palette_pose
                if keep_collections:
                    self.collections = source.collections.copy()
            else:
                # Copy data from PoseBone and Bone.
                assert isinstance(source, PoseBone), f"BoneInfo can only use a PoseBone or another BoneInfo as source, not {type(source)}."
                self.__load_data_from_real_pbone(
                    source,
                    allow_pose_transforms=allow_pose_transforms,
                    keep_collections=keep_collections,
                    keep_colors=keep_colors
                )

        # Apply property values from arbitrary keyword arguments if any were passed.
        for key, value in kwargs.items():
            if (
                isinstance(value, Vector)
                or isinstance(value, Matrix)
                or type(value) is dict
                or type(value) is list
            ):
                value = value.copy()
            setattr(self, key, value)

    def __load_data_from_real_pbone(
        self,
        pose_bone: PoseBone,
        allow_pose_transforms=False,
        keep_collections=False,
        keep_colors=False,
    ):
        """Load data from a PoseBone into this BoneInfo instance.
        Including its constraints, drivers, custom properties."""
        # NOTE: Parent is only stored as a string!

        rig_ob = pose_bone.id_data
        data_bone = pose_bone.bone
        edit_bone = rig_ob.data.edit_bones.get(data_bone.name)

        self.custom_shape_translation = pose_bone.custom_shape_translation.copy()
        self.custom_shape_rotation_euler = pose_bone.custom_shape_rotation_euler.copy()
        self.custom_shape_scale_xyz = pose_bone.custom_shape_scale_xyz.copy()
        self.bbone_width = data_bone.bbone_x
        if allow_pose_transforms and not edit_bone:
            self.head = pose_bone.head.copy()
            self.tail = pose_bone.tail.copy()
            _axis, self.roll = Bone.AxisRollFromMatrix(pose_bone.matrix.to_3x3())
        elif edit_bone:
            self.head = edit_bone.head.copy()
            self.tail = edit_bone.tail.copy()
            self.roll = edit_bone.roll
        else:
            self.head = data_bone.head_local.copy()
            self.tail = data_bone.tail_local.copy()
            _axis, self.roll = Bone.AxisRollFromMatrix(data_bone.matrix_local.to_3x3())

        if pose_bone.parent:
            self.parent = pose_bone.parent.name

        sources = {
            pose_bone: pose_bone_properties,
            data_bone: bone_properties,
        }

        for source, prop_list in sources.items():
            for key in prop_list:
                if not hasattr(source, key):
                    # This can happen when a new property is introduced in Blender, eg.
                    # custom_shape_wire_width in 4.2.
                    # Ignore such values in older versions, to preserve compatibility.
                    continue
                if key in ('x_axis', 'y_axis', 'z_axis', 'matrix'):
                    continue
                value = getattr(source, key)
                if value in [None, ""]:
                    continue
                if key == 'collections':
                    value = [coll.name for coll in value]
                if type(value) in [Vector, Matrix]:
                    value = value.copy()
                if type(value) is bpy_prop_array:
                    value = value[:]
                if type(value) in {EditBone, Bone, PoseBone}:
                    value = value.name
                if getattr(self, key) == value:
                    continue

                setattr(self, key, value)

        # The default value of use_deform in Blender is True, but for CloudRig, False makes a LOT more sense.
        self.use_deform = False

        # Load color palettes (only presets are supported, no custom colors)
        # TODO: If one day Blender's color presets are fixed, drop support for custom colors.
        if keep_colors:
            if data_bone.color.palette == 'CUSTOM' and False:
                self.owner_component.add_log(rpt_("Custom Colors must not be used."))
            else:
                self.color_palette_base = data_bone.color.palette

        # Load Collections.
        if keep_collections:
            self.collections = [coll.name for coll in data_bone.collections]

        if self.owner_component.painter:
            return

        # Load Constraints.
        for constr in pose_bone.constraints:
            self.add_constraint_from_real(constr)

        # Load Drivers to be copied later.
        if rig_ob.animation_data and not self.owner_component.painter:
            driver_map = self.owner_component.generator.driver_map
            if self.name in driver_map:
                for data_path, array_index in driver_map[self.name]:
                    fcurve = rig_ob.animation_data.drivers.find(
                        data_path, index=array_index
                    )
                    if 'constraints' in fcurve.data_path:
                        con_name = data_path.split('constraints["')[-1].split('"]')[0]
                        constraint_info = self.get_constraint(con_name)
                        if constraint_info:
                            constraint_info.drivers_to_copy.append(
                                (data_path, array_index)
                            )
                            continue

                    self.drivers_to_copy.append((data_path, array_index))

        # Load Custom Properties.
        if rna_idprop_has_properties(pose_bone):
            rna_properties = {
                prop.identifier
                for prop in pose_bone.bl_rna.properties
                if prop.is_runtime
            }
            for prop_name in pose_bone.keys():
                if prop_name in rna_properties:
                    # We don't want to copy addon-defined properties.
                    continue
                if 'rigify' in prop_name:
                    # Legacy stuff, don't need it.
                    continue
                try:
                    prop_data = pose_bone.id_properties_ui(prop_name).as_dict()
                except TypeError:
                    # This should only happen with python dictionaries.
                    # Just store the value to be able to copy the property over to the Target Rig.
                    prop_data = {'default': pose_bone[prop_name]}

                value = pose_bone[prop_name]
                if hasattr(value, 'to_list'):
                    value = value.to_list()
                    prop_data['default'] = value
                elif hasattr(value, 'to_dict'):
                    value = value.to_dict()
                    prop_data['default'] = value
                elif 'id_type' in prop_data:
                    # Setting the default to None for Datablock pointer props is necesasry for
                    # rna_idprop_ui_create() to interpret this data as a Datablock property.
                    prop_data['default'] = None

                prop_data['value'] = value
                prop_data['overridable'] = pose_bone.is_property_overridable_library(
                    f'["{prop_name}"]'
                )

                if 'description' not in prop_data:
                    prop_data['description'] = ""
                self.custom_props[prop_name] = prop_data

    def init_variables(self, var_dict):
        for key, value in var_dict.items():
            # Make Vectors/Matrices/Dicts/Lists unique copies.
            # Otherwise copied bones would share values.
            if key in ('x_axis', 'y_axis', 'z_axis', 'matrix'):
                continue
            if hasattr(value, 'copy'):
                value = value.copy()
            setattr(self, key, value)

    @property
    def bone(self) -> BoneInfo:
        return self

    @property
    def source(self) -> BoneInfo:
        """Returns the BoneInfo that this BoneInfo was copied from, or
        this BoneInfo itself.
        """
        # Recursively get the source of each bone until getting to what should be an ORG bone.
        if self._source == self:
            return self
        return self._source.source

    @property
    def custom_shape_scale(self) -> float:
        return sum((abs(s) for s in self.custom_shape_scale_xyz)) / 3

    @custom_shape_scale.setter
    def custom_shape_scale(self, value):
        self.custom_shape_scale_xyz *= Vector((value, value, value))

    @property
    def parent(self) -> BoneInfo | None:
        return self._parent

    @property
    def is_orphan(self) -> bool:
        if self.parent:
            return False

        for con_info in self.constraint_infos:
            if con_info.type == 'ARMATURE':
                return False
            if con_info.type == 'CHILD_OF':
                return False

        if self.ignore_orphan:
            return False

        return True

    @parent.setter
    def parent(self, value):
        if self.parent == value:
            return
        if self.parent and type(self.parent) is not str:
            self.parent.children.remove(self)
        self._parent = value
        if value and type(self) is type(value):
            value.children.append(self)

        # If we want to use connected parenting, do it explicitly, after setting the parent.
        # This is a more intuitive because otherwise changing the parent of a connected bone
        # will also move the child bone, which is quite unexpected.
        self.use_connect = False

    @property
    def bbone_width(self) -> float:
        """Return average display size of both axes."""
        return (self.bbone_x + self.bbone_z) / 2

    @bbone_width.setter
    def bbone_width(self, value):
        """Set all bone size related values at once."""
        self.bbone_x = value
        self.bbone_z = value
        self.head_radius = value * 0.1
        self.tail_radius = value * 0.1
        if hasattr(self, 'use_deform') and not self.use_deform:
            self.envelope_distance = 0

    def scale_width(self, value: int):
        """Set b-bone width relative to current."""
        self.bbone_width *= value

    @property
    def bbone_segments(self) -> int:
        return self._bbone_segments

    @bbone_segments.setter
    def bbone_segments(self, value: int):
        self._bbone_segments = value
        if value > 1:
            self.display_type = 'BBONE'

    @property
    def vector(self):
        """Vector pointing from head to tail."""
        return self.tail - self.head

    @vector.setter
    def vector(self, value: Vector):
        self.tail = self.head + value

    def scale_length(self, value: int):
        """Set bone length relative to its current length."""
        self.tail = self.head + self.vector * value

    @property
    def length(self) -> float:
        lgt = (self.tail - self.head).length
        if lgt <= 0:
            raise ValueError(rpt_("Length of bone must not be 0: {bone}, {head}, {tail}".format(bone=self.name, head=self.head, tail=self.tail)))
        return lgt

    @length.setter
    def length(self, value: float):
        assert value > 0.0, f"{self.name}: Bone length cannot be 0!"
        self.tail = self.head + self.vector.normalized() * value

    @property
    def center(self) -> Vector:
        return self.head + self.vector / 2

    def reverse(self):
        """Flip the head and the tail."""
        old_z_axis = self.z_axis.copy()
        self.head, self.tail = self.tail, self.head
        self.roll_align_vector(self.head+old_z_axis)

    def put(
        self, loc=None, length=None, width=None, scale_length=None, scale_width=None
    ):
        if not loc:
            loc = self.head

        offset = loc - self.head
        self.head = loc
        self.tail = loc + offset

        if length:
            self.length = length
        if width:
            self.bbone_width = width
        if scale_length:
            self.scale_length(scale_length)
        if scale_width:
            self.scale_width(scale_width)

    def flatten(self, axis=""):
        if axis:
            length = self.length
            if axis == 'X':
                self.tail.y = self.head.y
                self.tail.z = self.head.z
            elif axis == 'Y':
                self.tail.x = self.head.x
                self.tail.z = self.head.z
            elif axis == 'Z':
                self.tail.x = self.head.x
                self.tail.y = self.head.y
            self.length = length
        else:
            self.vector = flat(self.vector)

        from math import pi

        deg = self.roll * 180 / pi

        # Round to nearest 90 degrees.
        rounded = round(deg / 90) * 90
        self.roll = pi / 180 * rounded

    def world_align(self):
        """Orient this bone such that it exactly aligns with Blender's world axes."""
        self.tail.x = self.head.x
        self.tail.y = self.head.y + self.length
        self.tail.z = self.head.z
        self.roll = 0

    def roll_align_vector(self, vector: Vector, axis='+Z'):
        try:
            self.roll = calc_roll_to_align_axis(self, vector, axis)
        except ValueError:
            # This can happen when the vector we're trying to align with is perfectly aligned with the bone's length.
            self.owner_component.add_log(
                rpt_("Failed to Orient Bone"),
                trouble_bone=self.name,
                description=rpt_("The roll value of this bone could not be set to align with the desired vector."),
                display_stack_trace='ADVANCED',
            )

    def roll_align_other(self, other: BoneInfo, axis='+Z'):
        self.roll_align_vector(self.head+other.z_axis, axis=axis)

    def roll_flip(self):
        self.roll = wrap_angle_pi(self.roll+pi)

    @property
    def matrix(self) -> Matrix:
        matrix = Bone.MatrixFromAxisRoll(self.vector, self.roll).to_4x4()
        matrix = Matrix.Translation(self.head) @ matrix
        return matrix

    @property
    def x_axis(self) -> Vector:
        return self.matrix.to_3x3().col[0].normalized()

    @property
    def y_axis(self) -> Vector:
        return self.matrix.to_3x3().col[1].normalized()

    @property
    def z_axis(self) -> Vector:
        return self.matrix.to_3x3().col[2].normalized()

    @property
    def custom_shape_along_length(self):
        """Get custom widget display position as a factor along the bone's length."""
        if self.custom_shape_translation.y < 0.00001:
            return 0
        return self.custom_shape_translation.y / self.length

    @custom_shape_along_length.setter
    def custom_shape_along_length(self, value):
        """Set custom widget display position as a factor along the bone's length."""
        reference = self.custom_shape_transform or self
        self.custom_shape_translation.y = reference.length * value

    @property
    def custom_shape_name(self):
        return self._custom_shape_name

    @custom_shape_name.setter
    def custom_shape_name(self, value: str):
        self.custom_shape = None
        self._custom_shape_name = value

    def copy_custom_shape(self, other: BoneInfo | PoseBone):
        if not other.custom_shape:
            return
        if hasattr(other, 'custom_shape_name'):
            self.custom_shape_name = other.custom_shape_name
        self.custom_shape = other.custom_shape
        self.custom_shape_translation = other.custom_shape_translation
        self.custom_shape_rotation_euler = other.custom_shape_rotation_euler
        self.custom_shape_scale_xyz = other.custom_shape_scale_xyz
        self.use_custom_shape_bone_size = other.use_custom_shape_bone_size
        self.custom_shape_wire_width = other.custom_shape_wire_width

    def get_constraint(self, name: str) -> ConstraintInfo | None:
        for ci in self.constraint_infos:
            if ci.name == name:
                return ci

    def add_constraint(self, con_type: str, *, index: int = None, **kwargs) -> ConstraintInfo:
        """Store constraint information about a constraint in this BoneInfo.
        con_type: Type of constraint, eg. 'STRETCH_TO'.
        index: Where to insert constraint in the stack.
        kwargs: Constraint properties and values.
        """

        con_info = ConstraintInfo(self, con_type, **kwargs)
        if index is not None:
            self.constraint_infos.insert(index, con_info)
        else:
            self.constraint_infos.append(con_info)

        return con_info

    def add_constraint_from_real(self, constraint: Constraint) -> ConstraintInfo:
        kwargs = {}
        for prop in constraint.bl_rna.properties:
            if prop.is_readonly and prop.type!='COLLECTION':
                continue
            key = prop.identifier
            value = getattr(constraint, key)

            if constraint.type == 'ARMATURE' and key == 'targets':
                # TODO: Move this to @targets.setter
                kwargs['targets'] = [
                    {
                        'target': t.target,
                        'subtarget': t.subtarget,
                        'weight': t.weight,
                    } for t in constraint.targets
                ]
                continue
            elif (
                constraint.type == 'STRETCH_TO' and key == 'rest_length' and value == 0
            ):
                continue

            kwargs[key] = value
        new_con = ConstraintInfo(self, constraint.type, **kwargs)
        new_con.is_from_real = True
        self.constraint_infos.append(new_con)
        return new_con

    def clear_constraints(self):
        self.constraint_infos = []

    def write_edit_data(self, generator, edit_bone: EditBone):
        """Write relevant data of this BoneInfo into an EditBone."""
        if not self.preserve:
            return

        armature = generator.target_rig
        assert (
            armature.mode == 'EDIT'
        ), "Armature must be in Edit Mode when writing edit bone data."

        # Check for 0-length bones.
        if (self.head - self.tail).length == 0:
            self.bone_set.rig_component.add_log(
                rpt_("Zero-length bone"),
                trouble_bone=self.name,
                note=self.name,
                note_icon='BONE_DATA',
                description=rpt_('Bone "{bone}" had zero length. Its length was set to 1 to avoid a fatal error.').format(bone=self.name),
            )
            self.tail.y += 1
        assert (self.head - self.tail).length > 0, f'Bone "{edit_bone.name}" cannot be created with a length of 0.'


        ### Edit Bone properties
        for key in edit_bone_properties:
            value = getattr(self, key)
            if value == getattr(edit_bone, key):
                # For performance, don't write idenetical values.
                continue
            setattr(edit_bone, key, value)

        # Parenting - If an Armature Constraint is present, we automatically clear the parent.
        if any((con.type in ('ARMATURE', 'CHILD_OF') for con in self.constraint_infos)):
            self.parent = edit_bone.parent = None

        if self.parent:
            edit_bone.parent = armature.data.edit_bones.get(str(self.parent))
            if not edit_bone.parent:
                self.bone_set.rig_component.add_log(
                    rpt_("Parent not found"),
                    trouble_bone=self.name,
                    description=rpt_('Parent bone "{bone}" does not exist or is a child of this bone.').format(bone=self.parent),
                )

        # Custom Properties.
        for prop_name, prop in self.custom_props_edit.items():
            make_property(edit_bone, prop_name, **prop)

    def write_pose_data(self, context, metarig, pose_bone: PoseBone):
        """Write relevant data of this BoneInfo into a PoseBone."""
        if not self.preserve:
            return

        arm_ob = pose_bone.id_data

        assert (
            arm_ob.mode != 'EDIT'
        ), "Armature cannot be in Edit Mode when writing pose data"

        generator = self.owner_component.generator
        preserve_shapes = (generator.params.preserve_shapes_properties and generator.params.preserve_custom_shapes)
        if self.custom_shape_name and not preserve_shapes:
            self.custom_shape = self.owner_component.generator.ensure_widget(
                context, self.custom_shape_name
            )

        # Pose bone data
        for key in pose_bone_properties:
            if not hasattr(pose_bone, key):
                # This can happen when a new property is introduced in Blender, eg.
                # custom_shape_wire_width in 4.2.
                # Ignore such values in older versions, to preserve compatibility.
                continue
            if key in ("x_axis", "y_axis", "z_axis"):
                continue
            value = getattr(self, key)
            if value == getattr(pose_bone, key):
                # Don't write same values.
                continue
            if value in [None, ""]:
                continue
            if key == 'custom_shape_transform':
                name = naming.get_name(value)
                value = arm_ob.pose.bones.get(name)
            setattr(pose_bone, key, value)

        # Bone data
        bone = pose_bone.bone
        for key in bone_properties:
            if not hasattr(bone, key):
                # This can happen when a new property is introduced in Blender, eg.
                # custom_shape_wire_width in 4.2.
                # Ignore such values in older versions, to preserve compatibility.
                continue
            value = getattr(self, key)
            if value in [None, ""]:
                continue
            if 'bbone_custom_handle' in key:
                if hasattr(value, 'name'):
                    value = value.name
                value = arm_ob.data.bones.get(value)
            if key in ['x_axis', 'y_axis', 'z_axis']:
                # These area read-only, but I include them in bone_properties so they get read from real bones.
                continue
            if key == 'collections':
                for coll_name in value:
                    coll = arm_ob.data.collections_all.get(coll_name)
                    if coll:
                        coll.assign(pose_bone)
                    else:
                        # This can happen when there is a bone set collection without a collection name specified.
                        pass
                continue
            setattr(bone, key, value)

        # Bone colors
        bone.color.palette = self.color_palette_base
        pose_bone.color.palette = self.color_palette_pose

        # Convert theme colors to custom colors, so the rigger's theme colors
        # propagate to all users.
        # This is because we dropped support for custom colors expecting better
        # theme colors to drop in 4.0, but that didn't happen.
        if self.color_palette_base not in {'DEFAULT', 'CUSTOM'}:
            theme_color = context.preferences.themes[0].bone_color_sets[
                int(self.color_palette_base[-2:]) - 1
            ]
            self.color_palette_base = 'CUSTOM'
            bone.color.palette = 'CUSTOM'
            bone.color.custom.normal = theme_color.normal
            bone.color.custom.select = theme_color.select
            bone.color.custom.active = theme_color.active

        if bone.name.startswith("DEF") and not bone.use_deform:
            self.bone_set.rig_component.add_log(
                rpt_("Non-deforming DEF bone"),
                trouble_bone=self.name,
                description=rpt_('Bone name "{bone}" begins with "DEF" but Deform checkbox is not enabled. ' \
                            'This bone will not be keyframed by the "Whole Character" keying set!').format(bone=self.name),
                operator='object.cloudrig_rename_bone',
                op_kwargs={'old_name': bone.name},
            )

        pose_bone.hide = False

        def fixed_path(data_path):
            if not data_path.startswith("[") and not data_path.startswith("."):
                return "." + data_path
            return data_path

        def make_driver_safe(ob, *, target_id, **kwargs):
            try:
                make_driver(ob, target_id=target_id, **kwargs)
            except TypeError:
                if 'index' in kwargs:
                    del kwargs['index']
                try:
                    make_driver(ob, target_id=target_id, **kwargs)
                except Exception as e:
                    self.bone_set.rig_component.add_log(
                        rpt_("Failed to create Driver"),
                        trouble_bone=self.name,
                        description=str(e),
                    )

        # Constraints.
        for con_info in self.constraint_infos:
            con = con_info.make_real(pose_bone)
            for driver_info in con_info.drivers:
                driver_info['prop'] = (
                    f'pose.bones["{pose_bone.name}"].constraints["{con.name}"]{fixed_path(driver_info["prop"])}'
                )
                make_driver_safe(arm_ob, target_id=arm_ob, **driver_info)
            # Copied constraint drivers
            for data_path, array_index in con_info.drivers_to_copy:
                fcurve = metarig.animation_data.drivers.find(
                    data_path, index=array_index
                )
                if f'bones["{self.name}"]' not in data_path:
                    # If the bone's name has changed, fix it in the data path.
                    data_path = re.sub(
                        r'bones\[".*?"\]', f'bones["{self.name}"]', data_path
                    )
                if f'constraints["{con_info.name}"]' not in data_path:
                    # If the constraint's name has changed, fix it in the data path.
                    data_path = re.sub(
                        r'constraints\[".*?"\]', f'constraints["{con_info.name}"]', data_path
                    )

                copy_relink_real_driver(metarig, arm_ob, fcurve, data_path, array_index)

        # Custom Properties.
        for prop_name, prop in self.custom_props.items():
            ensure_custom_property(pose_bone, prop_name, **prop)

        # Pose Bone Drivers.
        for driver_info in self.drivers:
            driver_info['prop'] = (
                f'pose.bones["{pose_bone.name}"]{fixed_path(driver_info["prop"])}'
            )
            make_driver_safe(arm_ob, target_id=arm_ob, **driver_info)

        # Data Bone Drivers.
        for driver_info in self.drivers_data:
            driver_info['prop'] = (
                f'bones["{pose_bone.name}"]{fixed_path(driver_info["prop"])}'
            )
            make_driver_safe(arm_ob.data, target_id=arm_ob, **driver_info)

        # Copied drivers
        for data_path, array_index in self.drivers_to_copy:
            fcurve = metarig.animation_data.drivers.find(data_path, index=array_index)
            if self.name not in data_path:
                # If the bone's name has changed, fix it in the data path.
                data_path = re.sub(
                    r'bones\[".*?"\]', f'bones["{self.name}"]', data_path
                )
            copy_relink_real_driver(metarig, arm_ob, fcurve, data_path=data_path, index=array_index)

    def clone(self, new_name: str=None, bone_set: BoneSet=None) -> BoneInfo:
        """Return a clone of self."""
        if not new_name:
            new_name = naming.uniqify(
                self.name, list(self.owner_component.generator.bone_infos)
            )

        if not bone_set:
            bone_set = self.bone_set

        new_bone = bone_set.new(name=new_name)

        for key, value in self.__dict__.items():
            if key == 'name' or key.startswith("_"):
                continue
            value = getattr(self, key)
            if type(value) in [Vector, Matrix, dict]:
                setattr(new_bone, key, value.copy())
            elif type(value) in [list]:
                setattr(new_bone, key, value[:])
            else:
                setattr(new_bone, key, value)

        return new_bone

    def disown(self, new_parent):
        """Parent all children of this bone to a new parent."""
        for b in self.children:
            b.parent = new_parent

    def get_real(self, rig: Object) -> EditBone | PoseBone | None:
        """If a bone with the name of this BoneInfo exists in the passed rig,
        return it."""
        if rig.mode == 'EDIT':
            return rig.data.edit_bones.get(self.name)
        else:
            return rig.pose.bones.get(self.name)

    def __str__(self) -> str:
        return self.name


class ConstraintInfo(dict):
    """Abstracts away Blender's constraints, allowing less verbose ways to set properties,
    automatically remapping pointers to the metarig or None to the Target Rig,
    and with more commonly useful default values."""

    def __init__(
        self,
        bone_info,
        con_type,
        use_preferred_defaults=True,
        **kwargs,
    ):
        super(ConstraintInfo, self).__init__(**kwargs)
        # This is a cheeky hack to let us access our dict values as if
        # they were proper attributes.
        # https://stackoverflow.com/a/14620633/1527672
        self.__dict__ = self

        self.type = con_type
        self.bone_info = bone_info  # BoneInfo to which this constraint is being added.
        self.name = self.type.replace("_", " ").title()
        self.drivers = []

        # Data path & array index of drivers that should be copied from the metarig.
        # This supports keyframes and curve modifiers.
        self.drivers_to_copy: list[tuple[str, int]] = []

        # Whether this constraint was read from a real bpy.types.Constraint.
        self.is_from_real = False

        if use_preferred_defaults:
            self.set_preferred_defaults()

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.__dict__[key] = value

        # Allow @ symbols to specify subtargets.
        if '@' in self.name:
            split_name = self.name.split("@")
            subtargets = split_name[1:]
            targets = kwargs.get('targets', {})
            if self.type == 'ARMATURE':
                if len(subtargets) != len(targets):
                    self.bone_info.owner_component.raise_generation_error(
                        rpt_("Armature constraint using @ syntax specifies {count} names, " \
                        "but has {tar_count} targets. They must be equal.").format(count=len(subtargets), tar_count=len(targets)),
                        trouble_bone = self.bone_info.name
                    )
                self.targets = [
                    (targets[i]['target'], subtarget, targets[i]['weight'])
                    for i, subtarget in enumerate(split_name[1:])
                ]
            else:
                self.subtarget = split_name[1]

    @property
    def rig(self) -> Object:
        return self.bone_info.bone_set.rig_component.generator.target_rig

    @property
    def metarig(self) -> Object:
        return self.bone_info.bone_set.rig_component.generator.metarig

    @property
    def target(self) -> Object | None:
        target = self.get('target')
        if target in (None, self.metarig):
            self.target = self.rig
        return self.get('target')

    @target.setter
    def target(self, value: Object):
        if value == self.metarig:
            # Setting the metarig as a constraint target is not allowed!
            value = self.rig
        self['target'] = value

    @property
    def subtarget(self) -> str:
        if "@" not in self.name:
            return self.get('subtarget', "")

        split_name = self.name.split("@")
        return split_name[1]

    @subtarget.setter
    def subtarget(self, value):
        if value is None:
            value = ""
        elif type(value) is str:
            value = value
        elif hasattr(value, 'name'):
            value = value.name
        else:
            raise ValueError(f"Invalid value for 'subtarget': {value} of type {type(value)}")

        if self.type == 'ARMATURE':
            self.targets = [value]
            return

        self['subtarget'] = value

    @property
    def space_subtarget(self) -> str:
        return self.get('space_subtarget', '')

    @space_subtarget.setter
    def space_subtarget(self, value):
        if hasattr(value, 'name'):
            self['space_subtarget'] = value.name
        elif type(value) is str:
            self['space_subtarget'] = value
        else:
            raise ValueError(f"Invalid 'space_subtarget': {value}")

    @property
    def targets(self) -> list[dict]:
        # Only on Armature modifiers.
        # This should always return the same list, otherwise targets.append() won't work.
        return self['targets']

    @targets.setter
    def targets(self, value: list[dict|str]):
        """Allow a few different syntaxes, always coerce them to a dict."""
        _targets: list[dict] = []
        for tar in value:
            if type(tar) is str:
                _targets.append({'target': self.rig, 'subtarget': tar, 'weight': 1.0})
            elif type(tar) is tuple:
                targ_ob = next((t for t in tar if isinstance(t, Object)), None)
                subtarget = next((str(t) for t in tar if type(t) in (str, BoneInfo)), "")
                weight = next((t for t in tar if type(t) in (float, int)), 1.0)
                if len(tar) > 2:
                    weight = tar[2]
                _targets.append({'target': targ_ob, 'subtarget': subtarget, 'weight': weight})
            elif type(tar is dict):
                if tar.get('target') in (None, self.metarig):
                    tar['target'] = self.rig
                if type(tar.get('subtarget')) is not str:
                    tar['subtarget'] = str(tar.get('subtarget'))
                if 'weight' not in tar:
                    tar['weight'] = 1.0
                _targets.append(tar)
            else:
                raise ValueError(f"Invalid 'targets': {value}")

        for i, tar in enumerate(_targets):
            if tar['target'] in (self.metarig, None):
                _targets[i]['target'] = self.rig
        self['targets'] = _targets

    @property
    def use_min_xyz(self) -> tuple[bool, bool, bool]:
        return (
            self.get('use_min_x', False),
            self.get('use_min_y', False),
            self.get('use_min_z', False),
        )

    @use_min_xyz.setter
    def use_min_xyz(self, value: tuple[bool, bool, bool]):
        self['use_min_x'], self['use_min_y'], self['use_min_z'] = value

    @property
    def use_max_xyz(self) -> tuple[bool, bool, bool]:
        return (
            self.get('use_max_x', False),
            self.get('use_max_y', False),
            self.get('use_max_z', False),
        )

    @use_max_xyz.setter
    def use_max_xyz(self, value: tuple[bool, bool, bool]):
        self['use_max_x'], self['use_max_y'], self['use_max_z'] = value

    @property
    def use_xyz(self) -> tuple[bool, bool, bool]:
        return (
            self.get('use_x', False),
            self.get('use_y', False),
            self.get('use_z', False),
        )

    @use_xyz.setter
    def use_xyz(self, value: tuple[bool, bool, bool]):
        self['use_x'], self['use_y'], self['use_z'] = value

    @property
    def invert_xyz(self) -> tuple[bool, bool, bool]:
        return (
            self.get('invert_x', False),
            self.get('invert_y', False),
            self.get('invert_z', False),
        )

    @invert_xyz.setter
    def invert_xyz(self, value: tuple[bool, bool, bool]):
        self['invert_x'], self['invert_y'], self['invert_z'] = value

    @property
    def space_object(self) -> Object:
        return self.get('space_object', self.rig)

    @space_object.setter
    def space_object(self, value):
        if value == self.metarig:
            value = self.rig
        self['space_object'] = value

    @property
    def space(self) -> str:
        return self.get('owner_space', 'WORLD')

    @space.setter
    def space(self, value: str):
        self['owner_space'] = value
        self['target_space'] = value

    @property
    def head_tail(self) -> float:
        return self.get('head_tail', 0.0)

    @head_tail.setter
    def head_tail(self, value):
        self['use_bbone_shape'] = True
        self['head_tail'] = value

    def set_preferred_defaults(self):
        """Set some arbitrary preferred defaults, separately from __init__(),
        to keep this optional."""

        # Constraints that support local space should default to local space.
        default_local = [
            'COPY_LOCATION',
            'COPY_SCALE',
            'COPY_ROTATION',
            'COPY_TRANSFORMS',
            'LIMIT_LOCATION',
            'LIMIT_SCALE',
            'LIMIT_ROTATION',
            'ACTION',
            'TRANSFORM',
        ]
        if self.type in default_local:
            self.space = 'LOCAL'
        if self.type == 'TRANSFORM':
            self.mix_mode_scale = 'MULTIPLY'
            self.mix_mode_rot = 'BEFORE'
        if self.type == 'STRETCH_TO':
            self.use_bulge_min = True
            self.use_bulge_max = True
        elif self.type == 'LIMIT_SCALE':
            self.max_x = 1
            self.max_y = 1
            self.max_z = 1
            self.use_transform_limit = True
        elif self.type in ['LIMIT_LOCATION', 'LIMIT_ROTATION']:
            self.use_transform_limit = True
        elif self.type == 'IK':
            self.ik_chain_count = 2

    def make_real(self, pose_bone: PoseBone):
        """Create a constraint based on this ConstraintInfo on a given pose bone."""
        con = pose_bone.constraints.new(self.type)

        # Order sometimes matters, eg. some spaces aren't available until target is specified.
        order = [
            'target',
            'subtarget',
            'target_space',
            'owner_space',
        ]
        order_idx = {key:i for i, key in enumerate(order)}

        sorted_props = sorted(con.bl_rna.properties, key=lambda p: order_idx.get(p.identifier, len(order)))
        for prop in sorted_props:
            if prop.identifier == 'rest_length':
                con.rest_length = pose_bone.bone.length
                continue
            if prop.is_readonly and prop.type!='COLLECTION':
                continue
            if hasattr(self, prop.identifier):
                value = getattr(self, prop.identifier)
            elif prop.identifier in self:
                value = self[prop.identifier]
            else:
                # Nothing specified in the BoneInfo for this property, so leave it default.
                continue
            if prop.type == 'COLLECTION':
                # Somewhat generic solution for Armature constraint targets.
                coll = getattr(con, prop.identifier)
                for entry in value:
                    new = coll.new()
                    for k, v in entry.items():
                        setattr(new, k, v)
            else:
                try:
                    setattr(con, prop.identifier, value)
                except TypeError:
                    assert False, (
                        f"Cannot set value `{value}` on constraint '{self.name}' of bone '{self.bone_info.name}' " \
                        f"of type '{self.type}' for property '{prop.identifier}'"
                    )

        return con
