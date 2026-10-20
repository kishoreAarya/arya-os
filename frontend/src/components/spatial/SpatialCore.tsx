import React, { useState, useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { SpatialCoreProps } from '../../types/spatial';
import { SpatialModelViewer } from './SpatialModelViewer';
import { SpatialMonolith } from './SpatialMonolith';

const DEFAULT_MODEL_PATH = '/models/aryaos-core.glb';

/**
 * SpatialCore — Hybrid 3D System Core Architecture
 * Intelligently switches between high-fidelity GLB/GLTF 3D assets and
 * the deterministic procedural SpatialMonolith fallback.
 */
export const SpatialCore: React.FC<SpatialCoreProps> = ({
  modelPath = DEFAULT_MODEL_PATH,
  isReducedMotion = false,
  pointer = { x: 0, y: 0 },
  activeState = 'HUB',
  onCoreClick,
  systemState,
  intentStage,
}) => {
  const [isGlbAvailable, setIsGlbAvailable] = useState<boolean>(false);
  const [hasAttemptedCheck, setHasAttemptedCheck] = useState<boolean>(false);

  let isInsideRealCanvas = false;
  try {
    const three = useThree();
    if (three && three.gl && typeof (three.gl as any).render === 'function') {
      isInsideRealCanvas = true;
    }
  } catch {
    isInsideRealCanvas = false;
  }

  useEffect(() => {
    let isCancelled = false;

    // Fast HEAD probe to verify if GLB asset exists at the expected path
    if (typeof window !== 'undefined' && typeof window.fetch === 'function') {
      fetch(modelPath, { method: 'HEAD' })
        .then((res) => {
          if (!isCancelled) {
            // Model must exist with 200 OK and valid non-HTML response
            const isOk = res.ok && res.status === 200;
            const contentType = res.headers.get('content-type') || '';
            const isNotHtml = !contentType.includes('text/html');
            setIsGlbAvailable(Boolean(isOk && isNotHtml));
            setHasAttemptedCheck(true);
          }
        })
        .catch(() => {
          if (!isCancelled) {
            setIsGlbAvailable(false);
            setHasAttemptedCheck(true);
          }
        });
    } else {
      setHasAttemptedCheck(true);
    }

    return () => {
      isCancelled = true;
    };
  }, [modelPath]);

  const coreContent = isGlbAvailable ? (
    <SpatialModelViewer
      modelPath={modelPath}
      position={[0, 0, 0]}
      scale={0.95}
      rotation={[0, 0, 0]}
      isReducedMotion={isReducedMotion}
      pointer={pointer}
      onCoreClick={onCoreClick}
      systemState={systemState}
      intentStage={intentStage}
      onError={() => {
        // If GLB throws or fails to render, gracefully fall back to procedural monolith
        setIsGlbAvailable(false);
      }}
    />
  ) : (
    <SpatialMonolith
      isReducedMotion={isReducedMotion}
      pointer={pointer}
      activeState={activeState}
      onCoreClick={onCoreClick}
      glbModelPath={hasAttemptedCheck ? modelPath : undefined}
      systemState={systemState}
      intentStage={intentStage}
    />
  );

  if (isInsideRealCanvas) {
    return <group name="SpatialCoreContainer">{coreContent}</group>;
  }

  return (
    <group
      data-testid="spatial-core-container"
      data-active-state={activeState}
      name="SpatialCoreContainer"
    >
      {coreContent}
    </group>
  );
};
