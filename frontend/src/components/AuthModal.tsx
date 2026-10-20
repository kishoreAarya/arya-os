import React, { useState, useEffect } from 'react';
import { X, Lock, CheckCircle2 } from 'lucide-react';
import { getStoredApiKey, setStoredApiKey, clearStoredApiKey } from '../api/creatorApi';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onKeyUpdated: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onKeyUpdated }) => {
  const [apiKey, setApiKey] = useState(getStoredApiKey());
  const [savedMessage, setSavedMessage] = useState(false);

  // Close on Escape key press
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (apiKey.trim()) {
      setStoredApiKey(apiKey.trim());
    } else {
      clearStoredApiKey();
    }
    setSavedMessage(true);
    onKeyUpdated();
    setTimeout(() => {
      setSavedMessage(false);
      onClose();
    }, 800);
  };

  const handleClear = () => {
    clearStoredApiKey();
    setApiKey('');
    onKeyUpdated();
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(4, 6, 10, 0.82)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
        padding: '1rem',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
    >
      <div
        className="creator-card"
        style={{
          maxWidth: '480px',
          width: '100%',
          position: 'relative',
          boxShadow: 'var(--shadow-depth-3)',
          border: '1px solid rgba(255, 255, 255, 0.12)',
        }}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            position: 'absolute',
            top: '1rem',
            right: '1rem',
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '4px',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <X size={18} />
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              boxShadow: '0 0 10px rgba(59, 130, 246, 0.2)',
            }}
          >
            <Lock size={18} />
          </div>
          <div>
            <h2 id="auth-modal-title" style={{ fontSize: '1.125rem', fontWeight: 600, letterSpacing: '-0.01em' }}>
              AryaOS Authentication
            </h2>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Configure Bearer token for protected backend endpoints
            </p>
          </div>
        </div>

        <form onSubmit={handleSave}>
          <div style={{ marginBottom: '1.25rem' }}>
            <label className="form-label" htmlFor="apiKeyInput">
              ARYA_API_KEY
            </label>
            <input
              id="apiKeyInput"
              type="password"
              className="form-input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste your ARYA_API_KEY here"
              autoFocus
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem', lineHeight: 1.4 }}>
              In development mode with <code>API_AUTH_ENABLED=false</code>, authentication can be bypassed.
              When enabled, all generation and lineage calls require a valid Bearer token.
            </p>
          </div>

          {savedMessage && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                color: 'var(--success)',
                fontSize: '0.875rem',
                marginBottom: '1rem',
                padding: '0.5rem 0.75rem',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              <CheckCircle2 size={16} />
              <span>Authentication credentials saved</span>
            </div>
          )}

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            {apiKey && (
              <button
                type="button"
                onClick={handleClear}
                className="btn-secondary"
                style={{ color: 'var(--danger)', borderColor: 'rgba(239, 68, 68, 0.3)' }}
              >
                Clear Key
              </button>
            )}
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary" style={{ width: 'auto' }}>
              Save Credentials
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
