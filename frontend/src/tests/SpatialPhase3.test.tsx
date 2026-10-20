import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { CAMERA_WAYPOINTS } from '../types/spatial';
import { DEFAULT_SPATIAL_MODULES, SpatialModuleData } from '../types/spatialModules';
import { createDefaultProject } from '../utils/continuityEngine';
import { Project } from '../types/productionTimeline';
import { App } from '../App';

describe('AryaOS V1 Phase 3 — Spatial System Modules & Multi-Shot Corridor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('1. Spatial System Modules (Part A)', () => {
    it('1. System modules render safely in JSDOM fallback', () => {
      render(<SpatialWorld />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-system-modules-fallback')).toBeInTheDocument();
    });

    it('2. All four modules (MEMORY, PLANNING, ROUTING, EXECUTION) are represented', () => {
      render(<SpatialWorld />);
      expect(screen.getByTestId('spatial-module-memory')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-module-planning')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-module-routing')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-module-execution')).toBeInTheDocument();

      // Check module titles
      expect(screen.getByText('MEMORY')).toBeInTheDocument();
      expect(screen.getByText('PLANNING')).toBeInTheDocument();
      expect(screen.getByText('ROUTING')).toBeInTheDocument();
      expect(screen.getByText('EXECUTION')).toBeInTheDocument();
    });

    it('3. Module selection works and updates HUD telemetry', () => {
      render(<SpatialWorld />);

      // Select MEMORY module
      const memoryBtn = screen.getByTestId('spatial-module-memory');
      fireEvent.click(memoryBtn);

      const hudModule = screen.getByTestId('hud-selected-module');
      expect(hudModule).toBeInTheDocument();
      expect(screen.getByText(/SUBSYSTEM \/\/ MEMORY/i)).toBeInTheDocument();
      expect(screen.getAllByText(/MOD-01/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/EPISODIC ARCHIVE & RETRIEVAL/i)).toBeInTheDocument();

      // Select EXECUTION module
      const execBtn = screen.getByTestId('spatial-module-execution');
      fireEvent.click(execBtn);

      expect(screen.getByText(/SUBSYSTEM \/\/ EXECUTION/i)).toBeInTheDocument();
      expect(screen.getAllByText(/MOD-04/i).length).toBeGreaterThanOrEqual(1);
    });

    it('4. Module state changes render correctly with custom telemetry', () => {
      const customModules: SpatialModuleData[] = [
        {
          ...DEFAULT_SPATIAL_MODULES[0],
          telemetry: {
            status: 'PROCESSING',
            loadPercent: 99,
            throughput: '9.9 GB/s',
            latencyMs: 1,
            activeItemsCount: 512,
            detail: 'High-throughput memory burst active',
          },
        },
        DEFAULT_SPATIAL_MODULES[1],
        DEFAULT_SPATIAL_MODULES[2],
        DEFAULT_SPATIAL_MODULES[3],
      ];

      render(<SpatialWorld modules={customModules} selectedModuleId="memory" />);

      expect(screen.getAllByText(/LOAD: 99%/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/STATUS: PROCESSING/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/High-throughput memory burst active/i)).toBeInTheDocument();
    });
  });

  describe('2. Multi-Shot Spatial Corridor (Part B)', () => {
    it('5. Shot corridor renders safely with empty project state', () => {
      const defaultProj = createDefaultProject(null);
      const emptyProject: Project = {
        ...defaultProj,
        sequences: [
          {
            ...defaultProj.sequences[0],
            shots: [],
            totalShots: 0,
          },
        ],
      };

      render(<SpatialWorld project={emptyProject} />);

      expect(screen.getByTestId('spatial-corridor-empty')).toBeInTheDocument();
      expect(screen.getByText(/CORRIDOR STANDBY \/\/ NO ACTIVE PRODUCTION SHOTS/i)).toBeInTheDocument();
    });

    it('6. Shot corridor renders multiple production shots', () => {
      render(<SpatialWorld />);

      expect(screen.getByTestId('spatial-shot-corridor')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-01')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-02')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-03')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-04')).toBeInTheDocument();
    });

    it('7. Shot selection works and surfaces shot details in HUD', () => {
      render(<SpatialWorld />);

      const shot2Btn = screen.getByTestId('spatial-shot-shot-02');
      fireEvent.click(shot2Btn);

      const hudShot = screen.getByTestId('hud-selected-shot');
      expect(hudShot).toBeInTheDocument();
      expect(screen.getByText(/CORRIDOR SHOT \/\/ 02/i)).toBeInTheDocument();
      expect(screen.getByText(/Orbital Core Approach/i)).toBeInTheDocument();
    });

    it('8. Predecessor and continuity connections render between shots', () => {
      render(<SpatialWorld />);

      expect(screen.getByTestId('spatial-continuity-link-shot-01-shot-02')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-continuity-link-shot-02-shot-03')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-continuity-link-shot-03-shot-04')).toBeInTheDocument();
    });
  });

  describe('3. Camera Architecture, Stations & Accessibility', () => {
    it('9. Camera station transitions work across all 6 stations', () => {
      const handleSelectState = vi.fn();
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          onSelectCameraState={handleSelectState}
        />
      );

      // Verify all 6 waypoint buttons exist
      expect(screen.getByTitle('Switch to ENTRY viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to APPROACH viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to HUB viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to SYSTEMS viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to CORRIDOR viewpoint')).toBeInTheDocument();
      expect(screen.getByTitle('Switch to COMMAND viewpoint')).toBeInTheDocument();

      // Trigger station clicks
      fireEvent.click(screen.getByTitle('Switch to SYSTEMS viewpoint'));
      expect(handleSelectState).toHaveBeenCalledWith('SYSTEMS');

      fireEvent.click(screen.getByTitle('Switch to CORRIDOR viewpoint'));
      expect(handleSelectState).toHaveBeenCalledWith('CORRIDOR');

      fireEvent.click(screen.getByTitle('Switch to COMMAND viewpoint'));
      expect(handleSelectState).toHaveBeenCalledWith('COMMAND');
    });

    it('10. Reduced-motion mode remains safe without errors', () => {
      // Mock reduced motion
      const originalMatchMedia = window.matchMedia;
      window.matchMedia = vi.fn().mockImplementation((query) => ({
        matches: query.includes('prefers-reduced-motion'),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));

      render(<SpatialWorld />);
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();

      window.matchMedia = originalMatchMedia;
    });

    it('11. Existing Creator Studio navigation remains intact', async () => {
      render(<App initialView="spatial" />);

      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();

      const enterStudioBtn = screen.getByRole('button', { name: /ENTER CREATOR STUDIO/i });
      await act(async () => {
        fireEvent.click(enterStudioBtn);
      });

      // Returns to Creator Studio
      expect(screen.getByText('CONTROL CONSOLE')).toBeInTheDocument();

      // Navigate back to Spatial Core
      const spatialNavBtn = screen.getByRole('button', { name: /Spatial Core/i });
      await act(async () => {
        fireEvent.click(spatialNavBtn);
      });

      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
    });

    it('12. Spatial fallback remains completely safe in JSDOM', () => {
      render(<SpatialWorld initialCameraState="SYSTEMS" />);

      const fallback = screen.getByTestId('spatial-world-fallback');
      expect(fallback).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS \/\/ CORE SIMULATION ACTIVE \[SYSTEMS\]/i)).toBeInTheDocument();

      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'SYSTEMS');
    });
  });
});
