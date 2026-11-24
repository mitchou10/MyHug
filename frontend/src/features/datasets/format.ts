export const formatCount = (n: number) => new Intl.NumberFormat('en', { notation: 'compact' }).format(n)
export const formatSize = (mb: number) => (mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : mb >= 1 ? `${Math.round(mb)} MB` : `${Math.round(mb * 1024)} kB`)
