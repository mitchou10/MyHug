import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Dataset } from '../../mockData'

/** Mini histogram (numbers) or distinct count (text) shown under each column name. */
function ColumnStat({ values }: { values: (string | number)[] }) {
  if (typeof values[0] === 'string') return <span className="text-xs font-normal text-muted-foreground">{new Set(values).size} valeurs · string</span>
  const nums = values as number[]
  const min = Math.min(...nums), max = Math.max(...nums), bins = Array<number>(6).fill(0)
  nums.forEach((v) => bins[Math.min(5, Math.floor(((v - min) / (max - min || 1)) * 6))]++)
  return (
    <div>
      <div className="flex h-6 items-end gap-0.5">
        {bins.map((b, i) => <span key={i} className="w-3 rounded-t bg-primary/60" style={{ height: `${(b / Math.max(...bins)) * 100}%`, minHeight: 2 }} />)}
      </div>
      <span className="text-xs font-normal text-muted-foreground">{min} – {max}</span>
    </div>
  )
}

/** Tabular: a table whose headers carry the distribution of each column. */
export function TabularViewer({ dataset: d }: { dataset: Dataset }) {
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            {d.columns.map((c, j) => (
              <TableHead key={c} className="h-auto py-2 align-top">
                <div>{c}</div>
                <ColumnStat values={d.sample.map((r) => r[j])} />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {d.sample.map((row, i) => <TableRow key={i}>{row.map((cell, j) => <TableCell key={j}>{typeof cell === 'number' ? cell.toLocaleString() : cell}</TableCell>)}</TableRow>)}
        </TableBody>
      </Table>
    </div>
  )
}
