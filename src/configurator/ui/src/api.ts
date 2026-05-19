import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Profile } from './store'

const BASE = '/api'

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Targets ─────────────────────────────────────────────────────────────────

export interface TargetInfo {
  name: string
  description: string
  kernel_defconfig: string
  kernel_filename: string
  image_name: string
  image_size_mb: number
  boot_size_mb: number
  boot_cmdline: string
  qemu_machine: string | null
  qemu_cpu: string | null
  qemu_root_device: string | null
  qemu_supported: boolean
  install_boot_files: boolean
  build_kernel_modules: boolean
  kernel_config_options: string[]
  buildroot_package_lines: string[]
  status: 'verified' | 'wip'
}

export function useTargets() {
  return useQuery({
    queryKey: ['targets'],
    queryFn: () => fetchJSON<Record<string, TargetInfo>>(`${BASE}/targets`),
  })
}

// ── Packages ─────────────────────────────────────────────────────────────────

export interface PackageEntry {
  key: string
  name: string
  description: string
  size_kb: number
  required?: boolean
}

export interface PackageCategory {
  id: string
  name: string
  packages: PackageEntry[]
}

export interface PackagesCatalogue {
  categories: PackageCategory[]
}

export function usePackages() {
  return useQuery({
    queryKey: ['packages'],
    queryFn: () => fetchJSON<PackagesCatalogue>(`${BASE}/packages`),
  })
}

// ── Profiles ─────────────────────────────────────────────────────────────────

export interface ProfileSummary {
  name: string
  target: string
  version: string
}

export function useProfiles() {
  return useQuery({
    queryKey: ['profiles'],
    queryFn: () => fetchJSON<ProfileSummary[]>(`${BASE}/profiles`),
  })
}

export function useProfile(name: string, enabled = true) {
  return useQuery({
    queryKey: ['profiles', name],
    queryFn: () => fetchJSON<Profile>(`${BASE}/profiles/${name}`),
    enabled,
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, data }: { name: string; data: Profile }) =>
      fetchJSON<Profile>(`${BASE}/profiles/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profiles'] })
    },
  })
}

export function useDeleteProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      fetchJSON<{ deleted: string }>(`${BASE}/profiles/${name}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profiles'] })
    },
  })
}

export async function dryRun(name: string): Promise<string> {
  const res = await fetch(`${BASE}/profiles/${name}/dry-run`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.text()
}

// ── Builds ────────────────────────────────────────────────────────────────────

export interface BuildStartResult {
  build_id: string
  target: string
}

export async function startBuild(profileName: string): Promise<BuildStartResult> {
  return fetchJSON<BuildStartResult>(`${BASE}/profiles/${profileName}/build`, {
    method: 'POST',
  })
}

export function openBuildEventSource(buildId: string): EventSource {
  return new EventSource(`${BASE}/builds/${buildId}/events`)
}
