# -*- coding: utf-8 -*-
"""
sao_boss_entrance_gate.py
=========================

Передбанник та монументальна двостулкова брама Кімнати Боса 1-го поверху
Айнкраду (Sword Art Online) — процедурна генерація для Blender 5.3.

* Лише актуальний Python API: ``bpy`` (data-API, без застарілих операторів
  примітивів) та ``bmesh``. Єдиний оператор, який викликається, — експорт FBX
  (опціонально).
* 1 одиниця Blender = 1 метр.
* Стулки брами (Boss_Door_Left / Boss_Door_Right) — окремі об'єкти з нульовим
  обертанням, а їхні Origin стоять на вертикальних осях петель:
      Boss_Door_Left  -> (-3.6, 0.0, 0.0)
      Boss_Door_Right -> (+3.6, 0.0, 0.0)
  Після експорту в FBX з осями (Forward = -Z, Up = Y) вісь петель — це вісь Y
  у Roblox Studio. Двері відчиняються всередину Кімнати Боса (у бік +Y Blender
  / -Z Roblox).
* Жоден меш не перевищує 5 000 трикутників (перевірка + автоматичний
  Decimate-запобіжник, якщо бюджет колись буде перевищено після правок).

Запуск
------
1. Blender -> Scripting -> Open -> цей файл -> Run Script, або
2. ``blender --background --python sao_boss_entrance_gate.py -- --export [шлях.fbx]``

Аргументи після ``--``:
    --export            експортувати меші у FBX (увімкнено за замовчуванням)
    --no-export         не створювати FBX
    --export-path PATH  шлях до FBX (за замовчуванням поруч із .blend або у temp)
"""

import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# Налаштування
# ---------------------------------------------------------------------------

TRI_BUDGET = 5000                 # ліміт трикутників на один об'єкт (Roblox)
EXPORT_FBX = True                 # FBX для Roblox Studio створюється автоматично
EXPORT_PATH = "//sao_boss_entrance_gate.fbx"
RANDOM_SEED = 1                   # детермінована "потертість" підлоги та полум'я

COLL_HALL = "Prep_Hall_Structure"
COLL_DOORS = "Boss_Doors_Animatable"
COLL_FX = "Braziers_And_Markers"
COLL_PREVIEW = "Preview_Camera_And_Lights"   # лише для рендера, не експортується

# --- Зала очікування -------------------------------------------------------
HALL_W = 22.0          # X: -11 .. +11
HALL_D = 16.0          # Y: -16 .. 0 (стіна брами на Y = 0)
HALL_H = 11.0
WALL_T = 0.8
CHAMFER = 2.5          # скошені кути зали
PLINTH_H = 1.4
HALL_CENTER = Vector((0.0, -HALL_D / 2.0))

# --- Брама -----------------------------------------------------------------
GATE_HALF_W = 3.6      # проріз 7.2 м
GATE_H = 8.5           # висота арки у замку
DOOR_W = 3.6
DOOR_H = 8.0
DOOR_T = 0.45
ARCH_R = 6.0           # радіус пологої (сегментної) арки
ARCH_ZC = GATE_H - ARCH_R      # центр дуги прорізу  -> п'ята арки на 7.3 м
DOOR_ZC = DOOR_H - ARCH_R      # центр дуги стулок   -> край стулки 6.8 м
ARCH_SEG = 20                  # парне число: по 10 сегментів на кожну стулку

# Шари архівольта: (внутрішній відступ, зовнішній відступ, y_front, y_back, матеріал)
ARCH_LAYERS = (
    (0.00, 0.35, -0.50, 0.80, "stone_dark"),
    (0.35, 0.75, -0.80, 0.80, "stone_light"),
    (0.75, 0.95, -0.65, 0.80, "stone_dark"),
)
ARCH_OUTER = ARCH_LAYERS[-1][1]
PILASTER_X0 = GATE_HALF_W + ARCH_OUTER        # 4.55
PILASTER_W = 1.0                              # 4.55 .. 5.55
PILASTER_X1 = PILASTER_X0 + PILASTER_W
ENTABLATURE_Z = 9.5                           # низ фриза
CORNICE_TOP = 10.1                            # на карниз спираються балки

BEAM_XS = (-4.6, 0.0, 4.6)
BEAM_W = 1.8

BRAZIER_X = 6.6
BRAZIER_Z = 4.2
BRAZIER_Y = -0.95

ENTRANCE_HALF_W = 1.8
ENTRANCE_H = 4.5

# ---------------------------------------------------------------------------
# Матеріали (Principled BSDF)
# ---------------------------------------------------------------------------

MATERIAL_DEFS = {
    #  key            name                       base color              rough  metal  emission color         strength
    "stone_light": ("SAO_Stone_LightGrey",      (0.56, 0.54, 0.50),     0.85,  0.0,   None,                  0.0),
    "stone_dark":  ("SAO_Stone_DarkGrey",       (0.17, 0.16, 0.15),     0.90,  0.0,   None,                  0.0),
    "stone_worn":  ("SAO_Stone_Worn",           (0.38, 0.36, 0.33),     0.55,  0.0,   None,                  0.0),
    "door_panel":  ("SAO_Door_Stone",           (0.27, 0.25, 0.23),     0.80,  0.0,   None,                  0.0),
    "metal_dark":  ("SAO_Metal_DarkIron",       (0.10, 0.10, 0.11),     0.45,  1.0,   None,                  0.0),
    "bronze":      ("SAO_Metal_Bronze",         (0.42, 0.30, 0.17),     0.40,  1.0,   None,                  0.0),
    "embers":      ("SAO_Embers_Emission",      (0.20, 0.05, 0.01),     0.90,  0.0,   (1.00, 0.25, 0.04),    3.0),
    "flame":       ("SAO_Flame_Emission",       (1.00, 0.45, 0.08),     1.00,  0.0,   (1.00, 0.42, 0.07),   12.0),
    "flame_core":  ("SAO_FlameCore_Emission",   (1.00, 0.85, 0.35),     1.00,  0.0,   (1.00, 0.80, 0.30),   20.0),
    "neon_blue":   ("SAO_Neon_Blue_Emission",   (0.10, 0.55, 1.00),     0.20,  0.0,   (0.10, 0.55, 1.00),   15.0),
}

