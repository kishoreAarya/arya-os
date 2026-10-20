#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.3: Rendering Fidelity Correction Suite
Floor Reflection + Reactor Radiance + Bloom + Tone Mapping
===============================================================================
Evaluates:
- Step A: Floor Reflection Investigation (Candidate A SSR vs Candidate B Planar vs Candidate C Hybrid)
- Step B: Floor Art Direction (Dark obsidian graphite, not chrome, not blue)
- Step C: Reactor Radiance (Secondary GI dais fill, 380W core response)
- Step D: Bloom (Compositor bloom threshold ~4.8, strength ~0.035 emulation)
- Step E: Tone Mapping (AgX 0.812 vs ACESFilmic 0.812 vs Baseline)
- Multi-camera coherence: Hero + Monumental + Detail
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

PORT = 5183
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

EXPERIMENTS = [
    {
        "id": "p23_00_baseline",
        "step": "Baseline",
        "name": "Phase 2 Baseline (52 draws, AgX 0.95)",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": False,
            "renderMode": "standard",
            "daisBounceIntensity": 0.0,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#26364a",
                "groundColor": "#05080e",
                "warmGlowIntensity": 0.45
            }
        }
    },
    {
        "id": "p23_01_candidate_a_ssr",
        "step": "Step A - Floor Reflection",
        "name": "Candidate A: Screen-Space Reflection (SSRPass)",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": False,
            "renderMode": "ssr",
            "daisBounceIntensity": 0.0
        }
    },
    {
        "id": "p23_02_candidate_b_planar",
        "step": "Step A - Floor Reflection",
        "name": "Candidate B: Planar Architectural Reflection",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": True,
            "planarIntensity": 0.50,
            "renderMode": "standard",
            "daisBounceIntensity": 0.0
        }
    },
    {
        "id": "p23_03_candidate_c_hybrid",
        "step": "Step A/B - Hybrid Floor Reflection",
        "name": "Candidate C: Hybrid Reflection (Planar + Calibrated Environment Fallback)",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": True,
            "planarIntensity": 0.45,
            "renderMode": "standard",
            "daisBounceIntensity": 0.0,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#1c2635",
                "groundColor": "#040609",
                "warmGlowIntensity": 0.35
            }
        }
    },
    {
        "id": "p23_04_reactor_radiance",
        "step": "Step C - Reactor Radiance",
        "name": "Candidate C + Secondary Dais GI Bounce",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": True,
            "planarIntensity": 0.45,
            "renderMode": "standard",
            "daisBounceIntensity": 2.2,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#1c2635",
                "groundColor": "#040609",
                "warmGlowIntensity": 0.35
            }
        }
    },
    {
        "id": "p23_05_bloom_emulation",
        "step": "Step D - Bloom",
        "name": "Candidate C + Reactor Radiance + Compositor Bloom",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.95,
            "planarReflection": True,
            "planarIntensity": 0.45,
            "renderMode": "bloom",
            "bloomConfig": {"strength": 0.038, "radius": 0.50, "threshold": 0.88},
            "daisBounceIntensity": 2.2,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#1c2635",
                "groundColor": "#040609",
                "warmGlowIntensity": 0.35
            }
        }
    },
    {
        "id": "p23_06_tone_agx_081",
        "step": "Step E - Tone Mapping",
        "name": "Full Chain: AgX with Blender Calibrated Exposure (0.812)",
        "config": {
            "toneMapping": "AgX",
            "exposure": 0.812,
            "planarReflection": True,
            "planarIntensity": 0.45,
            "renderMode": "bloom",
            "bloomConfig": {"strength": 0.038, "radius": 0.50, "threshold": 0.88},
            "daisBounceIntensity": 2.2,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#1c2635",
                "groundColor": "#040609",
                "warmGlowIntensity": 0.35
            }
        }
    },
    {
        "id": "p23_07_tone_aces_081",
        "step": "Step E - Tone Mapping",
        "name": "Full Chain: ACESFilmic with Blender Calibrated Exposure (0.812)",
        "config": {
            "toneMapping": "ACESFilmic",
            "exposure": 0.812,
            "planarReflection": True,
            "planarIntensity": 0.45,
            "renderMode": "bloom",
            "bloomConfig": {"strength": 0.038, "radius": 0.50, "threshold": 0.88},
            "daisBounceIntensity": 2.2,
            "envOptions": {
                "zenithColor": "#0c1624",
                "horizonColor": "#1c2635",
                "groundColor": "#040609",
                "warmGlowIntensity": 0.35
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

def analyze_full_and_regional_metrics(clean_path, render_path, diff_output_path=None):
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
    
    # Save amplified difference image if requested
    if diff_output_path:
        diff_amplified = np.clip(diff * 5.0, 0, 255).astype(np.uint8)
        diff_img = Image.fromarray(diff_amplified)
        diff_img.save(diff_output_path)
    
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
    print("PHASE 2.3: RENDERING FIDELITY CORRECTION EXECUTION")
    print("="*80)
    
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    results = {
        "metadata": {
            "phase": "2.3",
            "date": "2026-10-01",
            "status": "in_progress"
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
                print(f"\n>>> Running [{exp['id']}] {exp['step']}")
                print(f"    Name: {exp['name']}")
                
                page.evaluate(f"window.setDiagnosticConfig({json.dumps(exp['config'])})")
                time.sleep(0.5)
                
                exp_views = {}
                for v in VIEWS:
                    page.evaluate(f"window.setCameraView('{v['cam']}', true)")
                    time.sleep(0.5)
                    metrics = page.evaluate("window.getPerformanceMetrics()")
                    
                    is_final_candidate = (exp["id"] in ["p23_06_tone_agx_081", "p23_07_tone_aces_081"])
                    render_filename = f"stage03_phase23_{v['key']}.png" if exp["id"] == "p23_07_tone_aces_081" else f"exp_{exp['id']}_{v['key']}.png"
                    render_path = os.path.join(RENDERS_DIR, render_filename)
                    
                    diff_filename = f"stage03_phase23_diff_{v['key']}.png" if exp["id"] == "p23_07_tone_aces_081" else None
                    diff_path = os.path.join(RENDERS_DIR, diff_filename) if diff_filename else None
                    
                    canvas.screenshot(path=render_path)
                    
                    analysis = analyze_full_and_regional_metrics(v["clean"], render_path, diff_output_path=diff_path)
                    
                    exp_views[v["key"]] = {
                        "camera": v["cam"],
                        "performance": metrics,
                        "overall": analysis["overall"],
                        "regions": analysis["regions"],
                        "render_file": render_path,
                        "diff_file": diff_path
                    }
                    
                    ov = analysis["overall"]
                    fl = analysis["regions"]["floor"]
                    co = analysis["regions"]["core"]
                    print(f"    [{v['key']:10s}] Calls: {metrics['drawCalls']} | Time: {metrics['frameTimeMs']:.2f}ms | PSNR: {ov['psnr']:5.2f} dB | MAE: {ov['mae']:5.2f} (Floor: {fl['mae']:5.2f}, Core: {co['mae']:5.2f})")
                    
                results["experiments"][exp["id"]] = {
                    "step": exp["step"],
                    "name": exp["name"],
                    "config": exp["config"],
                    "views": exp_views
                }
                
            browser.close()
            
        json_out = os.path.join(ASSETS_DIR, "stage03_phase23_experiments.json")
        with open(json_out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved Phase 2.3 experiment results to: {json_out}")
        
    finally:
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass
            
    print("\n" + "="*80)
    print("PHASE 2.3 EXPERIMENTS EXECUTION COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    main()
