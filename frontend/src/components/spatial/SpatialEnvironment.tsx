import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { MeshReflectorMaterial } from '@react-three/drei';
import { SpatialEnvironmentProps } from '../../types/spatial';

/**
 * Floating quantum luminescence particles creating volumetric aerospace depth
 */
const QuantumDustParticles: React.FC<{ isReducedMotion?: boolean }> = ({ isReducedMotion }) => {
  const pointsRef = useRef<THREE.Points>(null);

  const [positions] = useMemo(() => {
    const count = 220;
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 60;
      pos[i * 3 + 1] = 0.5 + Math.random() * 14;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 60;
    }
    return [pos];
  }, []);

  useFrame((state) => {
    if (isReducedMotion || !pointsRef.current) return;
    const t = state.clock.getElapsedTime() * 0.05;
    pointsRef.current.rotation.y = t;
  });

  return (
    <points ref={pointsRef} name="QuantumDustParticles">
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
      </bufferGeometry>
      <pointsMaterial
        color="#fbbf24"
        size={0.065}
        transparent
        opacity={0.32}
        sizeAttenuation
      />
    </points>
  );
};

/**
 * Floating obsidian islands / angular debris hovering in space
 * Creates atmospheric depth and vast cybernetic landscape as seen in the visual reference.
 */
const FloatingObsidianIslands: React.FC<{ isReducedMotion?: boolean }> = ({ isReducedMotion }) => {
  const groupRef = useRef<THREE.Group>(null);

  // Procedural island positions and scales (lightweight octahedrons and dodecahedrons)
  const islands = useMemo(() => {
    return [
      { pos: [-14.5, 6.2, -18.0] as [number, number, number], scale: [2.2, 1.4, 2.0] as [number, number, number], rot: [0.2, 0.4, 0.1], speed: 0.8 },
      { pos: [16.0, 7.8, -22.0] as [number, number, number], scale: [2.6, 1.8, 2.4] as [number, number, number], rot: [-0.1, 0.6, 0.3], speed: 0.6 },
      { pos: [-9.0, 9.4, -28.0] as [number, number, number], scale: [3.2, 2.1, 3.0] as [number, number, number], rot: [0.3, -0.2, 0.1], speed: 0.7 },
      { pos: [11.5, 11.2, -32.0] as [number, number, number], scale: [3.8, 2.6, 3.4] as [number, number, number], rot: [0.1, 0.5, -0.2], speed: 0.5 },
      { pos: [-18.0, 4.5, -12.0] as [number, number, number], scale: [1.6, 1.0, 1.4] as [number, number, number], rot: [0.4, 0.1, 0.2], speed: 0.9 },
      { pos: [19.0, 5.0, -14.0] as [number, number, number], scale: [1.8, 1.2, 1.6] as [number, number, number], rot: [-0.2, 0.3, 0.1], speed: 0.85 },
    ];
  }, []);

  const obsidianMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#070b12',
        metalness: 0.92,
        roughness: 0.32,
        flatShading: true,
      }),
    []
  );

  const amberVeinMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: '#f59e0b',
        wireframe: true,
        transparent: true,
        opacity: 0.25,
      }),
    []
  );

  useFrame((state) => {
    if (isReducedMotion || !groupRef.current) return;
    const time = state.clock.getElapsedTime();
    groupRef.current.children.forEach((child, idx) => {
      const isl = islands[idx];
      if (isl) {
        child.position.y = isl.pos[1] + Math.sin(time * 0.4 * isl.speed + idx) * 0.25;
        child.rotation.y += 0.0015 * isl.speed;
      }
    });
  });

  return (
    <group ref={groupRef} name="FloatingObsidianIslands">
      {islands.map((isl, idx) => (
        <group key={`island-${idx}`} position={isl.pos} rotation={isl.rot as [number, number, number]}>
          <mesh scale={isl.scale} material={obsidianMaterial}>
            <dodecahedronGeometry args={[1, 0]} />
          </mesh>
          <mesh scale={[isl.scale[0] * 1.01, isl.scale[1] * 1.01, isl.scale[2] * 1.01]} material={amberVeinMaterial}>
            <dodecahedronGeometry args={[1, 0]} />
          </mesh>
        </group>
      ))}
    </group>
  );
};

