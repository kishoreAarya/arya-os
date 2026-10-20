#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.4: Cinematic Look-Development & Perceptual Fidelity Experiments
===============================================================================
Executes the required A/B workflow across all 3 benchmark cameras:
- Variant A: Current Phase 2.3 baseline
- Variant B: Atmosphere correction
- Variant C: Atmosphere + Material / Highlight correction
- Variant D: Atmosphere + Material + Reactor integration
- Variant E: Full cinematic treatment
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
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")
REFS_DIR = os.path.join(BLEND_DIR, "references", "stage03_memory")

PORT = 5186
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

CAMERAS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Cinematic Hero Establishing",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_detail.png"),
    }
]

VARIANTS = [
    {
        "id": "variant_a",
        "name": "Variant A: Phase 2.3 Baseline",
        "config": {"variant": "A"}
    },
    {
        "id": "variant_b",
        "name": "Variant B: Atmosphere Correction",
        "config": {"variant": "B"}
    },
    {
        "id": "variant_c",
        "name": "Variant C: Atmosphere + Material/Highlight Correction",
        "config": {"variant": "C"}
    },
    {
        "id": "variant_d",
        "name": "Variant D: Atmosphere + Material + Reactor Integration",
        "config": {"variant": "D"}
    },
    {
        "id": "variant_e",
        "name": "Variant E: Full Cinematic Treatment",
        "config": {"variant": "E"}
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

def compute_metrics(img1_path, img2_path):
    i1 = Image.open(img1_path).convert('RGB')
    i2 = Image.open(img2_path).convert('RGB')
    if i1.size != i2.size:
        i2 = i2.resize(i1.size, Image.Resampling.LANCZOS)
    
    a1 = np.array(i1, dtype=np.float32)
    a2 = np.array(i2, dtype=np.float32)
    diff = np.abs(a1 - a2)
    mae = float(np.mean(diff))
    mse = float(np.mean((a1 - a2) ** 2))
    rmse = math.sqrt(mse)
    psnr = 20.0 * math.log10(255.0 / rmse) if rmse > 0 else 100.0

    lum1 = 0.299 * a1[:,:,0] + 0.587 * a1[:,:,1] + 0.114 * a1[:,:,2]
    lum2 = 0.299 * a2[:,:,0] + 0.587 * a2[:,:,1] + 0.114 * a2[:,:,2]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu1 = np.mean(lum1)
    mu2 = np.mean(lum2)
    var1 = np.var(lum1)
    var2 = np.var(lum2)
    cov = np.mean((lum1 - mu1) * (lum2 - mu2))
    ssim = float(((2 * mu1 * mu2 + c1) * (2 * cov + c2)) / ((mu1**2 + mu2**2 + c1) * (var1 + var2 + c2)))

    # Regional MAE breakdown
    h, w, _ = a1.shape
    floor_mae = float(np.mean(diff[int(h*0.65):, :]))
    core_mae = float(np.mean(diff[int(h*0.25):int(h*0.65), int(w*0.35):int(w*0.65)]))
    sky_mae = float(np.mean(diff[:int(h*0.35), :]))

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "psnr": round(psnr, 2),
        "ssim": round(ssim, 4),
        "floor_mae": round(floor_mae, 2),
        "core_mae": round(core_mae, 2),
        "sky_mae": round(sky_mae, 2),
        "mean_rgb": [round(float(np.mean(a2[:,:,ch])), 2) for ch in range(3)]
    }

def main():
    print("="*80)
    print("PHASE 2.4 LOOK-DEVELOPMENT EXPERIMENTS RUNNER")
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
                "phase": "2.4",
                "date": time.strftime("%Y-%m-%d"),
                "status": "complete"
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
                config = var["config"]
                print(f"\n--- Testing {var_name} ---")

                page.evaluate(f"window.setDiagnosticConfig({json.dumps(config)})")
                time.sleep(1.0)

                var_results = {
                    "id": var_id,
                    "name": var_name,
                    "views": {}
                }

                for cam_info in CAMERAS:
                    cam_key = cam_info["key"]
                    cam_name = cam_info["cam"]
                    cam_title = cam_info["title"]
                    ref_path = cam_info["ref"]
                    clean_path = cam_info["clean"]

                    print(f"  Camera {cam_name} ({cam_key})...")
                    page.evaluate(f"window.setCameraView('{cam_name}', true)")
                    time.sleep(0.5)

                    # Settle
                    for _ in range(6):
                        page.evaluate("window.renderFrame()")

                    render_filename = f"exp_p24_{var_id}_{cam_key}.png"
                    render_path = os.path.join(RENDERS_DIR, render_filename)
                    page.screenshot(path=render_path)

                    metrics = page.evaluate("window.getPerformanceMetrics()")

                    # Comparison vs Primary Target (reference image)
                    ref_metrics = compute_metrics(ref_path, render_path)
                    # Comparison vs Clean pass
                    clean_metrics = compute_metrics(clean_path, render_path)

                    print(f"    Perf: {metrics.get('drawCalls')} draws, {metrics.get('triangles')} tris, {metrics.get('frameTimeMs')} ms, {metrics.get('fps')} FPS")
                    print(f"    VS Target (Ref): MAE={ref_metrics['mae']}, PSNR={ref_metrics['psnr']}, SSIM={ref_metrics['ssim']}, Sky={ref_metrics['sky_mae']}, Core={ref_metrics['core_mae']}, Floor={ref_metrics['floor_mae']}")
                    print(f"    VS Clean Pass:   MAE={clean_metrics['mae']}, PSNR={clean_metrics['psnr']}")

                    var_results["views"][cam_key] = {
                        "camera": cam_name,
                        "title": cam_title,
                        "render_file": render_path,
                        "performance": metrics,
                        "vs_target_reference": ref_metrics,
                        "vs_clean_benchmark": clean_metrics
                    }

                results["variants"][var_id] = var_results

            browser.close()

        # Save results JSON
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase24_experiments.json")
        with open(out_json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved all Phase 2.4 experiment results to {out_json_path}")

    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
