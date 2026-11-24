import type { TFunction } from 'i18next'
import type { Model } from './mockData'

/** The description of a model: what its author wrote, or the one of the models we know. */
export const describe = (m: Model, t: TFunction) => m.description ?? t(`datasets.annotation.pre.models.${m.name}`, { defaultValue: '' })

/** The title of the main task of a model, e.g. "Entity extraction". */
export const mainTask = (m: Model, t: TFunction) => (m.tasks[0] ? t(`datasets.annotation.tasks.${m.tasks[0]}.title`) : t('models.noTask'))
