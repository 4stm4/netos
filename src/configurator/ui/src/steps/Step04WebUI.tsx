import React from 'react'
import { useStore } from '../store'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label>{label}</label>
      {children}
    </div>
  )
}

export function Step04WebUI() {
  const { profile, updateProfile } = useStore()
  const webui = profile.webui
  const nervum = profile.nervum

  function patchWebui(partial: Partial<typeof webui>) {
    updateProfile({ webui: { ...webui, ...partial } })
  }

  function patchNervum(partial: Partial<typeof nervum>) {
    updateProfile({ nervum: { ...nervum, ...partial } })
  }

  const envPreview = [
    `NETOS_WEBUI_GIT_URL=${webui.git_url}`,
    `NETOS_WEBUI_GIT_REF=${webui.git_ref}`,
    ...(webui.source === 'local' ? [`NETOS_WEBUI_SOURCE_DIR=${webui.source_dir}`] : []),
    ...(webui.source === 'runtime' ? [`NETOS_WEBUI_EMBED=0`] : []),
    `NETOS_WEBUI_PORT=${webui.port}`,
    `NETOS_WEBUI_DATA_DIR=${webui.data_dir}`,
    `NETOS_WEBUI_DATABASE_URL=${webui.database_url}`,
    `NETOS_WEBUI_PIP_MODE=${webui.pip_mode}`,
    `NETOS_WEBUI_ADMIN_USERNAME=${webui.admin_username}`,
    ...(webui.admin_password ? [`NETOS_WEBUI_ADMIN_PASSWORD=***`] : []),
    `NETOS_WEBUI_HEALTH_PATH=${webui.health_path}`,
    `NETOS_WEBUI_APP_MODULE=${webui.app_module}`,
    ...(nervum.enabled
      ? [
          `NETOS_NERVUM_GIT_URL=${nervum.git_url}`,
          `NETOS_NERVUM_GIT_REF=${nervum.git_ref}`,
          ...(nervum.source === 'local' ? [`NETOS_NERVUM_SOURCE_DIR=${nervum.source_dir}`] : []),
        ]
      : []),
  ]

  return (
    <div style={{ display: 'flex', gap: 24, height: '100%' }}>
      {/* Left: form */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 24, overflowY: 'auto', paddingRight: 4 }}>

        {/* Source */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Web UI Source</h3>
          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            {(['git', 'local', 'runtime'] as const).map((src) => (
              <button
                key={src}
                onClick={() => patchWebui({ source: src })}
                style={{
                  padding: '10px 20px',
                  background: webui.source === src ? 'var(--info)22' : 'var(--bg-2)',
                  border: `1px solid ${webui.source === src ? 'var(--info)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius)',
                  color: webui.source === src ? 'var(--info)' : 'var(--fg-3)',
                  fontWeight: webui.source === src ? 600 : 400,
                  fontSize: 13,
                }}
              >
                {src === 'git' && 'From Git'}
                {src === 'local' && 'Local path'}
                {src === 'runtime' && 'Runtime only'}
              </button>
            ))}
          </div>

          {webui.source === 'git' && (
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
              <Field label="Git URL">
                <input value={webui.git_url} onChange={(e) => patchWebui({ git_url: e.target.value })} />
              </Field>
              <Field label="Branch / Ref">
                <input value={webui.git_ref} onChange={(e) => patchWebui({ git_ref: e.target.value })} />
              </Field>
            </div>
          )}

          {webui.source === 'local' && (
            <Field label="Source directory path">
              <input
                placeholder="/path/to/your/app"
                value={webui.source_dir}
                onChange={(e) => patchWebui({ source_dir: e.target.value })}
              />
            </Field>
          )}

          {webui.source === 'runtime' && (
            <div
              style={{
                padding: '12px 16px',
                background: 'var(--warn)12',
                border: '1px solid var(--warn)44',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--warn)',
                fontSize: 12,
              }}
            >
              Runtime mode: the app is not embedded in the image. You must deploy it manually after boot.
            </div>
          )}
        </section>

        {/* Runtime config */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Runtime Configuration</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
            <Field label="Data directory">
              <input value={webui.data_dir} onChange={(e) => patchWebui({ data_dir: e.target.value })} />
            </Field>
            <Field label="Port">
              <input
                type="number"
                min={1}
                max={65535}
                value={webui.port}
                onChange={(e) => patchWebui({ port: Number(e.target.value) })}
              />
            </Field>
            <Field label="Database URL">
              <input value={webui.database_url} onChange={(e) => patchWebui({ database_url: e.target.value })} />
            </Field>
            <Field label="pip mode">
              <select value={webui.pip_mode} onChange={(e) => patchWebui({ pip_mode: e.target.value as 'never' | 'auto' })}>
                <option value="never">never (Buildroot packages only)</option>
                <option value="auto">auto (pip install at boot)</option>
              </select>
            </Field>
            <Field label="App module">
              <input value={webui.app_module} onChange={(e) => patchWebui({ app_module: e.target.value })} />
            </Field>
            <Field label="Health check path">
              <input value={webui.health_path} onChange={(e) => patchWebui({ health_path: e.target.value })} />
            </Field>
          </div>
        </section>

        {/* Admin credentials */}
        <section>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, fontWeight: 700 }}>Admin Credentials</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Field label="Username">
              <input value={webui.admin_username} onChange={(e) => patchWebui({ admin_username: e.target.value })} />
            </Field>
            <Field label="Password">
              <input
                type="password"
                placeholder="(leave empty for no auth)"
                value={webui.admin_password}
                onChange={(e) => patchWebui({ admin_password: e.target.value })}
              />
            </Field>
          </div>
        </section>

        {/* Nervum SDN Controller */}
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Nervum (SDN Controller)</h3>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 400,
                textTransform: 'none',
                letterSpacing: 0,
                color: 'var(--fg)',
              }}
            >
              <input
                type="checkbox"
                checked={nervum.enabled}
                onChange={(e) => patchNervum({ enabled: e.target.checked })}
                style={{ accentColor: 'var(--info)', width: 14, height: 14 }}
              />
              {nervum.enabled ? 'Enabled' : 'Disabled'}
            </label>
          </div>

          {nervum.enabled && (
            <>
              <div
                style={{
                  padding: '10px 14px',
                  background: 'var(--info)10',
                  border: '1px solid var(--info)33',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 11,
                  color: 'var(--fg-2)',
                  marginBottom: 16,
                  lineHeight: 1.6,
                }}
              >
                SDN Controller — installed as Python package in /opt/testum/.python
              </div>

              <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
                {(['git', 'local'] as const).map((src) => (
                  <button
                    key={src}
                    onClick={() => patchNervum({ source: src })}
                    style={{
                      padding: '10px 20px',
                      background: nervum.source === src ? 'var(--info)22' : 'var(--bg-2)',
                      border: `1px solid ${nervum.source === src ? 'var(--info)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius)',
                      color: nervum.source === src ? 'var(--info)' : 'var(--fg-3)',
                      fontWeight: nervum.source === src ? 600 : 400,
                      fontSize: 13,
                    }}
                  >
                    {src === 'git' ? 'Git clone' : 'Local dir'}
                  </button>
                ))}
              </div>

              {nervum.source === 'git' && (
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
                  <Field label="Git URL">
                    <input value={nervum.git_url} onChange={(e) => patchNervum({ git_url: e.target.value })} />
                  </Field>
                  <Field label="Branch / Ref">
                    <input value={nervum.git_ref} onChange={(e) => patchNervum({ git_ref: e.target.value })} />
                  </Field>
                </div>
              )}

              {nervum.source === 'local' && (
                <Field label="Source directory path">
                  <input
                    placeholder="/path/to/nervum"
                    value={nervum.source_dir}
                    onChange={(e) => patchNervum({ source_dir: e.target.value })}
                  />
                </Field>
              )}
            </>
          )}
        </section>
      </div>

      {/* Right: env preview */}
      <div
        style={{
          width: 280,
          flexShrink: 0,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          webui.env preview
        </div>
        <pre
          className="mono"
          style={{
            margin: 0,
            fontSize: 11,
            lineHeight: 1.8,
            color: 'var(--fg-2)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            overflowY: 'auto',
            flex: 1,
          }}
        >
          {envPreview.map((line, i) => {
            const [key, ...rest] = line.split('=')
            return (
              <span key={i}>
                <span style={{ color: 'var(--info)' }}>{key}</span>
                {'='}
                <span style={{ color: 'var(--ok)' }}>{rest.join('=')}</span>
                {'\n'}
              </span>
            )
          })}
        </pre>
      </div>
    </div>
  )
}
