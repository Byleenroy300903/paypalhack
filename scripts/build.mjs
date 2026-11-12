import { spawnSync } from 'node:child_process';

const value = (process.env.NEXUS_API_URL ?? '').trim();
let origin = '';
if (value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('NEXUS_API_URL must be an HTTP(S) origin, without credentials, path, query or fragment.');
  }
  origin = url.origin;
}
if (process.env.VERCEL && !origin) {
  throw new Error('Set NEXUS_API_URL to the deployed backend HTTPS origin in the frontend Vercel project.');
}
if (process.env.VERCEL && !origin.startsWith('https://')) {
  throw new Error('NEXUS_API_URL must use HTTPS on Vercel.');
}

const result = spawnSync(process.execPath, [
  'node_modules/@angular/cli/bin/ng.js', 'build',
  '--define', `NEXUS_API_ORIGIN=${JSON.stringify(origin)}`, ...process.argv.slice(2)
], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
