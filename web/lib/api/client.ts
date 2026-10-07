import type {
  AdapterInfo,
  AnnotatedVideoRead,
  PipelineDetail,
  PipelineSummary,
  RunDetail,
  RunSummary,
  ScheduleRead,
  StepRead,
  StepTypeRead,
  TemplateRead,
  VideoQuality,
  AssignableUser,
  CvRunDetail,
  CvRunKind,
  CvRunSummary,
  InteractionGraph,
  MovementClassRead,
  MovementEventDetail,
  MovementEventSummary,
  CheckRead,
  DatasetDetail,
  DatasetFacets,
  EventHistory,
  ExportRead,
  LineageGraph,
  SampleRead,
  VersionDetail,
  VersionSummary,
  ModelVersionRead,
  QueuePage,
  ReviewBatchRead,
  ReviewMetrics,
  ReviewRuleRead,
  ReviewSummary,
  AssignmentRead,
  DatasetSummary,
  DeviceSummary,
  GoogleConfig,
  AdminActivity,
  Limits,
  Requests,
  SignInRead,
  OperatorRead,
  OverviewResponse,
  Page,
  SessionDetail,
  SessionSummary,
  TokenResponse,
  UploadRead,
  UserRead,
  VideoDetail,
  VideoSummary,
} from "./types";

/**
 * Base URL of the FastAPI service, read at request time on the server (all API calls are server-side).
 * In Docker Compose this is `http://api:8000`; locally it defaults to `http://localhost:8000`.
 */
