"""
ARYAOS Core 3D Asset Generator & GLB Exporter for Blender 5.2+
Deterministic procedural modeling script using bpy.
Builds and exports the physical central ARYAOS CORE for AryaOS V1 Spatial Frontend.
"""

import bpy
import bmesh
import math
from mathutils import Vector, Matrix, Euler
import os
import sys

# ---------------------------------------------------------------------------
# CONFIGURATION & CONSTANTS
# ---------------------------------------------------------------------------

SCENE_NAME = "AryaOS_Core_Scene"
BLEND_FILE_PATH = os.path.abspath("frontend/blender/scenes/aryaos_core_source.blend")
GLB_EXPORT_PATH = os.path.abspath("frontend/public/models/aryaos-core.glb")

RENDER_PREVIEW_PATH = os.path.abspath("frontend/blender/renders/aryaos_core_cinematic_preview.png")
RENDER_MONUMENTAL_PATH = os.path.abspath("frontend/blender/renders/aryaos_core_monumental_low_angle.png")
RENDER_DETAIL_PATH = os.path.abspath("frontend/blender/renders/aryaos_core_detail_preview.png")

# Palette constants (Linear PBR)
# Saturated, rich Amber/Gold (#F59E0B) with controlled emission strength to prevent overexposed white burnout
COLOR_AMBER = (0.96, 0.52, 0.04, 1.0)
COLOR_AMBER_ACCENT = (0.92, 0.44, 0.02, 1.0)
COLOR_OBSIDIAN = (0.018, 0.020, 0.024, 1.0)
COLOR_GUNMETAL = (0.045, 0.050, 0.058, 1.0)
COLOR_TITANIUM = (0.35, 0.37, 0.40, 1.0)

COLLECTION_NAMES = [
    "ARYAOS_BASE",
    "ARYAOS_PYLONS",
    "ARYAOS_CORE",
    "ARYAOS_RINGS",
    "ARYAOS_CROWN",
    "ARYAOS_EMISSIVE",
    "ARYAOS_DETAILS",
]


# ---------------------------------------------------------------------------
# SCENE SETUP & UTILITIES
# ---------------------------------------------------------------------------

def clear_scene():
    """Wipes all existing objects, meshes, materials, and custom collections."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not bpy.data.scenes:
        bpy.data.scenes.new(SCENE_NAME)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'METERS'
    scene.unit_settings.scale_length = 1.0


def setup_collections():
    """Creates the strictly specified collection hierarchy."""
    cols = {}
    master_col = bpy.context.scene.collection
    for name in COLLECTION_NAMES:
        col = bpy.data.collections.new(name)
        master_col.children.link(col)
        cols[name] = col
    return cols


def link_object_to_collection(obj, col):
    """Links object to specified collection and unlinks from others."""
    if obj.name not in col.objects:
        col.objects.link(obj)
    for other_col in bpy.data.collections:
        if other_col != col and obj.name in other_col.objects:
            other_col.objects.unlink(obj)
    if obj.name in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.unlink(obj)


# ---------------------------------------------------------------------------
# MATERIAL CREATION
# ---------------------------------------------------------------------------

def create_materials():
    """Creates PBR materials with controlled amber luminescence."""
    materials = {}

    def get_or_create_principled(mat):
        if not mat.node_tree:
            mat.node_tree = bpy.data.node_groups.new(name=mat.name, type='ShaderNodeTree')
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
            out = mat.node_tree.nodes.get("Material Output")
            if not out:
                out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
            mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        return bsdf

    # 1. Obsidian / Graphite
    mat_obsidian = bpy.data.materials.new("MAT_GraphiteObsidian")
    bsdf = get_or_create_principled(mat_obsidian)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLOR_OBSIDIAN
        bsdf.inputs["Roughness"].default_value = 0.28
        bsdf.inputs["Metallic"].default_value = 0.22
        bsdf.inputs["IOR"].default_value = 1.55
    materials["obsidian"] = mat_obsidian

    # 2. Dark Gunmetal
    mat_gunmetal = bpy.data.materials.new("MAT_DarkGunmetal")
    bsdf = get_or_create_principled(mat_gunmetal)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLOR_GUNMETAL
        bsdf.inputs["Roughness"].default_value = 0.32
        bsdf.inputs["Metallic"].default_value = 0.92
    materials["gunmetal"] = mat_gunmetal

    # 3. Brushed Titanium Accents
    mat_titanium = bpy.data.materials.new("MAT_BrushedTitanium")
    bsdf = get_or_create_principled(mat_titanium)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLOR_TITANIUM
        bsdf.inputs["Roughness"].default_value = 0.22
        bsdf.inputs["Metallic"].default_value = 0.95
    materials["titanium"] = mat_titanium

    # 4. Pure Amber Energy (Controlled emission to keep rich warm amber saturation, avoiding blown-out white)
    mat_amber = bpy.data.materials.new("MAT_AmberEnergy")
    bsdf = get_or_create_principled(mat_amber)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLOR_AMBER
        bsdf.inputs["Roughness"].default_value = 0.15
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Emission Color"].default_value = COLOR_AMBER
        bsdf.inputs["Emission Strength"].default_value = 4.2
    materials["amber"] = mat_amber

    # 5. Amber Accent (Subtle telemetry glow)
    mat_amber_subtle = bpy.data.materials.new("MAT_AmberAccent")
    bsdf = get_or_create_principled(mat_amber_subtle)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLOR_AMBER_ACCENT
        bsdf.inputs["Roughness"].default_value = 0.25
        bsdf.inputs["Metallic"].default_value = 0.10
        bsdf.inputs["Emission Color"].default_value = COLOR_AMBER_ACCENT
        bsdf.inputs["Emission Strength"].default_value = 2.0
    materials["amber_subtle"] = mat_amber_subtle

    return materials


def assign_material(obj, mat):
    """Assigns material to object."""
    if not obj or not mat:
        return
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# ---------------------------------------------------------------------------
# PROCEDURAL MESH GENERATION HELPERS
# ---------------------------------------------------------------------------

def apply_bevel(obj, width=0.03, segments=2, limit_angle=30.0):
    """Applies clean bevel modifier to hard-surface geometry."""
    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(limit_angle)
    mod.miter_outer = 'MITER_SHARP'


def create_octagonal_prism(name, radius_bottom, radius_top, height, z_bottom, mat=None, bevel=True):
    """Creates an 8-sided tapered architectural prism with bottom face at z_bottom."""
    bm = bmesh.new()
    verts_bottom = []
    verts_top = []
    angle_offset = math.pi / 8.0
    for i in range(8):
        angle = angle_offset + i * (2.0 * math.pi / 8.0)
        xb = radius_bottom * math.cos(angle)
        yb = radius_bottom * math.sin(angle)
        xt = radius_top * math.cos(angle)
        yt = radius_top * math.sin(angle)
        verts_bottom.append(bm.verts.new((xb, yb, z_bottom)))
        verts_top.append(bm.verts.new((xt, yt, z_bottom + height)))
    
    bm.verts.ensure_lookup_table()
    bm.faces.new(reversed(verts_bottom))
    bm.faces.new(verts_top)
    for i in range(8):
        next_i = (i + 1) % 8
        bm.faces.new([verts_bottom[i], verts_bottom[next_i], verts_top[next_i], verts_top[i]])
    
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new(name, mesh)
    if mat:
        assign_material(obj, mat)
    if bevel:
        apply_bevel(obj, width=min(0.04, height * 0.1), segments=2)
    return obj


def create_cylinder_mesh(name, radius, height, z_bottom, vertices=24, mat=None, bevel=False):
    """Creates a vertical cylinder starting at z_bottom."""
    z_center = z_bottom + (height / 2.0)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=height,
        location=(0, 0, z_center)
    )
    obj = bpy.context.active_object
    obj.name = name
    if mat:
        assign_material(obj, mat)
    if bevel:
        apply_bevel(obj, width=0.02, segments=2)
    return obj


def create_box_mesh(name, size, location, rotation=(0, 0, 0), mat=None, bevel=True, bevel_width=0.03):
    """Creates a cuboid mesh at location with rotation."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if mat:
        assign_material(obj, mat)
    if bevel:
        apply_bevel(obj, width=bevel_width, segments=2)
    return obj


