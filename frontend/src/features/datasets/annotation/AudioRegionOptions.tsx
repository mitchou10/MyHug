import { useTranslation } from 'react-i18next'
import { StringListInput } from './StringListInput'

/** Audio: annotate the whole clip or stretches of it, and name the tracks the stretches are placed on. */
export function AudioRegionOptions({ canChoose, regions, onRegions, tracks, onTracks }: {
  /** False when the task always uses regions (segments, transcription). */
  canChoose: boolean; regions: boolean; onRegions: (v: boolean) => void; tracks: string[]; onTracks: (t: string[]) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      {canChoose && (
        <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={regions} onChange={(e) => onRegions(e.target.checked)} />
          <span>
            <span className="font-medium">{t('datasets.annotation.audio.regionsToggle.title')}</span>
            <span className="block text-xs text-muted-foreground">{t('datasets.annotation.audio.regionsToggle.hint')}</span>
          </span>
        </label>
      )}
      {regions && (
        <div className="space-y-1.5">
          <h3 className="text-sm font-medium">{t('datasets.annotation.audio.tracks')}</h3>
          <StringListInput value={tracks} onChange={onTracks} label={t('datasets.annotation.audio.tracks')} placeholder={t('datasets.annotation.audio.tracksPlaceholder')} />
          <p className="text-xs text-muted-foreground">{t('datasets.annotation.audio.tracksHint')}</p>
        </div>
      )}
    </div>
  )
}
