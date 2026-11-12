declare const NEXUS_API_ORIGIN: string;

export function apiUrl(path: string): string {
  return `${NEXUS_API_ORIGIN}${path}`;
}
