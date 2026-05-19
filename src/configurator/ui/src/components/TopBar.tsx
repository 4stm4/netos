import React, { useState } from 'react'
import { useStore } from '../store'
import { dryRun, useSaveProfile } from '../api'

export function TopBar() {
  const { profileName, profile, setProfileName } = useStore()
  const saveMutation = useSaveProfile()
  const [editingName, setEditingName] = useState(false)
  const [dryRunText, setDryRunText] = useState<string | null>(null)
  const [dryRunLoading, setDryRunLoading] = useState(false)
  const [dryRunError, setDryRunError] = useState<string | null>(null)

  const handleSave = () => {
    saveMutation.mutate({ name: profileName, data: profile })
  }

  const handleDryRun = async () => {
    setDryRunLoading(true)
    setDryRunError(null)
    setDryRunText(null)
    try {
      // Save first so the server has latest data
      await fetch(`/api/profiles/${profileName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      })
      const text = await dryRun(profileName)
      setDryRunText(text)
    } catch (e: unknown) {
      setDryRunError(e instanceof Error ? e.message : String(e))
    } finally {
      setDryRunLoading(false)
    }
  }

  return (
    <>
      <header
        style={{
          height: 52,
          background: 'var(--bg-1)',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 20px',
          gap: 12,
          flexShrink: 0,
        }}
      >
        <span style={{ color: 'var(--fg-3)', fontSize: 12 }}>Profile:</span>
        {editingName ? (
          <input
            autoFocus
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            onBlur={() => setEditingName(false)}
            onKeyDown={(e) => { if (e.key === 'Enter') setEditingName(false) }}
            style={{ width: 160, fontSize: 13, padding: '3px 8px' }}
          />
        ) : (
          <span
            onClick={() => setEditingName(true)}
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--fg)',
              cursor: 'pointer',
              padding: '3px 8px',
              border: '1px solid transparent',
              borderRadius: 'var(--radius-sm)',
            }}
            title="Click to rename"
          >
            {profileName}
          </span>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button
            onClick={handleDryRun}
            disabled={dryRunLoading}
            style={{
              padding: '6px 14px',
              background: 'var(--bg-2)',
              color: 'var(--fg-2)',
              borderColor: 'var(--border)',
              opacity: dryRunLoading ? 0.5 : 1,
            }}
          >
            {dryRunLoading ? 'Generating…' : 'Dry Run'}
          </button>
          <button
            onClick={handleSave}
            disabled={saveMutation.isPending}
            style={{
              padding: '6px 14px',
              background: saveMutation.isSuccess ? 'var(--ok)22' : 'var(--bg-2)',
              color: saveMutation.isSuccess ? 'var(--ok)' : 'var(--fg)',
              borderColor: saveMutation.isSuccess ? 'var(--ok)44' : 'var(--border)',
            }}
          >
            {saveMutation.isPending ? 'Saving…' : saveMutation.isSuccess ? 'Saved' : 'Save'}
          </button>
        </div>
      </header>

      {/* Dry run modal */}
      {(dryRunText !== null || dryRunError !== null) && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: '#000000cc',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={() => { setDryRunText(null); setDryRunError(null) }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)',
              width: '70vw',
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '14px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 14 }}>Generated defconfig</span>
              <button
                onClick={() => { setDryRunText(null); setDryRunError(null) }}
                style={{ background: 'transparent', border: 'none', color: 'var(--fg-3)', fontSize: 18, padding: '0 4px' }}
              >
                ×
              </button>
            </div>
            <pre
              className="mono"
              style={{
                padding: 20,
                overflow: 'auto',
                flex: 1,
                margin: 0,
                color: dryRunError ? 'var(--err)' : 'var(--fg)',
                fontSize: 12,
                lineHeight: 1.6,
              }}
            >
              {dryRunError ?? dryRunText}
            </pre>
          </div>
        </div>
      )}
    </>
  )
}
