import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { CAMERA_WAYPOINTS } from '../components/spatial/SpatialCameraRig';
import { App } from '../App';

describe('AryaOS V1 Phase 1 — Spatial World & Cinematic Interface', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('1. SpatialWorld Fallback & Headless Safety', () => {
    it('renders gracefully in JSDOM / headless environments without crashing', () => {
      render(<SpatialWorld />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-world-fallback')).toBeInTheDocument();
    });

    it('initializes with default HUB camera state', () => {
      render(<SpatialWorld />);
      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'HUB');
    });

    it('respects initialCameraState prop', () => {
      render(<SpatialWorld initialCameraState="ENTRY" />);
      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'ENTRY');
    });
  });

  describe('2. SpatialHudOverlay & Technical Telemetry', () => {
    it('renders core branding, telemetry and status indicators', () => {
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          onSelectCameraState={vi.fn()}
        />
      );

      expect(screen.getByText(/ARYAOS \/\/ SPATIAL OS/i)).toBeInTheDocument();
      expect(screen.getByText(/CORE V1/i)).toBeInTheDocument();
      expect(screen.getByText(/STATUS: ONLINE/i)).toBeInTheDocument();
      expect(screen.getByText(/SECTOR: 01-ALPHA/i)).toBeInTheDocument();
      expect(screen.getByText(/FREQ: 4.8 THz/i)).toBeInTheDocument();
    });

    it('renders all three camera waypoints', () => {
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          onSelectCameraState={vi.fn()}
        />
      );

      expect(screen.getByTitle('Switch to ENTRY viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to APPROACH viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to HUB viewpoint')).toBeInTheDocument();
    });

    it('calls onSelectCameraState when a waypoint button is clicked', () => {
      const handleSelect = vi.fn();
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          onSelectCameraState={handleSelect}
        />
      );

      fireEvent.click(screen.getByTitle('Switch to ENTRY viewpoint'));
      expect(handleSelect).toHaveBeenCalledWith('ENTRY');

      fireEvent.click(screen.getByTitle('Switch to APPROACH viewpoint'));
      expect(handleSelect).toHaveBeenCalledWith('APPROACH');
    });

    it('displays waypoint coordinate telemetry accurately', () => {
      render(
        <SpatialHudOverlay
          cameraState="APPROACH"
          onSelectCameraState={vi.fn()}
        />
      );

      const approachWp = CAMERA_WAYPOINTS.APPROACH;
      expect(screen.getByText(new RegExp(approachWp.label, 'i'))).toBeInTheDocument();
      expect(screen.getByText(new RegExp(`FOV: ${approachWp.fov}°`, 'i'))).toBeInTheDocument();
    });

    it('renders ENTER CREATOR STUDIO button and handles click', () => {
      const handleOpenStudio = vi.fn();
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          onSelectCameraState={vi.fn()}
          onOpenStudio={handleOpenStudio}
        />
      );

      const enterBtn = screen.getByRole('button', { name: /ENTER CREATOR STUDIO/i });
      expect(enterBtn).toBeInTheDocument();
      fireEvent.click(enterBtn);
      expect(handleOpenStudio).toHaveBeenCalledTimes(1);
    });
  });

  describe('3. Application Integration & Seamless Transition', () => {
    it('allows navigating to Spatial Core via AppNav without affecting Creator Studio', async () => {
      render(<App />);

      // Creator Studio is default view
      expect(screen.getByText('CONTROL CONSOLE')).toBeInTheDocument();

      // Click on Spatial Core in AppNav
      const spatialNavBtn = screen.getByRole('button', { name: /Spatial Core/i });
      expect(spatialNavBtn).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(spatialNavBtn);
      });

      // Spatial World is mounted
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS \/\/ SPATIAL OS/i)).toBeInTheDocument();

      // Click ENTER CREATOR STUDIO inside the Spatial HUD
      const enterStudioBtn = screen.getByRole('button', { name: /ENTER CREATOR STUDIO/i });
      await act(async () => {
        fireEvent.click(enterStudioBtn);
      });

      // Returns cleanly to Creator Studio
      expect(screen.getByText('CONTROL CONSOLE')).toBeInTheDocument();
    });

    it('can be mounted directly into spatial view via initialView prop', () => {
      render(<App initialView="spatial" />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS \/\/ SPATIAL OS/i)).toBeInTheDocument();
    });
  });
});
