import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthModal } from '../components/AuthModal';
import { setStoredApiKey, clearStoredApiKey, getStoredApiKey } from '../api/creatorApi';

describe('AuthModal Guidance and Synchronization', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('synchronizes input state with stored key whenever isOpen becomes true', async () => {
    setStoredApiKey('test-existing-key-123');
    const onClose = vi.fn();
    const onKeyUpdated = vi.fn();

    const { rerender } = render(
      <AuthModal isOpen={false} onClose={onClose} onKeyUpdated={onKeyUpdated} />
    );

    // When closed, modal content is not rendered
    expect(screen.queryByLabelText(/ARYA_API_KEY/i)).not.toBeInTheDocument();

    // Rerender as open
    rerender(<AuthModal isOpen={true} onClose={onClose} onKeyUpdated={onKeyUpdated} />);

    const input = screen.getByLabelText(/ARYA_API_KEY/i) as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('test-existing-key-123');
  });

  it('updates stored key and calls onKeyUpdated when credentials are saved', async () => {
    const onClose = vi.fn();
    const onKeyUpdated = vi.fn();

    render(<AuthModal isOpen={true} onClose={onClose} onKeyUpdated={onKeyUpdated} />);

    const input = screen.getByLabelText(/ARYA_API_KEY/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'my-new-secret-token' } });

    const saveButton = screen.getByRole('button', { name: /Save Credentials/i });
    fireEvent.click(saveButton);

    expect(getStoredApiKey()).toBe('my-new-secret-token');
    expect(onKeyUpdated).toHaveBeenCalled();
    expect(await screen.findByText(/Authentication credentials saved/i)).toBeInTheDocument();
  });

  it('clears stored key and calls onKeyUpdated when Clear Key is clicked', async () => {
    setStoredApiKey('initial-key-to-clear');
    const onClose = vi.fn();
    const onKeyUpdated = vi.fn();

    render(<AuthModal isOpen={true} onClose={onClose} onKeyUpdated={onKeyUpdated} />);

    const clearButton = screen.getByRole('button', { name: /Clear Key/i });
    fireEvent.click(clearButton);

    expect(getStoredApiKey()).toBe('');
    expect(onKeyUpdated).toHaveBeenCalled();
    const input = screen.getByLabelText(/ARYA_API_KEY/i) as HTMLInputElement;
    expect(input.value).toBe('');
  });
});
