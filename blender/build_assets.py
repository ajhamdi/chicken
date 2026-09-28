"""
Procedural Blender asset pipeline for the 3D "Hammer the Chickens" game.

Every model used by the game is authored here with Blender's Python API and
exported as a binary glTF (.glb) into ../assets/models/. The script then packs
all .glb files into ../assets/models.js (base64) so the game can load them
without a web server (it still works when index.html is opened from disk).

Run it with any of:
    blender -b -P blender/build_assets.py          # Blender installed
    python3 blender/build_assets.py                # `pip install bpy`
    or paste it into a Blender MCP "execute code" call (set OUT_DIR first).

Conventions
    * Blender is Z-up; glTF is Y-up. Models face Blender -Y which becomes +Z
      in three.js, so `object.lookAt()` style yaw works directly.
    * Parts that the game animates are separate objects with a pivot placed
      at the joint (WingL, WingR, LegL, LegR, ClawL, ClawR, Head, Tail, Gun...).
      Empties named "Muzzle" mark where projectiles leave a weapon.
    * Everything is low poly with flat shaded faces and plain PBR colors.
"""

import base64
import math
import os
import sys

import bpy  # must be imported before bmesh/mathutils when running as a pip module
import bmesh
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
OUT_DIR = os.environ.get("CHICKEN_ASSET_DIR") or os.path.join(HERE, "..", "assets", "models")
BUNDLE = os.path.join(OUT_DIR, "..", "models.js")


# --------------------------------------------------------------------------- #
# Scene / material helpers
# --------------------------------------------------------------------------- #

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


_materials = {}


