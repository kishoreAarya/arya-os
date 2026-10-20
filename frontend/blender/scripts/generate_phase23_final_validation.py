#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.3: Final Validation Renders & 4-Panel Side-by-Side Comparison Generator
===============================================================================
Generates:
1. Three.js Phase 2.3 Renders:
   - stage03_phase23_hero.png
   - stage03_phase23_monumental.png
   - stage03_phase23_detail.png
2. Amplified Difference Maps (5x):
   - stage03_phase23_diff_hero.png
   - stage03_phase23_diff_monumental.png
   - stage03_phase23_diff_detail.png
3. 4-Panel Side-by-Side Comparison Panels:
   [Blender Reference] | [Three.js Phase 2 Baseline] | [Three.js Phase 2.3 Candidate] | [Difference Map]
   - stage03_phase23_panel_hero.png
   - stage03_phase23_panel_monumental.png
   - stage03_phase23_panel_detail.png
4. Full Quantitative Comparison JSON:
   - stage03_phase23_comparison.json
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
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")

PORT = 5185
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

VIEWS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Archival Hero Establishing",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_threejs_hero.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase23_hero.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase23_diff_hero.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase23_panel_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_threejs_monumental.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase23_monumental.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase23_diff_monumental.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase23_panel_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_threejs_detail.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase23_detail.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase23_diff_detail.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase23_panel_detail.png"),
    }
]

# Optimal Phase 2.3 Candidate: Hybrid Planar Reflection + Dais GI Bounce + ACESFilmic 0.812
PHASE23_CONFIG = {
    "toneMapping": "ACESFilmic",
    "exposure": 0.812,
    "planarReflection": True,
    "planarIntensity": 0.45,
    "renderMode": "standard",
    "daisBounceIntensity": 2.0,
    "envOptions": {
        "zenithColor": "#0c1624",
        "horizonColor": "#1c2635",
        "groundColor": "#040609",
        "warmGlowIntensity": 0.35,
        "warmGlowRadius": 110,
        "bakedGroundBounce": False
    }
}

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

def create_4panel_image(clean_path, baseline_path, candidate_path, diff_path, output_panel_path, title):
    """Combines 4 images into a 2x2 or 4x1 comparison grid."""
    w, h = 960, 540
    img_clean = Image.open(clean_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_base = Image.open(baseline_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS) if os.path.exists(baseline_path) else img_clean
    img_cand = Image.open(candidate_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_diff = Image.open(diff_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    
    grid = Image.new('RGB', (w * 2, h * 2 + 60), color=(15, 20, 28))
    draw = ImageDraw.Draw(grid)
    
    grid.paste(img_clean, (0, 30))
    grid.paste(img_base, (w, 30))
    grid.paste(img_cand, (0, h + 60))
    grid.paste(img_diff, (w, h + 60))
    
    draw.text((20, 8), f"BLENDER EEVEE BENCHMARK ({title})", fill=(200, 220, 240))
    draw.text((w + 20, 8), "THREE.JS PHASE 2 BASELINE (52 Draws, AgX 0.95)", fill=(200, 220, 240))
    draw.text((20, h + 38), "THREE.JS PHASE 2.3 CANDIDATE (Hybrid Floor + Reactor GI + ACES 0.812)", fill=(255, 180, 50))
    draw.text((w + 20, h + 38), "AMPLIFIED DIFFERENCE MAP (5x)", fill=(255, 100, 100))
    
    grid.save(output_panel_path)
    print(f"Generated 4-panel comparison: {output_panel_path}")

def main():
    print("\n" + "="*80)
    print("PHASE 2.3: GENERATING FINAL VALIDATION RENDERS & 4-PANEL COMPARISONS")
    print("="*80)
    
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    
    comparison_data = {
        "metadata": {
            "phase": "2.3",
            "date": "2026-10-01",
            "solution": "Candidate C (Hybrid Planar Floor Reflection + Reactor Dais GI Bounce + ACESFilmic 0.812)",
            "config": PHASE23_CONFIG
        },
        "views": {}
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
            
            print(f"Configuring Phase 2.3 Selected Rendering Parameters...")
            page.evaluate(f"window.setDiagnosticConfig({json.dumps(PHASE23_CONFIG)})")
            time.sleep(0.6)
            
            for v in VIEWS:
                print(f"\nCapturing view: [{v['key'].upper()}] - {v['title']}")
                page.evaluate(f"window.setCameraView('{v['cam']}', true)")
                time.sleep(0.6)
                metrics = page.evaluate("window.getPerformanceMetrics()")
                
                canvas.screenshot(path=v["render"])
                print(f"  Rendered: {v['render']}")
                
                analysis = analyze_full_and_regional_metrics(v["clean"], v["render"], diff_output_path=v["diff"])
                print(f"  Generated Diff: {v['diff']}")
                
                # Generate 4-panel comparison
                create_4panel_image(v["clean"], v["baseline"], v["render"], v["diff"], v["panel"], v["title"])
                
                ov = analysis["overall"]
                fl = analysis["regions"]["floor"]
                co = analysis["regions"]["core"]
                sk = analysis["regions"]["sky"]
                print(f"  Overall: PSNR = {ov['psnr']:.2f} dB | MAE = {ov['mae']:.2f} | SSIM = {ov['ssim']:.4f}")
                print(f"  Regional: Floor MAE = {fl['mae']:.2f} | Core MAE = {co['mae']:.2f} | Sky MAE = {sk['mae']:.2f}")
                print(f"  Workload: Calls = {metrics['drawCalls']} | Triangles = {metrics['triangles']} | Time = {metrics['frameTimeMs']:.2f}ms | FPS = {metrics['fps']:.1f}")
                
                comparison_data["views"][v["key"]] = {
                    "camera": v["cam"],
                    "title": v["title"],
                    "performance": metrics,
                    "overall": ov,
                    "regions": analysis["regions"],
                    "render_file": v["render"],
                    "diff_file": v["diff"],
                    "panel_file": v["panel"]
                }
                
            browser.close()
            
        json_path = os.path.join(ASSETS_DIR, "stage03_phase23_comparison.json")
        with open(json_path, "w") as f:
            json.dump(comparison_data, f, indent=2)
        print(f"\nSaved Phase 2.3 comparison JSON: {json_path}")
        
    finally:
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass
            
    print("\n" + "="*80)
    print("PHASE 2.3 VALIDATION COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    main()
