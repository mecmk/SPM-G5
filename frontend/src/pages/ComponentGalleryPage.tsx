import { useState } from 'react'
import { Calendar, type CalendarEntry, type CalendarLegendItem } from '../components/Calendar'
import { Chip } from '../components/Chip'
import { EmptyState } from '../components/EmptyState'
import { FilterPills } from '../components/FilterPills'
import { PageHeader } from '../components/PageHeader'
import { Sidebar, type SidebarNavItem } from '../components/Sidebar'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'

const SAMPLE_NAV_ITEMS: SidebarNavItem[] = [
  { label: 'My Events', href: '#my-events', group: 'Events', isActive: true },
  { label: 'New Event Request', href: '#new-event-request', group: 'Events' },
  { label: 'Venue Catalogue', href: '#venue-catalogue', group: 'Venues' },
  { label: 'Manage Venues', href: '#manage-venues', group: 'Venues' },
  { label: 'Components', href: '#components' },
]

const SAMPLE_CALENDAR_ENTRIES: CalendarEntry[] = [
  { id: 'b1', date: '2026-11-05', label: '09:00 Grand Hall', tone: 'danger' },
  { id: 'b2', date: '2026-11-12', label: '13:00 Seminar Room', tone: 'warning' },
  { id: 'b3', date: '2026-11-18', label: '10:00 Data Literacy', tone: 'info' },
  { id: 'b4', date: '2026-11-25', label: '09:00 Nimbus Conf', tone: 'success' },
]

const CALENDAR_LEGEND: CalendarLegendItem[] = [
  { tone: 'danger', label: 'Booked / Unavailable' },
  { tone: 'warning', label: 'Pending Booking' },
  { tone: 'info', label: 'Event Day' },
  { tone: 'success', label: 'Confirmed' },
]

const SAMPLE_STATUSES = [
  'DRAFT',
  'SUBMITTED',
  'UNDER_REVIEW',
  'APPROVED',
  'PLANNING',
  'CONFIRMED',
  'COMPLETED',
  'REJECTED',
  'CANCELLED',
  'PENDING',
  'PARTIALLY_RESERVED',
  'ACTIVE',
  'WITHDRAWN',
]

type GalleryTab = 'buttons' | 'calendar'

export interface ComponentGalleryPageProps {
  /** Result of the health check, shown so the scaffold's backend status line stays visible. */
  backendStatus: string
}

/**
 * Story c3 - development scratch page showing the shared components built for the Figma
 * prototype port, so each one has a consumer while real pages are still being built. Not part of
 * any acceptance criterion; delete once every component below has a real page to live on.
 */
export function ComponentGalleryPage({ backendStatus }: ComponentGalleryPageProps) {
  const [month, setMonth] = useState(new Date(2026, 10, 1))
  const [activeTab, setActiveTab] = useState<GalleryTab>('buttons')
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'confirmed'>('all')
  const [selectedDay, setSelectedDay] = useState<string | null>(null)

  // No-op: this page is a static demo, not a signed-in shell.
  function handleSignOut() {}

  return (
    <div className="app-shell">
      <Sidebar
        navItems={SAMPLE_NAV_ITEMS}
        userName="Dr. Priya Nair"
        userRole="Event Organiser"
        onSignOut={handleSignOut}
      />
      <main className="app-main">
        <div className="page">
          <PageHeader
            title="Component Gallery"
            subtitle={
              <>
                Shared building blocks for the ConnectSphere prototype ·{' '}
                <span className="mono">
                  Backend status: <strong>{backendStatus}</strong>
                </span>
              </>
            }
          />

          <Tabs
            tabs={[
              { key: 'buttons', label: 'Buttons, badges & filters' },
              { key: 'calendar', label: 'Calendar' },
            ]}
            activeKey={activeTab}
            onChange={setActiveTab}
          />

          {activeTab === 'buttons' && (
            <div className="stack">
              <section className="card stack">
                <div>
                  <p className="eyebrow">Buttons</p>
                  <div className="cluster">
                    <button type="button">Primary</button>
                    <button type="button" className="secondary">
                      Secondary
                    </button>
                    <button type="button" className="brand">
                      Brand
                    </button>
                    <button type="button" className="danger">
                      Danger
                    </button>
                    <button type="button" className="danger-solid">
                      Danger solid
                    </button>
                    <button type="button" className="ghost">
                      Ghost
                    </button>
                    <button type="button" className="link">
                      Link
                    </button>
                    <button type="button" disabled>
                      Disabled
                    </button>
                  </div>
                </div>
                <div>
                  <p className="eyebrow">Small</p>
                  <div className="cluster">
                    <button type="button" className="button-sm">
                      Primary
                    </button>
                    <button type="button" className="secondary button-sm">
                      Edit Info
                    </button>
                    <button type="button" className="brand button-sm">
                      Confirm Booking
                    </button>
                    <button type="button" className="danger button-sm">
                      Reject
                    </button>
                    <button type="button" className="ghost button-sm">
                      Cancel
                    </button>
                  </div>
                </div>
              </section>

              <section className="card">
                <p className="eyebrow">Status badges</p>
                <div className="cluster">
                  {SAMPLE_STATUSES.map((status) => (
                    <StatusBadge key={status} status={status} />
                  ))}
                </div>
              </section>

              <section className="card">
                <p className="eyebrow">Chips</p>
                <div className="cluster">
                  <Chip label="AV System" />
                  <Chip label="Live Streaming" />
                  <Chip label="Wheelchair Access" tone="success" />
                  <Chip label="Video Conferencing" tone="info" />
                  <Chip label="Limited" tone="warning" />
                  <Chip label="Unavailable" tone="danger" />
                </div>
              </section>

              <section className="card stack">
                <div>
                  <p className="eyebrow">Filter pills</p>
                  <FilterPills
                    options={[
                      { key: 'all', label: 'All' },
                      { key: 'pending', label: 'Pending' },
                      { key: 'confirmed', label: 'Confirmed' },
                    ]}
                    value={statusFilter}
                    onChange={setStatusFilter}
                  />
                </div>
                <div>
                  <p className="eyebrow">Empty state</p>
                  <EmptyState>No venues match your current filters.</EmptyState>
                </div>
              </section>
            </div>
          )}

          {activeTab === 'calendar' && (
            <section className="card">
              <p className="eyebrow">Availability calendar</p>
              {selectedDay && <p className="success">Selected {selectedDay}</p>}
              <Calendar
                month={month}
                onMonthChange={setMonth}
                entries={SAMPLE_CALENDAR_ENTRIES}
                onSelectDay={setSelectedDay}
                legend={CALENDAR_LEGEND}
              />
            </section>
          )}
        </div>
      </main>
    </div>
  )
}
