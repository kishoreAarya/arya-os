import React, { useRef, useMemo, useState, useEffect } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame } from '@react-three/fiber';
import { Cpu, Radio, Sparkles } from 'lucide-react';
import { CommandCoreProps, CommandCoreState } from './commandCoreTypes';
import { usePrefersReducedMotion } from '../motion/MotionSystem';
import './CommandCore.css';

/**
 * Check if WebGL is available (prevents crashes in JSDOM / headless test environments)
 */
function checkWebGLSupport(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

/**
 * Stage 3 Semantic Color Palette for Command States
 * Cool blue / steel / neutral for normal operations. Red strictly reserved for error.
 */
const STATE_COLORS: Record<CommandCoreState, { primary: string; secondary: string; hex: number }> = {
  idle: { primary: '#94a3b8', secondary: 'rgba(148, 163, 184, 0.15)', hex: 0x94a3b8 },
  configuring: { primary: '#818cf8', secondary: 'rgba(129, 140, 248, 0.2)', hex: 0x818cf8 },
  ready: { primary: '#38bdf8', secondary: 'rgba(56, 189, 248, 0.28)', hex: 0x38bdf8 },
  generating: { primary: '#3b82f6', secondary: 'rgba(59, 130, 246, 0.38)', hex: 0x3b82f6 },
  processing: { primary: '#60a5fa', secondary: 'rgba(96, 165, 250, 0.38)', hex: 0x60a5fa },
  complete: { primary: '#34d399', secondary: 'rgba(52, 211, 153, 0.28)', hex: 0x34d399 },
  error: { primary: '#ef4444', secondary: 'rgba(239, 68, 68, 0.35)', hex: 0xef4444 },
};

/**
 * 3D Layered Command Instrument Scene
 * 7 Visual Depth Layers:
 * 1. Atmospheric outer field
 * 2. Outer orbital ring
 * 3. Secondary orbital ring
 * 4. Orbiting particle field
 * 5. Inner energy field
 * 6. Central command nucleus
 * 7. State indicator & focal point
 */
interface CoreSceneProps {
  state: CommandCoreState;
  pointer: { x: number; y: number };
  isHovered: boolean;
  isReducedMotion: boolean;
}

const CoreScene: React.FC<CoreSceneProps> = ({ state, pointer, isHovered, isReducedMotion }) => {
  const groupRef = useRef<THREE.Group>(null);
  const outerFieldRef = useRef<THREE.Mesh>(null);
  const ring1Ref = useRef<THREE.Mesh>(null);
  const ring2Ref = useRef<THREE.Mesh>(null);
  const innerEnergyRef = useRef<THREE.Mesh>(null);
  const particlesRef = useRef<THREE.Points>(null);
  const nucleusOuterRef = useRef<THREE.Mesh>(null);
  const nucleusInnerRef = useRef<THREE.Mesh>(null);

  const colors = STATE_COLORS[state];

  // Particle positions for orbiting energy field (42 particles)
  const particleCount = 42;
  const particlePositions = useMemo(() => {
    const pos = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const angle = (i / particleCount) * Math.PI * 2;
      const radius = 1.70 + (Math.random() - 0.5) * 0.28;
      pos[i * 3] = Math.cos(angle) * radius;
      pos[i * 3 + 1] = Math.sin(angle) * radius;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 0.3;
    }
    return pos;
  }, []);

  useFrame((_, delta) => {
    if (!groupRef.current) return;

    // 1. Subtle pointer parallax interpolation (smooth lerp, restrained physical instrument feel)
    if (!isReducedMotion) {
      groupRef.current.rotation.y = THREE.MathUtils.lerp(
        groupRef.current.rotation.y,
        pointer.x * 0.22,
        0.05
      );
      groupRef.current.rotation.x = THREE.MathUtils.lerp(
        groupRef.current.rotation.x,
        -pointer.y * 0.16,
        0.05
      );
    }

    // Prefers-reduced-motion completely stops rotational loops & pulses
    if (isReducedMotion) return;

    // 2. State-driven rotation velocities (Stage 3.6 calibrated hierarchy)
    let baseSpeed = 0.012; // Standby: meditative, subtle drift
    if (state === 'configuring') baseSpeed = 0.020; // Directional configuration
    if (state === 'ready') baseSpeed = 0.034; // Armed cyan state
    if (state === 'generating') baseSpeed = 0.075; // Active synthesis
    if (state === 'processing') baseSpeed = 0.058; // Pipeline execution
    if (state === 'complete') baseSpeed = 0.012; // Settled confirmation
    if (state === 'error') baseSpeed = 0.005; // Calm, non-seizure restrained pulse

    if (isHovered && state !== 'error') {
      baseSpeed *= 1.25;
    }

    // Layer 1: Atmospheric Outer Field (extremely slow drift)
    if (outerFieldRef.current) {
      outerFieldRef.current.rotation.z += delta * (baseSpeed * 0.25);
    }

    // Layer 2: Outer Primary Orbital Ring
    if (ring1Ref.current) {
      ring1Ref.current.rotation.z += delta * baseSpeed;
      ring1Ref.current.rotation.x += delta * (baseSpeed * 0.3);
    }

    // Layer 3: Secondary Tilted Orbital Ring (counter-rotation)
    if (ring2Ref.current) {
      ring2Ref.current.rotation.z -= delta * (baseSpeed * 1.15);
      ring2Ref.current.rotation.y += delta * (baseSpeed * 0.4);
    }

    // Layer 4: Particle Field
    if (particlesRef.current) {
      particlesRef.current.rotation.z += delta * (baseSpeed * 0.85);
    }

    // Layer 5: Inner Energy Field
    if (innerEnergyRef.current) {
      innerEnergyRef.current.rotation.x -= delta * (baseSpeed * 0.6);
      innerEnergyRef.current.rotation.y += delta * (baseSpeed * 0.7);
    }

    // Layer 6: Central Nucleus breathing & energy pulse
    const now = Date.now();
    if (nucleusOuterRef.current && nucleusInnerRef.current) {
      let scaleBase = 1.0;
      let pulseFreq = 0.003;
      let pulseAmp = 0.04;

      if (state === 'generating' || state === 'processing') {
        scaleBase = 1.12;
        pulseFreq = 0.006;
        pulseAmp = 0.07;
      } else if (state === 'complete') {
        scaleBase = 1.02;
        pulseFreq = 0.002;
        pulseAmp = 0.025;
      } else if (state === 'error') {
        scaleBase = 0.98;
        pulseFreq = 0.004;
        pulseAmp = 0.03;
      }

      const pulse = scaleBase + Math.sin(now * pulseFreq) * pulseAmp;
      nucleusOuterRef.current.scale.set(pulse, pulse, pulse);
      nucleusOuterRef.current.rotation.y += delta * (baseSpeed * 0.5);

      const innerPulse = 1.0 + Math.sin(now * pulseFreq + 0.5) * 0.06;
      nucleusInnerRef.current.scale.set(innerPulse, innerPulse, innerPulse);
    }
  });

  return (
    <group ref={groupRef}>
      {/* Layer 1: Atmospheric Outer Field Boundary */}
      <mesh ref={outerFieldRef}>
        <torusGeometry args={[2.15, 0.007, 6, 48]} />
        <meshBasicMaterial
          color={colors.primary}
          transparent
          opacity={state === 'generating' || state === 'processing' ? 0.35 : 0.16}
        />
      </mesh>

      {/* Layer 2: Outer Primary Orbital Ring (Precision Torus) */}
      <mesh ref={ring1Ref}>
        <torusGeometry args={[1.75, 0.022, 8, 48]} />
        <meshBasicMaterial
          color={colors.primary}
          transparent
          opacity={state === 'error' ? 0.55 : 0.68}
        />
      </mesh>

      {/* Layer 3: Secondary Tilted Orbital Ring */}
      <mesh ref={ring2Ref} rotation={[0.55, 0.3, 0]}>
        <torusGeometry args={[1.25, 0.022, 6, 36]} />
        <meshBasicMaterial
          color={colors.primary}
          transparent
          opacity={0.55}
        />
      </mesh>

      {/* Layer 4: Orbiting Particle Stream */}
      <points ref={particlesRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            count={particleCount}
            array={particlePositions}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.075}
          color={colors.primary}
          transparent
          opacity={state === 'generating' || state === 'processing' ? 0.8 : 0.55}
          sizeAttenuation
        />
      </points>

      {/* Layer 5: Inner Energy Field Cage */}
      <mesh ref={innerEnergyRef} rotation={[0.2, 0.4, 0]}>
        <icosahedronGeometry args={[0.88, 0]} />
        <meshBasicMaterial
          color={colors.primary}
          wireframe
          transparent
          opacity={state === 'generating' || state === 'processing' ? 0.35 : 0.18}
        />
      </mesh>

      {/* Layer 6: Central Command Nucleus (Brain of Creator Studio - Scaled Prominence) */}
      <mesh ref={nucleusOuterRef}>
        <octahedronGeometry args={[0.52, 0]} />
        <meshBasicMaterial
          color={colors.primary}
          wireframe
          transparent
          opacity={state === 'generating' || state === 'processing' ? 0.95 : 0.78}
        />
      </mesh>

      {/* Layer 7: Internal Nucleus Core */}
      <mesh ref={nucleusInnerRef}>
        <sphereGeometry args={[0.26, 14, 14]} />
        <meshBasicMaterial
          color={colors.primary}
          transparent
          opacity={state === 'generating' || state === 'processing' ? 0.7 : 0.42}
        />
      </mesh>
    </group>
  );
};

