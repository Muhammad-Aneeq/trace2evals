/** Typed fetch client. Same-origin only: this UI never talks to anything but the local server. */

import type {
  LabelRequest,
  LabelResponse,
  ParseReport,
  RunDetail,
  RunFilters,
  RunSummary,
  Stats,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    // FastAPI puts the useful message in `detail`; fall back to the status text.
    let detail = response.statusText
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: never) => JSON.stringify(d)).join('; ')
    } catch {
      /* a non-JSON error body is fine; the status text will do */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function toQuery(filters: RunFilters & { limit?: number; offset?: number }): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    // Empty string and null both mean "no filter"; false is a real value and must survive.
    if (value === '' || value === null || value === undefined) continue
    params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const api = {
  listRuns(filters: RunFilters & { limit?: number; offset?: number } = {}): Promise<RunSummary[]> {
    return request<RunSummary[]>(`/api/runs${toQuery(filters)}`)
  },

  getRun(runId: string): Promise<RunDetail> {
    return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`)
  },

  nextUnlabeled(exclude?: string): Promise<RunDetail | null> {
    const query = exclude ? `?exclude=${encodeURIComponent(exclude)}` : ''
    return request<RunDetail | null>(`/api/runs/next-unlabeled${query}`)
  },

  labelRun(runId: string, body: LabelRequest): Promise<LabelResponse> {
    return request<LabelResponse>(`/api/runs/${encodeURIComponent(runId)}/label`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  clearLabel(runId: string): Promise<void> {
    return request<void>(`/api/runs/${encodeURIComponent(runId)}/label`, { method: 'DELETE' })
  },

  importFiles(files: File[], options: { format?: string; redact?: boolean } = {}): Promise<ParseReport[]> {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const params = new URLSearchParams()
    if (options.format && options.format !== 'auto') params.set('format', options.format)
    if (options.redact === false) params.set('redact', 'false')
    const query = params.toString() ? `?${params}` : ''
    return request<ParseReport[]>(`/api/import${query}`, { method: 'POST', body: form })
  },

  getStats(): Promise<Stats> {
    return request<Stats>('/api/stats')
  },
}
