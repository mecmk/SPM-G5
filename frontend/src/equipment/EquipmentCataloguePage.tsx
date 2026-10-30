import { Link } from 'react-router'
import { listEquipmentCatalogue } from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { equipmentTypePath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { CATALOGUE_TITLE } from './outOfServiceLabels'

/**
 * Story 16.2 AC2 - the equipment catalogue, for Technical Support: every active type, by name,
 * with its stock and the units out of service now, each opening the type's page. AC6: App.tsx
 * guards the route with equipment:manage, and the backend refuses everyone else. On a phone the
 * table keeps its three narrow columns, so nothing scrolls sideways.
 */
export function EquipmentCataloguePage() {
  const { data: types, error, isLoading } = useLoaded(listEquipmentCatalogue)

  return (
    <div className="page page-wide">
      <p className="eyebrow">Equipment</p>
      <PageHeader
        title={CATALOGUE_TITLE}
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
