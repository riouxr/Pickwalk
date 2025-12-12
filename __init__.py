bl_info = {
    "name": "Screen-Based Vertex/Face Walker",
    "author": "Blender Bob",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "Edit Mode → CTRL + Arrows",
    "description": "Pick-walk vertices and faces based on screen direction.",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy_extras import view3d_utils


# ============================================================
# Addon Preferences
# ============================================================

class VWALK_Preferences(bpy.types.AddonPreferences):
    bl_idname = "screen_vertex_face_walker"

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
        col.label(text="Pick-Walk Hotkeys (CTRL + arrows):")
        col.prop(self, "key_up")
        col.prop(self, "key_down")
        col.prop(self, "key_left")
        col.prop(self, "key_right")


# ============================================================
# Helper: Get 3D View region & rv3d
# ============================================================

def get_view(context):
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
# Vertex walking (per-element)
# ============================================================

def walk_single_vertex(v, bm, mw, region, rv3d, direction_vector):
    aw = mw @ v.co
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aw)
    if a2d is None:
        return None

    best = None
    best_score = None

    for e in v.link_edges:
        nv = e.other_vert(v)
        nw = mw @ nv.co
        n2d = view3d_utils.location_3d_to_region_2d(region, rv3d, nw)
        if n2d is None:
            continue

        delta = n2d - a2d
        if delta.length == 0:
            continue

        dot = delta.normalized().dot(direction_vector)
        if dot < 0.3:
            continue

        score = dot * 10.0 - delta.length

        if best_score is None or score > best_score:
            best_score = score
            best = nv

    return best


def walk_vertices(context, direction_vector):
    region, rv3d = get_view(context)
    obj = context.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    mw = obj.matrix_world

    selected = [v for v in bm.verts if v.select]
    active = bm.select_history.active
    if not isinstance(active, bmesh.types.BMVert) or not active.select:
        active = selected[0]

    targets = set()
    unmoved = set()
    new_active = None

    # First pass, no selection changes
    for v in selected:
        t = walk_single_vertex(v, bm, mw, region, rv3d, direction_vector)
        if t:
            targets.add(t)
            if v is active:
                new_active = t
        else:
            unmoved.add(v)

    final = targets | unmoved

    if not new_active:
        new_active = active

    # Apply selection
    for v in bm.verts:
        v.select_set(False)
    for v in final:
        v.select_set(True)

    bm.select_history.clear()
    new_active.select_set(True)
    bm.select_history.add(new_active)

    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return {'FINISHED'}


# ============================================================
# Face walking (per-element)
# ============================================================

def walk_single_face(f, bm, mw, region, rv3d, direction_vector):
    aw = mw @ f.calc_center_median()
    a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, aw)
    if a2d is None:
        return None

    neighbors = set()
    for e in f.edges:
        for nf in e.link_faces:
            if nf is not f:
                neighbors.add(nf)

    best = None
    best_score = None

    for nf in neighbors:
        nw = mw @ nf.calc_center_median()
        n2d = view3d_utils.location_3d_to_region_2d(region, rv3d, nw)
        if n2d is None:
            continue

        delta = n2d - a2d
        if delta.length == 0:
            continue

        dot = delta.normalized().dot(direction_vector)
        if dot < 0.3:
            continue

        score = dot * 10.0 - delta.length

        if best_score is None or score > best_score:
            best_score = score
            best = nf

    return best


def walk_faces(context, direction_vector):
    region, rv3d = get_view(context)
    obj = context.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    mw = obj.matrix_world

    selected = [f for f in bm.faces if f.select]
    active = bm.select_history.active
    if not isinstance(active, bmesh.types.BMFace) or not active.select:
        active = selected[0]

    targets = set()
    unmoved = set()
    new_active = None

    for f in selected:
        t = walk_single_face(f, bm, mw, region, rv3d, direction_vector)
        if t:
            targets.add(t)
            if f is active:
                new_active = t
        else:
            unmoved.add(f)

    final = targets | unmoved

    if not new_active:
        new_active = active

    # Apply selection
    for f in bm.faces:
        f.select_set(False)
    for f in final:
        f.select_set(True)

    bm.select_history.clear()
    new_active.select_set(True)
    bm.select_history.add(new_active)

    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return {'FINISHED'}


# ============================================================
# Dispatcher with AUTO-CLEANUP
# ============================================================

def walk_dispatch(op, context, direction_vector):
    obj = context.edit_object
    if not obj or obj.type != 'MESH':
        op.report({'WARNING'}, "No mesh in Edit Mode.")
        return {'CANCELLED'}

    bm = bmesh.from_edit_mesh(obj.data)

    vert_mode, edge_mode, face_mode = context.tool_settings.mesh_select_mode

    if edge_mode:
        op.report({'WARNING'}, "Edge walking is not supported.")
        return {'CANCELLED'}

    # Auto-cleanup to avoid ghost selections
    if vert_mode and not face_mode:
        for f in bm.faces:
            f.select_set(False)

    if face_mode and not vert_mode:
        for v in bm.verts:
            v.select_set(False)

    # Recompute selection
    selected_verts = [v for v in bm.verts if v.select]
    selected_faces = [f for f in bm.faces if f.select]

    # MIX2: Only error if BOTH modes are active AND both contain elements
    if vert_mode and face_mode:
        if selected_verts and selected_faces:
            op.report({'WARNING'},
                      "Mixed vertex/face selection not supported.")
            return {'CANCELLED'}

    # Vertex mode
    if vert_mode and not face_mode:
        if not selected_verts:
            op.report({'WARNING'}, "No vertices selected.")
            return {'CANCELLED'}
        return walk_vertices(context, direction_vector)

    # Face mode
    if face_mode and not vert_mode:
        if not selected_faces:
            op.report({'WARNING'}, "No faces selected.")
            return {'CANCELLED'}
        return walk_faces(context, direction_vector)

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
    prefs = bpy.context.preferences.addons[__name__].preferences
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D", region_type="WINDOW")

    def add(key, op):
        kmi = km.keymap_items.new(
            op, key, 'PRESS', ctrl=True
        )
        addon_keymaps.append((km, kmi))

    add(prefs.key_up, "mesh.vwalk_up")
    add(prefs.key_down, "mesh.vwalk_down")
    add(prefs.key_left, "mesh.vwalk_left")
    add(prefs.key_right, "mesh.vwalk_right")


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
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
