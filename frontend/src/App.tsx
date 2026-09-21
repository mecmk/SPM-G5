import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { LoginPage } from './auth/LoginPage'
import { PERMISSIONS } from './auth/permissions'
import { RequireAuth, RequirePermission } from './auth/RequireAuth'
import { BookingRequestDetailPage } from './bookings/BookingRequestDetailPage'
import { BookingRequestFormPage } from './bookings/BookingRequestFormPage'
import { BookingRequestsPage } from './bookings/BookingRequestsPage'
import { EventDetailPage } from './events/EventDetailPage'
import { EventRequestFormPage } from './events/EventRequestFormPage'
import { ReviewQueuePage } from './events/ReviewQueuePage'
import { AppLayout } from './layout/AppLayout'
import { NAV_ITEMS } from './layout/navigation'
import { NotificationProvider } from './notifications/NotificationProvider'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { ComponentGalleryPage } from './pages/ComponentGalleryPage'
import { HomePage } from './pages/HomePage'
import {
  BOOKING_REQUEST_PATH,
  BOOKING_REQUESTS_PATH,
  COMPONENT_GALLERY_PATH,
  BOOKING_REQUEST_NEW_PATH,
  EVENT_EDIT_PATH,
  EVENT_NEW_PATH,
  EVENT_PATH,
  EVENTS_INBOX_PATH,
  HOME_PATH,
  LOGIN_PATH,
  VENUE_CATALOGUE_PATH,
  VENUE_EDIT_PATH,
  VENUE_NEW_PATH,
  VENUE_PATH,
  VENUES_MANAGE_PATH,
} from './routes'
import { VenueCataloguePage } from './venues/VenueCataloguePage'
import { VenueDetailPage } from './venues/VenueDetailPage'
import { VenueFormPage } from './venues/VenueFormPage'
import { VenueManagePage } from './venues/VenueManagePage'
import './App.css'

/**
 * The route map. Signed-in pages sit inside <RequireAuth> and render within <AppLayout>
 * (story 1.1); a role-restricted page also sits inside <RequirePermission> for its permission
 * (story 1.2). Sections whose page is not built yet (NAV_ITEMS with isAvailable: false) get a
 * placeholder. The notification centre wraps the signed-in frame, so signing out clears it.
 * The story c3 component gallery stays reachable in development builds.
 */
function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path={LOGIN_PATH} element={<LoginPage />} />
          {import.meta.env.DEV && (
            <Route path={COMPONENT_GALLERY_PATH} element={<ComponentGalleryPage />} />
          )}
          <Route element={<RequireAuth />}>
            <Route
              element={
                <NotificationProvider>
                  <AppLayout />
                </NotificationProvider>
              }
            >
              <Route index element={<HomePage />} />

              {/* Story 8.1: venue catalogue, any internal role that can read venues. */}
              <Route element={<RequirePermission permission={PERMISSIONS.VENUES_READ} />}>
                <Route path={VENUE_CATALOGUE_PATH} element={<VenueCataloguePage />} />
                <Route path={VENUE_PATH} element={<VenueDetailPage />} />
              </Route>

              {/* Story 8.3: venue records, Venue Staff only. */}
              <Route element={<RequirePermission permission={PERMISSIONS.VENUES_MANAGE} />}>
                <Route path={VENUES_MANAGE_PATH} element={<VenueManagePage />} />
                <Route path={VENUE_NEW_PATH} element={<VenueFormPage key="new" />} />
                <Route path={VENUE_EDIT_PATH} element={<VenueFormPage key="edit" />} />
              </Route>

              {/* Story 2.1: raise and edit an event request, Event Organisers only. */}
              <Route element={<RequirePermission permission={PERMISSIONS.EVENTS_CREATE} />}>
                <Route path={EVENT_NEW_PATH} element={<EventRequestFormPage key="new" />} />
                <Route path={EVENT_EDIT_PATH} element={<EventRequestFormPage key="edit" />} />
              </Route>

              {/* Story 4.1: the coordinator review queue. */}
              {/* Story 12.1: the Event Coordinator raises a venue booking request. */}
              <Route element={<RequirePermission permission={PERMISSIONS.BOOKINGS_REQUEST} />}>
                <Route path={BOOKING_REQUEST_NEW_PATH} element={<BookingRequestFormPage />} />
              </Route>

              <Route element={<RequirePermission permission={PERMISSIONS.EVENTS_REVIEW} />}>
                <Route path={EVENTS_INBOX_PATH} element={<ReviewQueuePage />} />
              </Route>

              {/* Story 13.1: the venue staff booking requests queue. */}
              <Route element={<RequirePermission permission={PERMISSIONS.BOOKINGS_DECIDE} />}>
                <Route path={BOOKING_REQUESTS_PATH} element={<BookingRequestsPage />} />
                <Route path={BOOKING_REQUEST_PATH} element={<BookingRequestDetailPage />} />
              </Route>
              {/*
                Story 7.1: full event details. Which event a signed-in user may open is a
                per-record relationship (own event, or an internal role once submitted), not a
                single permission, so this sits behind RequireAuth only - the backend enforces
                AC2 by answering with a "not found" response either way.
              */}
              <Route path={EVENT_PATH} element={<EventDetailPage />} />

              {NAV_ITEMS.filter((item) => !item.isAvailable).map((item) => (
                <Route key={item.to} element={<RequirePermission permission={item.permission} />}>
                  <Route path={item.to} element={<ComingSoonPage item={item} />} />
                </Route>
              ))}
            </Route>
          </Route>
          <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
