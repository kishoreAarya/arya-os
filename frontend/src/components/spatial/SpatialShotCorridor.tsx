import React, { useState, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { SpatialShotCardData } from '../../types/spatialModules';

interface SpatialShotCorridorProps {
  shots: SpatialShotCardData[];
  selectedShotId?: string;
  onSelectShot?: (shotId: string) => void;
  isReducedMotion?: boolean;
  executionModulePosition?: [number, number, number];
}

/**
 * Calculates curved corridor position for each production shot
 */
export function getShotCorridorPosition(index: number, total: number): [number, number, number] {
  const clampedTotal = Math.max(1, total);
  const spacing = 2.2;
  const x = (index - (clampedTotal - 1) / 2) * spacing;
  const z = 4.0 + Math.abs(index - (clampedTotal - 1) / 2) * 0.28;
  const y = 1.05;
  return [x, y, z];
}

/**
 * Procedural Continuity Link connecting adjacent or dependent shots
 */
const ContinuityLinkBeam: React.FC<{
  from: [number, number, number];
  to: [number, number, number];
  status?: string;
  isReducedMotion: boolean;
}> = ({ from, to, status = 'PASS', isReducedMotion }) => {
  const pulseRef = useRef<THREE.Mesh>(null);

  const beamColor = useMemo(() => {
    switch (status) {
      case 'PASS':
        return '#38bdf8';
      case 'WARNING':
        return '#f59e0b';
      case 'BLOCKED':
        return '#ef4444';
      default:
        return '#64748b';
    }
  }, [status]);

  const points = useMemo(() => {
    return [
      new THREE.Vector3(from[0] + 0.8, from[1] - 0.35, from[2]),
      new THREE.Vector3(to[0] - 0.8, to[1] - 0.35, to[2]),
    ];
  }, [from, to]);

  const lineGeometry = useMemo(() => {
    return new THREE.BufferGeometry().setFromPoints(points);
  }, [points]);

  const lineMaterial = useMemo(() => {
    return new THREE.LineBasicMaterial({
      color: new THREE.Color(beamColor),
      transparent: true,
      opacity: status === 'PASS' ? 0.75 : 0.9,
    });
  }, [beamColor, status]);

  const lineObject = useMemo(() => {
    return new THREE.Line(lineGeometry, lineMaterial);
  }, [lineGeometry, lineMaterial]);

  useFrame((state) => {
    if (isReducedMotion || !pulseRef.current) return;
    const t = (state.clock.getElapsedTime() * 0.8) % 1;
    pulseRef.current.position.set(
      points[0].x + (points[1].x - points[0].x) * t,
      points[0].y + (points[1].y - points[0].y) * t,
      points[0].z + (points[1].z - points[0].z) * t
    );
  });

  return (
    <group name="ContinuityLinkGroup">
      <primitive object={lineObject} />
      <mesh ref={pulseRef}>
        <sphereGeometry args={[0.025, 6, 6]} />
        <meshBasicMaterial color={new THREE.Color(beamColor)} />
      </mesh>
    </group>
  );
};

/**
 * Execution Feed Conduit connecting the Execution module to the Shot Corridor
 */
const ExecutionCorridorConduit: React.FC<{
  from: [number, number, number];
  to: [number, number, number];
  isReducedMotion: boolean;
}> = ({ from, to, isReducedMotion }) => {
  const pulseRef = useRef<THREE.Mesh>(null);

  const points = useMemo(() => {
    // Intermediate waypoint routing around core
    const midPoint = new THREE.Vector3(
      from[0] * 0.7 + to[0] * 0.3,
      0.9,
      from[2] * 0.4 + to[2] * 0.6
    );
    return [new THREE.Vector3(...from), midPoint, new THREE.Vector3(...to)];
  }, [from, to]);

  const curve = useMemo(() => {
    return new THREE.CatmullRomCurve3(points);
  }, [points]);

  const lineGeometry = useMemo(() => {
    const curvePoints = curve.getPoints(24);
    return new THREE.BufferGeometry().setFromPoints(curvePoints);
  }, [curve]);

  const lineMaterial = useMemo(() => {
    return new THREE.LineBasicMaterial({
      color: new THREE.Color('#f59e0b'),
      transparent: true,
      opacity: 0.65,
    });
  }, []);

  const lineObject = useMemo(() => {
    return new THREE.Line(lineGeometry, lineMaterial);
  }, [lineGeometry, lineMaterial]);

  useFrame((state) => {
    if (isReducedMotion || !pulseRef.current) return;
    const t = (state.clock.getElapsedTime() * 0.7) % 1;
    const pos = curve.getPoint(t);
    pulseRef.current.position.copy(pos);
  });

  return (
    <group name="ExecutionCorridorConduitGroup">
      <primitive object={lineObject} />
      <mesh ref={pulseRef}>
        <sphereGeometry args={[0.04, 8, 8]} />
        <meshBasicMaterial color={new THREE.Color('#fbbf24')} />
      </mesh>
    </group>
  );
};

/**
 * Single 3D Floating Cinematic Shot Card
 */
const SpatialShotCard: React.FC<{
  shot: SpatialShotCardData;
  position: [number, number, number];
  isSelected: boolean;
  isHovered: boolean;
  onSelect: (id: string) => void;
  onPointerOver: () => void;
  onPointerOut: () => void;
  isReducedMotion: boolean;
}> = ({
  shot,
  position,
  isSelected,
  isHovered,
  onSelect,
  onPointerOver,
  onPointerOut,
  isReducedMotion,
}) => {
  const cardRef = useRef<THREE.Group>(null);

  const statusColor = useMemo(() => {
    switch (shot.status) {
      case 'COMPLETE':
        return '#10b981';
      case 'GENERATING':
      case 'QUEUED':
        return '#f59e0b';
      case 'FAILED':
      case 'RECOVERY_REQUIRED':
        return '#ef4444';
      case 'READY':
        return '#38bdf8';
      default:
        return '#64748b';
    }
  }, [shot.status]);

  useFrame((state) => {
    if (isReducedMotion || !cardRef.current) return;
    const time = state.clock.getElapsedTime();
    // Gentle floating cadence
    cardRef.current.position.y = position[1] + Math.sin(time * 1.5 + shot.order) * 0.03;
  });

  return (
    <group
      ref={cardRef}
      position={position}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(shot.id);
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        onPointerOver();
      }}
      onPointerOut={(e) => {
        e.stopPropagation();
        onPointerOut();
      }}
      name={`SpatialShot_${shot.id}`}
    >
      {/* Outer Obsidian Bezel */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[1.72, 1.12, 0.06]} />
        <meshStandardMaterial
          color={new THREE.Color(isSelected ? '#1e293b' : isHovered ? '#162032' : '#090d16')}
          metalness={0.92}
          roughness={0.24}
        />
      </mesh>

      {/* Screen Display Face */}
      <mesh position={[0, 0, 0.035]}>
        <planeGeometry args={[1.6, 1.0]} />
        <meshStandardMaterial
          color={new THREE.Color('#030712')}
          emissive={new THREE.Color(statusColor)}
          emissiveIntensity={isSelected ? 0.35 : isHovered ? 0.22 : 0.08}
          metalness={0.5}
          roughness={0.5}
        />
      </mesh>

      {/* Top Status LED Indicator */}
      <mesh position={[0.7, 0.42, 0.045]}>
        <sphereGeometry args={[0.035, 8, 8]} />
        <meshBasicMaterial color={new THREE.Color(statusColor)} />
      </mesh>

      {/* Video Indicator Badge for Temporal/Video Shots */}
      {(shot.generationType === 'video' || shot.generationType === 'image_to_video' || (shot.duration && shot.duration > 0)) && (
        <group position={[-0.55, 0.42, 0.045]}>
          <mesh>
            <boxGeometry args={[0.32, 0.08, 0.01]} />
            <meshBasicMaterial color={new THREE.Color('#38bdf8')} />
          </mesh>
        </group>
      )}

      {/* Dependency State Indicator Pill */}
      {shot.dependencyState && shot.dependencyState !== 'INDEPENDENT' && (
        <group position={[-0.15, 0.42, 0.045]}>
          <mesh>
            <boxGeometry args={[0.36, 0.06, 0.01]} />
            <meshBasicMaterial
              color={
                new THREE.Color(
                  shot.dependencyState === 'READY' || shot.dependencyState.includes('PASS')
                    ? '#10b981'
                    : shot.dependencyState === 'WAITING_FOR_PREDECESSOR'
                    ? '#f59e0b'
                    : shot.dependencyState.includes('BLOCKED')
                    ? '#ef4444'
                    : '#64748b'
                )
              }
            />
          </mesh>
        </group>
      )}

      {/* Frame Anchor Indicator - Last Frame Available */}
      {(shot.lastFrame || (shot.frameAnchors && shot.frameAnchors.last_frame)) && (
        <group position={[0.45, 0.42, 0.045]}>
          <mesh>
            <boxGeometry args={[0.18, 0.06, 0.01]} />
            <meshBasicMaterial color={new THREE.Color('#10b981')} />
          </mesh>
        </group>
      )}

      {/* Selected / Focus Highlight Reticle */}
      {(isSelected || isHovered) && (
        <mesh position={[0, 0, 0.04]}>
          <boxGeometry args={[1.78, 1.18, 0.02]} />
          <meshBasicMaterial
            color={new THREE.Color(isSelected ? '#fbbf24' : '#f59e0b')}
            wireframe
            transparent
            opacity={isSelected ? 0.9 : 0.5}
          />
        </mesh>
      )}

      {/* Bottom Continuity Indicator Tab */}
      <mesh position={[0, -0.48, 0.04]}>
        <boxGeometry args={[0.42, 0.04, 0.02]} />
        <meshBasicMaterial
          color={
            new THREE.Color(
              shot.continuityStatus === 'PASS'
                ? '#38bdf8'
                : shot.continuityStatus === 'WARNING'
                ? '#f59e0b'
                : '#ef4444'
            )
          }
        />
      </mesh>
    </group>
  );
};

