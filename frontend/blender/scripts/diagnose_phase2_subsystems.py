#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.2: Systematic Subsystem Diagnostic & Transmission Draw-Call Optimization
===============================================================================
Isolates remaining visual error using:
- Post-processing / Tone-mapping sweeps
- Glass subsystem: Transmission (185 draws) vs Cinematic Physical Glass (~94 draws)
- Material vs Lighting-only neutral clay isolation
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

EXPERIMENTS = [
    {
        "id": "baseline_transmission",
        "name": "Baseline: Physical Transmission Glass (185 draws)",
        "config": {"toneMapping": "AgX", "exposure": 0.95, "cinematicGlass": False, "neutralMaterial": False}
    },
    {
        "id": "cinematic_glass",
        "name": "Optimized: Cinematic Physical Glass (~94 draws)",
        "config": {"toneMapping": "AgX", "exposure": 0.95, "cinematicGlass": True, "neutralMaterial": False}
    },
    {
        "id": "cinematic_glass_exp100",
        "name": "Cinematic Glass + AgX Exp 1.00",
        "config": {"toneMapping": "AgX", "exposure": 1.00, "cinematicGlass": True, "neutralMaterial": False}
    },
    {
        "id": "cinematic_glass_aces",
        "name": "Cinematic Glass + ACESFilmic",
        "config": {"toneMapping": "ACESFilmic", "exposure": 0.95, "cinematicGlass": True, "neutralMaterial": False}
    },
    {
        "id": "neutral_lighting_only",
        "name": "Diagnostic: Neutral Clay Material (Lighting-Only)",
        "config": {"toneMapping": "AgX", "exposure": 0.95, "neutralMaterial": True}
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

def compare_images(clean_path, render_path):
    img1 = Image.open(clean_path).convert('RGB')
    img2 = Image.open(render_path).convert('RGB')
    
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
        
    arr1 = np.array(img1, dtype=np.float32)
    arr2 = np.array(img2, dtype=np.float32)
    
    diff = np.abs(arr1 - arr2)
    mae = float(np.mean(diff))
    mse = float(np.mean((arr1 - arr2) ** 2))
    rmse = math.sqrt(mse)
    
    if mse == 0:
        psnr = 100.0
    else:
        psnr = 20.0 * math.log10(255.0 / rmse)
        
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
    
    return {
        "mae": round(mae, 4),
        "mse": round(mse, 4),
        "rmse": round(rmse, 4),
        "psnr": round(psnr, 2),
        "ssim": round(float(ssim), 4),
        "max_diff": round(float(np.max(diff)), 2)
    }

def main():
    print("\n" + "="*80)
    print("PHASE 2.2: SUBSYSTEM DIAGNOSTIC & TRANSMISSION PASS OPTIMIZATION")
    print("="*80)
    
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    experiment_results = {}
    
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
                print(f"\n--- Running Experiment: [{exp['id']}] {exp['name']} ---")
                page.evaluate(f"window.setDiagnosticConfig({json.dumps(exp['config'])})")
                time.sleep(0.5)
                
                exp_metrics = {}
                for v in VIEWS:
                    page.evaluate(f"window.setCameraView('{v['cam']}', true)")
                    time.sleep(0.6)
                    metrics = page.evaluate("window.getPerformanceMetrics()")
                    
                    tmp_render = os.path.join(RENDERS_DIR, f"diag_{exp['id']}_{v['key']}.png")
                    canvas.screenshot(path=tmp_render)
                    
                    comp = compare_images(v["clean"], tmp_render)
                    exp_metrics[v["key"]] = {
                        "camera": v["cam"],
                        "performance": metrics,
                        **comp,
                        "render_file": tmp_render
                    }
                    print(f"  [{v['key']:10s}] Calls: {metrics['drawCalls']:3d} | FPS: {metrics['fps']:5.1f} | PSNR: {comp['psnr']:5.2f} dB | MAE: {comp['mae']:5.2f} | SSIM: {comp['ssim']:5.4f}")
                    
                experiment_results[exp["id"]] = {
                    "name": exp["name"],
                    "config": exp["config"],
                    "metrics": exp_metrics
                }
                
            browser.close()
            
        diag_json = os.path.join(ASSETS_DIR, "stage03_phase2_2_subsystem_diagnostic.json")
        with open(diag_json, "w") as f:
            json.dump(experiment_results, f, indent=2)
        print(f"\nSaved diagnostic results: {diag_json}")
        
    finally:
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass
            
    print("\n" + "="*80)
    print("PHASE 2.2 DIAGNOSTIC COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    main()
