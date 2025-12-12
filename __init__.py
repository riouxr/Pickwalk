bl_info = {
    "name": "Screen-Based Vertex/Face Walker",
    "author": "ChatGPT",
    "version": (3, 1),
    "blender": (4, 2, 0),  # Updated min version for extension support
    "location": "Edit Mode > CTRL + Arrow Keys",
    "description": "Pick-walk vertices or faces based on screen direction (per-element walking)",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy_extras import view3d_utils


# ============================================================
# Addon Preferences (keys only)
# ============================================================

class VWALK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__  # Dynamic for extensions (matches manifest id)

    key_items = [
        ('UP_ARROW', "Up Arrow", ""),
        ('DOWN_ARROW', "Down Arrow", ""),
        ('LEFT_ARROW', "Left Arrow", ""),
        ('RIGHT_ARROW', "Right Arrow", ""),
        ('W', "W Key", ""),
        ('A', "A Key", ""),
        ('S', "S Key", ""),
        ('D', "D Key", ""),
        ('NUMPAD_8', "Numpad 8", ""),
        ('NUMPAD_2', "Numpad 2", ""),
        ('NUMPAD_4', "Numpad 4", ""),
        ('NUMPAD_6', "Numpad 6", ""),
    ]

    key_up: bpy.props.EnumProperty(name="Move Up", items=key_items, default='UP_ARROW')
    key_down: bpy.props.EnumProperty(name="Move Down", items=key_items, default='DOWN_ARROW')
    key_left: bpy.props.EnumProperty(name="Move Left", items=key_items, default='LEFT_ARROW')
    key_right: bpy.props.EnumProperty(name="Move Right", items=key_items, default='RIGHT_ARROW')

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Pick-Walk Keys:")
        col.prop(self, "key_up")
        col.prop(self, "key_down")
        col.prop(self, "key_left")
        col.prop(self, "key_right")


# ============================================================
# View helpers
# ============================================================

def get_view_region_rv3d(context):
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
    """Return the best neighbor vert for v in given direction, or None."""
    aworld = mw @ v.co
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aworld)
    if a2d is None:
        return None

    best = None
    best_score = None

    for e in v.link_edges:
        nv = e.other_vert(v)
        vworld = mw @ nv.co
        v2d = view3d_utils.location_3d_to_region_2d(region, rv3d, vworld)
        if v2d is None:
            continue

        delta = v2d - a2d
        if delta.length == 0:
            continue

        dot = delta.normalized().dot(direction_vector)
        if dot < 0.3:
            continue

        dist = delta.length
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

    # Build final selection (Q2 = M3):
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
    """Return the best neighbor face for f in given direction, or None."""
    aworld = mw @ f.calc_center_median()
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aworld)
    if a2d is None:
        return None

    neighbor_faces = set()
    for e in f.edges:
        for nf in e.link_faces:
            if nf is not f:
                neighbor_faces.add(nf)

    best = None
    best_score = None

    for nf in neighbor_faces:
        fworld = mw @ nf.calc_center_median()
        f2d = view3d_utils.location_3d_to_region_2d(region, rv3d, fworld)
        if f2d is None:
            continue

        delta = f2d - a2d
        if delta.length == 0:
            continue

        dot = delta.normalized().dot(direction_vector)
        if dot < 0.3:
            continue

        dist = delta.length
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
# Dispatcher with MIX2 rule
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

    # -------------------------------------------------------
    # 1) Pure vertex mode: ignore any face selection entirely
    # -------------------------------------------------------
    if vert_mode and not face_mode:
        if not selected_verts:
            op.report({'WARNING'}, "No vertices selected.")
            return {'CANCELLED'}
        return walk_vertices(context, direction_vector)

    # -------------------------------------------------------
    # 2) Pure face mode: ignore any vertex selection entirely
    # -------------------------------------------------------
    if face_mode and not vert_mode:
        if not selected_faces:
            op.report({'WARNING'}, "No faces selected.")
            return {'CANCELLED'}
        return walk_faces(context, direction_vector)

    # -------------------------------------------------------
    # 3) Both vertex and face mode enabled (rare but possible)
    #    Here we enforce MIX2: disallow true mixed selection.
    # -------------------------------------------------------
    if vert_mode and face_mode:
        if selected_verts and selected_faces:
            op.report(
                {'WARNING'},
                "Mixed vertex/face selection not supported. "
                "Please select only vertices OR only faces."
            )
            return {'CANCELLED'}

        # If only verts are actually selected, walk verts
        if selected_verts:
            return walk_vertices(context, direction_vector)

        # If only faces are actually selected, walk faces
        if selected_faces:
            return walk_faces(context, direction_vector)

        op.report({'WARNING'}, "Nothing selected.")
        return {'CANCELLED'}

    # -------------------------------------------------------
    # 4) No vertex or face mode apparently active
    # -------------------------------------------------------
    op.report({'WARNING'}, "Use Vertex or Face select mode.")
    return {'CANCELLED'}


# ============================================================
# Operators
# ============================================================

class VWALK_OT_up(bpy.types.Operator):
    bl_idname = "mesh.vwalk_up"
    bl_label = "Walk Up"

    def execute(self, context):
        return walk_dispatch(self, context, (0, 1))


class VWALK_OT_down(bpy.types.Operator):
    bl_idname = "mesh.vwalk_down"
    bl_label = "Walk Down"

    def execute(self, context):
        return walk_dispatch(self, context, (0, -1))


class VWALK_OT_left(bpy.types.Operator):
    bl_idname = "mesh.vwalk_left"
    bl_label = "Walk Left"

    def execute(self, context):
        return walk_dispatch(self, context, (-1, 0))


class VWALK_OT_right(bpy.types.Operator):
    bl_idname = "mesh.vwalk_right"
    bl_label = "Walk Right"

    def execute(self, context):
        return walk_dispatch(self, context, (1, 0))


# ============================================================
# Keymaps
# ============================================================

addon_keymaps = []


def register_keymaps():
    prefs = bpy.context.preferences.addons[__package__].preferences  # Dynamic for extensions
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")

    def add(op, key):
        kmi = km.keymap_items.new(op, key, 'PRESS', ctrl=True)
        addon_keymaps.append((km, kmi))

    add("mesh.vwalk_up", prefs.key_up)
    add("mesh.vwalk_down", prefs.key_down)
    add("mesh.vwalk_left", prefs.key_left)
    add("mesh.vwalk_right", prefs.key_right)


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


# ============================================================
# Registration
# ============================================================

classes = (
    VWALK_Preferences,
    VWALK_OT_up,
    VWALK_OT_down,
    VWALK_OT_left,
    VWALK_OT_right,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in classes:
        bpy.utils.unregister_class(cls)