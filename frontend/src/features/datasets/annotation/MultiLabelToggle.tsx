import { useTranslation } from 'react-i18next'

/** Lets an item get several labels instead of one. */
export function MultiLabelToggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm">
      <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={value} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="font-medium">{t('datasets.annotation.multiLabel.title')}</span>
        <span className="block text-xs text-muted-foreground">{t('datasets.annotation.multiLabel.hint')}</span>
      </span>
    </label>
  )
}
