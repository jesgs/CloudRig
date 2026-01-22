import os
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
)
from bpy.types import Area, Object, Operator
from mathutils import Vector

from ..rig_component_features.properties_ui import redraw_viewport
from ..rig_component_features.widgets.widgets import (
    get_native_widgets_path,
    widget_name,
)


def get_3d_view(context) -> Area | None:
    if context.area and context.area.type == 'VIEW_3D':
        area = context.area
    else:
        area = next((a for a in context.screen.areas if a.type=='VIEW_3D'))

    if area:
        return area.spaces.active

@contextmanager
def temporary_setattr(obj, **kwargs):
    """Temporarily set attributes on obj."""
    old_values = {name: getattr(obj, name) for name in kwargs}
    old_values = {name:value.copy() if hasattr(value, 'copy') else value for name, value in old_values.items()}
    try:
        for name, value in kwargs.items():
            if hasattr(value, 'copy'):
                value = value.copy()
            try:
                setattr(obj, name, value)
            except TypeError:
                print(f"CloudRig: Failed to set {name} to {value}")
                raise
        yield
    finally:
        for name, value in old_values.items():
            setattr(obj, name, value)

@contextmanager
def viewport_settings(
        context,
        resolution=(512, 512),
        show_overlays=False,
        show_gizmo=False,
        film_transparent=True,
        color_type='MATERIAL',
        light='MATCAP',
        single_color=(1, 1, 1),
        media_type='IMAGE',
        file_format='PNG',
        color_mode='RGBA',
        color_depth='8',
        show_object_outline=False,
        shading_type = 'SOLID',
    ):

    view_3d = get_3d_view(context)

    render = context.scene.render

    # Handle resolution separately (two attributes)
    old_res = (render.resolution_x, render.resolution_y)
    # Also handle color mode separately (because it doesn't work otherwise for no reason??)

    with temporary_setattr(
        render.image_settings,
        media_type=media_type,
        file_format=file_format,
        color_depth=str(color_depth),
        color_mode=color_mode,
        compression=100,
    ), temporary_setattr(
        render,
        film_transparent=film_transparent,
        resolution_x=resolution[0],
        resolution_y=resolution[1],
    ), temporary_setattr(
        view_3d,
        show_gizmo=show_gizmo,
    ), temporary_setattr(
        view_3d.overlay,
        show_overlays=show_overlays,
    ), temporary_setattr(
        view_3d.shading,
        type=shading_type,
        color_type=color_type,
        light=light,
        single_color=single_color,
        show_object_outline=show_object_outline,
    ):
        try:
            context.view_layer.update()
            yield
        finally:
            render.resolution_x, render.resolution_y = old_res

@contextmanager
def widget_geonodes(objects: list[Object], thickness=0.03):
    @contextmanager
    def widget_geonodes_single(obj: Object, thickness=0.03):
        GN_NAME = 'GN-bone_widget'
        node_group = bpy.data.node_groups.get(GN_NAME)
        if not node_group:
            with bpy.data.libraries.load(get_native_widgets_path(), link=True, relative=False) as (
                data_from,
                data_to,
            ):
                for node_group in data_from.node_groups:
                    if node_group == GN_NAME:
                        data_to.node_groups.append(node_group)
                        break
            node_group = bpy.data.node_groups.get(GN_NAME)
            assert node_group
        MOD_NAME = "GN-Widget"
        modifier = obj.modifiers.get(MOD_NAME)
        if not modifier:
            modifier = obj.modifiers.new(name=MOD_NAME, type='NODES')
        modifier.node_group = node_group
        modifier['Socket_2'] = thickness
        yield
        mod = obj.modifiers.get(MOD_NAME)
        if mod:
            obj.modifiers.remove(mod)

    with ExitStack() as stack:
        for obj in objects:
            stack.enter_context(widget_geonodes_single(obj, thickness))
        yield

