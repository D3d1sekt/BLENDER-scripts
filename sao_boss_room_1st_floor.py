"""
sao_boss_room_1st_floor.py

Велика зала Кімнати Боса 1-го поверху (SAO-стилістика): собор із вітражними
стінами, двома рядами колон, центральною доріжкою з кельтським орнаментом,
подіумом із троном та вхідною готичною брамою з енергетичним бар'єром.

Blender 5.3 (сумісний з 4.2+), лише актуальний API bpy/bmesh.
Сцена оптимізована під Roblox Studio та автоматично експортується у FBX.

Запуск:
  * Blender → Scripting → Open → Run Script, або
  * blender -b -P sao_boss_room_1st_floor.py -- [--output шлях.fbx] [--no-export]

Масштаб: 1 одиниця Blender = 1 метр. Північ = +Y (подіум), південь = −Y (брама).

Нотатки щодо Roblox:
  * Кожен MeshPart у Roblox має один матеріал, тому багатоколірні елементи
    (вітражі, орнамент) розбиті на окремі об'єкти за кольором; інтерактивні
    частини (стулки, бар'єр) — окремі об'єкти з виставленим Origin.
  * Неонова окантовка стулки — дочірній об'єкт стулки з тим самим Origin
    (в Roblox просто зваріть її зі стулкою через WeldConstraint).
  * Маркери Gameplay_Markers мають custom properties з підказками
    (Transparency = 1, CanCollide = false тощо).
"""

import math
import os
import random
import sys
import tempfile

import bmesh
import bpy
from mathutils import Matrix, Vector

# =============================================================================
# НАЛАШТУВАННЯ
# =============================================================================

# --- Зала --------------------------------------------------------------------
HALL_WIDTH = 36.0             # по X
HALL_LENGTH = 56.0            # по Y
HALL_HEIGHT = 18.0
WALL_THICKNESS = 1.0
FLOOR_THICKNESS = 0.5
WAINSCOT_HEIGHT = 2.0         # кам'яний цоколь під вітражами
TRANSOM_HEIGHT = 10.0         # горизонтальна перетинка вітражів
CORNICE_HEIGHT = 16.8         # карниз під стелею
MULLION_STEP = 6.0            # крок вертикальних перетинок (збігається з колонами)

# --- Доріжка та орнамент -----------------------------------------------------
CARPET_WIDTH = 8.0
CARPET_LENGTH = 44.0
ORNAMENT_TILES = 5            # кількість кельтських вузлів уздовж доріжки
ORNAMENT_RIBBON = 0.36        # ширина фіолетової стрічки, м
ORNAMENT_OUTLINE = 0.12       # ширина білої облямівки з кожного боку, м
ORNAMENT_SAMPLES = 220        # точок на один вузол

# --- Колони ------------------------------------------------------------------
PILLARS_PER_SIDE = 7
PILLAR_STEP = 6.0
PILLAR_ROW_X = 6.5            # відстань рядів від осі зали

# --- Стеля -------------------------------------------------------------------
BEAM_WIDTH = 1.2
BEAM_BOTTOM = 16.8
CEILING_SLAB = 0.6

# --- Подіум боса -------------------------------------------------------------
DAIS_WIDTH = 16.0
DAIS_DEPTH = 8.0
DAIS_HEIGHT = 2.2
DAIS_TIERS = 3
DAIS_STEPS = 8
DAIS_STEP_RUN = 0.55
DAIS_STAIR_WIDTH = 6.0

# --- Брама -------------------------------------------------------------------
GATE_WIDTH = 8.0
GATE_HEIGHT = 11.0
GATE_POINTEDNESS = 1.0        # 1.0 = рівностороння готична арка
GATE_FRAME_BORDER = 1.4       # ширина обрамлення з боків, м
GATE_FRAME_TOP = 13.2         # верх прямокутного обрамлення
GATE_FRAME_PROTRUDE = 0.6     # виступ обрамлення в залу
DOOR_THICKNESS = 0.25
DOOR_GAP = 0.03
DOOR_OPEN_DEG = 95.0          # стулки відчиняються назовні (на південь)

# --- Вітражі -----------------------------------------------------------------
GLASS_CELL = 1.9              # середній розмір вітражного шматка, м
GLASS_LEAD = 0.16             # ширина "свинцевої" перетинки між шматками
GLASS_SEED = 1                # зміна дає інший візерунок
GLASS_ALPHA = 0.85
GLASS_EMISSION = 1.5
GLASS_COLORS = {
    "Red": (0.95, 0.15, 0.12),
    "Orange": (1.0, 0.50, 0.10),
    "Yellow": (1.0, 0.85, 0.20),
    "Green": (0.25, 0.85, 0.30),
    "Cyan": (0.20, 0.80, 0.90),
    "Blue": (0.20, 0.35, 1.00),
    "Purple": (0.60, 0.25, 0.95),
    "Pink": (1.0, 0.40, 0.70),
}

# --- Маркери -----------------------------------------------------------------
TRIGGER_ZONE_SIZE = (24.0, 30.0, 10.0)
MINION_SPAWNS = [(-4.8, 14.5), (0.0, 13.0), (4.8, 14.5)]

# --- Roblox / експорт --------------------------------------------------------
MAX_TRIS_PER_OBJECT = 5000
UV_SCALE = 0.25               # box-UV: 1 тайл текстури = 4 м
CLEAR_SCENE = True
AUTO_EXPORT = True
ADD_PREVIEW_LIGHTS = True     # лише для превʼю в Blender, у FBX не потрапляє
EXPORT_FILENAME = "sao_boss_room_1st_floor.fbx"
EXPORT_DIR = ""               # "" → поруч із .blend / скриптом, інакше ~/Documents

