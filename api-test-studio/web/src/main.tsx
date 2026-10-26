import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from './lib/api';
import { AppShell } from './components/AppShell';
import { ToastProvider } from './components/ui';
import { LoginPage } from './pages/Login';
import { ProjectsPage } from './pages/Projects';
import { ProjectLayout } from './pages/ProjectLayout';
import { ConfigurationPage } from './pages/Configuration';
import { ApisPage } from './pages/Apis';
import { MembersPage } from './pages/Members';
import { ActivityPage } from './pages/Activity';
import { UnitCasesPage } from './pages/UnitCases';
import { UnitEndpointPage } from './pages/UnitEndpoint';
import { ScriptsPage } from './pages/Scripts';
import { FlowCasesPage } from './pages/FlowCases';
import { RoleCasesPage } from './pages/RoleCases';
import { RoleEndpointPage } from './pages/RoleEndpoint';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <ProjectsPage /> },
      {
        path: '/projects/:projectId',
        element: <ProjectLayout />,
        children: [
          { index: true, element: <ConfigurationPage /> },
          { path: 'apis', element: <ApisPage /> },
          { path: 'unit-cases', element: <UnitCasesPage /> },
          { path: 'unit-cases/:endpointId', element: <UnitEndpointPage /> },
          { path: 'flow-cases', element: <FlowCasesPage /> },
          { path: 'role-cases', element: <RoleCasesPage /> },
          { path: 'role-cases/:endpointId', element: <RoleEndpointPage /> },
          { path: 'scripts', element: <ScriptsPage /> },
          { path: 'framework', element: <Navigate to=".." relative="path" replace /> },
          { path: 'members', element: <MembersPage /> },
          { path: 'activity', element: <ActivityPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <LoginPage /> },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
