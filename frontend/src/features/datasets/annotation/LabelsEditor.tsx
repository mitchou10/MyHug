import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LabelDialog } from './LabelDialog'
import { newLabel, type LabelDef } from './store'

export const labelsValid = (labels: LabelDef[]) => labels.length >= 2 && labels.every((l) => l.name.trim()) && new Set(labels.map((l) => l.name.trim().toLowerCase())).size === labels.length

/** The labels of a task as a compact list; each one is edited in a modal. `usage` = annotations already given with each label. */
export function LabelsEditor({ labels, onChange, usage = {}, showKind = false }: { labels: LabelDef[]; onChange: (l: LabelDef[]) => void; usage?: Record<string, number>; showKind?: boolean }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<{ label: LabelDef; isNew: boolean } | null>(null)

  const save = (l: LabelDef) => {
    onChange(editing!.isNew ? [...labels, l] : labels.map((x) => (x.id === l.id ? l : x)))
    setEditing(null)
  }

  return (
    <div className="space-y-2">
      {labels.map((l) => (
        <div key={l.id} className="flex items-center gap-2 rounded-lg border p-2.5">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium">{l.name}</span>
              {showKind && <Badge variant={l.kind === 'semantic' ? 'secondary' : 'outline'}>{t(`datasets.annotation.kinds.${l.kind ?? 'entity'}.title`)}</Badge>}
              {showKind && (l.valueType ?? 'text') !== 'text' && <Badge variant="outline">{t(`datasets.annotation.types.${l.valueType}`)}</Badge>}
              {!!l.formats?.length && <span className="font-mono text-xs text-muted-foreground">{l.formats.join(' | ')}</span>}
            </div>
            {l.description && <p className="truncate text-xs text-muted-foreground">{l.description}</p>}
            {!!usage[l.id] && <p className="text-xs text-muted-foreground">{t('datasets.annotation.usedBy', { count: usage[l.id] })}</p>}
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label={t('datasets.annotation.editLabel')} onClick={() => setEditing({ label: l, isNew: false })}><Pencil /></Button>
          <Button type="button" variant="ghost" size="icon" aria-label={t('datasets.annotation.deleteLabel')} onClick={() => onChange(labels.filter((x) => x.id !== l.id))}><Trash2 /></Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => setEditing({ label: newLabel(), isNew: true })}><Plus />{t('datasets.annotation.addLabel')}</Button>
      {!labelsValid(labels) && <p className="text-xs text-muted-foreground">{t('datasets.annotation.labelsHint')}</p>}

      {editing && (
        <LabelDialog key={editing.label.id} label={editing.label} isNew={editing.isNew} ner={showKind} takenNames={labels.filter((x) => x.id !== editing.label.id).map((x) => x.name)} onSave={save} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}
