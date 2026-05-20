import React, { useState, useMemo } from 'react'
import { useStore } from '../store'
import { usePackages, useDefaults, type PackageEntry, type PackageCategory } from '../api'

const MINIMAL_PRESET = [
  'BR2_PACKAGE_BUSYBOX',
  'BR2_PACKAGE_IPROUTE2',
  'BR2_PACKAGE_DROPBEAR',
  'BR2_PACKAGE_PYTHON3',
  'BR2_PACKAGE_OPEN_ISCSI',
  'BR2_PACKAGE_OPENVSWITCH',
]

function fmtSize(kb: number): string {
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${kb} KB`
}

export function Step03Packages() {
  const { profile, updateProfile } = useStore()
  const { data: catalogue, isLoading } = usePackages()
  const { data: defaultsData } = useDefaults()
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [customInput, setCustomInput] = useState('')
  const [showCustomModal, setShowCustomModal] = useState(false)

  const enabled = useMemo(() => new Set(profile.packages.enabled), [profile.packages.enabled])

  const allPackages = useMemo(() => {
    if (!catalogue) return []
    return catalogue.categories.flatMap((c) => c.packages)
  }, [catalogue])

  const filteredCategories = useMemo(() => {
    if (!catalogue) return []
    const q = search.toLowerCase()
    return catalogue.categories
      .filter((c) => activeCategory === null || c.id === activeCategory)
      .map((c) => ({
        ...c,
        packages: c.packages.filter(
          (p) =>
            !q ||
            p.name.toLowerCase().includes(q) ||
            p.description.toLowerCase().includes(q) ||
            p.key.toLowerCase().includes(q)
        ),
      }))
      .filter((c) => c.packages.length > 0)
  }, [catalogue, search, activeCategory])

  const totalSize = useMemo(() => {
    return allPackages
      .filter((p) => enabled.has(p.key))
      .reduce((acc, p) => acc + (p.size_kb ?? 0), 0)
  }, [allPackages, enabled])

  const requiredKeys = useMemo(() => {
    if (!catalogue) return new Set<string>()
    return new Set(
      catalogue.categories.flatMap((c) => c.packages.filter((p) => p.required).map((p) => p.key))
    )
  }, [catalogue])

  const missingRequired = useMemo(
    () => [...requiredKeys].filter((k) => !enabled.has(k)),
    [requiredKeys, enabled]
  )

  function toggle(pkg: PackageEntry) {
    if (pkg.required) return
    const next = new Set(enabled)
    if (next.has(pkg.key)) {
      next.delete(pkg.key)
    } else {
      next.add(pkg.key)
    }
    updateProfile({ packages: { ...profile.packages, enabled: [...next] } })
  }

  function applyPreset(keys: string[]) {
    updateProfile({ packages: { ...profile.packages, enabled: [...new Set(keys)] } })
  }

  function applyFullPreset() {
    const keys = defaultsData?.keys ?? []
    applyPreset(keys)
  }

  function addCustom() {
    const line = customInput.trim()
    if (!line) return
    updateProfile({
      packages: {
        ...profile.packages,
        custom: [...profile.packages.custom, line],
      },
    })
    setCustomInput('')
    setShowCustomModal(false)
  }

  function removeCustom(line: string) {
    updateProfile({
      packages: {
        ...profile.packages,
        custom: profile.packages.custom.filter((l) => l !== line),
      },
    })
  }

  return (
    <div style={{ display: 'flex', gap: 0, height: '100%', overflow: 'hidden' }}>
      {/* Category sidebar */}
      <div
        style={{
          width: 160,
          borderRight: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          padding: '0 0 8px',
          overflowY: 'auto',
          flexShrink: 0,
        }}
      >
        <div style={{ padding: '8px 12px 12px', fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Categories
        </div>
        <button
          onClick={() => setActiveCategory(null)}
          style={{
            padding: '7px 12px',
            background: activeCategory === null ? 'var(--bg-2)' : 'transparent',
            border: 'none',
            borderRadius: 0,
            borderLeft: activeCategory === null ? '2px solid var(--info)' : '2px solid transparent',
            color: activeCategory === null ? 'var(--fg)' : 'var(--fg-3)',
            textAlign: 'left',
            fontSize: 12,
            fontWeight: activeCategory === null ? 600 : 400,
          }}
        >
          All
        </button>
        {catalogue?.categories.map((c) => (
          <button
            key={c.id}
            onClick={() => setActiveCategory(c.id)}
            style={{
              padding: '7px 12px',
              background: activeCategory === c.id ? 'var(--bg-2)' : 'transparent',
              border: 'none',
              borderRadius: 0,
              borderLeft: activeCategory === c.id ? '2px solid var(--info)' : '2px solid transparent',
              color: activeCategory === c.id ? 'var(--fg)' : 'var(--fg-3)',
              textAlign: 'left',
              fontSize: 12,
              fontWeight: activeCategory === c.id ? 600 : 400,
            }}
          >
            {c.name}
          </button>
        ))}

        <div style={{ padding: '16px 12px 8px', fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Presets
        </div>
        <button
          onClick={() => applyPreset(MINIMAL_PRESET)}
          style={{ padding: '7px 12px', background: 'transparent', border: 'none', color: 'var(--info)', textAlign: 'left', fontSize: 12, borderLeft: '2px solid transparent' }}
        >
          Minimal
        </button>
        <button
          onClick={applyFullPreset}
          style={{ padding: '7px 12px', background: 'transparent', border: 'none', color: 'var(--info)', textAlign: 'left', fontSize: 12, borderLeft: '2px solid transparent' }}
          title={`Выбирает все пакеты по умолчанию (${defaultsData?.keys.length ?? '…'})`}
        >
          Full netOS {defaultsData ? `(${defaultsData.keys.length})` : ''}
        </button>

        {/* Nervum / SDN info */}
        <div
          style={{
            margin: '16px 8px 0',
            padding: '10px',
            background: 'var(--info)0e',
            border: '1px solid var(--info)33',
            borderRadius: 'var(--radius-sm)',
            fontSize: 11,
            color: 'var(--fg-3)',
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--info)', marginBottom: 4 }}>SDN / Nervum</div>
          Nervum — не BR2_PACKAGE. Устанавливается отдельно через pip в /opt/testum/.python. Настраивается на шаге&nbsp;4.
        </div>
      </div>

      {/* Main package list */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <input
            placeholder="Search packages…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1, fontSize: 13 }}
          />
          <button
            onClick={() => setShowCustomModal(true)}
            style={{
              padding: '6px 12px',
              background: 'var(--bg-2)',
              color: 'var(--info)',
              borderColor: 'var(--info)44',
              whiteSpace: 'nowrap',
            }}
          >
            + Custom BR2_PACKAGE
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {isLoading && <div style={{ padding: '20px 16px', color: 'var(--fg-3)' }}>Loading packages…</div>}
          {filteredCategories.map((cat) => (
            <div key={cat.id}>
              <div
                style={{
                  padding: '10px 16px 6px',
                  fontSize: 11,
                  fontWeight: 700,
                  color: 'var(--fg-3)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  position: 'sticky',
                  top: 0,
                  background: 'var(--bg-1)',
                  zIndex: 1,
                }}
              >
                {cat.name}
              </div>
              {cat.packages.map((pkg) => {
                const checked = enabled.has(pkg.key)
                const required = pkg.required
                return (
                  <label
                    key={pkg.key}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 16px',
                      cursor: required ? 'default' : 'pointer',
                      background: checked ? 'var(--info)08' : 'transparent',
                      borderBottom: '1px solid var(--border)44',
                      textTransform: 'none',
                      fontSize: 13,
                      letterSpacing: 0,
                      color: 'var(--fg)',
                      fontWeight: 400,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked || !!required}
                      disabled={!!required}
                      onChange={() => toggle(pkg)}
                      style={{ accentColor: 'var(--info)', marginTop: 2, flexShrink: 0 }}
                    />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="mono" style={{ color: checked ? 'var(--fg)' : 'var(--fg-2)', fontSize: 12 }}>
                          {pkg.name}
                        </span>
                        {required && (
                          <span style={{ fontSize: 10, color: 'var(--warn)', fontWeight: 600, background: 'var(--warn)18', border: '1px solid var(--warn)33', borderRadius: 4, padding: '1px 5px' }}>
                            required
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--fg-3)', marginTop: 2 }}>{pkg.description}</div>
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--fg-3)', whiteSpace: 'nowrap', marginTop: 2 }}>
                      {fmtSize(pkg.size_kb)}
                    </span>
                  </label>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Right summary */}
      <div
        style={{
          width: 220,
          borderLeft: '1px solid var(--border)',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          overflowY: 'auto',
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Summary
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--fg-3)', fontSize: 12 }}>Selected</span>
              <span className="mono" style={{ color: 'var(--fg)', fontSize: 12 }}>{enabled.size}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--fg-3)', fontSize: 12 }}>Est. size</span>
              <span className="mono" style={{ color: 'var(--fg)', fontSize: 12 }}>{fmtSize(totalSize)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--fg-3)', fontSize: 12 }}>Custom</span>
              <span className="mono" style={{ color: 'var(--fg)', fontSize: 12 }}>{profile.packages.custom.length}</span>
            </div>
          </div>
        </div>

        {missingRequired.length > 0 && (
          <div
            style={{
              background: 'var(--err)12',
              border: '1px solid var(--err)44',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--err)', fontWeight: 600, marginBottom: 6 }}>
              Missing required
            </div>
            {missingRequired.map((k) => (
              <div key={k} className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 2 }}>
                {k}
              </div>
            ))}
          </div>
        )}

        {profile.packages.custom.length > 0 && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
              Custom lines
            </div>
            {profile.packages.custom.map((line) => (
              <div
                key={line}
                style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}
              >
                <span className="mono" style={{ fontSize: 10, color: 'var(--fg-2)', flex: 1, wordBreak: 'break-all' }}>
                  {line}
                </span>
                <button
                  onClick={() => removeCustom(line)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--err)',
                    padding: '0 2px',
                    fontSize: 14,
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Custom package modal */}
      {showCustomModal && (
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
          onClick={() => setShowCustomModal(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
              width: 420,
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700 }}>Add custom BR2_PACKAGE line</h3>
            <input
              autoFocus
              placeholder="BR2_PACKAGE_SOCAT=y"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addCustom() }}
              style={{ width: '100%', marginBottom: 14 }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowCustomModal(false)}
                style={{ padding: '7px 16px', background: 'var(--bg-2)', color: 'var(--fg-3)', borderColor: 'var(--border)' }}
              >
                Cancel
              </button>
              <button
                onClick={addCustom}
                style={{ padding: '7px 16px', background: 'var(--info)', color: '#fff', border: 'none', borderRadius: 'var(--radius-sm)' }}
              >
                Add
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
