#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.8: Controlled Single-Variable Experiment Sweeps (Variants A - G)
===============================================================================
Sweeps 7 conceptual subsystems across all 3 production cameras:
  - Variant Baseline (Phase 2.7)
  - Variant A: Atmospheric gradient refinement
  - Variant B: Reactor-to-dais warm-light distribution
  - Variant C: Foreground stair warm spill
  - Variant D: Floor reflection balance
  - Variant E: Colonnade shadow/midtone distribution
  - Variant F: Highlight rolloff & tone-mapping refinement
  - Variant G: Integrated Final Candidate
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
REFS_DIR = os.path.join(BLEND_DIR, "references", "stage03_memory")

PORT = 5200
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

VIEWS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Cinematic Hero Establishing",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
    }
]

# Baseline Phase 2.7 Configuration
BASE_CONFIG = {
    "variant": "P27_BASE",
    "toneMapping": "ACESFilmic",
    "exposure": 0.96,
    "envOptions": {
        "zenithColor": "#16202c",
        "upperSkyColor": "#202c3c",
        "horizonColor": "#4e6278",
        "lowerHorizonColor": "#283648",
        "groundColor": "#0e151e",
        "warmGlowRadius": 118,
        "warmGlowIntensity": 0.42,
        "cloudBands": True
    },
    "fogType": "linear",
    "fogNear": 19.5,
    "fogFar": 182.0,
    "fogColor": "#4e6278",
    "hemisphereIntensity": 0.30,
    "hemisphereSkyColor": "#4e6278",
    "hemisphereGroundColor": "#18202a",
    "ambientIntensity": 0.44,
    "ambientColor": "#1e2c3c",
    "coreIntensity": 11.2,
    "coreColor": "#ffa030",
    "daisBounceIntensity": 7.0,
    "daisBounceRange": 35.0,
    "daisBounceColor": "#ff9624",
    "tertiaryStairsIntensity": 2.0,
    "tertiaryStairsColor": "#ff9028",
    "tertiaryStairsRange": 24.0,
    "tertiaryStairsPosition": [0, 5.2, 14.0],
    "pedestalIntensity": 4.2,
    "canopyIntensity": 4.2,
    "rimBackIntensity": 3.0,
    "rimBackColor": "#5c80d1",
    "planarReflection": True,
    "planarIntensity": 0.36,
    "planarTint": "#0e1622",
    "floorColor": "#0e141c",
    "floorRoughness": 0.25,
    "floorClearcoat": 0.60,
    "floorClearcoatRoughness": 0.13,
    "glassColor": "#141e2a",
    "glassOpacity": 0.20,
    "amberCoreEmissiveIntensity": 2.4,
    "amberEnergyEmissiveIntensity": 0.42,
    "renderMode": "standard"
}

