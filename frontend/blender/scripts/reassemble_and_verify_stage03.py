#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 1: Full-Scene Reassembly & Render Script
Target: Blender 5.2.2 LTS

Reassembles the entire 150m environment using ONLY:
- The 14 exported modular GLBs
- The instance transform registry (stage03_memory_instances.json)
- The production lighting, atmosphere, cameras, and compositor

Renders validation views:
- stage03_memory_reassembled_hero.png
- stage03_memory_reassembled_monumental.png
- stage03_memory_reassembled_detail.png
===============================================================================
"""

import bpy
import json
import math
import os
import sys
from mathutils import Vector, Matrix

# Path Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")
INSTANCES_JSON_PATH = os.path.join(ASSETS_DIR, "stage03_memory_instances.json")

BENCHMARK_VIEWS = [
    ("hero", "CAM_CinematicHero", os.path.join(RENDERS_DIR, "stage03_memory_reassembled_hero.png")),
    ("monumental", "CAM_MonumentalLowAngle", os.path.join(RENDERS_DIR, "stage03_memory_reassembled_monumental.png")),
    ("detail", "CAM_ArchiveDetail", os.path.join(RENDERS_DIR, "stage03_memory_reassembled_detail.png"))
]

ARCHETYPE_GLBS = {
    "mountain": "08_memory_world_mountain.glb",
    "neural": "09_memory_world_neural.glb",
    "city": "10_memory_world_city.glb",
    "matrix": "11_memory_world_matrix.glb",
    "chrono": "12_memory_world_chrono.glb"
}

def relink_materials(objects, canonical_materials):
    """Reconnects imported meshes to the canonical scene procedural shaders."""
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            if not slot.material:
                continue
            mat_name = slot.material.name
            # Strip Blender import suffixes (.001, .002, etc.)
            base_name = mat_name.split('.')[0]
            if base_name in canonical_materials:
                slot.material = canonical_materials[base_name]

def main():
    print("\n" + "="*80)
    print("STAGE 03: FULL-SCENE GLB REASSEMBLY & RENDER")
    print("="*80)
    
    # 1. Load instances JSON
    if not os.path.exists(INSTANCES_JSON_PATH):
        print(f"FATAL: Missing instance registry: {INSTANCES_JSON_PATH}")
        sys.exit(1)
    with open(INSTANCES_JSON_PATH) as f:
        inst_registry = json.load(f)
        
    # 2. Cache canonical materials before removing objects
    canonical_materials = {m.name: m for m in bpy.data.materials}
    print(f"Cached {len(canonical_materials)} canonical scene materials.")
    
    # 3. Remove original 1,054 exported geometry objects
    collections_to_strip = [
        "MEMORY_CORE",
        "MEMORY_ARCHITECTURE",
        "MEMORY_CONDUITS",
        "MEMORY_ORBITAL_RINGS",
        "MEMORY_TOWERS",
        "MEMORY_CRYSTALS",
        "MEMORY_SCALE_ANCHORS"
    ]
    removed_count = 0
    for col_name in collections_to_strip:
        if col_name in bpy.data.collections:
            col = bpy.data.collections[col_name]
            for obj in list(col.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
                removed_count += 1
    print(f"Cleared {removed_count} production objects (retaining atmosphere, lights, and cameras).")
    
    # 4. Create Reassembly Collections
    master_col = bpy.context.scene.collection
    col_world = bpy.data.collections.new("REASSEMBLED_GLB_WORLD")
    col_instances = bpy.data.collections.new("REASSEMBLED_GLB_INSTANCES")
    col_templates = bpy.data.collections.new("REASSEMBLED_GLB_TEMPLATES")
    
    master_col.children.link(col_world)
    master_col.children.link(col_instances)
    master_col.children.link(col_templates)
    
    # Hide templates from render
    col_templates.hide_render = True
    col_templates.hide_viewport = True
    
    # 5. Import Static World-Space GLBs (01, 02, 03, 04, 05, 06, 13)
    static_glbs = [
        "01_astrolabe_hero_core.glb",
        "02_architecture_dais_stairs.glb",
        "03_architecture_columns_canopy.glb",
        "04_conduits_viaduct.glb",
        "05_orbital_viaducts.glb",
        "06_distant_towers.glb",
        "13_floating_slabs.glb"
    ]
    
    view_layer = bpy.context.view_layer
    view_layer.active_layer_collection = view_layer.layer_collection.children["REASSEMBLED_GLB_WORLD"]
    
    for g in static_glbs:
        p = os.path.join(ASSETS_DIR, g)
        pre_objs = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=p)
        new_objs = list(set(bpy.data.objects) - pre_objs)
        relink_materials(new_objs, canonical_materials)
        print(f"Imported static GLB [{g}]: {len(new_objs)} objects linked into world space.")
        
    # 6. Import Templates into col_templates
    view_layer.active_layer_collection = view_layer.layer_collection.children["REASSEMBLED_GLB_TEMPLATES"]
    
    # Housing template
    housing_glb = os.path.join(ASSETS_DIR, "07_memory_vitrine_housing.glb")
    pre_objs = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=housing_glb)
    housing_template_parts = list(set(bpy.data.objects) - pre_objs)
    relink_materials(housing_template_parts, canonical_materials)
    print(f"Imported vitrine housing template: {len(housing_template_parts)} parts.")
    
    # Archetype templates
    archetype_template_parts = {}
    for arch_key, glb_file in ARCHETYPE_GLBS.items():
        p = os.path.join(ASSETS_DIR, glb_file)
        pre_objs = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=p)
        arch_parts = list(set(bpy.data.objects) - pre_objs)
        relink_materials(arch_parts, canonical_materials)
        archetype_template_parts[arch_key] = arch_parts
        print(f"Imported archetype template [{arch_key}]: {len(arch_parts)} parts.")
        
    # Scale anchor template
    anchor_glb = os.path.join(ASSETS_DIR, "14_scale_anchor_figure.glb")
    pre_objs = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=anchor_glb)
    anchor_template_parts = list(set(bpy.data.objects) - pre_objs)
    relink_materials(anchor_template_parts, canonical_materials)
    print(f"Imported scale anchor template: {len(anchor_template_parts)} part(s).")
    
    # 7. Reassemble Vitrine Instances
    print("\nInstancing 24 Memory Vitrines and internal worlds ...")
    vitrine_count = 0
    for v_entry in inst_registry["vitrines"]:
        v_id = v_entry["id"]
        arch = v_entry["archetype"]
        mat_inst = Matrix(v_entry["blender_transform"]["matrix_4x4"])
        
        # Instance Housing parts
        for part in housing_template_parts:
            inst_obj = bpy.data.objects.new(f"{v_id}_{part.name}", part.data)
            inst_obj.matrix_world = mat_inst @ part.matrix_world
            col_instances.objects.link(inst_obj)
            
        # Instance Archetype parts
        arch_parts = archetype_template_parts[arch]
        for part in arch_parts:
            inst_obj = bpy.data.objects.new(f"{v_id}_{part.name}", part.data)
            inst_obj.matrix_world = mat_inst @ part.matrix_world
            col_instances.objects.link(inst_obj)
            
        vitrine_count += 1
    print(f"Successfully reassembled {vitrine_count} vitrines with internal worlds.")
    
    # 8. Reassemble Scale Anchor Instances
    print("\nInstancing 3 Scale Anchor figures ...")
    figure_src = anchor_template_parts[0]
    for a_entry in inst_registry["scale_anchors"]:
        a_id = a_entry["id"]
        mat_inst = Matrix(a_entry["blender_transform"]["matrix_4x4"])
        inst_obj = bpy.data.objects.new(f"{a_id}_Figure", figure_src.data)
        inst_obj.matrix_world = mat_inst @ figure_src.matrix_world
        col_instances.objects.link(inst_obj)
        print(f"Instanced [{a_id}].")
        
    # 9. Clean up temporary imported duplicate materials (.001, etc.)
    for mat in list(bpy.data.materials):
        if mat.users == 0 and '.' in mat.name:
            bpy.data.materials.remove(mat)
            
    # 10. Render Validation Views
    print("\n" + "="*80)
    print("RENDERING REASSEMBLED VALIDATION VIEWS (1920x1080)")
    print("="*80)
    
    scene = bpy.context.scene
    for key, cam_name, reassembled_path in BENCHMARK_VIEWS:
        cam_obj = bpy.data.objects.get(cam_name)
        if not cam_obj:
            raise ValueError(f"Camera not found: {cam_name}")
            
        scene.camera = cam_obj
        scene.render.filepath = reassembled_path
        print(f"\nRendering [{key.upper()}] via {cam_name} to: {reassembled_path} ...")
        bpy.ops.render.render(write_still=True)
        print(f"Finished rendering: {reassembled_path}")
        
    print("\n" + "="*80)
    print("ALL 3 REASSEMBLED VIEWS RENDERED SUCCESSFULLY!")
    print("="*80)

if __name__ == "__main__":
    main()
