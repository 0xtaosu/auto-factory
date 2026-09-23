function devApiBase() {
  const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
  const host = hostname || 'localhost';
  const formatted = host.includes(':') ? `[${host}]` : host;
  return `http://${formatted}:8000`;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? devApiBase() : '');

const DOWNLOAD_NAMES = {
  json: 'result.json',
  csv: 'activity_assessments.csv',
  ttl: 'inventory-activity.ttl',
  report: 'inventory-activity-mvp.md',
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isUnauthorized(error) {
  return Boolean(error) && error.status === 401;
}

export function defaultMcpUrl() {
  const path = '/mcp';
  if (API_BASE) return `${String(API_BASE).replace(/\/$/, '')}${path}`;
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}${path}`;
  }
  return path;
}

function parseError(text, status) {
  try {
    const data = JSON.parse(text);
    const detail = data.detail ?? data.error ?? data;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => item.msg || item.message || JSON.stringify(item)).join('；');
    }
    if (detail && typeof detail === 'object') {
      const message = detail.message || detail.msg;
      const extra = Array.isArray(detail.details) ? detail.details.filter(Boolean).join('；') : '';
      if (message && extra) return `${message}：${extra}`;
      if (message) return message;
    }
  } catch {
    /* keep raw text */
  }
  return text || `HTTP ${status}`;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: 'include',
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(error?.message || '网络请求失败', 0);
  }
  const text = await response.text();
  if (!response.ok) {
    throw new ApiError(text ? parseError(text, response.status) : `HTTP ${response.status}`, response.status);
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError('服务器返回了无法解析的响应', response.status);
  }
}

export async function getConfig() {
  return request('/api/activity/config');
}

export async function createJob(file, { observationDate, thresholdDays } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  if (observationDate) formData.append('observation_date', observationDate);
  if (thresholdDays !== '' && thresholdDays != null) {
    formData.append('threshold_days', String(thresholdDays));
  }
  return request('/api/activity/jobs', {
    method: 'POST',
    body: formData,
  });
}

export async function getJob(jobId) {
  return request(`/api/activity/jobs/${jobId}`);
}

export async function getOverview(jobId) {
  return request(`/api/activity/jobs/${jobId}/overview`);
}

export async function getAssessments(jobId, { q = '', inactiveOnly = false, offset = 0, limit = 50 } = {}) {
  const params = new URLSearchParams({
    q,
    inactive_only: String(Boolean(inactiveOnly)),
    offset: String(offset),
    limit: String(limit),
  });
  return request(`/api/activity/jobs/${jobId}/assessments?${params}`);
}

export async function getExplanation(jobId, materialCode) {
  return request(`/api/activity/jobs/${jobId}/materials/${encodeURIComponent(materialCode)}/explanation`);
}

export async function downloadResult(jobId, format) {
  let response;
  try {
    response = await fetch(`${API_BASE}/api/activity/jobs/${jobId}/download/${format}`, {
      credentials: 'include',
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(error?.message || '网络请求失败', 0);
  }
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(parseError(text, response.status), response.status);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const quoted = disposition.match(/filename="([^"]+)"/i);
  const plain = disposition.match(/filename=([^;]+)/i);
  const filename = decodeURIComponent(
    (star?.[1] || quoted?.[1] || plain?.[1] || DOWNLOAD_NAMES[format] || `download.${format}`).trim(),
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function getSession() {
  return request('/api/auth/session');
}

export function login(token) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}

export function logoutSession() {
  return request('/api/auth/logout', { method: 'POST' });
}

export function listApiKeys() {
  return request('/api/admin/keys');
}

export function createApiKey(payload) {
  return request('/api/admin/keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function revokeApiKey(keyId) {
  return request(`/api/admin/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
}

export function getMcpInfo() {
  return request('/api/admin/mcp');
}