export function apiUrl(): string {
  return (process.env.API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

export type ApiError =
  | { ok: false; kind: "unreachable"; message: string }
  | { ok: false; kind: "http"; status: number; message: string; detail: unknown };

export type ApiResult<T> = { ok: true; data: T } | ApiError;

interface ApiRequest {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

/** FastAPI errors carry `detail`: a string, or a list of validation errors. */
export function errorMessage(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
    const msg = (first.msg ?? "Invalid value").replace(/^Value error, /, "");
    return field ? `${String(field)}: ${msg}` : msg;
  }
  return `Request failed (${status})`;
}

export async function apiFetch<T>(path: string, { method = "GET", body, token, timeoutMs = 5000, headers: extra }: ApiRequest = {}): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { ...extra, accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${apiUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    return { ok: false, kind: "unreachable", message: err instanceof Error ? err.message : String(err) };
  }

  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail ?? json;
    return { ok: false, kind: "http", status: res.status, message: errorMessage(res.status, detail), detail };
  }
  return { ok: true, data: json as T };
}

export const api = {
  googleConfig: () => apiFetch<GoogleConfig>("/api/v1/auth/google"),
  /** `client` is the browser's address and user agent, kept with the sign-in for the admin. */
  googleSignIn: (code: string, redirectUri: string, codeVerifier: string, client: Record<string, string> = {}) =>
    apiFetch<TokenResponse>("/api/v1/auth/google", {
      method: "POST",
      body: { code, redirect_uri: redirectUri, code_verifier: codeVerifier },
      headers: client,
    }),
  me: (token: string) => apiFetch<UserRead>("/api/v1/auth/me", { token }),
  overview: (token: string) => apiFetch<OverviewResponse>("/api/v1/overview", { token }),
  videos: (token: string, query: QueryParams = {}) => apiFetch<Page<VideoSummary>>(`/api/v1/videos${qs(query)}`, { token }),
  video: (token: string, id: string) => apiFetch<VideoDetail>(`/api/v1/videos/${encodeURIComponent(id)}`, { token }),
  sessions: (token: string, query: QueryParams = {}) =>
    apiFetch<Page<SessionSummary>>(`/api/v1/sessions${qs(query)}`, { token }),
  session: (token: string, id: string) => apiFetch<SessionDetail>(`/api/v1/sessions/${encodeURIComponent(id)}`, { token }),
  nextSessionName: (token: string, date?: string) =>
    apiFetch<{ name: string }>(`/api/v1/sessions/next-name${qs({ date })}`, { token }),
  devices: (token: string, query: QueryParams = {}) => apiFetch<Page<DeviceSummary>>(`/api/v1/devices${qs(query)}`, { token }),
  operators: (token: string) => apiFetch<Page<OperatorRead>>("/api/v1/operators?limit=500", { token }),
  datasets: (token: string) => apiFetch<Page<DatasetSummary>>("/api/v1/datasets?limit=200", { token }),
  uploads: (token: string, query: QueryParams = {}) => apiFetch<Page<UploadRead>>(`/api/v1/uploads${qs(query)}`, { token }),
  users: (token: string, query: QueryParams = {}) => apiFetch<Page<UserRead>>(`/api/v1/users${qs({ limit: 200, ...query })}`, { token }),
  signIns: (token: string, query: QueryParams = {}) => apiFetch<Page<SignInRead>>(`/api/v1/users/sign-ins${qs(query)}`, { token }),
  activity: (token: string, query: QueryParams = {}) => apiFetch<Page<AdminActivity>>(`/api/v1/users/activity${qs(query)}`, { token }),
  limits: (token: string) => apiFetch<Limits>("/api/v1/settings/limits", { token }),
  requests: (token: string) => apiFetch<Requests>("/api/v1/requests", { token }),
  assignments: (token: string, query: QueryParams = {}) =>
    apiFetch<Page<AssignmentRead>>(`/api/v1/assignments${qs(query)}`, { token }),
  assignableUsers: (token: string) => apiFetch<AssignableUser[]>("/api/v1/users/assignable", { token }),
  cvAdapter: (token: string, kind: CvRunKind = "hand_tracking") =>
    apiFetch<AdapterInfo>(`/api/v1/cv/adapters${qs({ kind })}`, { token }),
  cvRuns: (token: string, query: QueryParams = {}) => apiFetch<Page<CvRunSummary>>(`/api/v1/cv/runs${qs(query)}`, { token }),
  cvRun: (token: string, id: string) => apiFetch<CvRunDetail>(`/api/v1/cv/runs/${encodeURIComponent(id)}`, { token }),
  movementClasses: (token: string) => apiFetch<MovementClassRead[]>("/api/v1/movement/classes", { token }),
  movementEvents: (token: string, query: QueryParams = {}) =>
    apiFetch<Page<MovementEventSummary>>(`/api/v1/movement/events${qs(query)}`, { token }),
  movementEvent: (token: string, id: string) =>
    apiFetch<MovementEventDetail>(`/api/v1/movement/events/${encodeURIComponent(id)}`, { token }),
  movementGraph: (token: string, query: QueryParams) =>
    apiFetch<InteractionGraph>(`/api/v1/movement/graph${qs(query)}`, { token }),
  // Phase 5: review and active learning
  reviewQueue: (token: string, query: QueryParams = {}) => apiFetch<QueuePage>(`/api/v1/review/queue${qs(query)}`, { token }),
  reviewSummary: (token: string, query: QueryParams = {}) => apiFetch<ReviewSummary>(`/api/v1/review/summary${qs(query)}`, { token }),
  eventHistory: (token: string, id: string) => apiFetch<EventHistory>(`/api/v1/review/events/${encodeURIComponent(id)}/history`, { token }),
  reviewRules: (token: string) => apiFetch<ReviewRuleRead[]>("/api/v1/review/rules", { token }),
  reviewBatches: (token: string, query: QueryParams = {}) => apiFetch<Page<ReviewBatchRead>>(`/api/v1/review/batches${qs(query)}`, { token }),
  reviewMetrics: (token: string, query: QueryParams = {}) => apiFetch<ReviewMetrics>(`/api/v1/review/metrics${qs(query)}`, { token }),
  // Phase 6: datasets
  dataset: (token: string, id: string) => apiFetch<DatasetDetail>(`/api/v1/datasets/${encodeURIComponent(id)}`, { token }),
  datasetFacets: (token: string) => apiFetch<DatasetFacets>("/api/v1/datasets/facets", { token }),
  datasetVersions: (token: string, query: QueryParams = {}) => apiFetch<Page<VersionSummary>>(`/api/v1/datasets/versions${qs(query)}`, { token }),
  datasetVersion: (token: string, id: string) => apiFetch<VersionDetail>(`/api/v1/datasets/versions/${encodeURIComponent(id)}`, { token }),
  versionSamples: (token: string, id: string, query: QueryParams = {}) =>
    apiFetch<Page<SampleRead>>(`/api/v1/datasets/versions/${encodeURIComponent(id)}/samples${qs(query)}`, { token }),
  versionChecks: (token: string, id: string) => apiFetch<CheckRead[]>(`/api/v1/datasets/versions/${encodeURIComponent(id)}/checks`, { token }),
  datasetExports: (token: string, query: QueryParams = {}) => apiFetch<Page<ExportRead>>(`/api/v1/datasets/exports${qs(query)}`, { token }),
  datasetSample: (token: string, id: string) => apiFetch<SampleRead>(`/api/v1/datasets/samples/${encodeURIComponent(id)}`, { token }),
  sampleLineage: (token: string, id: string) => apiFetch<LineageGraph>(`/api/v1/datasets/samples/${encodeURIComponent(id)}/lineage`, { token }),
  modelVersions: (token: string, query: QueryParams = {}) => apiFetch<ModelVersionRead[]>(`/api/v1/review/model-versions${qs(query)}`, { token }),
  // Phase 7: pipelines
  pipelineSteps: (token: string) => apiFetch<StepTypeRead[]>("/api/v1/pipelines/steps", { token }),
  pipelineTemplates: (token: string) => apiFetch<TemplateRead[]>("/api/v1/pipelines/templates", { token }),
  pipelines: (token: string, query: QueryParams = {}) => apiFetch<Page<PipelineSummary>>(`/api/v1/pipelines${qs(query)}`, { token }),
  pipeline: (token: string, id: string) => apiFetch<PipelineDetail>(`/api/v1/pipelines/${encodeURIComponent(id)}`, { token }),
  pipelineRuns: (token: string, query: QueryParams = {}) => apiFetch<Page<RunSummary>>(`/api/v1/pipelines/runs${qs(query)}`, { token }),
  pipelineRun: (token: string, id: string) => apiFetch<RunDetail>(`/api/v1/pipelines/runs/${encodeURIComponent(id)}`, { token }),
  pipelineRunSteps: (token: string, id: string, query: QueryParams = {}) =>
    apiFetch<Page<StepRead>>(`/api/v1/pipelines/runs/${encodeURIComponent(id)}/steps${qs(query)}`, { token }),
  pipelineSchedules: (token: string, query: QueryParams = {}) => apiFetch<ScheduleRead[]>(`/api/v1/pipelines/schedules${qs(query)}`, { token }),
  videoQuality: (token: string, id: string) => apiFetch<VideoQuality>(`/api/v1/videos/${encodeURIComponent(id)}/quality`, { token }),
  annotatedVideos: (token: string, id: string) => apiFetch<AnnotatedVideoRead[]>(`/api/v1/videos/${encodeURIComponent(id)}/annotated`, { token }),
};

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** Build `?a=1&b=2`, dropping empty values. */
export function qs(query: QueryParams): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}
