import React from 'react'
import { useStore } from '../store'

const STEPS = [
  { icon: '⬡', label: 'Target' },
  { icon: '◈', label: 'Branding & Network' },
  { icon: '◻', label: 'Packages' },
  { icon: '◉', label: 'Web UI' },
  { icon: '▶', label: 'Build' },
]

export function Sidebar() {
  const { currentStep, setStep } = useStore()

  return (
    <aside
      style={{
        width: 200,
        background: 'var(--bg-1)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '24px 0',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          padding: '0 20px 24px',
          borderBottom: '1px solid var(--border)',
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--fg-3)', textTransform: 'uppercase' }}>
          netOS
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', marginTop: 2 }}>
          Build Configurator
        </div>
      </div>

      {STEPS.map((step, i) => {
        const active = currentStep === i
        const done = currentStep > i
        return (
          <button
            key={i}
            onClick={() => setStep(i)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 20px',
              background: active ? 'var(--bg-2)' : 'transparent',
              borderLeft: active ? '2px solid var(--info)' : '2px solid transparent',
              border: 'none',
              borderRadius: 0,
              color: active ? 'var(--fg)' : done ? 'var(--fg-2)' : 'var(--fg-3)',
              fontWeight: active ? 600 : 400,
              textAlign: 'left',
              width: '100%',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            <span
              style={{
                width: 22,
                height: 22,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: '50%',
                fontSize: 11,
                fontWeight: 700,
                background: active
                  ? 'var(--info)'
                  : done
                  ? 'var(--ok)22'
                  : 'var(--border)',
                color: active ? '#fff' : done ? 'var(--ok)' : 'var(--fg-3)',
                flexShrink: 0,
              }}
            >
              {done ? '✓' : i + 1}
            </span>
            <span style={{ fontSize: 13 }}>{step.label}</span>
          </button>
        )
      })}
    </aside>
  )
}
