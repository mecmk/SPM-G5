import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  fetchEquipmentType,
  type EquipmentTypePage as TypePageData,
  type OutOfServiceRecord,
} from '../api/equipment'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_CATALOGUE_PATH, EQUIPMENT_CATALOGUE_TITLE } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { OutOfServiceForm } from './OutOfServiceForm'
import { OutOfServiceRecords } from './OutOfServiceRecords'
import { useReloadAtNextChange } from './useReloadAtNextChange'
import { ErrorToast } from '../components/ErrorToast'

/** The type as last loaded, and when, which labels each record In force or Scheduled. */
interface LoadedType {
  page: TypePageData
  loadedAt: number
}

/** A loader for the type that is not the one before it, so the page loads the type again after
 *  each change to its records. */
function typeLoader(typeId: string): () => Promise<LoadedType> {
  return async () => ({ page: await fetchEquipmentType(typeId), loadedAt: Date.now() })
}

/**
 * Story 16.2 AC2 - one equipment type's page, for Technical Support, opened from the catalogue:
 * its stock, the units out of service now and where it is kept; its current records, each with
 * Edit and End; and the Out of service form (AC1, AC3, AC5), each the page's full width. After
 * each change the type is loaded again, so the figures and the list show what the server now
 * has, and, fix f16.2.5, as a record starts or ends, so the figures change at its time without a
 * refresh. A record ended or removed takes its edit with it (AC3: an ended record is not edited).
 * A back link returns to the catalogue. Keyed by the type in the address, so moving to another
 * type starts afresh.
 */
export function EquipmentTypePage() {
  const { typeId = '' } = useParams()
  return <EquipmentTypeView key={typeId} typeId={typeId} />
}

function EquipmentTypeView({ typeId }: { typeId: string }) {
  const [load, setLoad] = useState(() => typeLoader(typeId))
  const { data: loaded, error, isLoading } = useLoaded(load)
  const page = loaded?.page ?? null
  const [editing, setEditing] = useState<OutOfServiceRecord | null>(null)

  const loadAgain = useCallback(() => setLoad(() => typeLoader(typeId)), [typeId])
  useReloadAtNextChange(page?.records ?? null, loaded?.loadedAt ?? 0, loadAgain)

  function handleSaved() {
    setEditing(null)
    loadAgain()
  }

  function handleEdit(record: OutOfServiceRecord) {
    setEditing(record)
  }

  function handleCancelEdit() {
    setEditing(null)
  }

  function handleChanged(recordId: string) {
    if (editing?.id === recordId) setEditing(null)
    loadAgain()
  }

  return (
    <div className="page page-wide equipment-type">
      <Link to={EQUIPMENT_CATALOGUE_PATH} className="back-link">
        ← {EQUIPMENT_CATALOGUE_TITLE}
      </Link>

      {error && <ErrorToast message={error} />}
      {isLoading && <LoadingState label="Loading the equipment…" />}

      {loaded !== null && page !== null && (
        <>
          <PageHeader title={page.name} subtitle={page.description ?? undefined} />
          <p className="cluster equipment-type-facts">
            <span>{page.total_quantity} in stock</span>
            <span>{page.out_of_service_now} out of service now</span>
            {page.storage_location && <span>Kept in {page.storage_location}</span>}
          </p>
          <div className="stack">
            <OutOfServiceRecords
              typeId={typeId}
              typeName={page.name}
              records={page.records}
              loadedAt={loaded.loadedAt}
              onEdit={handleEdit}
              onChanged={handleChanged}
            />
            <OutOfServiceForm
              key={editing?.id ?? 'new'}
              typeId={typeId}
              typeName={page.name}
              editing={editing}
              onSaved={handleSaved}
              onCancel={handleCancelEdit}
            />
          </div>
        </>
      )}
    </div>
  )
}
