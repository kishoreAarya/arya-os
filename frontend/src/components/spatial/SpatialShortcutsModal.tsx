import React, { useEffect } from 'react';
import { X, Command, Keyboard } from 'lucide-react';

interface SpatialShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface ShortcutEntry {
  keys: string[];
  action: string;
  category: 'STATIONS' | 'NAVIGATION' | 'INSPECTION' | 'WORKSPACE';
}

const SHORTCUTS: ShortcutEntry[] = [
  { keys: ['1', '–', '6'], action: 'Switch Camera Station (Entry → Command)', category: 'STATIONS' },
  { keys: ['C'], action: 'Open Creator Studio', category: 'WORKSPACE' },
  { keys: ['H'], action: 'Toggle Cinematic Mode (Hide / Show HUD)', category: 'WORKSPACE' },
  { keys: ['I'], action: 'Open Central ARYAOS Core Inspector', category: 'INSPECTION' },
  { keys: ['M'], action: 'Cycle Subsystem Modules (Memory → Planning → Routing → Exec)', category: 'INSPECTION' },
  { keys: ['['], action: 'Select Previous Corridor Shot', category: 'NAVIGATION' },
  { keys: [']'], action: 'Select Next Corridor Shot', category: 'NAVIGATION' },
  { keys: ['ESC'], action: 'Close Inspector / Dismiss Focus / Close Modal', category: 'NAVIGATION' },
  { keys: ['?'], action: 'Toggle Keyboard Shortcuts Guide', category: 'WORKSPACE' },
];

export const SpatialShortcutsModal: React.FC<SpatialShortcutsModalProps> = ({ isOpen, onClose }) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '?') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      data-testid="spatial-shortcuts-modal"
      role="dialog"
      aria-label="Keyboard Shortcuts Guide"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 60,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(2, 4, 8, 0.75)',
        backdropFilter: 'blur(10px)',
        padding: '1rem',
        pointerEvents: 'auto',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '520px',
          backgroundColor: 'rgba(10, 15, 24, 0.96)',
          border: '1px solid rgba(245, 158, 11, 0.45)',
          borderRadius: '8px',
          boxShadow: '0 16px 48px rgba(0, 0, 0, 0.85), 0 0 32px rgba(245, 158, 11, 0.15)',
          padding: '1.25rem 1.5rem',
          color: '#cbd5e1',
          fontFamily: "'JetBrains Mono', monospace",
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', paddingBottom: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Keyboard size={16} color="#f59e0b" />
            <h2 style={{ margin: 0, fontSize: '0.875rem', fontWeight: 700, color: '#f8fafc', letterSpacing: '0.08em' }}>
              OPERATOR COMMAND MATRIX // SHORTCUTS
            </h2>
          </div>
          <button
            type="button"
            data-testid="shortcuts-modal-close"
            onClick={onClose}
            aria-label="Close shortcuts guide"
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '4px',
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Shortcuts List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
          {SHORTCUTS.map((item, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.35rem 0.5rem',
                borderRadius: '4px',
                backgroundColor: 'rgba(15, 23, 42, 0.45)',
                border: '1px solid rgba(255, 255, 255, 0.03)',
              }}
            >
              <span style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>{item.action}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                {item.keys.map((k, kIdx) =>
                  k === '–' ? (
                    <span key={kIdx} style={{ fontSize: '0.6875rem', color: '#64748b' }}>–</span>
                  ) : (
                    <kbd
                      key={kIdx}
                      style={{
                        padding: '2px 6px',
                        backgroundColor: 'rgba(245, 158, 11, 0.12)',
                        border: '1px solid rgba(245, 158, 11, 0.45)',
                        borderRadius: '3px',
                        fontSize: '0.6875rem',
                        fontWeight: 700,
                        color: '#fbbf24',
                        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.4)',
                      }}
                    >
                      {k}
                    </kbd>
                  )
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Footer Note */}
        <div
          style={{
            fontSize: '0.625rem',
            color: '#64748b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderTop: '1px solid rgba(255, 255, 255, 0.06)',
            paddingTop: '0.625rem',
          }}
        >
          <span>PRESS [?] OR [ESC] ANYTIME TO DISMISS</span>
          <span style={{ color: '#f59e0b' }}>ARYAOS V1 // SPATIAL OPERATOR</span>
        </div>
      </div>
    </div>
  );
};
