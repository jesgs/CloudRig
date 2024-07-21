import bpy, re
from bpy.types import EditBone, PoseBone, Constraint, Object, ID, FCurve

from mathutils import Vector, Matrix

from ..utils.maths import flat
from ..utils.external.mechanism import make_constraint, make_driver
from .properties_ui import ensure_custom_property, make_property

# These values should match Blender's defaults, otherwise they won't be written.
# It is very confusing what belongs where because some properties exist on both EditBone and Bone,
# but are kept in sync by Blender, whereas others (bbone shape properties) are deliberately NOT kept in sync.
edit_bone_properties = {
    'head': Vector((0, 0, 0)),
    'tail': Vector((0, 1, 0)),
    'roll': 0,
    'head_radius': 0.1,
    'tail_radius': 0.05,
    'use_connect': False,
    'bbone_curveinx': 0,
    'bbone_curveinz': 0,
    'bbone_rollin': 0,
    'bbone_rollout': 0,
    'bbone_curveoutx': 0,
    'bbone_curveoutz': 0,
    'bbone_easein': 1,
    'bbone_easeout': 1,
    'bbone_scalein': Vector((1, 1, 1)),
    'bbone_scaleout': Vector((1, 1, 1)),
    # These axis values are only read for original bones. Updating them after
    # changing roll or head/tail positions would require some serious maths
    # or some functions to be exposed from C.
    'x_axis': Vector(),
    'y_axis': Vector(),
    'z_axis': Vector(),
}

bone_properties = {
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
}


