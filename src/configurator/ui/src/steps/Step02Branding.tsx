import React from 'react'
import { useStore } from '../store'

const WIFI_DISABLED_TARGETS = new Set(['qemu-virt', 'pi5', 'pi4'])

function Field({
  label,
  children,
  error,
}: {
  label: string
  children: React.ReactNode
  error?: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label>{label}</label>
      {children}
      {error && <span style={{ color: 'var(--err)', fontSize: 11 }}>{error}</span>}
    </div>
  )
}

export function Step02Branding() {
  const { profile, updateProfile } = useStore()
  const { branding, network, target } = profile
  const eth0 = network.eth0
  const wifi = network.wifi
  const wifiDisabled = WIFI_DISABLED_TARGETS.has(target)

  const idError = /^[a-z0-9-]+$/.test(branding.id) ? undefined : 'Must match ^[a-z0-9-]+$'
  const versionError = /^\d+\.\d+\.\d+/.test(branding.version) ? undefined : 'Must be semver (x.y.z)'
  const hostnameError = /^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$/.test(branding.hostname)
    ? undefined
    : 'Must match ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$'

  return (
    <div style={{ display: 'flex', gap: 24, height: '100%' }}>
      {/* Left: form */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 24, overflowY: 'auto', paddingRight: 4 }}>

        {/* Branding */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Branding</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Field label="OS Name">
              <input
                value={branding.name}
                onChange={(e) => updateProfile({ branding: { ...branding, name: e.target.value } })}
              />
            </Field>
            <Field label="OS ID (slug)" error={idError}>
              <input
                value={branding.id}
                onChange={(e) => updateProfile({ branding: { ...branding, id: e.target.value } })}
                style={{ borderColor: idError ? 'var(--err)' : undefined }}
              />
            </Field>
            <Field label="Version" error={versionError}>
              <input
                value={branding.version}
                onChange={(e) => updateProfile({ branding: { ...branding, version: e.target.value } })}
                style={{ borderColor: versionError ? 'var(--err)' : undefined }}
              />
            </Field>
            <Field label="Hostname" error={hostnameError}>
              <input
                value={branding.hostname}
                onChange={(e) => updateProfile({ branding: { ...branding, hostname: e.target.value } })}
                style={{ borderColor: hostnameError ? 'var(--err)' : undefined }}
              />
            </Field>
          </div>
        </section>

        {/* Access */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Access</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Root password">
              <input
                type="password"
                placeholder="(leave empty for dev-mode — no password)"
                value={branding.root_password ?? ''}
                onChange={(e) => updateProfile({ branding: { ...branding, root_password: e.target.value } })}
              />
              {!branding.root_password && (
                <span style={{ color: 'var(--warn)', fontSize: 11 }}>
                  Dev mode: root login without password. Set a password for production use.
                </span>
              )}
            </Field>
            <Field label="SSH Authorized Key (public key)">
              <textarea
                rows={3}
                placeholder="ssh-ed25519 AAAA... user@host"
                value={branding.ssh_authorized_key ?? ''}
                onChange={(e) => updateProfile({ branding: { ...branding, ssh_authorized_key: e.target.value } })}
                style={{
                  fontFamily: 'monospace',
                  fontSize: 11,
                  resize: 'vertical',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--fg)',
                  padding: '8px 10px',
                  lineHeight: 1.5,
                }}
              />
              <span style={{ color: 'var(--fg-3)', fontSize: 11 }}>
                Installed to /root/.ssh/authorized_keys
              </span>
            </Field>
          </div>
        </section>

        {/* Console */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Console</h3>
          <div style={{ display: 'flex', gap: 12 }}>
            {(['ttyAMA0', 'tty1', 'both'] as const).map((mode) => (
              <label
                key={mode}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  cursor: 'pointer',
                  color: (branding.console ?? 'ttyAMA0') === mode ? 'var(--fg)' : 'var(--fg-3)',
                  fontWeight: (branding.console ?? 'ttyAMA0') === mode ? 600 : 400,
                  textTransform: 'none',
                  fontSize: 13,
                  letterSpacing: 0,
                }}
              >
                <input
                  type="radio"
                  name="console"
                  value={mode}
                  checked={(branding.console ?? 'ttyAMA0') === mode}
                  onChange={() => updateProfile({ branding: { ...branding, console: mode } })}
                  style={{ accentColor: 'var(--info)', width: 14, height: 14 }}
                />
                {mode === 'ttyAMA0' && 'UART (ttyAMA0)'}
                {mode === 'tty1' && 'HDMI (tty1)'}
                {mode === 'both' && 'Both'}
              </label>
            ))}
          </div>
        </section>

        {/* Network eth0 */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Network · eth0</h3>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            {(['dhcp', 'static', 'disabled'] as const).map((mode) => (
              <label
                key={mode}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  cursor: 'pointer',
                  color: eth0.mode === mode ? 'var(--fg)' : 'var(--fg-3)',
                  fontWeight: eth0.mode === mode ? 600 : 400,
                  textTransform: 'none',
                  fontSize: 13,
                  letterSpacing: 0,
                }}
              >
                <input
                  type="radio"
                  name="eth0mode"
                  value={mode}
                  checked={eth0.mode === mode}
                  onChange={() =>
                    updateProfile({ network: { ...network, eth0: { ...eth0, mode } } })
                  }
                  style={{ accentColor: 'var(--info)', width: 14, height: 14 }}
                />
                {mode.toUpperCase()}
              </label>
            ))}
          </div>

          {eth0.mode === 'static' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Field label="IP Address (CIDR)">
                <input
                  placeholder="192.168.1.100/24"
                  value={eth0.address}
                  onChange={(e) =>
                    updateProfile({ network: { ...network, eth0: { ...eth0, address: e.target.value } } })
                  }
                />
              </Field>
              <Field label="Gateway">
                <input
                  placeholder="192.168.1.1"
                  value={eth0.gateway}
                  onChange={(e) =>
                    updateProfile({ network: { ...network, eth0: { ...eth0, gateway: e.target.value } } })
                  }
                />
              </Field>
              <Field label="DNS Server">
                <input
                  placeholder="1.1.1.1"
                  value={eth0.dns}
                  onChange={(e) =>
                    updateProfile({ network: { ...network, eth0: { ...eth0, dns: e.target.value } } })
                  }
                />
              </Field>
            </div>
          )}
        </section>

        {/* Wi-Fi */}
        <section style={{ opacity: wifiDisabled ? 0.4 : 1, pointerEvents: wifiDisabled ? 'none' : 'auto' }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 14, fontWeight: 700 }}>
            Wi-Fi
            {wifiDisabled && (
              <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--fg-3)', fontWeight: 400 }}>
                (not supported for {target})
              </span>
            )}
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 16 }}>
            <Field label="Country code">
              <input
                value={wifi.country}
                maxLength={2}
                onChange={(e) =>
                  updateProfile({ network: { ...network, wifi: { ...wifi, country: e.target.value.toUpperCase() } } })
                }
              />
            </Field>
            <Field label="SSID">
              <input
                value={wifi.ssid}
                onChange={(e) =>
                  updateProfile({ network: { ...network, wifi: { ...wifi, ssid: e.target.value } } })
                }
              />
            </Field>
            <Field label="PSK (password)">
              <input
                type="password"
                value={wifi.psk}
                onChange={(e) =>
                  updateProfile({ network: { ...network, wifi: { ...wifi, psk: e.target.value } } })
                }
              />
            </Field>
            <Field label="Bootstrap via Wi-Fi">
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  cursor: 'pointer',
                  textTransform: 'none',
                  fontSize: 13,
                  letterSpacing: 0,
                  color: 'var(--fg)',
                  fontWeight: 400,
                }}
              >
                <input
                  type="checkbox"
                  checked={wifi.bootstrap}
                  onChange={(e) =>
                    updateProfile({ network: { ...network, wifi: { ...wifi, bootstrap: e.target.checked } } })
                  }
                  style={{ accentColor: 'var(--info)', width: 14, height: 14 }}
                />
                Enable bootstrap
              </label>
            </Field>
          </div>
        </section>
      </div>

      {/* Right: live preview */}
      <div style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div
          style={{
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '14px 16px',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            /etc/os-release
          </div>
          <pre
            className="mono"
            style={{ margin: 0, fontSize: 11, lineHeight: 1.7, color: 'var(--fg-2)', whiteSpace: 'pre-wrap' }}
          >
            {[
              `NAME="${branding.name}"`,
              `ID=${branding.id}`,
              `VERSION="${branding.version}"`,
              `VERSION_ID=${branding.version}`,
              `PRETTY_NAME="${branding.name} ${branding.version}"`,
            ].join('\n')}
          </pre>
        </div>

        <div
          style={{
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '14px 16px',
            fontFamily: 'monospace',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            Login prompt preview
          </div>
          <div style={{ fontSize: 12, color: 'var(--ok)', lineHeight: 1.6 }}>
            {branding.name} {branding.version}
          </div>
          <div style={{ fontSize: 12, color: 'var(--fg-2)', lineHeight: 1.6 }}>
            {branding.hostname} login: <span style={{ color: 'var(--fg)' }}>root</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--fg-3)' }}>
            Password: {branding.root_password ? '(set)' : '(empty — dev mode)'}
          </div>
        </div>

        {branding.ssh_authorized_key && (
          <div
            style={{
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
              ~/.ssh/authorized_keys
            </div>
            <pre
              className="mono"
              style={{
                margin: 0,
                fontSize: 10,
                color: 'var(--ok)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                lineHeight: 1.5,
              }}
            >
              {branding.ssh_authorized_key.trim().slice(0, 120)}
              {branding.ssh_authorized_key.trim().length > 120 ? '…' : ''}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
