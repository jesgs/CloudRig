# SPDX-License-Identifier: GPL-3.0-or-later

from math import sqrt

import bmesh
import bpy
from bpy.app.translations import pgettext_n as n_
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
from bpy.types import Object, PropertyGroup

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.object import lock_transforms
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_fk_chain import Component_Chain_FK

PHYS_PREFIX = "PSX"


class CloudPhysicsChainRig(Component_Chain_FK):
    """FK Chain with cloth physics."""

    ui_name = "Chain: Physics"
    forced_params = {
        'fk_chain.double_first': False,
        'fk_chain.root': True,
        'fk_chain.hinge': False,
    }

    ##############################
    # Inherited functions.

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        self.phys_name = self.naming.add_prefix(self.base_bone_name, PHYS_PREFIX)

        phys_ob = self.__ensure_physics_object(context, self.bone_sets['FK Controls'])
        if self.params.physics_chain.make_ctrl:
            self.__make_physics_chain(self.bone_sets['FK Controls'])
        self.__constrain_chain_to_phys_ob(phys_ob, self.bone_sets['FK Controls'])

    def create_helper_objects(self, context):
        """This is called by the generator. In this case, the helper object
        needed to be created earlier, so that was already done at the create_bone_infos() stage.
        But here we still need to poke the Armature constraint to wake up,
        because we initialized it before the real bone existed..."""
        context.view_layer.update()
        phys_obj = self.params.physics_chain.phys_obj
        for c in phys_obj.constraints:
            c.influence = c.influence

    ##############################
    # Physics chain functions.

    @no_overlay
    def __ensure_physics_object(self, context, bone_chain: list[BoneInfo]):
        phys_obj = self.params.physics_chain.phys_obj
        if phys_obj and not self.params.physics_chain.force_regen:
            return phys_obj

        cloth_mesh = bpy.data.meshes.new(name=self.phys_name)
        if not phys_obj:
            # Create physics object.
            phys_obj = bpy.data.objects.new(cloth_mesh.name, cloth_mesh)
            context.scene.collection.objects.link(phys_obj)
            phys_obj.parent = self.target_rig
            lock_transforms(phys_obj)
        else:
            phys_obj.data = cloth_mesh

        phys_obj.hide_render = True

        # Wipe modifiers & vertex groups
        phys_obj.modifiers.clear()
        phys_obj.constraints.clear()
        phys_obj.vertex_groups.clear()

        # Parent physics object.
        phys_obj.parent = self.target_rig

        # Add Armature modifier on physics object
        if self.params.physics_chain.make_ctrl:
            arm_mod = phys_obj.modifiers.new(type='ARMATURE', name="Armature")
            arm_mod.object = self.target_rig
        else:
            arm_con = phys_obj.constraints.new(type='ARMATURE')
            tgt = arm_con.targets.new()
            tgt.target = self.target_rig
            tgt.subtarget = self.root_bone.name

        # Create verts and edges using bmesh.
        bm = bmesh.new()
        bm.from_mesh(cloth_mesh)
        for i, bone in enumerate(bone_chain):
            vert = bm.verts.new(bone.head)
            bm.verts.ensure_lookup_table()
            if i > 0:
                bm.edges.new((bm.verts[i], bm.verts[i - 1]))
            if i == len(bone_chain) - 1:
                tail_vert = bm.verts.new(bone.tail)
                bm.edges.new((vert, tail_vert))

        bm.to_mesh(cloth_mesh)
        bm.free()

        ### Create and assign vertex groups.

        # Total length of the chain
        total_length = 0
        for b in bone_chain:
            total_length += b.length
        total_length *= self.params.physics_chain.pin_falloff_offset
        cum_length = 0

        pin_name = "PIN-" + phys_obj.name

        # Assign weights.
        pin_vg = phys_obj.vertex_groups.new(name=pin_name)
        pin_vg.add([0], 1, 'REPLACE')
        for i, v in enumerate(cloth_mesh.vertices):
            if i == 0:
                continue
            pin_weight = 1
            name = self.naming.add_prefix(bone_chain[i - 1], PHYS_PREFIX)
            # Determine pin weight on this vertex.
            cum_length += bone_chain[i - 1].length
            ratio = (
                self.params.physics_chain.pin_falloff_offset - cum_length / total_length
            )
            if self.params.physics_chain.pin_falloff == 'NONE':
                pin_weight = 0
            elif self.params.physics_chain.pin_falloff == 'LINEAR':
                pin_weight = ratio
            elif self.params.physics_chain.pin_falloff == 'QUADRATIC':
                pin_weight = ratio * ratio
            elif self.params.physics_chain.pin_falloff == 'SQRT':
                pin_weight = sqrt(ratio)

            vg = phys_obj.vertex_groups.new(name=name)
            vg.add([i], 1, 'REPLACE')
            pin_vg.add([i], pin_weight, 'REPLACE')

        # Create Cloth modifier.
        cloth_mod = phys_obj.modifiers.new(type='CLOTH', name="Cloth")
        cloth_mod.settings.vertex_group_mass = pin_name

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        if phys_obj not in set(context.scene.objects):
            context.scene.collection.objects.link(phys_obj)
        visibility = self.ensure_visible(context, phys_obj)
        context.view_layer.objects.active = phys_obj
        phys_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        context.tool_settings.mesh_select_mode[0] = True
        bpy.ops.mesh.select_all(action='SELECT')
        # bpy.ops.mesh.extrude_region()
        bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value": (0, 0.01, 0)})
        bpy.ops.object.mode_set(mode='OBJECT')

        context.view_layer.objects.active = self.target_rig
        bpy.ops.object.mode_set(mode='EDIT')
        self.params.physics_chain.phys_obj = phys_obj
        visibility.restore(context)
        self.check_object_in_scene(context, phys_obj)
        return phys_obj

    def __make_physics_chain(self, from_chain: list[BoneInfo]):
        # Make a chain of bones to control the physics object.
        next_parent = from_chain[0].parent
        for fk_ctrl in from_chain:
            phys_ctrl = self.bone_sets['Physics Bones'].new(
                name=self.naming.add_prefix(fk_ctrl, PHYS_PREFIX),
                source=fk_ctrl,
                custom_shape_name=fk_ctrl.custom_shape_name,
                custom_shape_scale_xyz = fk_ctrl.custom_shape_scale_xyz * 1.2,
                parent=next_parent,
                use_deform=True,
            )
            next_parent = phys_ctrl

        self.bone_sets['Deform Bones'].new(
            name=self.naming.add_prefix(self.phys_name, "PIN"),
            source=self.bone_sets['Physics Bones'][0],
            parent=self.bone_sets['Physics Bones'][0],
            use_deform=True,
            custom_shape_name=self.params.fk_chain.shape_fk_root.shape_name,
        )

        # Parent first FK control to first PSX control.
        self.bone_sets['FK Controls'][0].parent = self.bone_sets['Physics Bones'][0]

        # Set first PSX control as the limb root bone, for correct parent switch
        # and root parenting behaviours
        self.root_bone = self.bone_sets['Physics Bones'][0]

    @no_overlay
    def __constrain_chain_to_phys_ob(self, phys_ob: Object, bone_chain: list[BoneInfo]):
        # For the moment, let's just slap some constraints on the FK chain.
        for fk_ctrl in bone_chain:
            fk_ctrl.add_constraint(
                'DAMPED_TRACK',
                use_preferred_defaults=False,
                target=phys_ob,
                subtarget=self.naming.add_prefix(fk_ctrl, PHYS_PREFIX),
            )

    ##############################
    # Parameters
    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Physics Bones"), color_palette='THEME04', collections=['Physics Bones']
        )

    @classmethod
    def draw_control_params(cls, layout, context, component):
        super().draw_control_params(layout, context, component)
        params = component.params

        layout.separator()
        cls.draw_control_label(layout, "Physics")

        cls.draw_prop(context, layout, params.physics_chain, 'phys_obj')
        cls.draw_prop(context, layout, params.physics_chain, 'force_regen')

        if not params.physics_chain.phys_obj or params.physics_chain.force_regen:
            cls.draw_prop(context, layout, params.physics_chain, 'pin_falloff')
            if params.physics_chain.pin_falloff != 'NONE':
                cls.draw_prop(
                    context, layout, params.physics_chain, 'pin_falloff_offset'
                )

        cls.draw_prop(context, layout, params.physics_chain, 'make_ctrl')


