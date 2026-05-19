import React from 'react'

type Status = 'verified' | 'wip' | 'running' | 'done' | 'error' | 'init'

const COLORS: Record<Status, string> = {
  verified: 'var(--ok)',
  wip: 'var(--warn)',
  running: 'var(--info)',
  done: 'var(--ok)',
  error: 'var(--err)',
  init: 'var(--fg-3)',
}

const LABELS: Record<Status, string> = {
  verified: 'verified',
  wip: 'wip',
  running: 'running',
  done: 'done',
  error: 'error',
  init: 'init',
}

interface Props {
  status: Status
  label?: string
}

export function StatusBadge({ status, label }: Props) {
  const color = COLORS[status] ?? 'var(--fg-3)'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        color,
        background: `${color}18`,
        border: `1px solid ${color}33`,
        borderRadius: 'var(--radius-sm)',
        padding: '2px 8px',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: color,
          display: 'inline-block',
          ...(status === 'running'
            ? { animation: 'pulse 1.2s ease-in-out infinite' }
            : {}),
        }}
      />
      {label ?? LABELS[status] ?? status}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </span>
  )
}