# --- Матеріали (Principled BSDF) ---------------------------------------------
MATERIALS = {
    "marble": dict(name="Boss_Marble_Dark_Polished", color=(0.05, 0.055, 0.065), roughness=0.12),
    "stone": dict(name="Boss_Stone_Dark", color=(0.13, 0.12, 0.13), roughness=0.55),
    "pillar": dict(name="Boss_Stone_Pillar", color=(0.17, 0.15, 0.16), roughness=0.45),
    "metal": dict(name="Boss_Metal_Dark", color=(0.035, 0.035, 0.045), metallic=0.9, roughness=0.35),
    "carpet": dict(name="Boss_Carpet_Green", color=(0.12, 0.45, 0.10), roughness=0.95),
    "purple": dict(name="Boss_Ornament_Purple", color=(0.38, 0.12, 0.65), roughness=0.8),
    "white": dict(name="Boss_Ornament_White", color=(0.95, 0.95, 0.98), roughness=0.6,
                  emission=(1.0, 1.0, 1.0), emission_strength=0.6),
    "glow": dict(name="Boss_Glow_White", color=(1.0, 1.0, 1.0), roughness=0.5,
                 emission=(1.0, 1.0, 1.0), emission_strength=8.0),
    "neon": dict(name="Boss_Neon_Blue", color=(0.1, 0.6, 1.0), roughness=0.3,
                 emission=(0.1, 0.65, 1.0), emission_strength=12.0),
    "barrier": dict(name="Boss_Barrier_Field", color=(0.2, 0.7, 1.0), roughness=0.1,
                    emission=(0.2, 0.7, 1.0), emission_strength=3.0, alpha=0.35),
    "marker": dict(name="Boss_Marker_Debug", color=(1.0, 0.1, 0.8), roughness=0.5, alpha=0.3),
}
for _cname, _rgb in GLASS_COLORS.items():
    MATERIALS[f"glass_{_cname}"] = dict(
        name=f"Boss_Glass_{_cname}", color=_rgb, roughness=0.15,
        emission=_rgb, emission_strength=GLASS_EMISSION, alpha=GLASS_ALPHA)

# --- Колекції ----------------------------------------------------------------
COLL_STRUCTURE = "Boss_Arena_Structure"
COLL_PILLARS = "Arena_Pillars"
COLL_GATE = "Boss_Entrance_Gate"
COLL_MARKERS = "Gameplay_Markers"

# =============================================================================
# ПОХІДНІ ВЕЛИЧИНИ
# =============================================================================

HX = HALL_WIDTH / 2.0
HY = HALL_LENGTH / 2.0
NORTH_Y, SOUTH_Y = HY, -HY
DAIS_FRONT_Y = NORTH_Y - DAIS_DEPTH
DAIS_TOP_FRONT_Y = DAIS_FRONT_Y + (DAIS_TIERS - 1) * 1.0
STAIRS_START_Y = DAIS_TOP_FRONT_Y - DAIS_STEPS * DAIS_STEP_RUN
CARPET_END_Y = STAIRS_START_Y
CARPET_START_Y = CARPET_END_Y - CARPET_LENGTH
GATE_OUTER_HALF = GATE_WIDTH / 2.0 + GATE_FRAME_BORDER
DOOR_BACK_Y = SOUTH_Y - 0.6 - DOOR_THICKNESS / 2.0     # зовнішня (південна) грань стулок
BARRIER_Y = SOUTH_Y - 0.1
PILLAR_YS = [(k - (PILLARS_PER_SIDE - 1) / 2.0) * PILLAR_STEP for k in range(PILLARS_PER_SIDE)]
BEAM_YS = sorted(set(PILLAR_YS + [PILLAR_YS[0] - PILLAR_STEP, PILLAR_YS[-1] + PILLAR_STEP]))
BEAM_YS = [y for y in BEAM_YS if abs(y) < HY - 1.0]
IDENTITY = Matrix.Identity(4)
# (u, v, w) → (x, z, y): профіль у площині XZ, видавлювання вздовж Y.
AXIS_XZ_EXTRUDE_Y = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
# (u, v, w) → (y, z, x): профіль у площині YZ, видавлювання вздовж X.
AXIS_YZ_EXTRUDE_X = Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def T(x=0.0, y=0.0, z=0.0):
    return Matrix.Translation((x, y, z))


def Rz(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Z")


# =============================================================================
# СЦЕНА, КОЛЕКЦІЇ, МАТЕРІАЛИ
# =============================================================================

def clear_scene():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    ours = (COLL_STRUCTURE, COLL_PILLARS, COLL_GATE, COLL_MARKERS)
    for coll in list(bpy.data.collections):
        if coll.name in ours or (not coll.objects and not coll.children):
            bpy.data.collections.remove(coll)
    for datablocks in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)
    # Після видалення об'єктів список view layer оновлюється ліниво — синхронізуємо.
    bpy.context.view_layer.update()


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
    """Простий Principled BSDF без процедурних вузлів."""
    mat = bpy.data.materials.get(spec["name"]) or bpy.data.materials.new(spec["name"])
    if mat.node_tree is None:  # лише для старих збірок; у 5.x вузли створюються самі
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def set_input(key, value):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = value

    color = spec["color"]
    alpha = spec.get("alpha", 1.0)
    set_input("Base Color", (*color, 1.0))
    set_input("Metallic", spec.get("metallic", 0.0))
    set_input("Roughness", spec.get("roughness", 0.5))
    if "emission" in spec:
        set_input("Emission Color", (*spec["emission"], 1.0))
        set_input("Emission Strength", spec["emission_strength"])
    if alpha < 1.0:
        set_input("Alpha", alpha)
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    mat.diffuse_color = (*color, alpha)
    mat.metallic = spec.get("metallic", 0.0)
    mat.roughness = spec.get("roughness", 0.5)
    return mat


# =============================================================================
# ПОБУДОВА МЕШІВ (bmesh)
# =============================================================================

