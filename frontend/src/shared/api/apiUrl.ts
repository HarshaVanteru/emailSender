/** Accept an origin or an API root without duplicating the version prefix. */
export function buildApiUrl(base: string, path: string): string {
  const origin = base.trim().replace(/\/+$/, '').replace(/\/api(?:\/v1)?$/, '');
  return `${origin}/api/v1/${path.replace(/^\/+/, '')}`;
}