def create_torus_ring(name, major_radius, minor_radius, location, rotation=(0, 0, 0), mat=None):
    """Creates a toroidal ring."""
    bpy.ops.mesh.primitive_torus_add(
        major_segments=36,
        minor_segments=12,
        major_radius=major_radius,
        minor_radius=minor_radius,
        location=location,
        rotation=rotation
    )
    obj = bpy.context.active_object
    obj.name = name
    if mat:
        assign_material(obj, mat)
    return obj


# ---------------------------------------------------------------------------
# 1. STEPPED OBSIDIAN BASE (WIDER, GROUNDED MONUMENTAL PLINTH)
# ---------------------------------------------------------------------------

def build_base(cols, mats):
    """
    Builds the reinforced, wider stepped octagonal obsidian plinth.
    Ground contact is strictly at Z=0.000.
    """
    base_col = cols["ARYAOS_BASE"]
    details_col = cols["ARYAOS_DETAILS"]
    emissive_col = cols["ARYAOS_EMISSIVE"]

    # Tier 1: Ground foundation (Z = 0.00 to 0.45m, radius 3.55m -> footprint ~7.1m across flats)
    t1 = create_octagonal_prism("Base_Tier_01_Foundation", 3.55, 3.48, 0.45, 0.00, mats["obsidian"], bevel=True)
    link_object_to_collection(t1, base_col)

    # Perimeter anchor plates on Tier 1 (8 corners)
    for i in range(8):
        angle = math.pi / 8.0 + i * (math.pi / 4.0)
        dist = 3.45
        x = dist * math.cos(angle)
        y = dist * math.sin(angle)
        plate = create_box_mesh(
            f"Base_Tier01_Anchor_{i+1:02d}",
            (0.42, 0.28, 0.16),
            (x, y, 0.225),
            rotation=(0, 0, angle),
            mat=mats["gunmetal"],
            bevel_width=0.015
        )
        link_object_to_collection(plate, details_col)

    # Tier 2: Secondary Plinth (Z = 0.45 to 0.90m, radius 3.05m)
    t2 = create_octagonal_prism("Base_Tier_02_Plinth", 3.05, 2.98, 0.45, 0.45, mats["obsidian"], bevel=True)
    link_object_to_collection(t2, base_col)

    # Tier 2 Conduit Inlays (8 radial amber channel strips)
    for i in range(8):
        angle = i * (math.pi / 4.0)
        x = 2.45 * math.cos(angle)
        y = 2.45 * math.sin(angle)
        strip = create_box_mesh(
            f"Base_Circuit_Channel_{i+1:02d}",
            (0.95, 0.065, 0.02),
            (x, y, 0.905),
            rotation=(0, 0, angle),
            mat=mats["amber"],
            bevel=False
        )
        link_object_to_collection(strip, emissive_col)

    # Tier 3: Upper Dais with Machined Ventilation Vents (Z = 0.90 to 1.35m, radius 2.55m)
    t3 = create_octagonal_prism("Base_Tier_03_Dais", 2.55, 2.46, 0.45, 0.90, mats["gunmetal"], bevel=True)
    link_object_to_collection(t3, base_col)

    # Ventilation vent grilles on the 4 orthogonal faces of Tier 3
    for i in range(4):
        angle = i * (math.pi / 2.0)
        dist = 2.40
        x = dist * math.cos(angle)
        y = dist * math.sin(angle)
        for row in range(3):
            z_vent = 1.02 + (row * 0.11)
            vent = create_box_mesh(
                f"Base_Vent_F{i+1}_R{row+1}",
                (0.80, 0.045, 0.035),
                (x, y, z_vent),
                rotation=(0, 0, angle + math.pi / 2.0),
                mat=mats["titanium"],
                bevel_width=0.008
            )
            link_object_to_collection(vent, details_col)

    # Tier 4: Pedestal Collar & Core Seat (Z = 1.35 to 1.70m, radius 2.05m)
    t4 = create_octagonal_prism("Base_Tier_04_Pedestal", 2.05, 1.95, 0.35, 1.35, mats["obsidian"], bevel=True)
    link_object_to_collection(t4, base_col)

    # Core Mounting Well Ring (Z = 1.68m, radius 0.95m)
    well_ring = create_torus_ring("Base_Core_Well_Rim", 0.95, 0.05, (0, 0, 1.70), mat=mats["titanium"])
    link_object_to_collection(well_ring, details_col)

    # 4 Heavy Footing Dais Mounts for the Pylons (widened radial stance at 2.42m)
    pylon_angles = [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]
    for idx, angle in enumerate(pylon_angles):
        rad = 1.92
        x = rad * math.cos(angle)
        y = rad * math.sin(angle)
        mount = create_box_mesh(
            f"Base_Pylon_Mount_{idx+1}",
            (0.88, 0.82, 0.28),
            (x, y, 1.58),
            rotation=(0, 0, angle),
            mat=mats["gunmetal"],
            bevel_width=0.03
        )
        link_object_to_collection(mount, details_col)


