import React from 'react';
import { Orbit, Sparkles, GitBranch, TrendingUp, Share2, Brain } from 'lucide-react';
import { AppView } from '../../types/dashboard';
import { motion } from 'motion/react';
import { usePrefersReducedMotion } from '../motion/MotionSystem';

interface AppNavProps {
  activeView: AppView;
  onViewChange: (view: AppView) => void;
}

interface NavItem {
  id: AppView;
  label: string;
  icon: React.ReactNode;
}

export const AppNav: React.FC<AppNavProps> = ({ activeView, onViewChange }) => {
  const isReducedMotion = usePrefersReducedMotion();

  const navItems: NavItem[] = [
    {
      id: 'spatial',
      label: 'Spatial Core',
      icon: <Orbit size={15} />,
    },
    {
      id: 'creator',
      label: 'Creator Studio',
      icon: <Sparkles size={15} />,
    },
    {
      id: 'pipelines',
      label: 'Pipelines & Runs',
      icon: <GitBranch size={15} />,
    },
    {
      id: 'research',
      label: 'Research & Trends',
      icon: <TrendingUp size={15} />,
    },
    {
      id: 'publishing',
      label: 'Publishing',
      icon: <Share2 size={15} />,
    },
    {
      id: 'learning',
      label: 'Learning Loop',
      icon: <Brain size={15} />,
    },
  ];

  return (
    <nav
      aria-label="Main Navigation"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '2px',
        backgroundColor: 'rgba(7, 10, 16, 0.85)',
        padding: '2px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-color)',
        boxShadow: 'inset 0 1px 2px rgba(0, 0, 0, 0.5), 0 2px 8px rgba(0, 0, 0, 0.3)',
      }}
    >
      {navItems.map((item) => {
        const isActive = activeView === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onViewChange(item.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.28rem',
              padding: '4px 7px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              backgroundColor: 'transparent',
              color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.75rem',
              fontWeight: isActive ? 600 : 500,
              position: 'relative',
              transition: 'color 0.15s ease',
              whiteSpace: 'nowrap',
            }}
            aria-current={isActive ? 'page' : undefined}
          >
            {/* Active Pill Indicator with Motion */}
            {isActive && (
              isReducedMotion ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: 'rgba(22, 32, 52, 0.95)',
                    border: '1px solid rgba(59, 130, 246, 0.4)',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
                    zIndex: 0,
                  }}
                />
              ) : (
                <motion.div
                  layoutId="activeNavIndicator"
                  style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: 'rgba(22, 32, 52, 0.95)',
                    border: '1px solid rgba(59, 130, 246, 0.4)',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
                    zIndex: 0,
                  }}
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )
            )}

            <span
              style={{
                position: 'relative',
                zIndex: 1,
                display: 'flex',
                alignItems: 'center',
                color: isActive ? 'var(--accent-primary)' : 'inherit',
                transition: 'color 0.15s ease',
              }}
            >
              {item.icon}
            </span>
            <span style={{ position: 'relative', zIndex: 1 }}>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
};
