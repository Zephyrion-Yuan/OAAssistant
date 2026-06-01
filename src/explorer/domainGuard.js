import { pagesConfig } from '../config.js';

function hostnameFromUrl(rawUrl) {
  try {
    return new URL(rawUrl).hostname.toLowerCase();
  } catch {
    return '';
  }
}

function configuredBusinessHosts() {
  const hosts = [];
  for (const page of pagesConfig.oa || []) {
    const host = hostnameFromUrl(page.url);
    if (host) hosts.push(host);
  }
  const pdmHost = hostnameFromUrl(pagesConfig.pdm?.url);
  if (pdmHost) hosts.push(pdmHost);
  return hosts;
}

export function explorationAllowedHosts() {
  const fromEnv = process.env.MEGANT_EXPLORE_ALLOWED_HOSTS || '';
  const hosts = fromEnv
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return Array.from(new Set([...configuredBusinessHosts(), ...hosts]));
}

export function isHostAllowed(hostname, allowedHosts, { allowSubdomains = false } = {}) {
  const host = String(hostname || '').toLowerCase();
  return allowedHosts.some((allowed) => {
    const normalized = String(allowed || '').toLowerCase();
    if (!normalized) return false;
    if (host === normalized) return true;
    return allowSubdomains && host.endsWith(`.${normalized}`);
  });
}

export function assertAllowedBusinessUrl(rawUrl, allowedHosts = explorationAllowedHosts()) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error('Invalid target URL.');
  }
  if (url.protocol !== 'https:') {
    throw new Error('Exploration target URL must use HTTPS.');
  }
  if (!isHostAllowed(url.hostname, allowedHosts)) {
    throw new Error(`Exploration target host is not whitelisted: ${url.hostname}`);
  }
  return url.toString();
}
