import * as THREE from 'three';
import * as BufferGeometryUtils from 'three/examples/jsm/utils/BufferGeometryUtils.js';

export interface Stage03CameraConfig {
  name: string;
  position: [number, number, number];
  target: [number, number, number];
  fov: number; // Vertical FOV in degrees
  focalLength: number;
}

export const STAGE03_CAMERAS: Record<string, Stage03CameraConfig> = {
  CAM_CinematicHero: {
    name: 'CAM_CinematicHero',
    position: [-12.0, 2.3, 38.5],
    target: [0.0, 9.8, 4.5],
    fov: 39.761,
    focalLength: 28.0,
  },
  CAM_MonumentalLowAngle: {
    name: 'CAM_MonumentalLowAngle',
    position: [0.0, 0.65, 26.0],
    target: [0.0, 16.5, 1.0],
    fov: 49.426,
    focalLength: 22.0,
  },
  CAM_ArchiveDetail: {
    name: 'CAM_ArchiveDetail',
    position: [-16.2, 1.85, 32.8],
    target: [-4.0, 2.5, 23.0],
    fov: 35.115,
    focalLength: 32.0,
  },
};

export interface Stage03MaterialPalette {
  obsidianStructure: THREE.MeshStandardMaterial;
  obsidianFloorWet: THREE.MeshPhysicalMaterial;
  gunmetal: THREE.MeshStandardMaterial;
  titanium: THREE.MeshStandardMaterial;
  amberRestrained: THREE.MeshStandardMaterial;
  amberEmission: THREE.MeshStandardMaterial;
  amberCoreBright: THREE.MeshStandardMaterial;
  crystalGlass: THREE.MeshPhysicalMaterial;
  cyanTelemetry: THREE.MeshStandardMaterial;
  distantTower: THREE.MeshStandardMaterial;
  floatingSlab: THREE.MeshStandardMaterial;
  humanSilhouette: THREE.MeshStandardMaterial;
  voxel: THREE.MeshStandardMaterial;
  voxelDeep: THREE.MeshStandardMaterial;
  verticalSheath: THREE.MeshPhysicalMaterial;
  verticalCore: THREE.MeshBasicMaterial;
}

export interface EnvironmentTextureOptions {
  zenithColor?: string;
  upperSkyColor?: string;
  horizonColor?: string;
  lowerHorizonColor?: string;
  groundColor?: string;
  warmGlowRadius?: number;
  warmGlowIntensity?: number;
  cloudBands?: boolean;
  bakedGroundBounce?: boolean;
}

/**
 * Creates the procedural environmental radiance map in Three.js.
 * Provides the cool steel-blue atmospheric sky dome and soft warm central core reflection
 * that gives PBR metals and glass their physical specular readability.
 */
