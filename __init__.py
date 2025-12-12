bl_info = {
    "name": "Screen-Based Vertex/Face Walker (Gesture)",
    "author": "Blender Bob & ChatGPT",
    "version": (4, 0),
    "blender": (4, 2, 0),
    "location": "Edit Mode > CTRL + MMB swipe",
    "description": "Pick-walk vertices or faces based on screen direction using a mouse gesture",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy_extras import view3d_utils


# ============================================================
# View helpers
# ============================================================

def get_view_region_rv3d(context):
    """Return (region, rv3d) for the first VIEW_3D window region."""
    win = context.window
    if not win:
        return None, None
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    return region, area.spaces.active.region_3d
    return None, None


# ============================================================
# Per-element walking: vertices
# ============================================================

def walk_single_vertex(v, bm, mw, region, rv3d, direction_vector):
    """
    Return the best neighbor vert for v in given direction,
    using strict quadrant logic.
    """
    aworld = mw @ v.co
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aworld)
    if a2d is None:
        return None

    dir_x, dir_y = direction_vector
    best = None
    best_score = None

    for e in v.link_edges:
        nv = e.other_vert(v)
        vworld = mw @ nv.co
        v2d = view3d_utils.location_3d_to_region_2d(region, rv3d, vworld)
        if v2d is None:
            continue

        delta = v2d - a2d
        dx, dy = delta.x, delta.y

        # Strict quadrant filtering
        if dir_y > 0:  # UP
            if dy <= 0 or abs(dy) < abs(dx):
                continue
        elif dir_y < 0:  # DOWN
            if dy >= 0 or abs(dy) < abs(dx):
                continue
        elif dir_x < 0:  # LEFT
            if dx >= 0 or abs(dx) < abs(dy):
                continue
        elif dir_x > 0:  # RIGHT
            if dx <= 0 or abs(dx) < abs(dy):
                continue

        dist = delta.length
        if dist == 0:
            continue

        # Score: maximize direction conformity and minimize distance
        dot = delta.normalized().dot(direction_vector)
        score = dot * 10.0 - dist

        if best_score is None or score > best_score:
            best_score = score
            best = nv

    return best


def walk_vertices(context, direction_vector):
    obj = context.edit_object
    if not obj or obj.type != 'MESH':
        return {'CANCELLED'}

    region, rv3d = get_view_region_rv3d(context)
    if region is None:
        return {'CANCELLED'}

    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    mw = obj.matrix_world

    selected_verts = [v for v in bm.verts if v.select]
    if not selected_verts:
        return {'CANCELLED'}

    active = bm.select_history.active
    if not isinstance(active, bmesh.types.BMVert) or not active.select:
        active = selected_verts[0]

    # First compute targets for ALL selected verts without changing selection
    origin_set = set(selected_verts)
    moved_origins = set()
    target_verts = set()
    active_target = None

    for v in origin_set:
        target = walk_single_vertex(v, bm, mw, region, rv3d, direction_vector)
        if target:
            target_verts.add(target)
            moved_origins.add(v)
            if v is active:
                active_target = target

    # Build final selection:
    # - moved verts → replaced by their targets
    # - non-moved verts → stay selected where they are
    final_selection = set(origin_set - moved_origins) | target_verts

    if not final_selection:
        return {'CANCELLED'}

    # Determine new active
    if active_target:
        new_active = active_target
    else:
        # If active didn't move, keep it active
        new_active = active

    # Clear all selections (verts, edges, faces)
    for v in bm.verts:
        v.select_set(False)
    for e in bm.edges:
        e.select_set(False)
    for f in bm.faces:
        f.select_set(False)

    # Apply vertex selection
    for v in final_selection:
        v.select_set(True)

    bm.select_history.clear()
    new_active.select_set(True)
    bm.select_history.add(new_active)

    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return {'FINISHED'}


# ============================================================
# Per-element walking: faces
# ============================================================

def walk_single_face(f, bm, mw, region, rv3d, direction_vector):
    """
    Return the best neighbor face for f in given direction,
    using strict quadrant logic.
    """
    aworld = mw @ f.calc_center_median()
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aworld)
    if a2d is None:
        return None

    dir_x, dir_y = direction_vector
    best = None
    best_score = None

    # Collect neighbors
    neighbor_faces = set()
    for e in f.edges:
        for nf in e.link_faces:
            if nf is not f:
                neighbor_faces.add(nf)

    for nf in neighbor_faces:
        fworld = mw @ nf.calc_center_median()
        f2d = view3d_utils.location_3d_to_region_2d(region, rv3d, fworld)
        if f2d is None:
            continue

        delta = f2d - a2d
        dx, dy = delta.x, delta.y

        # Strict quadrant filtering
        if dir_y > 0:  # UP
            if dy <= 0 or abs(dy) < abs(dx):
                continue
        elif dir_y < 0:  # DOWN
            if dy >= 0 or abs(dy) < abs(dx):
                continue
        elif dir_x < 0:  # LEFT
            if dx >= 0 or abs(dx) < abs(dy):
                continue
        elif dir_x > 0:  # RIGHT
            if dx <= 0 or abs(dx) < abs(dy):
                continue

        dist = delta.length
        if dist == 0:
            continue

        # Score inside allowed quadrant
        dot = delta.normalized().dot(direction_vector)
        score = dot * 10.0 - dist

        if best_score is None or score > best_score:
            best_score = score
            best = nf

    return best


