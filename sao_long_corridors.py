"""
sao_long_corridors.py

Генератор системи довгих готичних коридорів Вежі-Лабіринту 1-го поверху Айнкраду (SAO)
для Blender 5.3 (сумісний з 4.2+) та експорту в Roblox Studio (.fbx).

Що зроблено під Roblox:
  * кожен коридор/вузол розбитий на окремі частини (підлога, стіни, склепіння) —
    Roblox будує колізію MeshPart як опуклі оболонки, і порожнистий коридор одним
    мешем "заливається" колізією всередині (персонаж не може зайти);
  * FBX у метрах, Y-up, тріангульований, без кісток/анімації, з UV-розгорткою;
  * файл зберігається в теку з правом запису (ніколи не в C:\\Program Files),
    а шлях показується у спливному вікні та в системній консолі;
  * перевірка ліміту трикутників на кожен об'єкт.

Запуск: Blender → Scripting → Open → Run Script
        або: blender -b -P sao_long_corridors.py -- --output D:/roblox/sao_long_corridors.fbx
"""

import math
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Matrix, Vector

# ==============================================================================
# КОНСТАНТИ НАЛАШТУВАННЯ (1 одиниця Blender = 1 метр)
# ==============================================================================

EXPORT_FILENAME = "sao_long_corridors.fbx"
EXPORT_DIR = ""            # "" → поруч із .blend / скриптом, інакше ~/Documents
AUTO_EXPORT_FBX = True

SEGMENT_LEN = 8.0          # Базовий крок модуля (8 м)
CORRIDOR_OUTER_W = 8.0     # Зовнішня ширина коридору (8 м)
PASSAGE_WIDTH = 6.0        # Внутрішня ширина проходу (6 м, стіни по 1 м)
WALL_HEIGHT = 7.5          # Висота стін (7.5 м)
VAULT_HEIGHT = 2.0         # Висота стрілчастого склепіння над стінами (разом 9.5 м)
FLOOR_THICKNESS = 0.5      # Товщина підлоги

MAX_TRIS_PER_OBJECT = 5000
UV_SCALE = 0.5             # Box-UV: 1 тайл текстури = 2 м

# ==============================================================================
# ОЧИЩЕННЯ СЦЕНИ ТА КОЛЕКЦІЇ
# ==============================================================================

def reset_scene() -> None:
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    # Після масового видалення список view layer оновлюється ліниво — синхронізуємо.
    bpy.context.view_layer.update()


def get_or_create_collection(name: str) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    return col


# ==============================================================================
# МАТЕРІАЛИ (PRINCIPLED BSDF)
# ==============================================================================

