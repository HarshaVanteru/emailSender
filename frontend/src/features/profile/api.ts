import type { GmailProfile } from './types';
import { ApiError, apiRequest } from '../../shared/api/client';
import { logout } from '../google-login/session';

export async function fetchGmailProfile(): Promise<GmailProfile | null> {
  try {
    return await apiRequest<GmailProfile>('gmail/profile');
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) logout();
    return null;
  }
}

export const updateProfile = (data: { name?: string; signature?: string; preferences?: string; bio?: string }) =>
  apiRequest<void>('gmail/profile', undefined, 'PUT', data, 'Failed to update profile');
