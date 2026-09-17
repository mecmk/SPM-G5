import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { LoginPage } from './auth/LoginPage'
import { RequireAuth, RequirePermission } from './auth/RequireAuth'
import { AppLayout } from './layout/AppLayout'
import { NAV_ITEMS } from './layout/navigation'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { ComponentGalleryPage } from './pages/ComponentGalleryPage'
import { HomePage } from './pages/HomePage'
import { COMPONENT_GALLERY_PATH, HOME_PATH, LOGIN_PATH } from './routes'
import './App.css'

/**
 * The route map. Signed-in pages sit inside <RequireAuth> and render within <AppLayout>
 * (story 1.1); a role-restricted page also sits inside <RequirePermission> for its permission
 * (story 1.2). Sections whose page is not built yet (NAV_ITEMS with isAvailable: false) get a
 * placeholder. The story c3 component gallery stays reachable in development builds.
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
            <Route element={<AppLayout />}>
              <Route index element={<HomePage />} />
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
