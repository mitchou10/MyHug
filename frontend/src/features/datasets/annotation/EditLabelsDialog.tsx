import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { getDataset } from '../mockData'
import { AudioRegionOptions } from './AudioRegionOptions'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { MultiLabelToggle } from './MultiLabelToggle'
import { ScaleForm, scaleValid, toDraft, toScale } from './ScaleForm'
import { DEFAULT_TRACKS, patchProject, supportsMultiLabel, useAnnotations, usesRegions, type AnnotationProject } from './store'

/** For the creator of a task: change what annotators work with (labels, scale, tracks) while they annotate. */
export function EditLabelsDialog({ project, open, onOpenChange }: { project: AnnotationProject; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const { answers } = useAnnotations()
  const [owner, name] = project.datasetKey.split('/')
  const modality = getDataset(owner, name)?.modality
  const isAudio = (modality === 'audio' || modality === 'video') && project.task !== 'video_tracking' // timed, with regions
  const kind = project.task.replace(/^(audio|video)_/, '')
  const canChoose = isAudio && (kind === 'classification' || kind === 'caption' || project.task === 'regression')
  const optionalLabels = project.task === 'audio_transcription'

  const initial = () => ({ labels: project.labels, multi: !!project.multiLabel, sc: project.scale ? toDraft(project.scale) : null, regions: usesRegions(project), tracks: project.tracks?.length ? project.tracks : DEFAULT_TRACKS })
  const [f, setF] = useState(initial)
  const set = (p: Partial<ReturnType<typeof initial>>) => setF({ ...f, ...p })

  const usage: Record<string, number> = {}
  Object.values(answers[project.id] ?? {}).forEach((a) => [a.label, ...(a.labels ?? []), ...(a.spans ?? []).map((s) => s.label), ...(a.segments ?? []).flatMap((s) => [s.label, ...(s.labels ?? [])])].forEach((l) => l && (usage[l] = (usage[l] ?? 0) + 1)))

  const showLabels = project.labels.length > 0 || optionalLabels
  const valid = (!f.sc || scaleValid(toScale(f.sc))) && (!showLabels || (optionalLabels && f.labels.length === 0) || labelsValid(f.labels)) && (!f.regions || f.tracks.length > 0)
  const save = () => {
    patchProject(project.id, {
      ...(showLabels ? { labels: f.labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() })) } : {}),
      ...(f.sc ? { scale: toScale(f.sc) } : {}),
      ...(supportsMultiLabel(project.task) ? { multiLabel: f.multi } : {}),
      ...(isAudio ? { granularity: canChoose ? (f.regions ? 'regions' as const : 'clip' as const) : project.granularity, tracks: f.regions ? f.tracks : project.tracks } : {}),
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (o) setF(initial()); onOpenChange(o) }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('datasets.annotation.editTask')} · {project.name}</DialogTitle>
          <DialogDescription>{t(f.sc && !showLabels ? 'datasets.annotation.editScaleHint' : 'datasets.annotation.editLabelsHint')}</DialogDescription>
        </DialogHeader>
        {/* Only the content scrolls: the title and the buttons stay in view. */}
        <div className="max-h-[55vh] space-y-4 overflow-y-auto pr-1">
          {isAudio && <AudioRegionOptions canChoose={canChoose} regions={f.regions} onRegions={(regions) => set({ regions })} tracks={f.tracks} onTracks={(tracks) => set({ tracks })} />}
          {f.sc && <ScaleForm value={f.sc} onChange={(sc) => set({ sc })} />}
          {showLabels && (
            <div className="space-y-3">
              {supportsMultiLabel(project.task) && <MultiLabelToggle value={f.multi} onChange={(multi) => set({ multi })} />}
              <LabelsEditor labels={f.labels} onChange={(labels) => set({ labels })} usage={usage} showKind={project.task === 'ner'} />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!valid} onClick={save}>{t('datasets.annotation.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
