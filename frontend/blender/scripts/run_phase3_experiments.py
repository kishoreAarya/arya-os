#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 3: Single-Variable Cinematic Post-Processing Experiments (Variants A - E)
===============================================================================
Sweeps single-variable cinematic post-processing variations across all 3 production cameras:
  - Baseline: Phase 2.9 baseline (cinematic pass disabled)
  - Experiment A: Subtle Lens Vignette (darkness 0.15, offset 1.15)
  - Experiment B: Fine Monochromatic Film Grain (intensity 0.012)
  - Experiment C: Filmic Micro-Contrast (contrast 1.02)
  - Experiment D: Highlight Diffusion / Halation Tuning (threshold 0.90, strength 0.025, radius 0.45)
  - Experiment E: Atmospheric Color Integration Tint (tint [1.002, 1.000, 0.998])
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

# Phase 2.9 Baseline Configuration (Locked Ground Truth)
P29_BASE_CONFIG = {
    "variant": "P29_BASE",
    "toneMapping": "ACESFilmic",
    "exposure": 0.965,
    "envOptions": {
        "zenithColor": "#182230",
        "upperSkyColor": "#2c3a4b",
        "horizonColor": "#5a6b7e",
        "lowerHorizonColor": "#38495a",
        "groundColor": "#0e151e",
        "warmGlowRadius": 132,
        "warmGlowIntensity": 0.49,
        "cloudBands": True
    },
    "fogType": "linear",
    "fogNear": 19.0,
    "fogFar": 182.0,
    "fogColor": "#52657a",
    "hemisphereIntensity": 0.32,
    "hemisphereSkyColor": "#56687c",
    "hemisphereGroundColor": "#202226",
    "ambientIntensity": 0.44,
    "ambientColor": "#22262e",
    "coreIntensity": 12.0,
    "coreColor": "#ffa232",
    "daisBounceIntensity": 7.8,
    "daisBounceRange": 36.5,
    "daisBounceColor": "#ff9824",
    "tertiaryStairsIntensity": 3.0,
    "tertiaryStairsRange": 28.0,
    "tertiaryStairsColor": "#ff9226",
    "tertiaryStairsPosition": [0, 5.0, 15.0],
    "pedestalIntensity": 4.4,
    "canopyIntensity": 4.4,
    "rimBackIntensity": 3.2,
    "rimBackColor": "#ffb040",
    "rotundaKeyIntensity": 1.6,
    "rotundaKeyColor": "#566c86",
    "sunIntensity": 0.68,
    "sunColor": "#647b94",
    "pathLightIntensity": 0.18,
    "planarReflection": True,
    "planarIntensity": 0.35,
    "planarTint": "#141618",
    "floorColor": "#121518",
    "floorRoughness": 0.26,
    "floorClearcoat": 0.64,
    "floorClearcoatRoughness": 0.13,
    "glassColor": "#141e2a",
    "glassOpacity": 0.20,
    "amberCoreEmissiveIntensity": 3.0,
    "amberEnergyEmissiveIntensity": 0.58,
    "renderMode": "bloom",
    "bloomConfig": {
        "threshold": 0.92,
        "strength": 0.020,
        "radius": 0.40
    },
    "cinematicConfig": {
        "enabled": False
    }
}