# ---------------------------------------------------------------------------
# 2. FOUR STRUCTURAL PYLONS (WIDER STANCE, MONUMENTAL CHASSIS)
# ---------------------------------------------------------------------------

def build_pylons(cols, mats):
    """
    Builds the four precision-machined monolithic towers with widened stance and heavy chassis.
    Extends from Z=1.68m to Z=8.10m (~6.42m height), with pylon caps reaching Z=8.35m.
    """
    pylons_col = cols["ARYAOS_PYLONS"]
    details_col = cols["ARYAOS_DETAILS"]
    emissive_col = cols["ARYAOS_EMISSIVE"]

    angles = [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]
    pylon_radial_dist = 2.42  # Widened stance for monumental aspect ratio

    for idx, angle in enumerate(angles):
        p_name = f"Pylon_{idx+1:02d}"
        px = pylon_radial_dist * math.cos(angle)
        py = pylon_radial_dist * math.sin(angle)
        rot_z = angle

        # 1. Main Tapered Structural Chassis
        bm = bmesh.new()
        z_base = 1.68
        z_top = 8.10

        # Substantially widened base footprint: 0.86m x 0.74m -> Top: 0.52m x 0.44m
        w_b, d_b = 0.86, 0.74
        w_t, d_t = 0.52, 0.44

        vb = [
            bm.verts.new((-w_b/2, -d_b/2, z_base)),
            bm.verts.new((w_b/2, -d_b/2, z_base)),
            bm.verts.new((w_b/2, d_b/2, z_base)),
            bm.verts.new((-w_b/2, d_b/2, z_base)),
        ]
        vt = [
            bm.verts.new((-w_t/2, -d_t/2, z_top)),
            bm.verts.new((w_t/2, -d_t/2, z_top)),
            bm.verts.new((w_t/2, d_t/2, z_top)),
            bm.verts.new((-w_t/2, d_t/2, z_top)),
        ]
        bm.verts.ensure_lookup_table()
        bm.faces.new(reversed(vb))
        bm.faces.new(vt)
        for i in range(4):
            ni = (i + 1) % 4
            bm.faces.new([vb[i], vb[ni], vt[ni], vt[i]])

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        mesh = bpy.data.meshes.new(f"{p_name}_Chassis_Mesh")
        bm.to_mesh(mesh)
        bm.free()

        chassis_obj = bpy.data.objects.new(f"{p_name}_Chassis", mesh)
        chassis_obj.location = (px, py, 0)
        chassis_obj.rotation_euler = (0, 0, rot_z)
        assign_material(chassis_obj, mats["gunmetal"])
        apply_bevel(chassis_obj, width=0.04, segments=2)
        link_object_to_collection(chassis_obj, pylons_col)

        # 2. Outer Armor Plating Shells (3 vertical tiers with reveal seams)
        armor_tiers = [
            ("Armor_Lower", 1.85, 3.80, 0.88, 0.24, mats["obsidian"]),
            ("Armor_Mid",   3.92, 5.95, 0.76, 0.22, mats["obsidian"]),
            ("Armor_Upper", 6.08, 7.95, 0.62, 0.20, mats["gunmetal"]),
        ]
        for tname, zb, zt, w_tier, thick, arm_mat in armor_tiers:
            zh = zt - zb
            zc = zb + (zh / 2.0)
            armor_obj = create_box_mesh(
                f"{p_name}_{tname}",
                (w_tier, thick, zh),
                (0, d_b/2 + thick/2.0 - 0.02, zc),
                mat=arm_mat,
                bevel_width=0.025
            )
            armor_obj.parent = chassis_obj
            link_object_to_collection(armor_obj, pylons_col)

        # 3. Cooling Louver Arrays on Outer Flank (Z = 4.2m to 5.6m)
        for louver_idx in range(9):
            z_l = 4.25 + (louver_idx * 0.15)
            louver = create_box_mesh(
                f"{p_name}_Louver_{louver_idx+1:02d}",
                (0.56, 0.06, 0.035),
                (0, d_b/2 + 0.12, z_l),
                rotation=(math.radians(18), 0, 0),
                mat=mats["titanium"],
                bevel_width=0.005
            )
            louver.parent = chassis_obj
            link_object_to_collection(louver, details_col)

        # 4. Inward-Facing Emissive Conduit Strip (recessed along inner pylon face, local -Y)
        conduit_h = 5.6
        conduit_zc = 2.0 + (conduit_h / 2.0)
        conduit = create_box_mesh(
            f"{p_name}_Conduit_Strip",
            (0.075, 0.04, conduit_h),
            (0, -d_b/2 + 0.015, conduit_zc),
            mat=mats["amber"],
            bevel=False
        )
        conduit.parent = chassis_obj
        link_object_to_collection(conduit, emissive_col)

        # 5. Cantilevered Structural Mechanical Brackets linking Pylon directly to Core Chambers & Rings
        bracket_configs = [
            ("Bracket_Low_Reactor", 2.80, 0.55, 0.16),  # Anchors into lower reactor magnetic collar
            ("Bracket_Mid_Gimbal",  4.80, 0.65, 0.18),  # Anchors into containment ring assembly
            ("Bracket_Up_Strut",    6.80, 0.55, 0.16),  # Anchors into upper stabilization ring
        ]
        for b_name, b_z, reach, b_thick in bracket_configs:
            bracket = create_box_mesh(
                f"{p_name}_{b_name}",
                (0.32, reach, b_thick),
                (0, -d_b/2 - reach/2.0 + 0.05, b_z),
                mat=mats["titanium"],
                bevel_width=0.018
            )
            bracket.parent = chassis_obj
            link_object_to_collection(bracket, details_col)

        # 6. Top Pylon Magnetic Stabilizer Emitter Cap (Z = 8.10m to 8.35m)
        cap = create_box_mesh(
            f"{p_name}_Emitter_Cap",
            (0.46, 0.40, 0.25),
            (0, 0, 8.225),
            mat=mats["titanium"],
            bevel_width=0.02
        )
        cap.parent = chassis_obj
        link_object_to_collection(cap, pylons_col)

        cap_lens = create_cylinder_mesh(
            f"{p_name}_Emitter_Lens",
            0.12, 0.06, 8.35,
            vertices=16,
            mat=mats["amber"],
            bevel=False
        )
        cap_lens.parent = chassis_obj
        link_object_to_collection(cap_lens, emissive_col)


