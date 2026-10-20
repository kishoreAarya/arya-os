import React from 'react';
import { AmbientScene } from './AmbientScene';

/**
 * AtmosphericBackground creates the multi-depth cinematic environment
 * behind all workspace controls.
 */
export const AtmosphericBackground: React.FC = () => {
  return (
    <div className="ambient-background-layer" aria-hidden="true">
      {/* 1. Subtle top-centered electric light field */}
      <div className="ambient-light-cone" />

      {/* 2. Micro technical coordinate grid overlay */}
      <div className="ambient-grid-overlay" />

      {/* 3. Three.js minimal ambient particle drift */}
      <AmbientScene />

      {/* 4. Perimeter vignette for focus retention */}
      <div className="ambient-vignette" />
    </div>
  );
};
