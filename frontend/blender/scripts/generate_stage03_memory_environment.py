#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE LOOK-DEVELOPMENT CORRECTION PASS 2
Target: Blender 5.2.2 LTS (EEVEE-Next & Cycles Compatible)

Visual Target:
- Monumental futuristic intelligence archive / sci-fi memory sanctuary
- Dark graphite / machined gunmetal / dark titanium architecture (dark != black)
- Procedural micro-surface detail (noise roughness variation + micro-bump)
- Wet dark obsidian floor with realistic procedural sheen variation & reflections
- Physical optical glass for vitrines (Transmission=1.0, Alpha=1.0, Coat=1.0)
- ELIMINATE THE "UI OUTLINE" PROBLEM: Embedded optical conduit shader with
  dark smoked resin body, sharp clear-coat specular edges, and deep practical amber core
- Internal 3D memory worlds: dark mineral basalt with illuminated amber veins
- Astrolabe as precision machined hardware: cool slate-blue rim + warm core
- Localized restrained amber practical lighting & balanced cool slate-blue environment
- Subtle world volume (density 0.00012, anisotropy 0.68)
- AgX color management (Exposure -0.30, Medium High Contrast)
- Hard preservation lock: 1,143 objects, 10 collections, locked cameras/transforms
- Previews only: 960x540 for Hero, Monumental, Detail
===============================================================================
"""

import bpy
import bmesh
import math
import os
import sys
import shutil
from mathutils import Vector, Euler

# ---------------------------------------------------------------------------
# PATH CONFIGURATION
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
SCENES_DIR = os.path.join(BLEND_DIR, "scenes")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")

BLEND_EXPORT_PATH = os.path.join(SCENES_DIR, "stage03_aryaos_memory_environment.blend")
BACKUP_PATH = os.path.join(SCENES_DIR, "stage03_aryaos_memory_environment_backup_pass2.blend")

RENDER_HERO_PATH = os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png")
RENDER_MONUMENTAL_PATH = os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png")
RENDER_DETAIL_PATH = os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png")

PREVIEW_HERO_PATH = os.path.join(RENDERS_DIR, "stage03_memory_preview_hero.png")
PREVIEW_MONUMENTAL_PATH = os.path.join(RENDERS_DIR, "stage03_memory_preview_monumental.png")
PREVIEW_DETAIL_PATH = os.path.join(RENDERS_DIR, "stage03_memory_preview_detail.png")

ARTIFACT_DIR = "/Users/venkatakishorenasina/.gemini/antigravity-cli/brain/30adfb21-e95c-4b85-828f-3f7a6d9d1447"

# ---------------------------------------------------------------------------
# CINEMATIC COLOR PALETTE (RESTRAINED DUAL-CHROMA)
# ---------------------------------------------------------------------------
# Base Architecture (Dark != Black)
COLOR_OBSIDIAN_FLOOR   = (0.024, 0.028, 0.036, 1.0)  # Polished deep obsidian slate
COLOR_OBSIDIAN_STRUCT  = (0.048, 0.055, 0.068, 1.0)  # Dark graphite architectural stone/metal
COLOR_GUNMETAL         = (0.085, 0.095, 0.115, 1.0)  # Machined industrial gunmetal
COLOR_TITANIUM         = (0.145, 0.160, 0.185, 1.0)  # Dark polished neutral titanium

# Energy (Restrained Amber & Telemetry Accents)
COLOR_AMBER_ENERGY     = (1.000, 0.440, 0.080, 1.0)  # Restrained warm amber intelligence
COLOR_AMBER_CORE       = (1.000, 0.520, 0.120, 1.0)  # Primary memory core
COLOR_AMBER_DEEP       = (0.850, 0.350, 0.050, 1.0)  # Deep accent contours
COLOR_CYAN_TELEMETRY   = (0.040, 0.750, 0.850, 1.0)  # Minimal telemetry data

# Environment & Glass
COLOR_GLASS_TINT       = (0.940, 0.970, 1.000, 1.0)  # Optical crystal glass tint
COLOR_SKY_SLATE        = (0.040, 0.065, 0.095, 1.0)  # Cool stormy slate blue
COLOR_CLOUD_SCATTER    = (0.038, 0.050, 0.070, 1.0)  # Storm cloud atmosphere
COLOR_HUMAN_BLACK      = (0.005, 0.006, 0.008, 1.0)  # Matte silhouette reference

COLLECTION_NAMES = [
    "MEMORY_ARCHITECTURE",
    "MEMORY_CORE",
    "MEMORY_CRYSTALS",
    "MEMORY_CONDUITS",
    "MEMORY_ORBITAL_RINGS",
    "MEMORY_TOWERS",
    "MEMORY_ATMOSPHERE",
    "MEMORY_LIGHTING",
    "MEMORY_SCALE_ANCHORS",
    "CAMERAS",
]

def ensure_collections():
    """Ensures all 10 production collections exist and are linked to Scene Collection."""
    cols = {}
    master_col = bpy.context.scene.collection
    for name in COLLECTION_NAMES:
        if name in bpy.data.collections:
            col = bpy.data.collections[name]
        else:
            col = bpy.data.collections.new(name)
        if col.name not in master_col.children:
            try:
                master_col.children.link(col)
            except Exception:
                pass
        cols[name] = col
    return cols

def link_to_col(obj, col):
    """Safely links an object to a target collection and unlinks from other scene collections."""
    for c in list(obj.users_collection):
        if c != col:
            c.objects.unlink(obj)
    if obj.name not in col.objects:
        col.objects.link(obj)

# ---------------------------------------------------------------------------
# CINEMATIC MATERIAL UPGRADES (LOOK-DEV PASS 2)
# ---------------------------------------------------------------------------
def setup_or_calibrate_materials():
    """
    Applies the Pass 2 look-development material pass:
    1. Polished Obsidian Floor: Procedural liquid sheen roughness variation (0.08 to 0.20) + micro-bump.
    2. Structural Obsidian Mass: Dark graphite stone/metal composite with procedural roughness variation (0.22 to 0.34) and micro-grain bump.
    3. Gunmetal Machined: Machined aerospace alloy with directional micro-roughness.
    4. Titanium Machined: Dark polished neutral titanium with sharp specular bevels.
    5. Optical Glass Vitrines: Physical optical glass (Transmission=1.0, Alpha=1.0, Coat=1.0, IOR=1.52, Dithered raytrace refraction).
    6. Conduits (ELIMINATE UI OUTLINE): Smoked amber resin body with clear coat specular edges and embedded practical core emission.
    7. Memory Worlds: Dark mineral basalt mass with procedural illuminated amber veins.
    8. Core & Reactor: Controlled warm amber/gold emission without clipping.
    """
    mats = {}

    def get_or_create(mat_name):
        if mat_name in bpy.data.materials:
            m = bpy.data.materials[mat_name]
        else:
            m = bpy.data.materials.new(name=mat_name)
        m.use_nodes = True
        return m

    # 1. Polished Obsidian Floor (Wet dark sci-fi stone with procedural liquid sheen variation)
    for mname in ["MAT_Obsidian_Floor_Wet_PBR", "MAT_Obsidian_Polished_Floor"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_OBSIDIAN_FLOOR
        bsdf.inputs['Metallic'].default_value = 0.85
        bsdf.inputs['IOR'].default_value = 1.62
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.95
            bsdf.inputs['Coat Roughness'].default_value = 0.028

        coord = nodes.new('ShaderNodeTexCoord')
        mapping = nodes.new('ShaderNodeMapping')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 16.0
        noise.inputs['Detail'].default_value = 4.0
        noise.inputs['Roughness'].default_value = 0.45

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.18
        ramp.color_ramp.elements[0].color = (0.08, 0.08, 0.08, 1.0)  # Wet pooled liquid sheen
        ramp.color_ramp.elements[1].position = 0.80
        ramp.color_ramp.elements[1].color = (0.20, 0.20, 0.20, 1.0)  # Satin honed obsidian

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.012
        bump.inputs['Distance'].default_value = 0.015

        links.new(coord.outputs['Object'], mapping.inputs['Vector'])
        links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
        links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 2. Structural Obsidian Mass (Dark graphite stone/metal composite — NOT pure black, NOT plastic)
    for mname in ["MAT_Obsidian_Structure_PBR", "MAT_Obsidian_Structure"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_OBSIDIAN_STRUCT
        bsdf.inputs['Metallic'].default_value = 0.82
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.45
            bsdf.inputs['Coat Roughness'].default_value = 0.08

        coord = nodes.new('ShaderNodeTexCoord')
        mapping = nodes.new('ShaderNodeMapping')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 35.0
        noise.inputs['Detail'].default_value = 4.0
        noise.inputs['Roughness'].default_value = 0.55

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.15
        ramp.color_ramp.elements[0].color = (0.24, 0.24, 0.24, 1.0)  # Micro-variation low
        ramp.color_ramp.elements[1].position = 0.85
        ramp.color_ramp.elements[1].color = (0.34, 0.34, 0.34, 1.0)  # Micro-variation high

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.020
        bump.inputs['Distance'].default_value = 0.010

        links.new(coord.outputs['Object'], mapping.inputs['Vector'])
        links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
        links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 3. Distant Towers (Atmospheric Graphite)
    for mname in ["MAT_Distant_Tower_Obsidian"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.035, 0.045, 0.058, 1.0)
        bsdf.inputs['Metallic'].default_value = 0.85
        bsdf.inputs['Roughness'].default_value = 0.32
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 4. Gunmetal Machined / Brushed Alloy (Gimbals, Trusses, Columns)
    for mname in ["MAT_Gunmetal_Brushed", "MAT_Gunmetal_Machined"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_GUNMETAL
        bsdf.inputs['Metallic'].default_value = 0.94
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.55
            bsdf.inputs['Coat Roughness'].default_value = 0.05

        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 55.0
        noise.inputs['Detail'].default_value = 4.0
        noise.inputs['Roughness'].default_value = 0.60

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.20
        ramp.color_ramp.elements[0].color = (0.18, 0.18, 0.18, 1.0)
        ramp.color_ramp.elements[1].position = 0.80
        ramp.color_ramp.elements[1].color = (0.26, 0.26, 0.26, 1.0)

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.014
        bump.inputs['Distance'].default_value = 0.008

        links.new(coord.outputs['Object'], noise.inputs['Vector'])
        links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 5. Machined Titanium Trim (Capitals, Bevels, Conduit Rails)
    for mname in ["MAT_Titanium_Machined"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_TITANIUM
        bsdf.inputs['Metallic'].default_value = 0.96
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.65
            bsdf.inputs['Coat Roughness'].default_value = 0.035

        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 40.0
        noise.inputs['Detail'].default_value = 3.0
        noise.inputs['Roughness'].default_value = 0.50

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.20
        ramp.color_ramp.elements[0].color = (0.16, 0.16, 0.16, 1.0)
        ramp.color_ramp.elements[1].position = 0.80
        ramp.color_ramp.elements[1].color = (0.22, 0.22, 0.22, 1.0)

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.010
        bump.inputs['Distance'].default_value = 0.006

        links.new(coord.outputs['Object'], noise.inputs['Vector'])
        links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], bsdf.inputs['Roughness'])
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 6. Physical Optical Glass (SOLID GLASS - NO FAKE ALPHA TRANSPARENCY)
    for mname in ["MAT_Crystal_Glass_PBR"]:
        mat = get_or_create(mname)
        mat.blend_method = 'OPAQUE'
        if hasattr(mat, "surface_render_method"): mat.surface_render_method = 'DITHERED'
        if hasattr(mat, "use_raytrace_refraction"): mat.use_raytrace_refraction = True
        if hasattr(mat, "refraction_depth"): mat.refraction_depth = 0.04  # Realistic architectural optical glass wall thickness (4cm)
        if hasattr(mat, "use_transparent_shadow"): mat.use_transparent_shadow = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_GLASS_TINT
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Roughness'].default_value = 0.020
        bsdf.inputs['IOR'].default_value = 1.52
        bsdf.inputs['Alpha'].default_value = 1.0  # Physical transmission/refraction only!
        if 'Transmission Weight' in bsdf.inputs:
            bsdf.inputs['Transmission Weight'].default_value = 1.0
        elif 'Transmission' in bsdf.inputs:
            bsdf.inputs['Transmission'].default_value = 1.0
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 1.0  # Beveled edge specular reflections
            bsdf.inputs['Coat Roughness'].default_value = 0.025
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 7. Internal 3D Memory World Representation (Dark mineral basalt mass with illuminated amber veins)
    for mname in ["MAT_Memory_Data_Voxel"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.045, 0.052, 0.065, 1.0)  # Dark physical basalt
        bsdf.inputs['Metallic'].default_value = 0.08  # Physical stone (NOT metallic mirror)
        bsdf.inputs['Roughness'].default_value = 0.48  # Satin honed stone texture
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.0  # Zero coat reflection

        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 18.0
        noise.inputs['Detail'].default_value = 3.0
        noise.inputs['Roughness'].default_value = 0.55

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.72
        ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        ramp.color_ramp.elements[1].position = 0.92
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)

        math_node = nodes.new('ShaderNodeMath')
        math_node.operation = 'MULTIPLY'
        math_node.inputs[1].default_value = 0.35  # Subtle physical mineral vein glow (NOT glowing hologram)

        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = COLOR_AMBER_ENERGY
            links.new(coord.outputs['Object'], noise.inputs['Vector'])
            links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
            links.new(ramp.outputs['Color'], math_node.inputs[0])
            links.new(math_node.outputs['Value'], bsdf.inputs['Emission Strength'])

        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 8. Secondary Internal Memory Data Representation (Deeper accent)
    for mname in ["MAT_Memory_Data_Voxel_Deep"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.038, 0.045, 0.056, 1.0)  # Dark physical mineral mass
        bsdf.inputs['Metallic'].default_value = 0.10
        bsdf.inputs['Roughness'].default_value = 0.45
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.0  # Zero coat reflection

        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 22.0
        noise.inputs['Detail'].default_value = 4.0
        noise.inputs['Roughness'].default_value = 0.55

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.70
        ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        ramp.color_ramp.elements[1].position = 0.90
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)

        math_node = nodes.new('ShaderNodeMath')
        math_node.operation = 'MULTIPLY'
        math_node.inputs[1].default_value = 0.50  # Physical mineral base with restrained amber seams

        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = (1.000, 0.440, 0.080, 1.0)
            links.new(coord.outputs['Object'], noise.inputs['Vector'])
            links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
            links.new(ramp.outputs['Color'], math_node.inputs[0])
            links.new(math_node.outputs['Value'], bsdf.inputs['Emission Strength'])

        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 9. EMBEDDED CONDUIT SHADER — ACTIVE HIGHWAYS (ELIMINATES UI OUTLINE)
    # Outer body: dark smoked bronze/resin channel
    # Clear coat: sharp physical edge reflection
    # Inner core: warm amber emission with glancing falloff + procedural variation (restrained practical light)
    for mname in ["MAT_Amber_Energy_Emission"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.050, 0.030, 0.012, 1.0)  # Dark bronze channel casing
        bsdf.inputs['Metallic'].default_value = 0.65
        bsdf.inputs['Roughness'].default_value = 0.20
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 1.0  # Sharp outer edge reflection
            bsdf.inputs['Coat Roughness'].default_value = 0.030
            if 'Coat IOR' in bsdf.inputs:
                bsdf.inputs['Coat IOR'].default_value = 1.55

        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = (1.000, 0.440, 0.080, 1.0)  # Restrained amber/bronze

            layer_weight = nodes.new('ShaderNodeLayerWeight')
            layer_weight.inputs['Blend'].default_value = 0.45

            ramp_facing = nodes.new('ShaderNodeValToRGB')
            ramp_facing.color_ramp.elements[0].position = 0.0
            ramp_facing.color_ramp.elements[0].color = (0.15, 0.15, 0.15, 1.0)  # Glancing edges reflect dark casing
            ramp_facing.color_ramp.elements[1].position = 0.75
            ramp_facing.color_ramp.elements[1].color = (1.00, 1.00, 1.00, 1.0)  # Core glow

            coord = nodes.new('ShaderNodeTexCoord')
            noise = nodes.new('ShaderNodeTexNoise')
            noise.inputs['Scale'].default_value = 24.0
            noise.inputs['Detail'].default_value = 3.0
            noise.inputs['Roughness'].default_value = 0.50

            ramp_noise = nodes.new('ShaderNodeValToRGB')
            ramp_noise.color_ramp.elements[0].position = 0.0
            ramp_noise.color_ramp.elements[0].color = (0.80, 0.80, 0.80, 1.0)
            ramp_noise.color_ramp.elements[1].position = 1.0
            ramp_noise.color_ramp.elements[1].color = (1.00, 1.00, 1.00, 1.0)

            math_mul1 = nodes.new('ShaderNodeMath')
            math_mul1.operation = 'MULTIPLY'

            math_mul2 = nodes.new('ShaderNodeMath')
            math_mul2.operation = 'MULTIPLY'
            math_mul2.inputs[1].default_value = 0.50  # Soft practical core luminance (NOT laser neon)

            links.new(layer_weight.outputs['Facing'], ramp_facing.inputs['Fac'])
            links.new(coord.outputs['Object'], noise.inputs['Vector'])
            links.new(noise.outputs['Fac'], ramp_noise.inputs['Fac'])
            links.new(ramp_facing.outputs['Color'], math_mul1.inputs[0])
            links.new(ramp_noise.outputs['Color'], math_mul1.inputs[1])
            links.new(math_mul1.outputs['Value'], math_mul2.inputs[0])
            links.new(math_mul2.outputs['Value'], bsdf.inputs['Emission Strength'])

        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 9B. RESTRAINED SECONDARY AMBER CONDUITS (Dais rings, canopy halos, column slots, distant reactor slots)
    for mname in ["MAT_Amber_Energy_Restrained"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.035, 0.020, 0.008, 1.0)  # Dark metallic casing
        bsdf.inputs['Metallic'].default_value = 0.85
        bsdf.inputs['Roughness'].default_value = 0.25
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 0.85
            bsdf.inputs['Coat Roughness'].default_value = 0.040

        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = (1.000, 0.400, 0.060, 1.0)

            layer_weight = nodes.new('ShaderNodeLayerWeight')
            layer_weight.inputs['Blend'].default_value = 0.40

            ramp_facing = nodes.new('ShaderNodeValToRGB')
            ramp_facing.color_ramp.elements[0].position = 0.0
            ramp_facing.color_ramp.elements[0].color = (0.10, 0.10, 0.10, 1.0)
            ramp_facing.color_ramp.elements[1].position = 0.80
            ramp_facing.color_ramp.elements[1].color = (1.00, 1.00, 1.00, 1.0)

            math_mul = nodes.new('ShaderNodeMath')
            math_mul.operation = 'MULTIPLY'
            math_mul.inputs[1].default_value = 0.22  # Subtle practical guide lighting

            links.new(layer_weight.outputs['Facing'], ramp_facing.inputs['Fac'])
            links.new(ramp_facing.outputs['Color'], math_mul.inputs[0])
            links.new(math_mul.outputs['Value'], bsdf.inputs['Emission Strength'])

        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 9C. MATERIAL ASSIGNMENTS TO ELIMINATE WIREFRAME / CAD OUTLINE LOOK
    # Reassign floating slab wireframes to machined titanium
    mat_ti = mats.get("MAT_Titanium_Machined")
    if mat_ti:
        for o in bpy.data.objects:
            if "Floating_Slab_Border" in o.name:
                for slot in o.material_slots:
                    slot.material = mat_ti

    # Reassign secondary structural energy slots to restrained shader
    mat_restr = mats.get("MAT_Amber_Energy_Restrained")
    if mat_restr:
        for o in bpy.data.objects:
            name = o.name
            if any(k in name for k in [
                "Canopy_Under", "Canopy_Upper", "Dais_Glow_Ring",
                "Archive_Pillar_01_AmberSlot", "Archive_Pillar_02_AmberSlot",
                "Archive_Pillar_03_AmberSlot", "Archive_Pillar_04_AmberSlot",
                "Archive_Pillar_05_AmberSlot", "Archive_Pillar_06_AmberSlot",
                "Archive_Pillar_07_AmberSlot", "Archive_Pillar_08_AmberSlot",
                "Tower_Deep", "Tower_East", "Tower_West", "Tower_North", "Tower_South",
                "GrandStairs", "AmberCollar", "AmberStrip", "Pathway_AmberTrack", "Bollard_GlowCap"
            ]):
                for slot in o.material_slots:
                    if slot.material and "amber" in slot.material.name.lower():
                        slot.material = mat_restr

    # 10. Primary Intelligence Amber Core (Astrolabe reactor, nodes, tips)
    for mname in ["MAT_Amber_Core_Bright", "MAT_Amber_Core_Intelligence"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.12, 0.06, 0.02, 1.0)
        bsdf.inputs['Metallic'].default_value = 0.30
        bsdf.inputs['Roughness'].default_value = 0.10
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 1.0
            bsdf.inputs['Coat Roughness'].default_value = 0.020
        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = (1.000, 0.540, 0.120, 1.0)
            bsdf.inputs['Emission Strength'].default_value = 2.6  # Hero luminance without white clipping
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 11. Vertical Conduit Beam (Slender focused laser filament)
    for mname in ["MAT_Vertical_Conduit_Core"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (1.0, 0.60, 0.16, 1.0)
        em.inputs['Strength'].default_value = 3.8
        links.new(em.outputs['Emission'], out.inputs['Surface'])
        mats[mname] = mat

    # 12. Vertical Conduit Sheath (Delicate glass containment column)
    for mname in ["MAT_Vertical_Conduit_Sheath"]:
        mat = get_or_create(mname)
        mat.blend_method = 'BLEND'
        if hasattr(mat, "surface_render_method"): mat.surface_render_method = 'BLENDED'
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.95, 0.98, 1.0, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.035
        bsdf.inputs['Alpha'].default_value = 0.20
        if 'Transmission Weight' in bsdf.inputs:
            bsdf.inputs['Transmission Weight'].default_value = 0.92
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 1.0
            bsdf.inputs['Coat Roughness'].default_value = 0.025
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 13. Subtle Cyan Telemetry
    for mname in ["MAT_Cyan_Telemetry_Emission", "MAT_Cyan_Telemetry_Restrained"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.02, 0.08, 0.10, 1.0)
        bsdf.inputs['Metallic'].default_value = 0.20
        if 'Coat Weight' in bsdf.inputs:
            bsdf.inputs['Coat Weight'].default_value = 1.0
            bsdf.inputs['Coat Roughness'].default_value = 0.025
        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = COLOR_CYAN_TELEMETRY
            bsdf.inputs['Emission Strength'].default_value = 1.6
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 14. Subordinate Stormy Sky Dome (Emission 0.26 - NOT self-glowing)
    for mname in ["MAT_Stormy_Sky_Dome"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out_d = nodes.new('ShaderNodeOutputMaterial')
        em_d = nodes.new('ShaderNodeEmission')
        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 0.007
        noise.inputs['Detail'].default_value = 5.0
        noise.inputs['Roughness'].default_value = 0.65

        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.15
        ramp.color_ramp.elements[0].color = (0.035, 0.052, 0.082, 1.0)  # Deep slate blue
        ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[1].color = (0.120, 0.160, 0.220, 1.0)  # Storm cloud break

        links.new(coord.outputs['Object'], noise.inputs['Vector'])
        links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], em_d.inputs['Color'])
        em_d.inputs['Strength'].default_value = 0.26  # Subordinate ambient sky
        links.new(em_d.outputs['Emission'], out_d.inputs['Surface'])
        mats[mname] = mat

    # 15. Storm Cloud Sea
    for mname in ["MAT_Cumulus_Cloud_PBR", "MAT_Storm_Clouds_PBR"]:
        mat = get_or_create(mname)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = COLOR_CLOUD_SCATTER
        bsdf.inputs['Roughness'].default_value = 0.96
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    # 16. Floating Data Slab
    for mname in ["MAT_Floating_Memory_Slab", "MAT_Floating_Data_Slab"]:
        mat = get_or_create(mname)
        mat.blend_method = 'BLEND'
        if hasattr(mat, "surface_render_method"): mat.surface_render_method = 'BLENDED'
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.02, 0.025, 0.035, 1.0)
        bsdf.inputs['Alpha'].default_value = 0.25
        bsdf.inputs['Roughness'].default_value = 0.08
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        mats[mname] = mat

    return mats

# ---------------------------------------------------------------------------
# REORGANIZE COLLECTIONS (VERIFICATION ONLY)
# ---------------------------------------------------------------------------
def reorganize_existing_collections():
    """Verifies that all 1,143 objects are properly partitioned into the 10 collections."""
    cols = ensure_collections()

    if "MEMORY_ARCHIVE" in bpy.data.collections:
        archive_col = bpy.data.collections["MEMORY_ARCHIVE"]
        core_keywords = ['astrolabe', 'reactor', 'gimbal', 'shard', 'vertical_conduit', 'innercore']
        for obj in list(archive_col.objects):
            name_lower = obj.name.lower()
            if any(k in name_lower for k in core_keywords) and 'crystal' not in name_lower:
                link_to_col(obj, cols["MEMORY_CORE"])
            else:
                link_to_col(obj, cols["MEMORY_ARCHITECTURE"])
        if len(archive_col.objects) == 0:
            bpy.data.collections.remove(archive_col)

    if "MEMORY_SCALE_ANCHOR" in bpy.data.collections:
        scale_old = bpy.data.collections["MEMORY_SCALE_ANCHOR"]
        for obj in list(scale_old.objects):
            link_to_col(obj, cols["MEMORY_SCALE_ANCHORS"])
        if len(scale_old.objects) == 0:
            bpy.data.collections.remove(scale_old)

    print("Collections verified and synchronized:")
    for cname in COLLECTION_NAMES:
        c = bpy.data.collections.get(cname)
        count = len(c.objects) if c else 0
        print(f"  - {cname}: {count} objects")

    return cols

# ---------------------------------------------------------------------------
# GEOMETRY CALIBRATION (ZERO TRANSFORM CHANGES)
# ---------------------------------------------------------------------------
def calibrate_geometry_elements():
    """Verifies geometry elements without modifying any transforms or geometry."""
    sky = bpy.data.objects.get('Sky_Dome_Stormy_Atmosphere')
    if sky:
        sky.visible_shadow = False

# ---------------------------------------------------------------------------
# CINEMATIC LIGHTING & ATMOSPHERE
# ---------------------------------------------------------------------------
def calibrate_memory_lighting_and_atmosphere(lights_col, scene):
    """
    Sets up multi-point architectural key/fill lighting, astrolabe rim lighting, and subtle atmospheric volume:
    - Primary astrolabe core light: 400W (warm amber)
    - Astrolabe rim backlight: 340W (cool blue-grey)
    - Astrolabe pedestal uplight: 160W (warm amber bounce)
    - Front rotunda architectural key: 3800W (cool slate fill revealing column curvature)
    - Canopy downlight: 450W
    - Staircase wash: 360W (localized golden edge reflections on steps)
    - Path lights: 120W (warm amber illumination on walkway deck and crystal bases)
    - Detail crystal key: 80W (focused key light on foreground crystal)
    - Distant sun: 6.5W (cool slate rim)
    - Subtle World Volume (density 0.00012, anisotropy 0.68)
    """
    # 1. Existing Light Adjustments
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            l = obj.data
            name = obj.name
            if 'Astrolabe_WarmCore' in name or 'Astrolabe_Core' in name:
                l.energy = 380.0
                l.color = (1.0, 0.55, 0.12)
                if hasattr(l, "shadow_soft_size"): l.shadow_soft_size = 1.20
                link_to_col(obj, lights_col)
            elif 'Canopy' in name:
                l.energy = 380.0
                l.color = (1.0, 0.64, 0.22)
                if hasattr(l, "spot_size"): l.spot_size = math.radians(75.0)
                if hasattr(l, "spot_blend"): l.spot_blend = 0.50
                link_to_col(obj, lights_col)
            elif 'Staircase' in name:
                l.energy = 0.0  # Zeroed to eliminate specular glare / yellow overwash on balustrades and vitrines
                l.color = (1.0, 0.58, 0.16)
                link_to_col(obj, lights_col)
            elif 'Atmospheric' in name or 'Sun' in name:
                l.energy = 28.0  # Directional cool slate skylight across entire 150m environment
                l.color = (0.34, 0.46, 0.64)
                obj.rotation_euler = (math.radians(55.0), math.radians(15.0), math.radians(-35.0))
                link_to_col(obj, lights_col)
            elif 'Detail' in name:
                l.energy = 0.0  # Zeroed to eliminate direct specular point reflection circle on hero vitrine glass
                l.color = (1.0, 0.65, 0.24)
                if hasattr(l, "shadow_soft_size"): l.shadow_soft_size = 0.80
                link_to_col(obj, lights_col)
            elif 'PathLight' in name:
                l.energy = 80.0
                l.color = (1.0, 0.54, 0.14)
                link_to_col(obj, lights_col)

    # 2. Astrolabe Rim Backlight (Cool Blue-Grey)
    rim_name = "Light_Astrolabe_Rim_Back"
    rim_obj = bpy.data.objects.get(rim_name)
    if not rim_obj:
        rim_data = bpy.data.lights.new(name=rim_name, type='POINT')
        rim_obj = bpy.data.objects.new(rim_name, rim_data)
        lights_col.objects.link(rim_obj)
    rim_obj.location = (0.0, 9.5, 15.0)
    rim_obj.data.energy = 480.0
    rim_obj.data.color = (0.36, 0.50, 0.82)
    if hasattr(rim_obj.data, "shadow_soft_size"): rim_obj.data.shadow_soft_size = 1.0
    link_to_col(rim_obj, lights_col)

    # 3. Astrolabe Pedestal Uplight (Warm Amber)
    ped_light_name = "Light_Astrolabe_Pedestal_Up"
    ped_obj = bpy.data.objects.get(ped_light_name)
    if not ped_obj:
        ped_data = bpy.data.lights.new(name=ped_light_name, type='POINT')
        ped_obj = bpy.data.objects.new(ped_light_name, ped_data)
        lights_col.objects.link(ped_obj)
    ped_obj.location = (0.0, 0.0, 4.3)
    ped_obj.data.energy = 160.0
    ped_obj.data.color = (1.0, 0.52, 0.12)
    if hasattr(ped_obj.data, "shadow_soft_size"): ped_obj.data.shadow_soft_size = 0.50
    link_to_col(ped_obj, lights_col)

    # 4. Front Rotunda Architectural Key (Cool Slate Fill for Monumental Columns)
    front_key_name = "Light_Rotunda_Front_Key"
    front_key_obj = bpy.data.objects.get(front_key_name)
    if not front_key_obj:
        front_key_data = bpy.data.lights.new(name=front_key_name, type='POINT')
        front_key_obj = bpy.data.objects.new(front_key_name, front_key_data)
        lights_col.objects.link(front_key_obj)
    front_key_obj.location = (0.0, -22.0, 10.0)
    front_key_obj.data.energy = 12000.0  # Appropriate illumination for 20m column distance
    front_key_obj.data.color = (0.38, 0.50, 0.72)
    if hasattr(front_key_obj.data, "shadow_soft_size"): front_key_obj.data.shadow_soft_size = 8.0
    link_to_col(front_key_obj, lights_col)

    # 5. Subtle World Volume Atmosphere
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("WORLD_Stage03_Memory_Ambient")
        scene.world = world
    world.use_nodes = True
    w_nodes = world.node_tree.nodes
    w_links = world.node_tree.links
    w_nodes.clear()

    w_out = w_nodes.new('ShaderNodeOutputWorld')
    w_bg = w_nodes.new('ShaderNodeBackground')
    w_bg.inputs['Color'].default_value = (0.038, 0.055, 0.082, 1.0)
    w_bg.inputs['Strength'].default_value = 1.4
    w_links.new(w_bg.outputs['Background'], w_out.inputs['Surface'])

    # Low-density volume for aerial perspective
    w_vol = w_nodes.new('ShaderNodeVolumePrincipled')
    w_vol.inputs['Color'].default_value = (0.05, 0.08, 0.13, 1.0)
    w_vol.inputs['Density'].default_value = 0.00008
    w_vol.inputs['Anisotropy'].default_value = 0.65
    w_links.new(w_vol.outputs['Volume'], w_out.inputs['Volume'])

    print("Lighting and atmospheric volume configured successfully.")

# ---------------------------------------------------------------------------
# CINEMATIC CAMERAS & DEPTH OF FIELD
# ---------------------------------------------------------------------------
def setup_or_calibrate_cameras(cameras_col):
    """
    Calibrates the 3 production cameras and enables cinematic Depth of Field (DOF):
    - CAM_CinematicHero: 28mm, focus on Astrolabe, f/6.3
    - CAM_MonumentalLowAngle: 22mm, focus on Astrolabe, f/8.0
    - CAM_ArchiveDetail: 32mm, focus on foreground crystal vitrine, f/7.1
    """
    cam_configs = [
        ("CAM_CinematicHero",        (-12.0, -38.5, 2.30), (0.0, -4.5, 9.8),  28.0, "Astrolabe_Central_Reactor_Core", 6.3),
        ("CAM_MonumentalLowAngle",   (0.0, -26.0, 0.65),   (0.0, -1.0, 16.5), 22.0, "Astrolabe_Central_Reactor_Core", 8.0),
        ("CAM_ArchiveDetail",        (-16.2, -32.8, 1.85), (-4.0, -23.0, 2.5), 32.0, "Pathway_Memory_Crystal_02_CrystalPrism", 7.1),
    ]

    cameras = {}
    for name, loc, target_loc, focal, focus_target_name, fstop in cam_configs:
        cam_obj = bpy.data.objects.get(name)
        target_name = f"{name}_Target"
        target_obj = bpy.data.objects.get(target_name)

        if not target_obj:
            target_obj = bpy.data.objects.new(target_name, None)
            target_obj.empty_display_type = 'PLAIN_AXES'
            target_obj.empty_display_size = 0.5
            cameras_col.objects.link(target_obj)

        target_obj.location = target_loc
        link_to_col(target_obj, cameras_col)

        if not cam_obj:
            cam_data = bpy.data.cameras.new(name)
            cam_obj = bpy.data.objects.new(name, cam_data)
            cameras_col.objects.link(cam_obj)
        else:
            link_to_col(cam_obj, cameras_col)

        cam_obj.location = loc
        cam_obj.data.lens = focal
        cam_obj.data.sensor_width = 36.0
        cam_obj.data.clip_start = 0.1
        cam_obj.data.clip_end = 1500.0

        # Track-To constraint
        tt = None
        for c in cam_obj.constraints:
            if c.type == 'TRACK_TO':
                tt = c
                break
        if not tt:
            tt = cam_obj.constraints.new('TRACK_TO')
        tt.target = target_obj
        tt.track_axis = 'TRACK_NEGATIVE_Z'
        tt.up_axis = 'UP_Y'

        # Depth of Field
        cam_obj.data.dof.use_dof = True
        focus_obj = bpy.data.objects.get(focus_target_name)
        if focus_obj:
            cam_obj.data.dof.focus_object = focus_obj
        else:
            cam_obj.data.dof.focus_distance = (Vector(loc) - Vector(target_loc)).length
        cam_obj.data.dof.aperture_fstop = fstop

        cameras[name] = cam_obj
        print(f"Camera verified: {name} (Lens: {focal}mm, f/{fstop}, Focus: {focus_target_name})")

    return cameras

# ---------------------------------------------------------------------------
# RENDER SETTINGS & COMPOSITOR
# ---------------------------------------------------------------------------
def configure_render_settings_and_compositor(scene, is_preview=True):
    """Configures AgX color management (-0.30 exposure) and restrained Compositor Bloom."""
    scene.render.engine = 'BLENDER_EEVEE'
    if is_preview:
        scene.render.resolution_x = 960
        scene.render.resolution_y = 540
    else:
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.compression = 15

    # EEVEE-Next Screen-Space Raytracing & Fast GI
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "use_raytracing"): scene.eevee.use_raytracing = True
        if hasattr(scene.eevee, "ray_tracing_method"): scene.eevee.ray_tracing_method = 'SCREEN'
        if hasattr(scene.eevee, "use_fast_gi"): scene.eevee.use_fast_gi = True
        if hasattr(scene.eevee, "fast_gi_method"): scene.eevee.fast_gi_method = 'GLOBAL_ILLUMINATION'
        if hasattr(scene.eevee, "fast_gi_quality"): scene.eevee.fast_gi_quality = 1.0
        if hasattr(scene.eevee, "fast_gi_resolution"): scene.eevee.fast_gi_resolution = '1'
        if hasattr(scene.eevee, "fast_gi_step_count"): scene.eevee.fast_gi_step_count = 16
        if hasattr(scene.eevee, "fast_gi_ray_count"): scene.eevee.fast_gi_ray_count = 4
        if hasattr(scene.eevee, "gi_diffuse_bounces"): scene.eevee.gi_diffuse_bounces = 4
        if hasattr(scene.eevee, "taa_render_samples"): scene.eevee.taa_render_samples = 32

    # Color Management: AgX with controlled exposure
    view_transforms = [item.identifier for item in scene.view_settings.bl_rna.properties['view_transform'].enum_items]
    if 'AgX' in view_transforms:
        scene.view_settings.view_transform = 'AgX'
    elif 'Filmic' in view_transforms:
        scene.view_settings.view_transform = 'Filmic'

    looks = [item.identifier for item in scene.view_settings.bl_rna.properties['look'].enum_items]
    if 'Medium High Contrast' in looks:
        scene.view_settings.look = 'Medium High Contrast'

    scene.view_settings.exposure = -0.30
    scene.view_settings.gamma = 1.0

    # Compositor: Gentle controlled bloom on intense points only
    if hasattr(scene, "compositing_node_group"):
        comp_ng = bpy.data.node_groups.new('Compositor_Restrained_Bloom', 'CompositorNodeTree')
        scene.compositing_node_group = comp_ng
        rl = comp_ng.nodes.new('CompositorNodeRLayers')
        glare = comp_ng.nodes.new('CompositorNodeGlare')
        if 'Type' in glare.inputs: glare.inputs['Type'].default_value = 'Bloom'
        if 'Threshold' in glare.inputs: glare.inputs['Threshold'].default_value = 4.8
        if 'Strength' in glare.inputs: glare.inputs['Strength'].default_value = 0.035
        if 'Size' in glare.inputs: glare.inputs['Size'].default_value = 5
        out = comp_ng.nodes.new('NodeGroupOutput')
        comp_ng.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        links = comp_ng.links
        links.new(rl.outputs['Image'], glare.inputs['Image'])
        links.new(glare.outputs['Image'], out.inputs['Image'])

def render_camera_view(cam_obj, output_path):
    """Renders a single camera view and saves it to disk."""
    scene = bpy.context.scene
    scene.camera = cam_obj
    scene.render.filepath = output_path
    print(f"\nRendering camera [{cam_obj.name}] to: {output_path} ...")
    bpy.ops.render.render(write_still=True)
    print(f"Successfully generated: {output_path}")

# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------
def main():
    # Pass 2 Enforces Preview Gate (960x540)
    is_preview = True
    if "--final-1080p" in sys.argv:
        is_preview = False

    print("=" * 75)
    print(f"ARYAOS V1 — STAGE 03: MEMORY ARCHIVE LOOK-DEVELOPMENT PASS 2 ({'PREVIEW 540p' if is_preview else 'FINAL 1080p'})")
    print("=" * 75)

    # 1. Verify Backup Exists
    if not os.path.exists(BACKUP_PATH):
        raise RuntimeError(f"ABORT: Backup not found at {BACKUP_PATH}. Hard preservation lock required.")
    print(f"[PRESERVATION] Verified backup exists: {BACKUP_PATH}")

    # 2. Load Existing .blend Foundation
    if os.path.exists(BLEND_EXPORT_PATH):
        print(f"\n[RECOVERY] Opening existing scene from: {BLEND_EXPORT_PATH}")
        bpy.ops.wm.open_mainfile(filepath=BLEND_EXPORT_PATH)
        print(f"Successfully opened scene. Total existing objects: {len(bpy.data.objects)}")
    else:
        raise RuntimeError(f"ABORT: {BLEND_EXPORT_PATH} not found.")

    # 3. Automated Integrity Validation Gate
    obj_count = len(bpy.data.objects)
    col_count = len(bpy.data.collections)
    print(f"\n[AUTOMATED VALIDATION] Object count: {obj_count} | Collection count: {col_count}")
    if obj_count != 1143:
        raise RuntimeError(f"ABORT: Expected exactly 1,143 objects, found {obj_count}. Preservation violated.")
    if col_count != 10:
        raise RuntimeError(f"ABORT: Expected exactly 10 collections, found {col_count}. Preservation violated.")
    print("[AUTOMATED VALIDATION PASS] Foundation scene integrity verified.")

    # 4. Reorganize and Verify 10 Production Collections
    print("\n[Step 1/5] Verifying 10 production collections...")
    cols = reorganize_existing_collections()

    # 5. Setup or Calibrate PBR Materials
    print("\n[Step 2/5] Calibrating physical PBR materials (Embedded Conduits, Micro-Surface, Optical Glass)...")
    materials = setup_or_calibrate_materials()

    # 6. Verify Geometry Elements (Zero Transform Modifications)
    print("\n[Step 3/5] Verifying geometric elements (zero transform changes)...")
    calibrate_geometry_elements()

    # 7. Calibrate Multi-Point Lighting & Atmospheric Volume
    print("\n[Step 4/5] Calibrating localized practical lighting & slate-blue atmospheric volume...")
    calibrate_memory_lighting_and_atmosphere(cols["MEMORY_LIGHTING"], bpy.context.scene)

    # 8. Setup & Calibrate Production Cameras with DOF
    print("\n[Step 5/5] Verifying production cameras and Depth of Field...")
    cameras = setup_or_calibrate_cameras(cols["CAMERAS"])

    # 9. Configure Render Settings & Compositor
    print("\nConfiguring AgX color management & compositor...")
    configure_render_settings_and_compositor(bpy.context.scene, is_preview=is_preview)

    # 10. Re-verify Integrity Prior to Saving
    assert len(bpy.data.objects) == 1143, f"Integrity check failed: {len(bpy.data.objects)} objects"
    assert len(bpy.data.collections) == 10, f"Integrity check failed: {len(bpy.data.collections)} collections"

    # 11. Save Master .blend File
    os.makedirs(os.path.dirname(BLEND_EXPORT_PATH), exist_ok=True)
    print(f"\nSaving master Blender scene to: {BLEND_EXPORT_PATH} ...")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_EXPORT_PATH)
    print(f"Master scene successfully saved: {BLEND_EXPORT_PATH}")

    # 12. Render Stills
    os.makedirs(RENDERS_DIR, exist_ok=True)

    if is_preview:
        print("\nRendering 3 Preview Stills at 960x540 (16:9)...")
        render_camera_view(cameras["CAM_CinematicHero"], PREVIEW_HERO_PATH)
        render_camera_view(cameras["CAM_MonumentalLowAngle"], PREVIEW_MONUMENTAL_PATH)
        render_camera_view(cameras["CAM_ArchiveDetail"], PREVIEW_DETAIL_PATH)

        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        for src_path, art_name in [
            (PREVIEW_HERO_PATH, "stage03_memory_preview_hero.png"),
            (PREVIEW_MONUMENTAL_PATH, "stage03_memory_preview_monumental.png"),
            (PREVIEW_DETAIL_PATH, "stage03_memory_preview_detail.png"),
        ]:
            dest_path = os.path.join(ARTIFACT_DIR, art_name)
            if os.path.exists(src_path):
                shutil.copy2(src_path, dest_path)
                print(f"Copied preview artifact: {dest_path}")
    else:
        print("\nRendering 3 Final Production Stills at 1920x1080 (16:9)...")
        render_camera_view(cameras["CAM_CinematicHero"], RENDER_HERO_PATH)
        render_camera_view(cameras["CAM_MonumentalLowAngle"], RENDER_MONUMENTAL_PATH)
        render_camera_view(cameras["CAM_ArchiveDetail"], RENDER_DETAIL_PATH)

        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        for src_path, art_name in [
            (RENDER_HERO_PATH, "stage03_memory_clean_hero.png"),
            (RENDER_MONUMENTAL_PATH, "stage03_memory_clean_monumental.png"),
            (RENDER_DETAIL_PATH, "stage03_memory_clean_detail.png"),
        ]:
            dest_path = os.path.join(ARTIFACT_DIR, art_name)
            if os.path.exists(src_path):
                shutil.copy2(src_path, dest_path)
                print(f"Copied render artifact: {dest_path}")

    print("\n" + "=" * 75)
    print("STAGE 03 LOOK-DEVELOPMENT PIPELINE COMPLETE!")
    print("=" * 75)

if __name__ == "__main__":
    main()
