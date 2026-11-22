import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiUrl, request } from './client'
import { getCostAllocations, runAnalysis } from './runs'

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('apiUrl', () => {
  it('adds query values and leaves out undefined ones', () => {
    expect(
      apiUrl('/api/runs/abc/series', { metric: 'npv', asset_id: undefined }),
    ).toBe('/api/runs/abc/series?metric=npv')
    expect(apiUrl('/api/health')).toBe('/api/health')
  })
})

describe('request', () => {
  it('returns the JSON reply', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(reply(200, { status: 'ok' })),
    )
    await expect(request('/api/health')).resolves.toEqual({ status: 'ok' })
  })

  it('throws the backend message as an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(reply(404, { detail: "no run with ID 'x'" })),
    )
    const call = request('/api/runs/x')
    await expect(call).rejects.toBeInstanceOf(ApiError)
    await expect(call).rejects.toMatchObject({
      status: 404,
      message: "no run with ID 'x'",
    })
  })

  it('joins field problems from a malformed request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        reply(422, {
          detail: [{ msg: 'Field required' }, { msg: 'Not a number' }],
        }),
      ),
    )
    await expect(request('/api/runs')).rejects.toThrow(
      'Field required; Not a number',
    )
  })
})

describe('run calls', () => {
  it('posts the run request as JSON', async () => {
    const fetch = vi.fn().mockResolvedValue(reply(200, { run_id: 'abc' }))
    vi.stubGlobal('fetch', fetch)

    await runAnalysis({ asset_ids: ['A-1'], settings: { end_year: 2030 } })

    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/runs')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      asset_ids: ['A-1'],
      settings: { end_year: 2030 },
    })
  })

  it('asks for one year of costs for one asset', async () => {
    const fetch = vi.fn().mockResolvedValue(reply(200, { rows: [] }))
    vi.stubGlobal('fetch', fetch)

    await getCostAllocations('abc', 2026, 'A-1')

    expect(fetch.mock.calls[0][0]).toBe(
      '/api/runs/abc/cost-allocations?year=2026&asset_id=A-1',
    )
  })
})