VARIANTS = [
    {
        "id": "variant_baseline_p27",
        "name": "Phase 2.7 Baseline",
        "description": "Baseline established at the end of Phase 2.7.",
        "config": BASE_CONFIG
    },
    {
        "id": "variant_a_atmosphere",
        "name": "Variant A: Atmospheric Gradient Refinement",
        "description": "Layered multi-stop sky dome with warm horizon corona and softer haze integration.",
        "config": {
            **BASE_CONFIG,
            "envOptions": {
                "zenithColor": "#182230",
                "upperSkyColor": "#2d3b4c",
                "horizonColor": "#5c6d80",
                "lowerHorizonColor": "#3a4b5d",
                "groundColor": "#0e151e",
                "warmGlowRadius": 135,
                "warmGlowIntensity": 0.50,
                "cloudBands": True
            },
            "fogColor": "#54667a",
            "fogNear": 19.0,
            "fogFar": 180.0
        }
    },
    {
        "id": "variant_b_reactor_warmth",
        "name": "Variant B: Reactor-to-Dais Warm-Light Distribution",
        "description": "Astrolabe core emissive boost, warm rim back aperture, expanded dais GI bounce.",
        "config": {
            **BASE_CONFIG,
            "coreIntensity": 12.5,
            "coreColor": "#ffa232",
            "daisBounceIntensity": 8.0,
            "daisBounceRange": 38.0,
            "daisBounceColor": "#ff9824",
            "rimBackIntensity": 3.2,
            "rimBackColor": "#ffb244",
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5,
            "amberCoreEmissiveIntensity": 3.5,
            "amberEnergyEmissiveIntensity": 0.65
        }
    },
    {
        "id": "variant_c_stairs_spill",
        "name": "Variant C: Foreground Stair Warm Spill",
        "description": "Tertiary stairs grazing light forward projection reaching foreground vitrines.",
        "config": {
            **BASE_CONFIG,
            "tertiaryStairsIntensity": 3.5,
            "tertiaryStairsRange": 30.0,
            "tertiaryStairsColor": "#ff9428",
            "tertiaryStairsPosition": [0, 5.0, 15.5],
            "pathLightIntensity": 0.20
        }
    },
    {
        "id": "variant_d_floor_reflection",
        "name": "Variant D: Floor Reflection Balance",
        "description": "Neutral dark obsidian/slate base, neutral graphite planar tint, refined clearcoat.",
        "config": {
            **BASE_CONFIG,
            "floorColor": "#121518",
            "planarTint": "#141618",
            "planarIntensity": 0.38,
            "floorClearcoat": 0.65,
            "floorRoughness": 0.24,
            "floorClearcoatRoughness": 0.12
        }
    },
    {
        "id": "variant_e_colonnade_shadows",
        "name": "Variant E: Colonnade Shadow/Midtone Distribution",
        "description": "Neutral slate hemisphere ground bounce, neutral ambient fill, softened key light.",
        "config": {
            **BASE_CONFIG,
            "hemisphereIntensity": 0.34,
            "hemisphereSkyColor": "#56687c",
            "hemisphereGroundColor": "#202226",
            "ambientIntensity": 0.46,
            "ambientColor": "#242830",
            "rotundaKeyIntensity": 1.6,
            "rotundaKeyColor": "#586e88"
        }
    },
    {
        "id": "variant_f_highlight_rolloff",
        "name": "Variant F: Highlight Rolloff & Tone Mapping",
        "description": "Exposure calibrated to 0.98, restrained sun key to eliminate pillar hot streaks.",
        "config": {
            **BASE_CONFIG,
            "exposure": 0.98,
            "sunIntensity": 0.70,
            "sunColor": "#687f98"
        }
    },
    {
        "id": "variant_g_integrated",
        "name": "Variant G: Integrated Final Candidate",
        "description": "Full spatial lighting convergence combining validated parameters from Variants A-F.",
        "config": {
            "variant": "G_INTEGRATED",
            "toneMapping": "ACESFilmic",
            "exposure": 0.98,
            "envOptions": {
                "zenithColor": "#182230",
                "upperSkyColor": "#2d3b4c",
                "horizonColor": "#5c6d80",
                "lowerHorizonColor": "#3a4b5d",
                "groundColor": "#0e151e",
                "warmGlowRadius": 135,
                "warmGlowIntensity": 0.50,
                "cloudBands": True
            },
            "fogType": "linear",
            "fogNear": 19.0,
            "fogFar": 180.0,
            "fogColor": "#54667a",
            "hemisphereIntensity": 0.34,
            "hemisphereSkyColor": "#56687c",
            "hemisphereGroundColor": "#202226",
            "ambientIntensity": 0.46,
            "ambientColor": "#242830",
            "coreIntensity": 12.5,
            "coreColor": "#ffa232",
            "daisBounceIntensity": 8.0,
            "daisBounceRange": 38.0,
            "daisBounceColor": "#ff9824",
            "tertiaryStairsIntensity": 3.5,
            "tertiaryStairsRange": 30.0,
            "tertiaryStairsColor": "#ff9428",
            "tertiaryStairsPosition": [0, 5.0, 15.5],
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5,
            "rimBackIntensity": 3.2,
            "rimBackColor": "#ffb244",
            "rotundaKeyIntensity": 1.6,
            "rotundaKeyColor": "#586e88",
            "sunIntensity": 0.70,
            "sunColor": "#687f98",
            "pathLightIntensity": 0.20,
            "planarReflection": True,
            "planarIntensity": 0.38,
            "planarTint": "#141618",
            "floorColor": "#121518",
            "floorRoughness": 0.24,
            "floorClearcoat": 0.65,
            "floorClearcoatRoughness": 0.12,
            "glassColor": "#141e2a",
            "glassOpacity": 0.20,
            "amberCoreEmissiveIntensity": 3.5,
            "amberEnergyEmissiveIntensity": 0.65,
            "renderMode": "standard"
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
        "target_mean_rgb": c_mean,
        "render_mean_rgb": r_mean,
        "total_error_abs": float(np.sum(diff))
    }

def analyze_full_and_regional_metrics(ref_path, render_path):
    img1 = Image.open(ref_path).convert('RGB')
    img2 = Image.open(render_path).convert('RGB')
    
    if img1.size != (1920, 1080):
        img1 = img1.resize((1920, 1080), Image.Resampling.LANCZOS)
    if img2.size != (1920, 1080):
        img2 = img2.resize((1920, 1080), Image.Resampling.LANCZOS)
        
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
    
    regions_def = {
        "floor": (slice(int(h * 0.65), h), slice(0, w)),
        "core": (slice(int(h * 0.25), int(h * 0.65)), slice(int(w * 0.35), int(w * 0.65))),
        "sky": (slice(0, int(h * 0.35)), slice(0, w)),
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

    warm_pct = float(np.mean((arr2[:,:,0] > arr2[:,:,2] * 1.15) & (arr2[:,:,0] > 30)) * 100.0)
        
    return {
        "overall": {
            "mae": round(overall_mae, 4),
            "rmse": round(overall_rmse, 4),
            "psnr": round(psnr, 2),
            "ssim": round(float(ssim), 4),
            "max_diff": round(float(np.max(diff)), 2),
            "mean_lum": round(float(np.mean(lum2)), 2),
            "mean_rgb": [round(float(np.mean(arr2[:,:,ch])), 2) for ch in range(3)],
            "warm_pixels_pct": round(warm_pct, 2)
        },
        "regions": region_results
    }

def main():
    print("\n" + "="*80)
    print("PHASE 2.8: CONTROLLED EXPERIMENT SWEEPS (VARIANTS A - G)")
    print("="*80)
    
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    try:
        print(f"Waiting for Vite dev server on port {PORT}...")
        if not wait_for_server(URL, timeout=30):
            print("ERROR: Vite server failed to respond.")
            sys.exit(1)
        print("Vite server ready.")
        
        experiments_output = {
            "metadata": {
                "phase": "2.8",
                "date": time.strftime("%Y-%m-%d"),
                "experiment_count": len(VARIANTS),
                "cameras": [v["cam"] for v in VIEWS]
            },
            "variants": {}
        }
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--use-gl=angle",
                    "--use-angle=metal",
                    "--enable-webgl",
                    "--no-sandbox"
                ]
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            print(f"Navigating to {URL}...")
            page.goto(URL, wait_until="networkidle")
            
            page.wait_for_function("() => window.__STAGE03_READY__ === true", timeout=60000)
            print("Three.js Stage 03 Scene Ready.")
            
            for v_entry in VARIANTS:
                var_id = v_entry["id"]
                var_name = v_entry["name"]
                var_desc = v_entry["description"]
                config = v_entry["config"]
                
                print(f"\nEvaluating {var_name} ({var_id})...")
                print(f"  Description: {var_desc}")
                
                page.evaluate(f"window.setDiagnosticConfig({json.dumps(config)})")
                time.sleep(0.8)
                
                var_results = {
                    "id": var_id,
                    "name": var_name,
                    "description": var_desc,
                    "views": {}
                }
                
                for v in VIEWS:
                    key = v["key"]
                    cam = v["cam"]
                    title = v["title"]
                    ref_path = v["ref"]
                    
                    page.evaluate(f"window.setCameraView('{cam}', true)")
                    time.sleep(0.4)
                    
                    for _ in range(6):
                        page.evaluate("window.renderFrame()")
                        
                    tmp_render_path = os.path.join(RENDERS_DIR, f"tmp_p28_{var_id}_{key}.png")
                    page.screenshot(path=tmp_render_path)
                    
                    perf = page.evaluate("window.getPerformanceMetrics()")
                    metrics = analyze_full_and_regional_metrics(ref_path, tmp_render_path)
                    
                    var_results["views"][key] = {
                        "camera": cam,
                        "title": title,
                        "performance": perf,
                        "metrics": metrics
                    }
                    
                    print(f"    [{key.upper()}] MAE: {metrics['overall']['mae']} | PSNR: {metrics['overall']['psnr']} dB | SSIM: {metrics['overall']['ssim']} | MeanLum: {metrics['overall']['mean_lum']} | Warm%: {metrics['overall']['warm_pixels_pct']}% | Core MAE: {metrics['regions']['core']['mae']} | Floor MAE: {metrics['regions']['floor']['mae']} | {perf['frameTimeMs']} ms")
                    
                    # Clean up temporary test render
                    if os.path.exists(tmp_render_path):
                        os.remove(tmp_render_path)
                        
                experiments_output["variants"][var_id] = var_results
                
            browser.close()
            
        out_json = os.path.join(ASSETS_DIR, "stage03_phase28_experiments.json")
        with open(out_json, "w") as f:
            json.dump(experiments_output, f, indent=2)
            
        print(f"\nAll experiments complete. Results saved to: {out_json}")
        print("="*80)
        
    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
