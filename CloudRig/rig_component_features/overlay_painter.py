from __future__ import annotations

import functools
import hashlib
import json
from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gpu import GPUBatch

    from ..properties import RigComponent

import bpy
import gpu
from bpy.types import EditBone, Object, PoseBone
from gpu_extras.batch import batch_for_shader
from mathutils import Color, Euler, Matrix, Vector
from rna_prop_ui import IDPropertyGroup

from ..bs_utils.prefs import get_addon_prefs
from ..bs_utils.ui import label_split
from ..generation.cloudrig import is_active_cloud_metarig
from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.widgets.widgets import ensure_widget
from ..utils.maths import bounding_box_diagonal_size
from ..utils.rig import (
    bone_is_visible,
    get_pbone_of_active,
    get_pbones_of_selected,
)

# Thing to help with unregistration of the main overlay drawing function.
HANDLER = None

### Debug flags.
# Keep this. Helps determine if an issue is a cache invalidation issue or not.
DEBUG_IGNORE_CACHES = False
DEBUG_USE_LAG = False
DEBUG_LAG_ITER = 1000000

### Constants.
DASH_LENGTH = 0.03

### Hashes & Caches.
MODE_CACHE = ""
SELECTION_CACHE = set()
# GPUBatches of the last frame.
# Re-used if nothing about the metarig has changed, to eliminate viewport lag while navigating.
# Sorted by line width.
BATCH_CACHE: dict[float, GPUBatch] = {}
# Component bone name to hash. If unchanged from one frame to the next, no need to re-generate the component.

COMPONENT_HASHES: dict[str, str] = {}
# Component bone name to list of Geo instances.
# If the component hash is unchanged, re-use all Geos from here.
COMPONENT_GEOS: dict[str, Geo] = {}

# BoneInfo name to hash. If unchanged from one frame to the next, no need to re-create its Geo instance.
BONEINFO_HASHES: dict[str, str] = {}
# BoneInfo name to Geo instance.
# Any BoneInfo that hasn't changed can re-use its Geo from here.
BONEINFO_GEOS: dict[str, Geo] = {}


### Overlay drawing.