export function createStage03EnvironmentTexture(options: EnvironmentTextureOptions = {}): THREE.Texture {
  if (typeof document === 'undefined') {
    return new THREE.Texture();
  }
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new THREE.Texture();

  const zenith = options.zenithColor || '#182230';
  const upperSky = options.upperSkyColor || '#2c3a4b';
  const horizon = options.horizonColor || '#5a6b7e';
  const lowerHorizon = options.lowerHorizonColor || '#38495a';
  const ground = options.groundColor || '#0e151e';

  // Vertical sky-to-ground atmospheric gradient matching Blender MAT_Stormy_Sky_Dome
  const grad = ctx.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0.0, zenith);      // Zenith (cool deep stormy space)
  grad.addColorStop(0.28, upperSky);  // Upper sky dome
  grad.addColorStop(0.48, horizon);    // Horizon (steel-blue atmospheric haze)
  grad.addColorStop(0.55, lowerHorizon);  // Immediate ground horizon
  grad.addColorStop(1.0, ground);      // Ground (deep obsidian)
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 256);

  // Photographic storm cloud strata matching Blender MAT_Stormy_Sky_Dome volumetric noise
  if (options.cloudBands !== false) {
    ctx.save();
    // Pass 1: Broad macro atmospheric cloud shelves
    const macroShelves = [
      { y: 26, h: 24, alpha: 0.22 },
      { y: 50, h: 26, alpha: 0.30 },
      { y: 78, h: 28, alpha: 0.36 },
      { y: 108, h: 24, alpha: 0.28 },
      { y: 134, h: 18, alpha: 0.20 },
    ];
    for (const shelf of macroShelves) {
      const cloudGrad = ctx.createLinearGradient(0, shelf.y, 512, shelf.y + shelf.h);
      cloudGrad.addColorStop(0.0, 'rgba(48, 62, 80, 0.0)');
      cloudGrad.addColorStop(0.20, `rgba(62, 80, 102, ${(shelf.alpha * 0.75).toFixed(3)})`);
      cloudGrad.addColorStop(0.50, `rgba(82, 104, 130, ${shelf.alpha.toFixed(3)})`);
      cloudGrad.addColorStop(0.80, `rgba(58, 76, 98, ${(shelf.alpha * 0.65).toFixed(3)})`);
      cloudGrad.addColorStop(1.0, 'rgba(48, 62, 80, 0.0)');
      ctx.fillStyle = cloudGrad;
      ctx.fillRect(0, shelf.y, 512, shelf.h);
    }
    // Pass 2: Soft undulating turbulent filaments
    for (let j = 0; j < 5; j++) {
      const baseY = 34 + j * 20;
      ctx.beginPath();
      ctx.moveTo(0, baseY);
      for (let x = 0; x <= 512; x += 32) {
        const offset = Math.sin((x / 512) * Math.PI * 4 + j * 1.2) * 5;
        ctx.lineTo(x, baseY + offset);
      }
      ctx.lineTo(512, baseY + 10);
      ctx.lineTo(0, baseY + 10);
      ctx.closePath();
      ctx.fillStyle = `rgba(72, 94, 118, ${0.12 - j * 0.015})`;
      ctx.fill();
    }
    ctx.restore();
  }

  // Soft warm central glow (reflecting Astrolabe core onto surrounding surfaces)
  const glowIntensity = options.warmGlowIntensity !== undefined ? options.warmGlowIntensity : 0.49;
  const glowRadius = options.warmGlowRadius !== undefined ? options.warmGlowRadius : 132;
  if (glowIntensity > 0) {
    const radGrad = ctx.createRadialGradient(256, 138, 4, 256, 138, glowRadius);
    radGrad.addColorStop(0.0, `rgba(245, 158, 11, ${glowIntensity})`);
    radGrad.addColorStop(0.35, `rgba(180, 83, 9, ${(glowIntensity * 0.44).toFixed(3)})`);
    radGrad.addColorStop(1.0, 'rgba(0, 0, 0, 0.0)');
    ctx.fillStyle = radGrad;
    ctx.fillRect(0, 0, 512, 256);
  }

  // Precomputed / baked lower-hemisphere warm ground bounce (emulating EEVEE 4-bounce Fast GI)
  if (options.bakedGroundBounce) {
    const groundBounceGrad = ctx.createRadialGradient(256, 210, 10, 256, 210, 120);
    groundBounceGrad.addColorStop(0.0, 'rgba(245, 158, 11, 0.28)');
    groundBounceGrad.addColorStop(0.4, 'rgba(180, 83, 9, 0.12)');
    groundBounceGrad.addColorStop(1.0, 'rgba(0, 0, 0, 0.0)');
    ctx.fillStyle = groundBounceGrad;
    ctx.fillRect(0, 140, 512, 116);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

export interface Stage03MaterialOptions {
  cinematicGlass?: boolean;
  obsidianRoughness?: number;
  obsidianMetalness?: number;
  obsidianColor?: THREE.ColorRepresentation;
  floorRoughness?: number;
  floorClearcoat?: number;
  floorClearcoatRoughness?: number;
  floorColor?: THREE.ColorRepresentation;
  titaniumRoughness?: number;
  titaniumColor?: THREE.ColorRepresentation;
  gunmetalRoughness?: number;
  gunmetalColor?: THREE.ColorRepresentation;
  glassColor?: THREE.ColorRepresentation;
  glassOpacity?: number;
  cyanEmissiveIntensity?: number;
  amberCoreEmissiveIntensity?: number;
  amberEnergyEmissiveIntensity?: number;
}

/**
 * Creates the calibrated physical material palette for Stage 03 Memory Archive.
 * Adheres strictly to the ARYAOS dark cinematic aesthetic:
 * DARK != PURE BLACK
 */
export function createStage03MaterialPalette(options: Stage03MaterialOptions = {}): Stage03MaterialPalette {
  const obsidianStructure = new THREE.MeshStandardMaterial({
    name: 'MAT_Obsidian_Structure_PBR',
    color: new THREE.Color(options.obsidianColor !== undefined ? options.obsidianColor : 0x0e141d),
    metalness: options.obsidianMetalness !== undefined ? options.obsidianMetalness : 0.74,
    roughness: options.obsidianRoughness !== undefined ? options.obsidianRoughness : 0.48,
  });

  const obsidianFloorWet = new THREE.MeshPhysicalMaterial({
    name: 'MAT_Obsidian_Floor_Wet_PBR',
    color: new THREE.Color(options.floorColor !== undefined ? options.floorColor : 0x121518),
    metalness: 0.80,
    roughness: options.floorRoughness !== undefined ? options.floorRoughness : 0.26,
    clearcoat: options.floorClearcoat !== undefined ? options.floorClearcoat : 0.64,
    clearcoatRoughness: options.floorClearcoatRoughness !== undefined ? options.floorClearcoatRoughness : 0.13,
    ior: 1.62,
  });

  const gunmetal = new THREE.MeshStandardMaterial({
    name: 'MAT_Gunmetal_Brushed',
    color: new THREE.Color(options.gunmetalColor !== undefined ? options.gunmetalColor : 0x1a212c),
    metalness: 0.90,
    roughness: options.gunmetalRoughness !== undefined ? options.gunmetalRoughness : 0.35,
  });

  const titanium = new THREE.MeshStandardMaterial({
    name: 'MAT_Titanium_Machined',
    color: new THREE.Color(options.titaniumColor !== undefined ? options.titaniumColor : 0x323b49),
    metalness: 0.92,
    roughness: options.titaniumRoughness !== undefined ? options.titaniumRoughness : 0.26,
  });

  const amberRestrained = new THREE.MeshStandardMaterial({
    name: 'MAT_Amber_Energy_Restrained',
    color: new THREE.Color(0x1a0e06),
    metalness: 0.85,
    roughness: 0.25,
    emissive: new THREE.Color(0x000000),
    emissiveIntensity: 0.0,
  });

  const amberEmission = new THREE.MeshStandardMaterial({
    name: 'MAT_Amber_Energy_Emission',
    color: new THREE.Color(0x241208),
    metalness: 0.70,
    roughness: 0.20,
    emissive: new THREE.Color(0xe68a10),
    emissiveIntensity: options.amberEnergyEmissiveIntensity !== undefined ? options.amberEnergyEmissiveIntensity : 0.58,
    toneMapped: true,
  });

  const amberCoreBright = new THREE.MeshStandardMaterial({
    name: 'MAT_Amber_Core_Bright',
    color: new THREE.Color(0x3a190a),
    metalness: 0.30,
    roughness: 0.10,
    emissive: new THREE.Color(0xff8418),
    emissiveIntensity: options.amberCoreEmissiveIntensity !== undefined ? options.amberCoreEmissiveIntensity : 3.0,
    toneMapped: true,
  });

  // Physical optical glass
  // Smoked dark steel archival glass for futuristic museum presentation
  const isCinematicGlass = options.cinematicGlass !== false;
  const crystalGlass = new THREE.MeshPhysicalMaterial({
    name: isCinematicGlass ? 'MAT_Crystal_Glass_Cinematic' : 'MAT_Crystal_Glass_PBR',
    color: new THREE.Color(options.glassColor !== undefined ? options.glassColor : 0x141e2a),
    metalness: 0.0,
    roughness: 0.05,
    transmission: isCinematicGlass ? 0.0 : 0.96,
    transparent: true,
    opacity: isCinematicGlass ? (options.glassOpacity !== undefined ? options.glassOpacity : 0.20) : 1.0,
    ior: 1.52,
    reflectivity: 0.80,
    clearcoat: isCinematicGlass ? 0.75 : 0.0,
    clearcoatRoughness: 0.04,
    thickness: 0.5,
    specularIntensity: 0.85,
    depthWrite: false, // critical so internal worlds inside are visible!
  });

  const cyanTelemetry = new THREE.MeshStandardMaterial({
    name: 'MAT_Cyan_Telemetry_Emission',
    color: new THREE.Color(0x06141c),
    metalness: 0.30,
    roughness: 0.55,
    emissive: new THREE.Color(0x088096),
    emissiveIntensity: options.cyanEmissiveIntensity !== undefined ? options.cyanEmissiveIntensity : 0.14,
    toneMapped: true,
  });

  const distantTower = new THREE.MeshStandardMaterial({
    name: 'MAT_Distant_Tower_Obsidian',
    color: new THREE.Color(0x0d121a),
    metalness: 0.85,
    roughness: 0.36,
  });

  const floatingSlab = new THREE.MeshStandardMaterial({
    name: 'MAT_Floating_Memory_Slab',
    color: new THREE.Color(0x0a1018),
    metalness: 0.0,
    roughness: 0.10,
    transparent: true,
    opacity: 0.28,
  });

  const humanSilhouette = new THREE.MeshStandardMaterial({
    name: 'MAT_Human_Silhouette_Black',
    color: new THREE.Color(0x020304),
    metalness: 0.0,
    roughness: 0.95,
  });

  const voxel = new THREE.MeshStandardMaterial({
    name: 'MAT_Memory_Data_Voxel',
    color: new THREE.Color(0x18202c),
    metalness: 0.40,
    roughness: 0.42,
    emissive: new THREE.Color(0x92400e),
    emissiveIntensity: 0.015,
  });

  const voxelDeep = new THREE.MeshStandardMaterial({
    name: 'MAT_Memory_Data_Voxel_Deep',
    color: new THREE.Color(0x0e131d),
    metalness: 0.20,
    roughness: 0.50,
    emissive: new THREE.Color(0xb45309),
    emissiveIntensity: 0.02,
  });

  const verticalSheath = new THREE.MeshPhysicalMaterial({
    name: 'MAT_Vertical_Conduit_Sheath',
    color: new THREE.Color(0xf5f9ff),
    metalness: 0.0,
    roughness: 0.035,
    transmission: isCinematicGlass ? 0.0 : 0.92,
    transparent: true,
    opacity: isCinematicGlass ? 0.20 : 0.85,
    clearcoat: isCinematicGlass ? 1.0 : 0.0,
    clearcoatRoughness: 0.035,
    ior: 1.50,
    thickness: 0.4,
    depthWrite: false,
  });

  const verticalCore = new THREE.MeshBasicMaterial({
    name: 'MAT_Vertical_Conduit_Core',
    color: new THREE.Color(0xff8c1f),
  });

  return {
    obsidianStructure,
    obsidianFloorWet,
    gunmetal,
    titanium,
    amberRestrained,
    amberEmission,
    amberCoreBright,
    crystalGlass,
    cyanTelemetry,
    distantTower,
    floatingSlab,
    humanSilhouette,
    voxel,
    voxelDeep,
    verticalSheath,
    verticalCore,
  };
}

/**
 * Neutral clay material palette for isolating lighting & shadow subsystems.
 */
export function createStage03NeutralPalette(): Stage03MaterialPalette {
  const neutralMat = new THREE.MeshStandardMaterial({
    name: 'MAT_Neutral_Diagnostic_Clay',
    color: new THREE.Color(0x808080),
    metalness: 0.0,
    roughness: 0.85,
  });

  const neutralGlass = new THREE.MeshPhysicalMaterial({
    name: 'MAT_Neutral_Diagnostic_Glass',
    color: new THREE.Color(0xa0a0a0),
    metalness: 0.0,
    roughness: 0.05,
    transparent: true,
    opacity: 0.20,
    depthWrite: false,
  });

  return {
    obsidianStructure: neutralMat,
    obsidianFloorWet: neutralMat as any,
    gunmetal: neutralMat,
    titanium: neutralMat,
    amberRestrained: neutralMat,
    amberEmission: neutralMat,
    amberCoreBright: neutralMat,
    crystalGlass: neutralGlass,
    cyanTelemetry: neutralMat,
    distantTower: neutralMat,
    floatingSlab: neutralMat,
    humanSilhouette: neutralMat,
    voxel: neutralMat,
    voxelDeep: neutralMat,
    verticalSheath: neutralGlass,
    verticalCore: neutralMat as any,
  };
}

export function matchStage03Material(
  matName: string,
  palette: Stage03MaterialPalette
): THREE.Material {
  const n = matName.toLowerCase();
  if (n.includes('floor_wet')) return palette.obsidianFloorWet;
  if (n.includes('core_bright')) return palette.amberCoreBright;
  if (n.includes('amber_energy_emission')) return palette.amberEmission;
  if (n.includes('amber')) return palette.amberRestrained;
  if (n.includes('cyan')) return palette.cyanTelemetry;
  if (n.includes('glass') || n.includes('prism')) return palette.crystalGlass;
  if (n.includes('gunmetal')) return palette.gunmetal;
  if (n.includes('titanium')) return palette.titanium;
  if (n.includes('distant_tower')) return palette.distantTower;
  if (n.includes('floating_memory_slab') || n.includes('slab')) return palette.floatingSlab;
  if (n.includes('human')) return palette.humanSilhouette;
  if (n.includes('voxel_deep')) return palette.voxelDeep;
  if (n.includes('voxel')) return palette.voxel;
  if (n.includes('sheath')) return palette.verticalSheath;
  if (n.includes('conduit_core')) return palette.verticalCore;
  if (n.includes('obsidian')) return palette.obsidianStructure;
  return palette.obsidianStructure;
}

/**
 * Traverses an imported hierarchy and replaces raw GLTF materials with calibrated
 * Stage 03 physical materials.
 */
export function applyStage03Materials(
  root: THREE.Object3D,
  palette: Stage03MaterialPalette
): void {
  root.traverse((node) => {
    if ((node as THREE.Mesh).isMesh) {
      const mesh = node as THREE.Mesh;
      if (Array.isArray(mesh.material)) {
        mesh.material = mesh.material.map((m) =>
          matchStage03Material(m.name || '', palette)
        );
      } else if (mesh.material) {
        mesh.material = matchStage03Material(mesh.material.name || '', palette);
      }
    }
  });
}

/**
 * Merges submeshes within a group by material into single geometry buffers.
 * Preserves exact triangle topology, vertex attributes, and materials while
 * reducing draw calls to 1 per unique material.
 */
export function mergeGroupGeometriesByMaterial(group: THREE.Group): THREE.Group {
  group.updateMatrixWorld(true);
  const byMaterial = new Map<THREE.Material, THREE.BufferGeometry[]>();

  group.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      const mesh = obj as THREE.Mesh;
      const geom = mesh.geometry.clone();
      mesh.updateMatrix();
      geom.applyMatrix4(mesh.matrix);

      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach((m) => {
        if (!byMaterial.has(m)) {
          byMaterial.set(m, []);
        }
        byMaterial.get(m)!.push(geom);
      });
    }
  });

  const mergedGroup = new THREE.Group();
  mergedGroup.name = `${group.name}_Merged`;

  byMaterial.forEach((geoms, mat) => {
    if (geoms.length === 1) {
      const mesh = new THREE.Mesh(geoms[0], mat);
      mesh.name = `${mat.name || 'Submesh'}`;
      mergedGroup.add(mesh);
    } else if (geoms.length > 1) {
      const mergedGeom = BufferGeometryUtils.mergeGeometries(geoms, false);
      if (mergedGeom) {
        const mesh = new THREE.Mesh(mergedGeom, mat);
        mesh.name = `${mat.name || 'Merged'}_Submesh`;
        mergedGroup.add(mesh);
      }
    }
  });

  return mergedGroup;
}

