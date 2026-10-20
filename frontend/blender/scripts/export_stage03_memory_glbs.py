#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 1: Blender -> Modular GLB Export Pipeline
Target: Blender 5.2.2 LTS

Exports exactly 14 modular GLBs into:
  frontend/blender/assets/stage03_memory/
And generates:
  frontend/blender/assets/stage03_memory/stage03_memory_instances.json

Rules:
- Read-only access to source blend scene.
- Zero scene modifications saved.
- Preserves animatable Astrolabe hierarchy.
- Merges static architecture by material slots.
- Canonicalizes reusable vitrine housing, 5 archetypes, and scale figure.
- Records exact instance matrices for millimetric reassembly.
===============================================================================
"""

import bpy
import bmesh
import json
import math
import os
import sys
import shutil
from mathutils import Vector, Matrix, Euler, Quaternion

# Path Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
ASSETS_DIR = os.path.join(FRONTEND_DIR, "blender", "assets", "stage03_memory")
INSTANCES_JSON_PATH = os.path.join(ASSETS_DIR, "stage03_memory_instances.json")

ARCHETYPE_MAP = {
    'Mountain': [
        'Dais_Flank_Crystal_01', 'Dais_Flank_Crystal_06',
        'Pathway_Memory_Crystal_01', 'Pathway_Memory_Crystal_06', 'Pathway_Memory_Crystal_11',
        'Rotunda_Inner_Crystal_04'
    ],
    'Neural': [
        'Dais_Flank_Crystal_02', 'Dais_Flank_Crystal_07',
        'Pathway_Memory_Crystal_02', 'Pathway_Memory_Crystal_07', 'Pathway_Memory_Crystal_12'
    ],
    'City': [
        'Dais_Flank_Crystal_03', 'Dais_Flank_Crystal_08',
        'Pathway_Memory_Crystal_03', 'Pathway_Memory_Crystal_08',
        'Rotunda_Inner_Crystal_01'
    ],
    'Matrix': [
        'Dais_Flank_Crystal_04',
        'Pathway_Memory_Crystal_04', 'Pathway_Memory_Crystal_09',
        'Rotunda_Inner_Crystal_02'
    ],
    'Chrono': [
        'Dais_Flank_Crystal_05',
        'Pathway_Memory_Crystal_05', 'Pathway_Memory_Crystal_10',
        'Rotunda_Inner_Crystal_03'
    ]
}

def clean_temp_collection(temp_col_name="EXPORT_TEMP"):
    """Removes temporary export collection and its objects/meshes."""
    if temp_col_name in bpy.data.collections:
        col = bpy.data.collections[temp_col_name]
        for obj in list(col.objects):
            me = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)
        bpy.data.collections.remove(col)

def get_or_create_temp_collection(temp_col_name="EXPORT_TEMP"):
    clean_temp_collection(temp_col_name)
    col = bpy.data.collections.new(temp_col_name)
    bpy.context.scene.collection.children.link(col)
    return col

def export_glb(filepath, objects):
    """Selects the specified objects and exports them via glTF 2.0."""
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    
    # Active object
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
        
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLB',
        use_selection=True,
        export_apply=True,
        export_normals=True,
        export_materials='EXPORT',
        export_yup=True,
        export_draco_mesh_compression_enable=False,
        export_cameras=False,
        export_lights=False,
        export_animations=False
    )
    file_size = os.path.getsize(filepath)
    print(f"Exported [{os.path.basename(filepath)}]: {file_size:,} bytes, {len(objects)} object node(s)")
    return file_size

def merge_and_export_by_material(source_objs, filepath, prefix):
    """
    Groups source objects by material, bakes evaluated world geometry via bmesh,
    and exports a merged static GLB with 1 submesh per material slot.
    """
    temp_col = get_or_create_temp_collection("EXPORT_TEMP")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    # Group by material
    groups = {}
    for obj in source_objs:
        if obj.type != 'MESH':
            continue
        mat = obj.material_slots[0].material if obj.material_slots and obj.material_slots[0].material else None
        mat_name = mat.name if mat else "None"
        groups.setdefault(mat_name, (mat, []) )
        groups[mat_name][1].append(obj)
        
    created_objs = []
    for mat_name, (mat, objs) in groups.items():
        bm = bmesh.new()
        for obj in objs:
            eval_obj = obj.evaluated_get(depsgraph)
            me_eval = eval_obj.to_mesh()
            me_eval.transform(obj.matrix_world)
            bm.from_mesh(me_eval)
            eval_obj.to_mesh_clear()
            
        mesh_name = f"{prefix}_{mat_name}"
        new_mesh = bpy.data.meshes.new(mesh_name)
        bm.to_mesh(new_mesh)
        bm.free()
        
        if mat:
            new_mesh.materials.append(mat)
            
        new_obj = bpy.data.objects.new(mesh_name, new_mesh)
        temp_col.objects.link(new_obj)
        created_objs.append(new_obj)
        
    file_size = export_glb(filepath, created_objs)
    clean_temp_collection("EXPORT_TEMP")
    return file_size, len(created_objs)

def build_instance_metadata():
    """Builds and serializes stage03_memory_instances.json."""
    instances_data = {
        "version": "1.0.0",
        "stage": "STAGE_03_MEMORY",
        "description": "Instance transform registry for Stage 03 Memory Archive real-time WebGL reassembly",
        "coordinate_system": {
            "source": "Blender Z-up right-handed (+X right, +Y forward, +Z up)",
            "target_threejs": "Three.js Y-up right-handed (+X right, +Y up, +Z back) [x, z, -y]"
        },
        "vitrine_housing_model": "07_memory_vitrine_housing.glb",
        "vitrines": [],
        "scale_anchors": [],
        "static_assets": [
            {"id": "01_astrolabe_hero_core", "file": "01_astrolabe_hero_core.glb", "strategy": "functional_hierarchy", "objects": 25},
            {"id": "02_architecture_dais_stairs", "file": "02_architecture_dais_stairs.glb", "strategy": "world_merged_by_material", "submeshes": 4},
            {"id": "03_architecture_columns_canopy", "file": "03_architecture_columns_canopy.glb", "strategy": "world_merged_by_material", "submeshes": 3},
            {"id": "04_conduits_viaduct", "file": "04_conduits_viaduct.glb", "strategy": "world_merged_by_material", "submeshes": 6},
            {"id": "05_orbital_viaducts", "file": "05_orbital_viaducts.glb", "strategy": "world_merged_by_material", "submeshes": 4},
            {"id": "06_distant_towers", "file": "06_distant_towers.glb", "strategy": "world_merged_by_material", "submeshes": 3},
            {"id": "13_floating_slabs", "file": "13_floating_slabs.glb", "strategy": "world_merged_by_material", "submeshes": 2}
        ],
        "cameras": [],
        "lights": []
    }
    
    # 24 Vitrines
    for arch_name, inst_ids in ARCHETYPE_MAP.items():
        glb_name = f"0{arch_name_to_num(arch_name)}_memory_world_{arch_name.lower()}.glb"
        for inst_id in inst_ids:
            ped = bpy.data.objects[f"{inst_id}_Pedestal"]
            # Base of pedestal is at z - 0.275
            base_pos = Vector((ped.location.x, ped.location.y, ped.location.z - 0.275))
            rot_z = ped.rotation_euler.z
            mat_world = Matrix.Translation(base_pos) @ Matrix.Rotation(rot_z, 4, 'Z')
            quat = mat_world.to_quaternion()
            
            # Three.js coordinates: [x, z, -y]
            three_pos = [round(base_pos.x, 6), round(base_pos.z, 6), round(-base_pos.y, 6)]
            three_rot = [0.0, round(rot_z, 6), 0.0]
            
            inst_entry = {
                "id": inst_id,
                "archetype": arch_name.lower(),
                "archetype_glb": glb_name,
                "housing_glb": "07_memory_vitrine_housing.glb",
                "blender_transform": {
                    "position": [round(base_pos.x, 6), round(base_pos.y, 6), round(base_pos.z, 6)],
                    "rotation_euler_xyz": [0.0, 0.0, round(rot_z, 6)],
                    "quaternion_xyzw": [round(quat.x, 6), round(quat.y, 6), round(quat.z, 6), round(quat.w, 6)],
                    "matrix_4x4": [[round(val, 6) for val in row] for row in mat_world]
                },
                "threejs_transform": {
                    "position": three_pos,
                    "rotation_euler_xyz": three_rot
                }
            }
            instances_data["vitrines"].append(inst_entry)
            
    # Sort vitrines alphabetically by ID
    instances_data["vitrines"].sort(key=lambda x: x["id"])
    
    # Scale Anchors
    anchor_info = [
        ("Hero_Scale_Anchor", Vector((-7.5, -31.5, 0.51)), -0.4363),
        ("Stairs_Scale_Anchor", Vector((0.0, -17.5, 1.46)), 0.0),
        ("Pathway_Scale_Anchor", Vector((-10.5, -26.5, 0.51)), -0.3142)
    ]
    for a_id, b_pos, r_z in anchor_info:
        mat_world = Matrix.Translation(b_pos) @ Matrix.Rotation(r_z, 4, 'Z')
        quat = mat_world.to_quaternion()
        instances_data["scale_anchors"].append({
            "id": a_id,
            "glb": "14_scale_anchor_figure.glb",
            "blender_transform": {
                "position": [round(b_pos.x, 6), round(b_pos.y, 6), round(b_pos.z, 6)],
                "rotation_euler_xyz": [0.0, 0.0, round(r_z, 6)],
                "quaternion_xyzw": [round(quat.x, 6), round(quat.y, 6), round(quat.z, 6), round(quat.w, 6)],
                "matrix_4x4": [[round(val, 6) for val in row] for row in mat_world]
            },
            "threejs_transform": {
                "position": [round(b_pos.x, 6), round(b_pos.z, 6), round(-b_pos.y, 6)],
                "rotation_euler_xyz": [0.0, round(r_z, 6), 0.0]
            }
        })
        
    # Cameras
    if "CAMERAS" in bpy.data.collections:
        for obj in bpy.data.collections["CAMERAS"].objects:
            if obj.type == 'CAMERA':
                cam = obj.data
                instances_data["cameras"].append({
                    "name": obj.name,
                    "position": [round(v, 6) for v in obj.location],
                    "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
                    "focal_length_mm": round(cam.lens, 2),
                    "sensor_width_mm": round(cam.sensor_width, 2),
                    "dof_focus_object": cam.dof.focus_object.name if cam.dof and cam.dof.focus_object else None,
                    "fstop": round(cam.dof.aperture_fstop, 2) if cam.dof else None
                })
                
    # Lights
    if "MEMORY_LIGHTING" in bpy.data.collections:
        for obj in bpy.data.collections["MEMORY_LIGHTING"].objects:
            if obj.type == 'LIGHT':
                l = obj.data
                instances_data["lights"].append({
                    "name": obj.name,
                    "type": l.type,
                    "position": [round(v, 6) for v in obj.location],
                    "color_rgb": [round(c, 4) for c in l.color[:3]],
                    "energy_watts": round(l.energy, 2)
                })
                
    with open(INSTANCES_JSON_PATH, "w") as f:
        json.dump(instances_data, f, indent=2)
    print(f"Generated instance registry: {INSTANCES_JSON_PATH} ({os.path.getsize(INSTANCES_JSON_PATH):,} bytes)")

def arch_name_to_num(name):
    m = {'Mountain': 8, 'Neural': 9, 'City': 10, 'Matrix': 11, 'Chrono': 12}
    return m[name]

def main():
    print("\n" + "="*80)
    print("STAGE 03: MEMORY ARCHIVE — MODULAR GLB EXPORT PIPELINE")
    print("="*80)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    # -------------------------------------------------------------------------
    # 01. HERO CORE (25 objects, preserve hierarchy)
    # -------------------------------------------------------------------------
    print("\n[01/14] Exporting 01_astrolabe_hero_core.glb ...")
    core_objs = list(bpy.data.collections["MEMORY_CORE"].objects)
    assert len(core_objs) == 25, f"Expected 25 objects in MEMORY_CORE, found {len(core_objs)}"
    export_glb(os.path.join(ASSETS_DIR, "01_astrolabe_hero_core.glb"), core_objs)
    
    # -------------------------------------------------------------------------
    # 02. DAIS & STAIRS (77 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[02/14] Exporting 02_architecture_dais_stairs.glb ...")
    arch_objs = bpy.data.collections["MEMORY_ARCHITECTURE"].objects
    dais_stairs_objs = [
        o for o in arch_objs 
        if any(k in o.name.lower() for k in ['dais', 'step', 'stair', 'balustrade', 'rail', 'rotunda_deck'])
    ]
    assert len(dais_stairs_objs) == 77, f"Expected 77 dais/stairs objects, found {len(dais_stairs_objs)}"
    merge_and_export_by_material(
        dais_stairs_objs, 
        os.path.join(ASSETS_DIR, "02_architecture_dais_stairs.glb"), 
        "Dais_Stairs"
    )
    
    # -------------------------------------------------------------------------
    # 03. COLUMNS & CANOPY (78 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[03/14] Exporting 03_architecture_columns_canopy.glb ...")
    col_canopy_objs = [o for o in arch_objs if o not in dais_stairs_objs]
    assert len(col_canopy_objs) == 78, f"Expected 78 columns/canopy objects, found {len(col_canopy_objs)}"
    merge_and_export_by_material(
        col_canopy_objs,
        os.path.join(ASSETS_DIR, "03_architecture_columns_canopy.glb"),
        "Columns_Canopy"
    )
    
    # -------------------------------------------------------------------------
    # 04. CONDUITS & VIADUCT (222 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[04/14] Exporting 04_conduits_viaduct.glb ...")
    conduit_objs = list(bpy.data.collections["MEMORY_CONDUITS"].objects)
    assert len(conduit_objs) == 222, f"Expected 222 conduit objects, found {len(conduit_objs)}"
    merge_and_export_by_material(
        conduit_objs,
        os.path.join(ASSETS_DIR, "04_conduits_viaduct.glb"),
        "Conduits_Viaduct"
    )
    
    # -------------------------------------------------------------------------
    # 05. ORBITAL VIADUCTS (81 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[05/14] Exporting 05_orbital_viaducts.glb ...")
    orbital_objs = list(bpy.data.collections["MEMORY_ORBITAL_RINGS"].objects)
    assert len(orbital_objs) == 81, f"Expected 81 orbital objects, found {len(orbital_objs)}"
    merge_and_export_by_material(
        orbital_objs,
        os.path.join(ASSETS_DIR, "05_orbital_viaducts.glb"),
        "Orbital_Viaducts"
    )
    
    # -------------------------------------------------------------------------
    # 06. DISTANT TOWERS (137 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[06/14] Exporting 06_distant_towers.glb ...")
    tower_objs = list(bpy.data.collections["MEMORY_TOWERS"].objects)
    assert len(tower_objs) == 137, f"Expected 137 tower objects, found {len(tower_objs)}"
    merge_and_export_by_material(
        tower_objs,
        os.path.join(ASSETS_DIR, "06_distant_towers.glb"),
        "Distant_Towers"
    )
    
    # -------------------------------------------------------------------------
    # 07. MEMORY VITRINE HOUSING (Canonical 8 parts, origin-centered at base (0,0,0))
    # -------------------------------------------------------------------------
    print("\n[07/14] Exporting 07_memory_vitrine_housing.glb ...")
    ref_vitrine_id = "Pathway_Memory_Crystal_06"
    ref_ped = bpy.data.objects[f"{ref_vitrine_id}_Pedestal"]
    ref_base_pos = Vector((ref_ped.location.x, ref_ped.location.y, ref_ped.location.z - 0.275))
    ref_base_rot = ref_ped.rotation_euler.z
    ref_inv = (Matrix.Translation(ref_base_pos) @ Matrix.Rotation(ref_base_rot, 4, 'Z')).inverted()
    
    housing_parts = ['Pedestal', 'AmberCollar', 'Bracket', 'Bracket.001', 'Bracket.002', 'Bracket.003', 'CrystalPrism', 'TopCap']
    temp_col = get_or_create_temp_collection("EXPORT_TEMP")
    canonical_housing_objs = []
    for part in housing_parts:
        src_obj = bpy.data.objects[f"{ref_vitrine_id}_{part}"]
        eval_obj = src_obj.evaluated_get(depsgraph)
        me_eval = eval_obj.to_mesh()
        # Transform into canonical vitrine space
        local_matrix = ref_inv @ src_obj.matrix_world
        me_eval.transform(local_matrix)
        
        canonical_name = f"Vitrine_{part.replace('.', '_')}"
        new_mesh = bpy.data.meshes.new(canonical_name)
        bm = bmesh.new()
        bm.from_mesh(me_eval)
        bm.to_mesh(new_mesh)
        bm.free()
        eval_obj.to_mesh_clear()
        
        if src_obj.material_slots and src_obj.material_slots[0].material:
            new_mesh.materials.append(src_obj.material_slots[0].material)
            
        new_obj = bpy.data.objects.new(canonical_name, new_mesh)
        temp_col.objects.link(new_obj)
        canonical_housing_objs.append(new_obj)
        
    export_glb(os.path.join(ASSETS_DIR, "07_memory_vitrine_housing.glb"), canonical_housing_objs)
    clean_temp_collection("EXPORT_TEMP")
    
    # -------------------------------------------------------------------------
    # 08 - 12. FIVE INTERNAL MEMORY WORLD ARCHETYPES
    # -------------------------------------------------------------------------
    archetype_configs = [
        (8, "mountain", "Pathway_Memory_Crystal_06", [
            'MountainRidge_1', 'MountainRidge_2', 'MountainRidge_3',
            'MountainRidge_4', 'MountainRidge_5', 'SubPeak_1', 'SubPeak_2'
        ]),
        (9, "neural", "Pathway_Memory_Crystal_07", [
            'NeuralTrunk', 'Branch_1', 'Synapse_1', 'Branch_2', 'Synapse_2',
            'Branch_3', 'Synapse_3', 'Branch_4', 'Synapse_4', 'Branch_5', 'Synapse_5'
        ]),
        (10, "city", "Pathway_Memory_Crystal_03", [
            'CitySpire_1', 'CitySpireTip_1', 'CitySpire_2', 'CitySpireTip_2',
            'CitySpire_3', 'CitySpireTip_3', 'CitySpire_4', 'CitySpireTip_4',
            'CitySpire_5', 'CitySpireTip_5', 'CitySpire_6', 'CitySpireTip_6',
            'CitySpire_7', 'CitySpireTip_7'
        ]),
        (11, "matrix", "Pathway_Memory_Crystal_04", [
            'MatrixCore', 'MatrixCage'
        ]),
        (12, "chrono", "Pathway_Memory_Crystal_05", [
            'ChronoRing_1', 'ChronoRing_2', 'ChronoRing_3', 'ChronoCore'
        ])
    ]
    
    for idx, arch_name, ref_crystal, parts in archetype_configs:
        glb_filename = f"0{idx}_memory_world_{arch_name}.glb" if idx < 10 else f"{idx}_memory_world_{arch_name}.glb"
        print(f"\n[{idx:02d}/14] Exporting {glb_filename} (Canonical Archetype: {arch_name.title()}) ...")
        
        ped = bpy.data.objects[f"{ref_crystal}_Pedestal"]
        base_pos = Vector((ped.location.x, ped.location.y, ped.location.z - 0.275))
        base_rot = ped.rotation_euler.z
        inv_mat = (Matrix.Translation(base_pos) @ Matrix.Rotation(base_rot, 4, 'Z')).inverted()
        
        temp_col = get_or_create_temp_collection("EXPORT_TEMP")
        arch_objs = []
        for p in parts:
            src_obj = bpy.data.objects[f"{ref_crystal}_{p}"]
            eval_obj = src_obj.evaluated_get(depsgraph)
            me_eval = eval_obj.to_mesh()
            local_matrix = inv_mat @ src_obj.matrix_world
            me_eval.transform(local_matrix)
            
            canonical_name = f"World_{arch_name}_{p}"
            new_mesh = bpy.data.meshes.new(canonical_name)
            bm = bmesh.new()
            bm.from_mesh(me_eval)
            bm.to_mesh(new_mesh)
            bm.free()
            eval_obj.to_mesh_clear()
            
            if src_obj.material_slots and src_obj.material_slots[0].material:
                new_mesh.materials.append(src_obj.material_slots[0].material)
                
            new_obj = bpy.data.objects.new(canonical_name, new_mesh)
            temp_col.objects.link(new_obj)
            arch_objs.append(new_obj)
            
        export_glb(os.path.join(ASSETS_DIR, glb_filename), arch_objs)
        clean_temp_collection("EXPORT_TEMP")
        
    # -------------------------------------------------------------------------
    # 13. FLOATING DATA SLABS (36 objects, world-space merged by material)
    # -------------------------------------------------------------------------
    print("\n[13/14] Exporting 13_floating_slabs.glb ...")
    slab_objs = [o for o in bpy.data.collections["MEMORY_CRYSTALS"].objects if 'slab' in o.name.lower()]
    assert len(slab_objs) == 36, f"Expected 36 floating slab objects, found {len(slab_objs)}"
    merge_and_export_by_material(
        slab_objs,
        os.path.join(ASSETS_DIR, "13_floating_slabs.glb"),
        "Floating_Slabs"
    )
    
    # -------------------------------------------------------------------------
    # 14. HUMAN SCALE ANCHOR (5 parts merged, origin-centered at feet (0,0,0))
    # -------------------------------------------------------------------------
    print("\n[14/14] Exporting 14_scale_anchor_figure.glb ...")
    ref_anchor_prefix = "Stairs_Scale_Anchor"
    feet_origin = Vector((0.0, -17.5, 1.46))
    inv_feet_mat = Matrix.Translation(feet_origin).inverted()
    
    anchor_parts = ['Head', 'Torso', 'Coat', 'Boot_L', 'Boot_R']
    temp_col = get_or_create_temp_collection("EXPORT_TEMP")
    
    bm_anchor = bmesh.new()
    anchor_mat = bpy.data.materials.get("MAT_Human_Silhouette_Black")
    for part in anchor_parts:
        src_obj = bpy.data.objects[f"{ref_anchor_prefix}_{part}"]
        eval_obj = src_obj.evaluated_get(depsgraph)
        me_eval = eval_obj.to_mesh()
        me_eval.transform(inv_feet_mat @ src_obj.matrix_world)
        bm_anchor.from_mesh(me_eval)
        eval_obj.to_mesh_clear()
        
    new_mesh = bpy.data.meshes.new("Scale_Anchor_Figure")
    bm_anchor.to_mesh(new_mesh)
    bm_anchor.free()
    if anchor_mat:
        new_mesh.materials.append(anchor_mat)
        
    anchor_obj = bpy.data.objects.new("Scale_Anchor_Figure", new_mesh)
    temp_col.objects.link(anchor_obj)
    
    export_glb(os.path.join(ASSETS_DIR, "14_scale_anchor_figure.glb"), [anchor_obj])
    clean_temp_collection("EXPORT_TEMP")
    
    # -------------------------------------------------------------------------
    # GENERATE INSTANCE REGISTRY JSON
    # -------------------------------------------------------------------------
    print("\nGenerating stage03_memory_instances.json ...")
    build_instance_metadata()
    
    print("\n" + "="*80)
    print("PHASE 1 EXPORT COMPLETED SUCCESSFULLY!")
    print("="*80)

if __name__ == "__main__":
    main()
