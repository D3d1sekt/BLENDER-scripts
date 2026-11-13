"""
SAO — модульний готичний лабіринт вежі (1-й поверх) з пастками та скарбами.

Скрипт для Blender 5.3 (сумісний з 4.2+). Генерує сцену, оптимізовану для
імпорту в Roblox Studio, та автоматично експортує її у FBX.

Запуск:
  * Blender → Scripting → Open → Run Script, або
  * blender -b -P sao_labyrinth_traps_loot.py -- [--output шлях.fbx] [--no-export]

Масштаб: 1 одиниця Blender = 1 метр.
Уся геометрія будується через `bmesh` у локальних координатах об'єкта, тож
Origin кожного об'єкта стоїть точно там, де потрібно (без bpy.ops-операторів
редагування та без залежності від контексту вʼюпорту).
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# =============================================================================
# НАЛАШТУВАННЯ
# =============================================================================

# --- Сітка лабіринту ---------------------------------------------------------
GRID_SIZE = 3                 # 3 x 3 секції
CELL_SIZE = 8.0               # крок секції, м
CORRIDOR_WIDTH = 6.0          # ширина проходу, м
WALL_HEIGHT = 7.0             # висота стін (лінія пʼят склепіння), м
FLOOR_THICKNESS = 0.5         # товщина плити підлоги, м

# --- Готичне хрестове склепіння ----------------------------------------------
VAULT_RISE = 1.6              # підйом стрілчастого склепіння над стінами, м
VAULT_POINTEDNESS = 0.5       # 0 = напівкруг, 0.5 = класична стрілчаста арка
VAULT_SHELL = 0.4             # товщина склепіння над замком, м
VAULT_SEGMENTS = 16           # поділ склепіння по осі (16 → ~1.6k трикутників)

# --- Декор -------------------------------------------------------------------
COLUMN_INSET = 0.45           # відступ колони від внутрішнього кута, м
TORCH_HEIGHT = 3.2            # висота кріплення факела, м
TORCH_LIGHT_POWER = 120.0     # Вт; лише для превʼю в Blender (не експортується)
ADD_PREVIEW_LIGHTS = True

# --- Пастки ------------------------------------------------------------------
SPIKE_TRAP_SIZE = 4.0         # плита з шипами 4 x 4 м
SPIKE_GRID = 4                # 4 x 4 = 16 шипів
SPIKE_HOLE = 0.3              # розмір отвору під шип, м
SPIKE_PIT_DEPTH = 1.6         # глибина ями під плитою, м
SPIKE_TRAVEL = 1.0            # хід шипів вгору для анімації, м
PRESSURE_PLATE_SIZE = 2.0     # натискна плита 2 x 2 м
PRESSURE_PLATE_PROTRUDE = 0.1 # виступ над підлогою, м
PENDULUM_LENGTH = 7.3         # від осі кріплення до леза, м
PENDULUM_SWING_DEG = 45.0     # амплітуда для анімації

# --- Скрині ------------------------------------------------------------------
CHEST_WIDTH = 1.3
CHEST_DEPTH = 0.85
CHEST_HEIGHT = 0.6
CHEST_WALL = 0.07
CHEST_LID_OPEN_DEG = -105.0   # обертання кришки навколо локальної осі X
PEDESTAL_TOP = 0.7

# --- Roblox / експорт --------------------------------------------------------
MAX_TRIS_PER_OBJECT = 5000
UV_SCALE = 0.5                # box-проєкція UV: 1 тайл текстури = 2 м
CLEAR_SCENE = True
AUTO_EXPORT = True
EXPORT_FILENAME = "sao_maze_traps.fbx"
EXPORT_DIR = ""               # "" → поруч із .blend / скриптом / поточна тека

# --- Матеріали (Principled BSDF) ---------------------------------------------
MATERIALS = {
    "stone": dict(name="SAO_Stone_DarkGray", color=(0.11, 0.11, 0.12), metallic=0.0, roughness=0.9),
    "metal": dict(name="SAO_Metal_Rusty", color=(0.30, 0.15, 0.08), metallic=0.85, roughness=0.75),
    "wood":  dict(name="SAO_Wood_Dark", color=(0.09, 0.05, 0.025), metallic=0.0, roughness=0.7),
    "gold":  dict(name="SAO_Gold_Trim", color=(1.0, 0.72, 0.25), metallic=1.0, roughness=0.3),
    "flame": dict(name="SAO_Torch_Flame", color=(1.0, 0.45, 0.08), metallic=0.0, roughness=1.0,
                  emission=(1.0, 0.5, 0.1), emission_strength=6.0),
}

# --- Колекції ----------------------------------------------------------------
COLL_LAYOUT = "Maze_Layout"
COLL_TRAPS = "Traps"
COLL_LOOT = "Loot_And_Props"

# --- Планування лабіринту ----------------------------------------------------
# (x, y) секції → відкриті сторони: N(+Y), S(-Y), E(+X), W(-X).
# Головний прохід — стовпець x=1 (вхід з півдня → пастки → сходи вгору).
MAZE_CELLS = {
    (0, 0): "N",     # глухий кут — скриня 1
    (0, 1): "NSE",   # бічне відгалуження
    (0, 2): "S",     # глухий кут — скриня 2
    (1, 0): "SNE",   # вхід: натискна плита + маятник-сокира
    (1, 1): "SNW",   # шипи в підлозі
    (1, 2): "S",     # кам'яні гвинтові сходи вгору
    (2, 0): "WN",
    (2, 1): "SN",
    (2, 2): "S",     # глухий кут — скриня 3
}
ENTRANCES = {((1, 0), "S")}             # отвори назовні фрагмента
PENDULUM_CELL = (1, 0)
PRESSURE_PLATE_CELL, PRESSURE_PLATE_POS = (1, 0), (0.0, -2.5)
SPIKE_CELL = (1, 1)
STAIRS_CELL = (1, 2)
CHEST_CELLS = [(0, 0), (0, 2), (2, 2)]
STAIR_STEPS = 28
STAIR_TURN_DEG = 360.0

# Факели: (секція, стіна, зсув уздовж стіни у локальних осях секції)
TORCHES = [
    ((0, 0), "W", -1.4), ((0, 0), "E", -1.4),
    ((0, 2), "W", 1.4), ((0, 2), "E", 1.4),
    ((2, 2), "W", 1.4), ((2, 2), "E", 1.4),
    ((0, 1), "W", 0.0),
    ((1, 0), "W", 0.0),
    ((1, 1), "E", 0.0),
    ((2, 0), "S", 0.0), ((2, 0), "E", 0.0),
    ((2, 1), "E", 0.0), ((2, 1), "W", 0.0),
]

# =============================================================================
# ПОХІДНІ ВЕЛИЧИНИ
# =============================================================================

HALF = CELL_SIZE / 2.0
INNER = CORRIDOR_WIDTH / 2.0
CEIL_TOP = WALL_HEIGHT + VAULT_RISE + VAULT_SHELL
SIDE_DIR = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
# Поворот, що переводить "північну" локальну орієнтацію на потрібну сторону.
SIDE_YAW = {"N": 0.0, "W": 90.0, "S": 180.0, "E": -90.0}
IDENTITY = Matrix.Identity(4)


def T(x=0.0, y=0.0, z=0.0):
    return Matrix.Translation((x, y, z))


def Rx(deg):
    return Matrix.Rotation(math.radians(deg), 4, "X")


def Ry(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Y")


def Rz(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Z")


def S(sx, sy, sz):
    return Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))


# Переставляє осі (u, v, w) → (y, z, x): профіль у площині YZ, видавлювання по X.
AXIS_YZ_EXTRUDE_X = Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def cell_origin(cell):
    i, j = cell
    off = (GRID_SIZE - 1) / 2.0
    return Vector(((i - off) * CELL_SIZE, (j - off) * CELL_SIZE, 0.0))


# =============================================================================
# СЦЕНА, КОЛЕКЦІЇ, МАТЕРІАЛИ
# =============================================================================

def clear_scene():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name in (COLL_LAYOUT, COLL_TRAPS, COLL_LOOT) or (
            not coll.objects and not coll.children
        ):
            bpy.data.collections.remove(coll)
    for datablocks in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)
    # Після видалення об'єктів список view layer оновлюється ліниво — синхронізуємо.
    bpy.context.view_layer.update()


def deselect_all():
    view_layer = bpy.context.view_layer
    view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj is None or view_layer.objects.get(obj.name) is None:
            continue
        obj.select_set(False)
    view_layer.objects.active = None


def setup_scene_units():
    units = bpy.context.scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 1.0
    units.length_unit = "METERS"


def get_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    return coll


def make_material(spec):
    """Простий Principled BSDF без процедурних текстур."""
    mat = bpy.data.materials.get(spec["name"]) or bpy.data.materials.new(spec["name"])
    if mat.node_tree is None:  # лише для збірок, де вузли ще не створюються автоматично
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf.location, out.location = (0, 0), (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def set_input(name, value):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = value

    set_input("Base Color", (*spec["color"], 1.0))
    set_input("Metallic", spec["metallic"])
    set_input("Roughness", spec["roughness"])
    if "emission" in spec:
        set_input("Emission Color", (*spec["emission"], 1.0))
        set_input("Emission Strength", spec["emission_strength"])

    # Кольори вʼюпорту (Solid) та запасні значення для FBX.
    mat.diffuse_color = (*spec["color"], 1.0)
    mat.metallic = spec["metallic"]
    mat.roughness = spec["roughness"]
    return mat


# =============================================================================
# ПОБУДОВА МЕШІВ (bmesh)
# =============================================================================

class MeshBuilder:
    """Збирає геометрію одного об'єкта в локальних координатах (origin = 0,0,0)."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()

    # --- базові елементи ----------------------------------------------------
    def vert(self, co, matrix=IDENTITY):
        return self.bm.verts.new(matrix @ Vector(co))

    def face(self, verts, mat=0):
        clean = []
        for v in verts:
            if v not in clean:
                clean.append(v)
        if len(clean) < 3:
            return None
        try:
            f = self.bm.faces.new(clean)
        except ValueError:  # така грань уже існує
            return None
        f.material_index = mat
        return f

    # --- примітиви -----------------------------------------------------------
    def prism(self, poly, z0, z1, matrix=IDENTITY, mat=0):
        """Опуклий багатокутник у площині XY, видавлений від z0 до z1."""
        bot = [self.vert((u, v, z0), matrix) for u, v in poly]
        top = [self.vert((u, v, z1), matrix) for u, v in poly]
        self.face(list(reversed(bot)), mat)
        self.face(top, mat)
        n = len(poly)
        for k in range(n):
            k1 = (k + 1) % n
            self.face([bot[k], bot[k1], top[k1], top[k]], mat)

    def box(self, x0, x1, y0, y1, z0, z1, matrix=IDENTITY, mat=0):
        self.prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, matrix, mat)

    def lathe(self, profile, segments, matrix=IDENTITY, mat=0, angle_offset=0.0):
        """Тіло обертання навколо осі Z. profile = [(radius, z), ...]; r=0 → полюс."""
        rings = []
        for r, z in profile:
            if r <= 1e-9:
                rings.append([self.vert((0.0, 0.0, z), matrix)])
                continue
            ring = []
            for s in range(segments):
                a = math.radians(angle_offset) + 2.0 * math.pi * s / segments
                ring.append(self.vert((r * math.cos(a), r * math.sin(a), z), matrix))
            rings.append(ring)
        for ra, rb in zip(rings, rings[1:]):
            if len(ra) == 1 and len(rb) == 1:
                continue
            for s in range(segments):
                s1 = (s + 1) % segments
                if len(ra) == 1:
                    self.face([ra[0], rb[s], rb[s1]], mat)
                elif len(rb) == 1:
                    self.face([ra[s], ra[s1], rb[0]], mat)
                else:
                    self.face([ra[s], ra[s1], rb[s1], rb[s]], mat)
        if len(rings[0]) > 1:
            self.face(list(reversed(rings[0])), mat)
        if len(rings[-1]) > 1:
            self.face(rings[-1], mat)

    def grid_solid(self, xs, ys, cell_fn, matrix=IDENTITY, mat=0, diag_split=False):
        """
        Замкнене тіло на прямокутній сітці (xs × ys).
        cell_fn(cx, cy) → None (порожньо) або (z_bottom, z_top), де кожне —
        число або функція f(x, y). Сусідні клітинки з різною висотою
        автоматично з'єднуються вертикальними "сходинками" — так будуються
        стіни, підлоги з ямами/нішами, перфоровані плити та склепіння.
        """
        nx, ny = len(xs) - 1, len(ys) - 1
        cells = {}
        for i in range(nx):
            for j in range(ny):
                spec = cell_fn(0.5 * (xs[i] + xs[i + 1]), 0.5 * (ys[j] + ys[j + 1]))
                if spec is not None:
                    cells[(i, j)] = spec
        cache = {}

        def z_at(fn, n):
            return fn(xs[n[0]], ys[n[1]]) if callable(fn) else fn

        def v_at(cell, which, n):
            z = z_at(cells[cell][which], n)
            key = (n[0], n[1], round(z, 5))
            v = cache.get(key)
            if v is None:
                v = self.vert((xs[n[0]], ys[n[1]], z), matrix)
                cache[key] = v
            return v

        for c in sorted(cells):
            i, j = c
            nodes = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            b = [v_at(c, 0, n) for n in nodes]
            t = [v_at(c, 1, n) for n in nodes]
            if diag_split and callable(cells[c][0]):
                cx, cy = 0.5 * (xs[i] + xs[i + 1]), 0.5 * (ys[j] + ys[j + 1])
                if cx * cy > 0:   # розріз уздовж ребра-нервюри склепіння
                    self.face([b[0], b[1], b[2]], mat)
                    self.face([b[0], b[2], b[3]], mat)
                else:
                    self.face([b[0], b[1], b[3]], mat)
                    self.face([b[1], b[2], b[3]], mat)
            else:
                self.face(b, mat)
            self.face(t, mat)

            edges = [((0, 1), (i, j - 1)), ((1, 2), (i + 1, j)),
                     ((2, 3), (i, j + 1)), ((3, 0), (i - 1, j))]
            for (ka, kb), nb in edges:
                na, nb_node = nodes[ka], nodes[kb]
                if nb not in cells:
                    self.face([b[ka], b[kb], t[kb], t[ka]], mat)
                    continue
                if nb < c:
                    continue  # спільну межу обробляємо один раз
                ab = [z_at(cells[c][0], n) for n in (na, nb_node)]
                at = [z_at(cells[c][1], n) for n in (na, nb_node)]
                bb = [z_at(cells[nb][0], n) for n in (na, nb_node)]
                bt = [z_at(cells[nb][1], n) for n in (na, nb_node)]
                disjoint = all(at[k] <= bb[k] or bt[k] <= ab[k] for k in range(2))
                nbb = [v_at(nb, 0, na), v_at(nb, 0, nb_node)]
                nbt = [v_at(nb, 1, na), v_at(nb, 1, nb_node)]
                if disjoint:
                    self.face([b[ka], b[kb], t[kb], t[ka]], mat)
                    self.face([nbb[0], nbb[1], nbt[1], nbt[0]], mat)
                else:
                    self.face([b[ka], b[kb], nbb[1], nbb[0]], mat)
                    self.face([t[ka], t[kb], nbt[1], nbt[0]], mat)

    # --- фіналізація ---------------------------------------------------------
    def build(self, collection, materials, matrix_world=IDENTITY, props=None):
        bm = self.bm
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()
        add_box_uvs(bm)
        mesh = bpy.data.meshes.new(self.name)
        bm.to_mesh(mesh)
        bm.free()
        mesh.validate(clean_customdata=False)
        mesh.update()
        for m in materials:
            mesh.materials.append(m)
        obj = bpy.data.objects.new(self.name, mesh)
        collection.objects.link(obj)
        obj.matrix_world = matrix_world
        for key, value in (props or {}).items():
            obj[key] = value
        enforce_triangle_budget(obj)
        return obj


