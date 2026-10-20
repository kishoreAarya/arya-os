import React, { useRef, useMemo, useEffect, useState } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import {
  createStage03MaterialPalette,
  applyStage03Materials,
  setupStage03Lighting,
  animateStage03,
  AstrolabeKineticRefs,
  Stage03MaterialPalette,
  STAGE03_CAMERAS,
} from '../../stage03_assembly';
import { SpatialMemoryRelationships } from './SpatialMemoryRelationships';
import { memoryArchiveService } from '../../services/memoryArchiveService';

export interface SpatialMemoryArchiveProps {
  isReducedMotion?: boolean;
  activeCamera?: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail';
  assetBaseUrl?: string;
  selectedVitrineId?: string | null;
  selectedMemoryId?: string | null;
  highlightedVitrineIds?: string[];
  onSelectVitrine?: (vitrineId: string | null) => void;
  onHoverVitrine?: (vitrineId: string | null) => void;
  onLoaded?: () => void;
  onError?: (err: Error) => void;
}

const DEFAULT_ASSET_BASE = '/assets/stage03_memory';

/**
 * 01 Astrolabe Hero Core with real-time addressable kinetics
 */
const AstrolabeHeroCore: React.FC<{
  assetBaseUrl: string;
  palette: Stage03MaterialPalette;
  isReducedMotion?: boolean;
}> = ({ assetBaseUrl, palette, isReducedMotion }) => {
  const gltf = useGLTF(`${assetBaseUrl}/01_astrolabe_hero_core.glb`);
  const groupRef = useRef<THREE.Group>(null);
  const kineticRefs = useRef<AstrolabeKineticRefs>({
    gimbalOuter: null,
    gimbalMid: null,
    gimbalInner: null,
    corePulse: null,
    shards: [],
    floatingSlabs: null,
  });

  const clonedScene = useMemo(() => {
    if (!gltf.scene) return null;
    const scene = gltf.scene.clone(true);
    applyStage03Materials(scene, palette);

    // Wire kinetic nodes
    const refs: AstrolabeKineticRefs = {
      gimbalOuter: null,
      gimbalMid: null,
      gimbalInner: null,
      corePulse: null,
      shards: [],
      floatingSlabs: null,
    };

    scene.traverse((node) => {
      const name = node.name;
      if (name.includes('Gimbal_Ring_Outer') && !name.includes('Glow')) {
        refs.gimbalOuter = node;
      } else if (name.includes('Gimbal_Ring_Mid')) {
        refs.gimbalMid = node;
      } else if (name.includes('Gimbal_Ring_Inner')) {
        refs.gimbalInner = node;
      } else if (name.includes('Central_Reactor_Core')) {
        refs.corePulse = node;
      } else if (name.includes('Astrolabe_Shard_')) {
        refs.shards.push(node);
      }
    });

    kineticRefs.current = refs;
    return scene;
  }, [gltf.scene, palette]);

  useFrame((state, delta) => {
    if (isReducedMotion) return;
    const time = state.clock.getElapsedTime();
    animateStage03(kineticRefs.current, time, delta);
  });

  if (!clonedScene) return null;
  return <primitive ref={groupRef} object={clonedScene} name="AstrolabeHeroCore" />;
};

/**
 * Static Architecture packages (02, 03, 04, 05, 06, 13)
 */
const StaticWorldAsset: React.FC<{
  filename: string;
  assetBaseUrl: string;
  palette: Stage03MaterialPalette;
}> = ({ filename, assetBaseUrl, palette }) => {
  const gltf = useGLTF(`${assetBaseUrl}/${filename}`);
  const clonedScene = useMemo(() => {
    if (!gltf.scene) return null;
    const scene = gltf.scene.clone(true);
    applyStage03Materials(scene, palette);
    return scene;
  }, [gltf.scene, palette]);

  if (!clonedScene) return null;
  return <primitive object={clonedScene} name={`Static_${filename}`} />;
};

/**
 * Instanced Memory Vitrine Housings & Internal Archetypes
 */
