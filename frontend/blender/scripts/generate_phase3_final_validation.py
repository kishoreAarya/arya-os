#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 3: Production Readiness & Final Cinematic Runtime Validation Generator
===============================================================================
Generates:
1. Three.js Phase 3 Final Production Renders (1920x1080):
   - stage03_phase3_hero.png
   - stage03_phase3_monumental.png
   - stage03_phase3_detail.png
2. Amplified Difference Maps (5x vs Locked Reference Target):
   - stage03_phase3_diff_hero.png
   - stage03_phase3_diff_monumental.png
   - stage03_phase3_diff_detail.png
3. Luminance Heatmaps (Inferno Colormap):
   - stage03_phase3_heat_hero.png
   - stage03_phase3_heat_monumental.png
   - stage03_phase3_heat_detail.png
4. Atmospheric Depth Penetration Maps (Turbo Colormap):
   - stage03_phase3_depth_hero.png
   - stage03_phase3_depth_monumental.png
   - stage03_phase3_depth_detail.png
5. Highlight Rolloff & Diffusion Maps (Hot Colormap):
   - stage03_phase3_highlight_hero.png
   - stage03_phase3_highlight_monumental.png
   - stage03_phase3_highlight_detail.png
6. Warm/Cool Chromaticity Distribution Maps (Cool Colormap):
   - stage03_phase3_warmcool_hero.png
   - stage03_phase3_warmcool_monumental.png
   - stage03_phase3_warmcool_detail.png
7. High-Frequency Contrast & Edge Maps (Sobel Viridis):
   - stage03_phase3_contrast_hero.png
   - stage03_phase3_contrast_monumental.png
   - stage03_phase3_contrast_detail.png
8. 4-Panel Side-by-Side Comparison Panels (1920x1140):
   [1] Locked Reference Target          | [2] Phase 2.9 Baseline
   [3] Phase 3 Final Production Match   | [4] 5x Amplified Difference Map
   - stage03_phase3_panel_hero.png
   - stage03_phase3_panel_monumental.png
   - stage03_phase3_panel_detail.png
9. Full Quantitative Comparison JSON:
   - stage03_phase3_comparison.json
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
from PIL import Image, ImageDraw
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
        "baseline_p29": os.path.join(RENDERS_DIR, "stage03_phase29_hero.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase3_hero.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase3_diff_hero.png"),
        "heat": os.path.join(RENDERS_DIR, "stage03_phase3_heat_hero.png"),
        "depth": os.path.join(RENDERS_DIR, "stage03_phase3_depth_hero.png"),
        "highlight": os.path.join(RENDERS_DIR, "stage03_phase3_highlight_hero.png"),
        "warmcool": os.path.join(RENDERS_DIR, "stage03_phase3_warmcool_hero.png"),
        "contrast": os.path.join(RENDERS_DIR, "stage03_phase3_contrast_hero.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase3_panel_hero.png"),
    },
    {
        "key": "monumental",
        "cam": "CAM_MonumentalLowAngle",
        "title": "Monumental Rotunda Colonnade",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "baseline_p29": os.path.join(RENDERS_DIR, "stage03_phase29_monumental.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase3_monumental.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase3_diff_monumental.png"),
        "heat": os.path.join(RENDERS_DIR, "stage03_phase3_heat_monumental.png"),
        "depth": os.path.join(RENDERS_DIR, "stage03_phase3_depth_monumental.png"),
        "highlight": os.path.join(RENDERS_DIR, "stage03_phase3_highlight_monumental.png"),
        "warmcool": os.path.join(RENDERS_DIR, "stage03_phase3_warmcool_monumental.png"),
        "contrast": os.path.join(RENDERS_DIR, "stage03_phase3_contrast_monumental.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase3_panel_monumental.png"),
    },
    {
        "key": "detail",
        "cam": "CAM_ArchiveDetail",
        "title": "Archival Vitrine Detail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "baseline_p29": os.path.join(RENDERS_DIR, "stage03_phase29_detail.png"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase3_detail.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_phase3_diff_detail.png"),
        "heat": os.path.join(RENDERS_DIR, "stage03_phase3_heat_detail.png"),
        "depth": os.path.join(RENDERS_DIR, "stage03_phase3_depth_detail.png"),
        "highlight": os.path.join(RENDERS_DIR, "stage03_phase3_highlight_detail.png"),
        "warmcool": os.path.join(RENDERS_DIR, "stage03_phase3_warmcool_detail.png"),
        "contrast": os.path.join(RENDERS_DIR, "stage03_phase3_contrast_detail.png"),
        "panel": os.path.join(RENDERS_DIR, "stage03_phase3_panel_detail.png"),
    }
]

