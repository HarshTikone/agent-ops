import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

type Header = { key: string; value: string }
type HeaderRule = { source: string; headers: Header[] }

const vercelConfig = JSON.parse(readFileSync(resolve('vercel.json'), 'utf8')) as {
  headers?: HeaderRule[]
}

function productionHeaders(): Map<string, string> {
  const rule = vercelConfig.headers?.find(({ source }) => source === '/(.*)')
  return new Map(rule?.headers.map(({ key, value }) => [key, value]) ?? [])
}

describe('production frontend security configuration', () => {
  it('sets the required response headers', () => {
    const headers = productionHeaders()

    expect(headers.get('X-Content-Type-Options')).toBe('nosniff')
    expect(headers.get('X-Frame-Options')).toBe('DENY')
    expect(headers.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin')
    expect(headers.get('Permissions-Policy')).toContain('camera=()')
    expect(headers.get('Permissions-Policy')).toContain('microphone=()')
  })

  it('uses a restrictive CSP with only the required external origins', () => {
    const csp = productionHeaders().get('Content-Security-Policy')

    expect(csp).toContain("default-src 'self'")
    expect(csp).toContain("script-src 'self'")
    expect(csp).not.toContain("'unsafe-inline'")
    expect(csp).toContain("style-src 'self' https://fonts.googleapis.com")
    expect(csp).toContain("font-src 'self' https://fonts.gstatic.com")
    expect(csp).toContain("connect-src 'self' https://agent-ops-api-jcgc.onrender.com")
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("object-src 'none'")
  })

  it('loads the theme bootstrap without an inline script', () => {
    const indexHtml = readFileSync(resolve('index.html'), 'utf8')

    expect(indexHtml).toContain('<script src="/theme-bootstrap.js"></script>')
    expect(indexHtml).not.toMatch(/<script>(.|\s)*?<\/script>/)
  })
})
