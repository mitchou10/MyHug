import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { VALUE_TYPES, type ValueType } from './format'
import { StringListInput } from './StringListInput'
import type { LabelDef } from './store'

/** One label in a modal: name, description and, for entity extraction, kind, value type, formats and examples. */
export function LabelDialog({ label, isNew, ner, takenNames, onSave, onClose }: {
  label: LabelDef; isNew: boolean; ner: boolean; takenNames: string[]; onSave: (l: LabelDef) => void; onClose: () => void
}) {
  const { t } = useTranslation()
  const [l, setL] = useState(label)
  const patch = (p: Partial<LabelDef>) => setL({ ...l, ...p })
  const name = l.name.trim()
  const duplicate = takenNames.some((n) => n.trim().toLowerCase() === name.toLowerCase())
  const kind = l.kind ?? 'entity'

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(isNew ? 'datasets.annotation.addLabel' : 'datasets.annotation.editLabel')}</DialogTitle>
          <DialogDescription>{t('datasets.annotation.labelDialogHint')}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto px-0.5 pr-2">
          <div className="space-y-1.5">
            <Label htmlFor="lb-name">{t('datasets.annotation.labelName')}</Label>
            <Input id="lb-name" autoFocus value={l.name} onChange={(e) => patch({ name: e.target.value })} aria-invalid={duplicate} />
            {duplicate && <p className="text-xs text-destructive">{t('datasets.annotation.labelDuplicate')}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="lb-desc">{t('datasets.annotation.labelDescription')}</Label>
            <Textarea id="lb-desc" rows={2} value={l.description} onChange={(e) => patch({ description: e.target.value })} />
          </div>

          {ner && (
            <>
              <div className="space-y-1.5">
                <Label>{t('datasets.annotation.kind')}</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(['entity', 'semantic'] as const).map((k) => (
                    <button key={k} type="button" aria-pressed={kind === k} onClick={() => patch({ kind: k })}
                      className={cn('rounded-lg border p-2.5 text-left text-sm transition-colors hover:bg-muted/50', kind === k && 'border-primary bg-muted/50')}>
                      <div className="font-medium">{t(`datasets.annotation.kinds.${k}.title`)}</div>
                      <div className="text-xs text-muted-foreground">{t(`datasets.annotation.kinds.${k}.hint`)}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="lb-type">{t('datasets.annotation.valueType')}</Label>
                <select id="lb-type" value={l.valueType ?? 'text'} onChange={(e) => patch({ valueType: e.target.value as ValueType })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                  {VALUE_TYPES.map((v) => <option key={v} value={v}>{t(`datasets.annotation.types.${v}`)}</option>)}
                </select>
              </div>

              <div className="space-y-1.5">
                <Label>{t('datasets.annotation.formats')}</Label>
                <StringListInput mono value={l.formats ?? []} onChange={(formats) => patch({ formats })} label={t('datasets.annotation.formats')}
                  placeholder={t(l.valueType === 'date' ? 'datasets.annotation.formatDate' : 'datasets.annotation.formatOther')} />
                <p className="text-xs text-muted-foreground">{t(l.valueType === 'date' ? 'datasets.annotation.formatHelpDate' : 'datasets.annotation.formatHelp')}</p>
              </div>

              <div className="space-y-1.5">
                <Label>{t('datasets.annotation.examples')}</Label>
                <StringListInput value={l.examples ?? []} onChange={(examples) => patch({ examples })} label={t('datasets.annotation.examples')} placeholder={t('datasets.annotation.examplesPlaceholder')} />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('datasets.annotation.cancel')}</Button>
          <Button disabled={!name || duplicate} onClick={() => onSave({ ...l, name, description: l.description.trim() })}>{t('datasets.annotation.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
