import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  API_BASE_URL,
  ApiError,
  approvePendingAction,
  createSession,
  getSession,
  getTrace,
  listSessions,
  rejectPendingAction,
  sendMessage,
} from './api'

describe('api request helper (via the session/approval functions)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed JSON body on a 2xx response', async () => {
    const session = { id: 's1', status: 'created' }
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => session,
    })
    await expect(createSession()).resolves.toEqual(session)
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/sessions`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('throws an ApiError carrying the backend detail message on a 409', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "session is 'done', not 'created'" }),
    })
    const error = await sendMessage('s1', 'hi').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).message).toBe("session is 'done', not 'created'")
  })

  it('falls back to a generic message when the error body has no detail field', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    })
    const error = await getSession('s1').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toContain('status 500')
  })

  it('falls back to a generic message when the error body is not valid JSON', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError('Unexpected token')
      },
    })
    const error = await getTrace('s1').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toContain('status 502')
  })

  it('sendMessage POSTs the content as the JSON body', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    await sendMessage('s1', 'what is 2+2?')
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ content: 'what is 2+2?' })
  })

  it('approvePendingAction POSTs with no body', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    await approvePendingAction('p1')
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`${API_BASE_URL}/approvals/p1/approve`)
    expect(init.method).toBe('POST')
  })

  it('rejectPendingAction POSTs the reason, defaulting to null', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    await rejectPendingAction('p1')
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ reason: null })

    await rejectPendingAction('p1', 'not needed')
    const [, init2] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1]
    expect(JSON.parse(init2.body)).toEqual({ reason: 'not needed' })
  })

  it('listSessions GETs the plain sessions collection', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => [] })
    await listSessions()
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`${API_BASE_URL}/sessions`)
    expect(init.method).toBeUndefined()
  })
})
