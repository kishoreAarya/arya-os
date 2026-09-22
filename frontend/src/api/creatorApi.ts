import {
  CapabilitiesManifest,
  CreatorGeneratePayload,
  GenerationJob,
  HealthStatus,
  HistoryItem,
} from '../types/creator';

const STORAGE_KEY_AUTH = 'arya_api_key';

export const getStoredApiKey = (): string => {
  return localStorage.getItem(STORAGE_KEY_AUTH) || sessionStorage.getItem(STORAGE_KEY_AUTH) || '';
};

export const setStoredApiKey = (key: string, persist: boolean = true): void => {
  if (persist) {
    localStorage.setItem(STORAGE_KEY_AUTH, key.trim());
  } else {
    sessionStorage.setItem(STORAGE_KEY_AUTH, key.trim());
  }
};

export const clearStoredApiKey = (): void => {
  localStorage.removeItem(STORAGE_KEY_AUTH);
  sessionStorage.removeItem(STORAGE_KEY_AUTH);
};

const getAuthHeaders = (): HeadersInit => {
  const key = getStoredApiKey();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (key) {
    headers['Authorization'] = `Bearer ${key}`;
  }
  return headers;
};

export async function checkBackendHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch('/health');
    if (!res.ok) {
      return { status: 'error' };
    }
    const data = await res.json();
    return {
      status: data.status || 'healthy',
      checks: data.checks,
    };
  } catch {
    return { status: 'connecting' };
  }
}

export async function fetchCapabilities(): Promise<CapabilitiesManifest> {
  const res = await fetch('/creator/capabilities', {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to load capabilities: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function submitGeneration(payload: CreatorGeneratePayload): Promise<GenerationJob> {
  const res = await fetch('/creator/generate', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 422) {
    const errData = await res.json().catch(() => ({ detail: 'Invalid input payload' }));
    const msg = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
    throw new Error(`Validation error: ${msg}`);
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Submission failed: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function pollJobStatus(jobId: string): Promise<GenerationJob> {
  const res = await fetch(`/creator/jobs/${encodeURIComponent(jobId)}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 404) {
    throw new Error(`Job ${jobId} not found`);
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Job status poll failed: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchHistory(): Promise<HistoryItem[]> {
  const res = await fetch('/creator/history', {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`History fetch failed: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function uploadAsset(file: File): Promise<{ url: string; key: string; filename: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const base64Data = reader.result as string;
        const res = await fetch('/creator/upload', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({
            filename: file.name,
            content_base64: base64Data,
            content_type: file.type || 'image/png',
          }),
        });

        if (res.status === 401) {
          throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
        }
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`Upload failed: ${res.status} ${errText}`);
        }

        const data = await res.json();
        resolve(data);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('Failed to read file for upload'));
    reader.readAsDataURL(file);
  });
}

export function getDownloadProxyUrl(url: string, filename: string): string {
  return `/creator/assets/download?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(filename)}`;
}
