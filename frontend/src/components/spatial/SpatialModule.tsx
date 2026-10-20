import React, { useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { SpatialModuleData, SpatialModuleId } from '../../types/spatialModules';

interface SpatialModuleProps {
  module: SpatialModuleData;
  isSelected: boolean;
  isHovered: boolean;
  onSelect: (id: SpatialModuleId) => void;
  onPointerOver: () => void;
  onPointerOut: () => void;
  isReducedMotion: boolean;
}

export const SpatialModule: React.FC<SpatialModuleProps> = ({
  module,
  isSelected,
  isHovered,
  onSelect,
  onPointerOver,
  onPointerOut,
  isReducedMotion,
}) => {
  const groupRef = useRef<THREE.Group>(null);
  const ringRef = useRef<THREE.Mesh>(null);
  const coreRef = useRef<THREE.Mesh>(null);

  // Materials
  const graphiteArmor = React.useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(isSelected ? '#1e293b' : isHovered ? '#1a2234' : '#0f172a'),
        metalness: 0.92,
        roughness: 0.22,
      }),
    [isSelected, isHovered]
  );

  const gunmetalStrut = React.useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color('#334155'),
        metalness: 0.88,
        roughness: 0.35,
      }),
    []
  );

  const amberEnergy = React.useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color('#f59e0b'),
        emissive: new THREE.Color('#f59e0b'),
        emissiveIntensity: isSelected ? 3.5 : isHovered ? 2.8 : 1.8,
        toneMapped: false,
      }),
    [isSelected, isHovered]
  );

  const highlightBorder = React.useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(isSelected ? '#fbbf24' : '#f59e0b'),
        wireframe: true,
        transparent: true,
        opacity: isSelected ? 0.85 : isHovered ? 0.6 : 0.2,
      }),
    [isSelected, isHovered]
  );

  useFrame((state, delta) => {
    if (isReducedMotion || !groupRef.current) return;
    const time = state.clock.getElapsedTime();

    // Idle subtle vertical float
    const offset = module.id === 'memory' ? 0 : module.id === 'planning' ? 1.5 : module.id === 'routing' ? 3.0 : 4.5;
    groupRef.current.position.y = module.position[1] + Math.sin(time * 1.4 + offset) * 0.05;

    // Subsystem rotating parts
    if (ringRef.current) {
      ringRef.current.rotation.y += delta * (isSelected ? 0.45 : 0.18);
    }
    if (coreRef.current) {
      coreRef.current.rotation.x += delta * 0.12;
      coreRef.current.rotation.z += delta * 0.15;
    }
  });

  return (
    <group
      ref={groupRef}
      position={module.position}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(module.id);
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        onPointerOver();
      }}
      onPointerOut={(e) => {
        e.stopPropagation();
        onPointerOut();
      }}
      name={`SpatialModule_${module.id}`}
    >
      {/* Base Stepped Octagonal Plinth */}
      <mesh position={[0, -0.4, 0]} material={graphiteArmor}>
        <cylinderGeometry args={[0.55, 0.65, 0.14, 8]} />
      </mesh>
      <mesh position={[0, -0.3, 0]} material={gunmetalStrut}>
        <cylinderGeometry args={[0.48, 0.52, 0.08, 8]} />
      </mesh>

      {/* Unique Procedural Subsystem Architecture */}
      {module.id === 'memory' && (
        /* MEMORY: Stacked Holographic Data Cubes & Context Layers */
        <group position={[0, 0, 0]}>
          {/* Main Data Storage Cube */}
          <mesh position={[0, 0.05, 0]} material={graphiteArmor}>
            <boxGeometry args={[0.52, 0.52, 0.52]} />
          </mesh>
          {/* Upper Secondary Offset Cube */}
          <mesh position={[-0.15, 0.32, 0.15]} material={gunmetalStrut}>
            <boxGeometry args={[0.26, 0.26, 0.26]} />
          </mesh>
          {/* Internal Glowing Amber Conduits */}
          <mesh ref={coreRef} position={[0, 0.05, 0]} material={amberEnergy}>
            <boxGeometry args={[0.54, 0.04, 0.54]} />
          </mesh>
          {/* Hovering Holographic Memory Planes */}
          {[-0.32, 0, 0.32].map((offset, idx) => (
            <mesh key={`holo-plane-${idx}`} position={[offset, 0.42 + idx * 0.08, -0.2 + idx * 0.1]} rotation={[0.1, idx * 0.4, 0]}>
              <planeGeometry args={[0.28, 0.18]} />
              <meshBasicMaterial color="#38bdf8" transparent opacity={0.45} side={THREE.DoubleSide} />
            </mesh>
          ))}
          {/* Rotating Data Calibration Ring */}
          <mesh ref={ringRef} position={[0, 0.05, 0]} rotation={[Math.PI / 6, 0, 0]} material={gunmetalStrut}>
            <torusGeometry args={[0.58, 0.016, 8, 32]} />
          </mesh>
        </group>
      )}

      {module.id === 'planning' && (
        /* PLANNING: Tiered Circular Dais & Procedural Workflow Structure */
        <group position={[0, 0, 0]}>
          {/* Tiered Circular Platform 1 */}
          <mesh position={[0, -0.1, 0]} material={graphiteArmor}>
            <cylinderGeometry args={[0.48, 0.54, 0.12, 16]} />
          </mesh>
          {/* Tiered Circular Platform 2 */}
          <mesh position={[0, 0.06, 0]} material={gunmetalStrut}>
            <cylinderGeometry args={[0.36, 0.42, 0.1, 16]} />
          </mesh>
          {/* Central Pulsing Decision Octahedron */}
          <mesh ref={coreRef} position={[0, 0.26, 0]} material={amberEnergy}>
            <octahedronGeometry args={[0.22, 0]} />
          </mesh>
          {/* 4 Connected Workflow Node Anchors */}
          {[-0.32, 0.32].map((x) =>
            [-0.32, 0.32].map((z) => (
              <mesh key={`plan-node-${x}-${z}`} position={[x, 0.06, z]} material={graphiteArmor}>
                <sphereGeometry args={[0.06, 8, 8]} />
              </mesh>
            ))
          )}
          {/* Rotating Planning Gimbal Ring */}
          <mesh ref={ringRef} position={[0, 0.26, 0]} material={gunmetalStrut}>
            <torusGeometry args={[0.48, 0.015, 8, 32]} />
          </mesh>
        </group>
      )}

      {module.id === 'routing' && (
        /* ROUTING: Celestial Provider Constellation Cage */
        <group position={[0, 0, 0]}>
          {/* Central Router Core Sphere */}
          <mesh ref={coreRef} position={[0, 0.1, 0]} material={amberEnergy}>
            <sphereGeometry args={[0.2, 16, 16]} />
          </mesh>
          {/* Geodesic Constellation Cage */}
          <mesh position={[0, 0.1, 0]} material={gunmetalStrut}>
            <icosahedronGeometry args={[0.45, 1]} />
          </mesh>
          {/* Orbiting Provider Nodes (OpenAI, Kling, Runway, Flux, Fal, Stability) */}
          {[0, 1, 2, 3, 4, 5].map((idx) => {
            const angle = (idx / 6) * Math.PI * 2;
            const radius = 0.58;
            const x = Math.cos(angle) * radius;
            const z = Math.sin(angle) * radius;
            const y = Math.sin(idx * 2) * 0.14 + 0.1;
            return (
              <group key={`prov-node-${idx}`} position={[x, y, z]}>
                <mesh material={graphiteArmor}>
                  <sphereGeometry args={[0.06, 8, 8]} />
                </mesh>
                <mesh material={amberEnergy}>
                  <sphereGeometry args={[0.03, 6, 6]} />
                </mesh>
              </group>
            );
          })}
          {/* Rotating Routing Calibrator Ring */}
          <mesh ref={ringRef} position={[0, 0.1, 0]} rotation={[Math.PI / 3, 0, 0]} material={gunmetalStrut}>
            <torusGeometry args={[0.62, 0.015, 8, 32]} />
          </mesh>
        </group>
      )}

      {module.id === 'analytics' && (
        /* ANALYTICS: Holographic Data Prism & Telemetry Matrix */
        <group position={[0, 0, 0]}>
          {/* Base Octagonal Plinth */}
          <mesh position={[0, -0.05, 0]} material={graphiteArmor}>
            <cylinderGeometry args={[0.42, 0.48, 0.14, 8]} />
          </mesh>
          {/* Floating Telemetry Crystal Prism */}
          <mesh ref={coreRef} position={[0, 0.22, 0]} rotation={[0.2, 0.4, 0]}>
            <octahedronGeometry args={[0.28, 0]} />
            <meshStandardMaterial
              color="#0284c7"
              emissive="#38bdf8"
              emissiveIntensity={1.8}
              roughness={0.1}
              metalness={0.9}
              transparent
              opacity={0.85}
            />
          </mesh>
          {/* Orbiting Metric Bar Rings */}
          <mesh ref={ringRef} position={[0, 0.22, 0]} rotation={[-Math.PI / 4, 0, 0]} material={gunmetalStrut}>
            <torusGeometry args={[0.5, 0.014, 8, 32]} />
          </mesh>
          {/* Holographic Signal Points */}
          {[-0.2, 0, 0.2].map((x, idx) => (
            <mesh key={`sig-${idx}`} position={[x, 0.52 + idx * 0.06, 0]}>
              <boxGeometry args={[0.04, 0.12 + idx * 0.08, 0.02]} />
              <meshBasicMaterial color="#38bdf8" transparent opacity={0.7} />
            </mesh>
          ))}
        </group>
      )}

      {module.id === 'job_package' && (
        /* JOB PACKAGE: Ornate Cybernetic Payload Cube & Boundary Seal */
        <group position={[0, 0, 0]}>
          {/* Main Sealed Cube */}
          <mesh position={[0, 0.12, 0]} material={graphiteArmor}>
            <boxGeometry args={[0.46, 0.46, 0.46]} />
          </mesh>
          {/* Cybernetic Bevel Brackets */}
          <mesh position={[0, 0.12, 0]} material={gunmetalStrut}>
            <boxGeometry args={[0.48, 0.48, 0.08]} />
          </mesh>
          <mesh position={[0, 0.12, 0]} material={gunmetalStrut}>
            <boxGeometry args={[0.08, 0.48, 0.48]} />
          </mesh>
          {/* Center Amber Inspection Window */}
          <mesh ref={coreRef} position={[0, 0.12, 0]} material={amberEnergy}>
            <boxGeometry args={[0.24, 0.24, 0.49]} />
          </mesh>
          {/* Outer Rotating Contract Seal Ring */}
          <mesh ref={ringRef} position={[0, 0.12, 0]} rotation={[0, Math.PI / 4, 0]} material={gunmetalStrut}>
            <torusGeometry args={[0.54, 0.016, 8, 32]} />
          </mesh>
        </group>
      )}

      {module.id === 'execution' && (
        /* EXECUTION: Heavy Synthesis Chamber & Power Vanes */
        <group position={[0, 0, 0]}>
          {/* Heavy Gunmetal Housing */}
          <mesh position={[0, 0, 0]} material={graphiteArmor}>
            <boxGeometry args={[0.52, 0.44, 0.52]} />
          </mesh>
          {/* 4 Vertical Heat/Power Vanes */}
          {([-0.28, 0.28] as const).map((x) =>
            ([-0.28, 0.28] as const).map((z) => (
              <mesh key={`exec-vane-${x}-${z}`} position={[x, 0.04, z]} material={gunmetalStrut}>
                <boxGeometry args={[0.06, 0.56, 0.06]} />
              </mesh>
            ))
          )}
          {/* Central Reactor Core Glow */}
          <mesh ref={coreRef} position={[0, 0.04, 0]} material={amberEnergy}>
            <sphereGeometry args={[0.22, 16, 16]} />
          </mesh>
          {/* Forward Corridor Power Coupler */}
          <mesh position={[0, -0.06, 0.34]} rotation={[Math.PI / 2, 0, 0]} material={gunmetalStrut}>
            <cylinderGeometry args={[0.1, 0.14, 0.2, 8]} />
          </mesh>
          {/* High-speed Accelerator Ring */}
          <mesh ref={ringRef} position={[0, 0.04, 0]} rotation={[0, 0, Math.PI / 4]} material={gunmetalStrut}>
            <torusGeometry args={[0.52, 0.02, 8, 32]} />
          </mesh>
        </group>
      )}

      {/* Selected / Hover Reticle Bracket */}
      {(isSelected || isHovered) && (
        <mesh position={[0, 0.05, 0]} material={highlightBorder}>
          <boxGeometry args={[1.3, 1.2, 1.3]} />
        </mesh>
      )}
    </group>
  );
};