export const CommandCore: React.FC<CommandCoreProps> = ({
  state,
  generationType,
  modelName,
  onClick,
  className = '',
  style,
}) => {
  const isReducedMotion = usePrefersReducedMotion();
  const [hasWebGL, setHasWebGL] = useState(false);
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    setHasWebGL(checkWebGLSupport());
  }, []);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (isReducedMotion) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = ((e.clientY - rect.top) / rect.height) * 2 - 1;
    setPointer({ x, y });
  };

  const colors = STATE_COLORS[state];

  // Stage 3 Semantic Status Language
  const stateLabels: Record<CommandCoreState, string> = {
    idle: 'STANDBY',
    configuring: 'CONFIGURING',
    ready: 'READY',
    generating: 'SYNTHESIZING',
    processing: 'PROCESSING',
    complete: 'COMPLETE',
    error: 'ERROR',
  };

  return (
    <div
      className={`command-core-card core-card-${state} ${className}`}
      style={style}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        setPointer({ x: 0, y: 0 });
      }}
      onClick={onClick}
      role="region"
      aria-label="AryaOS 3D Command Core"
      data-state={state}
    >
      {/* Header bar of Command Core */}
      <div className="command-core-header">
        <div className="command-core-title">
          <Cpu size={15} color="var(--accent-primary)" />
          <span>Spatial Command Core</span>
        </div>

        <div className={`core-state-badge core-state-${state}`}>
          <span
            className="core-pulse-led"
            style={{
              backgroundColor: colors.primary,
              boxShadow: `0 0 7px ${colors.primary}`,
            }}
          />
          <span data-testid="core-state-label">{stateLabels[state]}</span>
        </div>
      </div>

      {/* 3D Interactive Viewport with Graceful Fallback */}
      <div className="command-core-canvas-wrap">
        {hasWebGL ? (
          <Canvas
            camera={{ position: [0, 0, 5.0], fov: 42 }}
            gl={{
              antialias: false,
              powerPreference: 'low-power',
              alpha: true,
            }}
            dpr={1}
            aria-hidden="true"
          >
            <CoreScene
              state={state}
              pointer={pointer}
              isHovered={isHovered}
              isReducedMotion={isReducedMotion}
            />
          </Canvas>
        ) : (
          /* Graceful CSS 2D Fallback for Non-WebGL environments / tests */
          <div
            aria-hidden="true"
            className="command-core-fallback"
            style={{
              borderColor: colors.primary,
              boxShadow: `0 0 16px ${colors.secondary}`,
            }}
          >
            <div
              className="command-core-fallback-inner"
              style={{
                backgroundColor: colors.secondary,
                borderColor: colors.primary,
              }}
            >
              <Sparkles size={24} color={colors.primary} />
            </div>
          </div>
        )}
      </div>

      {/* Command Core Telemetry Readout */}
      <div className="command-core-telemetry">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          <Radio size={12} color={colors.primary} />
          <span>
            Mode: <strong style={{ color: 'var(--text-primary)', textTransform: 'capitalize' }}>{generationType.replace(/_/g, ' ')}</strong>
          </span>
        </div>

        {modelName && (
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>
            Model: <strong style={{ color: 'var(--text-secondary)' }}>{modelName}</strong>
          </div>
        )}
      </div>
    </div>
  );
};