@contextmanager
def selection_state(context, active_obj: Object=None, selected_obs: list[Object]=None):
    # Obviously, deleting active or selected objects is not supported!
    # This does not enforce visibility!
    if selected_obs is None:
        selected_obs = [active_obj]
    if active_obj is None:
        active_obj = selected_obs[0]
    selection_backup = context.selected_objects[:]
    active_backup = context.active_object

    for obj in selection_backup:
        obj.select_set(False)
    for obj in selected_obs:
        obj.select_set(True)
    context.view_layer.objects.active = active_obj

    yield

    for obj in selected_obs:
        obj.select_set(False)
    for obj in selection_backup:
        obj.select_set(True)
    context.view_layer.objects.active = active_backup

@contextmanager
def focus_objects(context, objects: list[Object]=None, margin=0.1):
    view_3d = get_3d_view(context)
    if not objects or not view_3d:
        yield
        return
    region_3d = view_3d.region_3d
    org_view_matrix = region_3d.view_matrix.copy()

    focus_view_on_objects(context, objects, margin)

    yield

    region_3d.view_matrix = org_view_matrix

def focus_view_on_objects(context, objects: list[Object]=None, margin=0.1):
    if not objects:
        objects = context.selected_objects
    bbox_3d = get_bbox_3d(objects, margin=margin)
    fit_view3d_to_coords(context, *bbox_3d)
    if bpy.app.version >= (4, 4, 0):
        # This worked fine until 4.4, but now it needs to be ran twice...!
        fit_view3d_to_coords(context, *bbox_3d)

@contextmanager
def active_camera(context, camera: Object):
    view3d = get_3d_view(context)
    if not view3d:
        return

    org_matrix = view3d.region_3d.view_matrix.copy()
    org_location = view3d.region_3d.view_location.copy()
    org_distance = view3d.region_3d.view_distance

    with temporary_setattr(
            context.scene,
            camera=camera,
        ), temporary_setattr(
            view3d,
            use_local_camera=False,
        ), temporary_setattr(
            view3d.region_3d,
            view_perspective='CAMERA',
        ):
        # This is not just for UI feedback, it's for some reason necessary, otherwise
        # it's using the wrong camera...
        redraw_viewport()
        yield

    view3d.region_3d.view_matrix = org_matrix.copy()
    view3d.region_3d.view_location = org_location.copy()
    view3d.region_3d.view_distance = org_distance

def fit_view3d_to_coords(context, center, coords):
    view_3d = get_3d_view(context)
    if not view_3d:
        return
    region_3d = view_3d.region_3d
    use_temp_cam = False
    camera = None
    if region_3d.view_perspective == 'CAMERA' and view_3d.lock_camera:
        if view_3d.use_local_camera:
            camera = view_3d.camera
        else:
            camera = context.scene.camera
    if not camera:
        use_temp_cam = True
        org_cam = context.scene.camera
        org_persp = region_3d.view_perspective
        cam_data = bpy.data.cameras.new(name="temp_Camera")
        if region_3d.view_perspective == 'ORTHO':
            cam_data.type = 'ORTHO'
        cam_data.sensor_width = 72
        cam_data.lens = view_3d.lens

        camera = bpy.data.objects.new("temp_Camera", object_data=cam_data)
        camera.matrix_world = region_3d.view_matrix.inverted()
        context.scene.collection.objects.link(camera)
        context.scene.camera = camera
        region_3d.view_perspective = 'CAMERA'

    coords = [co for corner in coords for co in corner]
    depsgraph = context.evaluated_depsgraph_get()
    camera.location, ortho_scale = camera.camera_fit_coords(depsgraph, coords)
    if camera.data.type == 'ORTHO':
        camera.data.ortho_scale = ortho_scale

    context.view_layer.update()

    if use_temp_cam:
        region_3d.view_perspective = org_persp
        cam_matrix = camera.matrix_world.inverted()
        distance = (camera.matrix_world.translation - center).length
        if org_persp == 'ORTHO':
            region_3d.view_distance = camera.data.ortho_scale * view_3d.lens / 72
        else:
            region_3d.view_distance = distance

        bpy.data.objects.remove(camera)
        bpy.data.cameras.remove(cam_data)
        region_3d.view_matrix = cam_matrix
        context.scene.camera = org_cam

