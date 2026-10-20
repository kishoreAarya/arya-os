import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { interpolateSpatialProgress, CAMERA_WAYPOINTS } from '../types/spatial';
import { App } from '../App';

describe('AryaOS V1 Phase 2 — Cinematic 3D Asset Pipeline & Hybrid Core', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('1. SpatialWorld Hybrid Core & Fallback Architecture', () => {
    it('gracefully renders in JSDOM/headless environments when GLB is unavailable', () => {
      render(<SpatialWorld customGlbPath="/models/non-existent.glb" />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-world-fallback')).toBeInTheDocument();
    });

    it('mounts SpatialWorld with default expected GLB path', () => {
      render(<SpatialWorld customGlbPath="/models/aryaos-core.glb" />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS \/\/ SPATIAL OS/i)).toBeInTheDocument();
    });

    it('respects initialCameraState when mounting SpatialWorld', () => {
      render(<SpatialWorld initialCameraState="ENTRY" />);
      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'ENTRY');
    });
  });

  describe('2. Scroll Progress & Camera Waypoint Architecture', () => {
    it('interpolates camera position accurately at start (progress = 0.0 -> ENTRY)', () => {
      const coords = interpolateSpatialProgress(0.0);
      expect(coords.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[0]);
      expect(coords.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[1]);
      expect(coords.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[2]);
      expect(coords.fov).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.fov);
    });

    it('interpolates camera position accurately at midpoint (progress = 0.5 -> APPROACH)', () => {
      const coords = interpolateSpatialProgress(0.5);
      expect(coords.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.APPROACH.position[0]);
      expect(coords.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.APPROACH.position[1]);
      expect(coords.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.APPROACH.position[2]);
      expect(coords.fov).toBeCloseTo(CAMERA_WAYPOINTS.APPROACH.fov);
    });

    it('interpolates camera position accurately at hero hub (progress = 1.0 -> HUB)', () => {
      const coords = interpolateSpatialProgress(1.0);
      expect(coords.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[0]);
      expect(coords.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[1]);
      expect(coords.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[2]);
      expect(coords.fov).toBeCloseTo(CAMERA_WAYPOINTS.HUB.fov);
    });

    it('clamps progress safely outside [0, 1] range', () => {
      const underflow = interpolateSpatialProgress(-0.5);
      expect(underflow.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[2]);

      const overflow = interpolateSpatialProgress(1.8);
      expect(overflow.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[2]);
    });
  });

  describe('3. SpatialHudOverlay Phase 2 Enhancements', () => {
    it('renders progress percentage when spatialProgress is provided', () => {
      render(
        <SpatialHudOverlay
          cameraState="APPROACH"
          spatialProgress={0.42}
          onSelectCameraState={vi.fn()}
        />
      );
      expect(screen.getByText(/PROGRESS: 42%/i)).toBeInTheDocument();
    });

    it('preserves all discrete waypoint buttons while spatialProgress is active', () => {
      const handleSelect = vi.fn();
      render(
        <SpatialHudOverlay
          cameraState="APPROACH"
          spatialProgress={0.5}
          onSelectCameraState={handleSelect}
        />
      );

      fireEvent.click(screen.getByTitle('Switch to ENTRY viewpoint'));
      expect(handleSelect).toHaveBeenCalledWith('ENTRY');
    });
  });

  describe('4. SpatialWorld Phase 2 Integration & Navigation', () => {
    it('mounts SpatialWorld with spatialProgress prop safely', () => {
      render(
        <SpatialWorld
          customGlbPath="/models/aryaos-core.glb"
          spatialProgress={0.75}
        />
      );
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-world-fallback')).toBeInTheDocument();
      expect(screen.getByText(/PROGRESS: 75%/i)).toBeInTheDocument();
    });

    it('maintains roundtrip Creator Studio transition without breaking existing application', async () => {
      render(<App initialView="spatial" />);

      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();

      const enterStudioBtn = screen.getByRole('button', { name: /ENTER CREATOR STUDIO/i });
      await act(async () => {
        fireEvent.click(enterStudioBtn);
      });

      // Creator Studio rendered intact
      expect(screen.getByText('CONTROL CONSOLE')).toBeInTheDocument();

      // Return to Spatial Core
      const spatialNavBtn = screen.getByRole('button', { name: /Spatial Core/i });
      await act(async () => {
        fireEvent.click(spatialNavBtn);
      });

      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
    });
  });
});
