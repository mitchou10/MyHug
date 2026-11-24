import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Scale } from './store'

/** The scale as the text typed in the fields (so a field can be empty while typing). */
export interface ScaleDraft { min: string; max: string; step: string; unit: string; minLabel: string; maxLabel: string }

export const emptyScale: ScaleDraft = { min: '0', max: '10', step: '1', unit: '', minLabel: '', maxLabel: '' }
export const toDraft = (s: Scale): ScaleDraft => ({ min: String(s.min), max: String(s.max), step: String(s.step), unit: s.unit ?? '', minLabel: s.minLabel ?? '', maxLabel: s.maxLabel ?? '' })
const num = (v: string) => (v.trim() === '' ? NaN : Number(v))
export const toScale = (d: ScaleDraft): Scale => ({ min: num(d.min), max: num(d.max), step: num(d.step), unit: d.unit.trim() || undefined, minLabel: d.minLabel.trim() || undefined, maxLabel: d.maxLabel.trim() || undefined })
export const scaleValid = (s: Scale) => Number.isFinite(s.min) && Number.isFinite(s.max) && s.min < s.max && s.step > 0

/** min, max, step, unit and the legend of both ends. */
export function ScaleForm({ value, onChange }: { value: ScaleDraft; onChange: (v: ScaleDraft) => void }) {
  const { t } = useTranslation()
  const field = (k: keyof ScaleDraft, label: string, props: { type?: string; placeholder?: string } = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`sc-${k}`}>{label}</Label>
      <Input id={`sc-${k}`} value={value[k]} onChange={(e) => onChange({ ...value, [k]: e.target.value })} {...props} />
    </div>
  )
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        {field('min', t('datasets.annotation.scale.min'), { type: 'number' })}
        {field('max', t('datasets.annotation.scale.max'), { type: 'number' })}
        {field('step', t('datasets.annotation.scale.step'), { type: 'number' })}
      </div>
      {field('unit', t('datasets.annotation.scale.unit'), { placeholder: '€, m², pts…' })}
      <div className="grid grid-cols-2 gap-3">
        {field('minLabel', t('datasets.annotation.scale.minLabel'))}
        {field('maxLabel', t('datasets.annotation.scale.maxLabel'))}
      </div>
      {!scaleValid(toScale(value)) && <p className="text-xs text-destructive">{t('datasets.annotation.scale.invalid')}</p>}
    </div>
  )
}
