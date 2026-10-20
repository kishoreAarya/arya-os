#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.7: Cinematic Lighting Distribution Reconstruction Experiments
===============================================================================
Executes controlled lighting-layer experiments across all 3 benchmark cameras:
- Baseline: Phase 2.6 Baseline
- Variant A: Environmental Fill only (Layer 1: Hemisphere light + soft sky contribution)
- Variant B: Environmental Fill + Reactor Warmth (Layer 1 + Layer 2: multi-tier warm field)
- Variant C: Environmental Fill + Reactor Warmth + Shadow-Midtone Lift (exposure & ambient lift)
- Variant D: Environmental Fill + Reactor Warmth + Atmospheric Depth (Layer 3: linear fog depth)
- Variant E: Integrated Final Candidate (Optimal synthesis of all 3 lighting layers)
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
import cv2
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")
REFS_DIR = os.path.join(BLEND_DIR, "references", "stage03_memory")

PORT = 5198
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

CAMERAS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Cinematic Hero Establishing",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
        "baseline_p26": os.path.join(RENDERS_DIR, "stage03_phase26_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "baseline_p26": os.path.join(RENDERS_DIR, "stage03_phase26_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "baseline_p26": os.path.join(RENDERS_DIR, "stage03_phase26_detail.png"),
    }
]