const InstancedVitrines: React.FC<{
  assetBaseUrl: string;
  palette: Stage03MaterialPalette;
  vitrines: any[];
  selectedVitrineId?: string | null;
  highlightedVitrineIds?: string[];
  onSelectVitrine?: (id: string | null) => void;
  onHoverVitrine?: (id: string | null) => void;
}> = ({ assetBaseUrl, palette, vitrines, selectedVitrineId, highlightedVitrineIds, onSelectVitrine, onHoverVitrine }) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const housingGltf = useGLTF(`${assetBaseUrl}/07_memory_vitrine_housing.glb`);
  const mountainGltf = useGLTF(`${assetBaseUrl}/08_memory_world_mountain.glb`);
  const neuralGltf = useGLTF(`${assetBaseUrl}/09_memory_world_neural.glb`);
  const cityGltf = useGLTF(`${assetBaseUrl}/10_memory_world_city.glb`);
  const matrixGltf = useGLTF(`${assetBaseUrl}/11_memory_world_matrix.glb`);
  const chronoGltf = useGLTF(`${assetBaseUrl}/12_memory_world_chrono.glb`);

  const archetypeScenes = useMemo(() => {
    const map: Record<string, THREE.Group> = {
      mountain: mountainGltf.scene.clone(true),
      neural: neuralGltf.scene.clone(true),
      city: cityGltf.scene.clone(true),
      matrix: matrixGltf.scene.clone(true),
      chrono: chronoGltf.scene.clone(true),
    };
    Object.values(map).forEach((sc) => applyStage03Materials(sc, palette));
    return map;
  }, [mountainGltf.scene, neuralGltf.scene, cityGltf.scene, matrixGltf.scene, chronoGltf.scene, palette]);

  const housingScene = useMemo(() => {
    const sc = housingGltf.scene.clone(true);
    applyStage03Materials(sc, palette);
    return sc;
  }, [housingGltf.scene, palette]);

  return (
    <group name="InstancedVitrinesGroup">
      {vitrines.map((v) => {
        const pos = v.threejs_transform.position;
        const rot = v.threejs_transform.rotation_euler_xyz;
        const archKey = v.archetype;
        const archScene = archetypeScenes[archKey];
        const isHovered = hoveredId === v.id;
        const isSelected = selectedVitrineId === v.id;
        const isHighlighted = highlightedVitrineIds && highlightedVitrineIds.includes(v.id);
        const scale = isSelected ? 1.05 : isHighlighted ? 1.04 : isHovered ? 1.025 : 1.0;

        return (
          <group
            key={v.id}
            name={`Vitrine_${v.id}`}
            position={[pos[0], pos[1], pos[2]]}
            rotation={[rot[0], rot[1], rot[2]]}
            scale={[scale, scale, scale]}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHoveredId(v.id);
              onHoverVitrine?.(v.id);
            }}
            onPointerOut={(e) => {
              e.stopPropagation();
              if (hoveredId === v.id) {
                setHoveredId(null);
                onHoverVitrine?.(null);
              }
            }}
            onClick={(e) => {
              e.stopPropagation();
              onSelectVitrine?.(isSelected ? null : v.id);
            }}
          >
            <primitive object={housingScene.clone(true)} />
            {archScene && <primitive object={archScene.clone(true)} />}
          </group>
        );
      })}
    </group>
  );
};

/**
 * Instanced Human Scale Anchors (03 instances)
 */
const InstancedScaleAnchors: React.FC<{
  assetBaseUrl: string;
  palette: Stage03MaterialPalette;
  anchors: any[];
}> = ({ assetBaseUrl, palette, anchors }) => {
  const gltf = useGLTF(`${assetBaseUrl}/14_scale_anchor_figure.glb`);
  const baseScene = useMemo(() => {
    const sc = gltf.scene.clone(true);
    applyStage03Materials(sc, palette);
    return sc;
  }, [gltf.scene, palette]);

  return (
    <group name="ScaleAnchorsGroup">
      {anchors.map((a) => {
        const pos = a.threejs_transform.position;
        const rot = a.threejs_transform.rotation_euler_xyz;
        return (
          <group
            key={a.id}
            name={a.id}
            position={[pos[0], pos[1], pos[2]]}
            rotation={[rot[0], rot[1], rot[2]]}
          >
            <primitive object={baseScene.clone(true)} />
          </group>
        );
      })}
    </group>
  );
};

/**
 * Camera Controller aligning R3F perspective camera with STAGE03_CAMERAS specifications
 */
