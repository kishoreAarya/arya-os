import React, { useState, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { SpatialModuleData, SpatialModuleId, DEFAULT_SPATIAL_MODULES } from '../../types/spatialModules';
import { SpatialStage } from '../../types/spatial';
import { SpatialModule } from './SpatialModule';

interface SpatialSystemModulesProps {
  modules?: SpatialModuleData[];
  selectedModuleId?: SpatialModuleId;
  onSelectModule: (id: SpatialModuleId) => void;
  isReducedMotion?: boolean;
  corePosition?: [number, number, number];
  activeStage?: SpatialStage;
}

/**
 * Procedural Dynamic Energy Conduit connecting Subsystem Modules to Central Core
 */
const CoreConnectionBeam: React.FC<{
  from: [number, number, number];
  to: [number, number, number];
  isActive: boolean;
  isReducedMotion: boolean;
}> = ({ from, to, isActive, isReducedMotion }) => {
  const pulseRef = useRef<THREE.Mesh>(null);

  const points = useMemo(() => {
    return [new THREE.Vector3(...from), new THREE.Vector3(...to)];
  }, [from, to]);

  const lineGeometry = useMemo(() => {
    return new THREE.BufferGeometry().setFromPoints(points);
  }, [points]);

  const lineMaterial = useMemo(() => {
    return new THREE.LineBasicMaterial({
      color: new THREE.Color(isActive ? '#f59e0b' : '#334155'),
      transparent: true,
      opacity: isActive ? 0.85 : 0.28,
    });
  }, [isActive]);

  const lineObject = useMemo(() => {
    return new THREE.Line(lineGeometry, lineMaterial);
  }, [lineGeometry, lineMaterial]);

  useFrame((state) => {
    if (isReducedMotion || !pulseRef.current) return;
    const t = (state.clock.getElapsedTime() * (isActive ? 1.2 : 0.6)) % 1;
    // Lerp pulse position from module to core
    pulseRef.current.position.set(
      from[0] + (to[0] - from[0]) * t,
      from[1] + (to[1] - from[1]) * t,
      from[2] + (to[2] - from[2]) * t
    );
  });

  return (
    <group>
      <primitive object={lineObject} />
      {/* Traveling Energy Pulse Node */}
      <mesh ref={pulseRef}>
        <sphereGeometry args={[isActive ? 0.05 : 0.03, 8, 8]} />
        <meshBasicMaterial
          color={new THREE.Color(isActive ? '#fbbf24' : '#f59e0b')}
          transparent
          opacity={isActive ? 0.9 : 0.4}
        />
      </mesh>
    </group>
  );
};

export const SpatialSystemModules: React.FC<SpatialSystemModulesProps> = ({
  modules = DEFAULT_SPATIAL_MODULES,
  selectedModuleId,
  onSelectModule,
  isReducedMotion = false,
  corePosition = [0, 1.5, 0],
  activeStage,
}) => {
  const [hoveredModuleId, setHoveredModuleId] = useState<SpatialModuleId | null>(null);

  const isStageMatched = (modId: SpatialModuleId) => {
    if (!activeStage) return false;
    if (activeStage === 'MEMORY' && modId === 'memory') return true;
    if (activeStage === 'PLANNING' && modId === 'planning') return true;
    if (activeStage === 'ROUTING' && modId === 'routing') return true;
    if (activeStage === 'COMMAND' && modId === 'job_package') return true;
    if (activeStage === 'EXECUTION' && modId === 'execution') return true;
    return false;
  };

  return (
    <group name="SpatialSystemModulesGroup">
      {/* 6 Radial Energy Conduits Connecting to Core */}
      {modules.map((mod) => (
        <CoreConnectionBeam
          key={`beam-${mod.id}`}
          from={mod.position}
          to={corePosition}
          isActive={selectedModuleId === mod.id || hoveredModuleId === mod.id || isStageMatched(mod.id)}
          isReducedMotion={isReducedMotion}
        />
      ))}

      {/* 6 Procedural Subsystem Modules */}
      {modules.map((mod) => (
        <SpatialModule
          key={mod.id}
          module={mod}
          isSelected={selectedModuleId === mod.id || isStageMatched(mod.id)}
          isHovered={hoveredModuleId === mod.id}
          onSelect={onSelectModule}
          onPointerOver={() => setHoveredModuleId(mod.id)}
          onPointerOut={() => setHoveredModuleId(null)}
          isReducedMotion={isReducedMotion}
        />
      ))}
    </group>
  );
};
