import React, { useEffect, useRef } from 'react'
import { useStore } from './store'
import { useSaveProfile } from './api'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import { Step01Target } from './steps/Step01Target'
import { Step02Branding } from './steps/Step02Branding'
import { Step03Packages } from './steps/Step03Packages'
import { Step04WebUI } from './steps/Step04WebUI'
import { Step05Build } from './steps/Step05Build'

const STEPS = [Step01Target, Step02Branding, Step03Packages, Step04WebUI, Step05Build]
const STEP_NAMES = ['Target', 'Branding & Network', 'Packages', 'Web UI', 'Build']

function useAutosave() {
  const { profile, profileName } = useStore()
  const saveMutation = useSaveProfile()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevProfileRef = useRef<string>('')

  useEffect(() => {
    const serialized = JSON.stringify(profile)
    if (serialized === prevProfileRef.current) return
    prevProfileRef.current = serialized

    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      saveMutation.mutate({ name: profileName, data: profile })
    }, 1500)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [profile, profileName]) // saveMutation deliberately omitted — stable reference
}

export default function App() {
  const { currentStep, setStep } = useStore()
  useAutosave()

  const StepComponent = STEPS[currentStep]

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
      }}
    >
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar />

        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Step content */}
          <div
            style={{
              flex: 1,
              padding: '24px',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <StepComponent />
          </div>

          {/* Bottom navigation */}
          <div
            style={{
              borderTop: '1px solid var(--border)',
              padding: '14px 24px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'var(--bg-1)',
              flexShrink: 0,
            }}
          >
            <div style={{ fontSize: 12, color: 'var(--fg-3)' }}>
              Step {currentStep + 1} of {STEPS.length} — {STEP_NAMES[currentStep]}
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              {currentStep > 0 && (
                <button
                  onClick={() => setStep(currentStep - 1)}
                  style={{
                    padding: '8px 20px',
                    background: 'var(--bg-2)',
                    color: 'var(--fg-2)',
                    borderColor: 'var(--border)',
                  }}
                >
                  Back
                </button>
              )}
              {currentStep < STEPS.length - 1 && (
                <button
                  onClick={() => setStep(currentStep + 1)}
                  style={{
                    padding: '8px 20px',
                    background: 'var(--info)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  Next
                </button>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
