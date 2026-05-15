import mermaid from 'mermaid'
import { useEffect, useId, useRef } from 'react'

let mermaidConfigured = false

function ensureMermaidConfig() {
  if (mermaidConfigured) return
  mermaidConfigured = true
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'dark',
  })
}

type Props = { code: string }

const MERMAID_HEADER =
  /^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|mindmap|timeline|quadrantChart|block-beta|packet-beta)\b/i

function sanitizeMermaidCode(raw: string): string {
  let c = raw
    .trim()
    .replace(/\u201c/g, '"')
    .replace(/\u201d/g, '"')
    .replace(/\u2018/g, '\u0027')
    .replace(/\u2019/g, '\u0027')
    .replace(/\u2013/g, '-') // en dash
    .replace(/\u2014/g, '-') // em dash
    .replace(/\u200b/g, '')
  c = c.replace(/^```mermaid\s*/i, '').replace(/^```\s*/, '').replace(/\s*```$/, '')
  const lines = c.split('\n')
  let start = -1
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim()
    if (!t) continue
    if (MERMAID_HEADER.test(t)) {
      start = i
      break
    }
  }
  if (start === -1) {
    const body = lines
      .map((l) => l.trim())
      .filter(Boolean)
      .join('\n')
    if (!body) return c
    return `flowchart TD\n${body}`
  }
  return lines.slice(start).join('\n').trim()
}

/** Escape text for use inside A["..."] */
function safeNodeLabel(text: string, max = 140): string {
  return text
    .replace(/\n/g, ' ')
    .replace(/"/g, '\u0027')
    .replace(/[[\]]/g, '')
    .slice(0, max)
    .trim()
}

function trivialFallback(summary: string): string {
  const s = safeNodeLabel(summary, 120)
  return `flowchart LR\n   A["${s || 'Open your textbook figure for this topic'}"]`
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Mermaid's broken-diagram SVG always includes this phrase; avoid matching generic "error" in class names (false positives on valid charts). */
function mermaidSvgIsErrorPlaceholder(svg: string): boolean {
  return /Syntax error in text/i.test(svg)
}

export function MermaidDiagram({ code }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, '')

  useEffect(() => {
    const el = ref.current
    if (!el || !code.trim()) return

    let cancelled = false
    el.innerHTML = '<p class="hint">Drawing diagram…</p>'
    ensureMermaidConfig()

    const slugBase = `g-${reactId}-${Math.random().toString(36).slice(2, 9)}`
    const cleaned = sanitizeMermaidCode(code)

    const attempts: string[] = [cleaned]
    const firstLine = cleaned.split('\n').find((l) => l.trim()) || ''
    if (firstLine && !MERMAID_HEADER.test(firstLine)) {
      attempts.push(`flowchart TD\n${cleaned}`)
    }
    attempts.push(trivialFallback(cleaned))
    attempts.push('flowchart LR\n  A["Key idea"]')

    const run = async () => {
      let lastErr: unknown = null
      for (let i = 0; i < attempts.length; i++) {
        const slug = `${slugBase}-${i}`
        const text = attempts[i]
        try {
          const parsed = await mermaid.parse(text, { suppressErrors: true })
          if (parsed === false) {
            lastErr = new Error('Mermaid parse rejected diagram')
            continue
          }
          const { svg } = await mermaid.render(slug, text)
          if (mermaidSvgIsErrorPlaceholder(svg)) {
            lastErr = new Error('Mermaid produced error SVG')
            continue
          }
          if (!cancelled) {
            el.innerHTML = svg
            return
          }
        } catch (e) {
          lastErr = e
        }
      }
      if (!cancelled && lastErr) {
        const msg = escapeHtml(String(lastErr))
        el.innerHTML = `<div class="diagram-fallback"><p class="diagram-err-hint">Could not render diagram automatically.</p><p class="diagram-err">${msg}</p><details class="diagram-raw"><summary>Show diagram source</summary><pre>${escapeHtml(
          code,
        )}</pre></details></div>`
      }
    }

    void run()

    return () => {
      cancelled = true
    }
  }, [code, reactId])

  if (!code.trim()) return null

  return <div className="mermaid-wrap" ref={ref} />
}