def add_box_uvs(bm):
    """Box-проєкція UV (потрібна Roblox для майбутніх текстур/SurfaceAppearance)."""
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        n = f.normal
        axis = max(range(3), key=lambda k: abs(n[k]))
        for loop in f.loops:
            co = loop.vert.co
            if axis == 0:
                u, v = co.y, co.z
            elif axis == 1:
                u, v = co.x, co.z
            else:
                u, v = co.x, co.y
            loop[uv].uv = (u * UV_SCALE, v * UV_SCALE)


def triangle_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def enforce_triangle_budget(obj):
    """Страховка: якщо меш перевищує ліміт Roblox — децимуємо його."""
    tris = triangle_count(obj)
    if tris <= MAX_TRIS_PER_OBJECT:
        return
    print(f"[SAO] {obj.name}: {tris} трикутників > {MAX_TRIS_PER_OBJECT}, децимація…")
    mod = obj.modifiers.new("SAO_AutoDecimate", "DECIMATE")
    mod.ratio = (MAX_TRIS_PER_OBJECT * 0.95) / tris
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    new_mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    obj.modifiers.remove(mod)
    old_mesh = obj.data
    obj.data = new_mesh
    new_mesh.name = old_mesh.name
    bpy.data.meshes.remove(old_mesh)


