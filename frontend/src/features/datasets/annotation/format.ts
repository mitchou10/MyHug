import type { LabelDef } from './store'

export type ValueType = 'text' | 'date' | 'number' | 'identifier' | 'amount'
export const VALUE_TYPES: ValueType[] = ['text', 'date', 'number', 'identifier', 'amount']

/**
 * A format describes the normalized value of an entity, e.g. `YYYY-MM-DD` for a date or `DDDDDDD` for a 7-digit id.
 *  - dates: YYYY YY MM DD HH mm ss;
 *  - others: D = a digit, A = a letter, X = a letter or a digit, `+` after one of them = one or more; the rest is literal.
 */
export function formatToRegex(format: string, type: ValueType = 'text'): RegExp {
  let re = ''
  for (let i = 0; i < format.length; i++) {
    const rest = format.slice(i)
    if (type === 'date') {
      const m = /^(YYYY|YY|MM|DD|HH|mm|ss)/.exec(rest)
      if (m) { re += m[0] === 'YYYY' ? '\\d{4}' : '\\d{2}'; i += m[0].length - 1; continue }
    } else if ('DAX'.includes(format[i])) {
      re += format[i] === 'D' ? '\\d' : format[i] === 'A' ? '[A-Za-z]' : '[A-Za-z0-9]'
      if (format[i + 1] === '+') { re += '+'; i++ }
      continue
    }
    re += format[i].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${re}$`)
}

/** True when the value matches at least one of the formats of the label (or when it has none). */
export const matchesFormat = (value: string, l: LabelDef) => !l.formats?.length || l.formats.some((f) => formatToRegex(f, l.valueType).test(value.trim()))

/** Whether the annotator is asked for a normalized value next to the selected text. */
export const needsValue = (l?: LabelDef) => !!l && (!!l.formats?.length || (l.valueType ?? 'text') !== 'text')
