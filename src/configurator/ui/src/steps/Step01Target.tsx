import React from 'react'
import { useStore } from '../store'
import { useTargets } from '../api'
import { StatusBadge } from '../components/StatusBadge'

const TARGET_ICONS: Record<string, string> = {
  'qemu-virt': '🖥',
  pi5: '🍓',
  zero2w: '📡',
}

export function Step01Target() {
  const { profile, updateProfile } = useStore()
  const { data: targets, isLoading, error } = useTargets()

  const rootfs_mb = profile.image.size_mb - profile.image.boot_mb

  return (
    <div style={{ display: 'flex', gap: 24, height: '100%' }}>
      {/* Left: target cards + sliders */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <h2 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 700 }}>Select Target</h2>
          {isLoading && <div style={{ color: 'var(--fg-3)' }}>Loading targets…</div>}
          {error && <div style={{ color: 'var(--err)' }}>Failed to load targets</div>}
          {targets && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {Object.entries(targets).map(([key, t]) => {
                const active = profile.target === key
                return (
                  <button
                    key={key}
                    onClick={() => {
                      updateProfile({
                        target: key,
                        image: { size_mb: t.image_size_mb, boot_mb: t.boot_size_mb },
                      })
                    }}
                    style={{
                      width: 180,
                      padding: '16px',
                      background: active ? 'var(--info)18' : 'var(--bg-2)',
                      border: `1px solid ${active ? 'var(--info)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius)',
                      textAlign: 'left',
                      color: 'var(--fg)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                    }}
                  >
                    <div style={{ fontSize: 28 }}>{TARGET_ICONS[key] ?? '⬡'}</div>
                    <div style={{ fontWeight: 700, fontSize: 14 }}>{key}</div>
                    <div style={{ fontSize: 11, color: 'var(--fg-3)', lineHeight: 1.4 }}>{t.description}</div>
                    <StatusBadge status={t.status} />
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Image size sliders */}
        <div
          style={{
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Image Sizes</h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Total image size</label>
              <span className="mono" style={{ color: 'var(--fg)' }}>{profile.image.size_mb} MB</span>
            </div>
            <input
              type="range"
              min={256}
              max={4096}
              step={64}
              value={profile.image.size_mb}
              onChange={(e) =>
                updateProfile({ image: { ...profile.image, size_mb: Number(e.target.value) } })
              }
              style={{ width: '100%' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--fg-3)' }}>
              <span>256 MB</span>
              <span>4096 MB</span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Boot partition</label>
              <span className="mono" style={{ color: 'var(--fg)' }}>{profile.image.boot_mb} MB</span>
            </div>
            <input
              type="range"
              min={32}
              max={512}
              step={32}
              value={profile.image.boot_mb}
              onChange={(e) =>
                updateProfile({ image: { ...profile.image, boot_mb: Number(e.target.value) } })
              }
              style={{ width: '100%' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--fg-3)' }}>
              <span>32 MB</span>
              <span>512 MB</span>
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '10px 14px',
              background: 'var(--bg)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
            }}
          >
            <label>rootfs (calculated)</label>
            <span
              className="mono"
              style={{ color: rootfs_mb > 0 ? 'var(--ok)' : 'var(--err)' }}
            >
              {rootfs_mb} MB
            </span>
          </div>
        </div>
      </div>

      {/* Right: live preview */}
      <div
        style={{
          width: 280,
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--fg-3)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Target properties
          </div>
          {targets && targets[profile.target] ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {[
                  ['kernel', targets[profile.target].kernel_defconfig],
                  ['image', targets[profile.target].image_name],
                  ['qemu', targets[profile.target].qemu_supported ? 'yes' : 'no'],
                  ['modules', targets[profile.target].build_kernel_modules ? 'yes' : 'no'],
                  ['boot files', targets[profile.target].install_boot_files ? 'yes' : 'no'],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ padding: '4px 0', color: 'var(--fg-3)', fontSize: 12, width: '50%' }}>{k}</td>
                    <td className="mono" style={{ padding: '4px 0', color: 'var(--fg)', fontSize: 12 }}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: 'var(--fg-3)', fontSize: 12 }}>Select a target</div>
          )}
        </div>

        {targets && targets[profile.target]?.boot_cmdline && (
          <div
            style={{
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '16px',
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--fg-3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Boot cmdline
            </div>
            <pre
              className="mono"
              style={{
                margin: 0,
                fontSize: 11,
                color: 'var(--fg-2)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                lineHeight: 1.6,
              }}
            >
              {targets[profile.target].boot_cmdline}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
