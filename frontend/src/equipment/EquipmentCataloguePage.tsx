import { Link } from 'react-router'
import { listEquipmentCatalogue, type OutOfServiceRecord } from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_CATALOGUE_TITLE, equipmentTypePath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { describeOutPeriod, describeUnitsOut, hasStarted } from './outOfServiceLabels'

/**
 * Story 16.2 AC2 - the equipment catalogue, for Technical Support: every active type, by name,
 * with its stock, the units out of service now and every period they are out - in force or
 * scheduled, from when to when - each opening the type's page. AC6: App.tsx
 * guards the route with equipment:manage, and the backend refuses everyone else. On a phone the
 * headers and names wrap (App.css), so the four columns fit and nothing scrolls sideways.
 */
async function loadCatalogue() {
  return { types: await listEquipmentCatalogue(), loadedAt: Date.now() }
}

/** One period a type's units are out: how many, In force or Scheduled by the page's clock when it
 *  loaded, and from when to when. */
function PeriodRow({ record, loadedAt }: { record: OutOfServiceRecord; loadedAt: number }) {
  const isInForce = hasStarted(record, loadedAt)
  return (
    <li>
      <strong>{describeUnitsOut(record.quantity)}</strong>{' '}
      <StatusBadge
        status={isInForce ? 'warning' : 'info'}
        label={isInForce ? 'In force' : 'Scheduled'}
      />
      <br />
      <span className="item-timing">{describeOutPeriod(record)}</span>
    </li>
  )
}

export function EquipmentCataloguePage() {
  const { data: loaded, error, isLoading } = useLoaded(loadCatalogue)
  const types = loaded?.types ?? null
  const loadedAt = loaded?.loadedAt ?? 0

  return (
    <div className="page page-wide">
      <p className="eyebrow">Equipment</p>
      <PageHeader
        title={EQUIPMENT_CATALOGUE_TITLE}
        subtitle="Each equipment type's stock, and how many units are out of service now."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the catalogue…" />}

      {types !== null && types.length === 0 && (
        <EmptyState>No equipment types are in use.</EmptyState>
      )}
      {types !== null && types.length > 0 && (
        <div className="table-wrap">
          <table aria-label="Equipment types" className="equipment-catalogue">
            <thead>
              <tr>
                <th>Equipment</th>
                <th>In stock</th>
                <th>Out of service now</th>
                <th>Out of service periods</th>
              </tr>
            </thead>
            <tbody>
              {types.map((kind) => (
                <tr key={kind.id}>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