def walk_faces(context, direction_vector):
    obj = context.edit_object
    if not obj or obj.type != 'MESH':
        return {'CANCELLED'}

    region, rv3d = get_view_region_rv3d(context)
    if region is None:
        return {'CANCELLED'}

    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    mw = obj.matrix_world

    selected_faces = [f for f in bm.faces if f.select]
    if not selected_faces:
        return {'CANCELLED'}

    active = bm.select_history.active
    if not isinstance(active, bmesh.types.BMFace) or not active.select:
        active = selected_faces[0]

    origin_set = set(selected_faces)
    moved_origins = set()
    target_faces = set()
    active_target = None

    for f in origin_set:
        target = walk_single_face(f, bm, mw, region, rv3d, direction_vector)
        if target:
            target_faces.add(target)
            moved_origins.add(f)
            if f is active:
                active_target = target

    final_selection = set(origin_set - moved_origins) | target_faces

    if not final_selection:
        return {'CANCELLED'}

    if active_target:
        new_active = active_target
    else:
        new_active = active

    # Clear all selections (verts, edges, faces)
    for v in bm.verts:
        v.select_set(False)
    for e in bm.edges:
        e.select_set(False)
    for f in bm.faces:
        f.select_set(False)

    # Apply face selection
    for f in final_selection:
        f.select_set(True)

    bm.select_history.clear()
    new_active.select_set(True)
    bm.select_history.add(new_active)

    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return {'FINISHED'}


# ============================================================
# Dispatcher (MIX2 rule preserved)
# ============================================================

def walk_dispatch(op, context, direction_vector):
    obj = context.edit_object
    if not obj or obj.type != 'MESH':
        op.report({'WARNING'}, "No mesh in Edit Mode.")
        return {'CANCELLED'}

    me = obj.data
    bm = bmesh.from_edit_mesh(me)

    vert_mode, edge_mode, face_mode = context.tool_settings.mesh_select_mode

    if edge_mode:
        op.report({'WARNING'}, "Edge walking is not supported by Screen-Based Walker.")
        return {'CANCELLED'}

    # Read the raw selection once
    selected_verts = [v for v in bm.verts if v.select]
    selected_faces = [f for f in bm.faces if f.select]

    # 1) Pure vertex mode: ignore face selection
    if vert_mode and not face_mode:
        if not selected_verts:
            op.report({'WARNING'}, "No vertices selected.")
            return {'CANCELLED'}
        return walk_vertices(context, direction_vector)

    # 2) Pure face mode: ignore vertex selection
    if face_mode and not vert_mode:
        if not selected_faces:
            op.report({'WARNING'}, "No faces selected.")
            return {'CANCELLED'}
        return walk_faces(context, direction_vector)

    # 3) Both vertex and face mode enabled (MIX2 rule)
    if vert_mode and face_mode:
        if selected_verts and selected_faces:
            op.report(
                {'WARNING'},
                "Mixed vertex/face selection not supported. "
                "Please select only vertices OR only faces."
            )
            return {'CANCELLED'}

        if selected_verts:
            return walk_vertices(context, direction_vector)

        if selected_faces:
            return walk_faces(context, direction_vector)

        op.report({'WARNING'}, "Nothing selected.")
        return {'CANCELLED'}

    # 4) No vertex or face mode apparently active
    op.report({'WARNING'}, "Use Vertex or Face select mode.")
    return {'CANCELLED'}


# ============================================================
# Gesture operator (CTRL + MMB, 4 directions)
# ============================================================

class VWALK_OT_gesture(bpy.types.Operator):
    bl_idname = "mesh.vwalk_gesture"
    bl_label = "Gesture Pick Walk"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    start_mouse: bpy.props.IntVectorProperty(size=2)

    def modal(self, context, event):
        # ESC / RMB: cancel
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'CANCELLED'}

        # MMB release ends the gesture
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            dx = event.mouse_region_x - self.start_mouse[0]
            dy = event.mouse_region_y - self.start_mouse[1]

            # Ignore tiny movements
            if abs(dx) < 6 and abs(dy) < 6:
                return {'CANCELLED'}

            # Determine primary direction (4-way)
            if abs(dx) > abs(dy):
                # Horizontal swipe
                if dx > 0:
                    direction = (1, 0)   # RIGHT / EAST
                else:
                    direction = (-1, 0)  # LEFT / WEST
            else:
                # Vertical swipe
                if dy > 0:
                    direction = (0, 1)   # UP / NORTH
                else:
                    direction = (0, -1)  # DOWN / SOUTH

            return walk_dispatch(self, context, direction)

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Gesture walker works only in Edit Mesh mode.")
            return {'CANCELLED'}

        if event.type == 'MIDDLEMOUSE' and event.ctrl:
            self.start_mouse = (event.mouse_region_x, event.mouse_region_y)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}


# ============================================================
# Keymaps
# ============================================================

addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km.keymap_items.new(
        VWALK_OT_gesture.bl_idname,
        'MIDDLEMOUSE',
        'PRESS',
        ctrl=True,
    )
    addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


# ============================================================
# Registration
# ============================================================

classes = (
    VWALK_OT_gesture,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in classes:
        bpy.utils.unregister_class(cls)
