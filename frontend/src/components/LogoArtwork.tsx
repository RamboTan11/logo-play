interface LogoArtworkProps {
  variant: number
  domain: string
  compact?: boolean
}

const accents = ['#f7c65a', '#ff765f', '#c8ff38', '#78b4ff', '#e68ab3', '#c991ff']

export function LogoArtwork({ variant, domain, compact = false }: LogoArtworkProps) {
  const accent = accents[variant % accents.length]
  const wordmark = domain.split('.')[0]?.toUpperCase() || 'LOGO'

  return (
    <div className={`logo-artwork ${compact ? 'compact' : ''}`}>
      <svg viewBox="0 0 120 120" role="img" aria-label={`${wordmark} Logo 方案`}>
        <defs><linearGradient id={`mark-${variant}`} x1="0" y1="0" x2="1" y2="1"><stop stopColor={accent} /><stop offset="1" stopColor="#ff2d5b" /></linearGradient></defs>
        <path d={variant % 2 === 0 ? 'M60 10 108 60 60 110 12 60Z' : 'M22 22h76v76H22z'} fill={`url(#mark-${variant})`} opacity=".92" />
        <path d={variant % 3 === 0 ? 'M34 66 54 38l17 21 15-19' : 'M33 38h54v44H33z'} fill="none" stroke="#100608" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <strong>{wordmark}</strong>
    </div>
  )
}
