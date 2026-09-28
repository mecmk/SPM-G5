export interface PaginationProps {
  /** 1-based. */
  page: number
  pageCount: number
  isDisabled?: boolean
  onChange: (page: number) => void
}

/** How many page numbers either side of the current one stay visible before collapsing to "…". */
const NEIGHBOURS = 1

/**
 * The page numbers to show: always the first and last, the current page and its neighbours, and
 * `null` for each run collapsed into "…". A gap of one page shows that page rather than "…".
 */
function visiblePages(page: number, pageCount: number): (number | null)[] {
  const wanted = new Set([1, pageCount])
  for (let near = page - NEIGHBOURS; near <= page + NEIGHBOURS; near += 1) {
    if (near >= 1 && near <= pageCount) wanted.add(near)
  }
  const shown: (number | null)[] = []
  let previous = 0
  for (const candidate of [...wanted].sort((a, b) => a - b)) {
    if (candidate - previous === 2) shown.push(candidate - 1)
    else if (candidate - previous > 2) shown.push(null)
    shown.push(candidate)
    previous = candidate
  }
  return shown
}

/** Story 13.1.2 AC4 - Previous, numbered pages and Next. The page owns which page is showing. */
export function Pagination({ page, pageCount, isDisabled = false, onChange }: PaginationProps) {
  return (
    <nav className="pagination" aria-label="Pages">
      <button
        type="button"
        className="secondary button-sm"
        disabled={isDisabled || page <= 1}
        onClick={() => onChange(page - 1)}
      >
        Previous
      </button>
      {visiblePages(page, pageCount).map((candidate, index) =>
        candidate === null ? (
          <span key={`gap-${index}`} className="muted" aria-hidden="true">
            …
          </span>
        ) : (
          <button
            key={candidate}
            type="button"
            className={candidate === page ? 'brand button-sm' : 'secondary button-sm'}
            aria-current={candidate === page ? 'page' : undefined}
            disabled={isDisabled}
            onClick={() => onChange(candidate)}
          >
            {candidate}
          </button>
        ),
      )}
      <button
        type="button"
        className="secondary button-sm"
        disabled={isDisabled || page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        Next
      </button>
    </nav>
  )
}