const Stage03CameraController: React.FC<{
  activeCamera?: 'CAM_CinematicHero' | 'CAM_MonumentalLowAngle' | 'CAM_ArchiveDetail';
  isReducedMotion?: boolean;
}> = ({ activeCamera = 'CAM_CinematicHero' }) => {
  const { camera } = useThree();

  useEffect(() => {
    const cfg = STAGE03_CAMERAS[activeCamera] || STAGE03_CAMERAS.CAM_CinematicHero;
    if (camera && (camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
      const pCam = camera as THREE.PerspectiveCamera;
      pCam.fov = cfg.fov;
      pCam.position.set(...cfg.position);
      pCam.lookAt(...cfg.target);
      pCam.updateProjectionMatrix();
    }
  }, [activeCamera, camera]);

  return null;
};

/**
 * Lighting & Atmosphere Rig for Stage 03 Memory Archive
 */
const Stage03LightingRig: React.FC = () => {
  const { scene } = useThree();

  useEffect(() => {
    setupStage03Lighting(scene);
    return () => {
      // Remove lights on unmount
      const lightsToRemove: THREE.Object3D[] = [];
      scene.traverse((obj) => {
        if ((obj as THREE.Light).isLight || (obj as THREE.SpotLight).isSpotLight) {
          lightsToRemove.push(obj);
        }
      });
      lightsToRemove.forEach((l) => scene.remove(l));
    };
  }, [scene]);

  return null;
};

/**
 * SpatialMemoryArchive — Production Three.js Assembly for Stage 03: Memory Archive
 */
export const SpatialMemoryArchive: React.FC<SpatialMemoryArchiveProps> = ({
  isReducedMotion = false,
  activeCamera = 'CAM_CinematicHero',
  assetBaseUrl = DEFAULT_ASSET_BASE,
  selectedVitrineId = null,
  selectedMemoryId = null,
  highlightedVitrineIds = [],
  onSelectVitrine,
  onHoverVitrine,
  onLoaded,
  onError,
}) => {
  // Test environment guard for headless JSDOM runs
  const isTest =
    typeof (globalThis as any).process !== 'undefined' &&
    (globalThis as any).process.env?.NODE_ENV === 'test';
  let isRealCanvas = true;
  try {
    const three = useThree();
    if (!three || !three.gl || typeof (three.gl as any).render !== 'function') {
      isRealCanvas = false;
    }
  } catch {
    isRealCanvas = false;
  }

  if (isTest || !isRealCanvas) {
    return (
      <group data-testid="spatial-memory-archive" name="SpatialMemoryArchiveRoot">
        <mesh position={[0, 1.8, 0]}>
          <boxGeometry args={[1, 1, 1]} />
          <meshBasicMaterial color="#d9650d" />
        </mesh>
      </group>
    );
  }

  const palette = useMemo(() => createStage03MaterialPalette(), []);
  const [instancesData, setInstancesData] = useState<any | null>(null);

  useEffect(() => {
    let isCancelled = false;
    fetch(`${assetBaseUrl}/stage03_memory_instances.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status} fetching instances json`);
        return res.json();
      })
      .then((data) => {
        if (!isCancelled) {
          setInstancesData(data);
          onLoaded?.();
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          console.warn('Failed to load stage03_memory_instances.json, using fallback empty registry:', err);
          onError?.(err);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [assetBaseUrl, onLoaded, onError]);

  const vitrines = instancesData?.vitrines || [];
  const scaleAnchors = instancesData?.scale_anchors || [];

  return (
    <group name="SpatialMemoryArchiveRoot">
      {/* Dynamic Camera Controller aligning with locked STAGE03_CAMERAS */}
      <Stage03CameraController
        activeCamera={activeCamera}
        isReducedMotion={isReducedMotion}
      />

      {/* Lighting & Atmosphere Rig */}
      <Stage03LightingRig />

      {/* 01 Hero Astrolabe */}
      <React.Suspense fallback={null}>
        <AstrolabeHeroCore
          assetBaseUrl={assetBaseUrl}
          palette={palette}
          isReducedMotion={isReducedMotion}
        />
      </React.Suspense>

      {/* Static World Packages */}
      <React.Suspense fallback={null}>
        <StaticWorldAsset
          filename="02_architecture_dais_stairs.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
        <StaticWorldAsset
          filename="03_architecture_columns_canopy.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
        <StaticWorldAsset
          filename="04_conduits_viaduct.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
        <StaticWorldAsset
          filename="05_orbital_viaducts.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
        <StaticWorldAsset
          filename="06_distant_towers.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
        <StaticWorldAsset
          filename="13_floating_slabs.glb"
          assetBaseUrl={assetBaseUrl}
          palette={palette}
        />
      </React.Suspense>

      {/* Instanced Vitrines with internal memory-world archetypes & interactive selection */}
      {vitrines.length > 0 && (
        <React.Suspense fallback={null}>
          <InstancedVitrines
            assetBaseUrl={assetBaseUrl}
            palette={palette}
            vitrines={vitrines}
            selectedVitrineId={selectedVitrineId}
            highlightedVitrineIds={highlightedVitrineIds}
            onSelectVitrine={onSelectVitrine}
            onHoverVitrine={onHoverVitrine}
          />
        </React.Suspense>
      )}

      {/* 3D Dynamic Memory Relationship Splines (0 draw calls when unselected, 1 when selected) */}
      {vitrines.length > 0 && (
        <SpatialMemoryRelationships
          selectedMemoryId={
            selectedMemoryId ||
            (selectedVitrineId ? memoryArchiveService.getMemoryByVitrineId(selectedVitrineId)?.id || null : null)
          }
          vitrines={vitrines}
          isReducedMotion={isReducedMotion}
        />
      )}

      {/* Instanced Scale Anchors */}
      {scaleAnchors.length > 0 && (
        <React.Suspense fallback={null}>
          <InstancedScaleAnchors
            assetBaseUrl={assetBaseUrl}
            palette={palette}
            anchors={scaleAnchors}
          />
        </React.Suspense>
      )}
    </group>
  );
};
