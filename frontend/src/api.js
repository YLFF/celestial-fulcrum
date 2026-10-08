import { readPreference } from './preferences.js';

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

let token = readPreference('fulcrum-token', globalThis.sessionStorage) || '';
const images = new Map();

export function setToken(value) {
  token = value;
  sessionStorage.setItem('fulcrum-token', value);
  for (const value of images.values()) value.then(url => URL.revokeObjectURL(url)).catch(() => {});
  images.clear();
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (token) headers.set('X-Fulcrum-Token', token);
  let body = options.body;
  if (body && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { ...options, body, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || response.statusText);
    throw new ApiError(response.status, detail);
  }
  if (options.asBlob) return response.blob();
  if (options.asText) return response.text();
  return response.json();
}

export function imageURL(path) {
  if (!images.has(path)) images.set(path, api(path, { asBlob: true }).then(blob => URL.createObjectURL(blob)));
  return images.get(path);
}

export function download(data, filename, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
