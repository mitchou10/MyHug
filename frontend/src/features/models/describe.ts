import type { TFunction } from 'i18next'
import type { Model } from './types'

/** The title of the main task of a model, e.g. "Entity extraction". */
export const mainTask = (m: Pick<Model, 'tasks'>, t: TFunction) => (m.tasks[0] ? t(`datasets.annotation.tasks.${m.tasks[0]}.title`) : t('models.noTask'))
