import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { MultiLabelToggle } from './MultiLabelToggle'
import { ScaleForm, scaleValid, toDraft, toScale } from './ScaleForm'
import { setMultiLabel, supportsMultiLabel, updateLabels, updateScale, useAnnotations, type AnnotationProject } from './store'

/** For the creator of a task: change its labels (rename, describe, add, delete) or its scale while people annotate. */
export function EditLabelsDialog({ project, open, onOpenChange }: { project: AnnotationProject; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const { answers } = useAnnotations()
  const [labels, setLabels] = useState(project.labels)
  const [multi, setMulti] = useState(!!project.multiLabel)
  const [sc, setSc] = useState(() => (project.scale ? toDraft(project.scale) : null))
  const usage: Record<string, number> = {}
  Object.values(answers[project.id] ?? {}).forEach((a) => [a.label, ...(a.spans ?? []).map((s) => s.label)].forEach((l) => l && (usage[l] = (usage[l] ?? 0) + 1)))

  const valid = sc ? scaleValid(toScale(sc)) : labelsValid(labels)
  const save = () => {
    if (sc) updateScale(project.id, toScale(sc))
    else {
      if (supportsMultiLabel(project.task)) setMultiLabel(project.id, multi)
      updateLabels(project.id, labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() })))
    }
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (o) { setLabels(project.labels); setMulti(!!project.multiLabel); setSc(project.scale ? toDraft(project.scale) : null) } onOpenChange(o) }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(sc ? 'datasets.annotation.editScale' : 'datasets.annotation.editLabels')} · {project.name}</DialogTitle>
          <DialogDescription>{t(sc ? 'datasets.annotation.editScaleHint' : 'datasets.annotation.editLabelsHint')}</DialogDescription>
        </DialogHeader>
        {/* Only the list scrolls: the title and the buttons stay in view. */}
        <div className="max-h-[55vh] overflow-y-auto pr-1">
          {sc ? <ScaleForm value={sc} onChange={setSc} /> : (
            <div className="space-y-3">
              {supportsMultiLabel(project.task) && <MultiLabelToggle value={multi} onChange={setMulti} />}
              <LabelsEditor labels={labels} onChange={setLabels} usage={usage} showKind={project.task === 'ner'} />
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