def get_bbox_3d(objects: list[Object], margin=0.0) -> tuple[Vector, list[Vector]]:
    """Return combined transformed bounding box center and 8 corners in world space."""
    min_bound = [float('inf'), float('inf'), float('inf')]
    max_bound = [-float('inf'), -float('inf'), -float('inf')]

    for obj in objects:
        for co in get_world_bounding_box(obj):
            for i in range(3):  # X, Y, Z
                min_bound[i] = min(min_bound[i], co[i])
                max_bound[i] = max(max_bound[i], co[i])

    # Calculate the center of the bounding box
    center = Vector([(min_bound[i] + max_bound[i]) / 2 for i in range(3)])

    # Construct the 8 bounding box corners from the min/max X/Y/Z coords.
    corners = [
        Vector((min_bound[0]-margin, min_bound[1]-margin, min_bound[2]-margin)),
        Vector((min_bound[0]-margin, min_bound[1]-margin, max_bound[2]+margin)),
        Vector((min_bound[0]-margin, max_bound[1]+margin, min_bound[2]-margin)),
        Vector((min_bound[0]-margin, max_bound[1]+margin, max_bound[2]+margin)),
        Vector((max_bound[0]+margin, min_bound[1]-margin, min_bound[2]-margin)),
        Vector((max_bound[0]+margin, min_bound[1]-margin, max_bound[2]+margin)),
        Vector((max_bound[0]+margin, max_bound[1]+margin, min_bound[2]-margin)),
        Vector((max_bound[0]+margin, max_bound[1]+margin, max_bound[2]+margin)),
    ]

    return center, corners

def get_world_bounding_box(obj) -> list[Vector]:
    """Returns the world-space coordinates of an object's bounding box."""
    # Get the 8 local-space bounding box corners
    local_bbox_corners = [Vector(corner) for corner in obj.bound_box]
    # Convert to world space using matrix_world
    world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]

    return world_bbox_corners