class MeshBuilder:
    """Геометрія одного об'єкта в локальних координатах (origin = 0,0,0)."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()

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
        except ValueError:
            return None
        f.material_index = mat
        return f

    def tris(self):
        return sum(len(f.verts) - 2 for f in self.bm.faces)

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
        """Тіло обертання навколо Z. profile = [(radius, z), ...]; r=0 → полюс."""
        rings = []
        for r, z in profile:
            if r <= 1e-9:
                rings.append([self.vert((0.0, 0.0, z), matrix)])
                continue
            rings.append([
                self.vert((r * math.cos(math.radians(angle_offset) + 2 * math.pi * s / segments),
                           r * math.sin(math.radians(angle_offset) + 2 * math.pi * s / segments), z),
                          matrix)
                for s in range(segments)
            ])
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

    def sweep(self, path, half_w, w0, w1, matrix=IDENTITY, mat=0, closed=False):
        """
        Прямокутний переріз уздовж 2D-шляху (u, v); товщина від w0 до w1 по третій осі.
        Вісь (u, v, w) переводиться в 3D матрицею (напр. AXIS_XZ_EXTRUDE_Y).
        """
        n = len(path)

        def seg_normal(a, b):
            du, dv = b[0] - a[0], b[1] - a[1]
            length = math.hypot(du, dv) or 1.0
            return (-dv / length, du / length)

        rings = []
        for i in range(n):
            p = path[i]
            prev_p = path[i - 1] if (closed or i > 0) else None
            next_p = path[(i + 1) % n] if (closed or i < n - 1) else None
            if prev_p is not None and next_p is not None:
                n1, n2 = seg_normal(prev_p, p), seg_normal(p, next_p)
                mu, mv = n1[0] + n2[0], n1[1] + n2[1]
                ml = math.hypot(mu, mv) or 1.0
                mu, mv = mu / ml, mv / ml
                scale = 1.0 / max(mu * n1[0] + mv * n1[1], 0.35)
            else:
                mu, mv = seg_normal(prev_p, p) if next_p is None else seg_normal(p, next_p)
                scale = 1.0
            ou, ov = mu * half_w * scale, mv * half_w * scale
            rings.append([
                self.vert((p[0] + ou, p[1] + ov, w0), matrix),
                self.vert((p[0] - ou, p[1] - ov, w0), matrix),
                self.vert((p[0] - ou, p[1] - ov, w1), matrix),
                self.vert((p[0] + ou, p[1] + ov, w1), matrix),
            ])
        pairs = list(zip(rings, rings[1:]))
        if closed:
            pairs.append((rings[-1], rings[0]))
        for ra, rb in pairs:
            for k in range(4):
                k1 = (k + 1) % 4
                self.face([ra[k], ra[k1], rb[k1], rb[k]], mat)
        if not closed:
            self.face(list(reversed(rings[0])), mat)
            self.face(rings[-1], mat)

    def flat_poly(self, pts3d, normal, mat=0):
        """Одностороння плоска грань; порядок вершин підбирається під потрібну нормаль."""
        verts = [self.vert(p) for p in pts3d]
        # Нормаль за формулою Ньюела — стійка для майже колінеарних перших вершин.
        nrm = Vector((0.0, 0.0, 0.0))
        for i, p in enumerate(pts3d):
            q = pts3d[(i + 1) % len(pts3d)]
            nrm.x += (p[1] - q[1]) * (p[2] + q[2])
            nrm.y += (p[2] - q[2]) * (p[0] + q[0])
            nrm.z += (p[0] - q[0]) * (p[1] + q[1])
        if nrm.dot(Vector(normal)) < 0:
            verts.reverse()
        return self.face(verts, mat)

    # --- фіналізація ---------------------------------------------------------
    def build(self, collection, materials, location=(0.0, 0.0, 0.0), props=None, recalc=True):
        bm = self.bm
        if recalc:
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
        obj.location = location
        for key, value in (props or {}).items():
            obj[key] = value
        return obj


def add_box_uvs(bm):
    """Box-проєкція UV (для майбутніх текстур / SurfaceAppearance у Roblox)."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        axis = max(range(3), key=lambda k: abs(n[k]))
        for loop in f.loops:
            co = loop.vert.co
            u, v = ((co.y, co.z), (co.x, co.z), (co.x, co.y))[axis]
            loop[uv].uv = (u * UV_SCALE, v * UV_SCALE)


def triangle_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


class SplitBuilder:
    """Набирає геометрію в об'єкти з однаковим префіксом, не перевищуючи ліміт трикутників."""

    def __init__(self, name, collection, materials, recalc=False):
        self.name, self.collection, self.materials, self.recalc = name, collection, materials, recalc
        self.parts = []
        self.current = None

    def get(self, upcoming_tris):
        if self.current is None or self.current.tris() + upcoming_tris > MAX_TRIS_PER_OBJECT:
            if self.current is not None:
                self.parts.append(self.current)
            idx = len(self.parts) + 1
            self.current = MeshBuilder(self.name if idx == 1 else f"{self.name}_{idx:02d}")
        return self.current

    def build(self):
        if self.current is not None:
            self.parts.append(self.current)
        objs = [p.build(self.collection, self.materials, recalc=self.recalc) for p in self.parts]
        self.parts, self.current = [], None
        return objs


# =============================================================================
# 2D-ГЕОМЕТРІЯ: ГОТИЧНА АРКА, ВІДСТУПИ, ПЕРЕВИБІРКА
# =============================================================================

def pointed_arch(half_w, height, pointedness, offset=0.0, n_arc=10):
    """
    Двоцентрова стрілчаста арка (XZ). offset > 0 — обрис ширший, < 0 — вужчий.
    Повертає (шлях від лівої п'яти до правої, висота п'ят, висота замка).
    """
    c = half_w * pointedness
    r = half_w + c
    spring = height - math.sqrt(r * r - c * c)
    R = r + offset
    hw = half_w + offset
    theta_apex = math.acos(-c / R)
    left = []
    for k in range(1, n_arc + 1):
        th = math.pi + (theta_apex - math.pi) * k / n_arc
        left.append((c + R * math.cos(th), spring + R * math.sin(th)))
    left[-1] = (0.0, left[-1][1])
    right = [(-x, z) for x, z in reversed(left[:-1])]
    path = [(-hw, 0.0), (-hw, spring)] + left + right + [(hw, spring), (hw, 0.0)]
    return path, spring, left[-1][1]