MATS = {}


def _principled(nt):
    for node in nt.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def _set_input(node, names, value):
    for name in names:
        sock = node.inputs.get(name)
        if sock is not None:
            sock.default_value = value
            return


def make_material(name, color, roughness, metallic, emission, strength):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    # У Blender 5.x матеріали завжди мають дерево нодів; use_nodes лише для старих версій.
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(nt)
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if bsdf is None or out is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (300, 0)
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    rgba = (*color, 1.0)
    _set_input(bsdf, ("Base Color",), rgba)
    _set_input(bsdf, ("Roughness",), roughness)
    _set_input(bsdf, ("Metallic",), metallic)
    if emission is not None:
        _set_input(bsdf, ("Emission Color",), (*emission, 1.0))
        _set_input(bsdf, ("Emission Strength",), strength)
    else:
        _set_input(bsdf, ("Emission Strength",), 0.0)

    # Колір у в'юпорті (і запасний колір для імпортерів, які не читають ноди).
    mat.diffuse_color = rgba
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def build_materials():
    MATS.clear()
    for key, (name, color, rough, metal, emis, strength) in MATERIAL_DEFS.items():
        MATS[key] = make_material(name, color, rough, metal, emis, strength)


# ---------------------------------------------------------------------------
# Геометричні утиліти (bmesh)
# ---------------------------------------------------------------------------

def _faces_of(verts):
    faces = set()
    for v in verts:
        faces.update(v.link_faces)
    return list(faces)


def _vec(v):
    return v if isinstance(v, Vector) else Vector(v)


class MeshBuilder:
    """Збирає один меш у bmesh із кількома матеріальними слотами."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.mats = []

    # --- матеріали ---------------------------------------------------------
    def mat_index(self, key):
        mat = MATS[key]
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def tag(self, faces, key, smooth=False):
        idx = self.mat_index(key)
        for f in faces:
            f.material_index = idx
            f.smooth = smooth
        return faces

    # --- примітиви ----------------------------------------------------------
    def box(self, center, size, key, rot_z=0.0, rot=None):
        rot_m = rot if rot is not None else Matrix.Rotation(rot_z, 4, 'Z')
        m = Matrix.Translation(_vec(center)) @ rot_m @ Matrix.Diagonal((*size, 1.0))
        res = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        return self.tag(_faces_of(res["verts"]), key)

    def box_mm(self, mn, mx, key):
        mn, mx = _vec(mn), _vec(mx)
        return self.box((mn + mx) / 2.0, tuple(mx - mn), key)

    def beam_between(self, p0, p1, width, depth, key):
        """Брус від p0 до p1 (перетин width x depth)."""
        p0, p1 = _vec(p0), _vec(p1)
        axis = p1 - p0
        length = axis.length
        d = axis.normalized()
        ref = Vector((1.0, 0.0, 0.0)) if abs(d.x) < 0.9 else Vector((0.0, 1.0, 0.0))
        side = d.cross(ref).normalized()
        up = side.cross(d).normalized()
        rot = Matrix((side, up, d)).transposed().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2.0) @ rot @ Matrix.Diagonal((width, depth, length, 1.0))
        res = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        return self.tag(_faces_of(res["verts"]), key)

    def cyl(self, center, r1, r2, depth, segs, key, smooth=True, rot=None):
        m = Matrix.Translation(_vec(center))
        if rot is not None:
            m = m @ rot
        res = bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=segs,
            radius1=r1, radius2=r2, depth=depth, matrix=m,
        )
        return self.tag(_faces_of(res["verts"]), key, smooth=smooth)

    def prism_xz(self, pts, y0, y1, key):
        """Призма з контуру в площині XZ, видавлена вздовж Y."""
        bm = self.bm
        vf = [bm.verts.new((x, y0, z)) for x, z in pts]
        vb = [bm.verts.new((x, y1, z)) for x, z in pts]
        faces = [bm.faces.new(vf), bm.faces.new(vb[::-1])]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            faces.append(bm.faces.new((vf[i], vb[i], vb[j], vf[j])))
        return self.tag(faces, key)

    def prism_xy(self, pts, z0, z1, key):
        """Призма з контуру в площині XY, видавлена вздовж Z."""
        bm = self.bm
        vb = [bm.verts.new((x, y, z0)) for x, y in pts]
        vt = [bm.verts.new((x, y, z1)) for x, y in pts]
        faces = [bm.faces.new(vb[::-1]), bm.faces.new(vt)]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            faces.append(bm.faces.new((vb[i], vb[j], vt[j], vt[i])))
        return self.tag(faces, key)

    def sweep(self, sections, key, smooth=False):
        """Замкнений солід із послідовності чотирикутних перерізів."""
        bm = self.bm
        rings = [[bm.verts.new(_vec(p)) for p in sec] for sec in sections]
        faces = [bm.faces.new(rings[0][::-1]), bm.faces.new(rings[-1])]
        for a, b in zip(rings[:-1], rings[1:]):
            for k in range(4):
                k2 = (k + 1) % 4
                faces.append(bm.faces.new((a[k], a[k2], b[k2], b[k])))
        return self.tag(faces, key, smooth=smooth)

    def inset_face(self, faces, pick_dir, thickness, depth, inner_key=None):
        """Знаходить грань, найбільш спрямовану в pick_dir, та робить inset."""
        for f in faces:
            f.normal_update()
        pick_dir = _vec(pick_dir)
        face = max(faces, key=lambda f: f.normal.dot(pick_dir))
        res = bmesh.ops.inset_region(self.bm, faces=[face], thickness=thickness,
                                     depth=depth, use_even_offset=True)
        if inner_key is not None:
            face.material_index = self.mat_index(inner_key)
        side = res.get("faces", [])
        for f in side:
            f.material_index = faces[0].material_index
        return face

    # --- завершення ---------------------------------------------------------
    def finalize(self, collection, location=(0.0, 0.0, 0.0), uv_scale=0.25):
        bm = self.bm
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.normal_update()
        box_project_uv(bm, uv_scale)

        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for mat in self.mats:
            me.materials.append(mat)
        if hasattr(me, "set_sharp_from_angle"):
            me.set_sharp_from_angle(angle=math.radians(35.0))
        me.update()

        obj = bpy.data.objects.new(self.name, me)
        obj.location = location
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)
        collection.objects.link(obj)
        return obj


def box_project_uv(bm, scale):
    """Простий кубічний UV (Roblox потребує UV для SurfaceAppearance)."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            co = loop.vert.co
            if az >= ax and az >= ay:
                loop[uv].uv = (co.x * scale, co.y * scale)
            elif ax >= ay:
                loop[uv].uv = (co.y * scale, co.z * scale)
            else:
                loop[uv].uv = (co.x * scale, co.z * scale)


