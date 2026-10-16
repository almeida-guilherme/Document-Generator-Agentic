// Typed calls to the FastAPI backend (web/). The session is an httpOnly cookie, so requests only need
// to be same-origin; nothing is stored in the browser by this code.

export type User = { id: number; email: string };

export type RunStatus = "queued" | "running" | "done" | "failed";

export type RunSummary = {
  steps: number | null;
  screenshots: number | null;
  cost_usd: number | null;
  applications: string[];
  recorded_seconds: number | null;
  warnings: string[];
  to_complete: number;
};

export type Run = {
  id: string;
  video_name: string;
  status: RunStatus;
  stage: string | null;
  message: string | null;
  error: string | null;
  process_name: string | null;
  template_name: string | null;
  stages: string[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: RunSummary | null;
};

export type Step = {
  number: number;
  time: string;
  instruction: string;
  short_label: string;
  application: string;
  decision: string;
  duration_seconds: number | null;
  image_url: string | null;
};

export type ProcessModel = {
  process_name: string;
  project_proposal: string;
  as_is: Step[];
  inputs: { name: string; kind: "structured" | "semi_structured" | "unstructured"; source: string }[];
  requirements: { category: string; description: string }[];
  business_exceptions: ExceptionItem[];
  system_exceptions: ExceptionItem[];
};

export type Template = { id: string; name: string; language: string; created_at: string };

export type TemplateAction = "keep" | "remove" | "write" | "table_rows" | "table_answers" | "diagram" | "steps";

export type TemplateDetail = Template & {
  missing_label: string;
  placeholders: { text: string; meaning: string }[];
  step_label: string;
  blocks: { index: number; kind: string; text: string; action: TemplateAction; purpose: string; reason: string }[];
};

export type ExceptionItem = { name: string; action: string; parameters: string; action_to_be_taken: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  return (response.status === 204 ? undefined : await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    // FastAPI validation errors are a list; show the first one's message.
    if (Array.isArray(body.detail)) return String(body.detail[0]?.msg ?? "Invalid input.").replace(/^Value error, /, "");
    if (body.detail) return String(body.detail);
  } catch {
    /* not JSON */
  }
  return `Request failed (${response.status}).`;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) => request<User>("/api/auth/login", json({ email, password })),
  register: (email: string, password: string) => request<User>("/api/auth/register", json({ email, password })),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  runs: () => request<Run[]>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  model: (id: string) => request<ProcessModel>(`/api/runs/${id}/model`),
  retry: (id: string) => request<Run>(`/api/runs/${id}/retry`, { method: "POST" }),
  remove: (id: string) => request<void>(`/api/runs/${id}`, { method: "DELETE" }),
  documentUrl: (id: string) => `/api/runs/${id}/document`,
  templates: () => request<Template[]>("/api/templates"),
  template: (id: string) => request<TemplateDetail>(`/api/templates/${id}`),
  removeTemplate: (id: string) => request<void>(`/api/templates/${id}`, { method: "DELETE" }),
  uploadTemplate: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<TemplateDetail>("/api/templates", { method: "POST", body: form });
  },
};

/** Uploads a recording with progress (fetch can't report upload progress, XMLHttpRequest can). */
export function uploadRecording(file: File, templateId: string | null, onProgress: (fraction: number) => void): Promise<Run> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/runs");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: { detail?: unknown } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status === 201) resolve(body as Run);
      else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : `Upload failed (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection and try again."));
    const form = new FormData();
    form.append("file", file);
    if (templateId) form.append("template_id", templateId);
    xhr.send(form);
  });
}