def signed_area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                     - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def inset_polygon(poly, d):
    """Відступ усередину опуклого багатокутника на d."""
    if signed_area(poly) < 0:
        poly = poly[::-1]
    n = len(poly)
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        du, dv = b[0] - a[0], b[1] - a[1]
        length = math.hypot(du, dv)
        nu, nv = -dv / length, du / length
        lines.append(((a[0] + nu * d, a[1] + nv * d), (du / length, dv / length)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(cross) < 1e-9:
            out.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return out


def polyline_fracs(poly):
    acc = [0.0]
    for a, b in zip(poly, poly[1:]):
        acc.append(acc[-1] + math.dist(a, b))
    return [s / acc[-1] for s in acc], acc


def resample(poly, fracs):
    rel, acc = polyline_fracs(poly)
    total = acc[-1]
    out, j = [], 0
    for f in fracs:
        s = f * total
        while j < len(acc) - 2 and acc[j + 1] < s:
            j += 1
        seg = acc[j + 1] - acc[j]
        t = (s - acc[j]) / seg if seg > 0 else 0.0
        a, b = poly[j], poly[j + 1]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def x_range_at(poly, z):
    xs = []
    n = len(poly)
    for i in range(n):
        (x0, z0), (x1, z1) = poly[i], poly[(i + 1) % n]
        if (z0 - z) * (z1 - z) <= 0 and z0 != z1:
            xs.append(x0 + (x1 - x0) * (z - z0) / (z1 - z0))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


# =============================================================================
# ВІТРАЖІ
# =============================================================================

def glass_blobs(rng, u0, u1, v0, v1):
    """Розбиває прямокутну панель на органічні шматки скла (між ними — "свинець")."""
    blobs = []
    height = v1 - v0
    rows = max(1, round(height / GLASS_CELL))
    cuts = [v0] + sorted(v0 + height * (k + rng.uniform(-0.18, 0.18)) / rows
                         for k in range(1, rows)) + [v1]
    for r0, r1 in zip(cuts, cuts[1:]):
        u = u0
        while u < u1 - 1e-3:
            w = rng.uniform(GLASS_CELL * 0.65, GLASS_CELL * 1.55)
            if u1 - (u + w) < GLASS_CELL * 0.6:
                w = u1 - u
            blobs.append(make_blob(rng, u, u + w, r0, r1))
            u += w
    return [b for b in blobs if b]


def make_blob(rng, u0, u1, v0, v1, segments=14):
    rx = (u1 - u0) / 2.0 - GLASS_LEAD / 2.0
    ry = (v1 - v0) / 2.0 - GLASS_LEAD / 2.0
    if rx < 0.15 or ry < 0.15:
        return None
    amp = 0.07
    rx, ry = rx / (1.0 + 2 * amp), ry / (1.0 + 2 * amp)
    cu, cv = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    ph1, ph2 = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    expo = rng.uniform(2.2, 3.2)            # 2 = еліпс, більше — заокруглений прямокутник
    pts = []
    for k in range(segments):
        th = 2 * math.pi * k / segments
        c, s = math.cos(th), math.sin(th)
        sx = math.copysign(abs(c) ** (2.0 / expo), c)
        sy = math.copysign(abs(s) ** (2.0 / expo), s)
        wobble = 1.0 + amp * math.sin(2 * th + ph1) + amp * math.sin(3 * th + ph2)
        pts.append((cu + rx * sx * wobble, cv + ry * sy * wobble))
    return pts


def pick_color(rng):
    return rng.choice(list(GLASS_COLORS))


# =============================================================================
# СТІНИ
# =============================================================================

# Локальна система стіни: u — уздовж стіни, d — у бік зали, z — вгору.
# U × Z = N, тож багатокутник проти годинникової в (u, z) дивиться в залу.
WALLS = {
    "East": dict(origin=(HX, 0.0, 0.0), U=(0, -1, 0), N=(-1, 0, 0), half=HY, gate=False),
    "West": dict(origin=(-HX, 0.0, 0.0), U=(0, 1, 0), N=(1, 0, 0), half=HY, gate=False),
    "North": dict(origin=(0.0, HY, 0.0), U=(1, 0, 0), N=(0, -1, 0), half=HX, gate=False),
    "South": dict(origin=(0.0, -HY, 0.0), U=(-1, 0, 0), N=(0, 1, 0), half=HX, gate=True),
}


def wall_linear(w):
    U, N = Vector(w["U"]), Vector(w["N"])
    return Matrix(((U.x, N.x, 0, 0), (U.y, N.y, 0, 0), (U.z, N.z, 1, 0), (0, 0, 0, 1)))


def wall_mullions(w):
    half = w["half"]
    inner = []
    k = 1
    while k * MULLION_STEP < half - 1.0:
        inner += [-k * MULLION_STEP, k * MULLION_STEP]
        k += 1
    ms = sorted(set([0.0] + inner) | {-(half - 0.3), half - 0.3})
    if w["gate"]:
        ms = [m for m in ms if abs(m) > GATE_OUTER_HALF + 1.5] + [-GATE_OUTER_HALF, GATE_OUTER_HALF]
    return sorted(ms)


def build_wall_frames(coll, mats):
    for name, w in WALLS.items():
        lin = wall_linear(w)
        mb = MeshBuilder(f"Stained_Glass_Walls_Frame_{name}")
        ext = WALL_THICKNESS if name in ("East", "West") else 0.0
        u_min, u_max = -w["half"] - ext, w["half"] + ext
        segs = [(u_min, u_max)]
        if w["gate"]:
            segs = [(u_min, -GATE_OUTER_HALF), (GATE_OUTER_HALF, u_max)]
            mb.box(-GATE_OUTER_HALF, GATE_OUTER_HALF, -WALL_THICKNESS, 0.0,
                   GATE_FRAME_TOP, CORNICE_HEIGHT, lin, 1)
        t = WALL_THICKNESS
        for a, b in segs:
            mb.box(a, b, -t, 0.3, 0.0, WAINSCOT_HEIGHT, lin, 0)                       # цоколь
            mb.box(a, b, -t, 0.45, WAINSCOT_HEIGHT, WAINSCOT_HEIGHT + 0.2, lin, 0)     # капітель цоколя
            mb.box(a, b, -t, 0.0, WAINSCOT_HEIGHT + 0.2, CORNICE_HEIGHT, lin, 1)       # темна основа вітража
            mb.box(a, b, 0.0, 0.35, TRANSOM_HEIGHT - 0.2, TRANSOM_HEIGHT + 0.2, lin, 1)  # горизонтальна перетинка
        mb.box(u_min, u_max, -t, 0.5, CORNICE_HEIGHT, HALL_HEIGHT, lin, 0)            # карниз
        for m in wall_mullions(w):
            mb.box(m - 0.3, m + 0.3, 0.0, 0.4, WAINSCOT_HEIGHT + 0.2, CORNICE_HEIGHT, lin, 1)
        mb.build(coll, [mats["stone"], mats["metal"]], location=w["origin"],
                 props={"role": "stained_glass_frame"})


def wall_glass_panels(w):
    ms = wall_mullions(w)
    tiers = [(WAINSCOT_HEIGHT + 0.2, TRANSOM_HEIGHT - 0.2), (TRANSOM_HEIGHT + 0.2, CORNICE_HEIGHT)]
    panels = []
    for m0, m1 in zip(ms, ms[1:]):
        a, b = m0 + 0.3, m1 - 0.3
        if w["gate"] and abs(m0 + GATE_OUTER_HALF) < 1e-6 and abs(m1 - GATE_OUTER_HALF) < 1e-6:
            panels.append((a, b, GATE_FRAME_TOP, CORNICE_HEIGHT))
            continue
        panels += [(a, b, z0, z1) for z0, z1 in tiers]
    return panels


def build_wall_glass(coll, mats):
    rng = random.Random(GLASS_SEED)
    groups = {c: SplitBuilder(f"Stained_Glass_Walls_Glass_{c}", coll, [mats[f"glass_{c}"]])
              for c in GLASS_COLORS}
    for name, w in WALLS.items():
        O, U, N = Vector(w["origin"]), Vector(w["U"]), Vector(w["N"])
        for u0, u1, z0, z1 in wall_glass_panels(w):
            for blob in glass_blobs(rng, u0, u1, z0, z1):
                pts = [O + U * u + N * 0.02 + Vector((0, 0, v)) for u, v in blob]
                color = pick_color(rng)
                groups[color].get(len(pts) - 2).flat_poly(pts, N)
    for g in groups.values():
        for obj in g.build():
            obj["role"] = "stained_glass"


# =============================================================================
# СТЕЛЯ
# =============================================================================

def build_ceiling(coll, mats):
    mb = MeshBuilder("Cathedral_Ceiling")
    t = WALL_THICKNESS
    mb.box(-HX - t, HX + t, -HY - t, HY + t, HALL_HEIGHT, HALL_HEIGHT + CEILING_SLAB, mat=0)
    hb = BEAM_WIDTH / 2.0
    for y in BEAM_YS:   # масивні поперечні балки з нижнім уступом
        mb.box(-HX, HX, y - hb, y + hb, BEAM_BOTTOM, HALL_HEIGHT, mat=0)
        mb.box(-HX, HX, y - hb - 0.25, y + hb + 0.25, HALL_HEIGHT - 0.45, HALL_HEIGHT, mat=0)
    for x in (-PILLAR_ROW_X, PILLAR_ROW_X):  # поздовжні балки над рядами колон
        mb.box(x - 0.5, x + 0.5, -HY, HY, BEAM_BOTTOM + 0.15, HALL_HEIGHT, mat=0)
    mb.build(coll, [mats["metal"]], props={"role": "ceiling_beams"})

    rng = random.Random(GLASS_SEED + 101)
    groups = {c: SplitBuilder(f"Cathedral_Ceiling_Glass_{c}", coll, [mats[f"glass_{c}"]])
              for c in GLASS_COLORS}
    y_edges = [-HY] + [v for y in BEAM_YS for v in (y - hb - 0.25, y + hb + 0.25)] + [HY]
    x_bays = [(-HX, -PILLAR_ROW_X - 0.5), (-PILLAR_ROW_X + 0.5, PILLAR_ROW_X - 0.5),
              (PILLAR_ROW_X + 0.5, HX)]
    z = HALL_HEIGHT - 0.02
    down = Vector((0, 0, -1))
    for y0, y1 in zip(y_edges[0::2], y_edges[1::2]):
        for x0, x1 in x_bays:
            for blob in glass_blobs(rng, x0, x1, y0, y1):
                pts = [Vector((u, v, z)) for u, v in blob]
                groups[pick_color(rng)].get(len(pts) - 2).flat_poly(pts, down)
    for g in groups.values():
        for obj in g.build():
            obj["role"] = "stained_glass"


# =============================================================================
# ПІДЛОГА, ДОРІЖКА, ОРНАМЕНТ
# =============================================================================

def knot_curve(kind, t):
    """Проєкції торичних вузлів — "кельтські" переплетення з 3 та 4 пелюстками."""
    if kind == 0:   # трилисник (2,3)
        r = 2.0 + math.cos(3 * t)
        return r * math.cos(2 * t), r * math.sin(2 * t)
    r = 2.0 + math.cos(4 * t)   # чотирилисник (3,4)
    return r * math.cos(3 * t), r * math.sin(3 * t)


def ribbon(builder, pts, half_w, z, mat=0):
    """Плоска стрічка (дивиться вгору) уздовж замкненої 2D-кривої."""
    n = len(pts)
    left, right = [], []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        tx, ty = p2[0] - p0[0], p2[1] - p0[1]
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl
        left.append((p1[0] + nx * half_w, p1[1] + ny * half_w, z))
        right.append((p1[0] - nx * half_w, p1[1] - ny * half_w, z))
    up = (0.0, 0.0, 1.0)
    for i in range(n):
        j = (i + 1) % n
        builder.flat_poly([left[i], right[i], right[j], left[j]], up, mat)


def build_floor(coll, mats):
    t = WALL_THICKNESS
    floor = MeshBuilder("Arena_Floor")
    floor.box(-HX - t, HX + t, -HY - t, HY + t, -FLOOR_THICKNESS, 0.0)
    floor.build(coll, [mats["marble"]], props={"role": "floor"})

    cw = CARPET_WIDTH / 2.0
    carpet = MeshBuilder("Arena_Floor_Carpet")
    carpet.box(-cw, cw, CARPET_START_Y, CARPET_END_Y, 0.0, 0.03)
    carpet.build(coll, [mats["carpet"]], props={"role": "carpet"})

    purple = SplitBuilder("Arena_Floor_Ornament_Purple", coll, [mats["purple"]])
    white = SplitBuilder("Arena_Floor_Ornament_White", coll, [mats["white"]])
    tile = CARPET_LENGTH / ORNAMENT_TILES
    scale = (cw - 0.55) / 3.0
    for k in range(ORNAMENT_TILES):
        cy = CARPET_START_Y + (k + 0.5) * tile
        knot = [knot_curve(k % 2, 2 * math.pi * i / ORNAMENT_SAMPLES) for i in range(ORNAMENT_SAMPLES)]
        knot = [(x * scale, cy + y * scale) for x, y in knot]
        ring_r = min(cw, tile / 2.0) - 0.45
        ring = [(ring_r * math.cos(2 * math.pi * i / 72), cy + ring_r * math.sin(2 * math.pi * i / 72))
                for i in range(72)]
        for curve in (knot, ring):
            seg_tris = 2 * len(curve)
            ribbon(white.get(seg_tris), curve, ORNAMENT_RIBBON / 2 + ORNAMENT_OUTLINE, 0.032)
            ribbon(purple.get(seg_tris), curve, ORNAMENT_RIBBON / 2, 0.036)
    # Біла облямівка по краях доріжки.
    edge = white.get(16)
    up = (0, 0, 1)
    for x0, x1 in ((-cw + 0.15, -cw + 0.35), (cw - 0.35, cw - 0.15)):
        edge.flat_poly([(x0, CARPET_START_Y + 0.15, 0.032), (x1, CARPET_START_Y + 0.15, 0.032),
                        (x1, CARPET_END_Y - 0.15, 0.032), (x0, CARPET_END_Y - 0.15, 0.032)], up)
    for y0, y1 in ((CARPET_START_Y + 0.15, CARPET_START_Y + 0.35), (CARPET_END_Y - 0.35, CARPET_END_Y - 0.15)):
        edge.flat_poly([(-cw + 0.15, y0, 0.032), (cw - 0.15, y0, 0.032),
                        (cw - 0.15, y1, 0.032), (-cw + 0.15, y1, 0.032)], up)
    for obj in purple.build() + white.build():
        obj["role"] = "carpet_ornament"

    # Смуги, що світяться, по периметру біля підніжжя стін.
    glow = MeshBuilder("Arena_Floor_Glow_Strips")
    g0, g1 = 0.4, 0.6   # відступ від внутрішньої грані стіни
    glow.box(HX - g1, HX - g0, -HY + g0, HY - g0, 0.0, 0.06)
    glow.box(-HX + g0, -HX + g1, -HY + g0, HY - g0, 0.0, 0.06)
    glow.box(-HX + g1, HX - g1, HY - g1, HY - g0, 0.0, 0.06)
    for a, b in ((-HX + g1, -GATE_OUTER_HALF - 0.7), (GATE_OUTER_HALF + 0.7, HX - g1)):
        glow.box(a, b, -HY + g0, -HY + g1, 0.0, 0.06)
    glow.build(coll, [mats["glow"]], props={"role": "glow_strips"})


# =============================================================================
# ПОДІУМ І ТРОН
# =============================================================================

def build_dais(coll, mats):
    mb = MeshBuilder("Boss_Dais_Platform")
    hw = DAIS_WIDTH / 2.0
    tier_h = DAIS_HEIGHT / DAIS_TIERS
    for t in range(DAIS_TIERS):
        mb.box(-hw + t, hw - t, DAIS_FRONT_Y + t, NORTH_Y, 0.0, (t + 1) * tier_h)
        mb.box(-hw + t - 0.08, hw - t + 0.08, DAIS_FRONT_Y + t - 0.08, NORTH_Y,
               (t + 1) * tier_h - 0.12, (t + 1) * tier_h)               # карнизик сходинки
    rise = DAIS_HEIGHT / DAIS_STEPS
    sw = DAIS_STAIR_WIDTH / 2.0
    for k in range(DAIS_STEPS):
        mb.box(-sw, sw, STAIRS_START_Y + k * DAIS_STEP_RUN, DAIS_TOP_FRONT_Y, 0.0, (k + 1) * rise)
    for side in (-1, 1):   # бічні щоки сходів
        x0, x1 = sorted((side * sw, side * (sw + 0.6)))
        cheek = [(STAIRS_START_Y - 0.3, 0.0), (DAIS_TOP_FRONT_Y, 0.0),
                 (DAIS_TOP_FRONT_Y, DAIS_HEIGHT + 0.35), (STAIRS_START_Y - 0.3, 0.6)]
        mb.prism(cheek, x0, x1, AXIS_YZ_EXTRUDE_X)
    mb.build(coll, [mats["stone"]], props={"role": "boss_dais"})

    # Масивний кам'яний трон
    th = MeshBuilder("Boss_Dais_Throne")
    z0 = DAIS_HEIGHT
    ty = NORTH_Y - 2.4   # центр трону
    th.box(-2.3, 2.3, ty - 1.7, ty + 1.6, z0, z0 + 0.4)                    # постамент
    th.box(-1.5, 1.5, ty - 1.2, ty + 0.9, z0 + 0.4, z0 + 1.4)              # сидіння
    back = [(-1.7, z0 + 1.4), (1.7, z0 + 1.4), (1.7, z0 + 5.2), (0.0, z0 + 6.8), (-1.7, z0 + 5.2)]
    th.prism(back, ty + 0.9, ty + 1.6, AXIS_XZ_EXTRUDE_Y)                 # спинка зі стрілчастим верхом
    for side in (-1, 1):
        x0, x1 = sorted((side * 1.5, side * 2.15))
        th.box(x0, x1, ty - 1.2, ty + 0.9, z0 + 0.4, z0 + 2.3)              # підлокітники
        th.box(x0 - 0.1, x1 + 0.1, ty - 1.35, ty + 0.9, z0 + 2.3, z0 + 2.5)
        th.lathe([(0.45, z0 + 5.2), (0.0, z0 + 6.6)], 4,
                 T(side * 1.7, ty + 1.25, 0.0), angle_offset=45.0)          # шпилі
    th.build(coll, [mats["stone"]], props={"role": "boss_throne"})


# =============================================================================
# КОЛОНИ
# =============================================================================

LEAF_LOW = [(0.75, 13.9), (1.15, 14.3), (1.35, 14.9), (1.15, 14.8), (0.9, 14.5)]
LEAF_HIGH = [(0.95, 14.9), (1.35, 15.3), (1.55, 15.95), (1.32, 15.85), (1.08, 15.5)]


def build_pillar(name, x, y, coll, mats):
    mb = MeshBuilder(name)
    sq = math.sqrt(2.0)
    # Ступінчаста квадратна база (4-сегментний lathe з поворотом 45° = квадрат)
    mb.lathe([(1.2 * sq, 0.0), (1.2 * sq, 0.45)], 4, angle_offset=45.0)
    mb.lathe([(1.0 * sq, 0.45), (1.0 * sq, 0.85)], 4, angle_offset=45.0)
    mb.lathe([(0.85 * sq, 0.85), (0.85 * sq, 1.15), (0.78 * sq, 1.25)], 4, angle_offset=45.0)
    # Восьмигранний стовбур із поясами посередині та шийкою під капітеллю
    mb.lathe([
        (0.80, 1.25), (0.80, 1.45), (0.68, 1.60), (0.60, 1.70),
        (0.60, 7.30), (0.74, 7.45), (0.74, 7.70), (0.64, 7.80),
        (0.64, 8.00), (0.74, 8.10), (0.74, 8.35), (0.60, 8.50),
        (0.60, 13.45), (0.70, 13.55), (0.70, 13.80), (0.62, 13.90),
        (0.80, 14.60), (1.05, 15.30), (1.30, 16.00),
    ], 8, angle_offset=22.5)
    # Різьблена готична капітель: два яруси листя-крокетів
    for tier, leaf, offset in ((0, LEAF_LOW, 0.0), (1, LEAF_HIGH, 22.5)):
        for k in range(8):
            mb.prism(leaf, -0.1, 0.1, Rz(offset + 45.0 * k) @ AXIS_XZ_EXTRUDE_Y)
    # Абака та імпост до стелі
    mb.lathe([(1.2 * sq, 16.0), (1.2 * sq, 16.8)], 4, angle_offset=45.0)
    mb.lathe([(0.95 * sq, 16.8), (0.95 * sq, HALL_HEIGHT)], 4, angle_offset=45.0)
    mb.build(coll, [mats["pillar"]], location=(x, y, 0.0), props={"role": "pillar"})


def build_pillars(coll, mats):
    for side, tag in ((-1, "L"), (1, "R")):
        for k, y in enumerate(PILLAR_YS, start=1):
            build_pillar(f"Arena_Pillar_{tag}{k:02d}", side * PILLAR_ROW_X, y, coll, mats)


# =============================================================================
# БРАМА
# =============================================================================

def build_gate(coll, mats):
    hw = GATE_WIDTH / 2.0
    origin = Vector((0.0, SOUTH_Y, 0.0))
    y_back, y_front = -WALL_THICKNESS, GATE_FRAME_PROTRUDE   # локально відносно SOUTH_Y

    # --- Gate_Arch_Frame: масивне обрамлення зі стрілчастим отвором ---
    inner, spring, apex = pointed_arch(hw, GATE_HEIGHT, GATE_POINTEDNESS, n_arc=12)
    outer = [(-GATE_OUTER_HALF, 0.0), (-GATE_OUTER_HALF, GATE_FRAME_TOP),
             (GATE_OUTER_HALF, GATE_FRAME_TOP), (GATE_OUTER_HALF, 0.0)]
    fracs = sorted({round(f, 6) for f in polyline_fracs(inner)[0] + polyline_fracs(outer)[0]})
    P, Q = resample(inner, fracs), resample(outer, fracs)
    fr = MeshBuilder("Gate_Arch_Frame")
    Pf = [fr.vert((x, y_front, z)) for x, z in P]
    Pb = [fr.vert((x, y_back, z)) for x, z in P]
    Qf = [fr.vert((x, y_front, z)) for x, z in Q]
    Qb = [fr.vert((x, y_back, z)) for x, z in Q]
    for i in range(len(fracs) - 1):
        j = i + 1
        fr.face([Pf[i], Pf[j], Qf[j], Qf[i]])
        fr.face([Pb[i], Qb[i], Qb[j], Pb[j]])
        fr.face([Pf[i], Pb[i], Pb[j], Pf[j]])
        fr.face([Qf[i], Qf[j], Qb[j], Qb[i]])
    for i in (0, len(fracs) - 1):
        fr.face([Pf[i], Qf[i], Qb[i], Pb[i]])
    for off, half in ((0.35, 0.16), (1.0, 0.2)):     # архівольти
        path, _, _ = pointed_arch(hw, GATE_HEIGHT, GATE_POINTEDNESS, offset=off, n_arc=12)
        fr.sweep(path, half, y_front, y_front + 0.25, AXIS_XZ_EXTRUDE_Y)
    _, _, apex_outer = pointed_arch(hw, GATE_HEIGHT, GATE_POINTEDNESS, offset=1.2)
    fr.box(-0.4, 0.4, y_front, y_front + 0.35, apex_outer - 0.1, GATE_FRAME_TOP - 0.1)  # замковий камінь
    for side in (-1, 1):                                       # бокові пілястри
        x0, x1 = sorted((side * (hw + 0.2), side * (GATE_OUTER_HALF - 0.1)))
        fr.box(x0, x1, y_front, y_front + 0.3, 0.0, spring)
    fr.build(coll, [mats["stone"]], location=tuple(origin), props={"role": "gate_frame"})

    # --- Стулки дверей: Origin на зовнішній осі петель ---
    door_path, d_spring, _ = pointed_arch(hw, GATE_HEIGHT, GATE_POINTEDNESS,
                                          offset=-DOOR_GAP, n_arc=12)
    hw_d = hw - DOOR_GAP
    c = hw * GATE_POINTEDNESS
    R = hw + c - DOOR_GAP
    seam = DOOR_GAP / 2.0
    seam_z = d_spring + math.sqrt(R * R - (c + seam) ** 2)
    n_left = len(door_path) // 2      # точки від лівої п'яти до замка (без нього)
    left_arc = [p for p in door_path[:n_left] if p[0] < -seam - 1e-3]
    left_poly = left_arc + [(-seam, seam_z), (-seam, 0.0)]

    for side, tag in ((-1, "Left"), (1, "Right")):
        hinge_x = side * hw_d
        # Локальні координати стулки: x — від осі петель, y — товщина (у бік зали), z — вгору.
        poly = [((x if side < 0 else -x) - hinge_x, z) for x, z in left_poly]
        door = MeshBuilder(f"Gate_Door_{tag}")
        door.prism(poly, 0.0, DOOR_THICKNESS, AXIS_XZ_EXTRUDE_Y)
        front0, front1 = DOOR_THICKNESS, DOOR_THICKNESS + 0.06
        door.sweep(inset_polygon(poly, 0.45), 0.09, front0, front1, AXIS_XZ_EXTRUDE_Y, closed=True)
        for zs in (2.0, 5.5, 8.5):
            rng_x = x_range_at(poly, zs)
            if rng_x and rng_x[1] - rng_x[0] > 1.0:
                door.box(rng_x[0] + 0.25, rng_x[1] - 0.25, front0, front1 + 0.02,
                         zs - 0.15, zs + 0.15)                       # металеві пояси
        door_world = (hinge_x, DOOR_BACK_Y, 0.0)
        door_obj = door.build(coll, [mats["metal"]], location=door_world,
                              props={"interactive": True, "anim": "rotate_local_z",
                                     "open_deg": side * DOOR_OPEN_DEG,
                                     "note": "Origin = зовнішня вісь петель (південна грань)"})
        neon = MeshBuilder(f"Gate_Door_{tag}_Neon")
        neon.sweep(inset_polygon(poly, 0.14), 0.05, front0, front0 + 0.1, AXIS_XZ_EXTRUDE_Y, closed=True)
        # Дочірній об'єкт зі спільним Origin: локальний зсув 0, тож рухається разом зі стулкою.
        neon_obj = neon.build(coll, [mats["neon"]],
                              props={"interactive": True, "weld_to": door_obj.name})
        neon_obj.parent = door_obj
        neon_obj.matrix_parent_inverse = Matrix.Identity(4)

    # --- Енергетичний бар'єр усередині арки ---
    bar_path, _, _ = pointed_arch(hw, GATE_HEIGHT, GATE_POINTEDNESS, offset=-0.05, n_arc=12)
    barrier = MeshBuilder("Gate_Barrier_Field")
    barrier.prism(bar_path, -0.03, 0.03, AXIS_XZ_EXTRUDE_Y)
    barrier.build(coll, [mats["barrier"]], location=(0.0, BARRIER_Y, 0.0),
                  props={"interactive": True, "anim": "fade_or_scale",
                         "note": "Origin = центр низу арки; CanCollide під час бою"})


# =============================================================================
# МАРКЕРИ
# =============================================================================

MARKER_PROPS = {"gameplay_marker": True, "roblox_transparency": 1.0,
                "roblox_can_collide": False, "roblox_anchored": True}


def build_spawn_marker(name, location, radius, coll, mats):
    mb = MeshBuilder(name)
    mb.lathe([(radius, 0.0), (radius, 0.06)], 16)
    arrow = [(-0.35 * radius, -0.2 * radius), (0.35 * radius, -0.2 * radius), (0.0, -0.95 * radius)]
    mb.prism(arrow, 0.06, 0.12)          # стрілка — напрямок погляду (на південь, до входу)
    obj = mb.build(coll, [mats["marker"]], location=location, props=dict(MARKER_PROPS))
    obj.hide_render = True
    return obj


def build_markers(coll, mats):
    spawn = build_spawn_marker("Boss_Spawn_Point", (0.0, NORTH_Y - 5.0, DAIS_HEIGHT), 1.0, coll, mats)
    spawn["role"] = "boss_spawn"
    for k, (x, y) in enumerate(MINION_SPAWNS, start=1):
        m = build_spawn_marker(f"Minion_Spawn_{k}", (x, y, 0.0), 0.8, coll, mats)
        m["role"] = "minion_spawn"
    sx, sy, sz = TRIGGER_ZONE_SIZE
    zone = MeshBuilder("Arena_Trigger_Zone")
    zone.box(-sx / 2, sx / 2, -sy / 2, sy / 2, -sz / 2, sz / 2)
    obj = zone.build(coll, [mats["marker"]], location=(0.0, 0.0, sz / 2),
                     props=dict(MARKER_PROPS, role="trigger_zone", roblox_can_touch=True))
    obj.display_type = "WIRE"
    obj.hide_render = True


# =============================================================================
# ПРЕВʼЮ-СВІТЛО
# =============================================================================

def add_preview_lights():
    def add(name, ltype, location, energy, color=(1, 1, 1), size=None, rotation=None):
        light = bpy.data.lights.new(name, type=ltype)
        light.energy = energy
        light.color = color
        if size is not None:
            light.shadow_soft_size = size
        obj = bpy.data.objects.new(name, light)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = location
        if rotation is not None:
            obj.rotation_euler = rotation
        return obj

    add("Preview_Moon", "SUN", (0, 0, 40), 0.6, (0.8, 0.85, 1.0), rotation=(0.6, 0.2, 0.4))
    for y in (-18.0, 0.0, 18.0):
        add(f"Preview_Fill_{int(y)}", "POINT", (0.0, y, 12.0), 4000.0, (0.9, 0.8, 1.0), 2.0)
    add("Preview_Dais", "POINT", (0.0, NORTH_Y - 6.0, 8.0), 2500.0, (0.7, 0.4, 1.0), 1.0)
    add("Preview_Gate", "POINT", (0.0, SOUTH_Y + 4.0, 6.0), 1500.0, (0.3, 0.7, 1.0), 1.0)


# =============================================================================
# ЕКСПОРТ
# =============================================================================

def script_args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def is_writable_dir(folder):
    """Реальна перевірка запису (os.access у Windows не бачить обмежень Program Files)."""
    if not folder or not os.path.isdir(folder):
        return False
    try:
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


def script_dir():
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


def resolve_export_path():
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
        print(f"[BOSS] EXPORT_DIR недоступна для запису: {candidates[0]}")
    for folder in candidates:
        if is_writable_dir(folder):
            return os.path.join(os.path.abspath(folder), EXPORT_FILENAME)
    raise RuntimeError("Не знайдено теки з правом запису для FBX — задайте EXPORT_DIR")


def show_message(text, icon="INFO"):
    print(f"[BOSS] {text}")
    if bpy.app.background or bpy.context.window_manager is None:
        return

    def draw(menu, _context):
        menu.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title="SAO Boss Room", icon=icon)


def export_fbx(path):
    try:
        import addon_utils
        addon_utils.enable("io_scene_fbx", default_set=True)
    except Exception as exc:  # аддон вбудований, тож це не критично
        print(f"[BOSS] Не вдалося явно увімкнути io_scene_fbx: {exc}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=path,
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
        use_custom_props=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
        batch_mode="OFF",
    )
    show_message(f"FBX для Roblox збережено: {path}")


def verify_triangle_budget():
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    over = [(o.name, triangle_count(o)) for o in meshes if triangle_count(o) > MAX_TRIS_PER_OBJECT]
    worst = max(meshes, key=triangle_count)
    total = sum(triangle_count(o) for o in meshes)
    print(f"[BOSS] Мешів: {len(meshes)}, трикутників: {total}; "
          f"найважчий {worst.name} = {triangle_count(worst)} (ліміт {MAX_TRIS_PER_OBJECT})")
    if over:
        raise RuntimeError(f"Перевищено ліміт трикутників: {over}")


def deselect_all():
    view_layer = bpy.context.view_layer
    view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj is not None and view_layer.objects.get(obj.name) is not None:
            obj.select_set(False)
    view_layer.objects.active = None


# =============================================================================
# MAIN
# =============================================================================

def main():
    if CLEAR_SCENE:
        clear_scene()
    setup_scene_units()
    mats = {key: make_material(spec) for key, spec in MATERIALS.items()}

    structure = get_collection(COLL_STRUCTURE)
    pillars = get_collection(COLL_PILLARS)
    gate = get_collection(COLL_GATE)
    markers = get_collection(COLL_MARKERS)

    build_floor(structure, mats)
    build_wall_frames(structure, mats)
    build_wall_glass(structure, mats)
    build_ceiling(structure, mats)
    build_dais(structure, mats)
    build_pillars(pillars, mats)
    build_gate(gate, mats)
    build_markers(markers, mats)
    if ADD_PREVIEW_LIGHTS:
        add_preview_lights()

    verify_triangle_budget()
    deselect_all()
    if AUTO_EXPORT and "--no-export" not in script_args():
        export_fbx(resolve_export_path())


if __name__ == "__main__":
    main()
