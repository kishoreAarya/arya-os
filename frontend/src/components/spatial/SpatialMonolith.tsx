import React, { useRef, useMemo } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { SpatialMonolithProps } from '../../types/spatial';

/**
 * SpatialMonolith — Procedural AryaOS Core Architecture
 * Architectural silhouette: Multi-tiered graphite computational pylons,
 * central amber energy conduit, rotating calibration rings, and subtle parallax.
 * Designed with a clean extension point for Phase 2 Tripo GLB model drops.
 */
export const SpatialMonolith: React.FC<SpatialMonolithProps> = ({
  isReducedMotion = false,
  pointer = { x: 0, y: 0 },
  activeState = 'HUB',
  onCoreClick,
  systemState,
  intentStage = 'IDLE',
}) => {
  const rootGroupRef = useRef<THREE.Group>(null);
  const outerRingsRef = useRef<THREE.Group>(null);
  const innerCoreRef = useRef<THREE.Mesh>(null);
  const energyPulsesRef = useRef<THREE.Points>(null);
  const upperCrownRef = useRef<THREE.Group>(null);

  const isFailed = systemState === 'FAILED' || systemState === 'ERROR';
  const isGenerating = systemState === 'GENERATING' || systemState === 'PROCESSING' || intentStage === 'READY';
  const isAnalyzing = intentStage === 'ANALYZING' || intentStage === 'PLANNING' || intentStage === 'ROUTING';
  const isCompleted = systemState === 'COMPLETED' || systemState === 'ONLINE';

  const coreColor = isFailed
    ? '#ef4444'
    : isGenerating
    ? '#fbbf24'
    : isAnalyzing
    ? '#38bdf8'
    : '#f59e0b';

  // Materials for monolithic machine architecture
  const graphiteMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#0e1422',
        metalness: 0.92,
        roughness: 0.22,
      }),
    []
  );

  const carbonPlatesMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#090d16',
        metalness: 0.85,
        roughness: 0.35,
        wireframe: false,
      }),
    []
  );

  const amberEnergyMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: coreColor,
        wireframe: true,
        transparent: true,
        opacity: isGenerating ? 0.9 : isAnalyzing ? 0.75 : 0.65,
      }),
    [coreColor, isGenerating, isAnalyzing]
  );

  const amberSolidCoreMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: isFailed ? '#ef4444' : isGenerating ? '#fef08a' : isAnalyzing ? '#7dd3fc' : '#fbbf24',
        transparent: true,
        opacity: 0.88,
      }),
    [isFailed, isGenerating, isAnalyzing]
  );

  // Energy field particles along the vertical column
  const particleCount = 48;
  const particlePositions = useMemo(() => {
    const pos = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const angle = (i / particleCount) * Math.PI * 2;
      const radius = 0.72 + (Math.sin(i * 3) * 0.15);
      const y = (i / particleCount) * 4.2 - 0.5;
      pos[i * 3] = Math.cos(angle) * radius;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = Math.sin(angle) * radius;
    }
    return pos;
  }, []);

  useFrame((state, delta) => {
    if (!rootGroupRef.current) return;

    // 1. Subtle pointer parallax tilt (physical instrument response)
    if (!isReducedMotion) {
      rootGroupRef.current.rotation.y = THREE.MathUtils.lerp(
        rootGroupRef.current.rotation.y,
        pointer.x * 0.15,
        0.04
      );
      rootGroupRef.current.rotation.x = THREE.MathUtils.lerp(
        rootGroupRef.current.rotation.x,
        -pointer.y * 0.08,
        0.04
      );
    }

    if (isReducedMotion) return;

    const ringSpeedMult = isGenerating ? 3.0 : isAnalyzing ? 2.0 : 1.0;

    // 2. Controlled rotation of calibration rings
    if (outerRingsRef.current) {
      outerRingsRef.current.rotation.y += delta * 0.12 * ringSpeedMult;
      outerRingsRef.current.rotation.z += delta * 0.04 * ringSpeedMult;
    }

    // 3. Central energy pulse & subtle float
    const time = state.clock.getElapsedTime();
    const pulseRate = isGenerating ? 4.8 : isAnalyzing ? 3.4 : 2.0;
    if (innerCoreRef.current) {
      const pulse = 1.0 + Math.sin(time * pulseRate) * (isGenerating ? 0.09 : 0.05);
      innerCoreRef.current.scale.set(pulse, 1.0 + Math.sin(time * (pulseRate * 0.8)) * 0.04, pulse);
    }

    // 4. Crown breathing float
    if (upperCrownRef.current) {
      upperCrownRef.current.position.y = 3.6 + Math.sin(time * 1.5) * 0.06;
      upperCrownRef.current.rotation.y -= delta * 0.08 * ringSpeedMult;
    }

    // 5. Energy particles drift
    if (energyPulsesRef.current) {
      energyPulsesRef.current.rotation.y += delta * 0.25 * ringSpeedMult;
    }
  });

  return (
    <group
      ref={rootGroupRef}
      position={[0, 0, 0]}
      onClick={onCoreClick}
      name="AryaOS_System_Core_Monolith"
    >
      {/* ==================================================================
          A. BASE FOUNDATION / COMPUTE PLINTH
          ================================================================== */}
      {/* Octagonal Stepped Base 1 */}
      <mesh position={[0, 0.12, 0]} material={graphiteMaterial}>
        <cylinderGeometry args={[2.8, 3.2, 0.24, 8]} />
      </mesh>

      {/* Stepped Base 2 with Amber Perimeter Hairline */}
      <mesh position={[0, 0.32, 0]} material={carbonPlatesMaterial}>
        <cylinderGeometry args={[2.2, 2.7, 0.18, 8]} />
      </mesh>
      <mesh position={[0, 0.38, 0]}>
        <ringGeometry args={[2.18, 2.24, 8]} />
        <meshBasicMaterial color="#f59e0b" transparent opacity={0.4} />
      </mesh>

      {/* ==================================================================
          B. 4 PERIMETER COMPUTATIONAL PYLONS (ARCHITECTURAL SILHOUETTE)
          ================================================================== */}
      {[-1, 1].map((xSign) =>
        [-1, 1].map((zSign) => (
          <group
            key={`pylon-${xSign}-${zSign}`}
            position={[xSign * 1.25, 1.7, zSign * 1.25]}
            rotation={[0, (xSign * zSign > 0 ? 1 : -1) * 0.4, 0]}
          >
            {/* Pylon Main Tower */}
            <mesh material={graphiteMaterial}>
              <boxGeometry args={[0.34, 2.6, 0.34]} />
            </mesh>

            {/* Inward Facing Heat/Energy Fin */}
            <mesh
              position={[-xSign * 0.12, 0, -zSign * 0.12]}
              material={carbonPlatesMaterial}
            >
              <boxGeometry args={[0.06, 2.4, 0.18]} />
            </mesh>

            {/* Amber Indicator Notch */}
            <mesh position={[0, 0.4, 0.18]}>
              <boxGeometry args={[0.08, 0.5, 0.02]} />
              <meshBasicMaterial color="#f59e0b" />
            </mesh>
          </group>
        ))
      )}

      {/* ==================================================================
          C. CENTRAL AMBER ENERGY COLUMN & COMPUTATIONAL NUCLEUS
          ================================================================== */}
      {/* Inner Solid Amber Core */}
      <mesh
        ref={innerCoreRef}
        position={[0, 1.8, 0]}
        material={amberSolidCoreMaterial}
      >
        <cylinderGeometry args={[0.32, 0.32, 2.4, 16]} />
      </mesh>

      {/* Outer Crystalline Energy Cage */}
      <mesh position={[0, 1.8, 0]} material={amberEnergyMaterial}>
        <cylinderGeometry args={[0.62, 0.62, 2.2, 8]} />
      </mesh>

      {/* Vertical Core Wave Particles */}
      <points ref={energyPulsesRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            count={particleCount}
            array={particlePositions}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.065}
          color="#fbbf24"
          transparent
          opacity={0.8}
          sizeAttenuation
        />
      </points>

      {/* ==================================================================
          D. ROTATING CALIBRATION & ALIGNMENT GIMBAL RINGS
          ================================================================== */}
      <group ref={outerRingsRef} position={[0, 1.8, 0]}>
        {/* Horizontal Primary Calibration Ring */}
        <mesh>
          <torusGeometry args={[1.72, 0.028, 8, 48]} />
          <meshStandardMaterial
            color="#1e293b"
            metalness={0.9}
            roughness={0.2}
          />
        </mesh>

        {/* Diagonal Notched Ring */}
        <mesh rotation={[Math.PI / 4, 0, 0]}>
          <torusGeometry args={[1.52, 0.022, 6, 36]} />
          <meshBasicMaterial color="#d97706" transparent opacity={0.65} />
        </mesh>
      </group>

      {/* ==================================================================
          E. UPPER QUANTUM CROWN (HOVERING EMITTER STRUCTURE)
          ================================================================== */}
      <group ref={upperCrownRef} position={[0, 3.6, 0]}>
        {/* Floating Crown Inverted Pyramid / Obelisk Cap */}
        <mesh material={graphiteMaterial}>
          <octahedronGeometry args={[0.65, 0]} />
        </mesh>

        {/* Crown Amber Aperture */}
        <mesh position={[0, -0.2, 0]}>
          <ringGeometry args={[0.2, 0.45, 8]} />
          <meshBasicMaterial color="#f59e0b" transparent opacity={0.7} />
        </mesh>
      </group>
    </group>
  );
};
