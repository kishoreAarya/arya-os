import React, { useMemo, useRef, useEffect } from 'react';
import { ArrowRight } from 'lucide-react';
import { SpatialStage } from '../../types/spatial';
import { spatialAudio } from '../../utils/spatialAudio';

export interface SpatialAwakeningHeroProps {
  activeStage: SpatialStage;
  spatialProgress?: number;
  isReducedMotion?: boolean;
  onEnterCore?: () => void;
  heroImagePath?: string;
}

const DEFAULT_HERO_IMAGE = '/assets/spatial/awakening-hero.png';

/**
 * Lightweight 2D canvas particulate field simulating drifting atmospheric micro-motes
 * and distant energy sparks hovering in space. Zero external dependencies.
 */
const AwakeningParticulateField: React.FC<{ isReducedMotion?: boolean }> = ({ isReducedMotion }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      ctx = null;
    }
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width = canvas.offsetWidth);
    let height = (canvas.height = canvas.offsetHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = canvas.offsetWidth;
      height = canvas.height = canvas.offsetHeight;
    };
    window.addEventListener('resize', handleResize);

    const particleCount = 28;
    const particles = Array.from({ length: particleCount }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      size: 0.8 + Math.random() * 1.6,
      vx: (Math.random() - 0.5) * 0.12,
      vy: -0.08 - Math.random() * 0.18,
      alpha: 0.15 + Math.random() * 0.35,
      color: Math.random() > 0.4 ? '#fbbf24' : '#f59e0b',
    }));

    if (isReducedMotion) {
      // Draw static particle field once for accessibility
      ctx.clearRect(0, 0, width, height);
      particles.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.fill();
      });
      return () => window.removeEventListener('resize', handleResize);
    }

    const render = () => {
      ctx.clearRect(0, 0, width, height);
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        if (p.y < 0) {
          p.y = height + 5;
          p.x = Math.random() * width;
        }
        if (p.x < 0) p.x = width;
        if (p.x > width) p.x = 0;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.fill();
      }
      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
    };
  }, [isReducedMotion]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="awakening-particles-layer"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
      }}
    />
  );
};

/**
 * SpatialAwakeningHero — Stage 01 Initial Awakening Hero Asset Layer
 * Phase 16: Cinematic Living Spatial Environment
 * - Preserves existing Awakening hero image plate as the cinematic background
 * - Subtle multi-layered atmospheric fog drifts, volumetric haze, and micro-particles
 * - Central active AryaOS amber energy beam with breathing pulse, bloom & rising streamers
 * - Circular platform energy with slow inner ring rotation and outward pulse waves
 * - Slow 20–40s cinematic camera push-in progression
 * - Staged UI entrance choreography with immediate interactivity
 */
