# AryaOS V1 — 3D Asset Directory

This directory hosts production 3D assets for the AryaOS V1 Spatial World.

## Expected Asset Specification

- **Primary Path**: `/models/aryaos-core.glb` (served as `public/models/aryaos-core.glb`)
- **Format**: GLTF 2.0 Binary (`.glb`)
- **Scale**: Hero scale (approx 3.0 to 4.5 units height, Y-up)
- **Origin**: Centered at base/bottom `[0, 0, 0]`
- **Materials**: Physically Based Rendering (PBR) Metallic/Roughness workflow:
  - Outer Armor/Shell: High metalness (0.85–0.95), medium roughness (0.2–0.35), graphite/gunmetal tone
  - Mechanical Structure: High metalness, dark obsidian tone
  - Energy Conduits: Emissive amber/gold (`#f59e0b` / `#fbbf24`) with controlled intensity
- **Optimization**: Draco mesh compression or meshopt compatible; polygon budget < 100k triangles for real-time 60fps performance

## Fallback Behavior

When `/models/aryaos-core.glb` is not present, `SpatialCore` automatically and seamlessly displays the procedural machine architecture (`SpatialMonolith.tsx`) with zero downtime or visual breakage.