class Params(PropertyGroup):
    phys_obj: PointerProperty(
        type=Object,
        name="Cloth Object",
        description="Select an object which has vertex groups corresponding to the bone names of the chain, prefixed with 'phys_'. Leave empty to generate the object",
    )
    force_regen: BoolProperty(
        name="Force Re-generate",
        description="Even if the mesh already exists, force it to be re-generated from scratch",
        default=True,
    )
    pin_falloff: EnumProperty(
        name="Pin Falloff",
        description="Type of falloff to apply to the generated cloth mesh's pin vertex group. The first vertex is always fully pinned",
        items=[
            ('NONE', "None", "First vertex fully pinned, rest fully unpinned"),
            (
                'LINEAR',
                "Linear",
                "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated",
            ),
            (
                'QUADRATIC',
                "Loose",
                "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated and then raised to 2nd power",
            ),
            (
                'SQRT',
                "Stiff",
                "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated and then their square root is taken",
            ),
        ],
        default='QUADRATIC',
    )
    pin_falloff_offset: FloatProperty(
        name="Pin Falloff Offset",
        description="Calculate the pin falloffs as if the bone chain was this much longer than it actually is. Increasing this beyond 1.0 will cause all vertices to be more pinned",
        default=1.20,
        min=0.0,
        max=10.0,
    )
    make_ctrl: BoolProperty(
        name="Create Physics Controls",
        description="Create a control chain that can control the physics mesh using an Armature modifier",
        default=True,
    )


RIG_COMPONENT_CLASS = CloudPhysicsChainRig
