import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Scale } from './store'

/** Gives a number on a scale: a slider and a field that stay in sync, and the legend of both ends. */
export function ScaleInput({ scale, value, onChange }: { scale: Scale; value?: number; onChange: (v: number | undefined) => void }) {
  const { t } = useTranslation()
  const clamp = (n: number) => Math.min(scale.max, Math.max(scale.min, n))
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Input type="number" className="w-32 font-mono" aria-label={t('datasets.annotation.scale.value')} min={scale.min} max={scale.max} step={scale.step}
          value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? undefined : clamp(Number(e.target.value)))} />
        {scale.unit && <span className="text-sm text-muted-foreground">{scale.unit}</span>}
        {value !== undefined && <Button variant="ghost" size="sm" className="ml-auto" onClick={() => onChange(undefined)}>{t('datasets.annotation.scale.clear')}</Button>}
      </div>
      <input type="range" className="w-full accent-primary" aria-label={t('datasets.annotation.scale.value')} min={scale.min} max={scale.max} step={scale.step}
        value={value ?? (scale.min + scale.max) / 2} onChange={(e) => onChange(Number(e.target.value))} />
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{scale.min}{scale.minLabel && ` · ${scale.minLabel}`}</span>
        <span>{scale.maxLabel && `${scale.maxLabel} · `}{scale.max}</span>
      </div>
    </div>
  )
}