class OverlayPainter:
    def __init__(self):
        # This matrix must be applied on all drawn 3D shapes, so the caller doesn't have to worry about that.
        # Eg., if your overlays are attached to an object, simply pass the object's world matrix to painter.space,
        # and you don't have to worry about accounting for object transforms anymore.
        self.space = Matrix.Identity((4))

    @staticmethod
    def theme_bone_color(context, theme_color: str | int, color_type='normal') -> Color:
        theme = context.preferences.themes["Default"]
        color_sets = theme.bone_color_sets
        if type(theme_color) is str:
            if theme_color == 'DEFAULT':
                return (theme.view_3d.bone_pose) / 2
            try:
                idx = int(theme_color[-2:]) - 1
            except ValueError:
                raise ValueError("Theme color must be a string ending in 2 digits or an integer <20.")
        elif type(theme_color) is int:
            idx = theme_color
        else:
            raise TypeError("Theme color must be a string or an int.")

        color_set = color_sets[idx]
        color_type = color_type.lower()
        assert hasattr(
            color_set, color_type
        ), f"Color sets have no attribute {color_type}. Must be one of ('normal', 'select', 'active')."

        color = getattr(color_set, color_type)
        if color_type == 'normal':
            # For some reason Blender darkens the normal color by an arbitrary amount...
            n = 0.2
            color = Color((color.r - n, color.g - n, color.b - n))

        return color

    def object_wireframe_3d(self, context, obj: Object, transform: Matrix) -> list[Vector] | None:
        if not obj:
            return
        try:
            mesh = obj.data
        except ReferenceError:
            return
        if not hasattr(mesh, "edges"):
            return

        if DEBUG_USE_LAG:
            for _ in range(DEBUG_LAG_ITER):
                # Artificial lag.
                pass
        verts = mesh.vertices

        transform = self.space @ transform

        # Calculate dash length based on original (un-transformed) bounding box, and the scale component of the matrix.
        # (This is to avoid the dash length being dependent on shape orientation)
        edge_lines = [(verts[e.vertices[0]].co, verts[e.vertices[1]].co) for e in mesh.edges]
        prefs = get_addon_prefs(context)
        if prefs.is_dashed:
            scale = transform.to_scale()
            points = [p*scale for line in edge_lines for p in line]
            size = bounding_box_diagonal_size(points)
            dash_length = DASH_LENGTH * size
        else:
            dash_length = 0

        # Convert to world space
        edge_lines = [(transform @ e[0], transform @ e[1]) for e in edge_lines]

        return self.lines_3d(edge_lines, dash_length=dash_length)

    def lines_3d(self, lines: list[tuple[Vector, Vector]], dash_length=0.1) -> list[Vector] | None:
        if not lines:
            return

        # Generate dashed segments
        dashes = self.__dash_lines(lines, dash_length)

        # Flatten all line segments into a single vertex list
        verts = []
        for dash in dashes:
            for a, b in dash:
                verts.append(a)
                verts.append(b)

        return verts

    def __dash_lines(self, lines: list[tuple[Vector, Vector]], dash_length=0.1) -> list[list[tuple[Vector, Vector]]]:
        """A "dash" is a list of consecutive lines whose length sums to a hard-coded length.
        We take a list of lines as input, and return a list of dashes by splitting up
        long lines into multiple dashes, and combining shorter lines into a single dash.
        The results will only be visually coherent if the input lines are spatially consecutive.
        """
        if dash_length < 0.0001:
            return [lines]

        dashes: list[list[tuple[Vector, Vector]]] = []

        current_dash: list[tuple[Vector, Vector]] = []
        current_dash_length = 0.0

        for start, end in lines:
            remaining_start = start
            remaining_vec = end - start
            remaining_length = remaining_vec.length
            direction = remaining_vec.normalized()

            while remaining_length > 0:
                available = dash_length - current_dash_length

                if remaining_length <= available:
                    current_dash.append((remaining_start, end))
                    current_dash_length += remaining_length
                    break

                split_point = remaining_start + direction * available
                current_dash.append((remaining_start, split_point))
                dashes.append(current_dash)

                current_dash = []
                current_dash_length = 0.0

                remaining_start = split_point
                remaining_length -= available

        if current_dash:
            dashes.append(current_dash)

        # Return every 2nd dash, as the others represent the gaps.
        return dashes[::2]

    def bone_info_to_geo(self, context, metarig, bone_info) -> Geo | None:
        prefs = get_addon_prefs(context)
        self.space = metarig.matrix_world.copy()
        bi_hash = hash_boneinfo(prefs, metarig, bone_info)
        old_hash = BONEINFO_HASHES.get(bone_info.name)
        if bi_hash == old_hash and not DEBUG_IGNORE_CACHES:
            geo = BONEINFO_GEOS.get(bone_info.name)
            if not geo:
                return
            return geo

        BONEINFO_HASHES[bone_info.name] = bi_hash
        # XXX: Appending objects in overlay drawing code is pretty crazy ngl.
        # But on the other hand... it's also kinda bulletproof.
        wgt_ob = ensure_widget(bone_info.custom_shape_name, overwrite=False)
        if not wgt_ob:
            return

        transform = get_bone_display_matrix(bone_info)
        geo = Geo(
            'LINES',
            positions = self.object_wireframe_3d(context, wgt_ob, transform),
            color = self.theme_bone_color(context, theme_color=bone_info.color_palette_base),
            line_width = bone_info.custom_shape_wire_width,
        )

        BONEINFO_GEOS[bone_info.name] = geo
        return geo


class Geo:
    """Data that can be fed into a GPUBatch for drawing"""
    def __init__(
        self,
        data_layout='LINES',
        positions: list[Vector]=[],
        line_width=1.5,
        color=(1, 1, 1, 1),
    ):
        self.data_layout = data_layout
        self.positions = positions
        self.line_width = line_width
        self.color = color

    @classmethod
    def draw_all(cls):
        pass


