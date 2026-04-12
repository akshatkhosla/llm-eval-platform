import type { EvalRunSummary, EvalRunDetail, EvalResultsResponse, EvalTrace, CompareResponse } from '../types'

const BASE = '/api/v1'

export async function fetchEvals(params?: {
  status?: string | null
  limit?: number
  offset?: number
}): Promise<EvalRunSummary[]> {
  const sp = new URLSearchParams()
  if (params?.status) sp.set('status', params.status)
  if (params?.limit != null) sp.set('limit', String(params.limit))
  if (params?.offset != null) sp.set('offset', String(params.offset))
  const qs = sp.toString()
  const res = await fetch(`${BASE}/evals${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<EvalRunSummary[]>
}

export async function fetchEvalDetail(runId: string): Promise<EvalRunDetail> {
  const res = await fetch(`${BASE}/evals/${runId}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<EvalRunDetail>
}

export async function fetchEvalResults(runId: string): Promise<EvalResultsResponse> {
  const res = await fetch(`${BASE}/evals/${runId}/results`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<EvalResultsResponse>
}

export async function fetchEvalTraces(runId: string): Promise<EvalTrace> {
  const res = await fetch(`${BASE}/evals/${runId}/traces`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<EvalTrace>
}

export async function rerunEval(
  runId: string,
): Promise<{ run_id: string; status: string; parent_run_id: string }> {
  const res = await fetch(`${BASE}/evals/${runId}/rerun`, { method: 'POST' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<{ run_id: string; status: string; parent_run_id: string }>
}

export async function fetchCompare(
  runIdA: string,
  runIdB: string,
  flaggedLimit = 10,
): Promise<CompareResponse> {
  const sp = new URLSearchParams({ run_ids: `${runIdA},${runIdB}`, flagged_limit: String(flaggedLimit) })
  const res = await fetch(`${BASE}/evals/compare?${sp}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<CompareResponse>
}

export async function createEval(
  configYaml: string,
): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${BASE}/evals`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config_yaml: configYaml }),
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({ detail: res.statusText }))) as {
      detail?: string
    }
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<{ run_id: string; status: string }>
}
