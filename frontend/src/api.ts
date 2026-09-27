import type { ChatMessage, GeneratedEmail, SendEmailPayload, SendEmailResponse, GmailProfile } from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export function getToken(): string | null {
  return localStorage.getItem('access_token');
}

export function setToken(token: string) {
  localStorage.setItem('access_token', token);
}

export function logout() {
  localStorage.removeItem('access_token');
}

function getAuthHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

export async function fetchGmailProfile(): Promise<GmailProfile | null> {
  try {
    const res = await fetch(`${API_BASE}/api/gmail/profile`, {
      headers: {
        ...getAuthHeaders()
      }
    });
    if (!res.ok) {
      if (res.status === 401) logout();
      return null;
    }
    return await res.json();
  } catch {
    return null;
  }
}

export async function updateProfile(data: { name?: string; signature?: string; preferences?: string }): Promise<void> {
  const res = await fetch(`${API_BASE}/api/gmail/profile`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error('Failed to update profile');
  }
}

export function getGmailAuthUrl(): string {
  const base = API_BASE ? API_BASE : 'http://127.0.0.1:8000';
  return `${base}/api/gmail/auth`;
}

export async function generateEmailDraft(
  instruction: string,
  history: ChatMessage[] = []
): Promise<GeneratedEmail> {
  const res = await fetch(`${API_BASE}/api/ai/generate-email`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify({
      instruction,
      messages: history,
    }),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `AI generation failed with HTTP ${res.status}`);
  }

  return await res.json();
}

export async function sendEmail(payload: SendEmailPayload): Promise<SendEmailResponse> {
  const res = await fetch(`${API_BASE}/api/gmail/send`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify(payload),
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Email dispatch failed with HTTP ${res.status}`);
  }

  return data;
}

export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const [, base64Data = ''] = result.split(',', 2);
      resolve(base64Data);
    };
    reader.onerror = () => reject(new Error('Failed to read file for attachment.'));
    reader.readAsDataURL(file);
  });
}