export interface Stage03LightingOptions {
  fogColor?: THREE.ColorRepresentation;
  fogDensity?: number;
  fogType?: 'linear' | 'exp2';
  fogNear?: number;
  fogFar?: number;
  sunIntensity?: number;
  sunColor?: THREE.ColorRepresentation;
  rotundaKeyIntensity?: number;
  rotundaKeyColor?: THREE.ColorRepresentation;
  ambientIntensity?: number;
  ambientColor?: THREE.ColorRepresentation;
  hemisphereIntensity?: number;
  hemisphereSkyColor?: THREE.ColorRepresentation;
  hemisphereGroundColor?: THREE.ColorRepresentation;
  coreIntensity?: number;
  coreColor?: THREE.ColorRepresentation;
  daisBounceIntensity?: number;
  daisBounceRange?: number;
  daisBounceColor?: THREE.ColorRepresentation;
  tertiaryStairsIntensity?: number;
  tertiaryStairsColor?: THREE.ColorRepresentation;
  canopyIntensity?: number;
  canopyColor?: THREE.ColorRepresentation;
  pedestalIntensity?: number;
  rimBackIntensity?: number;
  rimBackColor?: THREE.ColorRepresentation;
  tertiaryStairsRange?: number;
  tertiaryStairsPosition?: [number, number, number];
  pathLightIntensity?: number;
  pathLightColor?: THREE.ColorRepresentation;
  useSkyBackground?: boolean;
  envOptions?: EnvironmentTextureOptions;
}

