"""
AryaOS V1 — Stage 02 ARYAOS CORE Environment Generator for Blender 5.2+
Authoritative 3D Cinematic Environment Builder matching the Awakening visual benchmark:
- Imports existing aryaos-core.glb as central intelligence asset (untouched)
- Colossal multi-tiered circular obsidian platform with stepped rims and recessed conduit channels
- Concentric amber energy ribbons and cyan intelligence telemetry tracks inlaid into floor channels
- 12 radial conduits forming the circular circuit mandala
- Low-lying rolling cumulus cloud sea surrounding the floating platform
- Procedural stormy overcast sky dome with atmospheric depth and cloud swirl
- Colossal distant citadel spire and flanking towers rising through the clouds
- Floating jagged obsidian monoliths hovering with telemetry lights
- Human-scale silhouette standing gracefully on the platform anchoring monumental scale
- 6 subsystem module stations (Memory, Planning, Routing, Analytics, Job Package, Execution)
- Monumental vertical amber energy pillar shooting from the Core into the overcast sky
- Cinematic high-contrast lighting with Compositor Bloom
- Saves complete scene to frontend/blender/scenes/stage02_aryaos_core_environment.blend
- Renders 3 high-resolution reference stills for visual approval
"""

import bpy
import bmesh
import math
from mathutils import Vector, Matrix, Euler
import os
import sys

# ---------------------------------------------------------------------------
# PATH CONFIGURATION
# ---------------------------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

GLB_SOURCE_PATH = os.path.join(BASE_DIR, "public", "models", "aryaos-core.glb")
BLEND_EXPORT_PATH = os.path.join(BASE_DIR, "blender", "scenes", "stage02_aryaos_core_environment.blend")

RENDERS_DIR = os.path.join(BASE_DIR, "blender", "renders")
ARTIFACT_DIR = "/Users/venkatakishorenasina/.gemini/antigravity-cli/brain/3ef15538-68d7-4a27-acba-87fb25404737"

RENDER_HERO_PATH = os.path.join(RENDERS_DIR, "stage02_core_cinematic_hero.png")
RENDER_LOW_ANGLE_PATH = os.path.join(RENDERS_DIR, "stage02_core_monumental_low_angle.png")
RENDER_DETAIL_PATH = os.path.join(RENDERS_DIR, "stage02_core_platform_detail.png")

# Palette constants (Linear PBR)
COLOR_AMBER = (1.0, 0.60, 0.10, 1.0)
COLOR_AMBER_BRIGHT = (1.0, 0.88, 0.50, 1.0)
COLOR_CYAN_ACCENT = (0.04, 0.85, 0.98, 1.0)
COLOR_OBSIDIAN = (0.012, 0.015, 0.020, 1.0)
COLOR_OBSIDIAN_EDGE = (0.024, 0.030, 0.040, 1.0)
COLOR_GUNMETAL = (0.042, 0.050, 0.062, 1.0)
COLOR_TITANIUM = (0.35, 0.38, 0.44, 1.0)
COLOR_TOWER_DISTANT = (0.040, 0.050, 0.065, 1.0)

# ---------------------------------------------------------------------------
# SCENE INITIALIZATION & UTILITIES
# ---------------------------------------------------------------------------

