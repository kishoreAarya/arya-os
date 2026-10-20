import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import {
  createStage03MaterialPalette,
  createStage03NeutralPalette,
  createStage03EnvironmentTexture,
  matchStage03Material,
  applyStage03Materials,
  setupStage03Lighting,
  STAGE03_CAMERAS,
  animateStage03,
  AstrolabeKineticRefs,
  mergeGroupGeometriesByMaterial,
} from './stage03_assembly';
import {
  Stage03PlanarReflector,
  Stage03PostProcessingManager,
  Stage03SSRManager,
} from './stage03_reflections';

declare global {
  interface Window {
    isSceneReady: () => boolean;
    setCameraView: (camName: string, pauseForBenchmark?: boolean) => void;
    getPerformanceMetrics: () => any;
    renderFrame: () => void;
    setDiagnosticConfig: (config: any) => void;
    __STAGE03_READY__: boolean;
    __STAGE03_METRICS__: any;
  }
}

window.__STAGE03_READY__ = false;
window.__STAGE03_METRICS__ = null;

function createInstancedPackage(
  templateGroup: THREE.Group,
  transforms: Array<{ position: [number, number, number]; rotation: [number, number, number] }>
): THREE.Group {
  const resultGroup = new THREE.Group();
  const count = transforms.length;
  if (count === 0) return resultGroup;

  templateGroup.updateMatrixWorld(true);

  templateGroup.traverse((node) => {
    if ((node as THREE.Mesh).isMesh) {
      const mesh = node as THREE.Mesh;
      const instMesh = new THREE.InstancedMesh(mesh.geometry, mesh.material, count);
      instMesh.name = `Instanced_${mesh.name}`;

      const dummy = new THREE.Object3D();
      const localMatrix = mesh.matrix.clone();

      transforms.forEach((t, idx) => {
        dummy.position.set(...t.position);
        dummy.rotation.set(...t.rotation);
        dummy.updateMatrix();

        const instMat = dummy.matrix.clone().multiply(localMatrix);
        instMesh.setMatrixAt(idx, instMat);
      });

      instMesh.instanceMatrix.needsUpdate = true;
      resultGroup.add(instMesh);
    }
  });

  return resultGroup;
}

