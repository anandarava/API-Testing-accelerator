import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { api, type ActivityItem, type EndpointSummary, type FrameworkView, type HelperState, type Member, type ProjectCard, type FlowsOverview, type ProjectDetail, type RoleEndpointDetail, type RolesOverview, type ScriptDetail, type ScriptsOverview, type Spec, type UnitEndpointDetail, type UnitOverview, type User } from './api';

export const keys = {
  me: ['me'] as const,
  helper: ['helper'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  members: (id: string) => ['project', id, 'members'] as const,
  activity: (id: string) => ['project', id, 'activity'] as const,
  endpoints: (id: string) => ['project', id, 'endpoints'] as const,
  specs: (id: string) => ['project', id, 'specs'] as const,
  framework: (id: string) => ['project', id, 'framework'] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api.get<User>('/auth/me'), retry: false });

export const useHelper = () => useQuery({ queryKey: keys.helper, queryFn: () => api.get<HelperState>('/me/helper'), refetchInterval: 5000 });

export const useProjects = () => useQuery({ queryKey: keys.projects, queryFn: () => api.get<ProjectCard[]>('/projects') });

export function useProjectId(): string {
  return useParams().projectId ?? '';
}

export function useProject() {
  const id = useProjectId();
  return useQuery({ queryKey: keys.project(id), queryFn: () => api.get<ProjectDetail>(`/projects/${id}`), enabled: !!id });
}

export function useMembers() {
  const id = useProjectId();
  return useQuery({ queryKey: keys.members(id), queryFn: () => api.get<Member[]>(`/projects/${id}/members`) });
}

export function useActivity(limit = 100) {
  const id = useProjectId();
  return useQuery({ queryKey: [...keys.activity(id), limit], queryFn: () => api.get<ActivityItem[]>(`/projects/${id}/activity?limit=${limit}`) });
}

export function useEndpoints() {
  const id = useProjectId();
  return useQuery({ queryKey: keys.endpoints(id), queryFn: () => api.get<{ spec: Spec | null; endpoints: EndpointSummary[] }>(`/projects/${id}/endpoints`) });
}

export function useSpecs() {
  const id = useProjectId();
  return useQuery({ queryKey: keys.specs(id), queryFn: () => api.get<Spec[]>(`/projects/${id}/specs`) });
}

export function useFramework() {
  const id = useProjectId();
  return useQuery({
    queryKey: keys.framework(id),
    queryFn: () => api.get<FrameworkView>(`/projects/${id}/framework`),
    refetchInterval: (query) => {
      const status = query.state.data?.latestJob?.status;
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });
}

const jobActive = (status?: string) => status === 'queued' || status === 'running';

export function useUnitOverview() {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'unit'],
    queryFn: () => api.get<UnitOverview>(`/projects/${id}/unit/endpoints`),
    refetchInterval: (query) => (jobActive(query.state.data?.job?.status) ? 3000 : false),
  });
}

export function useRoles() {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'roles'],
    queryFn: () => api.get<RolesOverview>(`/projects/${id}/roles`),
    refetchInterval: (query) => (jobActive(query.state.data?.job?.status) || jobActive(query.state.data?.analyzeJob?.status) ? 3000 : false),
  });
}

export function useRoleEndpoint(endpointId: string, live: boolean) {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'roles', endpointId],
    queryFn: () => api.get<RoleEndpointDetail>(`/projects/${id}/roles/endpoints/${endpointId}`),
    refetchInterval: live ? 3000 : false,
  });
}

export function useUnitEndpoint(endpointId: string, live: boolean) {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'unit', endpointId],
    queryFn: () => api.get<UnitEndpointDetail>(`/projects/${id}/unit/endpoints/${endpointId}`),
    refetchInterval: (query) => (live || query.state.data?.regenerating.length ? 3000 : false),
  });
}

export { jobActive };

export function useScripts() {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'scripts'],
    queryFn: () => api.get<ScriptsOverview>(`/projects/${id}/scripts`),
    refetchInterval: (query) => (jobActive(query.state.data?.job?.status) ? 3000 : false),
  });
}

export function useScriptDetail(endpointId: string | null, kind: 'endpoint' | 'flow' | 'role' = 'endpoint') {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'scripts', kind, endpointId],
    queryFn: () => api.get<ScriptDetail>(`/projects/${id}/scripts/${kind === 'endpoint' ? '' : `${kind}/`}${endpointId}`),
    enabled: !!endpointId,
  });
}

export function useFlows() {
  const id = useProjectId();
  return useQuery({
    queryKey: ['project', id, 'flows'],
    queryFn: () => api.get<FlowsOverview>(`/projects/${id}/flows`),
    refetchInterval: (query) => (jobActive(query.state.data?.job?.status) || query.state.data?.regenerating.length ? 3000 : false),
  });
}