# =============================================================================
# ЛАБІРИНТ (Maze_Layout)
# =============================================================================

def validate_layout():
    for cell, sides in MAZE_CELLS.items():
        for side in sides:
            dx, dy = SIDE_DIR[side]
            nb = (cell[0] + dx, cell[1] + dy)
            if (cell, side) in ENTRANCES:
                continue
            if nb not in MAZE_CELLS or OPPOSITE[side] not in MAZE_CELLS[nb]:
                raise ValueError(f"Невідповідний прохід: {cell} → {side}")


def arch_height(t):
    """Стрілчаста (двоцентрова) арка: 0 біля стіни, VAULT_RISE у замку."""
    t = min(abs(t), INNER)
    c = INNER * VAULT_POINTEDNESS
    r = INNER + c
    apex = math.sqrt(r * r - c * c)
    return VAULT_RISE * math.sqrt(max(r * r - (t + c) ** 2, 0.0)) / apex


def vault_z(x, y):
    """Хрестове склепіння = об'єднання двох циліндричних склепінь → max()."""
    return WALL_HEIGHT + max(arch_height(x), arch_height(y))


def floor_features(cell):
    """Прямокутні виїмки в підлозі: (x0, x1, y0, y1, z_top)."""
    feats = []
    if cell == SPIKE_CELL:
        h = SPIKE_TRAP_SIZE / 2.0
        feats.append((-h, h, -h, h, -SPIKE_PIT_DEPTH))
    if cell == PRESSURE_PLATE_CELL:
        h = PRESSURE_PLATE_SIZE / 2.0
        px, py = PRESSURE_PLATE_POS
        feats.append((px - h, px + h, py - h, py + h, -2.0 * PRESSURE_PLATE_PROTRUDE))
    return feats


