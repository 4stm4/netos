import React, { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { useSaveProfile, startBuild, openBuildEventSource } from '../api'
import { StatusBadge } from '../components/StatusBadge'

interface CheckItem {
  id: string
  label: string
  ok: boolean
  warn?: boolean
  message?: string
}

interface BuildEvent {
  event: string
  data: string
  stage: string
  build_id: string
}

const STAGES = ['init', 'host_deps', 'kernel', 'buildroot', 'rootfs_overlay', 'nervum_install', 'image', 'boot_test']
const STAGE_LABELS: Record<string, string> = {
  init: 'Initializing',
  host_deps: 'Host deps',
  kernel: 'Kernel',
  buildroot: 'Buildroot',
  rootfs_overlay: 'Rootfs overlay',
  nervum_install: 'Nervum install',
  image: 'Image',
  boot_test: 'Boot test',
}

const ETA_MINUTES: Record<string, string> = {
  'qemu-virt': '60–90 min',
  pi4: '90–150 min',
  pi5: '90–150 min',
  zero2w: '90–150 min',
}

const TARGET_ARTIFACTS: Record<string, string[]> = {
  'qemu-virt': ['qemu-virt.img', 'temp/rpi_linux/arch/arm64/boot/Image'],
  pi4: ['raspi-pi4.img'],
  pi5: ['raspi.img'],
  zero2w: ['raspi-zero2w.img'],
}

function usePreflightChecks() {
  const { profile } = useStore()

  const checks: CheckItem[] = []

  // 1. ID slug
  const idOk = /^[a-z0-9-]+$/.test(profile.branding.id)
  checks.push({ id: 'id_slug', label: 'Branding ID is valid slug', ok: idOk, message: idOk ? undefined : 'Must match ^[a-z0-9-]+$' })

  // 2. Hostname
  const hostnameOk = /^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$/.test(profile.branding.hostname)
  checks.push({ id: 'hostname', label: 'Hostname is valid', ok: hostnameOk, message: hostnameOk ? undefined : 'Must match ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$' })

  // 3. rootfs > 0
  const rootfs = profile.image.size_mb - profile.image.boot_mb
  const sizeOk = rootfs > 0
  checks.push({ id: 'rootfs_size', label: 'rootfs size > 0', ok: sizeOk, message: sizeOk ? undefined : `rootfs = ${rootfs} MB — increase image size or reduce boot partition` })

  // 4. rootfs < limit (3700 MB for non-qemu)
  const sizeLimitMb = profile.target === 'qemu-virt' ? 4000 : 3700
  const sizeLimit = profile.image.size_mb <= sizeLimitMb
  checks.push({ id: 'size_limit', label: `Image size within limit (${sizeLimitMb} MB)`, ok: sizeLimit, message: sizeLimit ? undefined : `Image size ${profile.image.size_mb} MB exceeds ${sizeLimitMb} MB` })

  // 5. Wi-Fi country set if ssid given on zero2w
  if (profile.target === 'zero2w' && profile.network.wifi.ssid) {
    const wifiCountryOk = profile.network.wifi.country.length === 2
    checks.push({ id: 'wifi_country', label: 'Wi-Fi country code set (2 chars)', ok: wifiCountryOk, message: wifiCountryOk ? undefined : 'Country must be a 2-letter code (e.g. US, DE)' })
  }

  // 6. Version semver
  const versionOk = /^\d+\.\d+\.\d+/.test(profile.branding.version)
  checks.push({ id: 'version', label: 'Version is semver', ok: versionOk, message: versionOk ? undefined : 'Use format x.y.z' })

  // 7. Wi-Fi SSID set on non-zero2w target — warn
  if (profile.network.wifi.ssid && profile.target !== 'zero2w') {
    checks.push({
      id: 'wifi_target_warn',
      label: 'Wi-Fi provisioning target',
      ok: true,
      warn: true,
      message: `Wi-Fi provisioning applies only to zero2w — SSID will be ignored for ${profile.target}`,
    })
  }

  // 8. Root password empty — warn
  if (!profile.branding.root_password) {
    checks.push({
      id: 'root_password_warn',
      label: 'Root password not set',
      ok: true,
      warn: true,
      message: 'Root is accessible without a password (dev mode)',
    })
  }

  // 9. Nervum enabled with local source but empty dir — error
  if (profile.nervum.enabled && profile.nervum.source === 'local' && !profile.nervum.source_dir) {
    checks.push({
      id: 'nervum_local_dir',
      label: 'Nervum local source directory',
      ok: false,
      message: 'Nervum source=local but source_dir is empty — set a path or switch to Git',
    })
  }

  const hasErrors = checks.some((c) => !c.ok)
  return { checks, hasErrors }
}

export function Step05Build() {
  const { profile, profileName } = useStore()
  const saveMutation = useSaveProfile()
  const { checks, hasErrors } = usePreflightChecks()
  const [buildId, setBuildId] = useState<string | null>(null)
  const [buildStatus, setBuildStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [currentStage, setCurrentStage] = useState<string>('init')
  const [logs, setLogs] = useState<string[]>([])
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  // Autoscroll
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  async function handleStartBuild() {
    setLogs([])
    setErrorMsg(null)
    setBuildStatus('running')
    setCurrentStage('init')

    // Save profile first
    await new Promise<void>((resolve) => {
      saveMutation.mutate(
        { name: profileName, data: profile },
        { onSettled: () => resolve() }
      )
    })

    let id: string
    try {
      const result = await startBuild(profileName)
      id = result.build_id
      setBuildId(id)
    } catch (e: unknown) {
      setBuildStatus('error')
      setErrorMsg(e instanceof Error ? e.message : String(e))
      return
    }

    const es = openBuildEventSource(id)
    esRef.current = es

    es.onmessage = (ev) => {
      try {
        const parsed: BuildEvent = JSON.parse(ev.data)
        if (parsed.event === 'log' || parsed.event === 'make_progress') {
          setLogs((prev) => [...prev, parsed.data])
        }
        if (parsed.event === 'stage') {
          setCurrentStage(parsed.stage)
        }
        if (parsed.event === 'done') {
          setBuildStatus('done')
          setCurrentStage('boot_test')
          es.close()
        }
        if (parsed.event === 'error') {
          setBuildStatus('error')
          setErrorMsg(parsed.data)
          es.close()
        }
      } catch {
        setLogs((prev) => [...prev, ev.data])
      }
    }

    es.onerror = () => {
      setBuildStatus('error')
      setErrorMsg('Connection to build stream lost.')
      es.close()
    }
  }

  const stageIdx = STAGES.indexOf(currentStage)
  const progressPct = buildStatus === 'done'
    ? 100
    : buildStatus === 'idle'
    ? 0
    : Math.round(((stageIdx + 1) / STAGES.length) * 85)

  const packageCount = profile.packages.enabled.length + profile.packages.custom.length
  const rootfs = profile.image.size_mb - profile.image.boot_mb
  const artifacts = TARGET_ARTIFACTS[profile.target] ?? [`${profile.target}.img`]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, height: '100%', overflow: 'hidden' }}>

      {/* Top: stat cards */}
      <div style={{ display: 'flex', gap: 12, flexShrink: 0 }}>
        {[
          { label: 'Target', value: profile.target },
          { label: 'Image', value: `${profile.image.size_mb} MB (rootfs ${rootfs} MB)` },
          { label: 'Packages', value: `${packageCount} selected` },
          { label: 'ETA', value: ETA_MINUTES[profile.target] ?? '~60 min' },
        ].map((s) => (
          <div
            key={s.label}
            style={{
              flex: 1,
              padding: '14px 16px',
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
              {s.label}
            </div>
            <div className="mono" style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg)' }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Pre-flight checklist + build button */}
      <div style={{ display: 'flex', gap: 16, flexShrink: 0 }}>
        <div
          style={{
            flex: 1,
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Pre-flight checks
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {checks.map((c) => {
              const icon = c.ok ? (c.warn ? '!' : '+') : 'x'
              const iconColor = c.ok ? (c.warn ? 'var(--warn)' : 'var(--ok)') : 'var(--err)'
              return (
                <div key={c.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <span
                    className="mono"
                    style={{ color: iconColor, fontSize: 13, marginTop: 1, flexShrink: 0, fontWeight: 700 }}
                  >
                    [{icon}]
                  </span>
                  <div>
                    <div style={{ fontSize: 12, color: c.ok ? 'var(--fg-2)' : 'var(--fg)' }}>{c.label}</div>
                    {c.message && (
                      <div style={{ fontSize: 11, color: c.ok ? 'var(--warn)' : 'var(--err)', marginTop: 2 }}>{c.message}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, justifyContent: 'center', minWidth: 200 }}>
          {buildStatus !== 'idle' && (
            <div style={{ textAlign: 'center' }}>
              <StatusBadge
                status={buildStatus === 'done' ? 'done' : buildStatus === 'error' ? 'error' : 'running'}
              />
            </div>
          )}
          <button
            onClick={handleStartBuild}
            disabled={hasErrors || buildStatus === 'running'}
            style={{
              padding: '14px 24px',
              fontSize: 14,
              fontWeight: 700,
              background: hasErrors || buildStatus === 'running'
                ? 'var(--border)'
                : buildStatus === 'done'
                ? 'var(--ok)'
                : 'var(--info)',
              color: hasErrors ? 'var(--fg-3)' : '#fff',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: hasErrors || buildStatus === 'running' ? 'not-allowed' : 'pointer',
              transition: 'background 0.2s',
            }}
          >
            {buildStatus === 'running'
              ? 'Building…'
              : buildStatus === 'done'
              ? 'Build again'
              : buildStatus === 'error'
              ? 'Retry build'
              : 'Start Build'}
          </button>
          {hasErrors && (
            <div style={{ fontSize: 11, color: 'var(--err)', textAlign: 'center' }}>
              Fix pre-flight errors first
            </div>
          )}
          {buildId && (
            <div style={{ fontSize: 10, color: 'var(--fg-3)', textAlign: 'center' }} className="mono">
              ID: {buildId}
            </div>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {buildStatus !== 'idle' && (
        <div style={{ flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {STAGES.map((s, i) => {
              const active = s === currentStage && buildStatus === 'running'
              const done = (buildStatus === 'done') || (stageIdx > i)
              return (
                <div key={s} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div
                    style={{
                      height: 3,
                      borderRadius: 99,
                      background: done
                        ? 'var(--ok)'
                        : active
                        ? 'var(--info)'
                        : 'var(--border)',
                      transition: 'background 0.3s',
                    }}
                  />
                  <div style={{ fontSize: 9, color: active ? 'var(--info)' : done ? 'var(--ok)' : 'var(--fg-3)', textAlign: 'center', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {STAGE_LABELS[s]}
                  </div>
                </div>
              )
            })}
          </div>
          <div style={{ fontSize: 11, color: 'var(--fg-3)' }}>
            {progressPct}% — stage: <span style={{ color: 'var(--fg)' }}>{STAGE_LABELS[currentStage] ?? currentStage}</span>
          </div>
        </div>
      )}

      {/* Artifacts block shown after successful build */}
      {buildStatus === 'done' && (
        <div
          style={{
            flexShrink: 0,
            background: 'var(--ok)12',
            border: '1px solid var(--ok)44',
            borderRadius: 'var(--radius)',
            padding: '14px 16px',
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ok)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Build artifacts
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {artifacts.map((path) => (
              <div key={path} className="mono" style={{ fontSize: 12, color: 'var(--fg-2)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: 'var(--ok)', fontWeight: 700 }}>+</span>
                <span>{path}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Build log */}
      {(buildStatus !== 'idle' || logs.length > 0) && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--fg-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8, flexShrink: 0 }}>
            Build log
          </div>
          <div
            ref={logRef}
            style={{
              flex: 1,
              overflowY: 'auto',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '12px 16px',
              fontFamily: 'monospace',
              fontSize: 11,
              lineHeight: 1.6,
              color: 'var(--fg-2)',
            }}
          >
            {logs.map((line, i) => {
              const isErr = line.includes('ERROR') || line.includes('error:') || line.includes('FAILED')
              const isWarn = line.includes('WARNING') || line.includes('warning:')
              const isMake = line.startsWith('>>>')
              return (
                <div
                  key={i}
                  style={{
                    color: isErr
                      ? 'var(--err)'
                      : isWarn
                      ? 'var(--warn)'
                      : isMake
                      ? 'var(--info)'
                      : 'var(--fg-2)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}
                >
                  {line}
                </div>
              )
            })}
            {errorMsg && (
              <div style={{ color: 'var(--err)', marginTop: 8, fontWeight: 600 }}>
                ERROR: {errorMsg}
              </div>
            )}
            {buildStatus === 'done' && (
              <div style={{ color: 'var(--ok)', marginTop: 8, fontWeight: 600 }}>
                Build completed successfully.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