# ---------------------------------------------------------------------------
# 3. CENTRAL CORE CHAMBER & AMBER ENERGY COLUMN
# ---------------------------------------------------------------------------

def build_core_chamber(cols, mats):
    """
    Builds the central magnetic containment pressure chamber and amber energy column.
    Spans Z = 1.70m to Z = 7.95m.
    """
    core_col = cols["ARYAOS_CORE"]
    emissive_col = cols["ARYAOS_EMISSIVE"]
    details_col = cols["ARYAOS_DETAILS"]

    # 1. Lower Core Pressure Flange (Z = 1.70 to 2.15m, radius 0.88m)
    lower_flange = create_octagonal_prism("Core_Lower_Flange", 0.88, 0.78, 0.45, 1.70, mats["gunmetal"], bevel=True)
    link_object_to_collection(lower_flange, core_col)

    # 2. Upper Core Pressure Flange (Z = 7.50 to 7.95m, radius 0.80m)
    upper_flange = create_octagonal_prism("Core_Upper_Flange", 0.72, 0.80, 0.45, 7.50, mats["gunmetal"], bevel=True)
    link_object_to_collection(upper_flange, core_col)

    # 3. Central Amber Energy Column (Z = 1.85 to 7.80m, radius 0.28m)
    energy_col = create_cylinder_mesh(
        "Core_Amber_Energy_Column",
        radius=0.28,
        height=5.95,
        z_bottom=1.85,
        vertices=24,
        mat=mats["amber"],
        bevel=False
    )
    link_object_to_collection(energy_col, emissive_col)

    # 4. Vertical Optical Waveguide Rods (4 conduit rods around column)
    waveguide_angles = [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0]
    for w_idx, w_angle in enumerate(waveguide_angles):
        rad_w = 0.46
        wx = rad_w * math.cos(w_angle)
        wy = rad_w * math.sin(w_angle)
        rod = create_cylinder_mesh(
            f"Core_Waveguide_Rod_{w_idx+1:02d}",
            radius=0.035,
            height=5.70,
            z_bottom=1.95,
            vertices=12,
            mat=mats["amber_subtle"],
            bevel=False
        )
        rod.location = (wx, wy, 1.95 + 2.85)
        link_object_to_collection(rod, emissive_col)

    # 5. Open Structural Confinement Ribs (8 vertical titanium columns forming the open viewing cage)
    for r_idx in range(8):
        r_angle = math.pi / 8.0 + r_idx * (math.pi / 4.0)
        rad_r = 0.72
        rx = rad_r * math.cos(r_angle)
        ry = rad_r * math.sin(r_angle)
        rib = create_box_mesh(
            f"Core_Cage_Rib_{r_idx+1:02d}",
            (0.10, 0.15, 5.50),
            (rx, ry, 4.80),
            rotation=(0, 0, r_angle),
            mat=mats["titanium"],
            bevel_width=0.015
        )
        link_object_to_collection(rib, core_col)

    # 6. Magnetic Constriction Collars (at 4 distinct compression nodes along the column)
    collar_heights = [2.80, 4.15, 5.50, 6.80]
    for c_idx, c_z in enumerate(collar_heights):
        collar = create_torus_ring(
            f"Core_Magnetic_Collar_{c_idx+1:02d}",
            major_radius=0.74,
            minor_radius=0.075,
            location=(0, 0, c_z),
            mat=mats["gunmetal"]
        )
        link_object_to_collection(collar, core_col)

        # Heavy clamp lugs on collars
        for lug_i in range(4):
            lug_ang = lug_i * (math.pi / 2.0)
            lx = 0.82 * math.cos(lug_ang)
            ly = 0.82 * math.sin(lug_ang)
            lug = create_box_mesh(
                f"Core_Collar_{c_idx+1}_Lug_{lug_i+1}",
                (0.12, 0.16, 0.18),
                (lx, ly, c_z),
                rotation=(0, 0, lug_ang),
                mat=mats["titanium"],
                bevel_width=0.012
            )
            link_object_to_collection(lug, details_col)