class VIEW3D_OT_render_widget_thumbnails(Operator):
    """Render a thumbnail for each selected mesh object suitable for bone custom shapes. Outputs to a "/thumbnails" folder."""

    bl_idname = "object.cloudrig_render_widget_thumbnails"
    bl_label = "Render Bone Shape Thumbnails"
    bl_options = {'REGISTER', 'UNDO'}

    thickness: FloatProperty(
        name="Wire Thickness",
        default=0.015,
        min=0.0,
        max=1.0
    )
    color: FloatVectorProperty(
        name="Wire Color",
        min=0.0,
        max=1.0,
        subtype='COLOR',
        default=(1.0, 1.0, 1.0)
    )
    focus_view: BoolProperty(
        name="Frame Objects",
        description="Frame objects in the view automatically, while still using current view rotation.",
        default=True,
    )
    margin: IntProperty(
        name="Cropping Margin",
        default=10,
        min=0,
        max=100
    )
    save: BoolProperty(
        name="Save File",
        description="Save a .png named after the widget, in a /thumbnails folder next to this .blend.",
        default=True
    )
    overwrite: BoolProperty(
        name="Overwrite",
        description="Overwrite existing files",
        default=True
    )
    render_resolution: IntVectorProperty(
        name="Render Resolution",
        description='Increase to increase crispness. Final image resolution is not determined by this. See "Downscale to Size" below.',
        size=2,
        min=64,
        max=2048,
        default=(512, 512),
    )
    downscale_to_size: IntProperty(
        name="Downscale to Size",
        description="After cropping out empty space, downscale the image to this size.",
        min=64,
        max=2048,
        default=128,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout = layout.column(align=True)
        layout.prop(self, 'thickness')
        layout.prop(self, 'color')
        layout.separator()

        layout.prop(self, 'focus_view')
        layout.prop(self, 'margin')
        layout.separator()

        layout.row().prop(self, 'render_resolution')
        layout.separator()

        layout.prop(self, 'save')
        if self.save:
            layout.prop(self, 'overwrite')
            layout.prop(self, 'downscale_to_size')

    def execute(self, context):
        for obj in sorted(context.selected_objects[:], key=lambda o: o.name):
            if obj.type not in ('MESH', 'CURVE'):
                continue
            if not self.overwrite and get_thumbnail_path(obj).exists():
                continue
            filepath = render_widget(
                context,
                obj,
                focus_view=self.focus_view,
                color=self.color,
                thickness=self.thickness,
                margin=self.margin,
                save=self.save,
                render_resolution=self.render_resolution,
                downscale_to_size=self.downscale_to_size,
            )
            if filepath:
                self.report({'INFO'}, f"Rendered thumbnail: {filepath}")
            else:
                self.report({'INFO'}, f"Rendered thumbnail.")
        return {'FINISHED'}

def render_widget(
        context,
        object: Object,
        *,
        focus_view=True,
        color=(1, 1, 1),
        thickness=0.01,
        margin=10,
        save=True,
        render_resolution=(512, 512),
        downscale_to_size=256,
    ) -> str:
    with (
        viewport_settings(context, light='FLAT', color_type='SINGLE', single_color=color, resolution=render_resolution),
        widget_geonodes([object], thickness=thickness),
        focus_objects(context, [object], margin=0.2) if focus_view else nullcontext()
    ):
        bpy.ops.render.opengl()
        redraw_viewport()
        render_result = bpy.data.images.get('Render Result')
        if save:
            full_path = get_thumbnail_path(object)

            img_processor = ImageProcessor(render_result, widget_name(object.name))
            img_processor.crop_to_square_content(margin=margin)
            img_processor.downscale_to_fit(downscale_to_size)
            img_processor.save(full_path.as_posix())

            return full_path.as_posix()
        else:
            return ""

def get_thumbnail_path(obj) -> Path:
    this_dir = Path(bpy.data.filepath).parent
    thumbnails_dir = this_dir / Path("thumbnails")
    filename = widget_name(obj.name) + ".png"
    return thumbnails_dir / Path(filename)

class ImageProcessor:
    def __init__(self, bpy_img: bpy.types.Image, name: str):
        self.width = bpy_img.size[0]
        self.height = bpy_img.size[1]
        self.bpy_img = bpy_img
        self._pixels = []
        self._pixels_rgba = []

        if bpy_img.type == "RENDER_RESULT":
            filepath = os.path.join(bpy.app.tempdir, f"cr_thumb_{name}.png")
            bpy_img.save_render(filepath)
            self.bpy_img = bpy.data.images.load(filepath)
            self.width, self.height = self.bpy_img.size

    def crop_to_square_content(self, margin=10) -> bool:
        """
        Crops the image to a square by removing empty rows/columns while
        ensuring the final image remains square. Useful for asset thumbnails.
        """
        if not self.pixels_rgba:
            return False  # No pixels to process

        # Convert 1D pixel list into a 2D list (rows of pixels)
        pixel_rows = [self.pixels_rgba[h * self.width:(h+1) * self.width] for h in range(self.height)]

        # Find the bounding box of non-transparent pixels
        min_x, max_x = self.width, 0
        min_y, max_y = self.height, 0

        for y, row in enumerate(pixel_rows):
            for x, pixel in enumerate(row):
                if pixel[3] > 0:  # If alpha > 0 (not transparent)
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)

        # If the image is fully transparent, return an empty square
        if max_x < min_x or max_y < min_y:
            self.width = self.height = 0
            self.pixels_rgba = []
            return False

        # Add the margin.
        max_x += margin
        min_x -= margin
        max_y += margin
        min_y -= margin

        # Calculate the bounding box width and height
        content_width = (max_x - min_x)
        content_height = (max_y - min_y)

        # Determine the square size
        square_size = max(content_width, content_height)
        if square_size == self.width:
            return False

        for i in range(max(0, square_size - self.width)):
            for row in pixel_rows:
                row.append((0, 0, 0, 0))
        extra_height = max(0, square_size - self.height)
        for y in range(extra_height):
            pixel_rows.append([(0, 0, 0, 0) for x in range(max(self.width, square_size))])

        # Extract the square pixels
        pixel_rows = [row[min_x:max_x] for row in pixel_rows[min_y:max_y]]

        row_of_nothing = [(0, 0, 0, 0) for x in range(len(pixel_rows[0]))]
        for i in range(square_size-content_height):
            if i % 2 == 0:
                pixel_rows.insert(0, row_of_nothing)
            else:
                pixel_rows.append(row_of_nothing)

        for i in range(square_size-content_width):
            for row in pixel_rows:
                if i % 2 == 0:
                    row.insert(0, (0, 0, 0, 0))
                else:
                    row.append((0, 0, 0, 0))

        # Update image data
        self.width = square_size
        self.height = square_size
        pixels_rgba = [pixel for row in pixel_rows for pixel in row]
        self.pixels_rgba = pixels_rgba
        return True

    def downscale_to_fit(self, max_size=256):
        """
        Downscale the image so that its width and height do not exceed max_size.
        The aspect ratio is preserved.
        """

        if self.width == 0 or self.height == 0:
            return
        if self.width <= max_size and self.height <= max_size:
            return
        scale = min([max_size / self.width, max_size / self.height])

        if scale >= 1:
            return

        new_width = int(self.width * scale)
        new_height = int(self.height * scale)

        # Downscale using nearest-neighbor sampling
        downsampled_pixels = []
        for y in range(new_height):
            orig_y = int(y / scale)
            for x in range(new_width):
                orig_x = int(x / scale)
                downsampled_pixels.append(self.pixels_rgba[orig_y * self.width + orig_x])

        # Update image properties
        self.width, self.height = new_width, new_height
        self.pixels_rgba = downsampled_pixels

    @property
    def pixels(self):
        return [channel for pixel in self.pixels_rgba for channel in pixel]

    @property
    def pixels_rgba(self):
        try:
            if self.bpy_img:
                self.bpy_img.name
        except ReferenceError:
            # Image has been removed.
            return []
        if not self._pixels_rgba:
            # NOTE: Careful! Accessing bpy_img.pixels is very slow! Do this only when needed!
            if self.bpy_img:
                pixels = self.bpy_img.pixels[:]
            else:
                pixels = self._pixels
            self._pixels_rgba = [tuple(pixels[i:i+4]) for i in range(0, len(pixels), 4)]
        return self._pixels_rgba

    @pixels_rgba.setter
    def pixels_rgba(self, value):
        self._pixels_rgba = value

    def save(self, filepath: str, discard=True):
        # First push pixel data back into our bpy_img, then use bpy to save image.
        self.bpy_img.scale(self.width, self.height)
        self.bpy_img.pixels = self.pixels
        self.bpy_img.save_render(filepath)
        if discard:
            bpy.data.images.remove(self.bpy_img)
            self.bpy_img = None

def draw_menu(self, context):
    self.layout.operator(VIEW3D_OT_render_widget_thumbnails.bl_idname)

registry = [VIEW3D_OT_render_widget_thumbnails]

def register():
    bpy.types.VIEW3D_MT_view.append(draw_menu)

def unregister():
    bpy.types.VIEW3D_MT_view.remove(draw_menu)