def create_material(
    name: str,
    color: tuple[float, float, float, float],
    metallic: float = 0.0,
    roughness: float = 0.82,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    if mat.node_tree is None:  # лише для старих збірок; у 5.x вузли створюються самі
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    # Шукаємо за типом, а не за назвою (назви вузлів можуть бути перекладені).
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        nodes.clear()
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = nodes.new("ShaderNodeOutputMaterial")
        out.location = (300, 0)
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def set_input(key, value):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = value

    set_input("Base Color", color)
    set_input("Metallic", metallic)
    set_input("Roughness", roughness)
    if emission and emission_strength > 0.0:
        set_input("Emission Color", emission)
        set_input("Emission Strength", emission_strength)
    # Колір вʼюпорту + запасні значення, які читає FBX-експортер.
    mat.diffuse_color = color
    mat.metallic = metallic
    mat.roughness = roughness
    return mat


def build_materials() -> dict[str, bpy.types.Material]:
    return {
        "stone": create_material("Mat_Obsidian_Stone", (0.13, 0.14, 0.17, 1.0), 0.0, 0.85),
        "trim": create_material("Mat_Gothic_Trim", (0.21, 0.23, 0.26, 1.0), 0.0, 0.76),
        "floor": create_material("Mat_Slate_Floor", (0.17, 0.19, 0.21, 1.0), 0.0, 0.80),
        "iron": create_material("Mat_Dark_Iron", (0.18, 0.18, 0.20, 1.0), 0.85, 0.50),
        "wood": create_material("Mat_Torch_Wood", (0.15, 0.09, 0.05, 1.0), 0.0, 0.75),
        "flame": create_material(
            "Mat_Torch_Flame",
            (1.0, 0.48, 0.10, 1.0),
            0.0,
            0.3,
            emission=(1.0, 0.45, 0.08, 1.0),
            emission_strength=4.5,
        ),
    }


# ==============================================================================
# ДОПОМІЖНІ ФУНКЦІЇ BMESH
# ==============================================================================

def _assign_material(bm: bmesh.types.BMesh, verts, mat_index: int) -> None:
    vert_set = set(verts)
    for f in {f for v in vert_set for f in v.link_faces}:
        if all(v in vert_set for v in f.verts):
            f.material_index = mat_index


def bm_add_box(
    bm: bmesh.types.BMesh,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    mat_index: int = 0,
    matrix: Matrix | None = None,
) -> None:
    sx, sy, sz = size
    xform = Matrix.Translation(center) @ Matrix.Diagonal((sx, sy, sz, 1.0))
    if matrix is not None:
        xform = matrix @ xform
    ret = bmesh.ops.create_cube(bm, size=1.0, matrix=xform)
    _assign_material(bm, ret["verts"], mat_index)


def add_box_uvs(bm: bmesh.types.BMesh) -> None:
    """Box-проєкція UV — Roblox потребує UV для текстур / SurfaceAppearance."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        axis = max(range(3), key=lambda k: abs(n[k]))
        for loop in f.loops:
            co = loop.vert.co
            u, v = ((co.y, co.z), (co.x, co.z), (co.x, co.y))[axis]
            loop[uv].uv = (u * UV_SCALE, v * UV_SCALE)


def finalize_mesh(
    bm: bmesh.types.BMesh,
    name: str,
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation_z_deg: float = 0.0,
) -> bpy.types.Object:
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    add_box_uvs(bm)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for m in materials:
        mesh.materials.append(m)
    mesh.validate(clean_customdata=False)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))
    return obj


# ==============================================================================
# БУДІВЕЛЬНІ МОДУЛІ ДОВГИХ КОРИДОРІВ
# ==============================================================================

ARCH_STEPS = 6
CEIL_THICK = 0.45


def vault_profile() -> list[Vector]:
    prof = []
    half_w = CORRIDOR_OUTER_W * 0.5
    for i in range(ARCH_STEPS + 1):
        x = -half_w + i / ARCH_STEPS * CORRIDOR_OUTER_W
        z = WALL_HEIGHT + VAULT_HEIGHT * (1.0 - (abs(x) / half_w) ** 1.35)
        prof.append(Vector((x, 0.0, z)))
    return prof


def bm_add_vault(bm: bmesh.types.BMesh, total_len: float) -> None:
    """Замкнена оболонка стрілчастого склепіння вздовж +Y (стеля — mat 0, торці — mat 1)."""
    prof_in = vault_profile()
    vs_in = [bm.verts.new((p.x, 0.0, p.z)) for p in prof_in]
    ve_in = [bm.verts.new((p.x, total_len, p.z)) for p in prof_in]
    vs_out = [bm.verts.new((p.x, 0.0, p.z + CEIL_THICK)) for p in prof_in]
    ve_out = [bm.verts.new((p.x, total_len, p.z + CEIL_THICK)) for p in prof_in]
    for i in range(ARCH_STEPS):
        bm.faces.new((vs_in[i], vs_in[i + 1], ve_in[i + 1], ve_in[i])).material_index = 0
        bm.faces.new((ve_out[i], ve_out[i + 1], vs_out[i + 1], vs_out[i])).material_index = 0
        bm.faces.new((vs_out[i], vs_out[i + 1], vs_in[i + 1], vs_in[i])).material_index = 1
        bm.faces.new((ve_in[i], ve_in[i + 1], ve_out[i + 1], ve_out[i])).material_index = 1
    bm.faces.new((vs_in[0], ve_in[0], ve_out[0], vs_out[0])).material_index = 0
    bm.faces.new((ve_in[-1], vs_in[-1], vs_out[-1], ve_out[-1])).material_index = 0


def create_long_straight_corridor(
    name: str,
    num_segments: int,
    location: tuple[float, float, float],
    rotation_z_deg: float,
    mats: dict[str, bpy.types.Material],
    col_corridors: bpy.types.Collection,
    col_props: bpy.types.Collection,
) -> None:
    """
    Довгий прямий коридор (num_segments * 8 м) вздовж локальної осі +Y.
    Origin усіх частин — центр початкового входу (X=0, Y=0, Z=0).
    Частини окремими об'єктами (для коректної колізії в Roblox):
      _Floor, _Wall_L, _Wall_R, _Vault, _ArchRibs + факели.
    """
    total_len = num_segments * SEGMENT_LEN
    half_w = CORRIDOR_OUTER_W * 0.5                     # 4.0 м
    wall_t = (CORRIDOR_OUTER_W - PASSAGE_WIDTH) * 0.5   # 1.0 м
    wall_x = half_w - wall_t * 0.5                      # 3.5 м
    place = dict(location=location, rotation_z_deg=rotation_z_deg)

    # 1. Підлога + центральна доріжка
    bm = bmesh.new()
    bm_add_box(bm, (0.0, total_len * 0.5, -FLOOR_THICKNESS * 0.5),
               (CORRIDOR_OUTER_W, total_len, FLOOR_THICKNESS), 0)
    bm_add_box(bm, (0.0, total_len * 0.5, 0.015), (PASSAGE_WIDTH - 0.6, total_len, 0.03), 1)
    finalize_mesh(bm, f"{name}_Floor", [mats["floor"], mats["trim"]], col_corridors, **place)

    # 2. Ліва / права стіни з цоколем і карнизом
    for side, suffix in ((-1.0, "L"), (1.0, "R")):
        bm = bmesh.new()
        bm_add_box(bm, (side * wall_x, total_len * 0.5, WALL_HEIGHT * 0.5),
                   (wall_t, total_len, WALL_HEIGHT), 0)
        bm_add_box(bm, (side * wall_x, total_len * 0.5, 0.35), (wall_t + 0.16, total_len, 0.70), 1)
        bm_add_box(bm, (side * wall_x, total_len * 0.5, WALL_HEIGHT - 0.25),
                   (wall_t + 0.22, total_len, 0.50), 1)
        finalize_mesh(bm, f"{name}_Wall_{suffix}", [mats["stone"], mats["trim"]], col_corridors, **place)

    # 3. Готичне стрілчасте склепіння
    bm = bmesh.new()
    bm_add_vault(bm, total_len)
    finalize_mesh(bm, f"{name}_Vault", [mats["stone"], mats["trim"]], col_corridors, **place)

    # 4. Ритмічні контрфорси-колони та аркові ребра кожні 8 м
    prof_in = vault_profile()
    bm_ribs = bmesh.new()
    for seg in range(num_segments + 1):
        y_pos = seg * SEGMENT_LEN
        if seg == 0:
            y_pos += 0.25      # крайні ребра всередину, щоб не перетиналися зі стиками
        elif seg == num_segments:
            y_pos -= 0.25
        for side in (-1.0, 1.0):
            px = side * (PASSAGE_WIDTH * 0.5 - 0.15)
            bm_add_box(bm_ribs, (px, y_pos, WALL_HEIGHT * 0.5), (0.45, 0.55, WALL_HEIGHT), 0)
        for i in range(ARCH_STEPS):
            p1, p2 = prof_in[i], prof_in[i + 1]
            mid = (p1 + p2) * 0.5
            angle = math.atan2(p2.z - p1.z, p2.x - p1.x)
            rib = (Matrix.Translation((mid.x, y_pos, mid.z - 0.12))
                   @ Matrix.Rotation(-angle, 4, "Y"))
            bm_add_box(bm_ribs, (0.0, 0.0, 0.0), ((p2 - p1).length + 0.05, 0.42, 0.28), 0, matrix=rib)
    finalize_mesh(bm_ribs, f"{name}_ArchRibs", [mats["trim"]], col_props, **place)

    # 5. Настінні факели кожні 16 м (через 2 секції)
    rot = Matrix.Rotation(math.radians(rotation_z_deg), 3, "Z")
    base = Vector(location)
    torch_idx = 1
    for seg in range(1, num_segments, 2):
        for side, wall_yaw in ((-1.0, -90.0), (1.0, 90.0)):
            local_pt = Vector((side * (PASSAGE_WIDTH * 0.5), seg * SEGMENT_LEN, 3.6))
            world_pt = base + rot @ local_pt
            create_torch(f"{name}_Torch_{torch_idx}", tuple(world_pt),
                         rotation_z_deg + wall_yaw, mats, col_props)
            torch_idx += 1


def create_junction_node(
    name: str,
    open_dirs: set[str],
    location: tuple[float, float, float],
    mats: dict[str, bpy.types.Material],
    col_junctions: bpy.types.Collection,
) -> None:
    """
    Вузол 8x8 м (перехрестя, T-розвилка або поворот на 90°) з пірамідальним склепінням.
    open_dirs: підмножина {"N", "S", "E", "W"}.
    Частини: _Floor, _Walls, _Vault.
    """
    half = CORRIDOR_OUTER_W * 0.5                      # 4.0 м
    wall_t = (CORRIDOR_OUTER_W - PASSAGE_WIDTH) * 0.5  # 1.0 м
    offset = half - wall_t * 0.5                       # 3.5 м

    # Підлога 8x8 м
    bm = bmesh.new()
    bm_add_box(bm, (0.0, 0.0, -FLOOR_THICKNESS * 0.5),
               (CORRIDOR_OUTER_W, CORRIDOR_OUTER_W, FLOOR_THICKNESS), 0)
    bm_add_box(bm, (0.0, 0.0, 0.015), (PASSAGE_WIDTH - 0.6, PASSAGE_WIDTH - 0.6, 0.03), 1)
    finalize_mesh(bm, f"{name}_Floor", [mats["floor"], mats["trim"]], col_junctions, location=location)

    # Кутові стовпи + глухі стіни
    bm = bmesh.new()
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            bm_add_box(bm, (sx * offset, sy * offset, WALL_HEIGHT * 0.5), (wall_t, wall_t, WALL_HEIGHT), 0)
            bm_add_box(bm, (sx * offset, sy * offset, 0.35), (wall_t + 0.16, wall_t + 0.16, 0.70), 1)
            bm_add_box(bm, (sx * offset, sy * offset, WALL_HEIGHT - 0.25),
                       (wall_t + 0.22, wall_t + 0.22, 0.50), 1)
    closed = {
        "N": ((0.0, offset), (PASSAGE_WIDTH, wall_t)),
        "S": ((0.0, -offset), (PASSAGE_WIDTH, wall_t)),
        "E": ((offset, 0.0), (wall_t, PASSAGE_WIDTH)),
        "W": ((-offset, 0.0), (wall_t, PASSAGE_WIDTH)),
    }
    for direction, ((cx, cy), (sx, sy)) in closed.items():
        if direction not in open_dirs:
            bm_add_box(bm, (cx, cy, WALL_HEIGHT * 0.5), (sx, sy, WALL_HEIGHT), 0)
    finalize_mesh(bm, f"{name}_Walls", [mats["stone"], mats["trim"]], col_junctions, location=location)

    # Високе пірамідально-готичне склепіння (замкнена оболонка)
    bm = bmesh.new()
    apex = Vector((0.0, 0.0, WALL_HEIGHT + VAULT_HEIGHT + 0.4))
    apex_top = Vector((0.0, 0.0, WALL_HEIGHT + VAULT_HEIGHT + 0.85))
    corners_in = [Vector((-half, -half, WALL_HEIGHT)), Vector((half, -half, WALL_HEIGHT)),
                  Vector((half, half, WALL_HEIGHT)), Vector((-half, half, WALL_HEIGHT))]
    v_in = [bm.verts.new(c) for c in corners_in]
    v_out = [bm.verts.new(c + Vector((0.0, 0.0, 0.45))) for c in corners_in]
    v_ap_in = bm.verts.new(apex)
    v_ap_out = bm.verts.new(apex_top)
    for i in range(4):
        nxt = (i + 1) % 4
        bm.faces.new((v_in[i], v_in[nxt], v_ap_in)).material_index = 0
        bm.faces.new((v_out[nxt], v_out[i], v_ap_out)).material_index = 0
        bm.faces.new((v_out[i], v_out[nxt], v_in[nxt], v_in[i])).material_index = 1
    finalize_mesh(bm, f"{name}_Vault", [mats["stone"], mats["trim"]], col_junctions, location=location)


def create_torch(
    name: str,
    location: tuple[float, float, float],
    yaw_deg: float,
    mats: dict[str, bpy.types.Material],
    collection: bpy.types.Collection,
) -> None:
    bm = bmesh.new()
    bm_add_box(bm, (0.0, 0.0, 0.0), (0.16, 0.05, 0.42), 0)
    bm_add_box(bm, (0.0, -0.14, 0.05), (0.14, 0.24, 0.06), 0)
    tilt = Matrix.Translation((0.0, -0.18, 0.14)) @ Matrix.Rotation(math.radians(20.0), 4, "X")
    ret_w = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=6,
                                  radius1=0.035, radius2=0.055, depth=0.68, matrix=tilt)
    _assign_material(bm, ret_w["verts"], 1)
    ret_f = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.11,
                                       matrix=tilt @ Matrix.Translation((0.0, 0.0, 0.44)))
    _assign_material(bm, ret_f["verts"], 2)
    finalize_mesh(bm, name, [mats["iron"], mats["wood"], mats["flame"]], collection,
                  location=location, rotation_z_deg=yaw_deg)


# ==============================================================================
# ПЕРЕВІРКА ПОЛІГОНАЖУ ТА ЕКСПОРТ У ROBLOX
# ==============================================================================

def script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def is_writable_dir(folder: str) -> bool:
    """Реальна перевірка запису (os.access у Windows не бачить обмежень Program Files)."""
    if not folder or not os.path.isdir(folder):
        return False
    try:
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


def script_dir() -> str:
    """Тека скрипта: файл на диску або текст, відкритий у Text Editor."""
    script = globals().get("__file__", "")
    if script and os.path.isfile(script):
        return os.path.dirname(os.path.abspath(script))
    base = os.path.basename(script.replace("\\", "/")).strip()
    for text in bpy.data.texts:
        if text.filepath and (text.name == base or os.path.basename(text.filepath) == base):
            path = bpy.path.abspath(text.filepath)
            if os.path.isfile(path):
                return os.path.dirname(path)
    return ""


def resolve_export_path() -> str:
    args = script_args()
    if "--output" in args and args.index("--output") + 1 < len(args):
        return os.path.abspath(bpy.path.abspath(args[args.index("--output") + 1]))
    home = os.path.expanduser("~")
    candidates = [
        bpy.path.abspath(EXPORT_DIR) if EXPORT_DIR else "",
        os.path.dirname(bpy.data.filepath) if bpy.data.filepath else "",
        script_dir(),
        os.path.join(home, "Documents"),
        home,
        tempfile.gettempdir(),
    ]
    if EXPORT_DIR and not is_writable_dir(candidates[0]):
        print(f"[WARNING] EXPORT_DIR недоступна для запису: {candidates[0]}")
    for folder in candidates:
        if is_writable_dir(folder):
            return os.path.join(os.path.abspath(folder), EXPORT_FILENAME)
    raise RuntimeError("Не знайдено теки з правом запису — задайте EXPORT_DIR")


def show_message(text: str, icon: str = "INFO") -> None:
    print(text)
    if bpy.app.background or bpy.context.window_manager is None:
        return

    def draw(menu, _context):
        menu.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title="SAO Long Corridors", icon=icon)


def verify_triangles() -> None:
    print("\n=== СТАТИСТИКА ДОВГИХ КОРИДОРІВ (ROBLOX STUDIO) ===")
    over = []
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if obj.type != "MESH":
            continue
        obj.data.calc_loop_triangles()
        tris = len(obj.data.loop_triangles)
        print(f"  {obj.name:<40} : {tris:>5} tris")
        if tris > MAX_TRIS_PER_OBJECT:
            over.append(obj.name)
    if over:
        raise RuntimeError(f"Перевищено {MAX_TRIS_PER_OBJECT} трикутників: {over}")


def export_fbx_for_roblox(filepath: str) -> None:
    try:
        import addon_utils
        addon_utils.enable("io_scene_fbx", default_set=True)
    except Exception as exc:  # аддон вбудований, тож це не критично
        print(f"[WARNING] Не вдалося явно увімкнути io_scene_fbx: {exc}")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        check_existing=False,
        use_selection=False,
        use_visible=False,
        use_active_collection=False,
        object_types={"MESH"},
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",   # файл у метрах, масштаб об'єктів = 1
        axis_forward="-Z",
        axis_up="Y",                             # Roblox: Y-up
        use_space_transform=True,
        bake_space_transform=False,
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        use_triangles=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
        batch_mode="OFF",
    )
    show_message(f"[SUCCESS] FBX для Roblox збережено: {filepath}")


# ==============================================================================
# ЗБІРКА СИСТЕМИ ДОВГИХ КОРИДОРІВ
# ==============================================================================

def main() -> None:
    reset_scene()
    units = bpy.context.scene.unit_settings
    units.system, units.scale_length, units.length_unit = "METRIC", 1.0, "METERS"

    mats = build_materials()
    col_straight = get_or_create_collection("Corridors_Straight")
    col_junctions = get_or_create_collection("Corridors_Junctions")
    col_props = get_or_create_collection("Corridor_Props")
    corridor = dict(mats=mats, col_corridors=col_straight, col_props=col_props)

    # 1. Головний вхідний коридор (Південь -> Північ): 48 м (6 секцій по 8 м)
    create_long_straight_corridor("Corridor_South_Main_48m", 6, (0.0, 4.0, 0.0), 0.0, **corridor)

    # 2. Перше велике T-перехрестя на Y = 56 м
    create_junction_node("Junction_Central_T", {"S", "W", "E"}, (0.0, 56.0, 0.0), mats, col_junctions)

    # 3. Західне крило (40 м на захід -> поворот 90° -> 32 м на північ)
    create_long_straight_corridor("Corridor_West_Wing_40m", 5, (-4.0, 56.0, 0.0), 90.0, **corridor)
    create_junction_node("Corner_West_Turn", {"E", "N"}, (-48.0, 56.0, 0.0), mats, col_junctions)
    create_long_straight_corridor("Corridor_West_North_32m", 4, (-48.0, 60.0, 0.0), 0.0, **corridor)
    create_junction_node("Corner_NorthWest_Turn", {"S", "E"}, (-48.0, 96.0, 0.0), mats, col_junctions)

    # 4. Східне крило (40 м на схід -> поворот 90° -> 32 м на північ)
    create_long_straight_corridor("Corridor_East_Wing_40m", 5, (4.0, 56.0, 0.0), -90.0, **corridor)
    create_junction_node("Corner_East_Turn", {"W", "N"}, (48.0, 56.0, 0.0), mats, col_junctions)
    create_long_straight_corridor("Corridor_East_North_32m", 4, (48.0, 60.0, 0.0), 0.0, **corridor)
    create_junction_node("Corner_NorthEast_Turn", {"S", "W"}, (48.0, 96.0, 0.0), mats, col_junctions)

    # 5. Північна поперечна галерея (з'єднує обидва крила перед виходом до Боса)
    create_long_straight_corridor("Corridor_North_WestArm_40m", 5, (-44.0, 96.0, 0.0), -90.0, **corridor)
    create_long_straight_corridor("Corridor_North_EastArm_40m", 5, (44.0, 96.0, 0.0), 90.0, **corridor)

    # Фінальне перехрестя з виходом на північ (до передбанника Кімнати Боса)
    create_junction_node("Junction_Boss_Approach_T", {"W", "E", "N"}, (0.0, 96.0, 0.0), mats, col_junctions)

    verify_triangles()
    if AUTO_EXPORT_FBX and "--no-export" not in script_args():
        export_fbx_for_roblox(resolve_export_path())


if __name__ == "__main__":
    main()
