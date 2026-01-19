# This script is loaded in Widgets.blend and does some automated housekeeping there.

import math
from collections import defaultdict
from pathlib import Path

import bpy
from bpy.types import MeshVertex


def pre_save(scene, context):
    widgets = [o for o in bpy.data.objects if o.name.startswith("WGT-")]
    row_max = int(math.sqrt(len(widgets)))
    spacing = 3
    for i, obj in enumerate(widgets):
        # Nuke custom properties
        for key in list(obj.keys()):
            del obj[key]
        for key in list(obj.data.keys()):
            del obj.data[key]

        # Sort into a grid
        col = i % row_max
        row = int(i / row_max)
        obj.location.x = row * spacing
        obj.location.y = col * spacing
        obj.location.z = 0
        obj.rotation_euler = (0, 0, 0)
        obj.scale = (1, 1, 1)
        if max(obj.dimensions) - 1.0 > 0.01:
            print("Warning: Widget object's longest dimension should be 1m: ", obj.name, obj.dimensions)

        # Nuke attributes
        if obj.data and hasattr(obj.data, 'attributes'):
            for attr in obj.data.attributes:
                if not attr.is_required:
                    obj.data.attributes.remove(attr)

        # Nuke add-on properties
        for key in obj.bl_rna.properties.keys():
            prop = obj.bl_rna.properties[key]
            if prop.is_runtime and not prop.is_required:
                obj.property_unset(key)

        # Sort mesh topologies
        rebuild_mesh_topology(obj)
        obj.data.name = "Data_" + obj.name

def rebuild_mesh_topology(obj: bpy.types.Object):
    """
    Rebuild a mesh with deterministic vertex and edge ordering.
    WARNING: All vertex and edge data will be lost. Only useful for widgets!
    Only matters for the ability to draw dashed lines.
    """
    mesh = obj.data

    # Build adjacency map
    adjacency = defaultdict(list)
    for edge in mesh.edges:
        vert_a, vert_b = edge.vertices
        adjacency[vert_a].append(vert_b)
        adjacency[vert_b].append(vert_a)

    visited_vertices = set()
    ordered_vertices = []
    new_edges = []
    visited_edges = set()  # store (min(vert_a,vert_b), max(v0,vert_b)) to avoid duplicates

    def pick_start_vertex(component_vertices: list[MeshVertex], is_loop: bool) -> MeshVertex:
        """Pick starting vertex according to heuristics."""
        if is_loop:
            # Closed loop: vertex with minimal coordinates
            return min(component_vertices, key=lambda i: sum(mesh.vertices[i].co))
        else:
            # Open line: pick minimal-coordinate endpoint
            endpoints = [v for v in component_vertices if len(adjacency[v]) == 1]
            if endpoints:
                return min(endpoints, key=lambda i: sum(mesh.vertices[i].co))
            return min(component_vertices, key=lambda i: sum(mesh.vertices[i].co))

    def walk_component(start: MeshVertex):
        """Deterministic walk along a component starting from `start`."""
        comp_order = []
        prev = None
        cur = start
        while cur not in visited_vertices:
            comp_order.append(cur)
            visited_vertices.add(cur)
            neighbors = [v for v in adjacency[cur] if v != prev and v not in visited_vertices]
            if not neighbors:
                break
            prev, cur = cur, neighbors[0]
        return comp_order

    # Walk all components
    for vert in range(len(mesh.vertices)):
        if vert in visited_vertices:
            continue

        # Discover all vertices in this component
        queue = [vert]
        component_vertices = set()
        while queue:
            comp_vert = queue.pop()
            if comp_vert in component_vertices:
                continue
            component_vertices.add(comp_vert)
            for adjacent_vert in adjacency[comp_vert]:
                if adjacent_vert not in component_vertices:
                    queue.append(adjacent_vert)
        component_vertices = list(component_vertices)
        if not component_vertices:
            continue

        # Determine if component is a loop: every vertex degree == 2 and more than 2 vertices
        is_loop = all(len(adjacency[cv]) == 2 for cv in component_vertices) and len(component_vertices) > 2

        # Pick start vertex
        start_vertex = pick_start_vertex(component_vertices, is_loop)

        # Walk the component deterministically
        comp_order = walk_component(start_vertex)
        if not comp_order:
            continue

        base_idx = len(ordered_vertices)
        ordered_vertices.extend(comp_order)
        comp_vert_map = {old_idx: base_idx + i for i, old_idx in enumerate(comp_order)}

        # Add consecutive edges along walk
        for i in range(len(comp_order) - 1):
            edge = (comp_order[i], comp_order[i + 1])
            key = tuple(sorted(edge))
            if key not in visited_edges:
                new_edges.append((comp_vert_map[edge[0]], comp_vert_map[edge[1]]))
                visited_edges.add(key)

        # Add closing edge for loops
        if is_loop:
            edge = (comp_order[-1], comp_order[0])
            key = tuple(sorted(edge))
            if key not in visited_edges:
                new_edges.append((comp_vert_map[edge[0]], comp_vert_map[edge[1]]))
                visited_edges.add(key)

    # Add any vertices not yet in ordered_vertices
    for i in range(len(mesh.vertices)):
        if i not in ordered_vertices:
            ordered_vertices.append(i)

    # Build global vertex map
    vert_map = {old_idx: new_idx for new_idx, old_idx in enumerate(ordered_vertices)}

    # Add leftover edges
    for edge in mesh.edges:
        vert_a, vert_b = edge.vertices
        key = tuple(sorted((vert_a, vert_b)))
        if key not in visited_edges:
            new_edges.append((vert_map[vert_a], vert_map[vert_b]))
            visited_edges.add(key)

    # Rebuild vertices
    new_verts = [mesh.vertices[i].co.copy() for i in ordered_vertices]

    # Rebuild faces
    new_faces = []
    for p in mesh.polygons:
        if all(v in vert_map for v in p.vertices):
            new_faces.append([vert_map[v] for v in p.vertices])

    # Create new mesh
    new_mesh = bpy.data.meshes.new(mesh.name + "_sorted")
    new_mesh.from_pydata(new_verts, new_edges, new_faces)
    new_mesh.update()
    obj.data = new_mesh

def set_filebrowser_path():
    file_browser = next((a for a in bpy.context.screen.areas if a.type=='FILE_BROWSER'), None)
    if not file_browser:
        return 0.2
    thumb_dir = Path(bpy.data.filepath).parent / Path("thumbnails")
    file_browser.spaces.active.params.directory = thumb_dir.as_posix().encode("utf-8")

def load_post(scene, context):
    bpy.app.timers.register(set_filebrowser_path, first_interval=0.2)

bpy.app.handlers.save_pre.append(pre_save)
bpy.app.handlers.load_post.append(load_post)
