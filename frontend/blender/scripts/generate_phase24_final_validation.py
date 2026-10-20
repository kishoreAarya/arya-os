#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.4: Final Validation Renders & 4-Panel Side-by-Side Comparison Generator
===============================================================================
Generates:
1. Three.js Phase 2.4 Renders (1920x1080):
   - stage03_phase24_hero.png
   - stage03_phase24_monumental.png
   - stage03_phase24_detail.png
2. Amplified Difference Maps (5x vs Reference Target):
   - stage03_phase24_diff_hero.png
   - stage03_phase24_diff_monumental.png
   - stage03_phase24_diff_detail.png
3. 4-Panel Side-by-Side Comparison Panels:
   [1. Cinematic Reference Target] | [2. Three.js Phase 2.3 Baseline]
   [3. Three.js Phase 2.4 Final]   | [4. Difference Visualization (5x)]
   - stage03_phase24_panel_hero.png
   - stage03_phase24_panel_monumental.png
   - stage03_phase24_panel_detail.png
4. Full Quantitative Comparison JSON:
   - stage03_phase24_comparison.json
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
REFS_DIR = os.path.join(BLEND_DIR, "references", "stage03_memory")

PORT = 5188
URL = f"http://127.0.0.1:{PORT}/stage03_validation.html"

VIEWS = [
    {
        "key": "hero",
        "cam": "CAM_CinematicHero",
        "title": "Cinematic Hero Establishing",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_hero.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase24_hero.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase24_diff_hero.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase24_panel_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_monumental.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase24_monumental.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase24_diff_monumental.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase24_panel_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
        "baseline": os.path.join(RENDERS_DIR, "stage03_phase23_detail.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase24_detail.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase24_diff_detail.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase24_panel_detail.png"),
    }
]

