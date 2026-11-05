import { useCallback, useMemo, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { listEquipmentCatalogue, type OutOfServiceRecord } from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import { Icon, type IconName } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_CATALOGUE_TITLE, equipmentTypePath } from '../routes'
import { isCardOpenClick } from '../shared/cardClick'
import { useLoaded } from '../shared/useLoaded'
import { ErrorToast } from '../components/ErrorToast'
import { describeOutRange, describeUnitsOut, hasStarted } from './outOfServiceLabels'
import { useReloadAtNextChange } from './useReloadAtNextChange'

async function loadCatalogue() {
  return { types: await listEquipmentCatalogue(), loadedAt: Date.now() }
}

/** A loader that is not the one before it, so the page loads the catalogue again. */
function freshLoader(): typeof loadCatalogue {
  return () => loadCatalogue()
}

function SummaryTile({ icon, value, label }: { icon: IconName; value: number; label: string }) {
  return (
    <div className="stat-card catalogue-tile">
      <Icon name={icon} size={20} />
      <p className="stat-card-value">{value}</p>
      <p className="fact-label">{label}</p>
    </div>
  )
}

/** One period a type's units are out: how many, from when to when, and In force or Scheduled by
 *  the page's clock when it loaded. */
function PeriodRow({ record, loadedAt }: { record: OutOfServiceRecord; loadedAt: number }) {
  const isInForce = hasStarted(record, loadedAt)
  return (
    <li>
      <strong className="period-units">{describeUnitsOut(record.quantity)}</strong>
      <span className="item-timing">
        <Icon name="calendar" size={14} /> {describeOutRange(record)}
      </span>
      <StatusBadge
        status={isInForce ? 'warning' : 'info'}
        label={isInForce ? 'In force' : 'Scheduled'}
      />
    </li>
  )
}

/**
 * Story 16.2 AC2 - the equipment catalogue, for Technical Support: totals across the types, then
 * every active type, by name, with its stock, the units out of service now and every period they
 * are out - in force or scheduled, from when to when - each opening the type's page. Fix f16.2.5:
 * the figures are read again as a record starts or ends, so a period scheduled for later takes
 * effect on the page without a refresh. AC6: App.tsx guards the route with equipment:manage, and the backend
 * refuses everyone else. On a phone the headers and names wrap (App.css), so the columns fit and
 * nothing scrolls sideways.
 */
export function EquipmentCataloguePage() {
  const [load, setLoad] = useState(() => loadCatalogue)
  const { data: loaded, error, isLoading } = useLoaded(load)
  const navigate = useNavigate()
  const types = loaded?.types ?? null
  const loadedAt = loaded?.loadedAt ?? 0
  const records = useMemo(() => types?.flatMap((kind) => kind.records) ?? null, [types])
  const loadAgain = useCallback(() => setLoad(freshLoader), [])
  useReloadAtNextChange(records, loadedAt, loadAgain)

  function handleRowClick(click: MouseEvent<HTMLTableRowElement>, typeId: string) {
    if (isCardOpenClick(click)) void navigate(equipmentTypePath(typeId))
  }

  return (
    <div className="page page-wide">
      <p className="eyebrow">Equipment</p>
      <PageHeader
        title={EQUIPMENT_CATALOGUE_TITLE}
        subtitle="Each equipment type's stock, and how many units are out of service now."
      />

      {error && <ErrorToast message={error} />}
      {isLoading && <LoadingState label="Loading the catalogue…" />}

      {types !== null && types.length === 0 && (
        <EmptyState>No equipment types are in use.</EmptyState>
      )}
      {types !== null && types.length > 0 && (
        <div className="stack">
          <section className="stat-card-grid" aria-label="Equipment summary">
            <SummaryTile icon="grid" value={types.length} label="Equipment types" />
            <SummaryTile
              icon="box"
              value={types.reduce((sum, kind) => sum + kind.total_quantity, 0)}
              label="Total units"
            />
            <SummaryTile
              icon="wrench"
              value={types.reduce((sum, kind) => sum + kind.out_of_service_now, 0)}
              label="Out of service now"
            />
            <SummaryTile
              icon="clock"
              value={types.reduce((sum, kind) => sum + kind.records.length, 0)}
              label="Out of service periods"
            />
          </section>

          <div className="table-wrap">
            <table aria-label="Equipment types" className="equipment-catalogue">
              <thead>
                <tr>
                  <th>Equipment</th>
                  <th>In stock</th>
                  <th>Out of service now</th>
                  <th>Out of service periods</th>
                  <th>
                    <span className="visually-hidden">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {types.map((kind) => (
                  <tr
                    key={kind.id}
                    className="catalogue-row"
                    onClick={(click) => handleRowClick(click, kind.id)}
                  >
                    <td>
                      <Link to={equipmentTypePath(kind.id)}>{kind.name}</Link>
                    </td>
                    <td className="mono">{kind.total_quantity}</td>
                    <td className="mono">{kind.out_of_service_now}</td>
                    <td>
                      {kind.records.length === 0 ? (
                        '—'
                      ) : (
                        <ul className="catalogue-periods">
                          {kind.records.map((record) => (
                            <PeriodRow key={record.id} record={record} loadedAt={loadedAt} />
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="catalogue-open">
                      <Link to={equipmentTypePath(kind.id)} tabIndex={-1} aria-hidden="true">
                        <Icon name="chevron-right" size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