# ---------------------------------------------------------------------------
# 4. CONTAINMENT RINGS & CALIBRATION GIMBALS
# ---------------------------------------------------------------------------

def build_containment_rings(cols, mats):
    """
    Builds the concentric calibration gimbals and containment rings encircling the core.
    """
    rings_col = cols["ARYAOS_RINGS"]
    details_col = cols["ARYAOS_DETAILS"]
    emissive_col = cols["ARYAOS_EMISSIVE"]

    # Ring 1: Lower Gimbal Assembly (Z = 2.80m)
    ring_low = create_torus_ring(
        "Ring_Lower_Gimbal_Main",
        major_radius=1.45,
        minor_radius=0.075,
        location=(0, 0, 2.80),
        rotation=(math.radians(3.0), math.radians(2.0), 0),
        mat=mats["gunmetal"]
    )
    link_object_to_collection(ring_low, rings_col)

    # Ring 2 & 3: Mid Dual Concentric Containment System (Z = 4.80m)
    # Outer indexing ring
    ring_mid_outer = create_torus_ring(
        "Ring_Mid_Outer_Index",
        major_radius=1.65,
        minor_radius=0.085,
        location=(0, 0, 4.80),
        mat=mats["gunmetal"]
    )
    link_object_to_collection(ring_mid_outer, rings_col)

    # 16 Machined Indexing Teeth on Outer Ring
    for t_idx in range(16):
        t_ang = t_idx * (2.0 * math.pi / 16.0)
        tx = 1.72 * math.cos(t_ang)
        ty = 1.72 * math.sin(t_ang)
        tooth = create_box_mesh(
            f"Ring_Mid_Tooth_{t_idx+1:02d}",
            (0.05, 0.09, 0.12),
            (tx, ty, 4.80),
            rotation=(0, 0, t_ang),
            mat=mats["titanium"],
            bevel_width=0.006
        )
        link_object_to_collection(tooth, details_col)

    # Inner counter-rotation gimbal ring
    ring_mid_inner = create_torus_ring(
        "Ring_Mid_Inner_Counter",
        major_radius=1.35,
        minor_radius=0.065,
        location=(0, 0, 4.80),
        mat=mats["obsidian"]
    )
    link_object_to_collection(ring_mid_inner, rings_col)

    # 8 Amber Sensor Nodes mounted along inner ring
    for s_idx in range(8):
        s_ang = s_idx * (2.0 * math.pi / 8.0)
        sx = 1.35 * math.cos(s_ang)
        sy = 1.35 * math.sin(s_ang)
        sensor = create_cylinder_mesh(
            f"Ring_Mid_SensorNode_{s_idx+1:02d}",
            radius=0.045,
            height=0.08,
            z_bottom=4.76,
            vertices=12,
            mat=mats["amber"],
            bevel=False
        )
        sensor.location = (sx, sy, 4.80)
        sensor.rotation_euler = (math.pi / 2.0, 0, s_ang)
        link_object_to_collection(sensor, emissive_col)

    # Ring 4: Upper Octagonal Stabilization Framework (Z = 6.80m)
    t_up = create_octagonal_prism(
        "Ring_Upper_Stabilizer_Octagon",
        radius_bottom=1.52,
        radius_top=1.52,
        height=0.20,
        z_bottom=6.70,
        mat=mats["titanium"],
        bevel=True
    )
    link_object_to_collection(t_up, rings_col)

    # 4 Tie-in struts linking upper ring to the 4 pylon brackets
    angles_diag = [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]
    for s_i, ang in enumerate(angles_diag):
        dist_mid = 1.82
        sx = dist_mid * math.cos(ang)
        sy = dist_mid * math.sin(ang)
        strut = create_box_mesh(
            f"Ring_Upper_Strut_{s_i+1}",
            (0.14, 0.45, 0.10),
            (sx, sy, 6.80),
            rotation=(0, 0, ang),
            mat=mats["gunmetal"],
            bevel_width=0.012
        )
        link_object_to_collection(strut, details_col)


# ---------------------------------------------------------------------------
# 5. FLOATING COMPUTATIONAL CROWN (ADVANCED AI INTELLIGENCE ASSEMBLY)
# ---------------------------------------------------------------------------