def draw_rig_preview():
    start = time()
    context = bpy.context
    if not overlay_poll(context):
        return
    global SELECTION_CACHE
    global MODE_CACHE
    metarig = context.active_object
    animdata = metarig.animation_data
    metarig_is_animated = animdata and (animdata.action or animdata.drivers)
    animating = context.screen.is_animation_playing and metarig_is_animated
    selection = set([pb.name for pb in get_pbones_of_selected(context, whole_ebone=False)])
    selection_unchanged = SELECTION_CACHE == selection
    mode_unchanged = context.mode == MODE_CACHE
    SELECTION_CACHE = selection
    MODE_CACHE = context.mode
    if is_modal_navi_running(context) and not animating and selection_unchanged and mode_unchanged:
        # During viewport navigation, if the metarig isn't animating,
        # re-draw entirely from cache. (This takes <0.1ms.)
        draw_component_geos(only_from_cache=True)
        return

    prefs = get_addon_prefs(context)

    components_to_draw = set(get_components_to_draw(context))

    global COMPONENT_HASHES
    global COMPONENT_GEOS

    # Start a new cache.
    COMPONENT_GEOS_NEW = {}

    components_to_regenerate = set()

    for component in components_to_draw:
        comp_pbone = component.component_pbone
        component_hash = hash_component(prefs, comp_pbone.cloudrig_component)
        old_comp_hash = COMPONENT_HASHES.get(comp_pbone.name, "")
        if component_hash == old_comp_hash and not DEBUG_IGNORE_CACHES:
            geos = COMPONENT_GEOS.get(comp_pbone.name)
            if not geos:
                components_to_regenerate.add(component)
                continue
            COMPONENT_GEOS_NEW[comp_pbone.name] = geos
            continue
        COMPONENT_HASHES[comp_pbone.name] = component_hash
        components_to_regenerate.add(component)

    if components_to_regenerate:
        painter = OverlayPainter()
        painter.space = metarig.matrix_world

        from ..generation.cloud_generator import CloudRig_Generator
        generator = CloudRig_Generator(context, metarig, painter)
        # Generate the abstraction layer (ie. BoneInfos) of ONLY the changed/missing components.
        generator.generate_abstraction_layer(context, [comp.component_pbone for comp in components_to_regenerate])
        for component in components_to_regenerate:
            comp_pbone = component.component_pbone
            try:
                generated_component = generator.component_map[comp_pbone.name]
            except KeyError:
                print(f"CloudRig Overlay Error: Couldn't find generated component {comp_pbone.name}")
                continue
            geos = generated_comp_to_geos(generated_component, context, painter)
            COMPONENT_GEOS_NEW[comp_pbone.name] = geos

    # Overwrite the old cache.
    COMPONENT_GEOS = COMPONENT_GEOS_NEW

    draw_component_geos()

    prefs.overlay_eval_time = (time() - start) * 1000


def overlay_poll(context) -> bool:
    """General rig preview overlay drawing poll function. If this returns False,
    we shouldn't be drawing or generating ANY rig preview.
    """
    prefs = get_addon_prefs(context)
    if not prefs or prefs.overlay_mode=='NONE':
        return False
    view3d = context.area.spaces.active
    if not view3d.overlay.show_overlays:
        return False
    if context.mode not in ('EDIT_ARMATURE', 'POSE'):
        return False
    active_metarig = is_active_cloud_metarig(context)
    if not active_metarig:
        return False
    return True


def is_modal_navi_running(context) -> bool:
    """Returns whether the viewport navigation operator is running.
    Used for disabling UI drawing for performance optimization."""
    for m in context.window.modal_operators:
        if m.bl_idname.startswith('VIEW3D_OT_'):
            return True
    return False