export const SpatialShotCorridor: React.FC<SpatialShotCorridorProps> = ({
  shots = [],
  selectedShotId,
  onSelectShot,
  isReducedMotion = false,
  executionModulePosition = [4.2, 1.4, -3.0],
}) => {
  const [hoveredShotId, setHoveredShotId] = useState<string | null>(null);

  // Fallback Empty State: When no shots are configured in the project
  if (shots.length === 0) {
    return (
      <group position={[0, 1.05, 4.0]} name="SpatialShotCorridorEmpty">
        <mesh>
          <boxGeometry args={[2.0, 1.1, 0.04]} />
          <meshBasicMaterial color="#334155" wireframe transparent opacity={0.3} />
        </mesh>
      </group>
    );
  }

  const firstShotPos = getShotCorridorPosition(0, shots.length);

  return (
    <group name="SpatialShotCorridorGroup">
      {/* Dynamic Conduit from Execution Module to First Shot of Corridor */}
      <ExecutionCorridorConduit
        from={executionModulePosition}
        to={firstShotPos}
        isReducedMotion={isReducedMotion}
      />

      {/* Continuity Links Between Adjacent Sequence Shots */}
      {shots.map((shot, idx) => {
        if (idx === 0) return null;
        const prevPos = getShotCorridorPosition(idx - 1, shots.length);
        const currPos = getShotCorridorPosition(idx, shots.length);
        return (
          <ContinuityLinkBeam
            key={`continuity-${shots[idx - 1].id}-${shot.id}`}
            from={prevPos}
            to={currPos}
            status={shot.continuityStatus}
            isReducedMotion={isReducedMotion}
          />
        );
      })}

      {/* 3D Cinematic Floating Shot Cards */}
      {shots.map((shot, idx) => {
        const pos = getShotCorridorPosition(idx, shots.length);
        return (
          <SpatialShotCard
            key={shot.id}
            shot={shot}
            position={pos}
            isSelected={selectedShotId === shot.id}
            isHovered={hoveredShotId === shot.id}
            onSelect={(id) => onSelectShot?.(id)}
            onPointerOver={() => setHoveredShotId(shot.id)}
            onPointerOut={() => setHoveredShotId(null)}
            isReducedMotion={isReducedMotion}
          />
        );
      })}
    </group>
  );
};
