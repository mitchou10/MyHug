import { Play } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { usePredict } from '../api/serving'
import type { Model, Serving } from '../types'

const SAMPLE_TEXT = 'Un film magnifique, je recommande vivement ce chef-d’œuvre !'

/** What the relay says when it cannot give an answer, in a sentence for the page (the key of `models.widget.errors`). */
export function predictProblem(error: unknown): string {
  if (!(error instanceof ApiError)) return 'network'
  const known: Record<number, string> = { 409: 'notServed', 413: 'tooLarge', 422: 'rejected', 429: 'tooMany', 502: 'badAnswer', 503: 'down', 504: 'slow' }
  return known[error.status] ?? 'failed'
}

interface Scored { label: string; score: number }

const isScored = (x: unknown): x is Scored => !!x && typeof x === 'object' && typeof (x as Scored).label === 'string' && typeof (x as Scored).score === 'number'

/** What came back, shown as what the model declared it gives: bars for labels, a sentence for a text, JSON otherwise. */
export function Output({ output, kind }: { output: unknown; kind: Serving['output'] }) {
  if (kind === 'labels' && Array.isArray(output) && output.length && output.every(isScored)) {
    const items = [...output].sort((a, b) => b.score - a.score)
    return (
      <div className="space-y-1.5">
        {items.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-sm">
            <span className="w-24 truncate">{s.label}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${Math.min(1, Math.max(0, s.score)) * 100}%` }} /></div>
            <span className="w-12 text-right font-mono text-xs">{Math.round(s.score * 100)} %</span>
          </div>
        ))}
      </div>
    )
  }
  if (kind === 'text' && typeof output === 'string') return <p className="text-sm whitespace-pre-wrap">{output}</p>
  if (kind === 'values' && typeof output === 'number') return <p className="font-mono text-2xl">{output}</p>
  return <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{JSON.stringify(output, null, 2)}</pre>
}

/** "Try it": give an input to a model and see what it answers. The platform relays it: nothing runs here. */
export function ModelWidget({ model, serving }: { model: Model; serving: Serving }) {
  const { t } = useTranslation()
  const predict = usePredict(model.owner, model.name)
  const [text, setText] = useState(serving.input === 'text' ? SAMPLE_TEXT : '')
  const [broken, setBroken] = useState(false)

  const asText = serving.input === 'text'
  // What the model takes is a text, or whatever the editor documented (a JSON value): a file is not sent from here.
  const run = () => {
    setBroken(false)
    if (asText) return predict.mutate(text)
    try {
      predict.mutate(JSON.parse(text))
    } catch {
      setBroken(true)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t(asText ? 'models.widget.hint' : 'models.widget.hintJson')}</p>
      <Textarea rows={asText ? 3 : 5} className={asText ? '' : 'font-mono text-xs'} value={text} aria-label={t(asText ? 'models.widget.input' : 'models.widget.inputJson')}
        onChange={(e) => { setText(e.target.value); predict.reset(); setBroken(false) }} />
      <Button onClick={run} disabled={predict.isPending || !text.trim()}><Play />{t('models.widget.run')}</Button>
      {broken && <p role="alert" className="text-sm text-destructive">{t('models.widget.notJson')}</p>}
      {predict.isError && <p role="alert" className="text-sm text-destructive">{t(`models.widget.errors.${predictProblem(predict.error)}`)}</p>}
      {predict.data && (
        <div className="space-y-2 rounded-lg border p-3" aria-live="polite">
          <h3 className="text-sm font-medium">{t('models.widget.result')}</h3>
          <Output output={predict.data.output} kind={serving.output} />
          <p className="text-xs text-muted-foreground">{t('models.widget.took', { ms: predict.data.tookMs })}</p>
        </div>
      )}
    </div>
  )
}