# Phase 3 Locked Production Configuration (Preserving Phase 2.9 Baseline)
PHASE3_FINAL_CONFIG = {
    "variant": "P3_PRODUCTION",
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

def analyze_full_and_regional_metrics(ref_path, render_path, diff_output_path=None, heat_output_path=None, depth_output_path=None, highlight_output_path=None, warmcool_path=None, contrast_path=None):
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
    
    if diff_output_path:
        diff_amplified = np.clip(diff * 5.0, 0, 255).astype(np.uint8)
        diff_img = Image.fromarray(diff_amplified)
        diff_img.save(diff_output_path)

    if heat_output_path:
        norm_lum = np.clip(lum2 / 255.0 * 255.0, 0, 255).astype(np.uint8)
        heatmap = cv2.applyColorMap(norm_lum, cv2.COLORMAP_INFERNO)
        cv2.imwrite(heat_output_path, heatmap)

    if depth_output_path:
        fog_ref = np.array([82.0, 101.0, 122.0], dtype=np.float32)
        color_dist = np.sqrt(np.sum((arr2 - fog_ref) ** 2, axis=2))
        depth_haze = np.clip(255.0 - (color_dist * 1.2), 0, 255).astype(np.uint8)
        depth_colored = cv2.applyColorMap(depth_haze, cv2.COLORMAP_TURBO)
        cv2.imwrite(depth_output_path, depth_colored)

    if highlight_output_path:
        highlight_mask = np.clip((lum2 - 130.0) / (255.0 - 130.0) * 255.0, 0, 255).astype(np.uint8)
        highlight_colored = cv2.applyColorMap(highlight_mask, cv2.COLORMAP_HOT)
        cv2.imwrite(highlight_output_path, highlight_colored)

    if warmcool_path:
        chroma_diff = np.clip((arr2[:,:,0] - arr2[:,:,2] + 60.0) / 120.0 * 255.0, 0, 255).astype(np.uint8)
        warmcool_map = cv2.applyColorMap(chroma_diff, cv2.COLORMAP_COOL)
        cv2.imwrite(warmcool_path, warmcool_map)

    if contrast_path:
        gray = lum2.astype(np.uint8)
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        edge_mag = np.clip(np.sqrt(sobelx**2 + sobely**2) * 2.5, 0, 255).astype(np.uint8)
        edge_colored = cv2.applyColorMap(edge_mag, cv2.COLORMAP_VIRIDIS)
        cv2.imwrite(contrast_path, edge_colored)
    
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

def create_4panel_image(ref_path, baseline_p29_path, final_p3_path, diff_path, output_panel_path, title):
    w, h = 960, 540
    img_ref = Image.open(ref_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_base = Image.open(baseline_p29_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS) if os.path.exists(baseline_p29_path) else img_ref
    img_final = Image.open(final_p3_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    img_diff = Image.open(diff_path).convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
    
    grid = Image.new('RGB', (w * 2, h * 2 + 60), color=(14, 18, 24))
    draw = ImageDraw.Draw(grid)
    
    grid.paste(img_ref, (0, 30))
    grid.paste(img_base, (w, 30))
    grid.paste(img_final, (0, h + 60))
    grid.paste(img_diff, (w, h + 60))
    
    draw.text((20, 8), f"1. LOCKED CINEMATIC TARGET ({title})", fill=(210, 230, 250))
    draw.text((w + 20, 8), "2. THREE.JS PHASE 2.9 BASELINE (Photographic Polish)", fill=(200, 220, 240))
    draw.text((20, h + 38), "3. THREE.JS PHASE 3 FINAL (Production-Ready Runtime Integration)", fill=(255, 185, 55))
    draw.text((w + 20, h + 38), "4. AMPLIFIED DIFFERENCE MAP (5x vs Locked Target)", fill=(255, 110, 110))
    
    grid.save(output_panel_path)
    print(f"Generated 4-panel comparison: {output_panel_path}")

def main():
    print("\n" + "="*80)
    print("PHASE 3: GENERATING FINAL PRODUCTION VALIDATION RENDERS & 4-PANEL COMPARISONS")
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
                "phase": "3.0",
                "date": time.strftime("%Y-%m-%d"),
                "solution": "Phase 3 Production Readiness & Cinematic Runtime Integration",
                "config": PHASE3_FINAL_CONFIG
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
            
            print("\nApplying Phase 3 Production Configuration...")
            page.evaluate(f"window.setDiagnosticConfig({json.dumps(PHASE3_FINAL_CONFIG)})")
            time.sleep(1.0)
            
            for v in VIEWS:
                key = v["key"]
                cam = v["cam"]
                title = v["title"]
                ref_path = v["ref"]
                baseline_p29_path = v["baseline_p29"]
                render_path = v["render"]
                diff_path = v["diff"]
                heat_path = v["heat"]
                depth_path = v["depth"]
                highlight_path = v["highlight"]
                warmcool_path = v["warmcool"]
                contrast_path = v["contrast"]
                panel_path = v["panel"]
                
                print(f"\nProcessing View: {title} ({cam})...")
                page.evaluate(f"window.setCameraView('{cam}', true)")
                time.sleep(0.5)
                
                for _ in range(6):
                    page.evaluate("window.renderFrame()")
                    
                page.screenshot(path=render_path)
                print(f"Saved 1920x1080 render: {render_path}")
                
                perf = page.evaluate("window.getPerformanceMetrics()")
                
                # Full & regional metrics vs Primary Reference Target
                vs_ref = analyze_full_and_regional_metrics(ref_path, render_path, diff_path, heat_path, depth_path, highlight_path, warmcool_path, contrast_path)
                # Full & regional metrics vs Phase 2.9 Baseline
                vs_p29 = analyze_full_and_regional_metrics(baseline_p29_path, render_path, None, None, None, None, None, None) if os.path.exists(baseline_p29_path) else None
                
                # Generate 4-panel comparison
                create_4panel_image(ref_path, baseline_p29_path, render_path, diff_path, panel_path, title)
                
                comparison_results["views"][key] = {
                    "camera": cam,
                    "title": title,
                    "performance": perf,
                    "vs_target_reference": vs_ref,
                    "vs_phase29_baseline": vs_p29,
                    "render_file": render_path,
                    "diff_file": diff_path,
                    "heat_file": heat_path,
                    "depth_file": depth_path,
                    "highlight_file": highlight_path,
                    "warmcool_file": warmcool_path,
                    "contrast_file": contrast_path,
                    "panel_file": panel_path
                }
                
                print(f"Performance: {perf['drawCalls']} draw calls, {perf['triangles']} triangles, {perf['frameTimeMs']} ms ({perf['fps']} FPS)")
                print(f"Vs Reference Target: MAE={vs_ref['overall']['mae']}, PSNR={vs_ref['overall']['psnr']} dB, SSIM={vs_ref['overall']['ssim']}")
                print(f"  Mean Luminance: {vs_ref['overall']['mean_lum']}, Warm Pixels: {vs_ref['overall']['warm_pixels_pct']}%")
                print(f"  Floor MAE: {vs_ref['regions']['floor']['mae']}, Core MAE: {vs_ref['regions']['core']['mae']}, Sky MAE: {vs_ref['regions']['sky']['mae']}")
                if vs_p29:
                    print(f"Vs Phase 2.9 Base:   MAE={vs_p29['overall']['mae']}, PSNR={vs_p29['overall']['psnr']} dB, SSIM={vs_p29['overall']['ssim']}")

            browser.close()
            
        out_json_path = os.path.join(ASSETS_DIR, "stage03_phase3_comparison.json")
        with open(out_json_path, "w") as f:
            json.dump(comparison_results, f, indent=2)
        print(f"\nSaved full quantitative comparison to: {out_json_path}")
        print("="*80)
        print("PHASE 3 VALIDATION RENDERING COMPLETE")
        print("="*80)
        
    finally:
        print("Stopping Vite dev server...")
        try:
            os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
        except Exception:
            pass

if __name__ == "__main__":
    main()
