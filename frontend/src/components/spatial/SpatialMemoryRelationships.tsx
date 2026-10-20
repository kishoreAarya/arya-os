/**
 * AryaOS V1 — Stage 04: Spatial Memory Relationship Splines
 *
 * Renders lightweight 3D cinematic connection splines between the active vitrine
 * and its semantically related vitrines.
 *
 * Performance budget:
 * - 0 draw calls when unselected (component returns null)
 * - 1 draw call when selected (single combined line geometry)
 * - Zero transmission passes
 */

import React, { useMemo } from 'react';
import * as THREE from 'three';
import { memoryArchiveService } from '../../services/memoryArchiveService';

export interface SpatialMemoryRelationshipsProps {
  selectedMemoryId: string | null;
  vitrines: Array<{
    id: string;
    threejs_transform: {
      position: [number, number, number];
    };
  }>;
  isReducedMotion?: boolean;
}

export const SpatialMemoryRelationships: React.FC<SpatialMemoryRelationshipsProps> = ({
  selectedMemoryId,
  vitrines,
  isReducedMotion = false,
}) => {
  const lineGeometry = useMemo(() => {
    if (!selectedMemoryId || vitrines.length === 0) return null;

    const originVitrineId = memoryArchiveService.getVitrineIdByMemoryId(selectedMemoryId);
    if (!originVitrineId) return null;

    const originVitrine = vitrines.find((v) => v.id === originVitrineId);
    if (!originVitrine) return null;

    const [ox, oy, oz] = originVitrine.threejs_transform.position;
    // Lift connection point to the top/center of the vitrine
    const startPoint = new THREE.Vector3(ox, oy + 0.8, oz);

    const related = memoryArchiveService.getRelatedMemories(selectedMemoryId);
    if (related.length === 0) return null;

    const points: THREE.Vector3[] = [];
    const segmentsPerCurve = isReducedMotion ? 4 : 16;

    related.forEach(({ memory: targetMem }) => {
      const targetVitrineId = memoryArchiveService.getVitrineIdByMemoryId(targetMem.id);
      if (!targetVitrineId) return;

      const targetVitrine = vitrines.find((v) => v.id === targetVitrineId);
      if (!targetVitrine) return;

      const [tx, ty, tz] = targetVitrine.threejs_transform.position;
      const endPoint = new THREE.Vector3(tx, ty + 0.8, tz);

      // Arc midpoint lifted above the floor
      const midPoint = new THREE.Vector3(
        (startPoint.x + endPoint.x) / 2,
        Math.max(startPoint.y, endPoint.y) + 1.2,
        (startPoint.z + endPoint.z) / 2
      );

      const curve = new THREE.QuadraticBezierCurve3(startPoint, midPoint, endPoint);
      const curvePoints = curve.getPoints(segmentsPerCurve);

      // Add line segments
      for (let i = 0; i < curvePoints.length - 1; i++) {
        points.push(curvePoints[i], curvePoints[i + 1]);
      }
    });

    if (points.length === 0) return null;

    const geom = new THREE.BufferGeometry().setFromPoints(points);
    return geom;
  }, [selectedMemoryId, vitrines, isReducedMotion]);

  if (!lineGeometry) return null;

  // Test environment guard for headless JSDOM runs without R3F Canvas
  const isTest =
    typeof (globalThis as any).process !== 'undefined' &&
    (globalThis as any).process.env?.NODE_ENV === 'test';

  if (isTest) {
    return (
      <div
        data-testid="spatial-memory-relationships"
        data-points={lineGeometry.attributes.position.count}
      />
    );
  }

  return (
    <lineSegments geometry={lineGeometry} name="SpatialMemoryRelationshipLines">
      <lineBasicMaterial
        color="#38bdf8"
        transparent
        opacity={0.55}
        linewidth={1}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </lineSegments>
  );
};