def build_floating_crown(cols, mats):
    """
    Builds the geometrically engineered floating crown hovering from Z = 8.65m to Z = 10.55m.
    A clean ~0.35m - 0.50m physical air gap separates it from the pylon tips (Z = 8.35m).
    """
    crown_col = cols["ARYAOS_CROWN"]
    details_col = cols["ARYAOS_DETAILS"]
    emissive_col = cols["ARYAOS_EMISSIVE"]

    # 1. Lower Induction Ring (Z = 8.65 to 8.88m, radius 1.60m)
    ind_ring = create_octagonal_prism(
        "Crown_Induction_Ring",
        radius_bottom=1.60,
        radius_top=1.52,
        height=0.23,
        z_bottom=8.65,
        mat=mats["titanium"],
        bevel=True
    )
    link_object_to_collection(ind_ring, crown_col)

    # 4 Downward Emitter Prisms on Induction Ring (aligning over pylon emitter caps)
    pylon_angles = [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]
    for idx, angle in enumerate(pylon_angles):
        rad = 1.55
        px = rad * math.cos(angle)
        py = rad * math.sin(angle)
        prism = create_box_mesh(
            f"Crown_Induction_Prism_{idx+1}",
            (0.20, 0.20, 0.16),
            (px, py, 8.60),
            rotation=(0, 0, angle),
            mat=mats["amber"],
            bevel=False
        )
        link_object_to_collection(prism, emissive_col)

    # 2. Central Computational Quantum Processor Monolith
    # Spans Z = 9.00m to Z = 10.15m (Height = 1.15m)
    bm = bmesh.new()
    zb, zm, zt = 9.00, 9.75, 10.20
    rb, rm, rt = 0.42, 0.82, 0.48

    verts_b, verts_m, verts_t = [], [], []
    for i in range(8):
        ang = math.pi / 8.0 + i * (math.pi / 4.0)
        verts_b.append(bm.verts.new((rb * math.cos(ang), rb * math.sin(ang), zb)))
        verts_m.append(bm.verts.new((rm * math.cos(ang), rm * math.sin(ang), zm)))
        verts_t.append(bm.verts.new((rt * math.cos(ang), rt * math.sin(ang), zt)))

    bm.verts.ensure_lookup_table()
    bm.faces.new(reversed(verts_b))
    bm.faces.new(verts_t)
    for i in range(8):
        ni = (i + 1) % 8
        bm.faces.new([verts_b[i], verts_b[ni], verts_m[ni], verts_m[i]])
    for i in range(8):
        ni = (i + 1) % 8
        bm.faces.new([verts_m[i], verts_m[ni], verts_t[ni], verts_t[i]])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Crown_Central_Processor_Mesh")
    bm.to_mesh(mesh)
    bm.free()

    proc_obj = bpy.data.objects.new("Crown_Central_Processor", mesh)
    assign_material(proc_obj, mats["obsidian"])
    apply_bevel(proc_obj, width=0.035, segments=2)
    link_object_to_collection(proc_obj, crown_col)

    # 3. Downward-Facing Amber Focal Aperture (at Z = 8.96m, projecting energy down to core)
    focal_lens = create_cylinder_mesh(
        "Crown_Focal_Emitter_Lens",
        radius=0.32,
        height=0.10,
        z_bottom=8.94,
        vertices=16,
        mat=mats["amber"],
        bevel=False
    )
    link_object_to_collection(focal_lens, emissive_col)

    # 4. Floating Satellite Accelerator Blades (4 outer blades at 0, 90, 180, 270 deg)
    sat_angles = [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0]
    sat_radius = 2.15

    for s_idx, s_ang in enumerate(sat_angles):
        sx = sat_radius * math.cos(s_ang)
        sy = sat_radius * math.sin(s_ang)

        # Wing blade body (Z = 9.15m to 10.05m, height 0.90m)
        blade = create_box_mesh(
            f"Crown_Satellite_Blade_{s_idx+1:02d}",
            (0.62, 0.18, 0.90),
            (sx, sy, 9.60),
            rotation=(0, 0, s_ang),
            mat=mats["gunmetal"],
            bevel_width=0.025
        )
        link_object_to_collection(blade, crown_col)

        # Aerodynamic titanium trailing edge
        trail_edge = create_box_mesh(
            f"Crown_Satellite_Trim_{s_idx+1:02d}",
            (0.65, 0.05, 0.92),
            (sx, sy, 9.60),
            rotation=(0, 0, s_ang),
            mat=mats["titanium"],
            bevel_width=0.01
        )
        link_object_to_collection(trail_edge, details_col)

        # Triple telemetry sensor slits
        for slit_i in range(3):
            slit_z = 9.35 + slit_i * 0.22
            slit = create_box_mesh(
                f"Crown_Satellite_Slit_{s_idx+1}_{slit_i+1}",
                (0.44, 0.04, 0.035),
                (sx, sy, slit_z),
                rotation=(0, 0, s_ang),
                mat=mats["amber"],
                bevel=False
            )
            link_object_to_collection(slit, emissive_col)

    # 5. Concentric Data Telemetry Ring (Z = 10.15m, radius 1.25m)
    data_ring = create_torus_ring(
        "Crown_Data_Telemetry_Ring",
        major_radius=1.25,
        minor_radius=0.05,
        location=(0, 0, 10.15),
        mat=mats["titanium"]
    )
    link_object_to_collection(data_ring, crown_col)

    # 6. Top Telemetry Apex Spire (Z = 10.20m to 10.55m)
    apex_pinnacle = create_octagonal_prism(
        "Crown_Apex_Pinnacle",
        radius_bottom=0.48,
        radius_top=0.08,
        height=0.35,
        z_bottom=10.20,
        mat=mats["titanium"],
        bevel=True
    )
    link_object_to_collection(apex_pinnacle, crown_col)

    apex_beacon = create_cylinder_mesh(
        "Crown_Apex_Beacon",
        radius=0.045,
        height=0.08,
        z_bottom=10.55,
        vertices=8,
        mat=mats["amber"],
        bevel=False
    )
    link_object_to_collection(apex_beacon, emissive_col)


# ---------------------------------------------------------------------------
# STUDIO LIGHTING & CAMERAS FOR PREVIEWS
# ---------------------------------------------------------------------------

