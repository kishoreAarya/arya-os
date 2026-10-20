import React, { useRef, useMemo } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';
import {
  SpatialCameraRigProps,
  CAMERA_WAYPOINTS,
  interpolateSpatialProgress,
  interpolateStageProgress,
} from '../../types/spatial';

export { CAMERA_WAYPOINTS };

/**
 * SpatialCameraRig — Smooth Damped Camera Transitions & Scroll Progress Architecture
 * Supports discrete waypoints (ENTRY, APPROACH, HUB) and continuous scroll progress [0.0 -> 1.0].
 */
export const SpatialCameraRig: React.FC<SpatialCameraRigProps> = ({
  cameraState,
  spatialProgress,
  pointer,
  isReducedMotion,
  focusTarget,
}) => {
  const { camera } = useThree();
  const currentLookAtRef = useRef<THREE.Vector3>(new THREE.Vector3(0, 1.8, 0));

  const waypoint = useMemo(
    () => CAMERA_WAYPOINTS[cameraState] || CAMERA_WAYPOINTS.HUB,
    [cameraState]
  );

  useFrame((state, delta) => {
    let targetPos: THREE.Vector3;
    let targetLookAt: THREE.Vector3;

    // Focus target (inspected item) takes priority if active
    if (focusTarget) {
      targetPos = new THREE.Vector3(...focusTarget.position);
      targetLookAt = new THREE.Vector3(...focusTarget.target);
    } else if (spatialProgress !== undefined) {
      // Continuous scroll progress across the 9-stage spatial operating narrative
      const interpolated = interpolateStageProgress(spatialProgress);
      targetPos = new THREE.Vector3(...interpolated.position);
      targetLookAt = new THREE.Vector3(...interpolated.target);
    } else {
      targetPos = new THREE.Vector3(...waypoint.position);
      targetLookAt = new THREE.Vector3(...waypoint.target);
    }

    // Phase 16: Cinematic Awakening Camera Progression (20-40s subtle push toward central AryaOS structure)
    if (cameraState === 'ENTRY' && !isReducedMotion && !focusTarget && (spatialProgress === undefined || spatialProgress < 0.02)) {
      const elapsed = state.clock.getElapsedTime();
      const pushRatio = Math.min(elapsed / 30.0, 1.0);
      targetPos.z -= pushRatio * 0.45;
      targetPos.y += Math.sin(elapsed * 0.2) * 0.02;
    }

    // Apply subtle pointer parallax to position if not reduced motion
    if (!isReducedMotion) {
      targetPos.x += pointer.x * 0.45;
      targetPos.y += pointer.y * 0.25;
    }

    if (isReducedMotion) {
      // Immediate snapping for reduced motion accessibility
      camera.position.copy(targetPos);
      currentLookAtRef.current.copy(targetLookAt);
      camera.lookAt(targetLookAt);
      return;
    }

    // Smooth cinematic damping interpolation (frame-rate independent)
    const damping = Math.min(delta * 2.8, 0.12);
    camera.position.lerp(targetPos, damping);

    // Interpolate look-at target vector
    currentLookAtRef.current.lerp(targetLookAt, damping);
    camera.lookAt(currentLookAtRef.current);
  });

  return null;
};