def build_floor(cell, coll, mats):
    feats = floor_features(cell)
    xs = sorted({-HALF, HALF, *[f[0] for f in feats], *[f[1] for f in feats]})
    ys = sorted({-HALF, HALF, *[f[2] for f in feats], *[f[3] for f in feats]})
    bottom = min([-FLOOR_THICKNESS] + [f[4] - 0.2 for f in feats])

    def cell_fn(cx, cy):
        top = 0.0
        for x0, x1, y0, y1, z in feats:
            if x0 < cx < x1 and y0 < cy < y1:
                top = z
        return (bottom, top)

    mb = MeshBuilder(f"Maze_Floor_{cell[0]}_{cell[1]}")
    mb.grid_solid(xs, ys, cell_fn, mat=0)
    return mb.build(coll, [mats["stone"]], T(*cell_origin(cell)))


def build_walls(cell, coll, mats):
    open_sides = MAZE_CELLS[cell]
    xs = ys = [-HALF, -INNER, INNER, HALF]

    def cell_fn(cx, cy):
        ix = 0 if cx < -INNER else (2 if cx > INNER else 1)
        iy = 0 if cy < -INNER else (2 if cy > INNER else 1)
        if ix == 1 and iy == 1:
            return None
        if ix != 1 and iy != 1:
            return (0.0, WALL_HEIGHT)          # кутовий пілон
        side = "W" if ix == 0 else "E" if ix == 2 else "S" if iy == 0 else "N"
        return None if side in open_sides else (0.0, WALL_HEIGHT)

    mb = MeshBuilder(f"Maze_Walls_{cell[0]}_{cell[1]}")
    mb.grid_solid(xs, ys, cell_fn, mat=0)
    # Цоколь і карниз уздовж глухих стін.
    for side in "NSEW":
        if side in open_sides:
            continue
        m = Rz(SIDE_YAW[side])
        mb.box(-INNER, INNER, INNER - 0.15, INNER, 0.0, 0.35, m)
        mb.box(-INNER, INNER, INNER - 0.15, INNER, WALL_HEIGHT - 0.4, WALL_HEIGHT, m)
    return mb.build(coll, [mats["stone"]], T(*cell_origin(cell)))


