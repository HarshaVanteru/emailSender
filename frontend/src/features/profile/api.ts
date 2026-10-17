import type { GmailProfile } from './types';
import { apiUrl, getAuthHeaders } from '../../shared/api/client';
import { logout } from '../google-login/session';

export async function fetchGmailProfile(): Promise<GmailProfile | null> {
  try {
    const res = await fetch(apiUrl('gmail/profile'), {
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

export async function updateProfile(data: { name?: string; signature?: string; preferences?: string; bio?: string }): Promise<void> {
  const res = await fetch(apiUrl('gmail/profile'), {
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