/**
 * Distant gothic/cybernetic spires looming in the background atmosphere
 * Establishes monumental scale and grand environment presence.
 */
const DistantAryaTowers: React.FC = () => {
  const towers = useMemo(() => {
    return [
      { pos: [0, 16.0, -52.0] as [number, number, number], args: [3.8, 6.2, 38, 4] as [number, number, number, number], isCenter: true },
      { pos: [-24.0, 12.0, -48.0] as [number, number, number], args: [2.6, 4.4, 28, 4] as [number, number, number, number], isCenter: false },
      { pos: [24.0, 12.0, -48.0] as [number, number, number], args: [2.6, 4.4, 28, 4] as [number, number, number, number], isCenter: false },
      { pos: [-42.0, 8.0, -60.0] as [number, number, number], args: [3.2, 5.0, 22, 4] as [number, number, number, number], isCenter: false },
      { pos: [42.0, 8.0, -60.0] as [number, number, number], args: [3.2, 5.0, 22, 4] as [number, number, number, number], isCenter: false },
    ];
  }, []);

  const towerMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#04070d',
        metalness: 0.9,
        roughness: 0.4,
      }),
    []
  );

  const centerSpireLight = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: '#f59e0b',
        transparent: true,
        opacity: 0.45,
      }),
    []
  );

  return (
    <group name="DistantAryaTowers">
      {towers.map((tower, idx) => (
        <group key={`tower-${idx}`} position={tower.pos}>
          {/* Main Tower Tapered Pylon */}
          <mesh material={towerMaterial}>
            <cylinderGeometry args={tower.args} />
          </mesh>
          {/* Center Tower Beacon Slit */}
          {tower.isCenter && (
            <mesh position={[0, 4, 2.2]} material={centerSpireLight}>
              <boxGeometry args={[0.2, 14, 0.4]} />
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
};

/**
 * SpatialEnvironment — Cinematic Atmosphere, Dramatic Lighting & PBR Floor Reflection
 * Batman-inspired dark mood: Obsidian ground plane with subtle silhouette reflection,
 * volumetric fog, high-contrast key & rim lighting with restrained amber/gold illumination.
 */
export const SpatialEnvironment: React.FC<SpatialEnvironmentProps> = ({
  isReducedMotion = false,
  enableReflections = true,
}) => {
  // Generate concentric spatial coordinate rings for technical scale
  const ringRadii = useMemo(() => [4, 8, 13, 19, 27, 36, 48], []);

  // Generate radial grid ray endpoints
  const radialRays = useMemo(() => {
    const rayCount = 16;
    const lines: [number, number, number, number, number, number][] = [];
    for (let i = 0; i < rayCount; i++) {
      const angle = (i / rayCount) * Math.PI * 2;
      const x1 = Math.cos(angle) * 3.5;
      const z1 = Math.sin(angle) * 3.5;
      const x2 = Math.cos(angle) * 48;
      const z2 = Math.sin(angle) * 48;
      lines.push([x1, 0.005, z1, x2, 0.005, z2]);
    }
    return lines;
  }, []);

  return (
    <>
      {/* 1. Volumetric Atmosphere Fog */}
      <color attach="background" args={['#020408']} />
      <fogExp2 attach="fog" args={['#020408', 0.022]} />

      {/* 2. Dramatic Cinematic Lighting Setup */}
      {/* Subtle cold ambient fill to keep shadows from clipping completely */}
      <ambientLight color="#080e1a" intensity={0.25} />

      {/* Primary Key Light: High-angle amber/gold directional beam */}
      <directionalLight
        position={[10, 18, 12]}
        color="#f59e0b"
        intensity={2.4}
        castShadow={false}
      />

      {/* Secondary Rim Light: Sharp steel/gunmetal edge light from behind-left */}
      <directionalLight
        position={[-14, 14, -14]}
        color="#94a3b8"
        intensity={1.8}
        castShadow={false}
      />

      {/* Cool Cyan Accent Light: Enhances continuity & technical instruments */}
      <directionalLight
        position={[16, 8, -10]}
        color="#38bdf8"
        intensity={0.65}
        castShadow={false}
      />

      {/* Core Ground Bounce: Low-angle amber bounce sculpting lower armor bevels */}
      <directionalLight
        position={[0, -4, 6]}
        color="#78350f"
        intensity={0.65}
        castShadow={false}
      />

      {/* Overhead Focus Spotlight pointing directly down at the Core */}
      <spotLight
        position={[0, 16, 0]}
        color="#fbbf24"
        intensity={1.6}
        angle={0.55}
        penumbra={0.85}
        distance={28}
      />

      {/* Monolith Core Point Emission (Amber energy radiation) */}
      <pointLight
        position={[0, 2.4, 0]}
        color="#d97706"
        intensity={3.2}
        distance={16}
        decay={2}
      />

      {/* 3. Obsidian / Graphite Spatial Floor with Subtle Reflector Material */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
        <planeGeometry args={[160, 160]} />
        {enableReflections && !isReducedMotion ? (
          <MeshReflectorMaterial
            blur={[300, 100]}
            resolution={512}
            mirror={0.32}
            mixBlur={1.0}
            mixStrength={1.4}
            roughness={0.38}
            depthScale={1.2}
            minDepthThreshold={0.4}
            maxDepthThreshold={1.4}
            color="#060911"
            metalness={0.88}
          />
        ) : (
          <meshStandardMaterial
            color="#060911"
            roughness={0.28}
            metalness={0.88}
          />
        )}
      </mesh>

      {/* 4. Concentric Spatial Technical Coordinate Rings */}
      {ringRadii.map((radius, idx) => (
        <mesh
          key={`ring-${radius}`}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, 0.005, 0]}
        >
          <ringGeometry args={[radius - 0.025, radius + 0.025, 64]} />
          <meshBasicMaterial
            color={idx === 0 || idx === 2 ? '#d97706' : idx === 3 ? '#38bdf8' : '#1e293b'}
            transparent
            opacity={idx === 0 ? 0.35 : idx === 2 ? 0.22 : idx === 3 ? 0.18 : 0.12}
          />
        </mesh>
      ))}

      {/* 5. Radial Scale Rays */}
      {radialRays.map(([x1, y1, z1, x2, y2, z2], idx) => {
        const points = [new THREE.Vector3(x1, y1, z1), new THREE.Vector3(x2, y2, z2)];
        const lineGeometry = new THREE.BufferGeometry().setFromPoints(points);
        return (
          <primitive
            key={`ray-${idx}`}
            object={
              new THREE.Line(
                lineGeometry,
                new THREE.LineBasicMaterial({
                  color: idx % 4 === 0 ? '#d97706' : idx % 4 === 2 ? '#38bdf8' : '#1e293b',
                  transparent: true,
                  opacity: idx % 4 === 0 ? 0.28 : 0.1,
                })
              )
            }
          />
        );
      })}

      {/* 6. Subtle Perimeter Grid Plane for Horizon Depth */}
      <gridHelper
        args={[120, 60, '#1e293b', '#0d1524']}
        position={[0, 0.002, 0]}
      />

      {/* 7. Quantum Dust Atmospheric Particulate Field */}
      <QuantumDustParticles isReducedMotion={isReducedMotion} />

      {/* 8. Floating Obsidian Island Fragments in Atmosphere */}
      <FloatingObsidianIslands isReducedMotion={isReducedMotion} />

      {/* 9. Distant Gothic/Cybernetic Towers */}
      <DistantAryaTowers />
    </>
  );
};
