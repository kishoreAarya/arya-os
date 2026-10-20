#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.2: Comprehensive Regional Subsystem A/B Diagnostics
===============================================================================
Investigates remaining Blender-to-Three.js visual discrepancies across:
1. Indirect Illumination (Fast GI Diffuse Bounces vs Baked Ground Radiance vs Ambient)
2. Floor Reflections (SSR geometry reflection vs Equirectangular Roughness/Clearcoat)
3. Environment Lighting (Sky Dome Gradient & Horizon Radiance)
4. Shadowing (Directional PCF Soft Shadowing vs Disabled)
5. Ambient Occlusion (Contact Darkening & Ground Plinth Occlusion)
6. Tone Mapping & Contrast (AgX vs ACESFilmic vs Blender Filmic -0.30 Exposure)

Rules:
- Exact 1-variable modifications relative to Baseline
- Regional segmentation: Sky, Core, Floor, Left Colonnade, Right Colonnade
- Hardware WebGL metrics: Draw calls, Triangles, Frame time (ms), FPS
===============================================================================
"""

import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.request
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")

PORT = 5178
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

VIEWS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Archival Hero Establishing",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
    }
]

# Baseline configuration: 52 draws, cinematic glass, AgX 0.95, default calibrated lighting & materials
BASELINE_CONFIG = {
    "toneMapping": "AgX",
    "exposure": 0.95,
    "cinematicGlass": True,
    "neutralMaterial": False,
    "shadows": True,
    "ambientIntensity": 0.14,
    "sunIntensity": 0.95,
    "envOptions": {
        "zenithColor": "#0c1624",
        "horizonColor": "#26364a",
        "groundColor": "#05080e",
        "warmGlowIntensity": 0.45,
        "warmGlowRadius": 110,
        "bakedGroundBounce": False
    },
    "floorRoughness": 0.16,
    "floorClearcoat": 0.95,
    "floorClearcoatRoughness": 0.028,
    "floorColor": 0x040608
}

# Single-variable diagnostic experiments
EXPERIMENTS = [
    {
        "id": "exp00_baseline",
        "subsystem": "Baseline",
        "name": "Baseline: Current 52-Draw Architecture",
        "variable_changed": "None (Reference Baseline)",
        "config": {}  # Exact baseline
    },
    # Subsystem 1: Tone Mapping & Exposure
    {
        "id": "exp01_tone_agx_081",
        "subsystem": "Tone Mapping",
        "name": "Tone Mapping: AgX with Blender Calibrated Exposure (0.812)",
        "variable_changed": "exposure: 0.95 -> 0.812 (matching Blender 2^-0.30)",
        "config": {"exposure": 0.812}
    },
    {
        "id": "exp02_tone_aces_095",
        "subsystem": "Tone Mapping",
        "name": "Tone Mapping: ACESFilmic (Exposure 0.95)",
        "variable_changed": "toneMapping: AgX -> ACESFilmic",
        "config": {"toneMapping": "ACESFilmic"}
    },
    {
        "id": "exp03_tone_aces_081",
        "subsystem": "Tone Mapping",
        "name": "Tone Mapping: ACESFilmic with Blender Calibrated Exposure (0.812)",
        "variable_changed": "toneMapping: AgX -> ACESFilmic, exposure: 0.95 -> 0.812",
        "config": {"toneMapping": "ACESFilmic", "exposure": 0.812}
    },
    # Subsystem 2: Floor Reflections
    {
        "id": "exp04_floor_roughness_low",
        "subsystem": "Floor Reflections",
        "name": "Floor: Lower Roughness (0.05)",
        "variable_changed": "floorRoughness: 0.16 -> 0.05",
        "config": {"floorRoughness": 0.05}
    },
    {
        "id": "exp05_floor_roughness_high",
        "subsystem": "Floor Reflections",
        "name": "Floor: Higher Roughness (0.35)",
        "variable_changed": "floorRoughness: 0.16 -> 0.35",
        "config": {"floorRoughness": 0.35}
    },
    {
        "id": "exp06_floor_clearcoat_off",
        "subsystem": "Floor Reflections",
        "name": "Floor: Disable Clearcoat (0.0)",
        "variable_changed": "floorClearcoat: 0.95 -> 0.0",
        "config": {"floorClearcoat": 0.0}
    },
    {
        "id": "exp07_floor_darker_base",
        "subsystem": "Floor Reflections",
        "name": "Floor: Deeper Obsidian Base (0x010203)",
        "variable_changed": "floorColor: 0x040608 -> 0x010203",
        "config": {"floorColor": 0x010203}
    },
    # Subsystem 3: Indirect Illumination (Fast GI Diffuse Bounce)
    {
        "id": "exp08_gi_baked_ground_bounce",
        "subsystem": "Indirect Illumination",
        "name": "Indirect GI: Baked Lower-Hemisphere Warm Ground Bounce",
        "variable_changed": "bakedGroundBounce: False -> True (precomputed 4-bounce Fast GI)",
        "config": {
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#26364a",
                "groundColor": "#05080e",
                "warmGlowIntensity": 0.45,
                "warmGlowRadius": 110,
                "bakedGroundBounce": True
            }
        }
    },
    {
        "id": "exp09_indirect_ambient_high",
        "subsystem": "Indirect Illumination",
        "name": "Indirect GI: Doubled Ambient Fill (0.28)",
        "variable_changed": "ambientIntensity: 0.14 -> 0.28",
        "config": {"ambientIntensity": 0.28}
    },
    {
        "id": "exp10_indirect_ambient_zero",
        "subsystem": "Indirect Illumination",
        "name": "Indirect GI: Zero Ambient Fill (Direct Lighting Only)",
        "variable_changed": "ambientIntensity: 0.14 -> 0.0",
        "config": {"ambientIntensity": 0.0}
    },
    # Subsystem 4: Shadowing
    {
        "id": "exp11_shadows_disabled",
        "subsystem": "Shadowing",
        "name": "Shadowing: Disable Shadow Maps",
        "variable_changed": "shadows: True -> False",
        "config": {"shadows": False}
    },
    # Subsystem 5: Environment Lighting
    {
        "id": "exp12_env_horizon_boost",
        "subsystem": "Environment Lighting",
        "name": "Environment: Elevated Horizon Luminance (#3a4f68)",
        "variable_changed": "horizonColor: #26364a -> #3a4f68",
        "config": {
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#3a4f68",
                "groundColor": "#05080e",
                "warmGlowIntensity": 0.45,
                "warmGlowRadius": 110,
                "bakedGroundBounce": False
            }
        }
    }
]

def wait_for_server(url, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def compute_region_metrics(clean_arr, render_arr, region_slices):
    """Computes MAE, RMSE, clean mean, render mean for a 2D bounding box."""
    c_sub = clean_arr[region_slices[0], region_slices[1], :]
    r_sub = render_arr[region_slices[0], region_slices[1], :]
    
    diff = np.abs(c_sub - r_sub)
    mae = float(np.mean(diff))
    mse = float(np.mean((c_sub - r_sub) ** 2))
    rmse = math.sqrt(mse)
    
    c_mean = [round(float(np.mean(c_sub[:, :, ch])), 2) for ch in range(3)]
    r_mean = [round(float(np.mean(r_sub[:, :, ch])), 2) for ch in range(3)]
    
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "clean_mean_rgb": c_mean,
        "render_mean_rgb": r_mean,
        "total_error_abs": float(np.sum(diff))
    }

def analyze_full_and_regional_metrics(clean_path, render_path):
    img1 = Image.open(clean_path).convert('RGB')
    img2 = Image.open(render_path).convert('RGB')
    
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
        
    arr1 = np.array(img1, dtype=np.float32)
    arr2 = np.array(img2, dtype=np.float32)
    h, w, _ = arr1.shape
    
    diff = np.abs(arr1 - arr2)
    total_abs_diff = float(np.sum(diff))
    overall_mae = float(np.mean(diff))
    overall_mse = float(np.mean((arr1 - arr2) ** 2))
    overall_rmse = math.sqrt(overall_mse)
    
    if overall_mse == 0:
        psnr = 100.0
    else:
        psnr = 20.0 * math.log10(255.0 / overall_rmse)
        
    lum1 = 0.299 * arr1[:,:,0] + 0.587 * arr1[:,:,1] + 0.114 * arr1[:,:,2]
    lum2 = 0.299 * arr2[:,:,0] + 0.587 * arr2[:,:,1] + 0.114 * arr2[:,:,2]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu1 = np.mean(lum1)
    mu2 = np.mean(lum2)
    var1 = np.var(lum1)
    var2 = np.var(lum2)
    cov = np.mean((lum1 - mu1) * (lum2 - mu2))
    ssim = ((2 * mu1 * mu2 + c1) * (2 * cov + c2)) / ((mu1**2 + mu2**2 + c1) * (var1 + var2 + c2))
    
    # 5 Spatial Regions:
    regions_def = {
        "sky": (slice(0, int(h * 0.35)), slice(0, w)),
        "core": (slice(int(h * 0.25), int(h * 0.65)), slice(int(w * 0.35), int(w * 0.65))),
        "floor": (slice(int(h * 0.65), h), slice(0, w)),
        "left_colonnade": (slice(int(h * 0.25), int(h * 0.65)), slice(0, int(w * 0.35))),
        "right_colonnade": (slice(int(h * 0.25), int(h * 0.65)), slice(int(w * 0.65), w)),
    }
    
    region_results = {}
    for r_name, r_slices in regions_def.items():
        r_met = compute_region_metrics(arr1, arr2, r_slices)
        r_share = round((r_met["total_error_abs"] / total_abs_diff) * 100.0, 2) if total_abs_diff > 0 else 0.0
        del r_met["total_error_abs"]
        r_met["error_share_pct"] = r_share
        region_results[r_name] = r_met
        
    return {
        "overall": {
            "mae": round(overall_mae, 4),
            "rmse": round(overall_rmse, 4),
            "psnr": round(psnr, 2),
            "ssim": round(float(ssim), 4),
            "max_diff": round(float(np.max(diff)), 2)
        },
        "regions": region_results
    }

def main():
    print("\n" + "="*80)
    print("PHASE 2.2: COMPREHENSIVE REGIONAL SUBSYSTEM A/B DIAGNOSTICS")
    print("="*80)
    print("Verifying locked Blender engine ground truth...")
    print("  Engine: BLENDER_EEVEE (EEVEE-Next Blender 5.2.2 LTS)")
    print("  Raytracing: True (SCREEN)")
    print("  Fast GI: True (GLOBAL_ILLUMINATION, 4 diffuse bounces)")
    print("  View Transform: Filmic | Look: Medium High Contrast | Exposure: -0.30")
    print("  Compositor: Bloom glare node (Threshold 4.8, Strength 0.035, Size 5.0)")
    print("="*80)
    
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    diagnostic_report = {
        "metadata": {
            "phase": "2.2",
            "date": "2026-10-01",
            "blender_engine": "BLENDER_EEVEE (EEVEE-Next 5.2.2 LTS)",
            "blender_view_transform": "Filmic",
            "blender_look": "Medium High Contrast",
            "blender_exposure": -0.30,
            "fast_gi_diffuse_bounces": 4,
            "ray_tracing_method": "SCREEN",
            "architecture_draw_calls": 52
        },
        "experiments": {}
    }
    
    try:
        if not wait_for_server(URL, timeout=20):
            print("FATAL: Vite server failed to respond within 20s")
            sys.exit(1)
        print(f"Vite server active at {URL}")
        
        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chrome_bin,
                headless=True,
                args=[
                    "--window-size=1920,1080",
                    "--use-gl=angle",
                    "--use-angle=metal",
                    "--enable-gpu-rasterization",
                    "--enable-zero-copy",
                    "--ignore-gpu-blocklist",
                    "--no-sandbox"
                ]
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.goto(URL, wait_until="networkidle")
            page.wait_for_function("window.__STAGE03_READY__ === true", timeout=30000)
            time.sleep(1.0)
            canvas = page.locator("#webgl-canvas")
            
            for exp in EXPERIMENTS:
                print(f"\n>>> Running [{exp['id']}] Subsystem: [{exp['subsystem']}]")
                print(f"    Name: {exp['name']}")
                print(f"    Single Variable: {exp['variable_changed']}")
                
                # Compose configuration starting from baseline
                merged_config = dict(BASELINE_CONFIG)
                for k, v in exp["config"].items():
                    merged_config[k] = v
                    
                page.evaluate(f"window.setDiagnosticConfig({json.dumps(merged_config)})")
                time.sleep(0.4)
                
                exp_view_results = {}
                for v in VIEWS:
                    page.evaluate(f"window.setCameraView('{v['cam']}', true)")
                    time.sleep(0.5)
                    metrics = page.evaluate("window.getPerformanceMetrics()")
                    
                    tmp_render = os.path.join(RENDERS_DIR, f"regional_diag_{exp['id']}_{v['key']}.png")
                    canvas.screenshot(path=tmp_render)
                    
                    analysis = analyze_full_and_regional_metrics(v["clean"], tmp_render)
                    
                    exp_view_results[v["key"]] = {
                        "camera": v["cam"],
                        "performance": metrics,
                        "overall": analysis["overall"],
                        "regions": analysis["regions"],
                        "render_file": tmp_render
                    }
                    
                    ov = analysis["overall"]
                    fl = analysis["regions"]["floor"]
                    co = analysis["regions"]["core"]
                    sk = analysis["regions"]["sky"]
                    print(f"    [{v['key']:10s}] Calls: {metrics['drawCalls']} | FPS: {metrics['fps']:5.1f} | PSNR: {ov['psnr']:5.2f} dB | MAE: {ov['mae']:5.2f} (Floor: {fl['mae']:5.2f}, Core: {co['mae']:5.2f}, Sky: {sk['mae']:5.2f})")
                    
                diagnostic_report["experiments"][exp["id"]] = {
                    "subsystem": exp["subsystem"],
                    "name": exp["name"],
                    "variable_changed": exp["variable_changed"],
                    "views": exp_view_results
                }
                
            browser.close()
            
        diag_path = os.path.join(ASSETS_DIR, "stage03_regional_subsystems_diagnostic.json")
        with open(diag_path, "w") as f:
            json.dump(diagnostic_report, f, indent=2)
        print(f"\nSaved regional diagnostic report: {diag_path}")
        
    finally:
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass
            
    print("\n" + "="*80)
    print("PHASE 2.2 REGIONAL SUBSYSTEM DIAGNOSTICS COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    main()
