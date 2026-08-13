import { Navigate, createBrowserRouter } from 'react-router-dom'
import { AccessPage } from '../pages/AccessPage'
import { CreationPage } from '../pages/CreationPage'
import { GenerationResultsPage } from '../pages/GenerationResultsPage'
import { SingleImageEditPage } from '../pages/SingleImageEditPage'
import { MyPlansTasksPage } from '../pages/MyPlansTasksPage'
import { TaskCenterPage } from '../pages/TaskCenterPage'
import { ModelConnectionsPage } from '../pages/ModelConnectionsPage'
import { BatchGenerationPolicyPage } from '../pages/BatchGenerationPolicyPage'
import { SingleEditPolicyPage } from '../pages/SingleEditPolicyPage'
import { ProtectedRoute } from '../components/ProtectedRoute'
import { AdminProtectedRoute } from '../components/AdminProtectedRoute'
import { AdminLoginPage } from '../pages/AdminLoginPage'
import { CustomerAccessPage } from '../pages/CustomerAccessPage'
import { NotificationConfigPage } from '../pages/NotificationConfigPage'

export const router = createBrowserRouter([
  { path: '/', element: <AccessPage /> },
  { path: '/access', element: <AccessPage /> },
  { path: '/create', element: <ProtectedRoute><CreationPage /></ProtectedRoute> },
  { path: '/results', element: <ProtectedRoute><GenerationResultsPage /></ProtectedRoute> },
  { path: '/edit/:versionId', element: <ProtectedRoute><SingleImageEditPage /></ProtectedRoute> },
  { path: '/my-plans', element: <ProtectedRoute><MyPlansTasksPage /></ProtectedRoute> },
  { path: '/my-plans/tasks/:taskId', element: <Navigate to="/my-plans" replace /> },
  { path: '/admin/login', element: <AdminLoginPage /> },
  { path: '/admin/tasks', element: <AdminProtectedRoute><TaskCenterPage /></AdminProtectedRoute> },
  { path: '/admin/customers', element: <AdminProtectedRoute><CustomerAccessPage /></AdminProtectedRoute> },
  { path: '/admin/notifications', element: <AdminProtectedRoute><NotificationConfigPage /></AdminProtectedRoute> },
  { path: '/admin/model-strategy', element: <Navigate to="/admin/model-strategy/models" replace /> },
  { path: '/admin/model-strategy/models', element: <AdminProtectedRoute><ModelConnectionsPage /></AdminProtectedRoute> },
  { path: '/admin/model-strategy/batch', element: <AdminProtectedRoute><BatchGenerationPolicyPage /></AdminProtectedRoute> },
  { path: '/admin/model-strategy/single-edit', element: <AdminProtectedRoute><SingleEditPolicyPage /></AdminProtectedRoute> },
], { basename: import.meta.env.BASE_URL.replace(/\/$/, '') || undefined })