def build_ceiling(cell, coll, mats):
    stairwell = cell == STAIRS_CELL
    inner = [-INNER + k * CORRIDOR_WIDTH / VAULT_SEGMENTS for k in range(VAULT_SEGMENTS + 1)]
    xs = ys = [-HALF] + inner + [HALF]

    def cell_fn(cx, cy):
        inside = abs(cx) < INNER and abs(cy) < INNER
        if inside:
            return None if stairwell else (vault_z, CEIL_TOP)
        return (WALL_HEIGHT, CEIL_TOP)   # поперечні арки над пілонами

    mb = MeshBuilder(f"Maze_Ceiling_{cell[0]}_{cell[1]}")
    mb.grid_solid(xs, ys, cell_fn, mat=0, diag_split=True)
    return mb.build(coll, [mats["stone"]], T(*cell_origin(cell)))


def build_spiral_stairs(cell, coll, mats):
    mb = MeshBuilder("Stairs_Spiral_Up")
    r0, r1 = 0.4, 2.75
    rise = CEIL_TOP / STAIR_STEPS
    step_angle = STAIR_TURN_DEG / STAIR_STEPS
    start = -90.0  # перша сходинка біля входу з півдня
    for k in range(STAIR_STEPS):
        a0 = math.radians(start + k * step_angle)
        a1 = math.radians(start + (k + 1.06) * step_angle)
        am = 0.5 * (a0 + a1)
        poly = [
            (r0 * math.cos(a0), r0 * math.sin(a0)),
            (r1 * math.cos(a0), r1 * math.sin(a0)),
            (r1 * math.cos(am), r1 * math.sin(am)),
            (r1 * math.cos(a1), r1 * math.sin(a1)),
            (r0 * math.cos(a1), r0 * math.sin(a1)),
        ]
        top = (k + 1) * rise
        mb.prism(poly, top - rise - 0.12, top)
    mb.lathe([(0.45, 0.0), (0.45, CEIL_TOP)], 12)   # центральний стовп
    return mb.build(coll, [mats["stone"]], T(*cell_origin(cell)),
                    props={"note": "Гвинтові сходи на 2-й поверх"})


# =============================================================================
# ПАСТКИ (Traps)
# =============================================================================

def spike_centers():
    step = SPIKE_TRAP_SIZE / SPIKE_GRID
    return [-SPIKE_TRAP_SIZE / 2 + step * (k + 0.5) for k in range(SPIKE_GRID)]


def build_spike_trap(coll, mats):
    base = cell_origin(SPIKE_CELL)
    h = SPIKE_TRAP_SIZE / 2.0
    centers = spike_centers()
    hh = SPIKE_HOLE / 2.0
    cuts = sorted({-h, h, *[c - hh for c in centers], *[c + hh for c in centers]})

    def in_hole(v):
        return any(abs(v - c) < hh for c in centers)

    def cell_fn(cx, cy):
        return None if (in_hole(cx) and in_hole(cy)) else (-0.2, 0.0)

    plate = MeshBuilder("Trap_Floor_Spikes")
    plate.grid_solid(cuts, cuts, cell_fn)
    plate.build(coll, [mats["stone"]], T(*base),
                props={"interactive": False, "role": "spike_plate_with_holes"})

    # Рухомі шипи: origin — центр низу несучої рами.
    spikes = MeshBuilder("Spikes_Moving")
    frame = h - 0.1
    spikes.box(-frame, frame, -frame, frame, 0.0, 0.1)
    for x in centers:
        for y in centers:
            spikes.lathe([(0.11, 0.1), (0.11, 0.18), (0.0, 1.0)], 6, T(x, y, 0.0))
    spikes_z = -0.2 - 0.05 - 1.0   # вістря на 5 см нижче отворів (сховані)
    spikes.build(coll, [mats["metal"]], T(base.x, base.y, spikes_z),
                 props={"interactive": True, "anim": "translate_local_z",
                        "travel_m": SPIKE_TRAVEL})


def build_pressure_plate(coll, mats):
    base = cell_origin(PRESSURE_PLATE_CELL)
    px, py = PRESSURE_PLATE_POS
    r = PRESSURE_PLATE_SIZE / 2.0 * math.sqrt(2.0)   # квадрат через 4-сегментний lathe
    mb = MeshBuilder("Trap_Pressure_Plate")
    mb.lathe([(r, -0.2), (r, -0.03), (r - 0.03 * math.sqrt(2.0), 0.0)], 4, angle_offset=45.0)
    # Origin — центр верхньої грані (при натисканні опускається на 0.1 м).
    mb.build(coll, [mats["stone"]], T(base.x + px, base.y + py, PRESSURE_PLATE_PROTRUDE),
             props={"interactive": True, "anim": "translate_local_z",
                    "travel_m": -PRESSURE_PLATE_PROTRUDE})


