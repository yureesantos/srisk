/* The evidence table. Every headline number in this report can be traced to a
 * table like this one — the table IS the audit trail, so it is built to be read
 * closely, not glanced at.
 *
 * What it does that a plain <table> doesn't:
 *  - numeric columns render in tabular figures and right-align, so magnitudes
 *    line up and the eye can scan a column for the outlier;
 *  - a row can be the active verify target, in which case it lights up (the
 *    `.is-verify-target` outline) when a finding elsewhere points at it;
 *  - the truncation footer states, in words, exactly which rows were dropped
 *    and how much stake they carried — a table that shows the top 30 of 900
 *    must say so, or it quietly lies by omission (DESIGN.md #1). */

import { useMemo, useState, type ReactNode } from 'react'
import { Search, ArrowUpDown } from 'lucide-react'
import type { Truncation } from '../lib/payload'
import { useVerify } from './verify'
import { int, moneyBlock } from '../lib/format'

export interface Column<Row> {
  key: string
  header: string
  /** Right-align + tabular figures for quantities; left for labels. */
  numeric?: boolean
  /** Cell renderer. Receives the row; returns pre-formatted content. */
  render: (row: Row) => ReactNode
  /** Optional fixed width hint (Tailwind class), e.g. 'w-40'. */
  width?: string
  /** Value used for client-side sort. Provide to make the column sortable. */
  sortValue?: (row: Row) => number | string
  /** Value used for the text filter (label match). Provide on the label col. */
  filterValue?: (row: Row) => string
}

interface TableProps<Row extends object> {
  /** The section id this table belongs to — the key verify refs point at. */
  sectionId: string
  columns: Column<Row>[]
  rows: Row[]
  /** Truncation metadata from the payload, rendered as an honest footer. */
  truncation?: Truncation | null
  /** Stable row key — a field name, or a function. */
  rowKey: (row: Row, index: number) => string
  /** Optional caption read by assistive tech. */
  caption?: string
  /** Show the filter box + sticky scroll region past this many rows. */
  denseAfter?: number
}

interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

export function Table<Row extends object>({
  sectionId,
  columns,
  rows,
  truncation,
  rowKey,
  caption,
  denseAfter = 30,
}: TableProps<Row>) {
  const { isTarget } = useVerify()
  const [sort, setSort] = useState<SortState | null>(null)
  const [query, setQuery] = useState('')

  const filterCol = columns.find((c) => c.filterValue)
  const isDense = rows.length > denseAfter

  // Filter (substring on the designated column), then sort (client-side
  // reorder of shipped rows — presentation, never a re-aggregation).
  const view = useMemo(() => {
    let out = rows
    if (filterCol && query.trim()) {
      const q = query.trim().toLowerCase()
      out = out.filter((r) => filterCol.filterValue!(r).toLowerCase().includes(q))
    }
    if (sort) {
      const col = columns.find((c) => c.key === sort.key)
      if (col?.sortValue) {
        const dir = sort.dir === 'asc' ? 1 : -1
        out = [...out].sort((a, b) => {
          const av = col.sortValue!(a)
          const bv = col.sortValue!(b)
          if (av < bv) return -1 * dir
          if (av > bv) return 1 * dir
          return 0
        })
      }
    }
    return out
  }, [rows, filterCol, query, sort, columns])

  const toggleSort = (key: string) =>
    setSort((s) =>
      s?.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'desc' },
    )

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      {isDense && filterCol && (
        <div className="flex items-center justify-between gap-3 border-b border-border bg-surface/70 px-3 py-2">
          <div className="relative flex items-center">
            <Search className="pointer-events-none absolute left-2 size-3.5 text-muted" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Filter ${filterCol.header.toLowerCase()}…`}
              className="h-7 w-56 rounded-md border border-border bg-raised pl-7 pr-2 text-[12px] text-ink placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <span className="tnum text-[11px] text-muted">
            {int(view.length)} of {int(rows.length)}
          </span>
        </div>
      )}
      <div className={isDense ? 'max-h-[440px] overflow-auto' : 'overflow-x-auto'}>
        <table className="w-full border-collapse text-[12px]">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="sticky top-0 z-[1]">
            <tr className="border-b border-border bg-raised">
              {columns.map((col) => {
                const sortable = !!col.sortValue
                const isSorted = sort?.key === col.key
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={
                      isSorted ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined
                    }
                    className={`
                      px-3 py-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-muted
                      ${col.numeric ? 'text-right' : 'text-left'}
                      ${col.width ?? ''}
                    `}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className={`inline-flex items-center gap-1 transition-colors hover:text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                          col.numeric ? 'flex-row-reverse' : ''
                        } ${isSorted ? 'text-ink2' : ''}`}
                      >
                        {col.header}
                        <ArrowUpDown
                          size={11}
                          className={isSorted ? 'text-bronze' : 'text-muted/60'}
                        />
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {view.map((row, i) => {
              const target = isTarget(sectionId, row as Record<string, unknown>)
              return (
                <tr
                  key={rowKey(row, i)}
                  className={`
                    border-b border-grid/60 last:border-b-0 transition-colors duration-150
                    ${target ? 'is-verify-target' : 'hover:bg-raised/40'}
                  `}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`
                        px-3 py-1.5 align-top
                        ${col.numeric ? 'tnum text-right text-ink' : 'text-ink2'}
                      `}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
          {truncation && <TruncationFooter t={truncation} span={columns.length} />}
        </table>
      </div>
    </div>
  )
}

/* States what was left out, so the visible rows never imply completeness they
 * don't have. Reads as prose, not a badge — the omission is information.
 *
 * The `omitted` detail block is optional in the payload: some tables ship the
 * counts only, others also describe the omitted range and its stake. Both must
 * render, so the count of omitted rows is derived from the totals when the
 * detail block is absent. */
function TruncationFooter({ t, span }: { t: Truncation; span: number }) {
  const omitted = t.omitted
  const omittedRows = omitted?.rows ?? t.total_rows - t.shipped_rows
  const rangeText =
    omitted?.range && omitted.described_by
      ? ` (${omitted.described_by} ${int(omitted.range[0])} to ${int(omitted.range[1])})`
      : ''
  const stakeText = omitted?.stake
    ? ` carrying ${moneyBlock(omitted.stake)} in stake`
    : ''

  return (
    <tfoot>
      <tr>
        <td
          colSpan={span}
          className="border-t border-grid bg-surface/40 px-3.5 py-2.5 text-[12px] leading-relaxed text-muted"
        >
          Showing the top{' '}
          <span className="tnum text-ink2">{int(t.shipped_rows)}</span> of{' '}
          <span className="tnum text-ink2">{int(t.total_rows)}</span> rows by{' '}
          {t.ranked_by}.{' '}
          <span className="tnum text-ink2">{int(omittedRows)}</span> rows omitted
          {rangeText}
          {stakeText}. Full table in <code className="text-ink2">{t.full_table}</code>.
        </td>
      </tr>
    </tfoot>
  )
}