def clear_scene():
    """Resets Blender factory settings and prepares clean metric environment."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not bpy.data.scenes:
        bpy.data.scenes.new("Stage02_Core_Environment")
    scene = bpy.context.scene
    scene.name = "Stage02_Core_Environment"

    # Set metric units (1 BU = 1 Meter)
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = 'METERS'

    # Color management for high dynamic range cinematic look
    scene.view_settings.view_transform = 'AgX' if 'AgX' in [item.identifier for item in scene.view_settings.bl_rna.properties['view_transform'].enum_items] else 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.view_settings.exposure = 0.10

    return scene

def create_collection(name, parent_col=None):
    """Creates a collection or returns existing, linked to parent."""
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
    else:
        col = bpy.data.collections.new(name)
        if parent_col:
            parent_col.children.link(col)
        else:
            bpy.context.scene.collection.children.link(col)
    return col

def link_to_collection(obj, target_col):
    """Ensures object is linked to target collection and unlinked from default."""
    for col in obj.users_collection:
        col.objects.unlink(obj)
    target_col.objects.link(obj)

# ---------------------------------------------------------------------------
# CINEMATIC SHADER LIBRARY
# ---------------------------------------------------------------------------

def create_materials():
    """Generates rich, procedural PBR materials matching the Awakening artwork."""
    materials = {}

    # 1. Monolithic Obsidian Floor (Dark, reflective wet obsidian alloy)
    mat_obsidian = bpy.data.materials.new(name="MAT_Obsidian_Floor_PBR")
    mat_obsidian.use_nodes = True
    nodes = mat_obsidian.node_tree.nodes
    links = mat_obsidian.node_tree.links
    nodes.clear()

    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = COLOR_OBSIDIAN
    bsdf.inputs['Metallic'].default_value = 0.85
    bsdf.inputs['IOR'].default_value = 1.55

    coord = nodes.new('ShaderNodeTexCoord')
    noise = nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 14.0
    noise.inputs['Detail'].default_value = 6.0
    noise.inputs['Roughness'].default_value = 0.55

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.10
    ramp.color_ramp.elements[0].color = (0.16, 0.16, 0.16, 1.0)
    ramp.color_ramp.elements[1].position = 0.85
    ramp.color_ramp.elements[1].color = (0.34, 0.34, 0.34, 1.0)

    links.new(coord.outputs['Object'], noise.inputs['Vector'])
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])

    bump = nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.03
    bump.inputs['Distance'].default_value = 0.06
    links.new(noise.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['obsidian'] = mat_obsidian

    # 2. Beveled Gunmetal Edge / Dais Trim
    mat_edge = bpy.data.materials.new(name="MAT_Obsidian_Edge_Trim")
    mat_edge.use_nodes = True
    nodes = mat_edge.node_tree.nodes
    links = mat_edge.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = COLOR_OBSIDIAN_EDGE
    bsdf.inputs['Metallic'].default_value = 0.88
    bsdf.inputs['Roughness'].default_value = 0.26
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['obsidian_beveled'] = mat_edge

    # 3. Titanium Structural Alloy (Machined architectural ribs)
    mat_ti = bpy.data.materials.new(name="MAT_Titanium_Machined")
    mat_ti.use_nodes = True
    nodes = mat_ti.node_tree.nodes
    links = mat_ti.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = COLOR_TITANIUM
    bsdf.inputs['Metallic'].default_value = 0.92
    bsdf.inputs['Roughness'].default_value = 0.22
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['titanium'] = mat_ti

    # 4. Restrained Amber Energy Emission (Conduits & Core) — Warm, refined glow
    mat_amber = bpy.data.materials.new(name="MAT_Amber_Energy_Emission")
    mat_amber.use_nodes = True
    nodes = mat_amber.node_tree.nodes
    links = mat_amber.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = COLOR_AMBER
    em.inputs['Strength'].default_value = 6.5
    links.new(em.outputs['Emission'], out_node.inputs['Surface'])
    materials['amber_energy'] = mat_amber

    # 5. Cyan Intelligence Telemetry Emission — Crisp accent
    mat_cyan = bpy.data.materials.new(name="MAT_Cyan_Telemetry_Emission")
    mat_cyan.use_nodes = True
    nodes = mat_cyan.node_tree.nodes
    links = mat_cyan.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = COLOR_CYAN_ACCENT
    em.inputs['Strength'].default_value = 5.5
    links.new(em.outputs['Emission'], out_node.inputs['Surface'])
    materials['cyan_telemetry'] = mat_cyan

    # 6. Central Vertical Beam: Inner Core (Slender, Focused pillar)
    mat_beam_core = bpy.data.materials.new(name="MAT_Beam_Core_Emission")
    mat_beam_core.use_nodes = True
    nodes = mat_beam_core.node_tree.nodes
    links = mat_beam_core.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = COLOR_AMBER_BRIGHT
    em.inputs['Strength'].default_value = 28.0
    links.new(em.outputs['Emission'], out_node.inputs['Surface'])
    materials['beam_core'] = mat_beam_core

    # 7. Central Vertical Beam: Outer Luminous Halo (Soft facing falloff)
    mat_beam_outer = bpy.data.materials.new(name="MAT_Beam_Outer_Sheath")
    mat_beam_outer.use_nodes = True
    nodes = mat_beam_outer.node_tree.nodes
    links = mat_beam_outer.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    mix = nodes.new('ShaderNodeMixShader')
    trans = nodes.new('ShaderNodeBsdfTransparent')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = COLOR_AMBER
    em.inputs['Strength'].default_value = 8.0
    layer = nodes.new('ShaderNodeLayerWeight')
    layer.inputs['Blend'].default_value = 0.35
    links.new(layer.outputs['Facing'], mix.inputs['Fac'])
    links.new(trans.outputs['BSDF'], mix.inputs[1])
    links.new(em.outputs['Emission'], mix.inputs[2])
    links.new(mix.outputs['Shader'], out_node.inputs['Surface'])
    materials['beam_outer'] = mat_beam_outer

    # 8. Rolling Cumulus Clouds PBR (Soft stormy overcast clouds catching ambient light)
    mat_cloud = bpy.data.materials.new(name="MAT_Cumulus_Cloud_PBR")
    mat_cloud.use_nodes = True
    nodes = mat_cloud.node_tree.nodes
    links = mat_cloud.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.13, 0.16, 0.20, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.90
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['cloud_pbr'] = mat_cloud

    # 9. Human Scale Silhouette (Matte black scale reference)
    mat_human = bpy.data.materials.new(name="MAT_Human_Silhouette_Black")
    mat_human.use_nodes = True
    nodes = mat_human.node_tree.nodes
    links = mat_human.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.005, 0.006, 0.008, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.95
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['human_silhouette'] = mat_human

    # 10. Distant Towers (Atmospheric misty obsidian catching sky depth)
    mat_tower = bpy.data.materials.new(name="MAT_Distant_Tower_Obsidian")
    mat_tower.use_nodes = True
    nodes = mat_tower.node_tree.nodes
    links = mat_tower.node_tree.links
    nodes.clear()
    out_node = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = COLOR_TOWER_DISTANT
    bsdf.inputs['Metallic'].default_value = 0.65
    bsdf.inputs['Roughness'].default_value = 0.45
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    materials['distant_tower'] = mat_tower

    return materials

# ---------------------------------------------------------------------------
# 1. IMPORT CENTRAL ARYAOS CORE ASSET
# ---------------------------------------------------------------------------

def import_central_core(core_col, materials):
    """Imports the authoritative aryaos-core.glb asset and positions it atop dais."""
    print(f"Importing central Core GLB from: {GLB_SOURCE_PATH}")
    if not os.path.exists(GLB_SOURCE_PATH):
        raise FileNotFoundError(f"Missing core GLB at {GLB_SOURCE_PATH}")

    prior_objects = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=GLB_SOURCE_PATH)
    new_objects = [bpy.data.objects[name] for name in bpy.data.objects.keys() if name not in prior_objects]

    # Create root empty anchor for Core
    core_root = bpy.data.objects.new("ARYAOS_CORE_ROOT", None)
    core_root.empty_display_type = 'ARROWS'
    core_root.empty_display_size = 1.0
    core_root.location = (0, 0, 1.30)
    core_col.objects.link(core_root)

    for obj in new_objects:
        link_to_collection(obj, core_col)
        if obj.parent is None:
            obj.parent = core_root

        # Normalize materials to ensure visual cohesion with the environment
        if obj.type == 'MESH':
            for slot in obj.material_slots:
                if slot.material:
                    mat_name = slot.material.name.lower()
                    if 'amber' in mat_name or 'emissive' in mat_name or 'energy' in mat_name:
                        slot.material = materials['amber_energy']
                    elif 'cyan' in mat_name or 'telemetry' in mat_name or 'sensor' in mat_name:
                        slot.material = materials['cyan_telemetry']
                    elif 'titanium' in mat_name:
                        slot.material = materials['titanium']
                    elif 'obsidian' in mat_name:
                        slot.material = materials['obsidian_beveled']

    print(f"Imported {len(new_objects)} Core objects into {core_col.name}.")
    return core_root

# ---------------------------------------------------------------------------
# 2. MONUMENTAL CIRCULAR PLATFORM ARCHITECTURE
# ---------------------------------------------------------------------------

def build_monumental_platform(platform_col, materials):
    """
    Builds the colossal circular obsidian platform matching the Awakening artwork:
    - 3 stepped outer terrace rings descending into clouds
    - Main obsidian platform deck with recessed concentric & radial channels
    - Multi-tiered central octagonal dais elevating the Core
    - 24 fine architectural vertical louvers hugging dais perimeter
    """
    # 2A. Main Platform Deck (Radius 22.0m, Height 2.0m, Top surface at z=0.0)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=128,
        radius=22.0,
        depth=2.0,
        location=(0, 0, -1.0)
    )
    main_deck = bpy.context.active_object
    main_deck.name = "Platform_Main_Obsidian_Deck"
    main_deck.data.materials.append(materials['obsidian'])
    link_to_collection(main_deck, platform_col)

    # 2B. Stepped Outer Rim Terraces (Descending 3 concentric stairs)
    # Tier 1: Radius 23.5m, Top at z=-0.35m
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=128,
        radius=23.5,
        depth=1.8,
        location=(0, 0, -1.25)
    )
    step1 = bpy.context.active_object
    step1.name = "Platform_Outer_Step_Tier1"
    step1.data.materials.append(materials['obsidian_beveled'])
    link_to_collection(step1, platform_col)

    # Tier 2: Radius 24.8m, Top at z=-0.75m
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=128,
        radius=24.8,
        depth=1.6,
        location=(0, 0, -1.55)
    )
    step2 = bpy.context.active_object
    step2.name = "Platform_Outer_Step_Tier2"
    step2.data.materials.append(materials['obsidian_beveled'])
    link_to_collection(step2, platform_col)

    # Tier 3: Radius 26.2m, Top at z=-1.20m
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=128,
        radius=26.2,
        depth=1.4,
        location=(0, 0, -1.90)
    )
    step3 = bpy.context.active_object
    step3.name = "Platform_Outer_Step_Tier3"
    step3.data.materials.append(materials['obsidian_beveled'])
    link_to_collection(step3, platform_col)

    # 2C. Multi-tiered Central Octagonal Dais
    # Dais Tier 1 (Base octagonal plinth, radius 2.85m, height 0.45m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=2.85,
        depth=0.45,
        location=(0, 0, 0.225)
    )
    dais1 = bpy.context.active_object
    dais1.name = "Dais_Plinth_Tier1"
    dais1.data.materials.append(materials['obsidian_beveled'])
    link_to_collection(dais1, platform_col)

    # Dais Tier 2 (Middle octagonal plinth, radius 2.40m, height 0.45m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=2.40,
        depth=0.45,
        location=(0, 0, 0.675)
    )
    dais2 = bpy.context.active_object
    dais2.name = "Dais_Plinth_Tier2"
    dais2.data.materials.append(materials['obsidian'])
    link_to_collection(dais2, platform_col)

    # Dais Tier 3 (Upper core mounting ring, radius 1.95m, height 0.40m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=1.95,
        depth=0.40,
        location=(0, 0, 1.10)
    )
    dais3 = bpy.context.active_object
    dais3.name = "Dais_Plinth_Tier3"
    dais3.data.materials.append(materials['obsidian_beveled'])
    link_to_collection(dais3, platform_col)

    # 2D. Dais Recessed Amber Glow Rings
    for z_pos, r_glow in [(0.45, 2.42), (0.90, 1.96)]:
        bpy.ops.mesh.primitive_torus_add(
            major_radius=r_glow,
            minor_radius=0.020,
            location=(0, 0, z_pos)
        )
        glow_ring = bpy.context.active_object
        glow_ring.name = f"Dais_Amber_Glow_Ring_z{int(z_pos*100)}"
        glow_ring.data.materials.append(materials['amber_energy'])
        link_to_collection(glow_ring, platform_col)

    # 2E. Fine Architectural Vertical Louvers (24 fins hugging dais perimeter)
    for i in range(24):
        ang = (i * 15) * (math.pi / 180.0)
        bx = math.cos(ang) * 2.75
        by = math.sin(ang) * 2.75
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(bx, by, 0.45)
        )
        fin = bpy.context.active_object
        fin.scale = (0.05, 0.14, 0.80)
        fin.rotation_euler = (0, 0, ang)
        fin.name = f"Dais_Louver_{i+1:02d}"
        fin.data.materials.append(materials['titanium'])
        link_to_collection(fin, platform_col)

    return main_deck

# ---------------------------------------------------------------------------
# 3. RECESSED CONDUIT GROOVES & ILLUMINATED ENERGY TRACKS
# ---------------------------------------------------------------------------

def build_conduits_and_tracks(conduits_col, materials):
    """
    Creates concentric and radial recessed illuminated conduits in the platform floor:
    - Restrained amber energy ribbons casting warm luminescence across obsidian deck
    - Cyan telemetry indexing tracks
    """
    CONCENTRIC_RINGS = [
        ("Ring_Inner_Amber_Energy", 3.8, 0.016, materials['amber_energy']),
        ("Ring_Cyan_Intelligence_Track", 7.2, 0.014, materials['cyan_telemetry']),
        ("Ring_Mid_Amber_Energy", 11.5, 0.018, materials['amber_energy']),
        ("Ring_Cyan_Orbital_Bus", 16.2, 0.015, materials['cyan_telemetry']),
        ("Ring_Outer_Amber_Boundary", 20.8, 0.020, materials['amber_energy']),
    ]

    for name, rad, thickness, mat in CONCENTRIC_RINGS:
        # Recessed emission ring ribbon (Refined, thin trace)
        bpy.ops.mesh.primitive_torus_add(
            major_radius=rad,
            minor_radius=thickness,
            major_segments=128,
            minor_segments=8,
            location=(0, 0, 0.006)
        )
        ring_obj = bpy.context.active_object
        ring_obj.name = name
        ring_obj.data.materials.append(mat)
        link_to_collection(ring_obj, conduits_col)

        # Titanium channel lip framing each luminous ring
        bpy.ops.mesh.primitive_torus_add(
            major_radius=rad + thickness * 1.5,
            minor_radius=thickness * 0.35,
            major_segments=128,
            minor_segments=6,
            location=(0, 0, 0.010)
        )
        lip = bpy.context.active_object
        lip.name = f"{name}_Channel_Lip"
        lip.data.materials.append(materials['titanium'])
        link_to_collection(lip, conduits_col)

    # 12 Radial Conduits linking dais to outer boundary (Circuit mandala)
    for i in range(12):
        angle = (i * 30) * (math.pi / 180.0)
        length = 17.5
        mid_r = 3.2 + length / 2.0
        cx = math.cos(angle) * mid_r
        cy = math.sin(angle) * mid_r

        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(cx, cy, 0.005)
        )
        strip = bpy.context.active_object
        strip.scale = (0.035, length, 0.008)
        strip.rotation_euler = (0, 0, angle + math.pi / 2.0)
        strip.name = f"Radial_Energy_Track_{i+1:02d}"
        strip.data.materials.append(materials['amber_energy'] if i % 2 == 0 else materials['cyan_telemetry'])
        link_to_collection(strip, conduits_col)

# ---------------------------------------------------------------------------
# 4. SUBSYSTEM MODULE STATIONS (Symmetrically Framed, Sightlines Open)
# ---------------------------------------------------------------------------

MODULE_CONFIGS = [
    ("MOD-01", "MEMORY", 150),       # Rear-right
    ("MOD-02", "PLANNING", 210),     # Rear-left
    ("MOD-03", "ROUTING", 240),      # Mid-left (leaves 270 deg / -Y wide open!)
    ("MOD-04", "ANALYTICS", 300),    # Mid-right (leaves 270 deg / -Y wide open!)
    ("MOD-05", "JOB_PACKAGE", 30),   # Front-right
    ("MOD-06", "EXECUTION", 90),     # Far-right
]

def build_subsystem_modules(modules_col, materials):
    """Builds the 6 physical module stations around platform perimeter at r=19.2m."""
    radius = 19.2

    for code, label, deg in MODULE_CONFIGS:
        rad = deg * (math.pi / 180.0)
        px = math.cos(rad) * radius
        py = math.sin(rad) * radius

        # Pedestal base
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=8,
            radius=1.1,
            depth=0.45,
            location=(px, py, 0.225)
        )
        base = bpy.context.active_object
        base.name = f"{code}_{label}_Station_Base"
        base.data.materials.append(materials['obsidian_beveled'])
        link_to_collection(base, modules_col)

        # Monolithic computational pylon
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(px, py, 1.25)
        )
        pylon = bpy.context.active_object
        pylon.scale = (0.65, 0.65, 1.6)
        pylon.rotation_euler = (0, 0, rad + math.pi)
        pylon.name = f"{code}_{label}_Pylon"
        pylon.data.materials.append(materials['obsidian'])
        link_to_collection(pylon, modules_col)

        # Titanium top cap
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=8,
            radius=0.70,
            depth=0.18,
            location=(px, py, 2.15)
        )
        cap = bpy.context.active_object
        cap.name = f"{code}_{label}_Top_Cap"
        cap.data.materials.append(materials['titanium'])
        link_to_collection(cap, modules_col)

        # Telemetry beacon slot
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(px, py, 1.4)
        )
        slit = bpy.context.active_object
        slit.scale = (0.68, 0.08, 0.18)
        slit.rotation_euler = (0, 0, rad + math.pi)
        slit.name = f"{code}_{label}_Telemetry_Slit"
        slit.data.materials.append(materials['cyan_telemetry'])
        link_to_collection(slit, modules_col)

# ---------------------------------------------------------------------------
# 5. HUMAN SCALE SILHOUETTE (Anchoring Monumental Scale)
# ---------------------------------------------------------------------------

def build_human_silhouette(human_col, materials):
    """
    Constructs a 1.80m tall human silhouette standing on the platform.
    Positioned gracefully on the left flank at (-5.8, -9.5, 0.0), looking AT the Core.
    Anchors colossal scale without obstructing the Core or cameras.
    """
    pos_x = -5.8
    pos_y = -9.5

    # Head
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.11,
        location=(pos_x, pos_y, 1.68)
    )
    head = bpy.context.active_object
    head.name = "Human_Silhouette_Head"
    head.data.materials.append(materials['human_silhouette'])
    link_to_collection(head, human_col)

    # Torso & Coat / Long Jacket
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.18,
        depth=0.75,
        location=(pos_x, pos_y, 1.15)
    )
    torso = bpy.context.active_object
    torso.name = "Human_Silhouette_Torso"
    torso.data.materials.append(materials['human_silhouette'])
    link_to_collection(torso, human_col)

    # Legs / Lower body
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.14,
        depth=0.78,
        location=(pos_x, pos_y, 0.40)
    )
    legs = bpy.context.active_object
    legs.name = "Human_Silhouette_Legs"
    legs.data.materials.append(materials['human_silhouette'])
    link_to_collection(legs, human_col)

    print(f"Created human scale silhouette at ({pos_x}, {pos_y}, 0.0)")

# ---------------------------------------------------------------------------
# 6. LOW-LYING BILLOWING CUMULUS CLOUD SEA
# ---------------------------------------------------------------------------

def build_cumulus_cloud_sea(cloud_col, materials):
    """
    Constructs the dense ocean of billowing cumulus clouds lying beneath the floating platform.
    The tops of the clouds stay below the platform rim (z = -1.5m to -3.0m),
    allowing the platform to appear floating high in the atmosphere above the clouds.
    """
    cloud_tex = bpy.data.textures.new("CloudDisplaceNoise", type='CLOUDS')
    cloud_tex.noise_scale = 1.25
    cloud_tex.noise_depth = 4

    # 16 Displaced Cumulus Billow Clusters along perimeter (centers at z = -8.0m to -10.0m)
    cloud_clusters = [
        (28.0, 18.0, -8.5, 14.0, (1.5, 1.5, 0.65), 3.5),
        (-27.0, 19.0, -8.8, 15.0, (1.5, 1.5, 0.65), 3.6),
        (34.0, -10.0, -8.2, 13.0, (1.4, 1.4, 0.60), 3.2),
        (-33.0, -8.0, -8.4, 14.5, (1.4, 1.4, 0.60), 3.4),
        (16.0, 38.0, -9.0, 18.0, (1.6, 1.6, 0.70), 4.2),
        (-18.0, 37.0, -8.8, 17.5, (1.6, 1.6, 0.70), 4.0),
        (0.0, 45.0, -9.5, 22.0, (1.8, 1.8, 0.75), 4.8),
        (26.0, -25.0, -8.0, 12.5, (1.4, 1.4, 0.55), 3.0),
        (-25.0, -26.0, -8.2, 13.0, (1.4, 1.4, 0.55), 3.2),
        (48.0, 15.0, -9.8, 20.0, (1.7, 1.7, 0.70), 4.5),
        (-46.0, 18.0, -9.6, 21.0, (1.7, 1.7, 0.70), 4.6),
        (42.0, -30.0, -9.2, 16.0, (1.5, 1.5, 0.60), 3.8),
        (-40.0, -32.0, -9.0, 17.0, (1.5, 1.5, 0.60), 4.0),
        (0.0, -42.0, -8.6, 15.0, (1.5, 1.5, 0.60), 3.5),
        (58.0, 45.0, -11.0, 26.0, (1.9, 1.9, 0.80), 5.5),
        (-56.0, 48.0, -10.8, 25.0, (1.9, 1.9, 0.80), 5.2),
    ]

    for idx, (cx, cy, cz, radius, scale, disp_strength) in enumerate(cloud_clusters):
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=3,
            radius=radius,
            location=(cx, cy, cz)
        )
        c_obj = bpy.context.active_object
        c_obj.name = f"Cumulus_Billow_{idx+1:02d}"
        c_obj.scale = scale
        c_obj.data.materials.append(materials['cloud_pbr'])

        mod = c_obj.modifiers.new("CloudDisplace", 'DISPLACE')
        mod.texture = cloud_tex
        mod.strength = disp_strength
        mod.texture_coords = 'LOCAL'

        for f in c_obj.data.polygons:
            f.use_smooth = True

        link_to_collection(c_obj, cloud_col)

    # Continuous Cloud Sea Bed Plane (Extending 350m x 350m at z = -7.0m)
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=64,
        y_subdivisions=64,
        size=350.0,
        location=(0, 25.0, -7.0)
    )
    bed = bpy.context.active_object
    bed.name = "Continuous_Cloud_Sea_Bed"
    bed.data.materials.append(materials['cloud_pbr'])

    mod_bed = bed.modifiers.new("BedDisplace", 'DISPLACE')
    mod_bed.texture = cloud_tex
    mod_bed.strength = 5.5
    for f in bed.data.polygons:
        f.use_smooth = True

    link_to_collection(bed, cloud_col)

# ---------------------------------------------------------------------------
# 7. PROCEDURAL STORMY OVERCAST SKY DOME (Broad, Majestic Cloud Swirls)
# ---------------------------------------------------------------------------

def build_stormy_sky_dome(arch_col):
    """
    Constructs an inverted procedural stormy sky dome encompassing the horizon.
    Uses calibrated large-scale noise (Scale=0.009) to form sweeping stormy cloud masses.
    """
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=280.0,
        location=(0, 20.0, 0)
    )
    dome = bpy.context.active_object
    dome.name = "Sky_Dome_Stormy_Atmosphere"

    mat = bpy.data.materials.new("MAT_Stormy_Sky_Dome")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out_node = nodes.new('ShaderNodeOutputMaterial')
    em = nodes.new('ShaderNodeEmission')

    coord = nodes.new('ShaderNodeTexCoord')
    
    noise = nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 0.009
    noise.inputs['Detail'].default_value = 6.0
    noise.inputs['Roughness'].default_value = 0.60

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.20
    ramp.color_ramp.elements[0].color = (0.018, 0.022, 0.032, 1.0)  # Deep dark storm cloud
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = (0.085, 0.105, 0.145, 1.0)  # Mid overcast slate gray
    elem = ramp.color_ramp.elements.new(0.88)
    elem.color = (0.190, 0.230, 0.300, 1.0)                         # Atmospheric cloud crest highlight

    links.new(coord.outputs['Object'], noise.inputs['Vector'])
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], em.inputs['Color'])
    em.inputs['Strength'].default_value = 1.30
    links.new(em.outputs['Emission'], out_node.inputs['Surface'])

    dome.data.materials.append(mat)

    # Invert polygons so dome is visible from inside
    for poly in dome.data.polygons:
        poly.flip()
    dome.data.update()

    link_to_collection(dome, arch_col)

# ---------------------------------------------------------------------------
# 8. DISTANT MEGASTRUCTURE ARCHITECTURE & FLOATING MONOLITHS
# ---------------------------------------------------------------------------

def build_distant_megastructures(arch_col, materials):
    """
    Constructs the monumental distant citadel spire, flanking towers,
    and floating obsidian monoliths matching the Awakening artwork.
    """
    # 8A. Central Monolithic Citadel Spire (Directly behind Core, rising to 135m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=13.0,
        depth=135.0,
        location=(0, 110.0, 58.0)
    )
    citadel = bpy.context.active_object
    citadel.name = "Citadel_Central_Colossus_Spire"
    citadel.data.materials.append(materials['distant_tower'])
    link_to_collection(citadel, arch_col)

    # Central Citadel Amber Reactor Slit
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, 96.5, 50.0)
    )
    slit = bpy.context.active_object
    slit.scale = (1.2, 0.35, 75.0)
    slit.name = "Citadel_Amber_Reactor_Core_Slit"
    slit.data.materials.append(materials['amber_energy'])
    link_to_collection(slit, arch_col)

    # 8B. Flanking Colossal Spire Towers
    flank_towers = [
        ("Left_Spire_01", -42.0, 80.0, 38.0, 9.0, 90.0),
        ("Right_Spire_01", 45.0, 84.0, 40.0, 9.5, 95.0),
        ("Left_Spire_Deep", -72.0, 128.0, 48.0, 11.0, 110.0),
        ("Right_Spire_Deep", 68.0, 122.0, 46.0, 10.5, 105.0),
    ]

    for name, tx, ty, tz, rad, height in flank_towers:
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=6,
            radius=rad,
            depth=height,
            location=(tx, ty, tz)
        )
        tower = bpy.context.active_object
        tower.name = f"Tower_{name}"
        tower.data.materials.append(materials['distant_tower'])
        link_to_collection(tower, arch_col)

        # Cyan beacon dot atop each tower
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.9,
            location=(tx, ty - rad + 0.4, tz + height / 2.0 - 4.0)
        )
        beacon = bpy.context.active_object
        beacon.name = f"Tower_{name}_Beacon"
        beacon.data.materials.append(materials['cyan_telemetry'])
        link_to_collection(beacon, arch_col)

    # 8C. Floating Obsidian Monoliths (Weightless shards hovering over cloud sea)
    monolith_coords = [
        ("Monolith_Floating_L1", -26.0, 32.0, 24.0, (1.8, 2.2, 16.0), (0.12, 0.18, 0.35)),
        ("Monolith_Floating_L2", -38.0, 52.0, 18.0, (2.2, 2.4, 20.0), (-0.15, 0.12, -0.25)),
        ("Monolith_Floating_R1", 28.0, 34.0, 26.0, (2.0, 2.0, 18.0), (-0.14, 0.16, -0.32)),
        ("Monolith_Floating_R2", 42.0, 56.0, 20.0, (2.4, 2.6, 22.0), (0.18, -0.10, 0.40)),
        ("Monolith_Low_L", -18.0, 22.0, 7.5, (1.4, 1.4, 9.0), (0.08, 0.22, 0.15)),
        ("Monolith_Low_R", 20.0, 24.0, 8.5, (1.5, 1.5, 10.0), (-0.10, 0.18, -0.22)),
    ]

    for name, mx, my, mz, scale, rot in monolith_coords:
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=4,
            radius=1.0,
            depth=1.0,
            location=(mx, my, mz)
        )
        m = bpy.context.active_object
        m.scale = scale
        m.rotation_euler = rot
        m.name = name
        m.data.materials.append(materials['obsidian_beveled'])
        link_to_collection(m, arch_col)

        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(mx, my - scale[1] * 0.45, mz)
        )
        accent = bpy.context.active_object
        accent.scale = (0.20, 0.10, 1.0)
        accent.rotation_euler = rot
        accent.name = f"{name}_Sensor"
        accent.data.materials.append(materials['cyan_telemetry'])
        link_to_collection(accent, arch_col)

# ---------------------------------------------------------------------------
# 9. CENTRAL VERTICAL AMBER ENERGY PILLAR & CINEMATIC LIGHTING
# ---------------------------------------------------------------------------

def build_energy_pillar_and_lighting(lights_col, materials):
    """
    Constructs the soaring vertical amber energy beam and high-contrast cinematic lighting rig:
    - Vertical beam starts ABOVE the Core (z = 2.45m to 140m), revealing the Core asset cleanly
    - Inner focused bright core + outer transparent facing halo sheath
    - Upward beam spotlight casting soft volumetric shaft
    - Warm key daylight filtering from upper right
    - Electric cyan rim lights separating silhouettes from dark void
    - Restrained amber floor bounce
    """
    beam_bottom_z = 2.45
    beam_top_z = 140.0
    beam_length = beam_top_z - beam_bottom_z
    beam_center_z = beam_bottom_z + beam_length / 2.0

    # 9A. Central Vertical Beam: Inner Focused Core (Radius 0.08m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=0.08,
        depth=beam_length,
        location=(0, 0, beam_center_z)
    )
    beam_core = bpy.context.active_object
    beam_core.name = "Central_Energy_Beam_Core"
    beam_core.data.materials.append(materials['beam_core'])
    link_to_collection(beam_core, lights_col)

    # 9B. Central Vertical Beam: Outer Luminous Halo (Radius 0.24m)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=0.24,
        depth=beam_length,
        location=(0, 0, beam_center_z)
    )
    beam_sheath = bpy.context.active_object
    beam_sheath.name = "Central_Energy_Beam_Sheath"
    beam_sheath.data.materials.append(materials['beam_outer'])
    link_to_collection(beam_sheath, lights_col)

    # 9C. Core Vertical Upward Beam Spotlight
    bpy.ops.object.light_add(
        type='SPOT',
        location=(0, 0, 2.50)
    )
    spot = bpy.context.active_object
    spot.name = "LIGHT_Core_Vertical_Beam_Spot"
    spot.data.energy = 2200.0
    spot.data.color = (1.0, 0.72, 0.22)
    spot.data.spot_size = 0.22
    spot.data.spot_blend = 0.70
    spot.rotation_euler = (math.pi, 0, 0)
    link_to_collection(spot, lights_col)

    # 9D. High-Angle Key Sun (Warm diffused golden daylight)
    bpy.ops.object.light_add(
        type='SUN',
        location=(25.0, -20.0, 45.0)
    )
    sun = bpy.context.active_object
    sun.name = "LIGHT_Key_Sun_Atmospheric"
    sun.data.energy = 4.2
    sun.data.color = (1.0, 0.90, 0.78)
    sun.data.angle = 0.20
    sun.rotation_euler = (0.75, 0.25, -0.60)
    link_to_collection(sun, lights_col)

    # 9E. Dual Electric Cyan Rim Lights (Left and Right background separation)
    for name, lx, ly, lz, rot in [
        ("LIGHT_Cyan_Rim_Left", -28.0, 32.0, 14.0, (0.85, 0.35, 2.3)),
        ("LIGHT_Cyan_Rim_Right", 28.0, 32.0, 14.0, (0.85, -0.35, -2.3)),
    ]:
        bpy.ops.object.light_add(
            type='AREA',
            location=(lx, ly, lz)
        )
        rim = bpy.context.active_object
        rim.name = name
        rim.data.energy = 380.0
        rim.data.color = (0.04, 0.80, 0.98)
        rim.data.size = 12.0
        rim.rotation_euler = rot
        link_to_collection(rim, lights_col)

    # 9F. Low-Angle Amber Floor Bounce Light
    bpy.ops.object.light_add(
        type='POINT',
        location=(0, -2.5, 0.40)
    )
    bounce = bpy.context.active_object
    bounce.name = "LIGHT_Amber_Floor_Bounce"
    bounce.data.energy = 180.0
    bounce.data.color = (1.0, 0.55, 0.08)
    link_to_collection(bounce, lights_col)

# ---------------------------------------------------------------------------
# 10. CINEMATIC CAMERAS CONFIGURATION (Precision Look-At Framing)
# ---------------------------------------------------------------------------

def look_at(obj, target_vec):
    """Orients object -Z towards target with +Y up."""
    direction = Vector(target_vec) - obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    obj.rotation_euler = rot_quat.to_euler()

def setup_cinematic_cameras(cameras_col):
    """
    Configures the 3 authoritative cinematic cameras with exact target tracking:
    1. CAM_CinematicHero (Wide establishing hero composition, 32mm)
    2. CAM_MonumentalLowAngle (Low-angle colossal architectural perspective, 24mm)
    3. CAM_PlatformDetail (Intimate focus on central dais & Core details, 50mm)
    """
    cameras = {}

    def add_cam(name, loc, target_loc, focal_length):
        cam_data = bpy.data.cameras.new(name=name)
        cam_data.lens = focal_length
        cam_data.clip_start = 0.1
        cam_data.clip_end = 500.0
        cam_obj = bpy.data.objects.new(name=name, object_data=cam_data)
        cam_obj.location = loc
        look_at(cam_obj, target_loc)
        cameras_col.objects.link(cam_obj)
        cameras[name] = cam_obj
        return cam_obj

    # Camera 1: Cinematic Hero (Wide/Medium establishing hero shot, 32mm)
    # Framed wide: Central Core, glowing conduits, human silhouette on left third, cloud sea
    add_cam(
        "CAM_CinematicHero",
        loc=(0.0, -23.5, 4.0),
        target_loc=(0.0, 0.0, 3.2),
        focal_length=32.0
    )

    # Camera 2: Monumental Low Angle (Dramatic colossal architectural scale, 24mm)
    # Ground level at (3.5, -13.5, 1.1), gazing directly UP at Core center (0, 0, 4.2)
    add_cam(
        "CAM_MonumentalLowAngle",
        loc=(3.5, -13.5, 1.1),
        target_loc=(0.0, 0.0, 4.2),
        focal_length=24.0
    )

    # Camera 3: Platform Detail (Technical calibration rings & core dais detail, 50mm)
    # Tightly framed on central dais, aryaos-core.glb gimbal rings, and inner glow track
    add_cam(
        "CAM_PlatformDetail",
        loc=(5.5, -9.5, 2.2),
        target_loc=(0.0, 0.0, 1.7),
        focal_length=50.0
    )

    return cameras

# ---------------------------------------------------------------------------
# 11. WORLD ENVIRONMENT, EEVEE-NEXT RAYTRACING & COMPOSITOR BLOOM
# ---------------------------------------------------------------------------

def configure_render_settings_and_compositor(scene):
    """
    Configures Blender 5.2 EEVEE-Next raytracing and Compositor Bloom
    for cinematic anamorphic glow.
    """
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.compression = 15

    # EEVEE-Next Screen-Space Raytracing
    scene.eevee.use_raytracing = True
    scene.eevee.ray_tracing_method = 'SCREEN'
    scene.eevee.use_fast_gi = True
    scene.eevee.taa_render_samples = 64

    # World ambient lighting (Dark moody overcast sky fill)
    world = bpy.data.worlds.new("WORLD_Stage02_Ambient")
    scene.world = world
    world.use_nodes = True
    w_nodes = world.node_tree.nodes
    w_links = world.node_tree.links
    w_nodes.clear()

    w_out = w_nodes.new('ShaderNodeOutputWorld')
    w_bg = w_nodes.new('ShaderNodeBackground')
    w_bg.inputs['Color'].default_value = (0.045, 0.058, 0.080, 1.0)
    w_bg.inputs['Strength'].default_value = 1.25
    w_links.new(w_bg.outputs['Background'], w_out.inputs['Surface'])

    # Compositor Node Tree with Bloom Glare (Threshold isolates beam & reactor highlights)
    comp_ng = bpy.data.node_groups.new('Compositor_Bloom_Pipeline', 'CompositorNodeTree')
    scene.compositing_node_group = comp_ng

    rl = comp_ng.nodes.new('CompositorNodeRLayers')
    glare = comp_ng.nodes.new('CompositorNodeGlare')
    glare.inputs['Type'].default_value = 'Bloom'
    glare.inputs['Threshold'].default_value = 1.8
    glare.inputs['Strength'].default_value = 0.25
    glare.inputs['Size'].default_value = 8

    out_node = comp_ng.nodes.new('NodeGroupOutput')
    comp_ng.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')

    comp_ng.links.new(rl.outputs['Image'], glare.inputs['Image'])
    comp_ng.links.new(glare.outputs['Image'], out_node.inputs['Image'])

def render_camera_view(camera_obj, output_path):
    """Renders a specific camera view and saves image file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scene = bpy.context.scene
    scene.camera = camera_obj
    scene.render.filepath = output_path
    print(f"Rendering camera [{camera_obj.name}] to: {output_path} ...")
    bpy.ops.render.render(write_still=True)
    print(f"Successfully generated: {output_path}")