/**
 * Configures the calibrated lighting hierarchy in Three.js matching Blender production look.
 */
export function setupStage03Lighting(scene: THREE.Scene, options: Stage03LightingOptions = {}): void {
  // 1. Procedural Environmental Radiance Map
  const envTexture = createStage03EnvironmentTexture(options.envOptions);
  scene.environment = envTexture;

  // 2. Stormy Sky Dome Background matching Blender MAT_Stormy_Sky_Dome
  if (options.useSkyBackground !== false) {
    scene.background = envTexture;
  } else {
    scene.background = new THREE.Color(options.fogColor !== undefined ? options.fogColor : 0x243040);
  }

  // 3. Atmospheric Linear Fog matching Blender Principled Volume & reference steel-blue haze
  const fogColor = options.fogColor !== undefined ? options.fogColor : 0x52657a;
  if (options.fogType === 'exp2') {
    const fogDensity = options.fogDensity !== undefined ? options.fogDensity : 0.0040;
    scene.fog = new THREE.FogExp2(fogColor, fogDensity);
  } else {
    const near = options.fogNear !== undefined ? options.fogNear : 19.0;
    const far = options.fogFar !== undefined ? options.fogFar : 182.0;
    scene.fog = new THREE.Fog(fogColor, near, far);
  }

  // 4. Cool Directional Sunlight (matching Blender Light_Atmospheric_Sun)
  const sunLight = new THREE.DirectionalLight(
    options.sunColor !== undefined ? options.sunColor : 0x647b94,
    options.sunIntensity !== undefined ? options.sunIntensity : 0.68
  );
  sunLight.name = 'Light_Atmospheric_Sun';
  sunLight.position.set(-17.4, 27.7, 37.8);
  sunLight.target.position.set(0, 5, 0);
  scene.add(sunLight);
  scene.add(sunLight.target);

  // 5. Warm Central Memory Reactor (Astrolabe Core: Light_Astrolabe_Core 380W)
  const coreLight = new THREE.PointLight(
    options.coreColor !== undefined ? options.coreColor : 0xffa232,
    options.coreIntensity !== undefined ? options.coreIntensity : 12.0,
    75,
    1.8
  );
  coreLight.name = 'Light_Astrolabe_Core';
  coreLight.position.set(0, 9.0, 0);
  scene.add(coreLight);

  // 6. Canopy Downlight (Light_Canopy_Downlight 380W)
  const canopyDownlight = new THREE.SpotLight(
    options.canopyColor !== undefined ? options.canopyColor : 0xffa338,
    options.canopyIntensity !== undefined ? options.canopyIntensity : 4.4,
    55,
    0.65,
    0.8,
    2
  );
  canopyDownlight.name = 'Light_Canopy_Downlight';
  canopyDownlight.position.set(0, 23.0, 0);
  canopyDownlight.target.position.set(0, 0, 0);
  scene.add(canopyDownlight);
  scene.add(canopyDownlight.target);

  // 7. Astrolabe Rim Back Light (Light_Astrolabe_Rim_Back 480W, pos: [0, 15, -9.5])
  const rimBackLight = new THREE.PointLight(
    options.rimBackColor !== undefined ? options.rimBackColor : 0xffb040,
    options.rimBackIntensity !== undefined ? options.rimBackIntensity : 3.2,
    50,
    2
  );
  rimBackLight.name = 'Light_Astrolabe_Rim_Back';
  rimBackLight.position.set(0, 15.0, -9.5);
  scene.add(rimBackLight);

  // 8. Astrolabe Pedestal Up Light (Light_Astrolabe_Pedestal_Up 160W, pos: [0, 4.3, 0])
  const pedestalUpLight = new THREE.PointLight(
    0xff8420,
    options.pedestalIntensity !== undefined ? options.pedestalIntensity : 4.4,
    30,
    1.8
  );
  pedestalUpLight.name = 'Light_Astrolabe_Pedestal_Up';
  pedestalUpLight.position.set(0, 4.3, 0);
  scene.add(pedestalUpLight);

  // 8b. Dais Secondary Warm GI Bounce (emulates 4-bounce Fast GI from 380W core onto rotunda deck)
  const daisBounceLight = new THREE.PointLight(
    options.daisBounceColor !== undefined ? options.daisBounceColor : 0xff9824,
    options.daisBounceIntensity !== undefined ? options.daisBounceIntensity : 7.8,
    options.daisBounceRange !== undefined ? options.daisBounceRange : 36.5,
    1.6
  );
  daisBounceLight.name = 'Light_Dais_GI_Bounce';
  daisBounceLight.position.set(0, 3.8, 0);
  scene.add(daisBounceLight);

  // 9. Rotunda Front Key Light (Softened to eliminate harsh column highlights)
  const rotundaKey = new THREE.PointLight(
    options.rotundaKeyColor !== undefined ? options.rotundaKeyColor : 0x566c86,
    options.rotundaKeyIntensity !== undefined ? options.rotundaKeyIntensity : 1.6,
    85,
    1.8
  );
  rotundaKey.name = 'Light_Rotunda_Front_Key';
  rotundaKey.position.set(0, 10.0, 22.0);
  scene.add(rotundaKey);

  // 10. Pathway Accent Lights (PathLight_Left/Center/Right 80W each - restrained practical accents)
  const pathLeft = new THREE.PointLight(0xff8a24, options.pathLightIntensity !== undefined ? options.pathLightIntensity : 0.18, 16, 2);
  pathLeft.name = 'PathLight_Left';
  pathLeft.position.set(-14.0, 3.8, 34.0);
  scene.add(pathLeft);

  const pathCenter = new THREE.PointLight(0xff8a24, options.pathLightIntensity !== undefined ? options.pathLightIntensity : 0.18, 16, 2);
  pathCenter.name = 'PathLight_Center';
  pathCenter.position.set(0.0, 3.8, 28.0);
  scene.add(pathCenter);

  const pathRight = new THREE.PointLight(0xff8a24, options.pathLightIntensity !== undefined ? options.pathLightIntensity : 0.18, 16, 2);
  pathRight.name = 'PathLight_Right';
  pathRight.position.set(14.0, 3.8, 34.0);
  scene.add(pathRight);

  // 11. Restrained Ambient Fill (preserves dark obsidian floor: DARK != PURE BLACK)
  const ambientLight = new THREE.AmbientLight(
    options.ambientColor !== undefined ? options.ambientColor : 0x22262e,
    options.ambientIntensity !== undefined ? options.ambientIntensity : 0.44
  );
  ambientLight.name = 'AmbientLight_Fill';
  scene.add(ambientLight);

  // 12. LAYER 1: Broad Hemisphere Environmental Fill (cool steel-blue sky, dark graphite ground bounce)
  const hemiIntensity = options.hemisphereIntensity !== undefined ? options.hemisphereIntensity : 0.32;
  if (hemiIntensity > 0) {
    const hemiLight = new THREE.HemisphereLight(
      options.hemisphereSkyColor !== undefined ? options.hemisphereSkyColor : 0x56687c,
      options.hemisphereGroundColor !== undefined ? options.hemisphereGroundColor : 0x202226,
      hemiIntensity
    );
    hemiLight.name = 'Light_Hemisphere_Environmental';
    scene.add(hemiLight);
  }

  // 13. LAYER 2: Tertiary Reactor Warm Field / Inner Stairs Grazing Light
  const stairsIntensity = options.tertiaryStairsIntensity !== undefined ? options.tertiaryStairsIntensity : 3.0;
  if (stairsIntensity > 0) {
    const tertiaryStairs = new THREE.PointLight(
      options.tertiaryStairsColor !== undefined ? options.tertiaryStairsColor : 0xff9226,
      stairsIntensity,
      options.tertiaryStairsRange !== undefined ? options.tertiaryStairsRange : 28.0,
      1.8
    );
    tertiaryStairs.name = 'Light_Reactor_Tertiary_Stairs';
    const pos = options.tertiaryStairsPosition || [0, 5.0, 15.0];
    tertiaryStairs.position.set(pos[0], pos[1], pos[2]);
    scene.add(tertiaryStairs);
  }
}