export const SpatialAwakeningHero: React.FC<SpatialAwakeningHeroProps> = ({
  activeStage,
  spatialProgress,
  isReducedMotion = false,
  onEnterCore,
  heroImagePath = DEFAULT_HERO_IMAGE,
}) => {
  const isAwakening = activeStage === 'AWAKENING';

  // Compute smooth continuous opacity based on spatialProgress (0.0 -> 0.15)
  const opacity = useMemo(() => {
    if (spatialProgress !== undefined) {
      if (spatialProgress <= 0.01) return 1.0;
      if (spatialProgress >= 0.14) return 0.0;
      // Smooth linear transition between progress 0.01 and 0.14
      return Math.max(0, Math.min(1, 1 - (spatialProgress - 0.01) / 0.13));
    }
    return isAwakening ? 1.0 : 0.0;
  }, [spatialProgress, isAwakening]);

  const isVisible = opacity > 0.005;

  const isTestEnv =
    (typeof (globalThis as any).process !== 'undefined' &&
      (globalThis as any).process?.env?.NODE_ENV === 'test') ||
    typeof (globalThis as any).vi !== 'undefined';

  const handleEnterIntelligence = () => {
    try {
      if (typeof (spatialAudio as any)?.playAwakeningTransition === 'function') {
        (spatialAudio as any).playAwakeningTransition();
      }
    } catch {}
    onEnterCore?.();
  };

  return (
    <div
      data-testid="spatial-awakening-hero"
      data-active={isAwakening}
      aria-hidden={!isVisible}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        zIndex: 5,
        pointerEvents: isAwakening && isVisible ? 'auto' : 'none',
        opacity,
        visibility: isVisible ? 'visible' : 'hidden',
        transition: isReducedMotion
          ? 'opacity 0.3s ease'
          : 'opacity 0.75s cubic-bezier(0.16, 1, 0.3, 1), transform 0.75s cubic-bezier(0.16, 1, 0.3, 1)',
        transform: !isReducedMotion && !isAwakening ? 'scale(1.05)' : 'scale(1.0)',
        overflow: 'hidden',
        backgroundColor: '#020408',
      }}
    >
      {isVisible && (
        <>
          {/* 1. Cinematic Camera Progression Plate (Over 20–40s subtle push toward central structure) */}
          <div
            data-testid="awakening-camera-plate"
            className={!isReducedMotion ? 'awakening-camera-plate' : ''}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              transformOrigin: '50% 46%',
              animation: !isReducedMotion
                ? 'awakeningCameraPush 30s cubic-bezier(0.25, 1, 0.5, 1) forwards'
                : 'none',
            }}
          >
            {/* 1A. Full-screen Cinematic Hero Image Plate (Untouched base asset) */}
            <img
              src={heroImagePath}
              alt="AryaOS Spatial OS Awakening Hero Environment"
              data-testid="awakening-hero-image"
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                objectPosition: 'center 46%',
                pointerEvents: 'none',
                userSelect: 'none',
              }}
            />

            {/* 2. Atmospheric Motion Layer (Fog/mist drift, volumetric haze, floating micro-particles) */}
            <div
              data-testid="awakening-atmospheric-motion"
              style={{
                position: 'absolute',
                inset: 0,
                pointerEvents: 'none',
                overflow: 'hidden',
              }}
            >
              {/* Layer A: High-altitude drifting fog */}
              <div
                className={!isReducedMotion ? 'awakening-fog-layer' : ''}
                style={{
                  position: 'absolute',
                  top: '25%',
                  left: '-10%',
                  width: '120%',
                  height: '35%',
                  background:
                    'radial-gradient(ellipse at 50% 60%, rgba(148, 163, 184, 0.08) 0%, rgba(2, 4, 8, 0) 70%)',
                  filter: 'blur(30px)',
                  animation: !isReducedMotion ? 'awakeningFogDriftA 28s ease-in-out infinite' : 'none',
                }}
              />

              {/* Layer B: Midground atmospheric haze above cloud line */}
              <div
                className={!isReducedMotion ? 'awakening-fog-layer' : ''}
                style={{
                  position: 'absolute',
                  top: '38%',
                  left: '-15%',
                  width: '130%',
                  height: '32%',
                  background:
                    'radial-gradient(ellipse at 45% 50%, rgba(245, 158, 11, 0.04) 0%, rgba(15, 23, 42, 0.12) 50%, rgba(2, 4, 8, 0) 75%)',
                  filter: 'blur(40px)',
                  animation: !isReducedMotion ? 'awakeningFogDriftB 36s ease-in-out infinite' : 'none',
                }}
              />

              {/* Floating Atmospheric Particulate Canvas */}
              <AwakeningParticulateField isReducedMotion={isReducedMotion} />
            </div>

            {/* 3. Central AryaOS Energy Layer (Active vertical amber beam, bloom variation, rising streamer motes) */}
            <div
              data-testid="awakening-central-energy"
              style={{
                position: 'absolute',
                top: '22%',
                left: '50%',
                transform: 'translateX(-50%)',
                width: '180px',
                height: '40%',
                pointerEvents: 'none',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'flex-end',
              }}
            >
              {/* Vertical Amber Beam Column */}
              <div
                data-testid="awakening-amber-beam"
                className={!isReducedMotion ? 'awakening-beam-pulse' : ''}
                style={{
                  position: 'absolute',
                  bottom: 0,
                  width: '7px',
                  height: '94%',
                  background:
                    'linear-gradient(to top, rgba(251, 191, 36, 0.95) 0%, rgba(245, 158, 11, 0.75) 45%, rgba(217, 119, 6, 0.25) 80%, transparent 100%)',
                  boxShadow: '0 0 24px rgba(245, 158, 11, 0.8), 0 0 48px rgba(245, 158, 11, 0.4)',
                  borderRadius: '4px',
                  animation: !isReducedMotion ? 'amberBeamPulse 6.5s ease-in-out infinite' : 'none',
                }}
              />

              {/* Restrained Central Core Energy Bloom */}
              <div
                style={{
                  position: 'absolute',
                  bottom: '-12px',
                  width: '150px',
                  height: '95px',
                  background:
                    'radial-gradient(ellipse at 50% 60%, rgba(245, 158, 11, 0.45) 0%, rgba(217, 119, 6, 0.15) 50%, transparent 75%)',
                  filter: 'blur(14px)',
                }}
              />

              {/* Upward-moving tiny energy streamer particles */}
              <div
                data-testid="awakening-beam-particles"
                style={{
                  position: 'absolute',
                  bottom: 0,
                  width: '26px',
                  height: '85%',
                  overflow: 'hidden',
                }}
              >
                {!isReducedMotion && (
                  <>
                    <div
                      style={{
                        position: 'absolute',
                        width: '3px',
                        height: '22px',
                        left: '8px',
                        background: 'linear-gradient(to top, #fbbf24, transparent)',
                        borderRadius: '2px',
                        animation: 'amberBeamParticles 4.2s ease-in-out infinite',
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        width: '2px',
                        height: '16px',
                        left: '15px',
                        background: 'linear-gradient(to top, #fef08a, transparent)',
                        borderRadius: '2px',
                        animation: 'amberBeamParticles 5.6s ease-in-out infinite 1.8s',
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        width: '2px',
                        height: '14px',
                        left: '11px',
                        background: 'linear-gradient(to top, #f59e0b, transparent)',
                        borderRadius: '2px',
                        animation: 'amberBeamParticles 3.8s ease-in-out infinite 3.1s',
                      }}
                    />
                  </>
                )}
              </div>
            </div>

            {/* 4. Platform Energy Layer (Subtle rotation of inner rings, grooves, outward pulse waves) */}
            <div
              data-testid="awakening-platform-energy"
              style={{
                position: 'absolute',
                bottom: '14%',
                left: '50%',
                transform: 'translateX(-50%) perspective(500px) rotateX(68deg)',
                width: '460px',
                height: '460px',
                pointerEvents: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* Outward Radial Energy Wave Pulse */}
              <div
                data-testid="awakening-platform-pulse"
                className={!isReducedMotion ? 'awakening-pulse-wave' : ''}
                style={{
                  position: 'absolute',
                  width: '100%',
                  height: '100%',
                  borderRadius: '50%',
                  border: '2px solid rgba(245, 158, 11, 0.45)',
                  boxShadow: '0 0 20px rgba(245, 158, 11, 0.3)',
                  animation: !isReducedMotion ? 'platformPulseWave 10s ease-out infinite' : 'none',
                }}
              />

              {/* Rotating Inner Calibration Ring */}
              <div
                data-testid="awakening-platform-rings"
                className={!isReducedMotion ? 'awakening-ring-rotate' : ''}
                style={{
                  position: 'absolute',
                  width: '74%',
                  height: '74%',
                  borderRadius: '50%',
                  border: '1px dashed rgba(245, 158, 11, 0.35)',
                  animation: !isReducedMotion ? 'platformRingRotate 55s linear infinite' : 'none',
                }}
              />

              {/* Concentric Amber Grooves */}
              <svg
                data-testid="awakening-platform-grooves"
                viewBox="0 0 400 400"
                style={{
                  position: 'absolute',
                  width: '92%',
                  height: '92%',
                }}
              >
                <circle
                  cx="200"
                  cy="200"
                  r="170"
                  fill="none"
                  stroke="rgba(245, 158, 11, 0.22)"
                  strokeWidth="1.5"
                  strokeDasharray="16 8 4 8"
                />
                <circle
                  cx="200"
                  cy="200"
                  r="125"
                  fill="none"
                  stroke="rgba(251, 191, 36, 0.3)"
                  strokeWidth="1.2"
                  strokeDasharray="24 12"
                />
              </svg>
            </div>
          </div>

          {/* 5. Atmospheric Vignette & Deep Shadow Treatments */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: '35%',
              background:
                'linear-gradient(to bottom, rgba(2, 4, 8, 0.65) 0%, rgba(2, 4, 8, 0.2) 60%, transparent 100%)',
              pointerEvents: 'none',
            }}
          />

          <div
            style={{
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              height: '45%',
              background:
                'linear-gradient(to top, rgba(2, 4, 8, 0.88) 0%, rgba(2, 4, 8, 0.35) 50%, transparent 100%)',
              pointerEvents: 'none',
            }}
          />

          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'radial-gradient(circle at 50% 50%, transparent 45%, rgba(2, 4, 8, 0.55) 100%)',
              pointerEvents: 'none',
            }}
          />

          {/* 6. Staged Hero Visual Identity & Enter Intelligence Callout */}
          <div
            data-testid="awakening-hero-overlay"
            style={{
              position: 'absolute',
              top: '36%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              textAlign: 'center',
              gap: '0.85rem',
              width: '92%',
              maxWidth: '820px',
              zIndex: 10,
              pointerEvents: 'auto',
              userSelect: 'none',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {/* System Identifier Badge (T+3s entrance) */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '4px 12px',
                borderRadius: '4px',
                backgroundColor: 'rgba(7, 10, 16, 0.75)',
                border: '1px solid rgba(245, 158, 11, 0.45)',
                backdropFilter: 'blur(8px)',
                animation:
                  !isReducedMotion && !isTestEnv
                    ? 'heroEntranceFade 0.8s cubic-bezier(0.16, 1, 0.3, 1) 2.8s both'
                    : 'none',
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: '#f59e0b',
                  boxShadow: '0 0 10px #f59e0b',
                  display: 'inline-block',
                }}
              />
              <span
                style={{
                  fontSize: '0.6875rem',
                  letterSpacing: '0.22em',
                  color: '#fbbf24',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                }}
              >
                ARYAOS // SPATIAL OS V1
              </span>
            </div>

            {/* Monumental Central Typography (T+4s entrance) */}
            <h1
              style={{
                margin: 0,
                fontSize: 'clamp(3rem, 7vw, 5.5rem)',
                fontWeight: 900,
                letterSpacing: '0.24em',
                color: '#f8fafc',
                textShadow: '0 0 40px rgba(245, 158, 11, 0.4), 0 6px 30px rgba(0, 0, 0, 0.95)',
                lineHeight: 1.0,
                textIndent: '0.24em',
                animation:
                  !isReducedMotion && !isTestEnv
                    ? 'heroEntranceFade 0.9s cubic-bezier(0.16, 1, 0.3, 1) 3.8s both'
                    : 'none',
              }}
            >
              ARYAOS
            </h1>

            {/* Pure Cognitive Identity Tagline (T+5s entrance) */}
            <p
              style={{
                margin: 0,
                fontSize: 'clamp(0.75rem, 1.5vw, 1.05rem)',
                letterSpacing: '0.2em',
                color: '#cbd5e1',
                textTransform: 'uppercase',
                fontWeight: 600,
                maxWidth: '640px',
                textShadow: '0 2px 16px rgba(0, 0, 0, 0.9)',
                lineHeight: 1.5,
                animation:
                  !isReducedMotion && !isTestEnv
                    ? 'heroEntranceFade 0.9s cubic-bezier(0.16, 1, 0.3, 1) 4.8s both'
                    : 'none',
              }}
            >
              THE INTELLIGENCE LAYER FOR AUTONOMOUS CREATION
            </p>

            {/* Enter Intelligence Interactive Action (T+6s entrance) */}
            {onEnterCore && (
              <button
                type="button"
                data-testid="awakening-enter-btn"
                onClick={handleEnterIntelligence}
                style={{
                  marginTop: '1.4rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.65rem',
                  backgroundColor: 'rgba(8, 12, 20, 0.88)',
                  border: '1px solid rgba(245, 158, 11, 0.75)',
                  color: '#fbbf24',
                  padding: '0.85rem 2rem',
                  borderRadius: '6px',
                  fontSize: '0.8125rem',
                  fontWeight: 700,
                  letterSpacing: '0.16em',
                  cursor: 'pointer',
                  backdropFilter: 'blur(16px)',
                  boxShadow:
                    '0 0 24px rgba(245, 158, 11, 0.25), 0 8px 32px rgba(0, 0, 0, 0.85)',
                  transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                  animation:
                    !isReducedMotion && !isTestEnv
                      ? 'heroEntranceFade 0.9s cubic-bezier(0.16, 1, 0.3, 1) 5.8s both'
                      : 'none',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.2)';
                  e.currentTarget.style.borderColor = '#fbbf24';
                  e.currentTarget.style.boxShadow =
                    '0 0 36px rgba(245, 158, 11, 0.55), 0 8px 32px rgba(0, 0, 0, 0.95)';
                  e.currentTarget.style.transform = 'translateY(-2px)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'rgba(8, 12, 20, 0.88)';
                  e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.75)';
                  e.currentTarget.style.boxShadow =
                    '0 0 24px rgba(245, 158, 11, 0.25), 0 8px 32px rgba(0, 0, 0, 0.85)';
                  e.currentTarget.style.transform = 'translateY(0)';
                }}
              >
                <span>ENTER THE INTELLIGENCE</span>
                <ArrowRight size={16} />
              </button>
            )}

            {/* Ambient Navigation Cue */}
            <span
              style={{
                marginTop: '0.35rem',
                fontSize: '0.625rem',
                letterSpacing: '0.14em',
                color: '#64748b',
                textTransform: 'uppercase',
              }}
            >
              SCROLL OR PRESS [2] TO ENTER 3D CORE
            </span>
          </div>
        </>
      )}
    </div>
  );
};