VARIANTS = [
    {
        "id": "variant_baseline_p26",
        "name": "Phase 2.6 Baseline",
        "description": "Unmodified Phase 2.6 configuration",
        "config": {
            "variant": "E",
            "toneMapping": "ACESFilmic",
            "exposure": 0.94,
            "fogType": "linear",
            "fogNear": 20.0,
            "fogFar": 185.0,
            "fogColor": "#4e6278",
            "ambientIntensity": 0.46,
            "ambientColor": "#1e2c3c",
            "hemisphereIntensity": 0.0,
            "tertiaryStairsIntensity": 0.0,
            "coreIntensity": 10.5,
            "coreColor": "#ffa030",
            "daisBounceIntensity": 6.5,
            "daisBounceRange": 34.0,
            "daisBounceColor": "#ff9624",
            "pedestalIntensity": 4.0,
            "canopyIntensity": 4.0,
            "planarIntensity": 0.36,
            "planarTint": "#0e1622",
            "floorColor": "#0e141c",
            "floorRoughness": 0.25,
            "floorClearcoat": 0.60,
            "floorClearcoatRoughness": 0.13,
            "renderMode": "standard"
        }
    },
    {
        "id": "variant_a",
        "name": "Variant A: Environmental Fill Only",
        "description": "Layer 1: Broad Hemisphere light (sky #4e6278, ground #18202a) providing soft ambient fill to shadow-side architecture",
        "config": {
            "hemisphereIntensity": 0.32,
            "hemisphereSkyColor": "#4e6278",
            "hemisphereGroundColor": "#18202a"
        }
    },
    {
        "id": "variant_b",
        "name": "Variant B: Environmental Fill + Reactor Warmth",
        "description": "Layer 1 + Layer 2: Multi-tier reactor warm field (core 11.5W, dais bounce 7.2W, tertiary stairs grazing light 2.2W)",
        "config": {
            "hemisphereIntensity": 0.32,
            "hemisphereSkyColor": "#4e6278",
            "hemisphereGroundColor": "#18202a",
            "coreIntensity": 11.5,
            "coreColor": "#ffa030",
            "daisBounceIntensity": 7.2,
            "daisBounceRange": 36.0,
            "daisBounceColor": "#ff9820",
            "tertiaryStairsIntensity": 2.2,
            "tertiaryStairsColor": "#ff9028",
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5
        }
    },
    {
        "id": "variant_c",
        "name": "Variant C: Environmental Fill + Reactor Warmth + Shadow-Midtone Lift",
        "description": "Layer 1 + 2 with shadow-floor lift (exposure 0.98, ambient fill 0.48) to reveal graphite midtones without flattening contrast",
        "config": {
            "hemisphereIntensity": 0.32,
            "hemisphereSkyColor": "#4e6278",
            "hemisphereGroundColor": "#18202a",
            "coreIntensity": 11.5,
            "coreColor": "#ffa030",
            "daisBounceIntensity": 7.2,
            "daisBounceRange": 36.0,
            "daisBounceColor": "#ff9820",
            "tertiaryStairsIntensity": 2.2,
            "tertiaryStairsColor": "#ff9028",
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5,
            "exposure": 0.98,
            "ambientIntensity": 0.48,
            "ambientColor": "#1e2c3c"
        }
    },
    {
        "id": "variant_d",
        "name": "Variant D: Environmental Fill + Reactor Warmth + Atmospheric Depth",
        "description": "Layer 1 + 2 + 3: Linear atmospheric depth calibration (near 19m, far 180m, sky dome warm glow radius 120)",
        "config": {
            "hemisphereIntensity": 0.32,
            "hemisphereSkyColor": "#4e6278",
            "hemisphereGroundColor": "#18202a",
            "coreIntensity": 11.5,
            "coreColor": "#ffa030",
            "daisBounceIntensity": 7.2,
            "daisBounceRange": 36.0,
            "daisBounceColor": "#ff9820",
            "tertiaryStairsIntensity": 2.2,
            "tertiaryStairsColor": "#ff9028",
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5,
            "fogNear": 19.0,
            "fogFar": 180.0,
            "fogColor": "#4e6278"
        }
    },
    {
        "id": "variant_e",
        "name": "Variant E: Integrated Final Candidate",
        "description": "Layer 1 + Layer 2 + Layer 3 + Calibrated Exposure: Optimal cinematic synthesis across all three benchmark cameras",
        "config": {
            "toneMapping": "ACESFilmic",
            "exposure": 0.96,
            "envOptions": {
                "zenithColor": "#16202c",
                "horizonColor": "#4e6278",
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
            "pedestalIntensity": 4.2,
            "canopyIntensity": 4.2,
            "planarIntensity": 0.36,
            "planarTint": "#0e1622",
            "floorColor": "#0e141c",
            "floorRoughness": 0.25,
            "floorClearcoat": 0.60,
            "floorClearcoatRoughness": 0.13,
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

def compute_metrics(ref_path, render_path):
    i_ref = Image.open(ref_path).convert('RGB')
    i_rnd = Image.open(render_path).convert('RGB')
    if i_ref.size != (1920, 1080):
        i_ref = i_ref.resize((1920, 1080), Image.Resampling.LANCZOS)
    if i_rnd.size != (1920, 1080):
        i_rnd = i_rnd.resize((1920, 1080), Image.Resampling.LANCZOS)

    arr_ref = np.array(i_ref, dtype=np.float32)
    arr_rnd = np.array(i_rnd, dtype=np.float32)

    diff = np.abs(arr_ref - arr_rnd)
    mae = float(np.mean(diff))
    mse = float(np.mean((arr_ref - arr_rnd) ** 2))
    rmse = math.sqrt(mse)
    psnr = 20.0 * math.log10(255.0 / rmse) if rmse > 0 else 100.0

    lum1 = 0.299 * arr_ref[:,:,0] + 0.587 * arr_ref[:,:,1] + 0.114 * arr_ref[:,:,2]
    lum2 = 0.299 * arr_rnd[:,:,0] + 0.587 * arr_rnd[:,:,1] + 0.114 * arr_rnd[:,:,2]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu1 = np.mean(lum1)
    mu2 = np.mean(lum2)
    var1 = np.var(lum1)
    var2 = np.var(lum2)
    cov = np.mean((lum1 - mu1) * (lum2 - mu2))
    ssim = float(((2 * mu1 * mu2 + c1) * (2 * cov + c2)) / ((mu1**2 + mu2**2 + c1) * (var1 + var2 + c2)))

    h, w, _ = arr_ref.shape
    floor_mae = float(np.mean(diff[int(h * 0.65):, :]))
    core_mae = float(np.mean(diff[int(h * 0.25):int(h * 0.65), int(w * 0.35):int(w * 0.65)]))
    sky_mae = float(np.mean(diff[:int(h * 0.35), :]))
    colonnade_mae = float(np.mean(diff[int(h * 0.25):int(h * 0.65), :int(w * 0.35)]))

    # Regional mean luminances
    floor_lum = float(np.mean(lum2[int(h * 0.65):, :]))
    core_lum = float(np.mean(lum2[int(h * 0.25):int(h * 0.65), int(w * 0.35):int(w * 0.65)]))
    sky_lum = float(np.mean(lum2[:int(h * 0.35), :]))
    colonnade_lum = float(np.mean(lum2[int(h * 0.25):int(h * 0.65), :int(w * 0.35)]))

    # Warm pixel percentage
    warm_pct = float(np.mean((arr_rnd[:,:,0] > arr_rnd[:,:,2] * 1.15) & (arr_rnd[:,:,0] > 30)) * 100.0)

    # Weighted Perceptual Score (Section 12):
    # 30% composition/silhouette, 25% lighting distribution, 20% atmospheric depth, 15% reactor warmth, 10% material response
    # Normalized so higher is better (based on error reduction vs baseline)
    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "psnr": round(psnr, 2),
        "ssim": round(ssim, 4),
        "mean_lum": round(float(np.mean(lum2)), 2),
        "floor_lum": round(floor_lum, 2),
        "core_lum": round(core_lum, 2),
        "sky_lum": round(sky_lum, 2),
        "colonnade_lum": round(colonnade_lum, 2),
        "sky_mae": round(sky_mae, 2),
        "core_mae": round(core_mae, 2),
        "floor_mae": round(floor_mae, 2),
        "colonnade_mae": round(colonnade_mae, 2),
        "warm_pixels_pct": round(warm_pct, 2)
    }

def main():
    print("="*80)
    print("PHASE 2.7: CINEMATIC LIGHTING DISTRIBUTION EXPERIMENTS RUNNER")
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

        results = {
            "metadata": {
                "phase": "2.7",
                "date": time.strftime("%Y-%m-%d"),
                "status": "complete",
                "benchmark_target": "memory_hero.jpg",
                "baseline": "Phase 2.6 final"
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

            for var in VARIANTS:
                var_id = var["id"]
                var_name = var["name"]
                desc = var["description"]
                config = var["config"]
                print(f"\n--- Testing {var_name} ({var_id}) ---")
                print(f"  Description: {desc}")

                # Reset to Phase 2.6 baseline first
                if var_id != "variant_baseline_p26":
                    page.evaluate(f"window.setDiagnosticConfig({json.dumps(VARIANTS[0]['config'])})")
                    time.sleep(0.3)

                page.evaluate(f"window.setDiagnosticConfig({json.dumps(config)})")
                time.sleep(0.8)

                var_results = {
                    "id": var_id,
                    "name": var_name,
                    "description": desc,
                    "config": config,
                    "views": {}
                }

                for cam_info in CAMERAS:
                    cam_key = cam_info["key"]
                    cam_name = cam_info["cam"]
                    cam_title = cam_info["title"]
                    ref_path = cam_info["ref"]
                    base_p26_path = cam_info["baseline_p26"]

                    print(f"  Camera {cam_name} ({cam_key})...")
                    page.evaluate(f"window.setCameraView('{cam_name}', true)")
                    time.sleep(0.4)

                    # Settle
                    for _ in range(6):
                        page.evaluate("window.renderFrame()")

                    render_filename = f"exp_p27_{var_id}_{cam_key}.png"
                    render_path = os.path.join(RENDERS_DIR, render_filename)
                    page.screenshot(path=render_path)

                    metrics = page.evaluate("window.getPerformanceMetrics()")

                    # Comparison vs Locked Reference Target
                    ref_metrics = compute_metrics(ref_path, render_path)
                    # Comparison vs Phase 2.6 Baseline
                    p26_metrics = compute_metrics(base_p26_path, render_path) if os.path.exists(base_p26_path) else None

                    print(f"    Perf: {metrics.get('drawCalls')} draws, {metrics.get('triangles')} tris, {metrics.get('frameTimeMs')} ms, {metrics.get('fps')} FPS")
                    print(f"    VS Locked Target: MAE={ref_metrics['mae']}, PSNR={ref_metrics['psnr']}, SSIM={ref_metrics['ssim']}, Lum={ref_metrics['mean_lum']}, Warm={ref_metrics['warm_pixels_pct']}%")
                    print(f"      Sky MAE={ref_metrics['sky_mae']}, Core MAE={ref_metrics['core_mae']}, Floor MAE={ref_metrics['floor_mae']}, Colonnade MAE={ref_metrics['colonnade_mae']}")

                    var_results["views"][cam_key] = {
                        "camera": cam_name,
                        "title": cam_title,
                        "render_file": render_path,
                        "performance": metrics,
                        "vs_target_reference": ref_metrics,
                        "vs_phase26_baseline": p26_metrics
                    }

                results["variants"][var_id] = var_results

            browser.close()

        # Save results JSON
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase27_experiments.json")
        with open(out_json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved all Phase 2.7 experiment results to {out_json_path}")

    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