def mat(name, color, rough=0.7, metal=0.0, emit=None, emit_strength=1.0, alpha=1.0):
    """Principled material, cached by name for the current asset."""
    key = name
    if key in _materials and _materials[key].name in bpy.data.materials:
        return _materials[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    rgba = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emit is not None:
        bsdf.inputs["Emission Color"].default_value = (emit[0], emit[1], emit[2], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            m.surface_render_method = "BLENDED"
        except AttributeError:
            m.blend_method = "BLEND"
    _materials[key] = m
    return m


def hexcol(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # Blender stores linear colors; convert from sRGB so hex values match the web.
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


def trs(loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    if not isinstance(scale, (tuple, list)):
        scale = (scale, scale, scale)
    return (Matrix.Translation(Vector(loc))
            @ Euler(rot, "XYZ").to_matrix().to_4x4()
            @ Matrix.Diagonal(Vector((*scale, 1.0))))


class Part:
    """Accumulates primitives into one bmesh, each with its own material."""

    def __init__(self, name, pivot=(0, 0, 0), smooth=False):
        self.name = name
        self.pivot = Vector(pivot)
        self.bm = bmesh.new()
        self.mats = []
        self.smooth = smooth

    def _mi(self, material):
        if material not in self.mats:
            self.mats.append(material)
        return self.mats.index(material)

    def _finish(self, verts, material, smooth=None):
        idx = self._mi(material)
        vset = set(verts)
        faces = {f for v in verts for f in v.link_faces if all(x in vset for x in f.verts)}
        for f in faces:
            f.material_index = idx
            f.smooth = self.smooth if smooth is None else smooth
        return self

    def sphere(self, material, loc=(0, 0, 0), scale=1.0, rot=(0, 0, 0), seg=10, rings=7, smooth=None):
        r = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=rings, radius=1.0,
                                      matrix=trs(loc, rot, scale))
        return self._finish(r["verts"], material, smooth)

    def ico(self, material, loc=(0, 0, 0), scale=1.0, rot=(0, 0, 0), sub=1, smooth=None):
        r = bmesh.ops.create_icosphere(self.bm, subdivisions=sub, radius=1.0, matrix=trs(loc, rot, scale))
        return self._finish(r["verts"], material, smooth)

    def cube(self, material, loc=(0, 0, 0), scale=1.0, rot=(0, 0, 0), smooth=None):
        r = bmesh.ops.create_cube(self.bm, size=1.0, matrix=trs(loc, rot, scale))
        return self._finish(r["verts"], material, smooth)

    def cone(self, material, loc=(0, 0, 0), r1=0.5, r2=0.0, depth=1.0, rot=(0, 0, 0), seg=8,
             scale=1.0, smooth=None):
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=seg,
                                  radius1=r1, radius2=r2, depth=depth, matrix=trs(loc, rot, scale))
        return self._finish(r["verts"], material, smooth)

    def cyl(self, material, loc=(0, 0, 0), r=0.5, depth=1.0, rot=(0, 0, 0), seg=10, scale=1.0, smooth=None):
        return self.cone(material, loc, r, r, depth, rot, seg, scale, smooth)

    def cyl_between(self, material, a, b, r=0.05, seg=6, r2=None):
        """Cylinder (or tapered cone) from point a to point b."""
        a, b = Vector(a), Vector(b)
        d = b - a
        rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_euler()
        mid = (a + b) / 2
        return self.cone(material, mid, r, r if r2 is None else r2, d.length, tuple(rot), seg)

    def poly(self, material, points, thickness=0.04, smooth=None):
        """Extruded flat polygon (wing membranes, fins, flames)."""
        verts = [self.bm.verts.new(Vector(p)) for p in points]
        face = self.bm.faces.new(verts)
        face.normal_update()
        n = face.normal.copy()
        ext = bmesh.ops.extrude_face_region(self.bm, geom=[face])
        new_verts = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
        bmesh.ops.translate(self.bm, verts=new_verts, vec=n * thickness)
        bmesh.ops.translate(self.bm, verts=verts + new_verts, vec=-n * thickness / 2)
        bmesh.ops.recalc_face_normals(self.bm, faces=list({f for v in verts + new_verts for f in v.link_faces}))
        return self._finish(verts + new_verts, material, smooth)

    def build(self, parent=None):
        me = bpy.data.meshes.new(self.name)
        bmesh.ops.translate(self.bm, verts=self.bm.verts, vec=-self.pivot)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = self.pivot
        if parent is not None:
            ob.parent = parent
        return ob


def empty(name, loc=(0, 0, 0), parent=None):
    ob = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    if parent is not None:
        ob.parent = parent
    return ob


def text_mesh(body, material, size=1.0, depth=0.05, loc=(0, 0, 0), rot=(0, 0, 0), name="Text"):
    """Convert a Blender text object into a mesh object."""
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.size = size
    curve.extrude = depth
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    tmp = bpy.data.objects.new(name + "_tmp", curve)
    bpy.context.scene.collection.objects.link(tmp)
    deps = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(deps))
    bpy.data.objects.remove(tmp)
    me.materials.clear()
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def export(name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_texcoords=False,
        export_normals=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
    )
    print(f"  exported {name}.glb ({os.path.getsize(path) / 1024:.1f} KB)")


# --------------------------------------------------------------------------- #
# Creatures
# --------------------------------------------------------------------------- #

def build_chicken():
    white = mat("Feather", hexcol("#f7f3ea"), 0.9)
    cream = mat("FeatherShade", hexcol("#e6dcc6"), 0.9)
    red = mat("Comb", hexcol("#e0282e"), 0.6)
    orange = mat("Beak", hexcol("#f5a31a"), 0.5)
    black = mat("Eye", hexcol("#111111"), 0.2)
    shine = mat("EyeShine", hexcol("#ffffff"), 0.1)

    root = empty("Chicken")

    body = Part("Body")
    body.sphere(white, (0, 0.05, 0.62), (0.42, 0.5, 0.4), seg=12, rings=8)
    body.sphere(cream, (0, -0.02, 0.5), (0.34, 0.38, 0.28), seg=10, rings=6)     # belly
    # tail feathers
    for i, a in enumerate((-0.35, 0, 0.35)):
        body.cone(white, (a * 0.35, 0.5, 0.92), 0.12, 0.02, 0.45, (-0.7, a, 0), seg=5)
    body.build(root)

    head = Part("Head", pivot=(0, -0.3, 0.9))
    head.sphere(white, (0, -0.38, 1.1), 0.24, seg=10, rings=7)
    head.cone(orange, (0, -0.64, 1.08), 0.08, 0.0, 0.2, (math.pi / 2, 0, 0), seg=6)   # beak
    head.sphere(red, (0, -0.56, 0.95), (0.05, 0.05, 0.1), seg=6, rings=4)            # wattle
    for i, (y, z, s) in enumerate(((-0.46, 1.34, 0.08), (-0.36, 1.37, 0.09), (-0.26, 1.33, 0.075))):
        head.sphere(red, (0, y, z), (0.045, s, s), seg=6, rings=4)                      # comb
    for sx in (-1, 1):
        head.sphere(black, (sx * 0.17, -0.5, 1.16), 0.045, seg=6, rings=4)
        head.sphere(shine, (sx * 0.19, -0.53, 1.18), 0.015, seg=4, rings=3)
    head.build(root)

    for side, sx in (("L", 1), ("R", -1)):
        w = Part("Wing" + side, pivot=(sx * 0.36, -0.05, 0.78))
        w.sphere(cream, (sx * 0.42, 0.08, 0.64), (0.08, 0.3, 0.2), (0.25, 0, 0), seg=8, rings=5)
        w.build(root)
        leg = Part("Leg" + side, pivot=(sx * 0.14, 0, 0.3))
        leg.cyl_between(orange, (sx * 0.14, 0, 0.3), (sx * 0.14, 0, 0.04), 0.035)
        for toe in (-0.5, 0, 0.5):
            leg.cyl_between(orange, (sx * 0.14, 0, 0.03),
                            (sx * 0.14 + math.sin(toe) * 0.13, -math.cos(toe) * 0.13, 0.02), 0.022)
        leg.build(root)


def build_crab():
    shell = mat("Shell", hexcol("#e2462c"), 0.45)
    shell2 = mat("ShellDark", hexcol("#b3301e"), 0.5)
    belly = mat("Belly", hexcol("#f6c08a"), 0.6)
    black = mat("Eye", hexcol("#111111"), 0.2)
    white = mat("EyeWhite", hexcol("#ffffff"), 0.2)

    root = empty("Crab")
    body = Part("Body")
    body.sphere(shell, (0, 0, 0.42), (0.62, 0.45, 0.22), seg=14, rings=8)
    body.sphere(belly, (0, 0, 0.34), (0.55, 0.4, 0.14), seg=12, rings=6)
    for sx in (-1, 1):
        body.sphere(shell2, (sx * 0.3, 0.1, 0.56), 0.08, seg=6, rings=4)
        body.cyl_between(shell, (sx * 0.14, -0.32, 0.5), (sx * 0.18, -0.4, 0.82), 0.035)
        body.sphere(white, (sx * 0.18, -0.4, 0.86), 0.08, seg=8, rings=6)
        body.sphere(black, (sx * 0.19, -0.47, 0.88), 0.04, seg=6, rings=4)
    body.build(root)

    for side, sx in (("L", 1), ("R", -1)):
        claw = Part("Claw" + side, pivot=(sx * 0.5, -0.25, 0.42))
        claw.cyl_between(shell, (sx * 0.5, -0.25, 0.42), (sx * 0.72, -0.55, 0.5), 0.07)
        claw.sphere(shell, (sx * 0.78, -0.68, 0.52), (0.18, 0.22, 0.14), seg=10, rings=6)
        claw.cone(shell2, (sx * 0.72, -0.92, 0.58), 0.07, 0.01, 0.26, (math.pi / 2 + 0.2, 0, 0), seg=6)
        claw.cone(shell2, (sx * 0.86, -0.9, 0.46), 0.06, 0.01, 0.22, (math.pi / 2 - 0.2, 0, 0), seg=6)
        claw.build(root)
        legs = Part("Legs" + side, pivot=(sx * 0.45, 0.05, 0.36))
        for i, y in enumerate((-0.12, 0.08, 0.26)):
            knee = (sx * 0.9, y + 0.05, 0.42)
            legs.cyl_between(shell, (sx * 0.45, y, 0.36), knee, 0.04)
            legs.cyl_between(shell2, knee, (sx * 1.02, y + 0.1, 0.0), 0.035, r2=0.01)
        legs.build(root)


def build_hornet():
    yellow = mat("Yellow", hexcol("#f7c21c"), 0.45)
    black = mat("Black", hexcol("#1c1a17"), 0.35)
    eye = mat("Eye", hexcol("#3a1010"), 0.15, emit=hexcol("#ff2a00"), emit_strength=0.6)
    wing = mat("Wing", hexcol("#d8f0ff"), 0.1, alpha=0.45)
    sting = mat("Stinger", hexcol("#2a2a2a"), 0.3, metal=0.4)

    root = empty("Hornet")
    body = Part("Body")
    body.sphere(black, (0, -0.05, 0.0), (0.22, 0.26, 0.22), seg=10, rings=7)          # thorax
    body.sphere(yellow, (0, -0.4, 0.05), 0.2, seg=10, rings=7)                           # head
    for sx in (-1, 1):
        body.sphere(eye, (sx * 0.12, -0.5, 0.1), (0.09, 0.08, 0.12), seg=8, rings=6)
        body.cyl_between(black, (sx * 0.06, -0.5, 0.22), (sx * 0.2, -0.75, 0.45), 0.018)
    body.cone(black, (0, -0.58, -0.08), 0.05, 0.0, 0.12, (math.pi / 2 + 0.6, 0, 0), seg=5)  # mandibles
    body.build(root)

    abdomen = Part("Tail", pivot=(0, 0.15, 0.0))
    stripes = [(0.3, 0.21, yellow), (0.43, 0.23, black), (0.56, 0.22, yellow), (0.68, 0.19, black),
               (0.79, 0.15, yellow), (0.88, 0.1, black)]
    for y, r, m in stripes:
        abdomen.sphere(m, (0, y, -0.08 - (y - 0.3) * 0.25), (r, 0.1, r), seg=10, rings=6)
    abdomen.cone(sting, (0, 1.0, -0.25), 0.04, 0.0, 0.2, (-math.pi / 2 - 0.4, 0, 0), seg=5)
    abdomen.build(root)

    for side, sx in (("L", 1), ("R", -1)):
        w = Part("Wing" + side, pivot=(sx * 0.12, -0.05, 0.18))
        w.poly(wing, [(sx * 0.12, -0.15, 0.2), (sx * 0.55, -0.1, 0.32), (sx * 0.85, 0.15, 0.34),
                      (sx * 0.7, 0.3, 0.28), (sx * 0.3, 0.18, 0.22), (sx * 0.12, 0.05, 0.19)], 0.015)
        w.poly(wing, [(sx * 0.12, 0.0, 0.18), (sx * 0.45, 0.25, 0.22), (sx * 0.55, 0.42, 0.2),
                      (sx * 0.25, 0.3, 0.18)], 0.015)
        w.build(root)
        legs = Part("Legs" + side, pivot=(sx * 0.1, -0.05, -0.1))
        for y in (-0.15, 0.0, 0.15):
            legs.cyl_between(black, (sx * 0.1, y, -0.1), (sx * 0.3, y + 0.05, -0.3), 0.02)
            legs.cyl_between(yellow, (sx * 0.3, y + 0.05, -0.3), (sx * 0.34, y + 0.12, -0.5), 0.015)
        legs.build(root)


def build_dragon():
    scale = mat("Scales", hexcol("#6b2fa3"), 0.5, metal=0.1)
    scale2 = mat("ScalesDark", hexcol("#43196e"), 0.55)
    belly = mat("Belly", hexcol("#f0b04a"), 0.6)
    horn = mat("Horn", hexcol("#f3ead2"), 0.4)
    eye = mat("Eye", hexcol("#ffcc00"), 0.2, emit=hexcol("#ffae00"), emit_strength=3.0)
    membrane = mat("Membrane", hexcol("#b0406a"), 0.6)
    fire = mat("Fire", hexcol("#ff5a00"), 0.4, emit=hexcol("#ff6a00"), emit_strength=2.0)

    root = empty("Dragon")
    body = Part("Body")
    body.sphere(scale, (0, 0.1, 0.0), (0.55, 0.85, 0.5), seg=14, rings=9)
    body.sphere(belly, (0, 0.0, -0.18), (0.42, 0.72, 0.34), seg=12, rings=7)
    # spikes along the back
    for i in range(6):
        y = -0.5 + i * 0.25
        body.cone(scale2, (0, y, 0.48 - abs(y) * 0.12), 0.08, 0.0, 0.3, (0.3, 0, 0), seg=4)
    # legs
    for sx in (-1, 1):
        for y in (-0.35, 0.5):
            body.cyl_between(scale, (sx * 0.35, y, -0.2), (sx * 0.45, y - 0.05, -0.65), 0.1)
            body.sphere(scale2, (sx * 0.46, y - 0.12, -0.7), (0.12, 0.18, 0.07), seg=6, rings=4)
            for t in (-0.06, 0, 0.06):
                body.cone(horn, (sx * 0.46 + t, y - 0.3, -0.7), 0.025, 0.0, 0.1, (math.pi / 2, 0, 0), seg=4)
    body.build(root)

    head = Part("Head", pivot=(0, -0.7, 0.3))
    head.cyl_between(scale, (0, -0.6, 0.2), (0, -1.0, 0.75), 0.22, seg=10, r2=0.17)       # neck
    head.sphere(scale, (0, -1.15, 0.85), (0.3, 0.36, 0.26), seg=12, rings=8)
    head.sphere(scale, (0, -1.5, 0.78), (0.2, 0.3, 0.16), seg=10, rings=6)                 # snout
    head.sphere(belly, (0, -1.48, 0.68), (0.17, 0.28, 0.08), seg=10, rings=6)              # jaw
    for sx in (-1, 1):
        head.sphere(eye, (sx * 0.19, -1.3, 0.96), (0.07, 0.06, 0.05), seg=8, rings=5)
        head.cone(horn, (sx * 0.16, -0.95, 1.2), 0.07, 0.0, 0.45, (-0.7, sx * 0.3, 0), seg=6)
        head.sphere(scale2, (sx * 0.08, -1.76, 0.86), 0.035, seg=5, rings=3)                # nostrils
    head.poly(fire, [(0, -1.78, 0.7), (0.12, -2.0, 0.7), (0.04, -2.3, 0.72), (0, -2.1, 0.7),
                     (-0.04, -2.3, 0.72), (-0.12, -2.0, 0.7)], 0.04)
    head.build(root)

    tail = Part("Tail", pivot=(0, 0.8, 0.0))
    pts = [(0, 0.8, 0.0), (0, 1.3, -0.08), (0.05, 1.8, 0.02), (0.12, 2.2, 0.18)]
    radii = [0.28, 0.2, 0.12, 0.06]
    for i in range(len(pts) - 1):
        tail.cyl_between(scale, pts[i], pts[i + 1], radii[i], seg=8, r2=radii[i + 1])
    tail.poly(scale2, [(0.12, 2.15, 0.18), (0.32, 2.45, 0.2), (0.12, 2.7, 0.22), (-0.08, 2.45, 0.2)], 0.04)
    tail.build(root)

    for side, sx in (("L", 1), ("R", -1)):
        w = Part("Wing" + side, pivot=(sx * 0.4, -0.2, 0.35))
        w.cyl_between(scale2, (sx * 0.4, -0.2, 0.35), (sx * 1.2, -0.4, 0.9), 0.06)
        w.cyl_between(scale2, (sx * 1.2, -0.4, 0.9), (sx * 2.2, 0.0, 0.8), 0.045, r2=0.02)
        w.cone(horn, (sx * 1.2, -0.48, 0.96), 0.04, 0.0, 0.18, (math.pi / 2, 0, 0), seg=4)
        w.poly(membrane, [(sx * 0.42, -0.18, 0.35), (sx * 1.2, -0.4, 0.9), (sx * 2.2, 0.0, 0.8),
                          (sx * 1.8, 0.45, 0.55), (sx * 1.3, 0.3, 0.5), (sx * 0.95, 0.65, 0.35),
                          (sx * 0.5, 0.35, 0.3)], 0.03)
        w.build(root)


def build_crown():
    gold = mat("Gold", hexcol("#ffd23f"), 0.25, metal=1.0, emit=hexcol("#7a5200"), emit_strength=0.6)
    gem = mat("Gem", hexcol("#e3173e"), 0.1, emit=hexcol("#ff1744"), emit_strength=1.2)
    p = Part("Crown")
    p.cyl(gold, (0, 0, 0.06), 0.2, 0.12, seg=12)
    for i in range(5):
        a = i / 5 * math.tau
        p.cone(gold, (math.cos(a) * 0.17, math.sin(a) * 0.17, 0.2), 0.06, 0.0, 0.18, seg=4)
        p.ico(gem, (math.cos(a) * 0.2, math.sin(a) * 0.2, 0.06), 0.035, sub=1)
    p.build()


# --------------------------------------------------------------------------- #
# Weapons
# --------------------------------------------------------------------------- #

def build_hammer():
    wood = mat("Wood", hexcol("#9a6533"), 0.8)
    grip = mat("Grip", hexcol("#2e2e2e"), 0.9)
    steel = mat("Steel", hexcol("#b9c2cc"), 0.3, metal=0.9)
    band = mat("Band", hexcol("#d33b2c"), 0.5)
    root = empty("Hammer")
    # Pivot (origin) at the grip end, handle along +X, striking face points down (-Z).
    h = Part("HammerMesh")
    h.cyl_between(grip, (0, 0, 0), (0.45, 0, 0), 0.07, seg=8)
    h.cyl_between(wood, (0.45, 0, 0), (1.62, 0, 0), 0.055, seg=8)
    h.cyl(steel, (1.7, 0, 0), 0.26, 0.72, seg=12)
    h.cyl(band, (1.7, 0, 0.16), 0.268, 0.1, seg=12)
    h.cyl(band, (1.7, 0, -0.16), 0.268, 0.1, seg=12)
    h.cyl(steel, (1.7, 0, -0.39), 0.22, 0.06, seg=12)
    h.cyl(steel, (1.7, 0, 0.39), 0.22, 0.06, seg=12)
    h.build(root)


def turret_base(root, accent):
    metal_dark = mat("Gunmetal", hexcol("#3b4148"), 0.45, metal=0.8)
    sandbag = mat("Sandbag", hexcol("#b89b6a"), 0.95)
    base = Part("Base")
    for i in range(8):
        a = i / 8 * math.tau
        base.sphere(sandbag, (math.cos(a) * 0.95, math.sin(a) * 0.95, 0.18), (0.42, 0.28, 0.2),
                    (0, 0, a + math.pi / 2), seg=8, rings=5)
    base.cyl(metal_dark, (0, 0, 0.35), 0.35, 0.7, seg=10)
    base.cyl(accent, (0, 0, 0.72), 0.42, 0.08, seg=12)
    base.build(root)


def build_machinegun():
    gun = mat("Gunmetal", hexcol("#3b4148"), 0.45, metal=0.8)
    black = mat("Black", hexcol("#1b1d20"), 0.6)
    olive = mat("Olive", hexcol("#5c6b3a"), 0.7)
    brass = mat("Brass", hexcol("#d6a73a"), 0.3, metal=1.0)
    root = empty("MachineGun")
    turret_base(root, olive)
    g = Part("Gun", pivot=(0, 0, 0.95))
    g.cube(olive, (0, 0.1, 0.95), (0.36, 0.7, 0.3))
    g.cube(gun, (0, 0.55, 0.95), (0.18, 0.4, 0.22))                                       # stock
    g.cyl_between(black, (0, -0.25, 0.95), (0, -1.3, 0.95), 0.1, seg=10)                 # shroud
    for a in range(6):
        ang = a / 6 * math.tau
        g.cyl_between(gun, (math.cos(ang) * 0.05, -1.2, 0.95 + math.sin(ang) * 0.05),
                      (math.cos(ang) * 0.05, -1.65, 0.95 + math.sin(ang) * 0.05), 0.022, seg=5)
    g.cube(brass, (0.26, 0.05, 0.9), (0.18, 0.3, 0.16))                                   # ammo box
    g.cube(black, (0, 0.05, 1.14), (0.05, 0.15, 0.08))
    g.cyl_between(gun, (-0.25, 0.3, 0.95), (-0.25, 0.5, 0.7), 0.04)                       # handles
    g.cyl_between(gun, (0.25, 0.3, 0.95), (0.25, 0.5, 0.7), 0.04)
    gob = g.build(root)
    empty("Muzzle", (0, -1.7, 0.0), gob)


def build_rocket_launcher():
    tube = mat("Tube", hexcol("#4d5a32"), 0.6)
    ring = mat("Ring", hexcol("#e8762c"), 0.5)
    gun = mat("Gunmetal", hexcol("#3b4148"), 0.45, metal=0.8)
    lens = mat("Lens", hexcol("#1e90ff"), 0.05, emit=hexcol("#3aa0ff"), emit_strength=1.5)
    root = empty("RocketLauncher")
    turret_base(root, ring)
    g = Part("Gun", pivot=(0, 0, 0.95))
    for sx in (-1, 1):
        g.cyl_between(tube, (sx * 0.24, 0.8, 1.0), (sx * 0.24, -1.1, 1.0), 0.2, seg=12)
        g.cyl_between(ring, (sx * 0.24, -1.05, 1.0), (sx * 0.24, -1.18, 1.0), 0.23, seg=12)
        g.cyl_between(ring, (sx * 0.24, 0.72, 1.0), (sx * 0.24, 0.85, 1.0), 0.23, seg=12)
    g.cube(gun, (0, 0, 0.88), (0.5, 0.5, 0.2))
    g.cube(gun, (0.55, -0.3, 1.2), (0.12, 0.3, 0.14))                                     # sight
    g.cyl_between(lens, (0.55, -0.46, 1.2), (0.55, -0.5, 1.2), 0.05)
    gob = g.build(root)
    empty("Muzzle", (0.0, -1.25, 0.05), gob)


def build_rocket():
    body = mat("RocketBody", hexcol("#e9e4da"), 0.4)
    red = mat("RocketRed", hexcol("#d8322b"), 0.4)
    fin = mat("Fin", hexcol("#ff8a1c"), 0.5)
    flame = mat("Flame", hexcol("#ffcc33"), 0.3, emit=hexcol("#ff9900"), emit_strength=4.0)
    p = Part("Rocket")
    # rocket points toward -Y (three.js +Z)
    p.cyl_between(body, (0, 0.35, 0), (0, -0.25, 0), 0.1, seg=10)
    p.cyl_between(red, (0, -0.25, 0), (0, -0.55, 0), 0.1, seg=10, r2=0.0)
    p.cyl_between(red, (0, 0.1, 0), (0, 0.0, 0), 0.105, seg=10)
    for i in range(4):
        a = i / 4 * math.tau
        c, s = math.cos(a), math.sin(a)
        p.poly(fin, [(c * 0.08, 0.2, s * 0.08), (c * 0.25, 0.42, s * 0.25), (c * 0.08, 0.38, s * 0.08)], 0.02)
    p.cyl_between(flame, (0, 0.36, 0), (0, 0.7, 0), 0.08, seg=8, r2=0.0)
    p.build()


def build_laser():
    white = mat("Hull", hexcol("#e8eef5"), 0.25, metal=0.3)
    dark = mat("Gunmetal", hexcol("#2a2f38"), 0.35, metal=0.8)
    glow = mat("Glow", hexcol("#00ffff"), 0.1, emit=hexcol("#00f0ff"), emit_strength=4.0)
    root = empty("LaserCannon")
    turret_base(root, glow)
    g = Part("Gun", pivot=(0, 0, 0.95))
    g.sphere(white, (0, 0.1, 0.98), (0.42, 0.55, 0.36), seg=14, rings=8)
    g.cyl_between(dark, (0, -0.3, 0.98), (0, -1.45, 0.98), 0.11, seg=12)
    for i, y in enumerate((-0.55, -0.85, -1.15)):
        g.cyl_between(glow, (0, y, 0.98), (0, y - 0.08, 0.98), 0.16 - i * 0.02, seg=12)
    g.cyl_between(white, (0, -1.4, 0.98), (0, -1.55, 0.98), 0.14, seg=12)
    g.sphere(glow, (0, -1.56, 0.98), 0.07, seg=8, rings=5)
    for sx in (-1, 1):
        g.poly(white, [(sx * 0.35, 0.3, 0.98), (sx * 0.75, 0.6, 1.02), (sx * 0.7, 0.2, 1.0),
                       (sx * 0.38, -0.1, 0.98)], 0.05)
        g.cyl_between(glow, (sx * 0.72, 0.62, 1.02), (sx * 0.72, 0.18, 1.0), 0.03)
    gob = g.build(root)
    empty("Muzzle", (0, -1.6, 0.03), gob)


# --------------------------------------------------------------------------- #
# Power-ups
# --------------------------------------------------------------------------- #

def build_powerup_freeze():
    ice = mat("Ice", hexcol("#9fe8ff"), 0.05, emit=hexcol("#2fb8ff"), emit_strength=1.2, alpha=0.9)
    core = mat("IceCore", hexcol("#ffffff"), 0.05, emit=hexcol("#bff3ff"), emit_strength=2.0)
    p = Part("Freeze")
    p.ico(core, (0, 0, 0), 0.16, sub=1)
    for i in range(6):
        a = i / 6 * math.tau
        d = Vector((math.cos(a), 0, math.sin(a)))
        p.cyl_between(ice, (0, 0, 0), tuple(d * 0.55), 0.045, seg=6)
        p.cone(ice, tuple(d * 0.6), 0.07, 0.0, 0.15, tuple(Vector((0, 0, 1)).rotation_difference(d).to_euler()), seg=6)
        for t in (0.3, 0.45):
            base = d * t
            for s in (-1, 1):
                b = Vector((math.cos(a + s * 0.9), 0, math.sin(a + s * 0.9)))
                p.cyl_between(ice, tuple(base), tuple(base + b * 0.15), 0.03, seg=5)
    p.build()


def build_powerup_bomb():
    black = mat("BombShell", hexcol("#22242a"), 0.35, metal=0.5)
    cap = mat("Cap", hexcol("#8d939c"), 0.3, metal=0.9)
    fuse = mat("Fuse", hexcol("#c7a26a"), 0.9)
    spark = mat("Spark", hexcol("#ffe066"), 0.2, emit=hexcol("#ffae00"), emit_strength=5.0)
    shine = mat("Shine", hexcol("#ffffff"), 0.1)
    p = Part("Bomb", smooth=True)
    p.sphere(black, (0, 0, 0), 0.42, seg=16, rings=10)
    p.sphere(shine, (-0.2, -0.28, 0.2), 0.07, seg=6, rings=4)
    p.cyl(cap, (0, 0, 0.44), 0.14, 0.14, seg=10)
    p.cyl_between(fuse, (0, 0, 0.5), (0.1, 0, 0.66), 0.03, seg=6)
    p.cyl_between(fuse, (0.1, 0, 0.66), (0.22, 0, 0.72), 0.03, seg=6)
    p.ico(spark, (0.25, 0, 0.74), 0.09, sub=1, smooth=False)
    p.build()


def build_powerup_double():
    gold = mat("Gold", hexcol("#ffcf33"), 0.25, metal=1.0, emit=hexcol("#6b4a00"), emit_strength=0.5)
    rim = mat("Rim", hexcol("#e0a100"), 0.3, metal=1.0)
    ink = mat("Ink", hexcol("#b3261e"), 0.4, emit=hexcol("#ff3b30"), emit_strength=0.6)
    root = empty("Double")
    p = Part("Coin")
    # coin stands upright facing -Y (the camera side in three.js is +Z)
    p.cyl(gold, (0, 0, 0), 0.5, 0.12, (math.pi / 2, 0, 0), seg=24)
    p.cyl(rim, (0, 0, 0), 0.54, 0.09, (math.pi / 2, 0, 0), seg=24)
    p.build(root)
    for sy in (-1, 1):
        t = text_mesh("x2", ink, size=0.55, depth=0.03, loc=(0, sy * 0.07, -0.02),
                      rot=(math.pi / 2, 0, 0 if sy < 0 else math.pi), name="Label" + ("F" if sy < 0 else "B"))
        t.parent = root


# --------------------------------------------------------------------------- #
# Farm environment
# --------------------------------------------------------------------------- #

ARENA_X = 12.0   # must match CONFIG.arenaHalfWidth in index.html
ARENA_Z = 7.0    # must match CONFIG.arenaHalfDepth in index.html


def build_farm():
    red = mat("BarnRed", hexcol("#b4302a"), 0.85)
    trim = mat("Trim", hexcol("#f4efe4"), 0.8)
    roof = mat("Roof", hexcol("#5b5f66"), 0.7)
    wood = mat("FenceWood", hexcol("#a8743e"), 0.9)
    wood_dark = mat("WoodDark", hexcol("#6e4a26"), 0.9)
    leaf = mat("Leaves", hexcol("#3f9a3a"), 0.9)
    leaf2 = mat("Leaves2", hexcol("#5cb84a"), 0.9)
    bark = mat("Bark", hexcol("#6b4424"), 0.9)
    hay = mat("Hay", hexcol("#e5c05c"), 0.95)
    hay_dark = mat("HayDark", hexcol("#c79c3a"), 0.95)
    rock = mat("Rock", hexcol("#9aa0a6"), 0.9)
    hill = mat("Hill", hexcol("#6cbf4f"), 1.0)
    hill2 = mat("Hill2", hexcol("#58a844"), 1.0)
    blade = mat("Blade", hexcol("#efe9dc"), 0.6)
    water = mat("Trough", hexcol("#5aa7d6"), 0.1, metal=0.2)
    flower_cols = [mat("FlowerR", hexcol("#ff5a6a"), 0.6), mat("FlowerY", hexcol("#ffd84a"), 0.6),
                   mat("FlowerW", hexcol("#ffffff"), 0.6), mat("FlowerP", hexcol("#c07cff"), 0.6)]
    stem = mat("Stem", hexcol("#2f7a2a"), 0.9)

    # ---- barn (back left) ------------------------------------------------ #
    barn = Part("Barn")
    bx, by = -8.5, 12.5          # Blender Y = -three.js Z (back of the arena is +Y)
    barn.cube(red, (bx, by, 2.2), (6.0, 5.0, 4.4))
    barn.poly(red, [(bx - 3, by - 2.5, 4.4), (bx + 3, by - 2.5, 4.4), (bx + 3, by - 2.5, 5.2),
                    (bx, by - 2.5, 7.0), (bx - 3, by - 2.5, 5.2)], 0.2)
    barn.poly(red, [(bx - 3, by + 2.5, 4.4), (bx + 3, by + 2.5, 4.4), (bx + 3, by + 2.5, 5.2),
                    (bx, by + 2.5, 7.0), (bx - 3, by + 2.5, 5.2)], 0.2)
    for sx in (-1, 1):
        # gambrel roof: lower steep panel + upper shallow panel
        barn.cube(roof, (bx + sx * 2.75, by, 4.85), (0.25, 5.6, 1.35), (0, sx * -0.35, 0))
        barn.cube(roof, (bx + sx * 1.45, by, 6.2), (0.25, 5.6, 3.2), (0, sx * -1.02, 0))
    barn.cube(trim, (bx, by - 2.56, 1.6), (2.6, 0.1, 3.2))
    barn.cube(red, (bx, by - 2.6, 1.6), (2.2, 0.1, 2.8))
    for s in (-1, 1):
        barn.cube(trim, (bx, by - 2.64, 1.6), (0.14, 0.06, 3.6), (0, s * 0.66, 0))
    barn.cube(trim, (bx, by - 2.58, 5.0), (1.0, 0.1, 1.0))
    barn.cube(wood_dark, (bx, by - 2.62, 5.0), (0.75, 0.08, 0.75))
    for sx in (-1, 1):
        barn.cube(trim, (bx + sx * 3.02, by, 2.2), (0.1, 5.1, 4.4 * 0.05))
    barn.build()

    # ---- silo ------------------------------------------------------------ #
    silo = Part("Silo")
    silo.cyl(trim, (-3.8, 14.0, 3.5), 1.4, 7.0, seg=16)
    for z in (1.2, 3.0, 4.8, 6.6):
        silo.cyl(roof, (-3.8, 14.0, z), 1.43, 0.12, seg=16)
    silo.sphere(red, (-3.8, 14.0, 7.0), (1.45, 1.45, 1.1), seg=16, rings=8)
    silo.build()

    # ---- windmill (back right) ------------------------------------------- #
    mill = Part("Windmill")
    mx, my = 9.5, 13.5
    for sx in (-1, 1):
        for sy in (-1, 1):
            mill.cyl_between(wood_dark, (mx + sx * 1.2, my + sy * 1.2, 0), (mx + sx * 0.3, my + sy * 0.3, 8.0), 0.09)
    for z in (2.0, 4.0, 6.0):
        k = 1.2 - (z / 8.0) * 0.9
        for sx in (-1, 1):
            mill.cyl_between(wood, (mx + sx * k, my - k, z), (mx + sx * k, my + k, z), 0.05)
            mill.cyl_between(wood, (mx - k, my + sx * k, z), (mx + k, my + sx * k, z), 0.05)
    mill.cube(trim, (mx, my, 8.2), (0.9, 1.2, 0.7))
    mill.cone(red, (mx + 0.9, my, 8.2), 0.25, 0.0, 0.5, (0, math.pi / 2, 0), seg=6)   # tail vane hub
    mill.poly(red, [(mx + 1.1, my, 7.7), (mx + 2.4, my, 7.6), (mx + 2.4, my, 8.9), (mx + 1.1, my, 8.6)], 0.05)
    mill.build()

    rotor = Part("WindmillRotor", pivot=(mx - 0.6, my, 8.2))
    rotor.cyl_between(wood_dark, (mx - 0.45, my, 8.2), (mx - 0.75, my, 8.2), 0.18, seg=8)
    for i in range(12):
        a = i / 12 * math.tau
        tip = (mx - 0.72, my + math.cos(a) * 2.2, 8.2 + math.sin(a) * 2.2)
        rotor.poly(blade, [(mx - 0.72, my + math.cos(a) * 0.25, 8.2 + math.sin(a) * 0.25),
                           (mx - 0.72, my + math.cos(a - 0.12) * 2.2, 8.2 + math.sin(a - 0.12) * 2.2),
                           tip,
                           (mx - 0.72, my + math.cos(a + 0.1) * 2.1, 8.2 + math.sin(a + 0.1) * 2.1)], 0.03)
    rotor.build()

    # ---- fence around sides and back of the arena ------------------------ #
    fence = Part("Fence")
    fx, fy = ARENA_X + 1.0, ARENA_Z + 1.0

    def fence_line(a, b, posts):
        a, b = Vector(a), Vector(b)
        for i in range(posts + 1):
            p = a.lerp(b, i / posts)
            fence.cube(wood_dark, (p.x, p.y, 0.55), (0.18, 0.18, 1.1))
            fence.cone(wood_dark, (p.x, p.y, 1.16), 0.13, 0.0, 0.14, (0, 0, math.pi / 4), seg=4)
        for z in (0.4, 0.85):
            fence.cyl_between(wood, (a.x, a.y, z), (b.x, b.y, z), 0.05, seg=4)

    fence_line((-fx, fy), (fx, fy), 13)              # back (three.js -Z)
    fence_line((-fx, fy), (-fx, -fy), 8)             # left
    fence_line((fx, fy), (fx, -fy), 8)               # right
    fence.build()

    # ---- trees ------------------------------------------------------------ #
    trees = Part("Trees")
    import random
    rng = random.Random(7)
    spots = [(-17, 6), (-18, -1), (-16.5, -8), (-20, 12), (17, 5), (18.5, -3), (16.5, -9), (20, 11),
             (-1, 19), (4, 20), (-14, 20), (15, 19), (-24, 3), (24, 1), (-22, -12), (23, -13)]
    for x, y in spots:
        s = rng.uniform(0.8, 1.35)
        trees.cyl(bark, (x, y, 1.1 * s), 0.28 * s, 2.2 * s, seg=7)
        l = leaf if rng.random() < 0.5 else leaf2
        trees.ico(l, (x, y, 2.9 * s), 1.35 * s, sub=1)
        trees.ico(l, (x + 0.6 * s, y + 0.3 * s, 2.4 * s), 0.9 * s, sub=1)
        trees.ico(l, (x - 0.5 * s, y - 0.4 * s, 3.5 * s), 0.85 * s, sub=1)
    trees.build()

    # ---- hay bales, rocks, trough, flowers ------------------------------- #
    props = Part("Props")
    for x, y, r in [(-15.0, 3.0, 0.2), (-15.2, 1.6, -0.1), (-14.9, 2.3, 0.0), (14.8, -4.0, 0.3),
                    (15.3, -5.3, 0.1), (3.5, 11.0, 1.4), (5.2, 11.3, 1.5)]:
        props.cyl(hay, (x, y, 0.55), 0.55, 1.2, (math.pi / 2, 0, r), seg=12)
        props.cyl(hay_dark, (x, y, 0.55), 0.57, 0.1, (math.pi / 2, 0, r), seg=12)
    props.cyl(hay, (-14.95, 2.3, 1.55), 0.55, 1.2, (math.pi / 2, 0, 1.5), seg=12)
    for x, y, s in [(-14.2, -6.5, 0.6), (13.8, 3.0, 0.45), (-2.0, 15.5, 0.7), (21.0, 7.0, 0.9), (-21.0, -5.0, 0.8)]:
        props.ico(rock, (x, y, s * 0.35), (s, s * 0.8, s * 0.6), sub=1)
    props.cube(wood_dark, (15.0, 8.8, 0.35), (2.4, 0.9, 0.7))
    props.cube(water, (15.0, 8.8, 0.62), (2.2, 0.7, 0.1))
    for i in range(70):
        x = rng.uniform(-26, 26)
        y = rng.uniform(-14, 20)
        if abs(x) < ARENA_X + 2 and -ARENA_Z - 6 < y < ARENA_Z + 2:
            continue
        c = flower_cols[i % len(flower_cols)]
        props.cyl_between(stem, (x, y, 0), (x, y, 0.3), 0.02, seg=4)
        props.ico(c, (x, y, 0.33), 0.09, sub=0)
    props.build()

    # ---- distant hills ---------------------------------------------------- #
    hills = Part("Hills")
    for x, y, sx, sy, sz, m in [(-30, 38, 22, 10, 7, hill), (0, 44, 26, 12, 9, hill2), (32, 38, 22, 10, 8, hill),
                                (-50, 20, 14, 18, 6, hill2), (50, 20, 14, 18, 6, hill2),
                                (-45, -10, 10, 20, 5, hill), (45, -10, 10, 20, 5, hill)]:
        hills.sphere(m, (x, y, 0), (sx, sy, sz), seg=16, rings=8)
    hills.build()

    # ---- clouds (the game drifts this object slowly) --------------------- #
    cloud = mat("Cloud", hexcol("#ffffff"), 1.0, emit=hexcol("#ffffff"), emit_strength=0.35)
    clouds = Part("Clouds")
    for x, y, z, s in [(-28, 55, 22, 1.0), (-4, 62, 26, 1.3), (22, 50, 21, 0.9), (40, 64, 27, 1.1),
                       (-46, 45, 18, 0.8), (8, 75, 30, 1.4)]:
        for dx, dz, r in [(0, 0, 3.2), (3.2, -0.6, 2.4), (-3.0, -0.8, 2.2), (1.2, 1.4, 2.3), (-1.4, 1.0, 1.9)]:
            clouds.ico(cloud, (x + dx * s, y, z + dz * s), (r * s, r * s * 0.8, r * s * 0.75), sub=1)
    clouds.build()


# --------------------------------------------------------------------------- #

ASSETS = [
    ("chicken", build_chicken),
    ("crab", build_crab),
    ("hornet", build_hornet),
    ("dragon", build_dragon),
    ("crown", build_crown),
    ("hammer", build_hammer),
    ("machinegun", build_machinegun),
    ("rocket_launcher", build_rocket_launcher),
    ("rocket", build_rocket),
    ("laser", build_laser),
    ("powerup_freeze", build_powerup_freeze),
    ("powerup_bomb", build_powerup_bomb),
    ("powerup_double", build_powerup_double),
    ("farm", build_farm),
]


def write_bundle():
    """Pack every .glb into assets/models.js so the game works from file:// too."""
    lines = ["// Generated by blender/build_assets.py; do not edit by hand.",
             "window.CHICKEN_MODELS = {"]
    for name, _ in ASSETS:
        with open(os.path.join(OUT_DIR, name + ".glb"), "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        lines.append(f'  "{name}": "{data}",')
    lines.append("};")
    with open(BUNDLE, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  bundled {len(ASSETS)} models into {os.path.relpath(BUNDLE)} "
          f"({os.path.getsize(BUNDLE) / 1024:.0f} KB)")


def main():
    only = [a for a in sys.argv[sys.argv.index("--") + 1:]] if "--" in sys.argv else []
    for name, fn in ASSETS:
        if only and name not in only:
            continue
        print(f"Building {name}...")
        reset_scene()
        _materials.clear()
        fn()
        export(name)
    write_bundle()


if __name__ == "__main__":
    main()