def get_components_to_draw(context) -> set[RigComponent]:
    """Whether rig preview should be drawn for a a given component."""
    prefs = get_addon_prefs(context)

    potential_components = set()

    if prefs.overlay_mode == 'ACTIVE':
        active_pbone = get_pbone_of_active(context)
        if not active_pbone or not hasattr(active_pbone, 'cloudrig_component'):
            return set()
        component = active_pbone.cloudrig_component.inherited_component
        if not component:
            return set()
        potential_components.add(component)
    elif prefs.overlay_mode in ('SELECTED', 'CHILDREN'):
        pbones = get_pbones_of_selected(context, whole_ebone=False)
        if prefs.overlay_mode == 'CHILDREN':
            for pbone in pbones:
                for child in pbone.children:
                    pbones.append(child)
        for pbone in set(pbones):
            if pbone.cloudrig_component.inherited_component:
                potential_components.add(pbone.cloudrig_component.inherited_component)
    elif prefs.overlay_mode == 'VISIBLE':
        metarig = context.active_object # (We don't care about WP mode, so this is fine!)
        potential_components = [
            pb.cloudrig_component
            for pb in metarig.pose.bones
            if pb.cloudrig_component.component_type
        ]
    else:
        raise ValueError("Overlay mode not implemented: ", prefs.overlay_mode)

    final_components = set()
    for comp in potential_components:
        if not any((bone_is_visible(pb) for pb in comp.component_pbone_chain)):
            continue
        comp_class = comp.component_class
        if not comp_class:
            continue
        final_components.add(comp)

    return final_components


def generated_comp_to_geos(generated_component, context, painter: OverlayPainter) -> dict[str, Geo]:
    geos = {}
    for bone_info in generated_component.all_bone_infos:
        if not bone_info.custom_shape_name:
            continue

        metarig = generated_component.generator.metarig
        colls = (metarig.data.collections_all.get(coll_name) for coll_name in bone_info.collections)
        if not any((coll.is_visible_effectively for coll in colls if coll)):
            continue

        geo = painter.bone_info_to_geo(context, metarig, bone_info)
        if geo:
            geos[bone_info.name] = geo
    return geos


def draw_component_geos(only_from_cache=False):
    global BATCH_CACHE
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    shader = gpu.shader.from_builtin('POLYLINE_FLAT_COLOR')
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])

    if only_from_cache and BATCH_CACHE and not DEBUG_IGNORE_CACHES:
        for line_width, batch in BATCH_CACHE.items():
            shader.uniform_float("lineWidth", line_width)
            batch.draw(shader)
        return

    BATCH_CACHE = {}
    geos_by_line_width = {}
    for _comp_bone_name, geos in COMPONENT_GEOS.items():
        for _bone_name, geo in geos.items():
            if geo.line_width not in geos_by_line_width:
                geos_by_line_width[geo.line_width] = []
            geos_by_line_width[geo.line_width].append(geo)

    for line_width, geos in geos_by_line_width.items():
        shader.uniform_float("lineWidth", line_width)
        geo_data = {"pos": [], "color": []}
        for geo in geos:
            geo_data["pos"].extend(geo.positions)
            geo_data["color"].extend([geo.color]*len(geo.positions))

        batch = batch_for_shader(shader, 'LINES', geo_data)
        batch.draw(shader)
        BATCH_CACHE[line_width] = batch

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