export interface AstrolabeKineticRefs {
  gimbalOuter: THREE.Object3D | null;
  gimbalMid: THREE.Object3D | null;
  gimbalInner: THREE.Object3D | null;
  corePulse: THREE.Object3D | null;
  shards: THREE.Object3D[];
  floatingSlabs: THREE.Object3D | null;
}

/**
 * Real-time Astrolabe kinetics and floating slab oscillations.
 */
export function animateStage03(
  refs: AstrolabeKineticRefs,
  time: number,
  delta: number
): void {
  // Outer Gimbal: steady forward axial rotation around X
  if (refs.gimbalOuter) {
    refs.gimbalOuter.rotation.x = time * 0.25;
  }
  // Mid Gimbal: counter-rotation around Y
  if (refs.gimbalMid) {
    refs.gimbalMid.rotation.y = -time * 0.35;
  }
  // Inner Gimbal: precession around Z
  if (refs.gimbalInner) {
    refs.gimbalInner.rotation.z = time * 0.45;
  }
  // Core: breathing pulse
  if (refs.corePulse) {
    const s = 1.0 + Math.sin(time * 2.0) * 0.04;
    refs.corePulse.scale.set(s, s, s);
  }
  // Shards: subtle wave oscillation
  refs.shards.forEach((shard, idx) => {
    shard.position.y += Math.sin(time * 1.5 + idx * 0.45) * 0.0008;
  });
  // Floating slabs: gentle collective floating wave
  if (refs.floatingSlabs) {
    refs.floatingSlabs.position.y = Math.sin(time * 0.6) * 0.06;
  }
}
