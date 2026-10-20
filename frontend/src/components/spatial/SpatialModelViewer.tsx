import React, { useRef, useMemo, useEffect } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import { SpatialModelViewerProps } from '../../types/spatial';

/**
 * Normalizes PBR materials across imported GLB meshes
 * Enforces the AryaOS Batman-inspired palette: graphite armor, gunmetal mechanicals, amber energy.
 */
function normalizeGlbMaterials(scene: THREE.Group): THREE.Group {
  const cloned = scene.clone(true);

  cloned.traverse((node) => {
    if ((node as THREE.Mesh).isMesh) {
      const mesh = node as THREE.Mesh;
      if (mesh.material) {
        // Clone material to avoid mutating cached Drei GLTF assets
        const origMat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        const mat = (origMat as THREE.MeshStandardMaterial).clone();

        const matName = (origMat.name || '').toLowerCase();
        const meshName = (mesh.name || '').toLowerCase();

        // Detect if this part is an energy conduit by material or mesh name
        const isEnergy =
          matName.includes('amber') ||
          matName.includes('emissive') ||
          meshName.includes('energy') ||
          meshName.includes('conduit') ||
          meshName.includes('glow') ||
          meshName.includes('beacon') ||
          meshName.includes('lens') ||
          meshName.includes('slit') ||
          (mat.emissive && mat.emissive.r > 0.6 && mat.emissive.b < 0.2);

        if (isEnergy) {
          mat.userData = { ...mat.userData, isEnergy: true };
          mat.emissive = new THREE.Color('#f59e0b');
          mat.emissiveIntensity = 2.0;
          mat.toneMapped = false;
        } else if (matName.includes('titanium')) {
          // Brushed titanium accents, cage ribs, louvers, and bevel trims
          mat.metalness = 0.95;
          mat.roughness = 0.22;
          mat.color = new THREE.Color('#64748b');
        } else if (matName.includes('obsidian')) {
          // Dark obsidian plinth and outer armor shells
          mat.metalness = 0.22;
          mat.roughness = 0.28;
          mat.color = new THREE.Color('#0c1017');
        } else {
          // Dark gunmetal structural chassis and reactor flanges
          mat.metalness = 0.92;
          mat.roughness = 0.32;
          mat.color = new THREE.Color('#161b24');
        }

        mesh.material = mat;
      }
    }
  });

  return cloned;
}

/**
 * Inner GLB Loader component (used inside Suspense)
 */
