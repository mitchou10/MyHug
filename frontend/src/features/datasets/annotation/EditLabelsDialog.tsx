import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { LabelsEditor, labelsValid } from './LabelsEditor'
import { updateLabels, useAnnotations, type AnnotationProject } from './store'

/** For the creator of a task: change the labels (rename, describe, add, delete) while people annotate. */
export function EditLabelsDialog({ project, open, onOpenChange }: { project: AnnotationProject; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const { answers } = useAnnotations()
  const [labels, setLabels] = useState(project.labels)
  const usage: Record<string, number> = {}
  Object.values(answers[project.id] ?? {}).forEach((a) => [a.label, ...(a.spans ?? []).map((s) => s.label)].forEach((l) => l && (usage[l] = (usage[l] ?? 0) + 1)))

  return (
    <Dialog open={open} onOpenChange={(o) => { if (o) setLabels(project.labels); onOpenChange(o) }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('datasets.annotation.editLabels')} · {project.name}</DialogTitle>
          <DialogDescription>{t('datasets.annotation.editLabelsHint')}</DialogDescription>
        </DialogHeader>
        <LabelsEditor labels={labels} onChange={setLabels} usage={usage} showKind={project.task === 'ner'} />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!labelsValid(labels)} onClick={() => { updateLabels(project.id, labels.map((l) => ({ ...l, name: l.name.trim(), description: l.description.trim() }))); onOpenChange(false) }}>{t('datasets.annotation.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