# ---------------------------------------------------------------------------
# MAIN EXECUTION ORCHESTRATION
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("ARYAOS V1 — STAGE 02 CORE ENVIRONMENT BLENDER BUILDER (V6 - PRECISION)")
    print("=" * 70)

    # 1. Clear & Init Scene
    scene = clear_scene()

    # 2. Setup Collection Hierarchy
    master_col = scene.collection
    core_col = create_collection("01_CENTRAL_CORE", master_col)
    platform_col = create_collection("02_MONUMENTAL_PLATFORM", master_col)
    conduits_col = create_collection("03_CONDUITS_AND_TRACKS", master_col)
    modules_col = create_collection("04_SUBSYSTEM_MODULE_STATIONS", master_col)
    human_col = create_collection("05_HUMAN_SCALE_SILHOUETTE", master_col)
    cloud_col = create_collection("06_CUMULUS_CLOUD_SEA", master_col)
    arch_col = create_collection("07_DISTANT_MEGASTRUCTURES", master_col)
    lights_col = create_collection("08_ENERGY_BEAM_AND_LIGHTING", master_col)
    cameras_col = create_collection("09_CAMERAS", master_col)

    # 3. Create Procedural Shader Library
    materials = create_materials()

    # 4. Import Authoritative AryaOS Core Asset (Public GLB untouched)
    import_central_core(core_col, materials)

    # 5. Build Colossal Circular Obsidian Platform
    build_monumental_platform(platform_col, materials)

    # 6. Build Concentric & Radial Illuminated Conduits
    build_conduits_and_tracks(conduits_col, materials)

    # 7. Build 6 Subsystem Module Stations (Framing, sightlines open)
    build_subsystem_modules(modules_col, materials)

    # 8. Build Human Scale Silhouette (Rule of Thirds scale anchor)
    build_human_silhouette(human_col, materials)

    # 9. Build Low-Lying Billowing Cumulus Cloud Sea
    build_cumulus_cloud_sea(cloud_col, materials)

    # 10. Build Procedural Stormy Sky Dome (Calibrated scale)
    build_stormy_sky_dome(arch_col)

    # 11. Build Distant Megastructures & Floating Monoliths
    build_distant_megastructures(arch_col, materials)

    # 12. Build Central Vertical Amber Energy Pillar & Lighting Rig
    build_energy_pillar_and_lighting(lights_col, materials)

    # 13. Setup Cameras (With exact look-at tracking)
    cameras = setup_cinematic_cameras(cameras_col)

    # 14. Configure Render Engine & Compositor Bloom
    configure_render_settings_and_compositor(scene)

    # 15. Save Master .blend Scene (With world & render settings fully configured)
    os.makedirs(os.path.dirname(BLEND_EXPORT_PATH), exist_ok=True)
    print(f"\nSaving master Blender scene to: {BLEND_EXPORT_PATH} ...")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_EXPORT_PATH)
    print(f"Master scene successfully saved: {BLEND_EXPORT_PATH}")

    # 16. Render 3 High-Resolution Reference Stills
    render_camera_view(cameras["CAM_CinematicHero"], RENDER_HERO_PATH)
    render_camera_view(cameras["CAM_MonumentalLowAngle"], RENDER_LOW_ANGLE_PATH)
    render_camera_view(cameras["CAM_PlatformDetail"], RENDER_DETAIL_PATH)

    # Copy renders to conversation artifact directory for visual inspection
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    for src_path, art_name in [
        (RENDER_HERO_PATH, "stage02_core_cinematic_hero.png"),
        (RENDER_LOW_ANGLE_PATH, "stage02_core_monumental_low_angle.png"),
        (RENDER_DETAIL_PATH, "stage02_core_platform_detail.png"),
    ]:
        dest_path = os.path.join(ARTIFACT_DIR, art_name)
        if os.path.exists(src_path):
            with open(src_path, "rb") as sf, open(dest_path, "wb") as df:
                df.write(sf.read())
            print(f"Copied render artifact: {dest_path}")

    print("\n" + "=" * 70)
    print("STAGE 02 CORE BLENDER ENVIRONMENT BUILD COMPLETE!")
    print("=" * 70)

if __name__ == "__main__":
    main()
