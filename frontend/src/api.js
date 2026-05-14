const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://localhost:8000' : '');

async function request(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function createJob(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request('/api/jobs', {
    method: 'POST',
    body: formData,
  });
}

export async function getJob(jobId) {
  return request(`/api/jobs/${jobId}`);
}

export async function getOverview(jobId) {
  return request(`/api/jobs/${jobId}/overview`);
}

export async function getDetail(jobId, indicatorId) {
  return request(`/api/jobs/${jobId}/details/${indicatorId}`);
}