# Final Phase 2.4 Configuration (Variant E - Cinematic Look Development)
PHASE24_FINAL_CONFIG = {
    "variant": "E",
    "toneMapping": "ACESFilmic",
    "exposure": 0.8122,
    "planarReflection": True,
    "planarIntensity": 0.38,
    "renderMode": "standard",
    "daisBounceIntensity": 3.5,
    "fogColor": "#38485c",
    "fogDensity": 0.0040,
    "ambientIntensity": 0.30,
    "envOptions": {
        "zenithColor": "#101824",
        "horizonColor": "#38485c",
        "groundColor": "#080d14",
        "warmGlowIntensity": 0.35,
        "warmGlowRadius": 110,
        "cloudBands": True,
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
        "target_mean_rgb": c_mean,
        "render_mean_rgb": r_mean,
        "total_error_abs": float(np.sum(diff))
    }

def analyze_full_and_regional_metrics(ref_path, render_path, diff_output_path=None):
    img1 = Image.open(ref_path).convert('RGB')
    img2 = Image.open(render_path).convert('RGB')
    
    if img1.size != img2.size:
        img1 = img1.resize(img2.size, Image.Resampling.LANCZOS)
        
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

def create_4panel_image(ref_path, baseline_path, final_path, diff_path, output_panel_path, title):
    w, h = 960, 540
    img_ref = Image.open(ref_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_base = Image.open(baseline_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS) if os.path.exists(baseline_path) else img_ref
    img_final = Image.open(final_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_diff = Image.open(diff_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    
    grid = Image.new('RGB', (w * 2, h * 2 + 60), color=(15, 20, 28))
    draw = ImageDraw.Draw(grid)
    
    grid.paste(img_ref, (0, 30))
    grid.paste(img_base, (w, 30))
    grid.paste(img_final, (0, h + 60))
    grid.paste(img_diff, (w, h + 60))
    
    draw.text((20, 8), f"1. LOCKED CINEMATIC TARGET ({title})", fill=(200, 220, 240))
    draw.text((w + 20, 8), "2. THREE.JS PHASE 2.3 BASELINE (Dark/Game-Engine Look)", fill=(200, 220, 240))
    draw.text((20, h + 38), "3. THREE.JS PHASE 2.4 CINEMATIC LOOK-DEV (Atmospheric Haze + Soft PBR)", fill=(255, 180, 50))
    draw.text((w + 20, h + 38), "4. AMPLIFIED DIFFERENCE MAP (5x vs Target)", fill=(255, 100, 100))
    
    grid.save(output_panel_path)
    print(f"Generated 4-panel comparison: {output_panel_path}")

def main():
    print("\n" + "="*80)
    print("PHASE 2.4: GENERATING FINAL VALIDATION RENDERS & 4-PANEL COMPARISONS")
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
        
        comparison_results = {
            "metadata": {
                "phase": "2.4",
                "date": time.strftime("%Y-%m-%d"),
                "solution": "Phase 2.4 Cinematic Look-Development (Atmospheric Perspective + Softened Metallic Response + Integrated Reactor Radiance + Archival Vitrines)",
                "config": PHASE24_FINAL_CONFIG
            },
            "views": {}
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
            
            # Apply Phase 2.4 Final Cinematic Configuration
            print("\nApplying Phase 2.4 Final Cinematic Look Configuration...")
            page.evaluate(f"window.setDiagnosticConfig({json.dumps(PHASE24_FINAL_CONFIG)})")
            time.sleep(1.0)
            
            for v in VIEWS:
                key = v["key"]
                cam = v["cam"]
                title = v["title"]
                ref_path = v["ref"]
                clean_path = v["clean"]
                baseline_path = v["baseline"]
                render_path = v["render"]
                diff_path = v["diff"]
                panel_path = v["panel"]
                
                print(f"\nProcessing View: {title} ({cam})...")
                page.evaluate(f"window.setCameraView('{cam}', true)")
                time.sleep(0.5)
                
                # Settle frames
                for _ in range(6):
                    page.evaluate("window.renderFrame()")
                    
                page.screenshot(path=render_path)
                print(f"Saved 1920x1080 render: {render_path}")
                
                perf = page.evaluate("window.getPerformanceMetrics()")
                
                # Full & regional metrics vs Primary Reference Target
                vs_ref = analyze_full_and_regional_metrics(ref_path, render_path, diff_path)
                # Full & regional metrics vs Clean Benchmark
                vs_clean = analyze_full_and_regional_metrics(clean_path, render_path, None)
                
                # Generate 4-panel comparison
                create_4panel_image(ref_path, baseline_path, render_path, diff_path, panel_path, title)
                
                comparison_results["views"][key] = {
                    "camera": cam,
                    "title": title,
                    "performance": perf,
                    "vs_target_reference": vs_ref,
                    "vs_clean_benchmark": vs_clean,
                    "render_file": render_path,
                    "diff_file": diff_path,
                    "panel_file": panel_path
                }
                
                print(f"Performance: {perf['drawCalls']} draw calls, {perf['triangles']} triangles, {perf['frameTimeMs']} ms ({perf['fps']} FPS)")
                print(f"Vs Reference Target: MAE={vs_ref['overall']['mae']}, PSNR={vs_ref['overall']['psnr']} dB, SSIM={vs_ref['overall']['ssim']}")
                print(f"  Floor MAE: {vs_ref['regions']['floor']['mae']}, Core MAE: {vs_ref['regions']['core']['mae']}, Sky MAE: {vs_ref['regions']['sky']['mae']}")
                print(f"Vs Clean Pass:       MAE={vs_clean['overall']['mae']}, PSNR={vs_clean['overall']['psnr']} dB")

            browser.close()
            
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase24_comparison.json")
        with open(out_json_path, "w") as f:
            json.dump(comparison_results, f, indent=2)
        print(f"\nSaved full quantitative comparison to: {out_json_path}")
        print("="*80)
        print("PHASE 2.4 VALIDATION RENDERING COMPLETE")
        print("="*80)
        
    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