def add_crescent_blade(mb, length, radius=1.5, wmax=0.7, thick=0.18,
                       phi_max_deg=62.0, samples=14, mat=0):
    """Серповидне лезо в площині YZ, гостре ребро внизу, обух угорі."""
    cz = -(length - radius)
    phi_max = math.radians(phi_max_deg)

    def point(rad, phi, x):
        return mb.vert((x, rad * math.sin(phi), cz - rad * math.cos(phi)))

    tip_a = point(radius, -phi_max, 0.0)
    tip_b = point(radius, phi_max, 0.0)
    rows = []
    for k in range(1, samples):
        s = -1.0 + 2.0 * k / samples
        f = math.cos(s * math.pi / 2.0) ** 0.7
        phi = s * phi_max
        w, t = wmax * f, thick * max(f, 0.15) ** 0.5
        rows.append((point(radius, phi, 0.0),
                     point(radius - w, phi, t / 2.0),
                     point(radius - w, phi, -t / 2.0)))
    for (e0, p0, n0), (e1, p1, n1) in zip(rows, rows[1:]):
        mb.face([e0, e1, p1, p0], mat)
        mb.face([e0, n0, n1, e1], mat)
        mb.face([p0, p1, n1, n0], mat)
    for tip, (e, p, n) in ((tip_a, rows[0]), (tip_b, rows[-1])):
        mb.face([tip, e, p], mat)
        mb.face([tip, n, e], mat)
        mb.face([tip, p, n], mat)
    return -length + wmax   # z верхньої точки обуха


def build_pendulum(coll, mats):
    base = cell_origin(PENDULUM_CELL)
    apex = WALL_HEIGHT + VAULT_RISE
    pivot = Vector((base.x, base.y, apex - 0.48))

    mount = MeshBuilder("Trap_Pendulum_Axe")
    mount.box(-0.45, 0.45, -0.45, 0.45, 0.3, 0.5)            # стельова плита
    for sx in (-1, 1):
        mount.box(sx * 0.2, sx * 0.28, -0.12, 0.12, -0.15, 0.32)  # вушка
    mount.lathe([(0.06, -0.32), (0.06, 0.32)], 8, Ry(90))      # вісь по X
    mount.build(coll, [mats["metal"]], T(*pivot),
                props={"interactive": False, "role": "ceiling_mount"})

    axe = MeshBuilder("Axe_Swinging")
    axe.lathe([(0.17, -0.18), (0.17, 0.18)], 12, Ry(90))       # маточина на осі
    spine_z = add_crescent_blade(axe, PENDULUM_LENGTH)
    axe.lathe([(0.075, spine_z + 0.1), (0.075, -0.12)], 8)     # штанга
    axe.lathe([(0.13, -2.4), (0.13, -2.2)], 8)                 # декоративні кільця
    axe.lathe([(0.13, -4.6), (0.13, -4.4)], 8)
    axe.box(-0.12, 0.12, -0.28, 0.28, spine_z - 0.05, spine_z + 0.3)  # гніздо леза
    # Origin = вісь кріплення (верхня точка) → обертання навколо локальної X.
    axe.build(coll, [mats["metal"]], T(*pivot),
              props={"interactive": True, "anim": "rotate_local_x",
                     "swing_deg": PENDULUM_SWING_DEG})


# =============================================================================
# СКАРБИ ТА ОТОЧЕННЯ (Loot_And_Props)
# =============================================================================

