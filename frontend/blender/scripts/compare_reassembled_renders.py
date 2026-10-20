#!/usr/bin/env python3
"""
===============================================================================
ARYAOS V1 — STAGE 03: MEMORY ARCHIVE
Visual Comparison Script (System Python with PIL + NumPy)
===============================================================================
"""

import json
import math
import os
import sys
import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
BLEND_DIR = os.path.join(FRONTEND_DIR, "blender")
ASSETS_DIR = os.path.join(BLEND_DIR, "assets", "stage03_memory")
RENDERS_DIR = os.path.join(BLEND_DIR, "renders")

BENCHMARKS = {
    "hero": {
        "title": "Archival Hero Establishing",
        "cam": "CAM_CinematicHero",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_hero.png"),
        "reassembled": os.path.join(RENDERS_DIR, "stage03_memory_reassembled_hero.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_memory_diff_hero.png")
    },
    "monumental": {
        "title": "Monumental Rotunda Colonnade",
        "cam": "CAM_MonumentalLowAngle",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_monumental.png"),
        "reassembled": os.path.join(RENDERS_DIR, "stage03_memory_reassembled_monumental.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_memory_diff_monumental.png")
    },
    "detail": {
        "title": "Archival Vitrine Detail",
        "cam": "CAM_ArchiveDetail",
        "clean": os.path.join(RENDERS_DIR, "stage03_memory_clean_detail.png"),
        "reassembled": os.path.join(RENDERS_DIR, "stage03_memory_reassembled_detail.png"),
        "diff": os.path.join(RENDERS_DIR, "stage03_memory_diff_detail.png")
    }
}

def compare_images(clean_path, reassembled_path, diff_path):
    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Missing clean benchmark: {clean_path}")
    if not os.path.exists(reassembled_path):
        raise FileNotFoundError(f"Missing reassembled render: {reassembled_path}")
        
    img1 = Image.open(clean_path).convert('RGB')
    img2 = Image.open(reassembled_path).convert('RGB')
    
    arr1 = np.array(img1, dtype=np.float32)
    arr2 = np.array(img2, dtype=np.float32)
    
    if arr1.shape != arr2.shape:
        raise ValueError(f"Shape mismatch: {arr1.shape} vs {arr2.shape}")
        
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
    print("STAGE 03: BENCHMARK VISUAL COMPARISON")
    print("="*80)
    
    results = {}
    for key, info in BENCHMARKS.items():
        print(f"\nAnalyzing [{info['title']} - {info['cam']}] ...")
        comp = compare_images(info["clean"], info["reassembled"], info["diff"])
        results[key] = {
            "title": info["title"],
            "camera": info["cam"],
            **comp
        }
        print(f"  Resolution: {comp['resolution']}")
        print(f"  PSNR:       {comp['psnr']} dB")
        print(f"  SSIM:       {comp['ssim']}")
        print(f"  RMSE:       {comp['rmse']}")
        print(f"  MAE:        {comp['mae']}")
        print(f"  Max Diff:   {comp['max_diff']} / 255")
        print(f"  Diff Map:   {comp['diff_map']}")
        
    out_json = os.path.join(ASSETS_DIR, "stage03_memory_reassembly_comparison.json")
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved comparison metrics: {out_json}")
    
    print("\n" + "="*80)
    print("ALL COMPARISONS COMPLETED!")
    print("="*80)

if __name__ == "__main__":
    main()
