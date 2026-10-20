#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Phase 2.6: Perceptual Difference Isolation & Large-Scale Luminance Analysis
===============================================================================
Generates:
1. 8x6 grid normalized luminance error maps
2. Color distribution (histograms, saturation, warm/cool balance)
3. Edge sharpness & microcontrast analysis (Laplacian, Sobel edge density)
4. Specific Regions A-F Perceptual Analysis (Sky, Reactor, Mass, Stairs, Floor, Colonnades)
5. Output: blender/assets/stage03_memory/stage03_phase26_luminance_analysis.json
===============================================================================
"""

import json
import math
import os
import sys
import cv2
import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")
REFS_DIR = os.path.join(BLEND_DIR, "references", "stage03_memory")

PAIRS = [
    {
        "key": "hero",
        "title": "Cinematic Hero Establishing",
        "cam": "CAM_CinematicHero",
        "ref": os.path.join(REFS_DIR, "memory_hero.jpg"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase25_hero.png")
    },
    {
        "key": "monumental",
        "title": "Monumental Rotunda Colonnade",
        "cam": "CAM_MonumentalLowAngle",
        "ref": os.path.join(REFS_DIR, "memory_low_angle.jpg"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase25_monumental.png")
    },
    {
        "key": "detail",
        "title": "Archival Vitrine Detail",
        "cam": "CAM_ArchiveDetail",
        "ref": os.path.join(REFS_DIR, "memory_detail.jpg"),
        "render": os.path.join(RENDERS_DIR, "stage03_phase25_detail.png")
    }
]

def analyze_image_pair(ref_path, render_path):
    # Load and resize
    i_ref = Image.open(ref_path).convert('RGB')
    i_rnd = Image.open(render_path).convert('RGB')
    if i_ref.size != (1920, 1080):
        i_ref = i_ref.resize((1920, 1080), Image.Resampling.LANCZOS)
    if i_rnd.size != (1920, 1080):
        i_rnd = i_rnd.resize((1920, 1080), Image.Resampling.LANCZOS)

    arr_ref = np.array(i_ref, dtype=np.float32)
    arr_rnd = np.array(i_rnd, dtype=np.float32)

    # Luminance: Rec. 709 / standard sRGB weights
    lum_ref = 0.2126 * arr_ref[:,:,0] + 0.7152 * arr_ref[:,:,1] + 0.0722 * arr_ref[:,:,2]
    lum_rnd = 0.2126 * arr_rnd[:,:,0] + 0.7152 * arr_rnd[:,:,1] + 0.0722 * arr_rnd[:,:,2]
    lum_diff = np.abs(lum_ref - lum_rnd)

    # Edge analysis using OpenCV Sobel and Laplacian
    gray_ref = cv2.cvtColor(np.uint8(arr_ref), cv2.COLOR_RGB2GRAY)
    gray_rnd = cv2.cvtColor(np.uint8(arr_rnd), cv2.COLOR_RGB2GRAY)

    sobel_ref = cv2.Sobel(gray_ref, cv2.CV_64F, 1, 1, ksize=3)
    sobel_rnd = cv2.Sobel(gray_rnd, cv2.CV_64F, 1, 1, ksize=3)
    edge_mag_ref = np.sqrt(sobel_ref**2)
    edge_mag_rnd = np.sqrt(sobel_rnd**2)

    laplacian_var_ref = float(cv2.Laplacian(gray_ref, cv2.CV_64F).var())
    laplacian_var_rnd = float(cv2.Laplacian(gray_rnd, cv2.CV_64F).var())

    # Saturation (HSV)
    hsv_ref = cv2.cvtColor(np.uint8(arr_ref), cv2.COLOR_RGB2HSV)
    hsv_rnd = cv2.cvtColor(np.uint8(arr_rnd), cv2.COLOR_RGB2HSV)
    sat_ref = hsv_ref[:,:,1] / 255.0
    sat_rnd = hsv_rnd[:,:,1] / 255.0

    # Warm / cool pixel distributions
    # Warm: R > B * 1.15 and R > 30
    warm_mask_ref = (arr_ref[:,:,0] > arr_ref[:,:,2] * 1.15) & (arr_ref[:,:,0] > 30)
    warm_mask_rnd = (arr_rnd[:,:,0] > arr_rnd[:,:,2] * 1.15) & (arr_rnd[:,:,0] > 30)
    cool_mask_ref = (arr_ref[:,:,2] > arr_ref[:,:,0] * 1.10) & (arr_ref[:,:,2] > 20)
    cool_mask_rnd = (arr_rnd[:,:,2] > arr_rnd[:,:,0] * 1.10) & (arr_rnd[:,:,2] > 20)

    # Highlight clipping (> 240 in any channel)
    clip_ref = float(np.mean(np.max(arr_ref, axis=2) > 240.0) * 100.0)
    clip_rnd = float(np.mean(np.max(arr_rnd, axis=2) > 240.0) * 100.0)

    # 1. 8x6 Grid Spatial Analysis (8 cols, 6 rows = 48 cells)
    rows, cols = 6, 8
    h, w = 1080, 1920
    row_h = h // rows
    col_w = w // cols

    grid_cells = []
    for r in range(rows):
        for c in range(cols):
            y0, y1 = r * row_h, (r + 1) * row_h
            x0, x1 = c * col_w, (c + 1) * col_w

            cell_ref_lum = lum_ref[y0:y1, x0:x1]
            cell_rnd_lum = lum_rnd[y0:y1, x0:x1]
            cell_diff_lum = lum_diff[y0:y1, x0:x1]

            cell_ref_rgb = arr_ref[y0:y1, x0:x1, :]
            cell_rnd_rgb = arr_rnd[y0:y1, x0:x1, :]

            cell_ref_edge = edge_mag_ref[y0:y1, x0:x1]
            cell_rnd_edge = edge_mag_rnd[y0:y1, x0:x1]

            mean_lum_ref = float(np.mean(cell_ref_lum))
            mean_lum_rnd = float(np.mean(cell_rnd_lum))
            mae_lum = float(np.mean(cell_diff_lum))

            grid_cells.append({
                "row": r,
                "col": c,
                "x_range": [x0, x1],
                "y_range": [y0, y1],
                "ref_mean_lum": round(mean_lum_ref, 2),
                "rnd_mean_lum": round(mean_lum_rnd, 2),
                "lum_delta": round(mean_lum_rnd - mean_lum_ref, 2), # positive = render is brighter, negative = render is darker
                "lum_mae": round(mae_lum, 2),
                "ref_mean_rgb": [round(float(np.mean(cell_ref_rgb[:,:,ch])), 2) for ch in range(3)],
                "rnd_mean_rgb": [round(float(np.mean(cell_rnd_rgb[:,:,ch])), 2) for ch in range(3)],
                "ref_edge_density": round(float(np.mean(cell_ref_edge)), 2),
                "rnd_edge_density": round(float(np.mean(cell_rnd_edge)), 2),
            })

    # 2. Key Visual Regions A - F
    regions_def = {
        "A_sky": (slice(0, int(h * 0.35)), slice(0, w)),
        "B_reactor_core": (slice(int(h * 0.28), int(h * 0.52)), slice(int(w * 0.40), int(w * 0.60))),
        "C_architectural_mass": (slice(int(h * 0.20), int(h * 0.65)), slice(int(w * 0.20), int(w * 0.80))),
        "D_foreground_stairs": (slice(int(h * 0.55), int(h * 0.72)), slice(int(w * 0.32), int(w * 0.68))),
        "E_floor": (slice(int(h * 0.65), h), slice(0, w)),
        "F_colonnade_left": (slice(int(h * 0.25), int(h * 0.65)), slice(0, int(w * 0.32))),
        "F_colonnade_right": (slice(int(h * 0.25), int(h * 0.65)), slice(int(w * 0.68), w))
    }

    region_analysis = {}
    for r_key, (sl_y, sl_x) in regions_def.items():
        sub_ref_rgb = arr_ref[sl_y, sl_x, :]
        sub_rnd_rgb = arr_rnd[sl_y, sl_x, :]
        sub_diff = np.abs(sub_ref_rgb - sub_rnd_rgb)

        sub_ref_lum = lum_ref[sl_y, sl_x]
        sub_rnd_lum = lum_rnd[sl_y, sl_x]
        sub_sat_ref = sat_ref[sl_y, sl_x]
        sub_sat_rnd = sat_rnd[sl_y, sl_x]

        region_analysis[r_key] = {
            "mae": round(float(np.mean(sub_diff)), 2),
            "ref_mean_lum": round(float(np.mean(sub_ref_lum)), 2),
            "rnd_mean_lum": round(float(np.mean(sub_rnd_lum)), 2),
            "lum_delta": round(float(np.mean(sub_rnd_lum) - np.mean(sub_ref_lum)), 2),
            "ref_mean_rgb": [round(float(np.mean(sub_ref_rgb[:,:,ch])), 2) for ch in range(3)],
            "rnd_mean_rgb": [round(float(np.mean(sub_rnd_rgb[:,:,ch])), 2) for ch in range(3)],
            "ref_mean_sat": round(float(np.mean(sub_sat_ref)), 3),
            "rnd_mean_sat": round(float(np.mean(sub_sat_rnd)), 3),
        }

    return {
        "global_summary": {
            "ref_mean_lum": round(float(np.mean(lum_ref)), 2),
            "rnd_mean_lum": round(float(np.mean(lum_rnd)), 2),
            "lum_delta_overall": round(float(np.mean(lum_rnd) - np.mean(lum_ref)), 2),
            "ref_mean_rgb": [round(float(np.mean(arr_ref[:,:,ch])), 2) for ch in range(3)],
            "rnd_mean_rgb": [round(float(np.mean(arr_rnd[:,:,ch])), 2) for ch in range(3)],
            "ref_mean_sat": round(float(np.mean(sat_ref)), 3),
            "rnd_mean_sat": round(float(np.mean(sat_rnd)), 3),
            "warm_pixels_pct": {
                "ref": round(float(np.mean(warm_mask_ref) * 100.0), 2),
                "rnd": round(float(np.mean(warm_mask_rnd) * 100.0), 2)
            },
            "cool_pixels_pct": {
                "ref": round(float(np.mean(cool_mask_ref) * 100.0), 2),
                "rnd": round(float(np.mean(cool_mask_rnd) * 100.0), 2)
            },
            "highlight_clipping_pct": {
                "ref": round(clip_ref, 2),
                "rnd": round(clip_rnd, 2)
            },
            "laplacian_edge_sharpness": {
                "ref": round(laplacian_var_ref, 1),
                "rnd": round(laplacian_var_rnd, 1)
            }
        },
        "regions_A_to_F": region_analysis,
        "grid_8x6": grid_cells
    }

def main():
    print("="*80)
    print("PHASE 2.6: LARGE-SCALE LUMINANCE & PERCEPTUAL DIFFERENCE ANALYSIS")
    print("="*80)

    full_analysis = {
        "metadata": {
            "phase": "2.6",
            "benchmark_target": "memory_hero.jpg",
            "threejs_baseline": "stage03_phase25_hero.png",
            "analysis_dimensions": [1920, 1080],
            "grid_dimensions": [8, 6]
        },
        "views": {}
    }

    for p in PAIRS:
        key = p["key"]
        title = p["title"]
        print(f"\nAnalyzing View: {title} ({key})...")
        res = analyze_image_pair(p["ref"], p["render"])
        full_analysis["views"][key] = res

        glob = res["global_summary"]
        print(f"  Global Mean Luminance: Ref={glob['ref_mean_lum']}, Three.js={glob['rnd_mean_lum']} (Delta = {glob['lum_delta_overall']})")
        print(f"  Global RGB Mean:       Ref={glob['ref_mean_rgb']}, Three.js={glob['rnd_mean_rgb']}")
        print(f"  Global Saturation:     Ref={glob['ref_mean_sat']}, Three.js={glob['rnd_mean_sat']}")
        print(f"  Warm / Cool Pixels %:  Ref: {glob['warm_pixels_pct']['ref']}% warm / {glob['cool_pixels_pct']['ref']}% cool | Rnd: {glob['warm_pixels_pct']['rnd']}% warm / {glob['cool_pixels_pct']['rnd']}% cool")
        print(f"  Edge Sharpness (Lap):  Ref={glob['laplacian_edge_sharpness']['ref']}, Three.js={glob['laplacian_edge_sharpness']['rnd']}")

        print("\n  Regional Breakdowns (A - F):")
        for r_name, r_data in res["regions_A_to_F"].items():
            print(f"    Region {r_name:22s}: MAE={r_data['mae']:5.2f} | Ref Lum={r_data['ref_mean_lum']:5.2f} vs Rnd Lum={r_data['rnd_mean_lum']:5.2f} (Delta={r_data['lum_delta']:+5.2f}) | Ref RGB={r_data['ref_mean_rgb']} vs Rnd={r_data['rnd_mean_rgb']}")

    out_json = os.path.join(ASSETS_DIR, "stage03_phase26_luminance_analysis.json")
    with open(out_json, "w") as f:
        json.dump(full_analysis, f, indent=2)
    print(f"\nSaved complete luminance and perceptual analysis to: {out_json}")
    print("="*80)

if __name__ == "__main__":
    main()