def build_chest(index, cell, coll, mats):
    open_side = MAZE_CELLS[cell]
    if len(open_side) != 1:
        raise ValueError(f"Скриня має стояти в глухому куті, а {cell} має проходи {open_side}")
    yaw = SIDE_YAW[OPPOSITE[open_side]]          # перед скрині дивиться у прохід
    frame = T(*cell_origin(cell)) @ Rz(yaw) @ T(0.0, 1.85, 0.0)
    w, d, h, t = CHEST_WIDTH, CHEST_DEPTH, CHEST_HEIGHT, CHEST_WALL
    tag = f"{index:02d}"

    ped = MeshBuilder(f"Chest_Pedestal_{tag}")
    ped.box(-1.1, 1.1, -0.8, 0.8, 0.0, 0.25)
    ped.box(-0.9, 0.9, -0.65, 0.65, 0.25, PEDESTAL_TOP - 0.1)
    ped.box(-1.0, 1.0, -0.72, 0.72, PEDESTAL_TOP - 0.1, PEDESTAL_TOP)
    ped.build(coll, [mats["stone"]], frame)

    # --- Chest_Base: порожниста скриня з золотими оковками ---
    base = MeshBuilder(f"Chest_Base_{tag}")
    xs = [-w / 2, -w / 2 + t, w / 2 - t, w / 2]
    ys = [-d / 2, -d / 2 + t, d / 2 - t, d / 2]
    base.grid_solid(xs, ys, lambda cx, cy: (0.0, 0.1) if abs(cx) < w / 2 - t
                    and abs(cy) < d / 2 - t else (0.0, h), mat=0)
    for bx in (-0.35, 0.35):
        base.box(bx - 0.04, bx + 0.04, -d / 2 - 0.015, -d / 2 + 0.01, 0.0, h, mat=1)
        base.box(bx - 0.04, bx + 0.04, d / 2 - 0.01, d / 2 + 0.015, 0.0, h, mat=1)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, x1 = sorted((sx * (w / 2 - 0.08), sx * (w / 2 + 0.015)))
            y0, y1 = sorted((sy * (d / 2 - 0.08), sy * (d / 2 + 0.015)))
            base.box(x0, x1, y0, y1, 0.0, h, mat=1)
    base.box(-0.09, 0.09, -d / 2 - 0.03, -d / 2, h - 0.22, h - 0.02, mat=1)  # замок
    base.build(coll, [mats["wood"], mats["gold"]], frame @ T(0, 0, PEDESTAL_TOP),
               props={"interactive": False, "role": "chest_base"})

    # --- Chest_Lid: origin на задній осі завіс ---
    lid = MeshBuilder(f"Chest_Lid_{tag}")
    r = d / 2 + 0.02
    seg = 10

    def half_circle(radius):
        return [(-r + radius * math.cos(math.pi * k / seg), radius * math.sin(math.pi * k / seg))
                for k in range(seg + 1)]

    lid.prism(half_circle(r), -w / 2 - 0.02, w / 2 + 0.02, AXIS_YZ_EXTRUDE_X, mat=0)
    for bx in (-0.35, 0.35):
        lid.prism(half_circle(r + 0.015), bx - 0.04, bx + 0.04, AXIS_YZ_EXTRUDE_X, mat=1)
    lid.box(-0.06, 0.06, -2 * r - 0.03, -2 * r, -0.14, 0.04, mat=1)  # застібка
    lid.build(coll, [mats["wood"], mats["gold"]],
              frame @ T(0.0, d / 2, PEDESTAL_TOP + h),
              props={"interactive": True, "anim": "rotate_local_x",
                     "open_deg": CHEST_LID_OPEN_DEG})

    # --- Скарб: купа золота всередині + монети на постаменті ---
    loot = MeshBuilder(f"Chest_Treasure_{tag}")
    loot.lathe([(0.0, 0.0), (0.36, 0.0), (0.32, 0.12), (0.2, 0.3), (0.0, 0.36)], 10,
               S(1.4, 0.85, 1.0))
    coins = [(-0.25, 0.05, 0.3, 15), (0.18, -0.08, 0.32, -10), (0.0, 0.1, 0.36, 5),
             (-0.6, -0.58, -0.1, 0), (-0.48, -0.62, -0.1, 0), (0.55, -0.6, -0.1, 0),
             (0.55, -0.6, -0.088, 0)]
    for cx, cy, cz, tilt in coins:
        loot.lathe([(0.05, 0.0), (0.05, 0.012)], 10, T(cx, cy, cz) @ Rx(tilt))
    loot.build(coll, [mats["gold"]], frame @ T(0, 0, PEDESTAL_TOP + 0.1),
               props={"role": "loot"})


def build_columns(coll, mats):
    count = 0
    for cell, open_sides in sorted(MAZE_CELLS.items()):
        for sx in (-1, 1):
            for sy in (-1, 1):
                side_x = "E" if sx > 0 else "W"
                side_y = "N" if sy > 0 else "S"
                if side_x not in open_sides and side_y not in open_sides:
                    continue
                count += 1
                c = INNER - COLUMN_INSET
                pos = cell_origin(cell) + Vector((sx * c, sy * c, 0.0))
                mb = MeshBuilder(f"Column_{cell[0]}_{cell[1]}_{count:02d}")
                H = WALL_HEIGHT
                mb.lathe([(0.64, 0.0), (0.64, 0.28), (0.55, 0.36)], 4, angle_offset=45.0)
                mb.lathe([(0.36, 0.34), (0.34, 0.48), (0.27, 0.6), (0.27, H - 0.75),
                          (0.33, H - 0.62), (0.42, H - 0.32)], 8, angle_offset=22.5)
                mb.lathe([(0.62, H - 0.32), (0.62, H)], 4, angle_offset=45.0)
                mb.build(coll, [mats["stone"]], T(*pos))
    return count


