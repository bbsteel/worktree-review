import { Highlight, themes } from 'prism-react-renderer'
import { useContext } from 'react'
import { ThemeContext } from '../../app/theme.ts'
import type { EvidenceSpanView } from '../../domain/review.ts'

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'tsx',
  js: 'javascript',
  jsx: 'jsx',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  md: 'markdown',
  go: 'go',
  rs: 'rust',
}

function languageForPath(path: string): string {
  const extension = path.split('.').pop() ?? ''
  return LANGUAGE_BY_EXTENSION[extension] ?? 'plain'
}

interface EvidenceViewerProps {
  span: EvidenceSpanView
}

/**
 * Renders one verified quoted evidence span with real line numbers.
 * Quoted lines use a left rule plus background (not color alone). Only the
 * verified quoted text is rendered — the viewer never fabricates surrounding
 * context lines. Code renders as text; no HTML is executed.
 */
export function EvidenceViewer({ span }: EvidenceViewerProps) {
  const theme = useContext(ThemeContext)
  const resolved = theme?.resolved ?? 'dark'
  const prismTheme = resolved === 'light' ? themes.nightOwlLight : themes.nightOwl

  return (
    <figure className="overflow-hidden rounded-md border border-border bg-code-background">
      <figcaption className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-3 py-1.5 text-meta text-text-secondary">
        <span className="font-mono text-text-primary">
          {span.path}:{span.startLine}–{span.endLine}
        </span>
        <span>verified quoted source</span>
        <span aria-hidden="true">·</span>
        <span>{span.changeKind}</span>
        <span aria-hidden="true">·</span>
        <span>source: {span.source}</span>
        <span aria-hidden="true">·</span>
        <span className="font-mono">snapshot {span.snapshotIdentity}</span>
      </figcaption>
      <Highlight code={span.quotedText} language={languageForPath(span.path)} theme={prismTheme}>
        {({ tokens, getLineProps, getTokenProps }) => (
          <pre
            className="overflow-x-auto p-2 font-mono text-meta"
            style={{ backgroundColor: 'transparent' }}
          >
            {tokens.map((line, lineIndex) => {
              const lineNumber = span.startLine + lineIndex
              const lineProps = getLineProps({ line })
              return (
                <div
                  key={lineNumber}
                  {...lineProps}
                  className={`${lineProps.className ?? ''} flex border-l-2 border-action-primary bg-surface-subtle/60`}
                >
                  <span
                    aria-hidden="true"
                    className="w-10 shrink-0 select-none pr-2 text-right text-text-secondary tabular-nums"
                  >
                    {lineNumber}
                  </span>
                  <span className="sr-only">(quoted line)</span>
                  <span className="min-w-0 whitespace-pre">
                    {line.map((token, tokenIndex) => (
                      <span key={tokenIndex} {...getTokenProps({ token })} />
                    ))}
                  </span>
                </div>
              )
            })}
          </pre>
        )}
      </Highlight>
    </figure>
  )
}
