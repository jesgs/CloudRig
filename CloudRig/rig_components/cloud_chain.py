# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from ..rig_component_features.bone_set import BoneSet
from ..rig_component_features.overlay_painter import no_overlay
from ..utils.maths import lerp
from .cloud_base import Component_Base


class Component_ToonChain(Component_Base):
    """Chain with cartoony squash and stretch controls."""

    ui_name = "Chain: Toon"

    relink_default_prefix = "STR"

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.is_cyclic = False
        self.chain_length = 0

        # Other components may want to access some bones, so we store them.
        self.main_str_bones: list[BoneInfo]
        self.str_chain: list[BoneInfo]
        self.tangent_helpers: list[BoneInfo]

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        self.is_cyclic = self.toon__is_cyclic()

        # Calculate total bone length
        self.chain_length = sum([bone.length for bone in self.bones_org])

        # Create Main STR controls
        self.main_str_bones = self.__make_main_str_bones(self.bones_org)

        # Create Sub STR controls, in-between the Main ones.
        # They are organized into a list of (main, [sub1, sub2...]) tuples.
        str_sections = self.__make_sub_str_sections(self.main_str_bones, self.bones_org)

        # Build a straight chain of STR bones that contains both main and sub
        # bones in order.
        self.str_chain = self.__sort_str_sections(str_sections, self.is_cyclic)

        # for str_bone in self.str_chain:
        # It would be nice to prevent STR bones from being scaled negatively, but it can't be done.
        #     str_bone.add_constraint('LIMIT_SCALE', use_max_xyz=False, use_min_xyz=True)

        self.tangent_helpers = []
        if self.params.chain.bbone_density > 0 and self.params.chain.smooth_spline:
            # Create tangent helpers that will control bendy bone curvature
            self.tangent_helpers = self.__make_tangent_helpers(self.str_chain)

        self.toon__make_def_chain(str_chain=self.str_chain)

        self.__connect_parent_component()

    def base__relink_single(self, org_idx, con_info):
        to_bone = self.base__relink_get_target(org_idx, con_info)
        org_bi = self.bones_org[org_idx]

        parent_helpers = [str_bone.parent_helper for str_bone in self.main_str_bones if str_bone.parent_helper]
        if  con_info.type == 'ARMATURE':
            if to_bone in self.main_str_bones and 'NOHLP' not in con_info.name:
                to_bone = to_bone.parent_helper

        if to_bone in parent_helpers and con_info.type == 'ARMATURE':
            # If user is adding an Armature constraint to the parent helper (which will already have one),
            # their intent is probably to replace it.
            to_bone.constraint_infos[0] = con_info
            org_bi.constraint_infos.remove(con_info)
        else:
            return super().base__relink_single(org_idx, con_info)

    def base__relink_get_target(self, org_i: int, con_info: ConstraintInfo) -> BoneInfo:
        """Return the bone to which a constraint should be moved to."""
        if con_info.name.startswith('TAIL-'):
            org_bone = self.bones_org[org_i]
            if len(self.main_str_bones) <= org_i + 1:
                # Since the TAIL- instruction is very explicit, if it fails, let's throw a hard error.
                self.raise_generation_error(rpt_(
                        'Cannot move constraint "{constraint}" from "{bone}" to final STR bone since ' \
                        'it does not exist! Make sure "Tip Control" param is enabled!'
                    ).format(constraint=con_info.name, bone=org_bone.name)
                )
            return self.main_str_bones[org_i + 1]
        elif (type(self).relink_default_prefix=="STR" and "-" not in con_info.name) or con_info.name.startswith("STR-"):
            # This is necessary because the main STR bones have an _1 suffix, so the name matching in the super() function fails.
            return self.main_str_bones[org_i]
        else:
            return super().base__relink_get_target(org_i, con_info)

    ##############################
    # Toon chain functions.

    def toon__is_cyclic(self) -> bool:
        """Return whether this component should become a cyclic chain rig.
        This is the case when the last bone's tail touches the first bone's head.
        This is not a cyclic dependency because each control only affects its neighbours,
        not the whole chain. This feature is not supported by FK chains, where that is no longer true.
        """
        if self.params.chain.tip_control:
            return False
        THRESHOLD = 0.001
        distance = self.bones_org[-1].tail - self.bones_org[0].head
        is_cyclic = distance.length < THRESHOLD
        if is_cyclic:
            # Make the LinkedList behaviour of the Original Bones BoneSet act like a loop.
            self.bones_org[0].prev = self.bones_org[-1]
            self.bones_org[-1].next = self.bones_org[0]
        return is_cyclic

    def __sort_str_sections(
        self, str_sections: list[tuple[BoneInfo, list[BoneInfo]]], is_cyclic: bool
    ) -> list[BoneInfo]:
        """Sort the main and sub STR bones into a chain, so each one knows
        which one comes before and after it."""
        str_chain = []
        for section in str_sections:
            str_chain.append(section[0])
            str_chain.extend(section[1])

        for i, str_bone in enumerate(str_chain[1:]):
            str_chain[i].next = str_bone
            str_bone.prev = str_chain[i]

        str_chain[0].prev = None
        str_chain[-1].next = None

        if is_cyclic:
            str_chain[-1].next = str_chain[0]
            str_chain[0].prev = str_chain[-1]

        return str_chain

    def __make_main_str_bones(self, org_chain: BoneSet) -> list[BoneInfo]:
        """Create the main stretch controls:
        One for each ORG bone, plus optionally one more at the end of the chain."""
        main_str_bones = []

        for org_bone in org_chain:
            main_str_bone = self.toon__make_main_str_bone(org_bone)
            main_str_bones.append(main_str_bone)

        if self.params.chain.tip_control:
            main_str_bones.append(self.toon__make_main_str_bone(org_bone, at_tip=True))

        return main_str_bones

    def toon__make_main_str_bone(
        self, org_bone: BoneInfo, at_tip=False
    ) -> BoneInfo:
        """Create and return a main STR control."""
        segments = self.params.chain.segments
        direction = org_bone.vector
        if org_bone.prev:
            # Make bone parallel to line from previous bone's head to current bone's tail.
            direction = (org_bone.tail - org_bone.prev.head).normalized()

        str_name = self.naming.add_prefix(org_bone, 'STR')

        # Add a 1 at the end unless there's only 1 segment.
        num_segments = self.toon__get_num_segments_of_section(org_bone)
        if at_tip:
            str_name = self.naming.increment_name(str_name)
        if num_segments > 1:
            str_name = self.naming.suffix_base_name(str_name, "_1")
        while self.generator.find_bone_info(str_name):
            str_name = self.naming.increment_name(str_name)
        size = sum((abs(s) for s in org_bone.custom_shape_scale_xyz))/3 * org_bone.length * self.params.chain.shape_size
        main_str = self.bone_sets['Stretch Controls'].new(
            name=str_name,
            source=org_bone,
            vector=direction,
            length=org_bone.length / segments / 3,
            use_custom_shape_bone_size = False,
            custom_shape_translation=Vector((0, 0, 0)),
            custom_shape_rotation_euler=Vector((0, 0, 0)),
            custom_shape_scale_xyz=Vector([size]*3),
            parent=org_bone,
        )
        if at_tip:
            main_str.put(org_bone.tail, length=main_str.length)
            main_str.custom_shape_scale_xyz *= -1

        if not self.is_cyclic and org_bone == self.bones_org[0] or at_tip:
            main_str.custom_shape_name = self.params.chain.shape_stretch_ends.shape_name
            main_str.custom_shape_scale_xyz.y *= -1
        else:
            main_str.custom_shape_name = self.params.chain.shape_stretch.shape_name
        main_str.roll_align_other(org_bone)

        if self.params.chain.bbone_density > 0:
            parent_helper = self.create_parent_bone(main_str, bone_set=self.bones_mch)
            parent_helper.add_constraint('ARMATURE', subtarget=parent_helper.parent)
            parent_helper.parent = None

        return main_str

    def toon__get_num_segments_of_section(self, org_bone: BoneInfo) -> int:
        """
        Return how many deform bones should be created for a given org_bone.
        Child classes override this.
        """
        if org_bone == self.bones_org[-1] and not self.params.chain.tip_control:
            return 1
        return self.params.chain.segments

    def __make_sub_str_sections(
        self, main_str_bones: list[BoneInfo], org_chain: BoneSet
    ) -> list[tuple[BoneInfo, list[BoneInfo]]]:
        """Create sub-STR controls inbetween the main ones.
        Return a list of (main STR, [sub STRs]) tuples.
        """

        # Storage for sections of sub-STR bones. This is a list of tuples where
        # the first element is a main STR bone, and the 2nd element is a list of its sub-STR bones.
        sections = [[main_str, []] for main_str in main_str_bones]

        num_sections = len(main_str_bones) - 1
        if self.is_cyclic:
            num_sections += 1

        for idx in range(num_sections):
            org_bone = org_chain[idx]
            main_start = main_str_bones[idx]

            end_idx = idx + 1
            if idx == len(main_str_bones) - 1 and self.is_cyclic:
                # The end STR of the last section of a cyclic chain is the first STR.
                end_idx = 0
            main_end = main_str_bones[end_idx]

            section = self.__make_sub_str_section(org_bone, main_start, main_end)
            sections[idx][1] = section
            main_start.sub_bones = section

        return sections

    def __make_sub_str_section(
        self, org_bone: BoneInfo, main_start: BoneInfo, main_end: BoneInfo
    ) -> list[BoneInfo]:
        """Create sub-STR controls using two others as anchor points."""

        num_segments = self.toon__get_num_segments_of_section(org_bone)

        section = []
        for idx in range(num_segments - 1):
            section.append(
                self.__make_sub_str_bone(
                    org_bone, main_start, main_end, num_segments, idx + 1
                )
            )
        return section

    def __make_sub_str_bone(
        self,
        org_bone: BoneInfo,
        main_start: BoneInfo,
        main_end: BoneInfo,
        num_segments: int,
        index: int,
    ) -> BoneInfo:
        # Add the index after the base name
        prefix, base, suffix, zeroes = self.naming.get_name_parts(main_start.name)
        base = base[:-1] + str(index + 1)
        sub_str_name = prefix+base+suffix+zeroes

        vector = main_end.head - main_start.head
        unit = vector / num_segments

        influence_unit = 1 / num_segments
        factor = index * influence_unit

        sub_str = self.bone_sets['Stretch Controls'].new(
            name=sub_str_name,
            source=org_bone,
            parent=org_bone,
            head=main_start.head + (unit * index),
            length=vector.length / num_segments / 2,
            custom_shape_name=self.params.chain.shape_stretch.shape_name,
            custom_shape_scale_xyz = Vector((1, 1, 1)),
            custom_shape_scale=lerp(main_start.custom_shape_scale, main_end.custom_shape_scale, factor)*0.75,
            custom_shape_translation=Vector((0, 0, 0)),
            custom_shape_rotation_euler=Vector((0, 0, 0)),
            use_custom_shape_bone_size=False,
            inherit_scale='AVERAGE',
        )
        sub_str.parent = self.__make_sub_str_helper(
            sub_str, main_start, main_end, factor
        )

        return sub_str

    @no_overlay
    def __make_sub_str_helper(
        self,
        sub_str: BoneInfo,
        main_start: BoneInfo,
        main_end: BoneInfo,
        factor: float,
    ) -> BoneInfo:
        """Create STR-H bones that keep STR controls between two main STR controls."""
        str_h_bone = self.bone_sets['Stretch Helpers'].new(
            name=sub_str.name.replace("STR-", "STR-H-"),
            source=sub_str,
            bbone_width=sub_str.bbone_width,
            # We want no parent for scale inheritance reasons: The driver on the bendy bone
            # scale values expects to find all parenting-induced transformations in the local
            # matrix of this bone.
            parent=None,
            ignore_orphan=True,
        )
        sub_str.parent = str_h_bone

        self.constrain_between_bones(str_h_bone, main_start, main_end, factor)
        str_h_bone.add_constraint(
            'LIMIT_SCALE',
            name="Limit Scale: Ignore Y (BBone Easing)",
            use_min_y=True,
            use_max_x=False,
            use_max_y=True,
            use_max_z=False,
        )
        return str_h_bone

    @no_overlay
    def __make_tangent_helpers(self, str_chain: list[BoneInfo]) -> list[BoneInfo]:
        """Create tangent helpers for each STR bone."""
        tangent_helpers = []

        for i, str_bone in enumerate(str_chain):
            str_bone.tangent_helper = self.__make_tangent_helper(  # TODO: remove satanic reference if at all possible (probably won't be possible in cloud_face_chain though)
                str_bone=str_bone,
                prev_str=str_bone.prev or str_bone,
                next_str=str_bone.next or str_bone,
            )
            tangent_helpers.append(str_bone.tangent_helper)

        return tangent_helpers

    def __make_tangent_helper(
        self,
        str_bone: BoneInfo,
        prev_str: BoneInfo = None,
        next_str: BoneInfo = None,
    ) -> BoneInfo:
        """Create a child bone for an STR bone with Damped Track constraints
        to aim at the previous and next STR bones if Smooth Curve is enabled."""
        handle_bone = self.bone_sets['Stretch Helpers'].new(
            name=str_bone.name.replace("STR-", "STR-TAN-"),
            source=str_bone,
            parent=str_bone.parent,  # For main STR bones the parent is the ORG bone. For sub STR bones it's the STR-H bone.
            length=str_bone.length * 0.2,
            bbone_width = str_bone.bbone_width * 1.5,
        )

        assert (
            prev_str and next_str
        ), "Previous and next STR are required."

        handle_bone.add_constraint(
            'COPY_LOCATION',
            name="Copy Location (Smooth Spline)",
            subtarget=str_bone.name,
            space='WORLD',
        )
        handle_bone.add_constraint(
            'DAMPED_TRACK',
            name="Damped Track Prev (Smooth Spline)",
            subtarget=prev_str.name,
            track_axis='TRACK_NEGATIVE_Y',
            influence=1.0,
        )
        handle_bone.add_constraint(
            'DAMPED_TRACK',
            name="Damped Track Next (Smooth Spline)",
            subtarget=next_str.name,
            track_axis='TRACK_Y',
            influence=0.5,
        )

        handle_bone.add_constraint(
            'COPY_TRANSFORMS',
            name="Copy STR Transforms (Smooth Spline)",
            subtarget=str_bone.name,
            target_space='LOCAL_OWNER_ORIENT',
            mix_mode='AFTER',
        )
        handle_bone.add_constraint(
            'COPY_LOCATION',
            name="Copy Location For Display (Smooth Spline)",
            subtarget=str_bone.name,
            space='WORLD',
        )
        str_bone.custom_shape_transform = handle_bone

        handle_bone.add_constraint(
            'COPY_SCALE',
            name="Copy Scale (Smooth Spline)",
            subtarget=str_bone.name,
            space='POSE',
            use_offset=False,
        )

        return handle_bone

    @no_overlay
    def toon__make_def_chain(self, str_chain: list[BoneInfo]) -> list[BoneInfo]:
        """Create a deform chain stretching from one STR bone to the next."""

        # For each STR control, create a deform bone between it and the next one.
        next_parent = str_chain[0].parent
        for i, str_bone in enumerate(str_chain):
            is_tip_str = self.params.chain.tip_control and i == len(str_chain) - 1
            if is_tip_str:
                # Don't create a deform bone for tip STR control.
                continue
            org_bone = str_bone.source
            if not str_bone.next:
                # This happens for the last deform bone when tip_control=False.
                # In this case, the deform bone should just match the metarig bone.
                tail = org_bone.tail
            else:
                tail = str_bone.next.head

            head = str_bone.head
            bbone_width = (head-tail).length/10
            bbone_x, bbone_z = bbone_width, bbone_width
            if org_bone.display_type == 'BBONE' or (org_bone.display_type=='ARMATURE_DEFINED' and self.metarig.data.display_type == 'BBONE'):
                bbone_x, bbone_z = org_bone.bbone_x, org_bone.bbone_z

            def_bone = self.bones_def.new(
                name=str_bone.name.replace("STR", "DEF"),
                source=org_bone,
                parent=next_parent,
                head=head,
                tail=tail,
                use_deform=True,
                inherit_scale='NONE',
                bbone_x=bbone_x,
                bbone_z=bbone_z,
            )
            next_parent = def_bone
            if i == 0:
                # The deform chain is parented to each other, but that means the
                # first DEF bone needs to follow the first stretch bone.
                # Using CopyLoc doesn't work with Create Deform Bones,
                # since then the DEF bone doesn't follow DEF-CTR.
                # So, we just parent it.
                def_bone.parent = str_bone

            if self.params.chain.unlock_deform:
                self.__make_def_control(str_bone, def_bone)

            if i == len(str_chain) - 1 and not self.is_cyclic:
                # The last deform bone when there's no STR control at the tip of the chain
                # can skip the __setup_def_bone() phase, but needs some special treatment.
                def_bone.tail = org_bone.tail
                def_bone.parent = str_bone
                continue

            self.__setup_def_bone(
                def_bone=def_bone, org_bone=org_bone, str_bone=str_bone
            )

        return self.bones_def

    @no_overlay
    def __setup_def_bone(
        self,
        def_bone: BoneInfo,
        org_bone: BoneInfo,
        str_bone: BoneInfo,
        next_str_bone: BoneInfo = None,
    ):
        """Configure BBone setup for def_bone."""

        if not next_str_bone:
            next_str_bone = str_bone.next

        if self.params.chain.bbone_density == 0 and not self.params.chain.unlock_deform:
            # In this case, need to copy rotation of the STR bone.
            # https://projects.blender.org/Mets/CloudRig/issues/174
            def_bone.add_constraint(
                'COPY_ROTATION',
                subtarget=str_bone,
                space='WORLD'
            )

        # Stretch to next STR bone.
        if not self.params.chain.unlock_deform:
            def_bone.add_constraint(
                'STRETCH_TO',
                subtarget=next_str_bone,
                use_bulge_min=not self.params.chain.preserve_volume,
                use_bulge_max=True,
                bulge_max=5 if self.params.chain.preserve_volume else 1,
                bulge=self.params.chain.volume_variation,
            )

        # Set BBone Segments according to BBone Density param.
        def_bone.bbone_segments = self.toon__get_num_segments(org_bone, def_bone)

        # If bbone_density is >0, force at least 2 bbone_segments.
        # Otherwise it's not a bendy bone.
        if self.params.chain.bbone_density > 0 and def_bone.bbone_segments < 2:
            def_bone.bbone_segments = 2
        elif self.params.chain.bbone_density == 0:
            # If we don't have bendy bones, we still need to propagate scale.
            def_bone.add_constraint('COPY_SCALE', index=0, space='WORLD', subtarget=str_bone)
            return

        # Set initial ease according to Sharp Sections param.
        if self.params.chain.sharp:
            if str_bone in self.main_str_bones:
                def_bone.bbone_easein = 0
            if next_str_bone in self.main_str_bones:
                def_bone.bbone_easeout = 0

        # B-Bone ease
        def_bone.bbone_handle_type_start = 'TANGENT'
        def_bone.bbone_handle_type_end = 'TANGENT'
        start_handle = str_bone
        end_handle = next_str_bone
        if hasattr(start_handle, 'tangent_helper'):
            start_handle = start_handle.tangent_helper
        if hasattr(end_handle, 'tangent_helper'):
            # This can be False when connecting to a parent chain rig that has Smooth Spline=False.
            end_handle = end_handle.tangent_helper
        def_bone.bbone_custom_handle_start = start_handle
        def_bone.bbone_custom_handle_end = end_handle

        for handle_bone, prop_name in zip([start_handle, end_handle], ['bbone_scalein', 'bbone_scaleout']):
            if not handle_bone:
                # This happens when Tip Control param is off so there's no next_str_bone.
                continue
            for axis, idx in zip(('X', 'Z'), (0, 2)):
                driver = {
                    'prop' : prop_name,
                    'index' : idx,
                    'expression' : f"parent_{axis} * direct_{axis}",
                    'variables' : {
                        f'parent_{axis}': {
                            'type': 'TRANSFORMS',
                            'targets': [
                                {
                                    'bone_target': handle_bone.parent.name,
                                    'transform_space': 'LOCAL_SPACE',
                                    'transform_type': f'SCALE_{axis}',
                                }
                            ],
                        },
                        f'direct_{axis}': {
                            'type': 'TRANSFORMS',
                            'targets': [
                                {
                                    'bone_target': handle_bone.name,
                                    'transform_space': 'LOCAL_SPACE',
                                    'transform_type': f'SCALE_{axis}',
                                }
                            ],
                        }
                    }
                }
                def_bone.drivers.append(driver)

        # Let the STR bone local Y scale delta (relative to average scale) drive the ease value.
        # So scaling the bone uniformally won't affect easing, but increasing local Y scale will.
        for handle_bone, prop_name in zip([start_handle, end_handle], ['bbone_easein', 'bbone_easeout']):
            if not handle_bone:
                # This happens when Tip Control param is off so there's no str_bone.next.
                continue
            def_bone.drivers.append(
                {
                    'prop': prop_name,
                    'expression': "abs(scale_Y/((scale_X+scale_Z)/2)) - 1",
                    'variables': {
                        f'scale_{axis}': {
                            'type': 'TRANSFORMS',
                            'targets': [
                                {
                                    'bone_target': handle_bone.name,
                                    'transform_space': 'LOCAL_SPACE',
                                    'transform_type': f'SCALE_{axis}',
                                }
                            ],
                        }
                        for axis in "XYZ"
                    },
                }
            )

        if self.params.chain.shape_key_helpers and def_bone.prev:
            self.__make_shape_key_helper(def_bone.prev, def_bone)

    def toon__get_num_segments(
        self, org_bone: BoneInfo, def_bone: BoneInfo
    ) -> int:
        """Determine how many deform and b-bone segments should be in a section of the chain."""
        average_bone_length = self.chain_length / len(
            self.bones_org
        )  # TODO: This might be wrong now because we add a bone to bones_org when tip control is enabled...
        bbone_density = round(
            org_bone.length
            / average_bone_length
            * self.params.chain.bbone_density
            * self.params.chain.segments
        )

        bbone_segments = int(bbone_density / (org_bone.length / def_bone.length))
        if self.params.chain.bbone_density > 0:
            # Force at least 2 bbone_segments, otherwise it's not a bendy bone.
            bbone_segments = max(bbone_segments, 2)

        return bbone_segments

    def __make_def_control(self, str_bone: BoneInfo, def_bone: BoneInfo) -> BoneInfo:
        """Create CTR-DEF controls that can be used to nudge deform bones
        completely independently from their neighbours.
        """
        def_bone_control = self.create_parent_bone(
            def_bone, bone_set=self.bone_sets['Deform Controls']
        )
        def_bone_control.name = def_bone_control.name.replace("DEF-P-", "CTR-DEF-")
        def_bone_control.inherit_scale = 'ALIGNED'
        def_bone_parent = self.create_parent_bone(
            def_bone_control, bone_set=self.bone_sets['Deform Helpers']
        )
        def_bone_parent.parent = str_bone.parent
        def_bone_parent.add_constraint(
            'COPY_LOCATION', subtarget=str_bone.name, space='WORLD'
        )
        def_bone_control.head = def_bone_control.center
        def_bone_control.custom_shape_scale_xyz *= 0.7

        if str_bone.next:
            def_bone_parent.add_constraint(
                'STRETCH_TO',
                subtarget=str_bone.next.name,
                use_bulge_min=not self.params.chain.preserve_volume,
                use_bulge_max=True,
                bulge_max=5,
                bulge=self.params.chain.volume_variation,
            )
        def_bone_control.custom_shape_name = self.params.chain.shape_def_control.shape_name
        def_bone_control.custom_shape_scale_xyz.y = 0.1
        def_bone_control.collections = self.bone_sets['Deform Controls'].collections

        # Add drivers to BBone Roll so that rotating CTR-DEF controls on
        # local Y axis gives the results an animator might expect.
        for rna_prop in ['bbone_rollin', 'bbone_rollout']:
            roll_driver = {
                'prop': rna_prop,
                'variables': {
                    'var': {
                        'type': 'TRANSFORMS',
                        'targets': [
                            {
                                'bone_target': def_bone_control.name,
                                'transform_space': 'LOCAL_SPACE',
                                'rotation_mode': 'SWING_TWIST_Y',
                                'transform_type': 'ROT_Y',
                            }
                        ],
                    }
                },
            }
            def_bone.drivers.append(roll_driver)

        return def_bone_control

    @no_overlay
    def __make_shape_key_helper(
        self, def_bone_1: BoneInfo, def_bone_2: BoneInfo
    ) -> BoneInfo:
        """
        Create SKP and SKH helper bones.

        Reading the local rotation of SKH
        gives us the rotation that we can use to activate corrective
        shape keys. It will be the rotational difference between the
        end of def_bone_1 and the start of def_bone_2.
        """

        # SKP (Shape Key Helper Parent): Copy Transforms of the b-bone tail
        # of def_bone_1.
        skp_bone = self.bone_sets['Shape Key Helpers'].new(
            name=def_bone_1.name.replace("DEF", "SKP"),
            source=def_bone_1,
            head=def_bone_1.tail.copy(),
            tail=def_bone_1.tail + def_bone_1.vector,
            parent=def_bone_1,
        )
        skp_bone.scale_length(0.3)
        skp_bone.add_constraint(
            'COPY_TRANSFORMS',
            space='WORLD',
            subtarget=def_bone_1.name,
            use_bbone_shape=True,
            head_tail=1,
        )

        # SKH (Shape Key Helper): This is parented to SKP and Copy Transforms
        # of the b-bone head of def_bone_2.
        skh_bone = self.bone_sets['Shape Key Helpers'].new(
            name=def_bone_1.name.replace("DEF", "SKH"),
            source=def_bone_1,
            head=def_bone_2.head.copy(),
            tail=def_bone_2.tail.copy(),
            parent=skp_bone,
        )
        skh_bone.scale_width(2)
        skh_bone.scale_length(0.4)
        skh_bone.add_constraint(
            'COPY_TRANSFORMS',
            space='WORLD',
            subtarget=def_bone_2.name,
            use_bbone_shape=True,
            head_tail=0,
        )
        return skh_bone

    def __connect_parent_component(self):
        """Connect two separate but connected cloud_chain components.

        If the parent rig is a connected chain rig with tip_control=False,
        make the last DEF bone of that rig stretch to this rig's first STR.
        """
        parent_component = self.parent_component
        meta_org_bone = self.get_metarig_pbone(self.bones_org[0].name)
        if not parent_component:
            return

        can_connect = (
            isinstance(parent_component, Component_ToonChain) and
            not parent_component.params.chain.tip_control and
            meta_org_bone.bone.use_connect
        )
        if not can_connect:
            return

        last_str = parent_component.str_chain[-1]
        last_str.next = self.str_chain[0]
        last_str.custom_shape_name = self.str_chain[0].custom_shape_name = self.params.chain.shape_stretch.shape_name

        if self.painter:
            return

        tip_control_bkp = parent_component.params.chain.tip_control
        parent_component.params.chain.tip_control = True
        last_def = parent_component.bones_def[-1]
        last_org = parent_component.bones_org[-1]
        parent_component.__setup_def_bone(
            def_bone=last_def,
            org_bone=last_org,
            str_bone=last_str,
            next_str_bone=self.str_chain[0],
        )
        parent_component.params.chain.tip_control = tip_control_bkp

        # Set bbone ease according to parent rig's Sharp Sections param.
        if parent_component.params.chain.sharp:
            parent_component.bones_def[-1].bbone_easeout = 0
            self.bones_def[0].bbone_easein = 0

        if (
            self.params.chain.shape_key_helpers
            or parent_component.params.chain.shape_key_helpers
        ):
            self.__make_shape_key_helper(last_def, self.bones_def[0])
        if self.params.chain.smooth_spline:
            self.tangent_helpers[0].constraint_infos[1].subtarget = (
                parent_component.str_chain[-1]
            )
        if parent_component.params.chain.smooth_spline:
            parent_component.tangent_helpers[-1].constraint_infos[2].subtarget = (
                self.str_chain[0]
            )
        if parent_component.params.chain.unlock_deform:
            parent_component.__make_def_control(last_str, last_def)

    ##############################
    # Parameters

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        # We only want to draw this bone set UI if the option for it is enabled.
        if set_name in ["deform_controls", "deform_helpers"]:
            return params.chain.unlock_deform
        if set_name == 'shape_key_helpers':
            return params.chain.shape_key_helpers
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        if params.chain.unlock_deform:
            cls.draw_prop_custom_shape(context, layout, params.chain, 'shape_def_control')
        cls.draw_prop_custom_shape(context, layout, params.chain, 'shape_stretch')
        cls.draw_prop_custom_shape(context, layout, params.chain, 'shape_stretch_ends')
        cls.draw_prop(context, layout, params.chain, 'shape_size', text="Size", enabled=component.appearance_enabled)
        return layout

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Stretch Controls"),
            color_palette='THEME09'
        )
        cls.define_bone_set(
            n_("Deform Controls"),
            color_palette='THEME09',
        )
        cls.define_bone_set(
            n_("Deform Helpers"),
            collections=['Mechanism Bones'],
            is_advanced=True,
        )
        cls.define_bone_set(
            n_("Stretch Helpers"),
            collections=['Mechanism Bones'],
            is_advanced=True,
        )
        cls.define_bone_set(
            n_("Shape Key Helpers"),
            collections=['Mechanism Bones'],
            is_advanced=True,
        )

    @classmethod
    def draw_bendy_params(cls, layout, context, component):
        params = component.params
        cls.draw_prop(context, layout, params.chain, 'bbone_density')
        enabled = params.chain.bbone_density > 0
        cls.draw_prop(context, layout, params.chain, 'sharp', enabled=enabled)
        cls.draw_prop(context, layout, params.chain, 'smooth_spline', enabled=enabled)

        if cls.is_advanced_mode(context):
            cls.draw_prop(context, layout, params.chain, 'preserve_volume')
            if params.chain.preserve_volume:
                cls.draw_prop(context, layout, params.chain, 'volume_variation')
            cls.draw_prop(context, layout, params.chain, 'shape_key_helpers')
            cls.draw_prop(context, layout, params.chain, 'unlock_deform')

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        cls.draw_stretch_control_params(layout, context, component)

    @classmethod
    def draw_stretch_control_params(cls, layout, context, component):
        params = component.params
        cls.draw_control_label(layout, iface_("Stretch"))
        cls.draw_prop(context, layout, params.chain, 'segments')
        cls.draw_prop(context, layout, params.chain, 'tip_control')