def setup_preview_studio():
    """Configures architectural studio lighting and framing cameras."""
    scene = bpy.context.scene

    studio_col = bpy.data.collections.new("STUDIO_LIGHTING_CAMERA")
    scene.collection.children.link(studio_col)

    # Ground reflective stage plane
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0, 0, -0.002))
    ground = bpy.context.active_object
    ground.name = "Studio_Ground_Plane"
    mat_floor = bpy.data.materials.new("MAT_StudioDarkFloor")
    bsdf_floor = mat_floor.node_tree.nodes.get("Principled BSDF") if mat_floor.node_tree else None
    if bsdf_floor:
        bsdf_floor.inputs["Base Color"].default_value = (0.012, 0.014, 0.018, 1.0)
        bsdf_floor.inputs["Roughness"].default_value = 0.16
        bsdf_floor.inputs["Metallic"].default_value = 0.75
    assign_material(ground, mat_floor)
    link_object_to_collection(ground, studio_col)

    # 1. Key Light (Hero architectural cool white/cyan rim)
    bpy.ops.object.light_add(type='AREA', location=(14.0, -10.0, 9.0))
    key_light = bpy.context.active_object
    key_light.name = "Light_Key_Area"
    key_light.data.energy = 6500.0
    key_light.data.size = 7.0
    key_light.data.color = (0.88, 0.94, 1.0)
    key_light.rotation_euler = (math.radians(52), math.radians(12), math.radians(35))
    link_object_to_collection(key_light, studio_col)

    # 2. Rim / Silhouette Kicker Light (High-angle backlight)
    bpy.ops.object.light_add(type='AREA', location=(-8.0, 11.0, 12.0))
    rim_light = bpy.context.active_object
    rim_light.name = "Light_Rim_Area"
    rim_light.data.energy = 5500.0
    rim_light.data.size = 7.0
    rim_light.data.color = (0.75, 0.88, 1.0)
    rim_light.rotation_euler = (math.radians(-50), math.radians(-25), math.radians(-140))
    link_object_to_collection(rim_light, studio_col)

    # 3. Soft Ambient Fill Light
    bpy.ops.object.light_add(type='AREA', location=(-12.0, -9.0, 6.5))
    fill_light = bpy.context.active_object
    fill_light.name = "Light_Fill_Area"
    fill_light.data.energy = 2800.0
    fill_light.data.size = 9.0
    fill_light.data.color = (0.88, 0.90, 0.95)
    fill_light.rotation_euler = (math.radians(65), math.radians(-20), math.radians(-45))
    link_object_to_collection(fill_light, studio_col)

    # 4. Floor Warm Bounce / Uplight
    bpy.ops.object.light_add(type='AREA', location=(2.0, -7.0, 0.4))
    uplight = bpy.context.active_object
    uplight.name = "Light_Floor_Uplight"
    uplight.data.energy = 1600.0
    uplight.data.size = 5.0
    uplight.data.color = (1.0, 0.72, 0.35)
    uplight.rotation_euler = (math.radians(-75), 0, math.radians(15))
    link_object_to_collection(uplight, studio_col)

    # World background dark atmosphere
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AryaOS_World")
    if not scene.world.node_tree:
        scene.world.node_tree = bpy.data.node_groups.new(name="AryaOS_World_Tree", type='ShaderNodeTree')
    bg = scene.world.node_tree.nodes.get("Background")
    if not bg:
        bg = scene.world.node_tree.nodes.new("ShaderNodeBackground")
        out_w = scene.world.node_tree.nodes.get("World Output") or scene.world.node_tree.nodes.new("ShaderNodeOutputWorld")
        scene.world.node_tree.links.new(bg.outputs["Background"], out_w.inputs["Surface"])
    if bg:
        bg.inputs["Color"].default_value = (0.007, 0.009, 0.014, 1.0)
        bg.inputs["Strength"].default_value = 0.5

    # Cinematic Camera: Monumental architectural hero angle
    bpy.ops.object.camera_add(location=(17.5, -7.5, 4.8))
    cam = bpy.context.active_object
    cam.name = "Camera_Hero_Cinematic"
    cam.data.lens = 32.0
    cam.data.clip_start = 0.1
    cam.data.clip_end = 200.0
    
    target = Vector((0.0, 0.0, 5.3))
    direction = target - cam.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()

    scene.camera = cam
    link_object_to_collection(cam, studio_col)
    return cam


def render_preview(filepath, resolution_x=1920, resolution_y=1080, samples=32):
    """Renders high-quality preview still using Cycles."""
    scene = bpy.context.scene
    import addon_utils
    addon_utils.enable('cycles')
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.filepath = filepath
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    print(f"Rendering preview to: {filepath} ...")
    bpy.ops.render.render(write_still=True)
    print(f"Render complete: {filepath}")


# ---------------------------------------------------------------------------
# GLB EXPORT AUTOMATION (OPTIMIZED FOR BROWSER / THREE.JS)
# ---------------------------------------------------------------------------

def export_core_glb(filepath, scale_factor=0.3333333):
    """
    Exports the ARYAOS Core to glTF 2.0 Binary (.glb).
    - Selects ONLY model collections (excludes studio lights & cameras).
    - Applies 1/3 scale (~0.3333) directly with center (0, 0, 0) and applies transform
      so that the 10.55m monument becomes 3.5167 units natively in the GLB.
      When SpatialCore renders with scale=1.2, height is 4.22 units, matching SpatialMonolith exactly.
    - Ground contact strictly at Y=0 (Three.js Y-up).
    - Origin centered at (0, 0, 0).
    """
    print(f"\nPreparing GLB export to: {filepath} ...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # 1. Select all model mesh objects
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.data.objects:
        if obj.name != 'Studio_Ground_Plane' and 'Light' not in obj.name and 'Camera' not in obj.name:
            obj.select_set(True)
        else:
            obj.select_set(False)

    # 2. Scale around origin (0, 0, 0)
    bpy.ops.transform.resize(value=(scale_factor, scale_factor, scale_factor), center_override=(0, 0, 0))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # 3. Export to GLB
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLB',
        use_selection=True,
        export_yup=True,
        export_materials='EXPORT',
        export_cameras=False,
        export_lights=False,
        export_animations=False,
    )

    # 4. Invert scale to restore full monument dimensions in Blender scene
    inv_scale = 1.0 / scale_factor
    bpy.ops.transform.resize(value=(inv_scale, inv_scale, inv_scale), center_override=(0, 0, 0))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    print(f"GLB export successfully written to: {filepath}")


