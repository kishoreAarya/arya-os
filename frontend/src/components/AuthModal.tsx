import React, { useState } from 'react';
import { Key, X, Lock, CheckCircle2, AlertCircle } from 'lucide-react';
import { getStoredApiKey, setStoredApiKey, clearStoredApiKey } from '../api/creatorApi';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onKeyUpdated: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onKeyUpdated }) => {
  const [apiKey, setApiKey] = useState(getStoredApiKey());
  const [savedMessage, setSavedMessage] = useState(false);

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
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 50,
      padding: '1rem',
    }}>
      <div className="creator-card" style={{ maxWidth: '480px', width: '100%', position: 'relative' }}>
        <button
          onClick={onClose}
          style={{
            position: 'absolute',
            top: '1rem',
            right: '1rem',
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
          }}
        >
          <X size={20} />
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '8px',
            backgroundColor: 'rgba(99, 102, 241, 0.15)',
            color: 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Lock size={20} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>AryaOS Authentication</h2>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Configure Bearer token for protected backend endpoints
            </p>
          </div>
        </div>

        <form onSubmit={handleSave}>
          <div style={{ marginBottom: '1.25rem' }}>
            <label className="form-label" htmlFor="apiKeyInput">ARYA_API_KEY</label>
            <input
              id="apiKeyInput"
              type="password"
              className="form-input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste your ARYA_API_KEY here"
              autoFocus
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
              In development mode with <code>API_AUTH_ENABLED=false</code>, authentication can be bypassed.
              When enabled, all generation and lineage calls require a valid Bearer token.
            </p>
          </div>

          {savedMessage && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              color: 'var(--success)',
              fontSize: '0.875rem',
              marginBottom: '1rem',
            }}>
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
                style={{ color: 'var(--danger)' }}
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
