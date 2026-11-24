import { X } from 'lucide-react'
import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** A list of short strings as removable chips: type one, press Enter to add it. */
export function StringListInput({ value, onChange, placeholder, label, mono }: { value: string[]; onChange: (v: string[]) => void; placeholder: string; label: string; mono?: boolean }) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const v = draft.trim()
    if (v && !value.includes(v)) onChange([...value, v])
    setDraft('')
  }
  return (
    <div className="space-y-1.5">
      {!!value.length && (
        <div className="flex flex-wrap gap-1">
          {value.map((v) => (
            <span key={v} className={cn('flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs', mono && 'font-mono')}>
              {v}
              <button type="button" aria-label={`remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}><X className="size-3" /></button>
            </span>
          ))}
        </div>
      )}
      <Input aria-label={label} placeholder={placeholder} className={cn(mono && 'font-mono')} value={draft} onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} onBlur={add} />
    </div>
  )
}