def offset_polyline(pts, dist, closed=False, center=HALL_CENTER):
    """Зміщує полілінію (у плані XY) на dist від центру зали (з мітрою)."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    edge_normals = []
    edge_count = n if closed else n - 1
    for i in range(edge_count):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b - a).normalized()
        nrm = Vector((d.y, -d.x))
        if nrm.dot((a + b) / 2.0 - center) < 0.0:
            nrm = -nrm
        edge_normals.append(nrm)
    out = []
    for i in range(n):
        if closed:
            n1, n2 = edge_normals[i - 1], edge_normals[i % edge_count]
        else:
            n1 = edge_normals[max(i - 1, 0)]
            n2 = edge_normals[min(i, edge_count - 1)]
        m = (n1 + n2).normalized()
        out.append(pts[i] + m * (dist / max(m.dot(n1), 0.2)))
    return out


def wall_from_polyline(b, pts, z0, z1, d_in, d_out, key):
    """Стінка вздовж полілінії: від зсуву d_in до d_out (від'ємне = в залу)."""
    inner = offset_polyline(pts, d_in)
    outer = offset_polyline(pts, d_out)
    sections = []
    for pi, po in zip(inner, outer):
        sections.append((
            (pi.x, pi.y, z0), (po.x, po.y, z0), (po.x, po.y, z1), (pi.x, pi.y, z1),
        ))
    return b.sweep(sections, key)


def arch_profile(half_w, zc, radius, segs):
    """Профіль прорізу: ліва стійка -> сегментна дуга -> права стійка (XZ)."""
    th0 = math.asin(half_w / radius)
    pts = [(-half_w, 0.0)]
    for i in range(segs + 1):
        t = -th0 + 2.0 * th0 * i / segs
        pts.append((radius * math.sin(t), zc + radius * math.cos(t)))
    pts.append((half_w, 0.0))
    return pts


def arc_band_sections(inner, outer, y0, y1):
    return [
        ((xi, y0, zi), (xo, y0, zo), (xo, y1, zo), (xi, y1, zi))
        for (xi, zi), (xo, zo) in zip(inner, outer)
    ]


def door_top_z(x):
    return DOOR_ZC + math.sqrt(max(ARCH_R ** 2 - x * x, 0.0))


# ---------------------------------------------------------------------------
# Колекції та очищення
# ---------------------------------------------------------------------------

def remove_default_startup_cube():
    """Прибирає лише незмінений стартовий 'Cube' (2x2x2 м у центрі світу),
    бо він стоїть рівно на порозі брами. Інші об'єкти користувача не чіпаються."""
    obj = bpy.data.objects.get("Cube")
    if (obj is None or obj.type != 'MESH' or len(obj.data.vertices) != 8
            or obj.location.length > 1e-6 or any(abs(a) > 1e-6 for a in obj.rotation_euler)
            or any(abs(s - 1.0) > 1e-6 for s in obj.scale)):
        return
    me = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if me.users == 0:
        bpy.data.meshes.remove(me)


def get_clean_collection(name, parent):
    coll = bpy.data.collections.get(name)
    if coll is not None:
        for obj in list(coll.all_objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
        bpy.data.collections.remove(coll)
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


# ---------------------------------------------------------------------------
# 1. Prep_Hall_Structure
# ---------------------------------------------------------------------------

def interior_octagon():
    hw, d, c = HALL_W / 2.0, HALL_D, CHAMFER
    return [
        (-hw + c, 0.0), (hw - c, 0.0), (hw, -c), (hw, -d + c),
        (hw - c, -d), (-hw + c, -d), (-hw, -d + c), (-hw, -c),
    ]


def build_floor(coll, rng):
    b = MeshBuilder("Prep_Floor")
    hw = HALL_W / 2.0
    # Основа-"розчин" між плитами (темний камінь, видно у швах).
    b.box_mm((-hw, -HALL_D, -0.40), (hw, 0.0, -0.03), "stone_dark")

    row_d, tile_w, gap = 1.6, 2.2, 0.025
    rows = int(round(HALL_D / row_d))
    for r in range(rows):
        y0 = -HALL_D + r * row_d
        x = -hw - (tile_w / 2.0 if r % 2 else 0.0)
        while x < hw - 1e-6:
            xa, xb = max(x, -hw), min(x + tile_w, hw)
            x += tile_w
            if xb - xa < 0.3:
                continue
            cx, cy = (xa + xb) / 2.0, y0 + row_d / 2.0
            # Потертість: центральна "доріжка" до брами стерта сильніше.
            lane = abs(cx) < 2.6
            near_gate = cy > -5.0
            worn = (lane and rng.random() < (0.85 if near_gate else 0.6)) or rng.random() < 0.12
            sink = rng.uniform(0.0, 0.025) + (0.015 if worn else 0.0)
            top = -sink
            faces = b.box_mm((xa + gap, y0 + gap, -0.16), (xb - gap, y0 + row_d - gap, top),
                             "stone_worn" if worn else "stone_light")
            # Фаска/вибоїна верхньої грані.
            b.inset_face(faces, (0, 0, 1), thickness=0.05 if not worn else 0.12,
                         depth=0.008 if not worn else -0.012)
            # Легкий нахил плити — нерівна стара підлога.
            ax_, ay_ = rng.uniform(-0.006, 0.006), rng.uniform(-0.006, 0.006)
            for v in {v for f in faces for v in f.verts}:
                if v.co.z > -0.1:
                    v.co.z += ax_ * (v.co.x - cx) + ay_ * (v.co.y - cy)
    return b.finalize(coll)


def build_walls_and_columns(coll):
    b = MeshBuilder("Prep_Walls_And_Columns")
    hw, d, c = HALL_W / 2.0, HALL_D, CHAMFER
    ex = ENTRANCE_HALF_W
    side_a = [(PILASTER_X1, 0.0), (hw - c, 0.0), (hw, -c), (hw, -d + c), (hw - c, -d), (ex, -d)]
    side_b = [(-x, y) for x, y in reversed(side_a)]

    for poly in (side_a, side_b):
        # Основна стіна
        wall_from_polyline(b, poly, 0.0, HALL_H, 0.0, WALL_T, "stone_light")
        # Масивний цоколь 1.4 м + профільований карниз цоколя
        wall_from_polyline(b, poly, 0.0, PLINTH_H, -0.25, 0.05, "stone_dark")
        wall_from_polyline(b, poly, PLINTH_H, PLINTH_H + 0.15, -0.32, 0.05, "stone_dark")
        # Верхній карниз стіни під стелею
        wall_from_polyline(b, poly, HALL_H - 0.3, HALL_H, -0.18, 0.05, "stone_dark")

    # Стіна над рамою брами та перемичка над вхідним прорізом
    wall_from_polyline(b, [(PILASTER_X1, 0.0), (-PILASTER_X1, 0.0)], ENTABLATURE_Z, HALL_H,
                       0.0, WALL_T, "stone_light")
    wall_from_polyline(b, [(ex, -d), (-ex, -d)], ENTRANCE_H, HALL_H, 0.0, WALL_T, "stone_light")

    # Обрамлення вхідного прорізу (з боку гравця)
    for s in (-1, 1):
        b.box_mm((min(s * ex, s * (ex + 0.5)), -d, 0.0), (max(s * ex, s * (ex + 0.5)), -d + 0.3, ENTRANCE_H),
                 "stone_dark")
    b.box_mm((-ex - 0.5, -d, ENTRANCE_H), (ex + 0.5, -d + 0.35, ENTRANCE_H + 0.6), "stone_dark")

    # Пілястри задньої стіни під бічними балками + консоль під центральною балкою
    for bx in BEAM_XS:
        if abs(bx) < 1e-6:
            b.box_mm((-0.7, -d, 8.9), (0.7, -d + 0.4, 9.3), "stone_dark")
            b.box_mm((-0.95, -d, 9.3), (0.95, -d + 0.6, CORNICE_TOP), "stone_dark")
            continue
        b.box_mm((bx - 0.8, -d, 0.0), (bx + 0.8, -d + 0.5, CORNICE_TOP), "stone_light")
        b.box_mm((bx - 0.95, -d, 0.0), (bx + 0.95, -d + 0.65, 0.9), "stone_dark")
        b.box_mm((bx - 1.0, -d, 9.5), (bx + 1.0, -d + 0.7, CORNICE_TOP), "stone_dark")

    # Стінові панелі (рамка + заглиблене поле)
    panel_segments = [
        ((hw - c, 0.0), (hw, -c)),
        ((hw, -c), (hw, -d + c)),
        ((hw, -d + c), (hw - c, -d)),
        ((hw - c, -d), (BEAM_XS[2] + 1.0, -d)),
    ]
    panel_segments += [((-a[0], a[1]), (-b_[0], b_[1])) for a, b_ in panel_segments]
    for p0, p1 in panel_segments:
        add_wall_panels(b, Vector(p0), Vector(p1))

    # Дві великі круглі колони біля скошених кутів поруч із брамою
    for s in (-1, 1):
        p0, p1 = Vector((s * (hw - c), 0.0)), Vector((s * hw, -c))
        mid = (p0 + p1) / 2.0
        inward = (HALL_CENTER - mid)
        inward = Vector((inward.x, inward.y)).normalized()
        n_edge = Vector((-(p1 - p0).y, (p1 - p0).x)).normalized()
        if n_edge.dot(inward) < 0:
            n_edge = -n_edge
        center = mid + n_edge * 1.15
        add_column(b, center, math.atan2((p1 - p0).y, (p1 - p0).x))
    return b.finalize(coll)


def add_wall_panels(b, p0, p1, z0=2.2, z1=8.6):
    length = (p1 - p0).length
    if length < 1.6:
        return
    n = max(1, int(length // 3.4))
    slot = length / n
    w = slot - 0.8
    d = (p1 - p0).normalized()
    nrm = Vector((d.y, -d.x))
    mid = (p0 + p1) / 2.0
    if nrm.dot(HALL_CENTER - mid) < 0:
        nrm = -nrm                      # у бік зали
    rot = math.atan2(d.y, d.x)
    for k in range(n):
        p = p0 + d * (slot * (k + 0.5)) + nrm * 0.06
        faces = b.box((p.x, p.y, (z0 + z1) / 2.0), (w, 0.12, z1 - z0), "stone_light", rot_z=rot)
        b.inset_face(faces, (nrm.x, nrm.y, 0.0), thickness=0.18, depth=-0.08, inner_key="stone_dark")


def add_column(b, c, rot):
    cx, cy = c.x, c.y
    seg = 20
    # База
    b.box((cx, cy, 0.225), (1.9, 1.9, 0.45), "stone_dark", rot_z=rot)
    b.cyl((cx, cy, 0.575), 0.98, 0.98, 0.25, seg, "stone_light")
    b.cyl((cx, cy, 0.85), 0.90, 0.80, 0.30, seg, "stone_light")
    b.cyl((cx, cy, 1.10), 0.80, 0.76, 0.20, seg, "stone_dark")
    # Різьблення бази (вінець блоків)
    for i in range(12):
        a = 2.0 * math.pi * i / 12
        b.box((cx + math.cos(a) * 0.99, cy + math.sin(a) * 0.99, 0.575), (0.12, 0.16, 0.18),
              "stone_dark", rot_z=a)
    # Стовбур
    b.cyl((cx, cy, (1.2 + 9.6) / 2.0), 0.74, 0.68, 8.4, seg, "stone_light")
    b.cyl((cx, cy, 1.35), 0.79, 0.79, 0.12, seg, "stone_dark")
    b.cyl((cx, cy, 9.45), 0.74, 0.74, 0.12, seg, "stone_dark")
    # Капітель
    b.cyl((cx, cy, 9.9), 0.70, 0.98, 0.60, seg, "stone_light")
    for i in range(12):
        a = 2.0 * math.pi * (i + 0.5) / 12
        b.box((cx + math.cos(a) * 0.86, cy + math.sin(a) * 0.86, 9.88), (0.1, 0.18, 0.22),
              "stone_dark", rot_z=a)
    b.box((cx, cy, 10.375), (2.0, 2.0, 0.35), "stone_dark", rot_z=rot)
    b.box((cx, cy, 10.775), (1.6, 1.6, 0.45), "stone_light", rot_z=rot)


def build_ceiling(coll):
    b = MeshBuilder("Prep_Ceiling_Beams")
    outline = offset_polyline(interior_octagon(), WALL_T, closed=True)
    b.prism_xy([(p.x, p.y) for p in outline], HALL_H, HALL_H + 0.6, "stone_dark")
    for bx in BEAM_XS:
        # Широка поздовжня балка: від задньої стіни до карниза брами
        b.box_mm((bx - BEAM_W / 2, -HALL_D, CORNICE_TOP), (bx + BEAM_W / 2, WALL_T, HALL_H + 0.05),
                 "stone_light")
        # Декоративна смуга-софіт під балкою
        b.box_mm((bx - 0.45, -HALL_D + 0.9, CORNICE_TOP - 0.1), (bx + 0.45, -1.5, CORNICE_TOP),
                 "stone_dark")
        # Поперечні накладки-"хомути"
        for y in (-12.0, -8.0, -4.0):
            b.box_mm((bx - BEAM_W / 2 - 0.05, y - 0.2, CORNICE_TOP - 0.05),
                     (bx + BEAM_W / 2 + 0.05, y + 0.2, CORNICE_TOP + 0.35), "stone_dark")
    return b.finalize(coll)


# ---------------------------------------------------------------------------
# 2. Boss_Doors_Animatable
# ---------------------------------------------------------------------------

def build_arch_frame(coll):
    b = MeshBuilder("Boss_Door_Arch_Frame")
    n = ARCH_SEG

    # Шар 0: кам'яна "голова" прорізу між верхом стулок (8.0) та аркою (8.5) — упор.
    door_arc = arch_profile(GATE_HALF_W, DOOR_ZC, ARCH_R, n)[1:-1]
    gate_arc = arch_profile(GATE_HALF_W, ARCH_ZC, ARCH_R, n)[1:-1]
    b.sweep(arc_band_sections(door_arc, gate_arc, -0.35, 0.80), "stone_dark")

    # Багатошаровий архівольт зі стійками
    for d_in, d_out, y0, y1, key in ARCH_LAYERS:
        inner = arch_profile(GATE_HALF_W + d_in, ARCH_ZC, ARCH_R + d_in, n)
        outer = arch_profile(GATE_HALF_W + d_out, ARCH_ZC, ARCH_R + d_out, n)
        b.sweep(arc_band_sections(inner, outer, y0, y1), key)

    # Пазухи арки (заповнення до фриза)
    outer_arc = arch_profile(PILASTER_X0, ARCH_ZC, ARCH_R + ARCH_OUTER, n)[1:-1]
    top_line = [(x, ENTABLATURE_Z) for x, _ in outer_arc]
    b.sweep(arc_band_sections(outer_arc, top_line, -0.40, 0.80), "stone_light")

    # Бічні різьблені пілястри
    for s in (-1, 1):
        cx = s * (PILASTER_X0 + PILASTER_W / 2.0)
        b.box_mm((cx - 0.5, -1.0, 0.0), (cx + 0.5, 0.8, ENTABLATURE_Z), "stone_light")
        b.box_mm((cx - 0.65, -1.15, 0.0), (cx + 0.65, 0.8, 0.9), "stone_dark")          # база
        b.box_mm((cx - 0.6, -1.08, 0.9), (cx + 0.6, 0.8, 1.05), "stone_dark")
        b.box_mm((cx - 0.65, -1.15, 8.8), (cx + 0.65, 0.8, ENTABLATURE_Z), "stone_dark")  # капітель
        b.box_mm((cx - 0.6, -1.08, 8.65), (cx + 0.6, 0.8, 8.8), "stone_dark")
        # Різьблення: вертикальні валики + ланцюг ромбів
        for ex in (-0.4, 0.4):
            b.box_mm((cx + ex - 0.05, -1.07, 1.05), (cx + ex + 0.05, -0.95, 8.65), "stone_dark")
        rot45 = Matrix.Rotation(math.pi / 4.0, 4, 'Y')
        z = 1.5
        while z < 8.3:
            b.box((cx, -1.03, z), (0.38, 0.1, 0.38), "stone_dark", rot=rot45)
            b.box((cx, -1.09, z), (0.16, 0.06, 0.16), "stone_light", rot=rot45)
            z += 0.85

    # Фриз, замковий карниз і замковий камінь
    b.box_mm((-PILASTER_X1 - 0.15, -1.05, ENTABLATURE_Z), (PILASTER_X1 + 0.15, 0.8, 9.8), "stone_light")
    b.box_mm((-PILASTER_X1 - 0.5, -1.2, 9.8), (PILASTER_X1 + 0.5, 0.8, 9.95), "stone_dark")
    b.box_mm((-PILASTER_X1 - 0.65, -1.35, 9.95), (PILASTER_X1 + 0.65, 0.8, CORNICE_TOP), "stone_dark")
    b.prism_xz([(-0.4, GATE_H - 0.05), (0.4, GATE_H - 0.05), (0.6, 9.8), (-0.6, 9.8)],
               -1.0, 0.8, "stone_light")
    b.prism_xz([(-0.22, GATE_H + 0.25), (0.22, GATE_H + 0.25), (0.32, 9.6), (-0.32, 9.6)],
               -1.1, -0.9, "stone_dark")
    return b.finalize(coll)


def build_door_left_geometry():
    """Ліва стулка у світових координатах (x від -3.6 до 0)."""
    b = MeshBuilder("Boss_Door_Left")
    hy = DOOR_T / 2.0                       # 0.225
    front = -hy                             # лицьова сторона дивиться в залу (-Y)
    half = ARCH_SEG // 2
    th0 = math.asin(GATE_HALF_W / ARCH_R)

    # Корпус стулки: прямокутник із сегментним верхом
    arc = []
    for i in range(half + 1):               # від замка (x = 0) до краю (x = -3.6)
        t = -th0 * i / half
        arc.append((ARCH_R * math.sin(t), DOOR_ZC + ARCH_R * math.cos(t)))
    outline = [(-DOOR_W, 0.0), (0.0, 0.0)] + arc
    b.prism_xz(outline, -hy, hy, "door_panel")

    # Металева окантовка: верхня дуга, зовнішній брус, нижня рейка, центральний хребет
    arc_rev = arc[::-1]
    b.sweep(arc_band_sections([(x, z - 0.22) for x, z in arc_rev], arc_rev, front - 0.06, front + 0.01),
            "metal_dark")
    b.box_mm((-DOOR_W, front - 0.06, 0.0), (-DOOR_W + 0.22, front + 0.01, door_top_z(-DOOR_W) - 0.05),
             "metal_dark")
    b.box_mm((-DOOR_W, front - 0.06, 0.0), (0.0, front + 0.01, 0.25), "metal_dark")
    b.box_mm((-0.16, front - 0.08, 0.25), (0.0, front + 0.01, DOOR_H - 0.2), "metal_dark")

    # Горизонтальна рельєфна обшивка
    z, plank_h = 0.42, 0.36
    while z + plank_h < DOOR_H - 0.25:
        zt = z + plank_h
        dz = zt + 0.25 - DOOR_ZC
        if dz < ARCH_R:
            xlim = math.sqrt(ARCH_R ** 2 - dz ** 2)
            xa, xb = -min(DOOR_W - 0.3, xlim), -0.2
            if xb - xa > 0.3:
                b.box_mm((xa, front - 0.035, z), (xb, front + 0.01, zt), "door_panel")
        z += plank_h + 0.07

    # Вертикальні металеві ребра жорсткості із заклепками
    for x0 in (-2.75, -1.65):
        top = door_top_z(x0) - 0.3
        b.box_mm((x0 - 0.1, front - 0.1, 0.3), (x0 + 0.1, front + 0.01, top), "metal_dark")
        zr = 0.7
        while zr < top - 0.2:
            b.box((x0, front - 0.12, zr), (0.09, 0.06, 0.09), "bronze")
            zr += 0.8

    # Центральна ромбоподібна емблема — рівно ЛІВА половина (x <= 0)
    ez = 4.2
    b.prism_xz([(0.0, ez - 1.8), (0.0, ez + 1.8), (-0.95, ez)], front - 0.12, front + 0.01, "bronze")
    b.prism_xz([(0.0, ez - 1.25), (0.0, ez + 1.25), (-0.6, ez)], front - 0.2, front - 0.1, "metal_dark")
    disc = [(-0.3 * math.sin(math.pi * k / 8), ez + 0.3 * math.cos(math.pi * k / 8)) for k in range(9)]
    b.prism_xz(disc, front - 0.27, front - 0.18, "bronze")
    for oz in (1.3, 7.05):                  # малі півромби на хребті (як на референсі)
        b.prism_xz([(0.0, oz - 0.45), (0.0, oz + 0.45), (-0.32, oz)], front - 0.14, front + 0.01, "bronze")

    # Петлі: барабани на осі (X = -3.6, Y = 0) + накладні смуги з обох боків
    for hz in (1.1, 3.9, 6.2):
        b.cyl((-DOOR_W, 0.0, hz), 0.13, 0.13, 0.7, 10, "metal_dark")
        for y0, y1 in ((front - 0.07, front + 0.01), (hy - 0.01, hy + 0.07)):
            b.box_mm((-DOOR_W + 0.05, y0, hz - 0.12), (-DOOR_W + 1.4, y1, hz + 0.12), "metal_dark")

    # Тильна сторона (з боку Кімнати Боса): поперечні металеві засуви
    for bz in (1.6, 4.0, 6.0):
        b.box_mm((-DOOR_W + 0.2, hy - 0.01, bz - 0.15), (-0.2, hy + 0.06, bz + 0.15), "metal_dark")
    return b


def build_doors(coll):
    left = build_door_left_geometry()

    # Права стулка — дзеркальна копія (емблема автоматично стає ПРАВОЮ половиною)
    right = MeshBuilder("Boss_Door_Right")
    right.bm.free()
    right.bm = left.bm.copy()
    right.mats = list(left.mats)
    bmesh.ops.scale(right.bm, vec=(-1.0, 1.0, 1.0), verts=right.bm.verts[:])
    bmesh.ops.reverse_faces(right.bm, faces=right.bm.faces[:])

    # Перенос Origin на осі петель: геометрія в локальних координатах відносно петлі
    hinge_l = Vector((-GATE_HALF_W, 0.0, 0.0))
    hinge_r = Vector((GATE_HALF_W, 0.0, 0.0))
    bmesh.ops.translate(left.bm, vec=-hinge_l, verts=left.bm.verts[:])
    bmesh.ops.translate(right.bm, vec=-hinge_r, verts=right.bm.verts[:])

    obj_l = left.finalize(coll, location=hinge_l)
    obj_r = right.finalize(coll, location=hinge_r)
    for obj, sign in ((obj_l, 1), (obj_r, -1)):
        # Довідкові властивості (корисні для скриптів/імпортерів, що читають custom props)
        obj["hinge_axis_roblox"] = "Y"
        obj["open_direction"] = "into boss room (+Y Blender / -Z Roblox)"
        obj["suggested_open_angle_deg"] = 100.0 * sign
    return obj_l, obj_r


# ---------------------------------------------------------------------------
# 3. Braziers_And_Markers
# ---------------------------------------------------------------------------

def flame_tongue(b, base, r0, h, sway, twist, rng, key, rings=5, segs=7):
    bm = b.bm
    base = _vec(base)
    sway = _vec(sway)
    ring_verts = []
    for k in range(rings):
        t = k / rings
        r = r0 * (1.0 - t) ** 0.75 * (1.0 + 0.25 * math.sin(t * math.pi))
        off = sway * (t ** 1.5)
        ring = []
        for j in range(segs):
            a = 2.0 * math.pi * j / segs + twist * t
            jr = r * (1.0 + rng.uniform(-0.2, 0.2))
            ring.append(bm.verts.new((base.x + off.x + jr * math.cos(a),
                                      base.y + off.y + jr * math.sin(a),
                                      base.z + t * h)))
        ring_verts.append(ring)
    apex = bm.verts.new(base + sway + Vector((0.0, 0.0, h)))
    faces = [bm.faces.new(ring_verts[0][::-1])]
    for a_ring, b_ring in zip(ring_verts[:-1], ring_verts[1:]):
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append(bm.faces.new((a_ring[j], a_ring[j2], b_ring[j2], b_ring[j])))
    top = ring_verts[-1]
    for j in range(segs):
        faces.append(bm.faces.new((top[j], top[(j + 1) % segs], apex)))
    b.tag(faces, key, smooth=True)


def build_brazier(coll, name, side, rng):
    b = MeshBuilder(name)
    wall_y = -BRAZIER_Y                     # стіна в локальних координатах (0.95)
    # Настінна плита, кронштейн і підкіс
    b.box_mm((-0.35, wall_y - 0.1, -1.35), (0.35, wall_y, 0.15), "metal_dark")
    b.box_mm((-0.25, wall_y - 0.14, -1.2), (0.25, wall_y - 0.1, 0.0), "bronze")
    b.box_mm((-0.08, 0.0, -0.4), (0.08, wall_y - 0.1, -0.24), "metal_dark")
    b.beam_between((0.0, wall_y - 0.1, -1.15), (0.0, 0.05, -0.5), 0.12, 0.12, "metal_dark")
    # Ніжка з наконечником
    b.cyl((0.0, 0.0, -0.735), 0.03, 0.2, 0.23, 10, "bronze")
    b.cyl((0.0, 0.0, -0.435), 0.12, 0.11, 0.37, 10, "metal_dark")
    # Кам'яно-металева чаша
    b.cyl((0.0, 0.0, -0.04), 0.24, 0.62, 0.42, 16, "stone_dark")
    b.cyl((0.0, 0.0, -0.20), 0.30, 0.30, 0.10, 16, "bronze")
    b.cyl((0.0, 0.0, 0.18), 0.67, 0.67, 0.12, 16, "metal_dark")
    for i in range(8):
        a = 2.0 * math.pi * i / 8
        b.box((math.cos(a) * 0.47, math.sin(a) * 0.47, -0.02), (0.08, 0.1, 0.26), "bronze", rot_z=a)
    # Жар
    b.cyl((0.0, 0.0, 0.255), 0.56, 0.2, 0.17, 12, "embers")
    obj = b.finalize(coll, location=(side * BRAZIER_X, BRAZIER_Y, BRAZIER_Z))

    # Окремий меш полум'я (Emission) над чашею жаровні
    f = MeshBuilder(name + "_Flame")
    flame_tongue(f, (0, 0, 0), 0.34, 1.15, (0.0, 0.0, 0.0), 1.4, rng, "flame")
    for k in range(3):
        a = 2.0 * math.pi * k / 3 + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(a), math.sin(a), 0.0))
        flame_tongue(f, d * 0.22, 0.2, rng.uniform(0.65, 0.9), d * 0.12, -1.2, rng, "flame")
    flame_tongue(f, (0, 0, 0.02), 0.18, 0.62, (0.0, 0.0, 0.0), 0.8, rng, "flame_core")
    # Без parent: пласка ієрархія надійніше імпортується в Roblox Studio.
    flame = f.finalize(coll, location=(side * BRAZIER_X, BRAZIER_Y, BRAZIER_Z + 0.3))
    return obj, flame


def build_threshold_markers(coll):
    b = MeshBuilder("Threshold_Blue_Markers")
    bm = b.bm
    count, spacing = 10, 1.2
    for i in range(count):
        x = (i - (count - 1) / 2.0) * spacing
        b.cyl((x, 0.0, 0.04), 0.16, 0.13, 0.08, 6, "metal_dark", smooth=False)
        # Видовжений октаедр-кристал
        cz, hh, r = 0.45, 0.25, 0.11
        top = bm.verts.new((x, 0.0, cz + hh))
        bot = bm.verts.new((x, 0.0, cz - hh))
        eq = [bm.verts.new((x + r * math.cos(a), r * math.sin(a), cz))
              for a in (math.pi / 4 + k * math.pi / 2 for k in range(4))]
        faces = []
        for k in range(4):
            k2 = (k + 1) % 4
            faces.append(bm.faces.new((eq[k], eq[k2], top)))
            faces.append(bm.faces.new((eq[k2], eq[k], bot)))
        b.tag(faces, "neon_blue")
    return b.finalize(coll, location=(0.0, -1.6, 0.0))


# ---------------------------------------------------------------------------
# Попередній перегляд: світло, камера, світ (не експортується)
# ---------------------------------------------------------------------------

def build_preview(coll, scene):
    def light(name, ltype, loc, energy, color, size=0.3):
        data = bpy.data.lights.new(name, type=ltype)
        data.energy = energy
        data.color = color
        data.shadow_soft_size = size
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        coll.objects.link(obj)
        return obj

    for s in (-1, 1):
        light(f"Light_Brazier_{'L' if s < 0 else 'R'}", 'POINT',
              (s * BRAZIER_X, BRAZIER_Y - 0.3, BRAZIER_Z + 0.8), 900.0, (1.0, 0.55, 0.2))
    light("Light_Threshold_Blue", 'POINT', (0.0, -2.0, 0.6), 150.0, (0.2, 0.55, 1.0), 1.0)
    fill = light("Light_Hall_Fill", 'AREA', (0.0, -9.0, 10.0), 600.0, (1.0, 0.85, 0.7), 1.0)
    fill.data.size = 8.0

    cam_data = bpy.data.cameras.new("Preview_Camera")
    cam_data.lens = 22.0
    cam = bpy.data.objects.new("Preview_Camera", cam_data)
    cam.location = (0.0, -15.2, 2.0)
    direction = Vector((0.0, 0.0, 4.6)) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    coll.objects.link(cam)
    scene.camera = cam

    world = scene.world or bpy.data.worlds.new("SAO_World")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is not None:
        bg.inputs["Color"].default_value = (0.008, 0.008, 0.012, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    engines = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    for candidate in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        if candidate in engines:
            scene.render.engine = candidate
            break


# ---------------------------------------------------------------------------
# Перевірки під Roblox
# ---------------------------------------------------------------------------

def tri_count(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def enforce_tri_budget(objs):
    """Перевіряє бюджет; якщо меш завеликий — зменшує його Decimate без bpy.ops."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objs:
        tris = tri_count(obj.data)
        if tris <= TRI_BUDGET:
            continue
        print(f"[WARN] {obj.name}: {tris} tris > {TRI_BUDGET}, застосовую Decimate")
        mod = obj.modifiers.new("Roblox_Budget", 'DECIMATE')
        mod.ratio = (TRI_BUDGET / tris) * 0.95
        depsgraph.update()
        new_me = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph),
                                                 preserve_all_data_layers=True, depsgraph=depsgraph)
        obj.modifiers.remove(mod)
        old = obj.data
        obj.data = new_me
        new_me.name = old.name
        bpy.data.meshes.remove(old)


def validate(objs, door_l, door_r):
    ok = True
    print("\n=== Бюджет трикутників (ліміт Roblox: %d на об'єкт) ===" % TRI_BUDGET)
    total = 0
    for obj in sorted(objs, key=lambda o: o.name):
        tris = tri_count(obj.data)
        total += tris
        status = "OK " if tris <= TRI_BUDGET else "FAIL"
        ok &= tris <= TRI_BUDGET
        print(f"  [{status}] {obj.name:<28} {tris:>6} tris  {len(obj.data.vertices):>6} verts")
    print(f"  Разом: {total} трикутників у {len(objs)} мешах")

    print("\n=== Петлі стулок ===")
    eps = 1e-5
    for obj, expected in ((door_l, Vector((-3.6, 0.0, 0.0))), (door_r, Vector((3.6, 0.0, 0.0)))):
        loc_ok = (obj.location - expected).length < eps
        rot_ok = all(abs(a) < eps for a in obj.rotation_euler)
        scl_ok = all(abs(s - 1.0) < eps for s in obj.scale)
        xs = [v.co.x for v in obj.data.vertices]
        width = max(abs(min(xs)), abs(max(xs)))
        ok &= loc_ok and rot_ok and scl_ok
        print(f"  {obj.name}: origin={tuple(round(c, 4) for c in obj.location)} "
              f"rotation={tuple(obj.rotation_euler)} scale={tuple(obj.scale)} "
              f"leaf_width={width:.3f} m -> {'OK' if loc_ok and rot_ok and scl_ok else 'FAIL'}")
    return ok


def export_fbx(objs, path):
    if not bpy.data.filepath and path.startswith("//"):
        # .blend ще не збережено -> кладемо FBX у домашню папку (не в temp)
        path = os.path.join(os.path.expanduser("~"), os.path.basename(path[2:]))
    path = bpy.path.abspath(path)
    view_layer = bpy.context.view_layer
    for o in view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    view_layer.objects.active = objs[0]
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={'MESH'},
        use_mesh_modifiers=True,
        mesh_smooth_type='FACE',
        use_triangles=True,
        apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_ALL',   # масштаб 1, одиниці = метри
        bake_space_transform=True,      # обертання об'єктів лишаються (0, 0, 0)
        axis_forward='-Z',
        axis_up='Y',                    # Y-up як у Roblox -> вісь петель = Y
        add_leaf_bones=False,
        use_custom_props=True,
        path_mode='AUTO',
    )
    print(f"\nFBX для Roblox Studio збережено: {path}")
    return path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    export, path = EXPORT_FBX, EXPORT_PATH
    if "--export" in argv:
        export = True
    if "--no-export" in argv:
        export = False
    if "--export-path" in argv:
        i = argv.index("--export-path")
        if i + 1 < len(argv):
            export, path = True, argv[i + 1]
    return export, path


def main():
    if bpy.app.version < (4, 2, 0):
        print("[WARN] Скрипт розрахований на Blender 5.x (мінімум 4.2).")
    export, export_path = parse_args()
    rng = random.Random(RANDOM_SEED)

    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0

    remove_default_startup_cube()
    build_materials()
    root = scene.collection
    c_hall = get_clean_collection(COLL_HALL, root)
    c_doors = get_clean_collection(COLL_DOORS, root)
    c_fx = get_clean_collection(COLL_FX, root)
    c_prev = get_clean_collection(COLL_PREVIEW, root)

    meshes = [
        build_floor(c_hall, rng),
        build_walls_and_columns(c_hall),
        build_ceiling(c_hall),
        build_arch_frame(c_doors),
    ]
    door_l, door_r = build_doors(c_doors)
    meshes += [door_l, door_r]
    for side, name in ((-1, "Brazier_Left"), (1, "Brazier_Right")):
        meshes += list(build_brazier(c_fx, name, side, rng))
    meshes.append(build_threshold_markers(c_fx))

    build_preview(c_prev, scene)

    enforce_tri_budget(meshes)
    ok = validate(meshes, door_l, door_r)
    if not ok:
        print("\n[ERROR] Валідація не пройдена — експорт пропущено.")
        return
    if export:
        export_fbx(meshes, export_path)
    print("\nГотово: передбанник Кімнати Боса 1-го поверху згенеровано.")


if __name__ == "__main__":
    main()
