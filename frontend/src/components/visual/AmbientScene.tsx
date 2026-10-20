import React, { useMemo, useRef, useState, useEffect } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame } from '@react-three/fiber';
import { usePrefersReducedMotion } from '../motion/MotionSystem';

/**
 * Helper to safely test WebGL availability (e.g. guarded against JSDOM)
 */
function checkWebGLSupport(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

/**
 * Minimal ambient particle drift for cinematic depth
 */
const AmbientParticles: React.FC<{ isReducedMotion: boolean }> = ({ isReducedMotion }) => {
  const pointsRef = useRef<THREE.Points>(null);
  const count = 75;

  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 22;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 14;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 10;
    }
    return pos;
  }, []);

  useFrame((_, delta) => {
    if (isReducedMotion || !pointsRef.current) return;
    // Extremely slow, low-intensity ambient drift
    pointsRef.current.rotation.y += delta * 0.015;
    pointsRef.current.rotation.x += delta * 0.008;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.06}
        color="#3b82f6"
        transparent
        opacity={0.35}
        sizeAttenuation
      />
    </points>
  );
};

/**
 * Minimal Stage 1 Three.js Ambient Scene Boundary
 * Establishes integration foundation without heavy overhead or blocking interactions.
 */
export const AmbientScene: React.FC = () => {
  const [hasWebGL, setHasWebGL] = useState(false);
  const isReducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    setHasWebGL(checkWebGLSupport());
  }, []);

  // Gracefully fallback if WebGL is unavailable (e.g. JSDOM in tests or low-end browser)
  if (!hasWebGL || isReducedMotion) {
    return null;
  }

  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 0,
        opacity: 0.6,
      }}
    >
      <Canvas
        style={{ pointerEvents: 'none' }}
        camera={{ position: [0, 0, 12], fov: 50 }}
        gl={{
          antialias: false,
          powerPreference: 'low-power',
          alpha: true,
          preserveDrawingBuffer: false,
        }}
        dpr={1}
      >
        <AmbientParticles isReducedMotion={isReducedMotion} />
      </Canvas>
    </div>
  );
};