class Params(PropertyGroup):
    segments: IntProperty(  # TODO: It would be more intuitive to rename this to "Sub-Controls" and set default to 0, change code logic accordingly, and do metarig versioning.
        name="Stretch Segments",
        description="Number of bendy bones to create for each original bone",
        default=1,
        min=1,
        max=9,
    )
    bbone_density: IntProperty(
        name="B-Bone Density",
        description="Average number of B-Bone Segments per deform bone. Longer bones will have more, shorter ones fewer, to get an even distribution. There will be a minimum of 2 B-Bone Segments unless this parameter is 0",
        default=10,
        min=0,
        max=32,
    )
    unlock_deform: BoolProperty(
        name="Create Deform Controls",
        description="Create CTR-DEF controls that allow Deform bones to be controlled directly",
        default=False,
    )
    shape_key_helpers: BoolProperty(
        name="Create Shape Key Helpers",
        description="Create SKH bones that read the rotation between two deform bones, which can be used to drive corrective shape keys",
    )
    sharp: BoolProperty(
        name="Sharp Sections",
        description="B-Bone EaseIn/Out is set to 0 for bones connecting two sections",
        default=False,
    )
    smooth_spline: BoolProperty(
        name="Smooth Spline",
        description="B-Bone Splines affect their neighbours for smoother curves",
        default=False,
    )

    # This parameter is not exposed, and only exists for backwards compatibility currently.
    align_roll: BoolProperty(
        name="Align Roll",
        description="Re-calculate the bone roll of STR controls based on the ORG bones",
        default=True,
    )
    tip_control: BoolProperty(
        name="Tip Control",
        description="Add the final control at the end of the chain. Disabling this allows you to connect another chain to this one, or to make this chain loop into itself",
        default=True,
    )
    preserve_volume: BoolProperty(
        name="Squash & Stretch",
        description="The bone will become thinner and thicker depending on stretching length.\n\nNOTE: This will result in non-uniform scale inheritance when scaling root bones!",
        default=False,
    )
    volume_variation: FloatProperty(
        name="Volume Variation",
        description="How exaggerated the squashing and stretching should be",
        min=0, max=100,
        soft_max=5,
        default=1,
    )

    shape_stretch: Component_Base.make_custom_shape_params(
        identifier="Stretch",
        default="Sphere 2"
    )
    shape_stretch_ends: Component_Base.make_custom_shape_params(
        identifier="Stretch Ends",
        default="Sphere H"
    )
    shape_def_control: Component_Base.make_custom_shape_params(
        identifier="Deform Control",
        default="Square"
    )
    shape_size: FloatProperty(
        name="Custom Shape Size",
        min=0.1, max=10.0, default=0.6
    )


RIG_COMPONENT_CLASS = Component_ToonChain