EXPERIMENTS = [
    {
        "id": "exp_baseline_p29",
        "name": "Phase 2.9 Baseline",
        "description": "Locked Phase 2.9 baseline configuration with bloom diffusion.",
        "config": P29_BASE_CONFIG
    },
    {
        "id": "exp_a_subtle_vignette",
        "name": "Experiment A: Subtle Lens Vignette",
        "description": "Applies a gentle lens vignette (darkness 0.15, offset 1.15) to simulate optical falloff in frame corners.",
        "config": {
            **P29_BASE_CONFIG,
            "cinematicConfig": {
                "enabled": True,
                "vignetteDarkness": 0.15,
                "vignetteOffset": 1.15
            }
        }
    },
    {
        "id": "exp_b_fine_film_grain",
        "name": "Experiment B: Fine Monochromatic Film Grain",
        "description": "Adds ultra-fine monochromatic film grain (amplitude 0.012) to soften pin-hole rasterization edges.",
        "config": {
            **P29_BASE_CONFIG,
            "cinematicConfig": {
                "enabled": True,
                "grainIntensity": 0.012
            }
        }
    },
    {
        "id": "exp_c_filmic_micro_contrast",
        "name": "Experiment C: Filmic Micro-Contrast",
        "description": "Slight midtone contrast expansion (contrast 1.02 around midtone 0.18) preserving graphite blacks.",
        "config": {
            **P29_BASE_CONFIG,
            "cinematicConfig": {
                "enabled": True,
                "contrast": 1.02
            }
        }
    },
    {
        "id": "exp_d_highlight_halation",
        "name": "Experiment D: Highlight Halation Tuning",
        "description": "Softens halation around the central core (threshold 0.90, strength 0.025, radius 0.45).",
        "config": {
            **P29_BASE_CONFIG,
            "bloomConfig": {
                "threshold": 0.90,
                "strength": 0.025,
                "radius": 0.45
            }
        }
    },
    {
        "id": "exp_e_atmospheric_tint",
        "name": "Experiment E: Atmospheric Color Integration",
        "description": "Subtle full-frame chromatic balance adjustment (tint [1.002, 1.000, 0.998]).",
        "config": {
            **P29_BASE_CONFIG,
            "cinematicConfig": {
                "enabled": True,
                "atmosphericTint": [1.002, 1.000, 0.998]
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

def compute_metrics(clean_arr, render_arr):
    diff = np.abs(clean_arr - render_arr)
    mae = float(np.mean(diff))
    mse = float(np.mean((clean_arr - render_arr) ** 2))
    rmse = math.sqrt(mse)
    
    if mse == 0:
        psnr = 100.0
    else:
        psnr = 20.0 * math.log10(255.0 / rmse)
        
    lum1 = 0.299 * clean_arr[:,:,0] + 0.587 * clean_arr[:,:,1] + 0.114 * clean_arr[:,:,2]
    lum2 = 0.299 * render_arr[:,:,0] + 0.587 * render_arr[:,:,1] + 0.114 * render_arr[:,:,2]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu1 = np.mean(lum1)
    mu2 = np.mean(lum2)
    var1 = np.var(lum1)
    var2 = np.var(lum2)
    cov = np.mean((lum1 - mu1) * (lum2 - mu2))
    ssim = ((2 * mu1 * mu2 + c1) * (2 * cov + c2)) / ((mu1**2 + mu2**2 + c1) * (var1 + var2 + c2))
    
    warm_pct = float(np.mean((render_arr[:,:,0] > render_arr[:,:,2] * 1.15) & (render_arr[:,:,0] > 30)) * 100.0)
    
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "psnr": round(psnr, 2),
        "ssim": round(float(ssim), 4),
        "mean_lum": round(float(np.mean(lum2)), 2),
        "mean_rgb": [round(float(np.mean(render_arr[:,:,ch])), 2) for ch in range(3)],
        "warm_pixels_pct": round(warm_pct, 2)
    }

def main():
    print("\n" + "="*80)
    print("PHASE 3: RUNNING SINGLE-VARIABLE CINEMATIC POST-PROCESSING EXPERIMENTS")
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
        
        all_results = {
            "metadata": {
                "phase": "3.0",
                "date": time.strftime("%Y-%m-%d"),
                "experiment_count": len(EXPERIMENTS),
                "cameras": [v["cam"] for v in VIEWS]
            },
            "experiments": {}
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
            
            ref_images = {}
            for v in VIEWS:
                img = Image.open(v["ref"]).convert('RGB').resize((1920, 1080), Image.Resampling.LANCZOS)
                ref_images[v["key"]] = np.array(img, dtype=np.float32)
                
            for exp in EXPERIMENTS:
                exp_id = exp["id"]
                name = exp["name"]
                cfg = exp["config"]
                
                print("\n" + "-"*80)
                print(f"Executing: {name} ({exp_id})")
                print(f"Description: {exp['description']}")
                print("-"*80)
                
                page.evaluate(f"window.setDiagnosticConfig({json.dumps(cfg)})")
                time.sleep(0.8)
                
                exp_result = {
                    "id": exp_id,
                    "name": name,
                    "description": exp["description"],
                    "views": {}
                }
                
                for v in VIEWS:
                    key = v["key"]
                    cam = v["cam"]
                    title = v["title"]
                    
                    page.evaluate(f"window.setCameraView('{cam}', true)")
                    time.sleep(0.4)
                    
                    for _ in range(6):
                        page.evaluate("window.renderFrame()")
                        
                    render_path = os.path.join(RENDERS_DIR, f"temp_phase3_{exp_id}_{key}.png")
                    page.screenshot(path=render_path)
                    
                    render_img = Image.open(render_path).convert('RGB')
                    render_arr = np.array(render_img, dtype=np.float32)
                    
                    perf = page.evaluate("window.getPerformanceMetrics()")
                    metrics = compute_metrics(ref_images[key], render_arr)
                    
                    # Regional metrics for core and floor
                    h, w, _ = render_arr.shape
                    floor_clean = ref_images[key][int(h * 0.65):h, 0:w, :]
                    floor_rend = render_arr[int(h * 0.65):h, 0:w, :]
                    floor_mae = round(float(np.mean(np.abs(floor_clean - floor_rend))), 4)
                    
                    core_clean = ref_images[key][int(h * 0.25):int(h * 0.65), int(w * 0.35):int(w * 0.65), :]
                    core_rend = render_arr[int(h * 0.25):int(h * 0.65), int(w * 0.35):int(w * 0.65), :]
                    core_mae = round(float(np.mean(np.abs(core_clean - core_rend))), 4)
                    
                    exp_result["views"][key] = {
                        "camera": cam,
                        "title": title,
                        "performance": perf,
                        "overall": metrics,
                        "floor_mae": floor_mae,
                        "core_mae": core_mae
                    }
                    
                    print(f"  [{key.upper()}] MAE: {metrics['mae']} | PSNR: {metrics['psnr']} dB | SSIM: {metrics['ssim']} | Lum: {metrics['mean_lum']} | Core MAE: {core_mae} | Floor MAE: {floor_mae} | Latency: {perf['frameTimeMs']} ms ({perf['drawCalls']} calls)")
                    
                    # Clean up temp file
                    if os.path.exists(render_path):
                        os.remove(render_path)
                        
                all_results["experiments"][exp_id] = exp_result
                
            browser.close()
            
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase3_experiments.json")
        with open(out_json_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nSaved Phase 3 experiments dataset to: {out_json_path}")
        print("="*80)
        print("PHASE 3 EXPERIMENTAL SWEEPS COMPLETE")
        print("="*80)
        
    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
