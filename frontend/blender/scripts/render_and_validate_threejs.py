#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2: Three.js Headless Hardware Validation & Visual Comparison Runner
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
        "render": os.path.join(RENDERS_DIR, "stage03_threejs_hero.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_threejs_diff_hero.png")
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_threejs_monumental.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_threejs_diff_monumental.png")
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_threejs_detail.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_threejs_diff_detail.png")
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

def compare_images(clean_path, render_path, diff_path):
    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Missing clean benchmark: {clean_path}")
    if not os.path.exists(render_path):
        raise FileNotFoundError(f"Missing Three.js render: {render_path}")
        
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
        
    # Difference amplification for visual inspection: 5x
    diff_vis = np.clip(diff * 5.0, 0, 255).astype(np.uint8)
    diff_img = Image.fromarray(diff_vis)
    diff_img.save(diff_path)
    
    max_diff = float(np.max(diff))
    
    # Structural similarity estimate over luminance
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
        "max_diff": round(max_diff, 2),
        "resolution": f"{img1.width}x{img1.height}",
        "diff_map": diff_path
    }

def main():
    print("\n" + "="*80)
    print("STAGE 03: THREE.JS PRODUCTION VALIDATION & HARDWARE RENDER RUNNER")
    print("="*80)
    
    # 1. Start Vite Server
    print(f"\n[1/4] Starting Vite server on port {PORT}...")
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    try:
        if not wait_for_server(URL, timeout=20):
            print("FATAL: Vite server failed to respond within 20s")
            sys.exit(1)
        print(f"Vite server active at {URL}")
        
        # 2. Launch Google Chrome via Playwright
        print("\n[2/4] Launching Google Chrome (Metal Hardware WebGL)...")
        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        results = {}
        performance_stats = {}
        
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
            
            page = browser.new_page(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1
            )
            
            # Forward browser console logs
            page.on("console", lambda msg: print(f"  [Chrome Console] {msg.text}"))
            
            print(f"Navigating to {URL} ...")
            page.goto(URL, wait_until="networkidle")
            
            # Wait for scene ready hook
            page.wait_for_function("window.__STAGE03_READY__ === true", timeout=30000)
            print("Stage 03 scene initialized and ready!")
            
            # Settle render loop
            time.sleep(2.0)
            
            # 3. Render Each View & Capture Screenshot + Metrics
            print("\n[3/4] Rendering 3 Production Camera Views at 1920x1080...")
            canvas = page.locator("#webgl-canvas")
            
            for v in VIEWS:
                print(f"\nRendering [{v['title']} - {v['cam']}]...")
                page.evaluate(f"window.setCameraView('{v['cam']}', true)")
                time.sleep(1.0)  # allow texture bindings and camera to settle
                
                # Fetch performance stats
                metrics = page.evaluate("window.getPerformanceMetrics()")
                performance_stats[v["key"]] = metrics
                print(f"  Draw Calls:      {metrics['drawCalls']}")
                print(f"  Triangles:       {metrics['triangles']:,}")
                print(f"  Textures:        {metrics['textures']}")
                print(f"  Approx GPU Mem:  {metrics['gpuMemoryMb']} MB")
                print(f"  Frame Time:      {metrics['frameTimeMs']} ms")
                print(f"  FPS:             {metrics['fps']}")
                
                # Capture exact canvas screenshot
                canvas.screenshot(path=v["render"])
                print(f"  Saved render:    {v['render']}")
                
            browser.close()
            
        # 4. Compare with Clean Benchmarks
        print("\n[4/4] Comparing Three.js Renders Against Blender Clean Benchmarks...")
        for v in VIEWS:
            print(f"\nAnalyzing [{v['title']}]...")
            comp = compare_images(v["clean"], v["render"], v["diff"])
            results[v["key"]] = {
                "title": v["title"],
                "camera": v["cam"],
                "performance": performance_stats[v["key"]],
                **comp
            }
            print(f"  Resolution: {comp['resolution']}")
            print(f"  PSNR:       {comp['psnr']} dB")
            print(f"  SSIM:       {comp['ssim']}")
            print(f"  RMSE:       {comp['rmse']}")
            print(f"  MAE:        {comp['mae']}")
            print(f"  Max Diff:   {comp['max_diff']} / 255")
            print(f"  Diff Map:   {comp['diff_map']}")
            
        out_json = os.path.join(ASSETS_DIR, "stage03_threejs_comparison.json")
        with open(out_json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved Three.js validation comparison: {out_json}")
        
    finally:
        # Cleanly terminate Vite server
        print("\nShutting down Vite server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass
            
    print("\n" + "="*80)
    print("PHASE 2 THREE.JS VALIDATION COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    main()
