#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.6: Perceptual Difference Isolation & Single-Variable Experiments
===============================================================================
Executes single-variable experiments strictly in accordance with Section 12:
- Baseline: Phase 2.5 baseline
- EXP_01_SKY_ATMOSPHERE: Only change sky/atmosphere luminance & tint
- EXP_02_REACTOR_RADIANCE: Only change central reactor radiance & dais bounce
- EXP_03_FLOOR_RESPONSE: Only change floor planar reflection & diffuse tint
- EXP_04_MIDGROUND_DEPTH: Only change atmospheric depth & ambient fill
- EXP_05_HIGHLIGHT_ROLLOFF: Only change exposure & highlight rolloff
- EXP_06_FILMIC_POST: Only change post-processing subtle halation
- EXP_07_INTEGRATED_MATCH: Converged combination of accepted modifications
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

PORT = 5194
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

CAMERAS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Cinematic Hero Establishing",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
        "baseline_p25": os.path.join(RENDERS_DIR, "stage03_phase25_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "baseline_p25": os.path.join(RENDERS_DIR, "stage03_phase25_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "baseline_p25": os.path.join(RENDERS_DIR, "stage03_phase25_detail.png"),
    }
]

EXPERIMENTS = [
    {
        "id": "baseline_p25",
        "name": "Phase 2.5 Baseline",
        "subsystem": "Baseline",
        "description": "Unmodified Phase 2.5 configuration",
        "config": {
            "variant": "E",
            "toneMapping": "ACESFilmic",
            "exposure": 0.8122,
            "fogType": "linear",
            "fogNear": 22.0,
            "fogFar": 190.0,
            "fogColor": "#38485c",
            "ambientIntensity": 0.34,
            "ambientColor": "#1a2636",
            "planarReflection": True,
            "planarIntensity": 0.34,
            "planarTint": "#0a1420",
            "floorRoughness": 0.24,
            "floorClearcoat": 0.58,
            "floorClearcoatRoughness": 0.12,
            "coreIntensity": 6.8,
            "coreColor": "#ff9428",
            "daisBounceIntensity": 4.2,
            "daisBounceRange": 32.0,
            "daisBounceColor": "#ff9024",
            "glassColor": "#141e2a",
            "glassOpacity": 0.20,
            "renderMode": "standard"
        }
    },
    {
        "id": "EXP_01_SKY_ATMOSPHERE",
        "name": "Exp 01: Sky Atmosphere Luminance",
        "subsystem": "Sky / Atmosphere",
        "description": "Raises sky dome gradient & horizon radiance closer to reference luminance (~71)",
        "config": {
            "envOptions": {
                "zenithColor": "#182230",
                "horizonColor": "#52667d",
                "groundColor": "#101720",
                "warmGlowRadius": 110,
                "warmGlowIntensity": 0.35,
                "cloudBands": True
            },
            "fogColor": "#52667d"
        }
    },
    {
        "id": "EXP_02_REACTOR_RADIANCE",
        "name": "Exp 02: Central Reactor Radiance",
        "subsystem": "Reactor Lighting",
        "description": "Amplifies core point light, canopy downlight, and dais secondary GI bounce to bring warm pixel ratio towards 16%",
        "config": {
            "coreIntensity": 11.5,
            "coreColor": "#ffa030",
            "daisBounceIntensity": 7.2,
            "daisBounceRange": 36.0,
            "daisBounceColor": "#ff9820",
            "pedestalIntensity": 4.5,
            "canopyIntensity": 4.5
        }
    },
    {
        "id": "EXP_03_FLOOR_RESPONSE",
        "name": "Exp 03: Wet Obsidian Floor PBR Response",
        "subsystem": "Floor Materials",
        "description": "Adjusts floor diffuse base tint, clearcoat roughness, and planar intensity to match graphite floor luminance (44)",
        "config": {
            "floorColor": "#101620",
            "planarIntensity": 0.38,
            "planarTint": "#101824",
            "floorRoughness": 0.26,
            "floorClearcoat": 0.62,
            "floorClearcoatRoughness": 0.14
        }
    },
    {
        "id": "EXP_04_MIDGROUND_DEPTH",
        "name": "Exp 04: Midground Depth & Indirect Ambient Fill",
        "subsystem": "Midground & Colonnade",
        "description": "Increases ambient fill and starts linear atmospheric haze at 18m to illuminate colonnades without clipping",
        "config": {
            "ambientIntensity": 0.52,
            "ambientColor": "#222f3e",
            "fogNear": 18.0,
            "fogFar": 175.0
        }
    },
    {
        "id": "EXP_05_HIGHLIGHT_ROLLOFF",
        "name": "Exp 05: Exposure & Highlight Rolloff",
        "subsystem": "Tone Mapping / Exposure",
        "description": "Calibrates exposure from 0.8122 to 0.96 for higher midtone presence while preserving highlight shoulder",
        "config": {
            "exposure": 0.96
        }
    },
    {
        "id": "EXP_06_FILMIC_POST",
        "name": "Exp 06: Filmic Post-Processing & Subtle Core Halation",
        "subsystem": "Post-Processing",
        "description": "Enables subtle bloom/halation (threshold 0.88, strength 0.038, radius 0.45) for organic light rolloff",
        "config": {
            "renderMode": "bloom",
            "bloomConfig": {
                "threshold": 0.88,
                "strength": 0.038,
                "radius": 0.45
            }
        }
    },
    {
        "id": "EXP_07_INTEGRATED_MATCH",
        "name": "Exp 07: Converged Phase 2.6 Image-Matching Profile",
        "subsystem": "Integrated",
        "description": "Combines accepted single-variable calibrations into an integrated cinematic profile",
        "config": {
            "toneMapping": "ACESFilmic",
            "exposure": 0.94,
            "envOptions": {
                "zenithColor": "#16202c",
                "horizonColor": "#4e6278",
                "groundColor": "#0e151e",
                "warmGlowRadius": 115,
                "warmGlowIntensity": 0.40,
                "cloudBands": True
            },
            "fogType": "linear",
            "fogNear": 20.0,
            "fogFar": 185.0,
            "fogColor": "#4e6278",
            "ambientIntensity": 0.46,
            "ambientColor": "#1e2c3c",
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
    if i_ref.size != i_rnd.size:
        i_ref = i_ref.resize(i_rnd.size, Image.Resampling.LANCZOS)

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
    arch_mae = float(np.mean(diff[int(h * 0.20):int(h * 0.65), :]))

    # Warm pixel percentage
    warm_pct = float(np.mean((arr_rnd[:,:,0] > arr_rnd[:,:,2] * 1.15) & (arr_rnd[:,:,0] > 30)) * 100.0)

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "psnr": round(psnr, 2),
        "ssim": round(ssim, 4),
        "sky_mae": round(sky_mae, 2),
        "core_mae": round(core_mae, 2),
        "floor_mae": round(floor_mae, 2),
        "arch_mae": round(arch_mae, 2),
        "mean_lum": round(float(np.mean(lum2)), 2),
        "mean_rgb": [round(float(np.mean(arr_rnd[:,:,ch])), 2) for ch in range(3)],
        "warm_pixels_pct": round(warm_pct, 2)
    }

def main():
    print("="*80)
    print("PHASE 2.6: SINGLE-VARIABLE CONTROLLED EXPERIMENTS RUNNER")
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
                "phase": "2.6",
                "date": time.strftime("%Y-%m-%d"),
                "status": "complete",
                "benchmark_target": "memory_hero.jpg",
                "baseline": "Phase 2.5 final"
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

            for exp in EXPERIMENTS:
                exp_id = exp["id"]
                exp_name = exp["name"]
                subsystem = exp["subsystem"]
                desc = exp["description"]
                config = exp["config"]
                print(f"\n--- Testing {exp_name} ({exp_id}) ---")
                print(f"  Subsystem: {subsystem} | {desc}")

                # First reset to Phase 2.5 baseline if running an isolated test
                if exp_id not in ("baseline_p25", "EXP_07_INTEGRATED_MATCH"):
                    page.evaluate(f"window.setDiagnosticConfig({json.dumps(EXPERIMENTS[0]['config'])})")
                    time.sleep(0.3)

                page.evaluate(f"window.setDiagnosticConfig({json.dumps(config)})")
                time.sleep(0.8)

                exp_results = {
                    "id": exp_id,
                    "name": exp_name,
                    "subsystem": subsystem,
                    "description": desc,
                    "config": config,
                    "views": {}
                }

                for cam_info in CAMERAS:
                    cam_key = cam_info["key"]
                    cam_name = cam_info["cam"]
                    cam_title = cam_info["title"]
                    ref_path = cam_info["ref"]
                    base_p25_path = cam_info["baseline_p25"]

                    print(f"  Camera {cam_name} ({cam_key})...")
                    page.evaluate(f"window.setCameraView('{cam_name}', true)")
                    time.sleep(0.4)

                    # Settle
                    for _ in range(6):
                        page.evaluate("window.renderFrame()")

                    render_filename = f"exp_p26_{exp_id}_{cam_key}.png"
                    render_path = os.path.join(RENDERS_DIR, render_filename)
                    page.screenshot(path=render_path)

                    metrics = page.evaluate("window.getPerformanceMetrics()")

                    # Comparison vs Locked Reference Target
                    ref_metrics = compute_metrics(ref_path, render_path)
                    # Comparison vs Phase 2.5 Baseline
                    p25_metrics = compute_metrics(base_p25_path, render_path) if os.path.exists(base_p25_path) else None

                    print(f"    Perf: {metrics.get('drawCalls')} draws, {metrics.get('triangles')} tris, {metrics.get('frameTimeMs')} ms, {metrics.get('fps')} FPS")
                    print(f"    VS Locked Target: MAE={ref_metrics['mae']}, PSNR={ref_metrics['psnr']}, SSIM={ref_metrics['ssim']}, Lum={ref_metrics['mean_lum']}, Warm={ref_metrics['warm_pixels_pct']}%")
                    print(f"      Sky MAE={ref_metrics['sky_mae']}, Core MAE={ref_metrics['core_mae']}, Floor MAE={ref_metrics['floor_mae']}, Arch MAE={ref_metrics['arch_mae']}")

                    exp_results["views"][cam_key] = {
                        "camera": cam_name,
                        "title": cam_title,
                        "render_file": render_path,
                        "performance": metrics,
                        "vs_target_reference": ref_metrics,
                        "vs_phase25_baseline": p25_metrics
                    }

                results["experiments"][exp_id] = exp_results

            browser.close()

        # Save results JSON
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase26_experiments.json")
        with open(out_json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved all Phase 2.6 experiment results to {out_json_path}")

    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