def build_torches(coll, mats):
    for idx, (cell, side, along) in enumerate(TORCHES, start=1):
        if side in MAZE_CELLS[cell]:
            raise ValueError(f"Факел {idx}: сторона {side} секції {cell} відкрита")
        tag = f"{idx:02d}"
        local = {"N": (along, INNER), "S": (along, -INNER),
                 "E": (INNER, along), "W": (-INNER, along)}[side]
        frame = (T(*cell_origin(cell)) @ T(local[0], local[1], TORCH_HEIGHT)
                 @ Rz(SIDE_YAW[side]))  # локально: стіна в y=0, кімната в −Y

        holder = MeshBuilder(f"Torch_Holder_{tag}")
        holder.box(-0.1, 0.1, -0.05, 0.0, -0.25, 0.25)                 # настінна пластина
        holder.box(-0.03, 0.03, -0.4, -0.05, -0.03, 0.03)              # кронштейн
        dy, dz = -0.27, 0.2
        brace_len = math.hypot(dy, dz)
        holder.box(-0.025, 0.025, -brace_len / 2, brace_len / 2, -0.02, 0.02,
                   T(0.0, -0.05 + dy / 2, -0.2 + dz / 2) @ Rx(math.degrees(math.atan2(dz, dy))))
        holder.lathe([(0.0, -0.12), (0.06, -0.12), (0.11, 0.04), (0.0, 0.04)], 8,
                     T(0.0, -0.38, 0.0))                               # чаша
        holder.build(coll, [mats["metal"]], frame)

        stick = MeshBuilder(f"Torch_{tag}")
        stick.lathe([(0.0, 0.0), (0.035, 0.0), (0.045, 0.5), (0.065, 0.52),
                     (0.065, 0.68), (0.0, 0.7)], 6)
        stick.build(coll, [mats["wood"]], frame @ T(0.0, -0.38, -0.12))

        flame = MeshBuilder(f"Torch_Flame_{tag}")
        flame.lathe([(0.0, 0.0), (0.09, 0.08), (0.07, 0.22), (0.0, 0.42)], 6)
        flame_frame = frame @ T(0.0, -0.38, 0.56)
        flame.build(coll, [mats["flame"]], flame_frame)

        if ADD_PREVIEW_LIGHTS:
            light = bpy.data.lights.new(f"Torch_Light_{tag}", type="POINT")
            light.energy = TORCH_LIGHT_POWER
            light.color = (1.0, 0.6, 0.3)
            light.shadow_soft_size = 0.15
            lobj = bpy.data.objects.new(f"Torch_Light_{tag}", light)
            coll.objects.link(lobj)
            lobj.matrix_world = flame_frame @ T(0.0, -0.25, 0.3)
    return len(TORCHES)


# =============================================================================
# ЕКСПОРТ
# =============================================================================

def script_args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def resolve_export_path():
    args = script_args()
    if "--output" in args and args.index("--output") + 1 < len(args):
        return os.path.abspath(bpy.path.abspath(args[args.index("--output") + 1]))
    if EXPORT_DIR:
        folder = bpy.path.abspath(EXPORT_DIR)
    elif bpy.data.filepath:
        folder = os.path.dirname(bpy.data.filepath)
    else:
        script = globals().get("__file__", "")
        folder = os.path.dirname(script) if script and os.path.isfile(script) else os.getcwd()
    return os.path.join(os.path.abspath(folder), EXPORT_FILENAME)


def export_fbx(path):
    try:
        import addon_utils
        addon_utils.enable("io_scene_fbx", default_set=True)
    except Exception as exc:  # аддон вбудований; помилка тут не критична
        print(f"[SAO] Не вдалося явно увімкнути io_scene_fbx: {exc}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=path,
        check_existing=False,
        use_selection=False,
        use_visible=False,
        use_active_collection=False,
        object_types={"MESH"},          # світло факелів лише для превʼю
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",  # файл у метрах, масштаб об'єктів = 1
        axis_forward="-Z",
        axis_up="Y",                    # Roblox: Y-up
        use_space_transform=True,
        bake_space_transform=False,
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        use_triangles=True,             # Roblox усе одно тріангулює
        use_custom_props=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
        batch_mode="OFF",
    )
    print(f"[SAO] FBX експортовано: {path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    validate_layout()
    if CLEAR_SCENE:
        clear_scene()
    setup_scene_units()

    mats = {key: make_material(spec) for key, spec in MATERIALS.items()}
    layout = get_collection(COLL_LAYOUT)
    traps = get_collection(COLL_TRAPS)
    loot = get_collection(COLL_LOOT)

    for cell in sorted(MAZE_CELLS):
        build_floor(cell, layout, mats)
        build_walls(cell, layout, mats)
        build_ceiling(cell, layout, mats)
    build_spiral_stairs(STAIRS_CELL, layout, mats)

    build_spike_trap(traps, mats)
    build_pendulum(traps, mats)
    build_pressure_plate(traps, mats)

    for n, cell in enumerate(CHEST_CELLS, start=1):
        build_chest(n, cell, loot, mats)
    columns = build_columns(loot, mats)
    torches = build_torches(loot, mats)

    # --- Звіт по бюджету трикутників ---
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    worst = max(meshes, key=triangle_count)
    total = sum(triangle_count(o) for o in meshes)
    over = [o.name for o in meshes if triangle_count(o) > MAX_TRIS_PER_OBJECT]
    print(f"[SAO] Об'єктів: {len(meshes)}, трикутників усього: {total}; "
          f"максимум {triangle_count(worst)} ({worst.name}); колон: {columns}, факелів: {torches}")
    if over:
        raise RuntimeError(f"Перевищено ліміт {MAX_TRIS_PER_OBJECT} трикутників: {over}")

    deselect_all()

    if AUTO_EXPORT and "--no-export" not in script_args():
        export_fbx(resolve_export_path())


if __name__ == "__main__":
    main()
