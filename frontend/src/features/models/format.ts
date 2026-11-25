import { formatSize } from '../datasets/format'

/** A size in bytes, the way the rest of the app writes sizes. */
export const formatBytes = (bytes: number) => formatSize(bytes / 1024 ** 2)

/** The files that were chosen, by the path they will have in the version (a folder keeps its tree). */
export const pathOf = (file: File) => (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