async function initValidationScene() {
  const canvas = document.getElementById('webgl-canvas') as HTMLCanvasElement;
  if (!canvas) throw new Error('Canvas #webgl-canvas not found');

  const width = 1920;
  const height = 1080;

  // 1. Renderer Setup with ACESFilmic Tone Mapping matching Blender
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    powerPreference: 'high-performance',
    alpha: false,
    preserveDrawingBuffer: true,
  });

  renderer.setSize(width, height);
  renderer.setPixelRatio(1);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.965;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();

  // 2. Setup Production Lighting
  setupStage03Lighting(scene);

  // 3. Perspective Camera
  const defaultCam = STAGE03_CAMERAS.CAM_CinematicHero;
  const camera = new THREE.PerspectiveCamera(defaultCam.fov, width / height, 0.1, 500);
  camera.position.set(...defaultCam.position);
  camera.lookAt(...defaultCam.target);
  scene.add(camera);

  // 3b. Setup Planar Reflector, Post-Processing and SSR Managers
  const planarReflector = new Stage03PlanarReflector({
    planeY: 0.0,
    textureWidth: 960,
    textureHeight: 540,
    intensity: 0.35,
    tintColor: 0x141618,
  });
  planarReflector.enabled = true;

  const postProcessor = new Stage03PostProcessingManager(renderer, scene, camera, width, height);
  const ssrManager = new Stage03SSRManager(renderer, scene, camera, width, height);

  let activeRenderMode: 'standard' | 'bloom' | 'ssr' = 'bloom';
  let isPlanarEnabled = true;

  const performRender = () => {
    if (isPlanarEnabled) {
      planarReflector.update(renderer, scene, camera);
    }
    if (activeRenderMode === 'bloom') {
      postProcessor.render();
    } else if (activeRenderMode === 'ssr') {
      ssrManager.render();
    } else {
      renderer.render(scene, camera);
    }
  };

  // 4. Material Palette
  const palette = createStage03MaterialPalette();

  // 5. Load Registry JSON
  const instancesRes = await fetch('/assets/stage03_memory/stage03_memory_instances.json');
  if (!instancesRes.ok) throw new Error(`HTTP ${instancesRes.status} loading instances json`);
  const instancesData = await instancesRes.json();

  const loader = new GLTFLoader();
  const loadGlb = (path: string): Promise<THREE.Group> => {
    return new Promise((resolve, reject) => {
      loader.load(
        path,
        (gltf) => resolve(gltf.scene),
        undefined,
        (err) => reject(err)
      );
    });
  };

  const assetBase = '/assets/stage03_memory';

  // 6. Load Static & Kinetic World
  console.log('Loading 14 modular GLB packages...');
  const [
    coreScene,
    daisScene,
    columnsScene,
    conduitsScene,
    orbitalScene,
    towersScene,
    housingScene,
    mountainScene,
    neuralScene,
    cityScene,
    matrixScene,
    chronoScene,
    slabsScene,
    figureScene,
  ] = await Promise.all([
    loadGlb(`${assetBase}/01_astrolabe_hero_core.glb`),
    loadGlb(`${assetBase}/02_architecture_dais_stairs.glb`),
    loadGlb(`${assetBase}/03_architecture_columns_canopy.glb`),
    loadGlb(`${assetBase}/04_conduits_viaduct.glb`),
    loadGlb(`${assetBase}/05_orbital_viaducts.glb`),
    loadGlb(`${assetBase}/06_distant_towers.glb`),
    loadGlb(`${assetBase}/07_memory_vitrine_housing.glb`),
    loadGlb(`${assetBase}/08_memory_world_mountain.glb`),
    loadGlb(`${assetBase}/09_memory_world_neural.glb`),
    loadGlb(`${assetBase}/10_memory_world_city.glb`),
    loadGlb(`${assetBase}/11_memory_world_matrix.glb`),
    loadGlb(`${assetBase}/12_memory_world_chrono.glb`),
    loadGlb(`${assetBase}/13_floating_slabs.glb`),
    loadGlb(`${assetBase}/14_scale_anchor_figure.glb`),
  ]);

  // Apply materials to all templates
  [
    coreScene,
    daisScene,
    columnsScene,
    conduitsScene,
    orbitalScene,
    towersScene,
    housingScene,
    mountainScene,
    neuralScene,
    cityScene,
    matrixScene,
    chronoScene,
    slabsScene,
    figureScene,
  ].forEach((sc) => applyStage03Materials(sc, palette));

  // Batch static architecture packages (02, 03, 04, 05, 06) by material
  const staticGroup = new THREE.Group();
  staticGroup.name = 'StaticArchitectureGroup';
  staticGroup.add(daisScene, columnsScene, conduitsScene, orbitalScene, towersScene);
  const mergedStatic = mergeGroupGeometriesByMaterial(staticGroup);

  // Add Static Packages to scene
  scene.add(coreScene);
  scene.add(mergedStatic);
  scene.add(slabsScene);

  // Attach floor mesh to planar reflector
  mergedStatic.traverse((node) => {
    if ((node as THREE.Mesh).isMesh && node.name.includes('Floor_Wet')) {
      planarReflector.setFloorMesh(node as THREE.Mesh);
    }
  });

  // Setup Astrolabe kinetic references
  const kineticRefs: AstrolabeKineticRefs = {
    gimbalOuter: null,
    gimbalMid: null,
    gimbalInner: null,
    corePulse: null,
    shards: [],
    floatingSlabs: slabsScene,
  };

  coreScene.traverse((node) => {
    const name = node.name;
    if (name.includes('Gimbal_Ring_Outer') && !name.includes('Glow')) {
      kineticRefs.gimbalOuter = node;
    } else if (name.includes('Gimbal_Ring_Mid')) {
      kineticRefs.gimbalMid = node;
    } else if (name.includes('Gimbal_Ring_Inner')) {
      kineticRefs.gimbalInner = node;
    } else if (name.includes('Central_Reactor_Core')) {
      kineticRefs.corePulse = node;
    } else if (name.includes('Astrolabe_Shard_')) {
      kineticRefs.shards.push(node);
    }
  });

  // Reassemble 24 Vitrines Housing via GPU Instancing (batch merged by material)
  const vitrineTransforms = instancesData.vitrines.map((v: any) => ({
    position: v.threejs_transform.position as [number, number, number],
    rotation: v.threejs_transform.rotation_euler_xyz as [number, number, number],
  }));
  const mergedHousing = mergeGroupGeometriesByMaterial(housingScene);
  const instancedHousing = createInstancedPackage(mergedHousing, vitrineTransforms);
  scene.add(instancedHousing);

  // Reassemble 5 Archetypes via GPU Instancing (batch merged by material)
  const archetypeConfigs: Array<{ key: string; scene: THREE.Group }> = [
    { key: 'mountain', scene: mountainScene },
    { key: 'neural', scene: neuralScene },
    { key: 'city', scene: cityScene },
    { key: 'matrix', scene: matrixScene },
    { key: 'chrono', scene: chronoScene },
  ];

  archetypeConfigs.forEach(({ key, scene: archTemplate }) => {
    const matchingTransforms = instancesData.vitrines
      .filter((v: any) => v.archetype === key)
      .map((v: any) => ({
        position: v.threejs_transform.position as [number, number, number],
        rotation: v.threejs_transform.rotation_euler_xyz as [number, number, number],
      }));
    const mergedArch = mergeGroupGeometriesByMaterial(archTemplate);
    const instGroup = createInstancedPackage(mergedArch, matchingTransforms);
    scene.add(instGroup);
  });

  // Reassemble 3 Scale Anchors via GPU Instancing
  const anchorTransforms = instancesData.scale_anchors.map((a: any) => ({
    position: a.threejs_transform.position as [number, number, number],
    rotation: a.threejs_transform.rotation_euler_xyz as [number, number, number],
  }));
  const instancedAnchors = createInstancedPackage(figureScene, anchorTransforms);
  scene.add(instancedAnchors);

  console.log('Stage 03 scene reassembled via GPU InstancedMesh successfully!');

  // Benchmark Camera Setter
  let isPausedForCapture = false;

  const setCameraView = (camName: string, pauseForBenchmark: boolean = false) => {
    const cfg = STAGE03_CAMERAS[camName];
    if (!cfg) throw new Error(`Unknown camera view: ${camName}`);
    camera.fov = cfg.fov;
    camera.aspect = width / height;
    camera.position.set(...cfg.position);
    camera.lookAt(...cfg.target);
    camera.updateProjectionMatrix();

    if (pauseForBenchmark) {
      isPausedForCapture = true;
      animateStage03(kineticRefs, 0, 0); // Reset kinetics to exact Blender resting pose t=0
    }

    // Render multiple passes to settle any texture bindings & shaders
    for (let i = 0; i < 5; i++) {
      performRender();
    }
  };

  // Performance Profiling
  let frameTimes: number[] = [];
  const renderFrameWithProfiling = () => {
    const start = performance.now();
    performRender();
    const end = performance.now();
    const duration = end - start;
    frameTimes.push(duration);
    if (frameTimes.length > 30) frameTimes.shift();
  };

  const getPerformanceMetrics = () => {
    const info = renderer.info;
    const avgFrameTime =
      frameTimes.length > 0
        ? frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length
        : 16.6;
    const fps = avgFrameTime > 0 ? 1000 / avgFrameTime : 60;

    let approxGeomBytes = 0;
    scene.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
        const mesh = obj as THREE.Mesh;
        const geom = mesh.geometry;
        if (geom) {
          for (const attrName in geom.attributes) {
            const attr = geom.attributes[attrName];
            approxGeomBytes += attr.array.byteLength;
          }
          if (geom.index) {
            approxGeomBytes += geom.index.array.byteLength;
          }
        }
      }
    });

    const gpuMemoryMb = (approxGeomBytes / (1024 * 1024)).toFixed(2);
    const isBloomMode = activeRenderMode === 'bloom';
    const drawCalls = isBloomMode && postProcessor.lastSceneCalls ? postProcessor.lastSceneCalls : info.render.calls;
    const triangles = isBloomMode && postProcessor.lastSceneTriangles ? postProcessor.lastSceneTriangles : info.render.triangles;

    return {
      drawCalls,
      triangles,
      points: info.render.points,
      lines: info.render.lines,
      geometries: info.memory.geometries,
      textures: info.memory.textures,
      gpuMemoryMb: parseFloat(gpuMemoryMb),
      frameTimeMs: parseFloat(avgFrameTime.toFixed(2)),
      fps: parseFloat(fps.toFixed(1)),
    };
  };

  // Initial render settle
  setCameraView('CAM_CinematicHero', false);

  // Animation Loop
  const clock = new THREE.Clock();

  const animateLoop = () => {
    requestAnimationFrame(animateLoop);
    if (!isPausedForCapture) {
      const time = clock.getElapsedTime();
      const delta = clock.getDelta();
      animateStage03(kineticRefs, time, delta);
    }
    renderFrameWithProfiling();
  };
  animateLoop();

  // Expose hooks to window for headless Playwright execution
  window.setCameraView = setCameraView;
  window.getPerformanceMetrics = getPerformanceMetrics;
  window.renderFrame = () => performRender();
  (window as any).resumeAnimation = () => {
    isPausedForCapture = false;
  };
  window.setDiagnosticConfig = (config: any) => {
    // 0. High-level Phase 2.4 A/B Variants Preset
    if (config.variant) {
      if (config.variant === 'A') {
        // Variant A: Current Phase 2.3 baseline
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 0.8122;
        activeRenderMode = 'standard';
        isPlanarEnabled = true;
        planarReflector.enabled = true;
        planarReflector.intensity = 0.45;
        scene.fog = new THREE.FogExp2(0x19212c, 0.0020);
        scene.background = new THREE.Color(0x19212c);
        const sun = scene.getObjectByName('Light_Atmospheric_Sun') as THREE.DirectionalLight;
        if (sun) { sun.intensity = 0.95; sun.color.set(0x567298); }
        const rKey = scene.getObjectByName('Light_Rotunda_Front_Key') as THREE.PointLight;
        if (rKey) { rKey.intensity = 4.8; rKey.color.set(0x5878a0); }
        const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
        if (amb) { amb.intensity = 0.14; amb.color.set(0x080d14); }
        const core = scene.getObjectByName('Light_Astrolabe_Core') as THREE.PointLight;
        if (core) { core.intensity = 7.5; }
        const db = scene.getObjectByName('Light_Dais_GI_Bounce') as THREE.PointLight;
        if (db) { db.intensity = 2.0; }
        const envA = createStage03EnvironmentTexture({ zenithColor: '#0c1624', horizonColor: '#1c2635', groundColor: '#040609', cloudBands: false });
        scene.environment = envA;
        const palA = createStage03MaterialPalette({
          obsidianRoughness: 0.35, obsidianMetalness: 0.82,
          titaniumRoughness: 0.16,
          floorRoughness: 0.16, floorClearcoat: 0.95, floorClearcoatRoughness: 0.028,
          glassColor: 0xf5f8ff, glassOpacity: 0.16,
        });
        scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
            const mesh = obj as THREE.Mesh;
            if (mesh.material) {
              const mName = Array.isArray(mesh.material) ? mesh.material[0]?.name : mesh.material.name;
              mesh.material = matchStage03Material(mName || '', palA);
            }
          }
        });
      } else if (config.variant === 'B') {
        // Variant B: Atmosphere Correction
        scene.fog = new THREE.FogExp2(0x283444, 0.0042);
        const envB = createStage03EnvironmentTexture({ zenithColor: '#101824', horizonColor: '#38485c', groundColor: '#080d14', cloudBands: true });
        scene.environment = envB;
        scene.background = envB;
        const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
        if (amb) { amb.intensity = 0.28; amb.color.set(0x16202c); }
      } else if (config.variant === 'C') {
        // Variant C: Atmosphere + Material / Highlight Correction
        scene.fog = new THREE.FogExp2(0x283444, 0.0042);
        const envC = createStage03EnvironmentTexture({ zenithColor: '#101824', horizonColor: '#38485c', groundColor: '#080d14', cloudBands: true });
        scene.environment = envC;
        scene.background = envC;
        const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
        if (amb) { amb.intensity = 0.30; amb.color.set(0x16202c); }
        const rKey = scene.getObjectByName('Light_Rotunda_Front_Key') as THREE.PointLight;
        if (rKey) { rKey.intensity = 1.8; rKey.color.set(0x526e8e); }
        const sun = scene.getObjectByName('Light_Atmospheric_Sun') as THREE.DirectionalLight;
        if (sun) { sun.intensity = 0.72; sun.color.set(0x607d9e); }
        planarReflector.intensity = 0.40;
        const palC = createStage03MaterialPalette({
          obsidianRoughness: 0.48, obsidianMetalness: 0.74,
          titaniumRoughness: 0.26,
          gunmetalRoughness: 0.35,
          floorRoughness: 0.22, floorClearcoat: 0.65, floorClearcoatRoughness: 0.10,
          glassColor: 0x16202c, glassOpacity: 0.22,
        });
        scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
            const mesh = obj as THREE.Mesh;
            if (mesh.material) {
              const mName = Array.isArray(mesh.material) ? mesh.material[0]?.name : mesh.material.name;
              mesh.material = matchStage03Material(mName || '', palC);
            }
          }
        });
      } else if (config.variant === 'D') {
        // Variant D: Atmosphere + Material + Reactor Integration
        scene.fog = new THREE.FogExp2(0x283444, 0.0042);
        const envD = createStage03EnvironmentTexture({ zenithColor: '#101824', horizonColor: '#38485c', groundColor: '#080d14', cloudBands: true, warmGlowRadius: 120, warmGlowIntensity: 0.38 });
        scene.environment = envD;
        scene.background = envD;
        const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
        if (amb) { amb.intensity = 0.30; amb.color.set(0x16202c); }
        const rKey = scene.getObjectByName('Light_Rotunda_Front_Key') as THREE.PointLight;
        if (rKey) { rKey.intensity = 1.8; rKey.color.set(0x526e8e); }
        const sun = scene.getObjectByName('Light_Atmospheric_Sun') as THREE.DirectionalLight;
        if (sun) { sun.intensity = 0.72; sun.color.set(0x607d9e); }
        const core = scene.getObjectByName('Light_Astrolabe_Core') as THREE.PointLight;
        if (core) { core.intensity = 6.5; }
        const db = scene.getObjectByName('Light_Dais_GI_Bounce') as THREE.PointLight;
        if (db) { db.intensity = 3.6; }
        const ped = scene.getObjectByName('Light_Astrolabe_Pedestal_Up') as THREE.PointLight;
        if (ped) { ped.intensity = 2.8; }
        planarReflector.intensity = 0.40;
        const palD = createStage03MaterialPalette({
          obsidianRoughness: 0.48, obsidianMetalness: 0.74,
          titaniumRoughness: 0.26,
          gunmetalRoughness: 0.35,
          floorRoughness: 0.22, floorClearcoat: 0.65, floorClearcoatRoughness: 0.10,
          glassColor: 0x16202c, glassOpacity: 0.22,
        });
        scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
            const mesh = obj as THREE.Mesh;
            if (mesh.material) {
              const mName = Array.isArray(mesh.material) ? mesh.material[0]?.name : mesh.material.name;
              mesh.material = matchStage03Material(mName || '', palD);
            }
          }
        });
      } else if (config.variant === 'E') {
        // Variant E: Full Cinematic Treatment
        scene.fog = new THREE.FogExp2(0x283444, 0.0042);
        const envE = createStage03EnvironmentTexture({ zenithColor: '#101824', horizonColor: '#38485c', groundColor: '#080d14', cloudBands: true, warmGlowRadius: 110, warmGlowIntensity: 0.35 });
        scene.environment = envE;
        scene.background = envE;
        const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
        if (amb) { amb.intensity = 0.30; amb.color.set(0x16202c); }
        const rKey = scene.getObjectByName('Light_Rotunda_Front_Key') as THREE.PointLight;
        if (rKey) { rKey.intensity = 1.8; rKey.color.set(0x526e8e); }
        const sun = scene.getObjectByName('Light_Atmospheric_Sun') as THREE.DirectionalLight;
        if (sun) { sun.intensity = 0.72; sun.color.set(0x607d9e); }
        const core = scene.getObjectByName('Light_Astrolabe_Core') as THREE.PointLight;
        if (core) { core.intensity = 6.5; }
        const db = scene.getObjectByName('Light_Dais_GI_Bounce') as THREE.PointLight;
        if (db) { db.intensity = 3.5; }
        const ped = scene.getObjectByName('Light_Astrolabe_Pedestal_Up') as THREE.PointLight;
        if (ped) { ped.intensity = 2.8; }
        planarReflector.intensity = 0.38;
        activeRenderMode = config.renderMode || 'standard';
        postProcessor.setBloomConfig({ threshold: 0.88, strength: 0.040, radius: 0.50 });
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 0.8122;
        const palE = createStage03MaterialPalette();
        scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
            const mesh = obj as THREE.Mesh;
            if (mesh.material) {
              const mName = Array.isArray(mesh.material) ? mesh.material[0]?.name : mesh.material.name;
              mesh.material = matchStage03Material(mName || '', palE);
            }
          }
        });
      }
    }

    // 1. Tone Mapping Subsystem
    if (config.toneMapping) {
      if (config.toneMapping === 'AgX') renderer.toneMapping = THREE.AgXToneMapping;
      else if (config.toneMapping === 'ACESFilmic') renderer.toneMapping = THREE.ACESFilmicToneMapping;
      else if (config.toneMapping === 'Neutral') renderer.toneMapping = THREE.NeutralToneMapping;
      else if (config.toneMapping === 'Linear') renderer.toneMapping = THREE.NoToneMapping;
    }
    if (typeof config.exposure === 'number') {
      renderer.toneMappingExposure = config.exposure;
    }

    // 1b. Fog Subsystem
    if (config.fogDensity !== undefined || config.fogColor !== undefined || config.fogType !== undefined) {
      const curColor = (scene.fog as any)?.color?.getHex() ?? 0x283444;
      const fColor = config.fogColor !== undefined ? config.fogColor : curColor;
      if (config.fogType === 'linear') {
        const near = config.fogNear !== undefined ? config.fogNear : 20;
        const far = config.fogFar !== undefined ? config.fogFar : 190;
        scene.fog = new THREE.Fog(fColor, near, far);
      } else {
        const fDens = config.fogDensity !== undefined ? config.fogDensity : ((scene.fog as THREE.FogExp2)?.density ?? 0.0042);
        scene.fog = new THREE.FogExp2(fColor, fDens);
      }
    }

    // 1c. Rotunda Key Light
    if (config.rotundaKeyIntensity !== undefined || config.rotundaKeyColor !== undefined) {
      const rk = scene.getObjectByName('Light_Rotunda_Front_Key') as THREE.PointLight;
      if (rk) {
        if (config.rotundaKeyIntensity !== undefined) rk.intensity = config.rotundaKeyIntensity;
        if (config.rotundaKeyColor !== undefined) rk.color.set(config.rotundaKeyColor);
      }
    }

    // 2. Shadow Subsystem
    if (config.shadows !== undefined) {
      renderer.shadowMap.enabled = Boolean(config.shadows);
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
          (obj as THREE.Mesh).castShadow = Boolean(config.shadows);
          (obj as THREE.Mesh).receiveShadow = Boolean(config.shadows);
        }
      });
    }

    // 3. Indirect Illumination / Ambient Fill
    if (typeof config.ambientIntensity === 'number' || config.ambientColor !== undefined) {
      const amb = scene.getObjectByName('AmbientLight_Fill') as THREE.AmbientLight;
      if (amb) {
        if (typeof config.ambientIntensity === 'number') amb.intensity = config.ambientIntensity;
        if (config.ambientColor !== undefined) amb.color.set(config.ambientColor);
      }
    }

    // 4. Directional Sun Light
    if (typeof config.sunIntensity === 'number' || config.sunColor !== undefined) {
      const sun = scene.getObjectByName('Light_Atmospheric_Sun') as THREE.DirectionalLight;
      if (sun) {
        if (typeof config.sunIntensity === 'number') sun.intensity = config.sunIntensity;
        if (config.sunColor !== undefined) sun.color.set(config.sunColor);
      }
    }

    // 4b. Astrolabe Core Light
    if (typeof config.coreIntensity === 'number' || config.coreColor !== undefined) {
      const core = scene.getObjectByName('Light_Astrolabe_Core') as THREE.PointLight;
      if (core) {
        if (typeof config.coreIntensity === 'number') core.intensity = config.coreIntensity;
        if (config.coreColor !== undefined) core.color.set(config.coreColor);
      }
    }

    // 5. Environment Radiance Texture (Atmosphere & Baked Diffuse Ground Bounce)
    if (config.envOptions) {
      const newEnv = createStage03EnvironmentTexture(config.envOptions);
      scene.environment = newEnv;
      if (config.useSkyBackground !== false) {
        scene.background = newEnv;
      }
    }

    // 6. Floor & Glass Material Subsystem
    if (
      config.floorRoughness !== undefined ||
      config.floorClearcoat !== undefined ||
      config.floorClearcoatRoughness !== undefined ||
      config.floorColor !== undefined ||
      config.glassColor !== undefined ||
      config.glassOpacity !== undefined
    ) {
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
          const mesh = obj as THREE.Mesh;
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach((m) => {
            if (m && m.name && m.name.includes('Floor_Wet')) {
              const floorMat = m as THREE.MeshPhysicalMaterial;
              if (config.floorRoughness !== undefined) floorMat.roughness = config.floorRoughness;
              if (config.floorClearcoat !== undefined) floorMat.clearcoat = config.floorClearcoat;
              if (config.floorClearcoatRoughness !== undefined) floorMat.clearcoatRoughness = config.floorClearcoatRoughness;
              if (config.floorColor !== undefined) floorMat.color.set(config.floorColor);
              floorMat.needsUpdate = true;
            }
            if (m && m.name && (m.name.includes('Glass') || m.name.includes('Crystal'))) {
              const glassMat = m as THREE.MeshPhysicalMaterial;
              if (config.glassColor !== undefined) glassMat.color.set(config.glassColor);
              if (config.glassOpacity !== undefined) glassMat.opacity = config.glassOpacity;
              glassMat.needsUpdate = true;
            }
          });
        }
      });
    }

    // 7. Full Material Palette (Neutral Clay vs Calibrated)
    if (config.neutralMaterial !== undefined || config.cinematicGlass !== undefined || config.materialOptions !== undefined) {
      const activePalette = config.neutralMaterial
        ? createStage03NeutralPalette()
        : createStage03MaterialPalette({ cinematicGlass: config.cinematicGlass ?? true, ...config.materialOptions });

      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
          const mesh = obj as THREE.Mesh;
          if (mesh.material) {
            const mName = Array.isArray(mesh.material) ? mesh.material[0]?.name : mesh.material.name;
            mesh.material = matchStage03Material(mName || '', activePalette);
          }
        }
      });
    }

    // 8. Planar Architectural Reflection Subsystem (Candidate B & C)
    if (config.planarReflection !== undefined) {
      isPlanarEnabled = Boolean(config.planarReflection);
      planarReflector.enabled = isPlanarEnabled;
    }
    if (typeof config.planarIntensity === 'number') {
      planarReflector.intensity = config.planarIntensity;
      const sh = (planarReflector.floorMesh?.material as any)?.userData?.shader;
      if (sh && sh.uniforms.uPlanarIntensity) {
        sh.uniforms.uPlanarIntensity.value = config.planarIntensity;
      }
    }
    if (config.planarTint !== undefined) {
      planarReflector.tintColor.set(config.planarTint);
      const sh = (planarReflector.floorMesh?.material as any)?.userData?.shader;
      if (sh && sh.uniforms.uPlanarTint) {
        sh.uniforms.uPlanarTint.value.set(config.planarTint);
      }
    }
    if (typeof config.planarPlaneY === 'number') {
      planarReflector.planeY = config.planarPlaneY;
    }

    // 9. Post-Processing Mode (Standard vs Bloom vs SSR)
    if (config.renderMode) {
      activeRenderMode = config.renderMode; // 'standard' | 'bloom' | 'ssr'
    }
    if (config.bloomConfig) {
      postProcessor.setBloomConfig(config.bloomConfig);
    }
    if (config.cinematicConfig) {
      postProcessor.setCinematicConfig(config.cinematicConfig);
    }

    // 10. Secondary Reactor Radiance / Dais GI Bounce
    if (typeof config.daisBounceIntensity === 'number' || config.daisBounceRange !== undefined || config.daisBounceColor !== undefined) {
      const db = scene.getObjectByName('Light_Dais_GI_Bounce') as THREE.PointLight;
      if (db) {
        if (typeof config.daisBounceIntensity === 'number') db.intensity = config.daisBounceIntensity;
        if (typeof config.daisBounceRange === 'number') db.distance = config.daisBounceRange;
        if (config.daisBounceColor !== undefined) db.color.set(config.daisBounceColor);
      }
    }

    // 11. Pedestal Up Light
    if (typeof config.pedestalIntensity === 'number' || config.pedestalColor !== undefined) {
      const ped = scene.getObjectByName('Light_Astrolabe_Pedestal_Up') as THREE.PointLight;
      if (ped) {
        if (typeof config.pedestalIntensity === 'number') ped.intensity = config.pedestalIntensity;
        if (config.pedestalColor !== undefined) ped.color.set(config.pedestalColor);
      }
    }

    // 12. Canopy Downlight
    if (typeof config.canopyIntensity === 'number' || config.canopyColor !== undefined) {
      const can = scene.getObjectByName('Light_Canopy_Downlight') as THREE.SpotLight;
      if (can) {
        if (typeof config.canopyIntensity === 'number') can.intensity = config.canopyIntensity;
        if (config.canopyColor !== undefined) can.color.set(config.canopyColor);
      }
    }

    // 13. Layer 1: Hemisphere Environmental Fill
    if (config.hemisphereIntensity !== undefined || config.hemisphereSkyColor !== undefined || config.hemisphereGroundColor !== undefined) {
      let hemi = scene.getObjectByName('Light_Hemisphere_Environmental') as THREE.HemisphereLight;
      if (!hemi && config.hemisphereIntensity > 0) {
        hemi = new THREE.HemisphereLight(
          config.hemisphereSkyColor !== undefined ? config.hemisphereSkyColor : 0x4e6278,
          config.hemisphereGroundColor !== undefined ? config.hemisphereGroundColor : 0x18202a,
          config.hemisphereIntensity
        );
        hemi.name = 'Light_Hemisphere_Environmental';
        scene.add(hemi);
      } else if (hemi) {
        if (typeof config.hemisphereIntensity === 'number') hemi.intensity = config.hemisphereIntensity;
        if (config.hemisphereSkyColor !== undefined) hemi.color.set(config.hemisphereSkyColor);
        if (config.hemisphereGroundColor !== undefined) hemi.groundColor.set(config.hemisphereGroundColor);
      }
    }

    // 14. Layer 2: Tertiary Reactor Warm Field / Inner Stairs
    if (config.tertiaryStairsIntensity !== undefined || config.tertiaryStairsColor !== undefined || config.tertiaryStairsRange !== undefined || config.tertiaryStairsPosition !== undefined) {
      let tert = scene.getObjectByName('Light_Reactor_Tertiary_Stairs') as THREE.PointLight;
      if (!tert && config.tertiaryStairsIntensity > 0) {
        tert = new THREE.PointLight(
          config.tertiaryStairsColor !== undefined ? config.tertiaryStairsColor : 0xff9028,
          config.tertiaryStairsIntensity,
          config.tertiaryStairsRange !== undefined ? config.tertiaryStairsRange : 24,
          1.8
        );
        tert.name = 'Light_Reactor_Tertiary_Stairs';
        const pos = config.tertiaryStairsPosition || [0, 5.2, 14.0];
        tert.position.set(pos[0], pos[1], pos[2]);
        scene.add(tert);
      } else if (tert) {
        if (typeof config.tertiaryStairsIntensity === 'number') tert.intensity = config.tertiaryStairsIntensity;
        if (config.tertiaryStairsColor !== undefined) tert.color.set(config.tertiaryStairsColor);
        if (typeof config.tertiaryStairsRange === 'number') tert.distance = config.tertiaryStairsRange;
        if (config.tertiaryStairsPosition) {
          tert.position.set(config.tertiaryStairsPosition[0], config.tertiaryStairsPosition[1], config.tertiaryStairsPosition[2]);
        }
      }
    }

    // 15. Astrolabe Rim Back Light
    if (config.rimBackIntensity !== undefined || config.rimBackColor !== undefined) {
      const rim = scene.getObjectByName('Light_Astrolabe_Rim_Back') as THREE.PointLight;
      if (rim) {
        if (typeof config.rimBackIntensity === 'number') rim.intensity = config.rimBackIntensity;
        if (config.rimBackColor !== undefined) rim.color.set(config.rimBackColor);
      }
    }

    // 16. Pathway Accent Lights
    if (config.pathLightIntensity !== undefined || config.pathLightColor !== undefined) {
      ['PathLight_Left', 'PathLight_Center', 'PathLight_Right'].forEach((name) => {
        const pl = scene.getObjectByName(name) as THREE.PointLight;
        if (pl) {
          if (typeof config.pathLightIntensity === 'number') pl.intensity = config.pathLightIntensity;
          if (config.pathLightColor !== undefined) pl.color.set(config.pathLightColor);
        }
      });
    }

    // 17. Amber Emissive Materials
    if (config.amberCoreEmissiveIntensity !== undefined || config.amberEnergyEmissiveIntensity !== undefined) {
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh || (obj as THREE.InstancedMesh).isInstancedMesh) {
          const mesh = obj as THREE.Mesh;
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach((m) => {
            if (m && m.name) {
              if (m.name.includes('Core_Bright') && config.amberCoreEmissiveIntensity !== undefined) {
                (m as THREE.MeshStandardMaterial).emissiveIntensity = config.amberCoreEmissiveIntensity;
                m.needsUpdate = true;
              } else if (m.name.includes('Energy_Emission') && config.amberEnergyEmissiveIntensity !== undefined) {
                (m as THREE.MeshStandardMaterial).emissiveIntensity = config.amberEnergyEmissiveIntensity;
                m.needsUpdate = true;
              }
            }
          });
        }
      });
    }

    // Settle renders
    for (let i = 0; i < 5; i++) {
      performRender();
    }
  };
  window.isSceneReady = () => true;
  window.__STAGE03_READY__ = true;
  (window as any).__STAGE03_SCENE__ = scene;
  (window as any).__STAGE03_RENDERER__ = renderer;
  console.log('__STAGE03_READY__ = true');
}

initValidationScene().catch((err) => {
  console.error('Failed to initialize Stage 03 validation scene:', err);
});
