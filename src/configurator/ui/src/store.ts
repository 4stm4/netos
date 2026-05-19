import { create } from 'zustand'

export interface BrandingConfig {
  name: string
  id: string
  version: string
  hostname: string
}

export interface Eth0Config {
  mode: 'dhcp' | 'static' | 'disabled'
  address: string
  gateway: string
  dns: string
}

export interface WifiConfig {
  country: string
  ssid: string
  psk: string
  bootstrap: boolean
}

export interface NetworkConfig {
  eth0: Eth0Config
  wifi: WifiConfig
}

export interface PackagesConfig {
  enabled: string[]
  custom: string[]
}

export interface WebUIConfig {
  source: 'git' | 'local' | 'runtime'
  git_url: string
  git_ref: string
  source_dir: string
  port: number
  data_dir: string
  database_url: string
  pip_mode: 'never' | 'auto'
  admin_username: string
  admin_password: string
  health_path: string
  app_module: string
}

export interface ImageConfig {
  size_mb: number
  boot_mb: number
}

export interface Profile {
  name: string
  target: string
  branding: BrandingConfig
  network: NetworkConfig
  packages: PackagesConfig
  webui: WebUIConfig
  image: ImageConfig
}

const DEFAULT_PROFILE: Profile = {
  name: 'default',
  target: 'qemu-virt',
  branding: {
    name: '4stm4 netOS',
    id: '4stm4-netos',
    version: '0.1.0',
    hostname: '4stm4-netos',
  },
  network: {
    eth0: { mode: 'dhcp', address: '', gateway: '', dns: '' },
    wifi: { country: 'US', ssid: '', psk: '', bootstrap: true },
  },
  packages: { enabled: [], custom: [] },
  webui: {
    source: 'git',
    git_url: 'https://github.com/4stm4/testum.git',
    git_ref: 'main',
    source_dir: '',
    port: 8080,
    data_dir: '/opt/testum',
    database_url: 'sqlite:////opt/testum/testum.db',
    pip_mode: 'never',
    admin_username: 'admin',
    admin_password: '',
    health_path: '/health',
    app_module: 'app.main:app',
  },
  image: { size_mb: 512, boot_mb: 64 },
}

interface WizardState {
  currentStep: number
  profileName: string
  profile: Profile
  setStep: (n: number) => void
  updateProfile: (patch: Partial<Profile>) => void
  setProfileName: (name: string) => void
  loadProfile: (p: Profile) => void
}

export const useStore = create<WizardState>((set) => ({
  currentStep: 0,
  profileName: 'default',
  profile: structuredClone(DEFAULT_PROFILE),
  setStep: (n) => set({ currentStep: n }),
  updateProfile: (patch) =>
    set((s) => ({ profile: { ...s.profile, ...patch } })),
  setProfileName: (name) =>
    set((s) => ({ profileName: name, profile: { ...s.profile, name } })),
  loadProfile: (p) => set({ profile: p, profileName: p.name }),
}))