### Decorator for rig components and generator functions to skip unnecessary functions when generating for the overlay.
def no_overlay(_func=None, *, return_value=None):
    """Decorator for use by rig component functions which need to be skipped
    during overlay drawing.
    Can also be applied to other functions which can be safely skipped,
    for a small performance boost in overlay drawing. But USE CAREFULLY!!!
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.painter:
                return return_value
            return func(self, *args, **kwargs)

        return wrapper

    # Called as @no_overlay
    if _func is not None and callable(_func):
        return decorator(_func)

    # Called as @no_overlay(...)
    return decorator


### Hashing functions.
def hash_boneinfo(prefs, metarig: Object, boneinfo: BoneInfo) -> str:
    return any_to_hash(
        prefs.overlay_mode,
        prefs.is_dashed,
        metarig.name,
        metarig.matrix_world,
        boneinfo.head,
        boneinfo.tail,
        boneinfo.roll,
        boneinfo.custom_shape_name,
        get_bone_display_matrix(boneinfo),
        boneinfo.custom_shape_wire_width,
        boneinfo.color_palette_base,
        boneinfo.color_palette_pose,
        boneinfo.collections,
    )


def hash_component(prefs, component) -> str:
    rig = component.id_data
    pbone_chain = component.component_pbone_chain
    return any_to_hash(
        bpy.data.filepath,
        prefs.overlay_mode,
        prefs.is_dashed,
        rig.name,
        rig.matrix_world,
        [pb.select for pb in pbone_chain],
        [bone_is_visible(pb) for pb in pbone_chain],
        [hash_bone(rig, pbone) for pbone in pbone_chain],
        [coll.is_visible for coll in rig.data.collections_all],
    )


def any_to_hash(*args) -> str:
    """Hash whatever."""
    try:
        stringified = json.dumps(
            args,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        stringified = ";".join(map(str, args))

    return hashlib.sha256(stringified.encode("utf-8")).hexdigest()


def hash_bone(rig: Object, bone: PoseBone | EditBone) -> str:
    pbone = rig.pose.bones.get(bone.name)
    if not pbone:
        return ""
    if rig.mode == 'EDIT':
        ebone = rig.data.edit_bones[bone.name]
        transforms = [ebone.head, ebone.tail, ebone.roll]
    else:
        transforms = pbone.matrix
    return any_to_hash(
        pbone.name,
        transforms,
        pbone.hide,
        pbone.select,
        pbone.custom_shape_translation,
        pbone.custom_shape_rotation_euler,
        pbone.custom_shape_scale_xyz,
        pbone.custom_shape_wire_width,
        pgroup_to_dict(pbone.cloudrig_component),
    )


def pgroup_to_dict(pgroup: IDPropertyGroup) -> dict:
    pg_dict = dict(pgroup)
    for key, value in pg_dict.items():
        if isinstance(value, IDPropertyGroup):
            pg_dict[key] = pgroup_to_dict(value)
        if type(value) is list:
            pg_dict[key] = [pgroup_to_dict(v) for v in value]
    return pg_dict


def get_bone_display_matrix(bone: BoneInfo | PoseBone) -> Matrix:
    """Return object-space matrix of a BoneInfo or PoseBone, without override transform (for now)."""
    if isinstance(bone, PoseBone):
        display_bone = bone.custom_shape_transform or bone
        matrix = display_bone.matrix.copy()
    else:
        matrix = (bone.custom_shape_transform or bone).matrix

    # Account for additional scaling from use_custom_shape_bone_size,
    # which scales the shape by the bone length.
    scale = bone.custom_shape_scale_xyz.copy()
    if bone.use_custom_shape_bone_size:
        if isinstance(bone, BoneInfo):
            scale *= bone.length
        else:
            scale *= bone.bone.length

    # Step 3: Create a matrix from the custom shape translation, rotation
    # and this scale which already accounts for bone length.
    custom_shape_matrix = Matrix.LocRotScale(
        bone.custom_shape_translation, Euler(bone.custom_shape_rotation_euler, 'XYZ'), scale
    )

    # Step 4: Multiply the pose bone's world matrix by the custom shape matrix.
    matrix = matrix @ custom_shape_matrix

    return matrix


### Menu buttons in the Overlays pop-over.

def draw_overlay_toggle(self, context):
    if context.mode not in ('POSE', 'EDIT_ARMATURE'):
        return
    prefs = get_addon_prefs(context)
    layout = self.layout.column(align=True)

    row = label_split(layout, text="CloudRig Preview")
    row.prop(prefs, 'overlay_mode', text="")
    if prefs.overlay_mode != 'NONE':
        label_split(layout, text="Dashed").prop(prefs, 'is_dashed')
        # label_split(layout, text="Time:").label(text=f"{prefs.overlay_eval_time:.2f}ms")


### Registration.

def register():
    global HANDLER
    HANDLER = bpy.types.SpaceView3D.draw_handler_add(
        draw_rig_preview,
        (),  # args
        'WINDOW',  # region_type,
        'POST_VIEW',  # draw_type
    )
    bpy.types.VIEW3D_PT_overlay.append(draw_overlay_toggle)


def unregister():
    global HANDLER
    bpy.types.SpaceView3D.draw_handler_remove(HANDLER, 'WINDOW')
    bpy.types.VIEW3D_PT_overlay.remove(draw_overlay_toggle)
