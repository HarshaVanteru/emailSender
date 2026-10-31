export function getToken(): string | null {
  const previous = localStorage.getItem('access_token');
  if (previous) {
    sessionStorage.setItem('access_token', previous);
    localStorage.removeItem('access_token');
  }
  return sessionStorage.getItem('access_token');
}

export function setToken(token: string) {
  sessionStorage.setItem('access_token', token);
  localStorage.removeItem('access_token');
}

export function logout() {
  localStorage.removeItem('access_token');
  sessionStorage.removeItem('access_token');
}