const GlbSceneRenderer: React.FC<SpatialModelViewerProps> = ({
  modelPath,
  position = [0, 0, 0],
  scale = 1,
  rotation = [0, 0, 0],
  isReducedMotion = false,
  pointer = { x: 0, y: 0 },
  onCoreClick,
  systemState,
  intentStage = 'IDLE',
}) => {
  const gltf = useGLTF(modelPath);
  const groupRef = useRef<THREE.Group>(null);

  // Normalize materials once per loaded scene
  const normalizedScene = useMemo(() => {
    if (!gltf.scene) return null;
    return normalizeGlbMaterials(gltf.scene);
  }, [gltf.scene]);

  // Operational lighting state derivation
  const isFailed = systemState === 'FAILED' || systemState === 'ERROR';
  const isGenerating = systemState === 'GENERATING' || systemState === 'PROCESSING' || intentStage === 'READY';
  const isAnalyzing = intentStage === 'ANALYZING' || intentStage === 'PLANNING' || intentStage === 'ROUTING';

  const targetColorHex = isFailed
    ? '#ef4444'
    : isGenerating
    ? '#fbbf24'
    : isAnalyzing
    ? '#38bdf8'
    : '#f59e0b';

  const targetColor = useMemo(() => new THREE.Color(targetColorHex), [targetColorHex]);

  // Extract energy conduits to dynamically update emissive pulses
  const energyMaterials = useMemo(() => {
    if (!normalizedScene) return [];
    const mats: THREE.MeshStandardMaterial[] = [];
    normalizedScene.traverse((node) => {
      if ((node as THREE.Mesh).isMesh) {
        const mesh = node as THREE.Mesh;
        if (mesh.material) {
          const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          list.forEach((m) => {
            if ((m as any).userData?.isEnergy && (m as THREE.MeshStandardMaterial).emissive) {
              mats.push(m as THREE.MeshStandardMaterial);
            }
          });
        }
      }
    });
    return mats;
  }, [normalizedScene]);

  // Clean disposal on unmount
  useEffect(() => {
    return () => {
      if (normalizedScene) {
        normalizedScene.traverse((node) => {
          if ((node as THREE.Mesh).isMesh) {
            const mesh = node as THREE.Mesh;
            mesh.geometry?.dispose();
            if (Array.isArray(mesh.material)) {
              mesh.material.forEach((m) => m.dispose());
            } else {
              mesh.material?.dispose();
            }
          }
        });
      }
    };
  }, [normalizedScene]);

  useFrame((state, delta) => {
    if (!groupRef.current) return;

    // Pointer parallax response
    if (!isReducedMotion) {
      groupRef.current.rotation.y = THREE.MathUtils.lerp(
        groupRef.current.rotation.y,
        rotation[1] + pointer.x * 0.15,
        0.04
      );
      groupRef.current.rotation.x = THREE.MathUtils.lerp(
        groupRef.current.rotation.x,
        rotation[0] - pointer.y * 0.08,
        0.04
      );
    }

    if (isReducedMotion) return;

    // Controlled slow rotation & subtle breathing float
    const time = state.clock.getElapsedTime();
    groupRef.current.rotation.y += delta * 0.06;
    groupRef.current.position.y = position[1] + Math.sin(time * 1.6) * 0.04;

    // React to system state via energy emissive color lerp and dynamic pulsing
    const pulseSpeed = isGenerating ? 4.5 : isAnalyzing ? 3.0 : 1.8;
    const baseIntensity = isGenerating ? 2.8 : isAnalyzing ? 2.2 : 1.8;
    const dynamicIntensity = baseIntensity + Math.sin(time * pulseSpeed) * (isGenerating ? 0.8 : 0.4);

    if (energyMaterials.length > 0) {
      for (let i = 0; i < energyMaterials.length; i++) {
        const mat = energyMaterials[i];
        mat.emissive.lerp(targetColor, 0.08);
        mat.emissiveIntensity = dynamicIntensity;
      }
    }
  });

  if (!normalizedScene) return null;

  const scaleVec: [number, number, number] =
    typeof scale === 'number' ? [scale, scale, scale] : scale;

  return (
    <group
      ref={groupRef}
      position={position}
      scale={scaleVec}
      rotation={rotation}
      onClick={onCoreClick}
      name="AryaOS_GLB_Core"
    >
      <primitive object={normalizedScene} />
    </group>
  );
};

/**
 * ErrorBoundary for safe GLB loading
 */
interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

class GlbErrorBoundary extends React.Component<
  { children: React.ReactNode; onError?: (error: Error) => void; fallback?: React.ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: React.ReactNode; onError?: (error: Error) => void; fallback?: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    if (this.props.onError) {
      this.props.onError(error);
    }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || null;
    }
    return this.props.children;
  }
}

/**
 * SpatialModelViewer — Primary 3D GLB/GLTF Asset Pipeline
 * Renders GLB models with Suspense and ErrorBoundary safety, material normalization,
 * and seamless fallback capability.
 */
export const SpatialModelViewer: React.FC<SpatialModelViewerProps> = (props) => {
  return (
    <GlbErrorBoundary onError={props.onError}>
      <React.Suspense fallback={null}>
        <GlbSceneRenderer {...props} />
      </React.Suspense>
    </GlbErrorBoundary>
  );
};