class BoneInfo:
    """
    The class tries to abstract bpy.types.Bone/PoseBone/EditBone.

    This class does not concern itself with posing the bone, only creating and
    rigging it. Eg, it does not store transformations such as loc/rot/scale.
    """

    def __init__(
        self,
        bone_set,
        name="Bone",
        source: EditBone or BoneInfo = None,
        owner_component=None,
        **kwargs,
    ):
        """
        source:    Bone to take transforms from (head, tail, roll, bbone_x, bbone_z).
        kwargs: Allow setting arbitrary bone properties at initialization.
        """

        self.bone_set = bone_set
        self.owner_component = owner_component
        self.create = True
        self.next = self.prev = None  # For LinkedList behaviour.
        self.gizmo_vgroup = ""  # For CloudRig Gizmos
        self.gizmo_operator = 'transform.translate'

        # {"name" : {kwargs}} where kwargs will be passed to make_property().
        self.custom_props = {}
        self.custom_props_edit = {}

        # List of dictionaries that will be passed to make_driver(). This is where we define drivers during rig generation.
        self.drivers = []
        # Same but for data bone properties.
        self.drivers_data = []

        # Data path & array index of drivers that should be copied from the metarig.
        # This supports keyframes and curve modifiers.
        self.drivers_to_copy: list[tuple[str, int]] = []

        self.color_palette_base = 'DEFAULT'
        self.color_palette_pose = 'DEFAULT'
        # List of ConstraintInfo objects. Their __dict__ will be passed to make_constraint().
        self.constraint_infos = []

        self._name = name
        self._parent = None
        self.children: list[BoneInfo] = []

        self.init_variables(edit_bone_properties)
        self.init_variables(bone_properties)
        self.init_variables(pose_bone_properties)
        # A better default.
        self.use_custom_shape_bone_size = False
        # Custom boolean for CloudRig, used by the generator.
        self.use_custom_shape_bbone_scaling = True

        ### Recalculate Roll
        # Whether the roll_bone or roll_vector should be used to calculate bone roll..
        self.roll_type = ""
        # If roll_type=='ALIGN', use this as the bone to align with. This is a BoneInfo instance or a string. This is equivalent to the "Active Bone" alignment in Blender.
        self.roll_bone = None
        # If roll_type=='VECTOR', use this as the vector that the Z axis should point towards. This is equivalent to "Align to Cursor" in Blender.
        self.roll_vector = Vector()

        self.custom_shape_name = ""
        self._source = self

        # If True, this bone won't be auto-parented to the root if it doesn't have a parent.
        self.ignore_orphan = False

        if source:
            self.head = source.head.copy()
            self.tail = source.tail.copy()
            self.roll = source.roll
            self.envelope_distance = source.envelope_distance
            self.envelope_weight = source.envelope_weight
            self.use_envelope_multiply = source.use_envelope_multiply
            self.head_radius = source.head_radius
            self.tail_radius = source.tail_radius
            if type(source) == type(self):
                self._source = source
                self.roll_type = source.roll_type
                self.roll_bone = source.roll_bone
                self.roll = source.roll
                self.bbone_width = source.bbone_width
                if source.parent:
                    self.parent = source.parent
            elif type(source) == EditBone:
                self.bbone_x = source.bbone_x
                self.bbone_z = source.bbone_z
                if source.parent:
                    self.parent = source.parent.name

        # Apply property values from arbitrary keyword arguments if any were passed.
        for key, value in kwargs.items():
            setattr(self, key, value)

    def init_variables(self, var_dict):
        for key in var_dict.keys():
            value = var_dict[key]
            if type(value) in [Vector, Matrix]:
                value = value.copy()
            setattr(self, key, value)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        new_name = value
        rig_component = self.bone_set.rig_component
        rig_ob = rig_component.target_rig
        bone = rig_ob.data.bones.get(self._name)
        if bone:
            bone.name = new_name
        self._name = new_name

    @property
    def source(self):
        """The source is the ORG bone that this BoneInfo was copied from, or
        this BoneInfo itself.
        """
        # Recursively get the source of each bone until getting to what should be an ORG bone.
        if self._source == self:
            return self
        return self._source.source

    @property
    def custom_shape_scale(self):
        return sum(self.custom_shape_scale_xyz) / 3

    @custom_shape_scale.setter
    def custom_shape_scale(self, value):
        self.custom_shape_scale_xyz = Vector((value, value, value))

    @property
    def parent(self):
        return self._parent

    @property
    def is_orphan(self):
        if self.parent:
            return False

        for con_info in self.constraint_infos:
            if con_info.type == 'ARMATURE':
                return False

        if self.ignore_orphan:
            return False

        return True

    @parent.setter
    def parent(self, value):
        if self.parent == value:
            return
        if self._parent and isinstance(self._parent, BoneInfo):
            self._parent.children.remove(self)
        self._parent = value
        if value and isinstance(value, BoneInfo):
            value.children.append(self)

        # If we want to use connected parenting, do it explicitly, after setting the parent.
        # Otherwise, this is a lot more intuitive, since otherwise changing the parent
        # of a connected bone will also move the bone, which is quite unexpected.
        self.use_connect = False

    @property
    def bbone_width(self):
        """Return average display size of both axes."""
        return (self.bbone_x + self.bbone_z) / 2

    @bbone_width.setter
    def bbone_width(self, value):
        """Set all bone size related values at once."""
        self.bbone_x = value
        self.bbone_z = value
        self.envelope_distance = value
        self.head_radius = value
        self.tail_radius = value

    @property
    def vector(self):
        """Vector pointing from head to tail."""
        return self.tail - self.head

    @vector.setter
    def vector(self, value: Vector):
        self.tail = self.head + value

    def scale_width(self, value: int):
        """Set b-bone width relative to current."""
        self.bbone_width *= value

    def scale_length(self, value: int):
        """Set bone length relative to its current length."""
        self.tail = self.head + self.vector * value

    @property
    def length(self):
        return (self.tail - self.head).length

    @length.setter
    def length(self, value):
        assert value > 0.0, f"{self.name}: Bone length cannot be 0!"
        self.tail = self.head + self.vector.normalized() * value

    @property
    def center(self):
        return self.head + self.vector / 2

    def reverse(self):
        """Flip the head and the tail."""  # NOTE: What to do with roll, if there is one?
        self.head, self.tail = self.tail, self.head

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

    @property
    def custom_shape_along_length(self):
        """Get custom widget display position as a factor along the bone's length."""
        if self.custom_shape_translation.y < 0.00001:
            return 0
        return self.custom_shape_translation.y / self.length

    @custom_shape_along_length.setter
    def custom_shape_along_length(self, value):
        """Set custom widget display position as a factor along the bone's length."""
        self.custom_shape_translation.y = self.length * value

    def copy_custom_shape(self, other):
        if not other.custom_shape:
            return
        self.custom_shape_name = other.custom_shape_name
        self.custom_shape = other.custom_shape
        self.custom_shape_translation = other.custom_shape_translation
        self.custom_shape_rotation_euler = other.custom_shape_rotation_euler
        self.custom_shape_scale_xyz = other.custom_shape_scale_xyz
        self.use_custom_shape_bone_size = other.use_custom_shape_bone_size
        self.use_custom_shape_bbone_scaling = False

    def get_constraint(self, name):
        for ci in self.constraint_infos:
            if ci.name == name:
                return ci

    def add_constraint(self, con_type: str, index: int = None, **kwargs):
        """Store constraint information about a constraint in this BoneInfo.
        con_type: Type of constraint, eg. 'STRETCH_TO'.
        kwargs: Dictionary of properties and values.
        true_defaults: When False, we use a set of arbitrary default values that
                I consider better than Blender's defaults.
        """

        con_info = ConstraintInfo(self, con_type, **kwargs)
        if index != None:
            self.constraint_infos.insert(index, con_info)
        else:
            self.constraint_infos.append(con_info)

        return con_info

    def add_constraint_from_real(self, constraint: Constraint):
        kwargs = {}
        skip = [
            'active',
            'bl_rna',
            'error_location',
            'error_rotation',
            'is_proxy_local',
            'is_valid',
            'rna_type',
            'type',
        ]
        for key in dir(constraint):
            if "__" in key:
                continue
            if key in skip:
                continue
            value = getattr(constraint, key)

            if constraint.type == 'ARMATURE' and key == 'targets':
                kwargs['targets'] = []
                for t in constraint.targets:
                    kwargs['targets'].append(
                        {
                            'target': t.target,
                            'subtarget': t.subtarget,
                            'weight': t.weight,
                        }
                    )
                continue
            elif (
                constraint.type == 'STRETCH_TO' and key == 'rest_length' and value == 0
            ):
                continue

            kwargs[key] = value
            # HACK: Why is subtarget handled differently than space_subtarget?? Commit message includes "quick fix" so this probably needs a cleanup.
            if key == 'space_subtarget':
                kwargs[key] = kwargs[key].replace("ORG-", "")
        new_con = ConstraintInfo(self, constraint.type, **kwargs)
        new_con.is_from_real = True
        self.constraint_infos.append(new_con)
        return new_con

    def clear_constraints(self):
        self.constraint_infos = []

    def relink(self):
        """Relinking a bone just means relinking its drivers, constraints and
        constraint drivers."""
        # Relink bone drivers
        for drv in self.drivers:
            self.bone_set.rig_component.relink_driver_info(drv)

        for con_inf in self.constraint_infos:
            con_inf.relink()
            # Relink constraint drivers
            for drv in con_inf.drivers:
                self.bone_set.rig_component.relink_driver_info(drv)

    def write_edit_data(self, generator, edit_bone: EditBone):
        """Write relevant data of this BoneInfo into an EditBone."""
        if not self.create:
            return

        armature = generator.target_rig
        assert (
            armature.mode == 'EDIT'
        ), "Armature must be in Edit Mode when writing edit bone data."

        # Check for 0-length bones.
        if (self.head - self.tail).length == 0:
            self.bone_set.rig_component.add_log(
                "Zero-length bone",
                trouble_bone=self.name,
                description=f'Bone "{self.name}" had zero length. Its length was set to 1 to avoid a fatal error.',
            )
            self.tail.y += 1
        assert (
            self.head - self.tail
        ).length > 0, f'Bone "{edit_bone.name}" cannot be created with a length of 0.'

        ### Edit Bone properties
        for key in edit_bone_properties:
            if not hasattr(edit_bone, key):
                # This can happen when a new property is introduced in Blender, eg.
                # custom_shape_wire_width in 4.2.
                # Ignore such values in older versions, to preserve compatibility.
                continue

            # Allow bbone properties to specify if they are only for EditBone
            key = key.replace("edit_", "")

            if key.endswith("_axis"):
                # Read-only, skip.
                continue

            value = self.__dict__[key]
            default_value = edit_bone_properties[key]
            if value == default_value:
                # For performance, don't write default values.
                continue
            setattr(edit_bone, key, value)

        scale = generator.scale
        edit_bone.bbone_x = self.bbone_width * scale
        edit_bone.bbone_z = self.bbone_width * scale
        edit_bone.envelope_distance = self.bbone_width * scale
        edit_bone.head_radius = self.bbone_width * scale
        edit_bone.tail_radius = self.bbone_width * scale

        # Parenting - If an Armature Constraint is present, don't allow double parenting.
        for con in self.constraint_infos:
            if con.type == 'ARMATURE':
                self.parent = None

        if self.parent:
            edit_bone.parent = armature.data.edit_bones.get(str(self.parent))
            if not edit_bone.parent:
                self.bone_set.rig_component.add_log(
                    "Parent not found",
                    trouble_bone=self.name,
                    description=f'Parent bone "{self.parent}" does not exist or is a child of this bone.',
                )

        # Custom Properties.
        for prop_name, prop in self.custom_props_edit.items():
            make_property(edit_bone, prop_name, **prop)

        # Recalculate roll.
        if self.roll_type != "":
            if self.roll_type == 'ALIGN':
                # NOTE: If you're looking at this code and wondering why your roll
                # is not aligned like it should be, it's probably because
                # `eb.roll += self.roll`` down below.
                # Make sure to set `self.roll = 0` if that's what you need.
                align_bone = armature.data.edit_bones.get(str(self.roll_bone))
                if not align_bone:
                    self.owner_component.raise_generation_error(
                        f"Could not find bone {self.roll_bone} to calculate roll of {edit_bone.name}."
                    )
                else:
                    edit_bone.align_roll(align_bone.z_axis)
            elif self.roll_type == 'VECTOR':
                edit_bone.align_roll(self.roll_vector)

            edit_bone.roll += self.roll

    def write_pose_data(self, context, metarig, pose_bone: PoseBone):
        """Write relevant data of this BoneInfo into a PoseBone."""
        if not self.create:
            return

        arm_ob = pose_bone.id_data

        assert (
            arm_ob.mode != 'EDIT'
        ), "Armature cannot be in Edit Mode when writing pose data"

        if self.custom_shape_name:
            self.custom_shape = self.owner_component.generator.ensure_widget(
                context, self.custom_shape_name
            )

        # Pose bone data
        for key in pose_bone_properties:
            key = key.replace(
                "pose_", ""
            )  # Allows bbone properties to specify if they are only for pose bone version
            if not hasattr(pose_bone, key):
                # This can happen when a new property is introduced in Blender, eg.
                # custom_shape_wire_width in 4.2.
                # Ignore such values in older versions, to preserve compatibility.
                continue
            value = self.__dict__[key]
            default_value = pose_bone_properties[key]
            if value == default_value:
                # For performance, don't write default values.
                continue
            if value in [None, ""]:
                continue
            if key == 'custom_shape_transform':
                name = self.owner_component.naming.get_name(value)
                value = arm_ob.pose.bones.get(name)
            setattr(pose_bone, key, value)

        if (
            not pose_bone.use_custom_shape_bone_size
            and self.use_custom_shape_bbone_scaling
        ):
            pose_bone.custom_shape_scale_xyz *= (
                self.bbone_width * 10 * self.bone_set.rig_component.generator.scale
            )

        # Bone data
        bone = pose_bone.bone
        for key in bone_properties:
            if not hasattr(bone, key):
                # This can happen when a new property is introduced in Blender, eg.
                # custom_shape_wire_width in 4.2.
                # Ignore such values in older versions, to preserve compatibility.
                continue
            value = self.__dict__[key]
            if value in [None, ""]:
                continue
            if 'bbone_custom_handle' in key:
                if hasattr(value, 'name'):
                    value = value.name
                value = arm_ob.data.bones.get(value)
            if key in ['bbone_x', 'bbone_z']:
                # TODO: To write bone shape scale data properly, we would need a reference to the generator.scale.
                # This would best be done if this function was in the generator rather than BoneInfo.
                continue
            if key == 'collections':
                for coll_name in value:
                    coll = arm_ob.data.collections_all.get(coll_name)
                    coll.assign(pose_bone)
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
                "Non-deforming DEF bone",
                trouble_bone=self.name,
                description=f'Bone name "{self.name}" begins with "DEF" but Deform checkbox is not enabled. This bone will not be keyframed by the "Whole Character" keying set!',
                operator='object.cloudrig_rename_bone',
                op_kwargs={'old_name': bone.name},
            )

        def fixed_path(data_path):
            if not data_path.startswith("[") and not data_path.startswith("."):
                return "." + data_path
            return data_path

        def make_driver_safe(ob, *, target_id, **kwargs):
            try:
                make_driver(ob, target_id=target_id, **kwargs)
            except:
                if 'index' in kwargs:
                    del kwargs['index']
                try:
                    make_driver(ob, target_id=target_id, **kwargs)
                except Exception as e:
                    self.bone_set.rig_component.add_log(
                        "Failed to create Driver",
                        trouble_bone=self.name,
                        description=str(e),
                    )

        # Constraints.
        for ci in self.constraint_infos:
            con = ci.make_real(pose_bone)
            for driver_info in ci.drivers:
                driver_info['prop'] = (
                    f'pose.bones["{pose_bone.name}"].constraints["{con.name}"]{fixed_path(driver_info["prop"])}'
                )
                make_driver_safe(arm_ob, target_id=arm_ob, **driver_info)
            # Copied constraint drivers
            for data_path, array_index in ci.drivers_to_copy:
                fcurve = metarig.animation_data.drivers.find(
                    data_path, index=array_index
                )
                if self.name not in data_path:
                    # If the bone's name has changed, fix it in the data path.
                    data_path = re.sub(
                        r'bones\[".*?"\]', f'bones["{self.name}"]', data_path
                    )
                if ci.name not in data_path:
                    # If the constraint's name has changed, fix it in the data path.
                    data_path = re.sub(
                        r'constraints\[".*?"\]', f'constraints["{ci.name}"]', data_path
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
            copy_relink_real_driver(metarig, arm_ob, fcurve)

    def clone(self, new_name=None, bone_set=None):
        """Return a clone of self."""
        if not new_name:
            new_name = self.owner_component.naming.uniqify(
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

    def get_real(self, rig: Object):
        """If a bone with the name of this BoneInfo exists in the passed rig,
        return it."""
        if rig.mode == 'EDIT':
            return rig.data.edit_bones.get(self.name)
        else:
            return rig.pose.bones.get(self.name)

    def __str__(self):
        return self.name


class ConstraintInfo(dict):
    """Helper class to store and manage constraint info before it's passed to
    make_constraint()."""

    def __init__(
        self,
        bone_info,
        con_type,
        target=None,
        use_preferred_defaults=True,
        use_min_xyz=[],
        use_max_xyz=[],
        **kwargs,
    ):
        # Blame this guy https://stackoverflow.com/a/14620633/1527672
        super(ConstraintInfo, self).__init__(**kwargs)
        self.__dict__ = self

        self.type = con_type
        self.bone_info = bone_info  # BoneInfo to which this constraint is being added.
        self.target = target
        if con_type == 'ARMATURE':
            self.targets = [{'target': target, 'subtarget': "", 'weight': 1.0}]
        self.name = self.type.replace("_", " ").title()
        self.drivers = []

        if use_min_xyz:
            if type(use_min_xyz) == bool:
                use_min_xyz = [use_min_xyz] * 3
                self.use_min_x, self.use_min_y, self.use_min_z = use_min_xyz
        if use_max_xyz:
            if type(use_max_xyz) == bool:
                use_max_xyz = [use_max_xyz] * 3
                self.use_max_x, self.use_max_y, self.use_max_z = use_max_xyz

        # Data path & array index of drivers that should be copied from the metarig.
        # This supports keyframes and curve modifiers.
        self.drivers_to_copy: list[tuple[str, int]] = []

        self.is_from_real = (
            False  # Whether this constraint was read from a real bpy.types.Constraint.
        )

        if use_preferred_defaults:
            self.set_preferred_defaults()

        for key, value in kwargs.items():
            self.__dict__[key] = value

    def set_preferred_defaults(self):
        """Set some arbitrary preferred defaults, separately from __init__(),
        to keep this optional."""

        # Set target as the rig object, except for some constraint types.
        if self.type not in [
            'SPLINE_IK',
            'LIMIT_LOCATION',
            'LIMIT_SCALE',
            'LIMIT_ROTATION',
            'SHRINKWRAP',
        ]:
            if hasattr(self.bone_info, 'rig') and self.target in [
                None,
                self.bone_info.owner_component.generator.metarig,
            ]:
                self.target = self.bone_info.bone_set.rig_component.target_rig

        # Constraints that support local space should default to local space.
        support_local = [
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
        if not hasattr(self, 'space') and self.type in support_local:
            self.space = 'LOCAL'

        if self.type == 'TRANSFORM':
            self.mix_mode_scale = 'MULTIPLY'
            self.mix_mode_rot = 'BEFORE'
        if self.type == 'STRETCH_TO':
            self.use_bulge_min = True
            self.use_bulge_max = True
            self.rest_length = self.bone_info.length
        elif self.type in ['COPY_LOCATION', 'COPY_SCALE']:
            self.use_offset = self.space != 'WORLD'
        elif self.type == 'COPY_ROTATION':
            if self.space != 'WORLD':
                self.mix_mode = 'BEFORE'
                self.use_offset = True
        elif self.type in ['COPY_TRANSFORMS', 'ACTION']:
            if self.space not in {'WORLD', 'POSE'}:
                self.mix_mode = 'BEFORE'
        elif self.type == 'LIMIT_SCALE':
            self.max_x = 1
            self.max_y = 1
            self.max_z = 1
            self.use_transform_limit = True
        elif self.type in ['LIMIT_LOCATION', 'LIMIT_ROTATION']:
            self.use_transform_limit = True
        elif self.type == 'IK':
            self.chain_count = 2

    def relink(self):
        """Allow the naming convention of an @ symbol separating
        the constraint name from a list of subtargets separated by commas."""

        rig_component = self.bone_info.bone_set.rig_component
        rig = rig_component.target_rig
        metarig = rig_component.generator.metarig

        if "@" not in self.name:
            if self.type == 'ARMATURE':
                for i, t in enumerate(self.targets):
                    if 'target' not in self.targets[i] or not self.targets[i]['target']:
                        t['target'] = rig
                    elif t['target'] == metarig:
                        t['target'] = rig

            return

        split_name = self.name.split("@")
        subtargets = split_name[1:]
        self.name = split_name[0]

        if self.type == 'ARMATURE':
            if len(self.targets) > len(subtargets):
                self.bone_info.owner_component.add_log(
                    "Relinking failed",
                    trouble_bone=self.bone_info.name,
                    description=f'Failed to relink constraint due to too many targets in constraint "{self.name}".\n Remove unneeded targets from the Armature constraint!',
                )
                return

            for i, t in enumerate(self.targets):
                t['subtarget'] = subtargets[i]
                if not t['target']:
                    t['target'] = rig
                if t['target'] == metarig:
                    t['target'] = rig
            return

        if len(subtargets) > 0:
            self.subtarget = subtargets[0]

    def make_real(self, pose_bone):
        """Create a constraint based on this ConstraintInfo on a given pose bone."""
        con_info = self.__dict__.copy()
        for key in [
            'type',
            'bone_info',
            'drivers',
            'drivers_to_copy',
            'is_from_real',
            'is_override_data',
        ]:
            if key in con_info:
                del con_info[key]

        # List of ID + string tuples that define a constraint target.
        # The string is an optional "subtarget" (bone or vgroup name)
        target_pairs: list[tuple[ID, str]] = []
        if 'targets' in con_info:
            for target_info in con_info['targets']:
                assert (
                    'subtarget' in target_info
                ), f"Armature constraint with no subtarget: {pose_bone.name}"
                if 'target' not in target_info:
                    # Allow omitting target object from Armature contraint targets.
                    target_info['target'] = pose_bone.id_data
                if hasattr(target_info['subtarget'], 'name'):
                    # Allow using BoneInfo instances, convert them to string here.
                    target_info['subtarget'] = target_info['subtarget'].name
                if target_info['subtarget'] == None:
                    # Replace None with empty string, otherwise make_constraint() throws error.
                    target_info['subtarget'] = ''
            target_pairs = [
                (t['target'], str(t['subtarget'])) for t in con_info['targets']
            ]
        elif 'target' in con_info:
            target_pairs = [[con_info['target'], ""]]

        if 'subtarget' in con_info:
            if hasattr(con_info['subtarget'], 'name'):
                # Allow using BoneInfo instances, convert them to string here.
                con_info['subtarget'] = con_info['subtarget'].name

            # Singular target, target object is optional, assumed to be the rig.
            target = target_pairs[0][0]
            if not target:
                target = pose_bone.id_data
            target_pairs = [(target, con_info['subtarget'])]

        for target_pair in target_pairs:
            target, subtarget = target_pair
            if (target and target.type == 'ARMATURE') and (
                subtarget not in target.data.bones
            ):
                self.bone_info.owner_component.add_log(
                    "Invalid constraint target!",
                    base_bone_name=self.bone_info.name,
                    trouble_bone=subtarget,
                    description=f'Constraint "{self.name}" on bone "{self.bone_info}" has non-existent target bone "{subtarget}".',
                )

        con = make_constraint(pose_bone, self.type, **con_info)

        return con


def copy_relink_real_driver(
    metarig, rig, fcurve, data_path: str = None, index: int = None
):
    """Copy a real driver to the target rig.
    Replace references to the metarig with the generated rig.
    May copy to a different data path than the source.
    """
    copy_driver(fcurve, rig, data_path, index)
    for var in fcurve.driver.variables:
        for tgt in var.targets:
            if tgt.id == metarig:
                tgt.id = rig


def copy_driver(
    from_fcurve: FCurve, target: ID, data_path: str = None, index: int = None
) -> FCurve:
    """Copy an existing FCurve containing a driver to a new ID, by creating a copy
    of the existing driver on the target ID.

    Args:
        from_fcurve: FCurve containing a driver
        target: ID that can have AnimationData
        data_path: Data Path of new driver. Defaults to copying the passed fcurve
        index: array index of the property to drive. Defaults to copying the passed fcurve

    Returns:
        FCurve: Fcurve with new driver on target ID
    """

    # Ensure anim data.
    if not target.animation_data:
        target.animation_data_create()

    # Remove old driver if it exists.
    tgt_drivers = target.animation_data.drivers
    if not data_path:
        data_path = from_fcurve.data_path
    if index not in {-1, None}:
        old_fcurve = tgt_drivers.find(data_path, index=index)
    else:
        old_fcurve = tgt_drivers.find(data_path)

    if old_fcurve:
        tgt_drivers.remove(old_fcurve)

    new_fcurve = tgt_drivers.from_existing(src_driver=from_fcurve)
    new_fcurve.data_path = data_path
    if index not in {None, -1}:
        new_fcurve.array_index = index

    return new_fcurve