# ---------------------------------------------------------------------------
# STATS & VERIFICATION REPORT
# ---------------------------------------------------------------------------

def calculate_scene_stats():
    """Computes exact geometric stats across all procedural meshes."""
    total_triangles = 0
    total_vertices = 0
    total_objects = 0
    materials_set = set()

    min_z = float('inf')
    max_z = float('-inf')
    max_radius = 0.0

    for obj in bpy.data.objects:
        if obj.type == 'MESH' and obj.name != "Studio_Ground_Plane":
            total_objects += 1
            mesh = obj.data
            for poly in mesh.polygons:
                total_triangles += max(1, len(poly.vertices) - 2)
            total_vertices += len(mesh.vertices)
            for mat in obj.data.materials:
                if mat:
                    materials_set.add(mat.name)

            for corner in obj.bound_box:
                w_corner = obj.matrix_world @ Vector(corner)
                min_z = min(min_z, w_corner.z)
                max_z = max(max_z, w_corner.z)
                rad = math.hypot(w_corner.x, w_corner.y)
                max_radius = max(max_radius, rad)

    return {
        "total_objects": total_objects,
        "total_triangles": total_triangles,
        "total_vertices": total_vertices,
        "materials": sorted(list(materials_set)),
        "min_z": round(min_z, 4),
        "max_z": round(max_z, 4),
        "height": round(max_z - min_z, 4),
        "footprint_diameter": round(max_radius * 2.0, 4),
    }


# ---------------------------------------------------------------------------
# MAIN EXECUTION ROUTINE
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("ARYAOS CORE 3D REFINED GENERATOR & GLB EXPORT — PHASE 6B")
    print("=" * 60)

    # 1. Reset scene
    clear_scene()

    # 2. Setup Collections
    cols = setup_collections()

    # 3. Create Materials
    mats = create_materials()

    # 4. Build Architectural Assemblies
    print("Building Base...")
    build_base(cols, mats)

    print("Building Pylons...")
    build_pylons(cols, mats)

    print("Building Core Chamber...")
    build_core_chamber(cols, mats)

    print("Building Containment Rings...")
    build_containment_rings(cols, mats)

    print("Building Floating Crown...")
    build_floating_crown(cols, mats)

    # 5. Studio Lighting & Camera
    print("Setting up preview studio...")
    cam = setup_preview_studio()

    # 6. Ensure target directories exist
    os.makedirs(os.path.dirname(BLEND_FILE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(RENDER_PREVIEW_PATH), exist_ok=True)

    # 7. Save .blend source scene
    print(f"Saving .blend scene to: {BLEND_FILE_PATH} ...")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_FILE_PATH)
    print("Blend file successfully saved.")

    # 8. Render Previews
    # 8a. Hero View (Full 16:9 Monument)
    render_preview(RENDER_PREVIEW_PATH, resolution_x=1920, resolution_y=1080, samples=40)

    # 8b. Low-Angle Dramatic Perspective
    cam.location = (11.5, -4.5, 1.4)
    cam.data.lens = 26.0
    target_low = Vector((0.0, 0.0, 5.8))
    direction_low = target_low - cam.location
    cam.rotation_euler = direction_low.to_track_quat('-Z', 'Y').to_euler()
    render_preview(RENDER_MONUMENTAL_PATH, resolution_x=1920, resolution_y=1080, samples=32)

    # 8c. Detail Close-up (Core & Containment Rings)
    cam.location = (5.5, -4.0, 4.8)
    cam.data.lens = 55.0
    target_detail = Vector((0.0, 0.0, 4.8))
    direction_detail = target_detail - cam.location
    cam.rotation_euler = direction_detail.to_track_quat('-Z', 'Y').to_euler()
    render_preview(RENDER_DETAIL_PATH, resolution_x=1920, resolution_y=1080, samples=32)

    # 9. Export GLB for Frontend Integration
    export_core_glb(GLB_EXPORT_PATH, scale_factor=0.3333333)

    # 10. Calculate & Report Stats
    stats = calculate_scene_stats()
    glb_size_bytes = os.path.getsize(GLB_EXPORT_PATH) if os.path.exists(GLB_EXPORT_PATH) else 0

    print("\n" + "=" * 60)
    print("GENERATION & EXPORT COMPLETE — METRICS & VERIFICATION")
    print("=" * 60)
    print(f"Objects Created:       {stats['total_objects']}")
    print(f"Approx Dimensions:     Height {stats['height']}m (Z: {stats['min_z']}m -> {stats['max_z']}m), Footprint: {stats['footprint_diameter']}m")
    print(f"Triangle Count:        {stats['total_triangles']:,} tris")
    print(f"Vertex Count:          {stats['total_vertices']:,} verts")
    print(f"Material Count:        {len(stats['materials'])} ({', '.join(stats['materials'])})")
    print(f"Collection Structure:  {', '.join(COLLECTION_NAMES)}")
    print(f"Source .blend Saved:   {BLEND_FILE_PATH}")
    print(f"Hero Render Saved:     {RENDER_PREVIEW_PATH}")
    print(f"Monumental Low Saved:  {RENDER_MONUMENTAL_PATH}")
    print(f"Detail Render Saved:   {RENDER_DETAIL_PATH}")
    print(f"GLB Exported To:       {GLB_EXPORT_PATH} ({glb_size_bytes / 1024:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
